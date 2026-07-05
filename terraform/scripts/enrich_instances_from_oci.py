#!/usr/bin/env python3
"""Enrich a tenancy instances CSV with real OCI compartment/instance names,
VM OS (from image), VM status (lifecycle_state), and OSMH agent status.

This helper uses the Python OCI SDK (ComputeClient + IdentityClient), not the CLI.
It is read-only by default: resolves OCIDs in a tenancy/region and prints a rich
TSV showing generated CSV names beside real OCI values (including operating_system,
operating_system_version, agent_state). Tenancy-aware via freeform_tags.account
+ explicit --tenancy-name. Region-aware via OCID parsing + explicit --region.
Pass --in-place to update the CSV (creates timestamped backup in backup/).
No identity modifications. Enhanced to show VM OS/status/agent per feedback
(for apacanzset03child2 in Sydney/Melbourne).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import oci

OCID_REGION_MAP = {
    "iad": "us-ashburn-1",
}
INSTANCE_OCID_RE = re.compile(r"^ocid1\.instance\.oc1\.([^.]+)\.")


def infer_region_from_instance_id(instance_id: str) -> str:
    match = INSTANCE_OCID_RE.match(instance_id or "")
    if not match:
        return ""
    region = match.group(1)
    return OCID_REGION_MAP.get(region, region)


def load_oci_config(profile: str | None, config_file: str | None) -> dict[str, Any]:
    profile_name = profile or os.environ.get("OCI_CLI_PROFILE") or "DEFAULT"
    config_path = config_file or os.environ.get("OCI_CONFIG_FILE") or oci.config.DEFAULT_LOCATION
    try:
        config = oci.config.from_file(file_location=config_path, profile_name=profile_name)
    except Exception as exc:
        raise SystemExit(f"Could not load OCI config profile {profile_name!r} from {config_path}: {exc}") from exc
    return config


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def backup_csv(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = path.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.name}.{timestamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_account(row: dict[str, str]) -> str:
    raw = row.get("freeform_tags", "")
    if not raw:
        return ""
    try:
        tags = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    return str(tags.get("account", "")).strip()


def include_row(row: dict[str, str], tenancy_name: str, region: str) -> bool:
    account = row_account(row)
    if account and account != tenancy_name:
        return False
    instance_region = infer_region_from_instance_id(row.get("instance_id", ""))
    row_region = row.get("region", "").strip()
    return region in {row_region, instance_region}


def safe_str(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def get_instance(compute_client: oci.core.ComputeClient, instance_id: str) -> Any | None:
    try:
        return compute_client.get_instance(instance_id).data
    except oci.exceptions.ServiceError:
        return None


def get_compartment(
    identity_client: oci.identity.IdentityClient,
    compartment_id: str | None,
    cache: dict[str, Any | None],
) -> Any | None:
    if not compartment_id:
        return None
    if compartment_id not in cache:
        try:
            response = identity_client.get_compartment(compartment_id)
            cache[compartment_id] = response.data if response and hasattr(response, "data") else None
        except oci.exceptions.ServiceError:
            cache[compartment_id] = None
    return cache[compartment_id]


def get_image(
    compute_client: oci.core.ComputeClient,
    image_id: str | None,
    cache: dict[str, Any | None],
) -> Any | None:
    """Lookup image for operating_system / operating_system_version details."""
    if not image_id:
        return None
    if image_id not in cache:
        try:
            response = compute_client.get_image(image_id)
            cache[image_id] = response.data if response and hasattr(response, "data") else None
        except oci.exceptions.ServiceError:
            cache[image_id] = None
    return cache[image_id]


def get_agent_state(instance: Any | None) -> str:
    """Extract OS Management Hub agent plugin state (modeled after osmh_agent_scan.py)."""
    if not instance or not hasattr(instance, "agent_config") or not instance.agent_config:
        return "MISSING"
    config = instance.agent_config
    # Handle both SDK object attributes and potential dicts
    plugins_config = (
        getattr(config, "plugins_config", None)
        or getattr(config, "pluginsConfig", None)
        or []
    )
    if isinstance(plugins_config, (list, tuple)):
        for plugin in plugins_config:
            name = (
                getattr(plugin, "name", "")
                or (plugin.get("name") if isinstance(plugin, dict) else "")
            )
            if "OS Management Hub Agent" in str(name) or "os-management-hub" in str(name).lower():
                desired = (
                    getattr(plugin, "desired_state", None)
                    or getattr(plugin, "desiredState", None)
                    or (plugin.get("desired-state") if isinstance(plugin, dict) else None)
                )
                return str(desired or "UNKNOWN").upper()
    if getattr(config, "are_all_plugins_disabled", False) or getattr(
        config, "areAllPluginsDisabled", False
    ):
        return "ALL_DISABLED"
    return "DISABLED"


def planned_updates(
    row: dict[str, str],
    instance: Any | None,
    compartment: Any | None,
    image: Any | None,
    region: str,
) -> dict[str, str]:
    return {
        "display_name": safe_str(getattr(instance, "display_name", "")),
        "compartment_name": safe_str(getattr(compartment, "name", "")),
        "compartment_id": safe_str(getattr(instance, "compartment_id", "")) or row.get("compartment_id", ""),
        "region": region,
        "lifecycle_state": safe_str(getattr(instance, "lifecycle_state", "")),
        "shape": safe_str(getattr(instance, "shape", "")),
        "availability_domain": safe_str(getattr(instance, "availability_domain", "")),
        "time_created": safe_str(getattr(instance, "time_created", "")),
        "operating_system": safe_str(getattr(image, "operating_system", "")),
        "operating_system_version": safe_str(getattr(image, "operating_system_version", "")),
        "agent_state": get_agent_state(instance),
    }


def changed(old: str, new: str) -> bool:
    return bool(new) and old != new


def describe_changes(row: dict[str, str], updates: dict[str, str]) -> list[str]:
    changes: list[str] = []
    for field, new_value in updates.items():
        if field in row and changed(row.get(field, ""), new_value):
            changes.append(f"{field}:{row.get(field, '')}->{new_value}")
    return changes


def apply_updates(row: dict[str, str], updates: dict[str, str]) -> None:
    for field, new_value in updates.items():
        if field in row and changed(row.get(field, ""), new_value):
            row[field] = new_value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path, help="Tenancy instances CSV to inspect or update.")
    parser.add_argument("--tenancy-name", required=True, help="Tenancy/account name, e.g. apacanzset03child2.")
    parser.add_argument("--region", required=True, help="OCI region to inspect, e.g. ap-melbourne-1 or us-ashburn-1.")
    parser.add_argument("--profile", help="OCI config profile. Defaults to OCI_CLI_PROFILE or DEFAULT.")
    parser.add_argument("--config-file", help="OCI config file. Defaults to OCI_CONFIG_FILE or ~/.oci/config.")
    parser.add_argument("--in-place", action="store_true", help="Update the CSV in place with OCI names/metadata.")
    args = parser.parse_args()

    oci_config = load_oci_config(args.profile, args.config_file)
    oci_config["region"] = args.region
    compute_client = oci.core.ComputeClient(oci_config)
    identity_client = oci.identity.IdentityClient(oci_config)

    fieldnames, rows = load_rows(args.csv)
    compartment_cache: dict[str, Any | None] = {}
    image_cache: dict[str, Any | None] = {}

    print(
        "csv_compartment\tcsv_instance\toci_compartment\toci_instance\t"
        "vm_os\tvm_os_version\tagent_state\tregion\tlifecycle_state\tstatus\tchanges"
    )

    counts = {"checked": 0, "diffs": 0, "missing_instance_id": 0, "get_failed": 0}
    for row in rows:
        if not include_row(row, args.tenancy_name, args.region):
            continue

        instance_id = row.get("instance_id", "").strip()
        if not instance_id:
            counts["checked"] += 1
            counts["missing_instance_id"] += 1
            print("\t".join([row.get("compartment_name", ""), row.get("display_name", ""), "", "", "", "", "", args.region, "", "NO_INSTANCE_ID", ""]))
            continue

        instance_region = infer_region_from_instance_id(instance_id) or args.region
        if instance_region != args.region:
            continue

        counts["checked"] += 1
        instance = get_instance(compute_client, instance_id)
        if not instance:
            counts["get_failed"] += 1
            print(
                "\t".join(
                    [
                        row.get("compartment_name", ""),
                        row.get("display_name", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        args.region,
                        "",
                        "GET_FAILED",
                        "",
                    ]
                )
            )
            continue

        compartment = get_compartment(identity_client, getattr(instance, "compartment_id", None), compartment_cache)
        image = get_image(compute_client, getattr(instance, "image_id", None), image_cache)
        updates = planned_updates(row, instance, compartment, image, args.region)
        changes = describe_changes(row, updates)
        if changes:
            counts["diffs"] += 1
            if args.in_place:
                apply_updates(row, updates)

        status = ("UPDATED" if args.in_place else "DIFF") if changes else "OK"
        print(
            "\t".join(
                [
                    row.get("compartment_name", ""),
                    row.get("display_name", ""),
                    safe_str(getattr(compartment, "name", "")),
                    safe_str(getattr(instance, "display_name", "")),
                    safe_str(getattr(image, "operating_system", "")),
                    safe_str(getattr(image, "operating_system_version", "")),
                    get_agent_state(instance),
                    args.region,
                    safe_str(getattr(instance, "lifecycle_state", "")),
                    status,
                    ";".join(changes),
                ]
            )
        )

    backup_path = None
    if args.in_place:
        backup_path = backup_csv(args.csv)
        write_rows(args.csv, fieldnames, rows)

    print(
        f"Summary: tenancy={args.tenancy_name} region={args.region} checked={counts['checked']} "
        f"{'updated' if args.in_place else 'diffs'}={counts['diffs']} "
        f"missing_instance_id={counts['missing_instance_id']} get_failed={counts['get_failed']} "
        f"wrote={args.in_place} backup={backup_path or ''}"
    )


if __name__ == "__main__":
    main()
