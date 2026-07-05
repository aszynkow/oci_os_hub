#!/usr/bin/env python3
"""Compare configured fleet instances with OSMH managed instances.

This is a read-only helper. It lists OSMH managed instances in configured
compartments for a region and reports which configured fleet rows are visible
to OS Management Hub.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

OCID_PATTERN = re.compile(r"^ocid1\.[a-z0-9]+\.oc1\.")


def run_oci(args: list[str], *, quiet: bool = False) -> dict[str, Any] | list[Any] | None:
    command = [os.environ.get("OCI_CLI", "oci"), *args, "--output", "json"]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        if quiet:
            return None
        raise SystemExit(
            f"OCI command failed: {' '.join(command)}\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    output = result.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OCI output was not valid JSON for {' '.join(command)}: {exc}") from exc


def load_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file is not valid JSON: {path}\n{exc}") from exc


def is_real_ocid(value: object) -> bool:
    return isinstance(value, str) and OCID_PATTERN.match(value) is not None and "replace_" not in value


def configured_compartments(config: dict[str, Any], region: str) -> dict[str, str]:
    compartments: dict[str, str] = {}

    osmh_compartment_id = config.get("osmh", {}).get("compartment_id")
    if is_real_ocid(osmh_compartment_id):
        compartments["osmh"] = osmh_compartment_id

    for name, compartment_id in config.get("compartments", {}).items():
        if is_real_ocid(compartment_id):
            compartments[name] = compartment_id

    for instance in config.get("fleet", {}).get("instances", []):
        if instance.get("region") != region:
            continue
        compartment_id = instance.get("compartment_id")
        if not is_real_ocid(compartment_id):
            continue
        name = instance.get("compartment_name") or f"fleet:{compartment_id[-8:]}"
        compartments.setdefault(name, compartment_id)

    return compartments


def fleet_instances(config: dict[str, Any], region: str, include_unsupported: bool) -> list[dict[str, Any]]:
    rows = []
    for instance in config.get("fleet", {}).get("instances", []):
        if instance.get("region") != region:
            continue
        if instance.get("lifecycle_state") != "RUNNING":
            continue
        if not include_unsupported and not instance.get("osmh", {}).get("supported", False):
            continue
        rows.append(instance)
    return rows


def list_managed_instances(region: str, compartment_id: str) -> list[dict[str, Any]]:
    response = run_oci(
        [
            "os-management-hub",
            "managed-instance",
            "list",
            "--region",
            region,
            "--compartment-id",
            compartment_id,
            "--all",
        ],
        quiet=True,
    )
    if not isinstance(response, dict):
        return []

    data = response.get("data", {})
    if isinstance(data, dict):
        items = data.get("items", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return items if isinstance(items, list) else []


def index_managed_instances(items: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_compartment_and_name: dict[tuple[str, str], dict[str, Any]] = {}

    for item in items:
        candidates = [
            item.get("id"),
            item.get("managed-instance-id"),
            item.get("compute-instance-id"),
            item.get("instance-id"),
            item.get("managedInstanceId"),
            item.get("computeInstanceId"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.startswith("ocid1.instance."):
                by_id[candidate] = item

        compartment_id = item.get("compartment-id") or item.get("compartmentId")
        display_name = item.get("display-name") or item.get("displayName")
        if compartment_id and display_name:
            by_compartment_and_name[(compartment_id, display_name)] = item

    return by_id, by_compartment_and_name


def field(item: dict[str, Any] | None, *names: str) -> str:
    if not item:
        return ""
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/osmh_config.json"))
    parser.add_argument("--region", required=True, help="OCI region to check, e.g. ap-sydney-1")
    parser.add_argument(
        "--include-unsupported",
        action="store_true",
        help="Include fleet rows marked osmh.supported=false.",
    )
    parser.add_argument(
        "--show-extra",
        action="store_true",
        help="Also print OSMH managed instances found in compartments but not in the config fleet.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    fleet = fleet_instances(config, args.region, args.include_unsupported)
    compartments = configured_compartments(config, args.region)
    if not compartments:
        raise SystemExit(f"No real compartment OCIDs found in {args.config}")

    managed: list[dict[str, Any]] = []
    seen_managed_ids: set[str] = set()
    for compartment_name, compartment_id in sorted(compartments.items()):
        items = list_managed_instances(args.region, compartment_id)
        for item in items:
            item_id = field(item, "id", "managed-instance-id", "managedInstanceId")
            if item_id and item_id in seen_managed_ids:
                continue
            if item_id:
                seen_managed_ids.add(item_id)
            item["_listed_compartment_name"] = compartment_name
            managed.append(item)

    by_id, by_compartment_and_name = index_managed_instances(managed)

    print(
        "display_name\tregion\tcompartment\tconfigured_instance_id\tstatus\t"
        "osmh_state\tgroup\tprofile\tmanaged_instance_id\tlast_checkin"
    )

    matched_managed_ids: set[str] = set()
    counts = {"registered": 0, "missing": 0, "unsupported": 0}
    for instance in fleet:
        name = instance.get("display_name", "")
        compartment_name = instance.get("compartment_name", "")
        compartment_id = instance.get("compartment_id", "")
        instance_id = instance.get("instance_id", "")
        supported = instance.get("osmh", {}).get("supported", False)

        item = by_id.get(instance_id) if instance_id else None
        if not item and compartment_id and name:
            item = by_compartment_and_name.get((compartment_id, name))

        if not supported:
            status = "UNSUPPORTED"
            counts["unsupported"] += 1
        elif item:
            status = "REGISTERED"
            counts["registered"] += 1
            managed_id = field(item, "id", "managed-instance-id", "managedInstanceId")
            if managed_id:
                matched_managed_ids.add(managed_id)
        else:
            status = "MISSING"
            counts["missing"] += 1

        print(
            "\t".join(
                [
                    str(name),
                    args.region,
                    str(compartment_name),
                    str(instance_id),
                    status,
                    field(item, "lifecycle-state", "status", "lifecycleState"),
                    field(item, "managed-instance-group-display-name", "managedInstanceGroupDisplayName", "group-name", "groupName"),
                    field(item, "profile-display-name", "profileDisplayName", "profile-name", "profileName"),
                    field(item, "id", "managed-instance-id", "managedInstanceId"),
                    field(item, "time-last-checkin", "timeLastCheckin", "last-checkin", "lastCheckin"),
                ]
            )
        )

    print(
        f"Summary: region={args.region} fleet={len(fleet)} "
        f"registered={counts['registered']} missing={counts['missing']} "
        f"unsupported={counts['unsupported']} managed_seen={len(managed)}"
    )

    if args.show_extra:
        extras = []
        for item in managed:
            managed_id = field(item, "id", "managed-instance-id", "managedInstanceId")
            if managed_id and managed_id in matched_managed_ids:
                continue
            extras.append(item)
        if extras:
            print("\nExtra OSMH managed instances not matched to config fleet:")
            print("display_name\tcompartment\tosmh_state\tmanaged_instance_id")
            for item in extras:
                print(
                    "\t".join(
                        [
                            field(item, "display-name", "displayName"),
                            field(item, "_listed_compartment_name", "compartment-name", "compartmentName"),
                            field(item, "lifecycle-state", "status", "lifecycleState"),
                            field(item, "id", "managed-instance-id", "managedInstanceId"),
                        ]
                    )
                )


if __name__ == "__main__":
    main()
