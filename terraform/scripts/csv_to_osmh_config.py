#!/usr/bin/env python3
"""Populate OSMH config inventory from an OCI instance CSV export."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ARCH_KEY_NAMES = {
    "X86_64": "x86",
    "AARCH64": "aarch64",
}

REGION_KEY_NAMES = {
    "ap-sydney-1": "sydney",
    "ap-melbourne-1": "melbourne",
    "ap-tokyo-1": "tokyo",
    "us-ashburn-1": "us_ashburn_1",
}

REGION_DISPLAY_NAMES = {
    "ap-sydney-1": "Sydney",
    "ap-melbourne-1": "Melbourne",
    "ap-tokyo-1": "Tokyo",
    "us-ashburn-1": "Ashburn",
}

ARCH_DISPLAY_NAMES = {
    "X86_64": "x86_64",
    "AARCH64": "Arm",
}

ARCH_SOURCE_NAMES = {
    "X86_64": "x86_64",
    "AARCH64": "aarch64",
}

OS_FAMILY_NAMES = {
    8: "ORACLE_LINUX_8",
    9: "ORACLE_LINUX_9",
}


def infer_arch(shape: str) -> str:
    if ".A1." in shape or shape.endswith(".A1.Flex"):
        return "AARCH64"
    return "X86_64"


def infer_os_major(os_distro: str) -> int | None:
    distro = os_distro.lower()
    if "oracle linux 9" in distro:
        return 9
    if "oracle linux" in distro:
        return 8
    return None


def region_key_name(region: str) -> str:
    return REGION_KEY_NAMES.get(region, region.replace("-", "_"))


def region_display_name(region: str) -> str:
    return REGION_DISPLAY_NAMES.get(region, region_key_name(region).replace("_", " ").title())


def region_slug(region: str) -> str:
    return region_display_name(region).lower().replace(" ", "-")


def patch_group_key(os_major: int, arch_type: str, region: str) -> str:
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    return f"ol{os_major}_{arch_key}_{region_key_name(region)}"


def infer_osmh(display_name: str, os_distro: str, shape: str, region: str) -> dict:
    arch_type = infer_arch(shape)
    distro = os_distro.lower()

    if "rocky" in distro:
        return {
            "supported": False,
            "arch_type": arch_type,
            "reason": "Rocky Linux is not targeted by the standard OSMH Terraform config.",
        }

    if "autonomous" in distro:
        return {
            "supported": False,
            "arch_type": arch_type,
            "reason": "Autonomous Linux should be handled separately from standard OSMH groups.",
        }

    os_major = infer_os_major(os_distro)
    if os_major:
        group_key = patch_group_key(os_major, arch_type, region)
        return {
            "supported": True,
            "arch_type": arch_type,
            "managed_instance_group_key": group_key,
            "profile_key": f"{group_key}_profile",
        }

    return {
        "supported": False,
        "arch_type": arch_type,
        "reason": f"{display_name} has unsupported or unknown OS distro: {os_distro}",
    }


def clean_row(row: dict) -> dict:
    normalized = {key.strip(): (value or "").strip() for key, value in row.items()}
    region = normalized.get("region", "")
    display_name = normalized.get("display_name", "")
    shape = normalized.get("shape", "")
    os_distro = normalized.get("os_distro", "")

    instance = {
        "region": region,
        "display_name": display_name,
        "lifecycle_state": normalized.get("lifecycle_state", ""),
        "shape": shape,
        "os_distro": os_distro,
        "availability_domain": normalized.get("availability_domain", ""),
        "compartment_name": normalized.get("compartment_name", ""),
        "compartment_id": normalized.get("compartment_id", ""),
        "osmh": infer_osmh(display_name, os_distro, shape, region),
    }

    instance_id = normalized.get("id") or normalized.get("instance_id")
    if instance_id:
        instance["instance_id"] = instance_id

    return instance


def build_compartment_map(instances: list[dict]) -> dict:
    compartments = {}
    conflicts = {}

    for instance in instances:
        name = instance.get("compartment_name", "")
        compartment_id = instance.get("compartment_id", "")
        if not name or not compartment_id:
            continue

        existing = compartments.get(name)
        if existing and existing != compartment_id:
            conflicts.setdefault(name, sorted({existing, compartment_id}))
            continue

        compartments[name] = compartment_id

    if conflicts:
        conflict_names = ", ".join(sorted(conflicts))
        raise SystemExit(f"Compartment name maps to multiple IDs: {conflict_names}")

    return compartments


def software_source_key(os_major: int, arch_type: str, channel: str, region: str) -> str:
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    return f"ol{os_major}_{arch_key}_{channel}_{region_key_name(region)}"


def build_software_source(os_major: int, arch_type: str, channel: str, region: str) -> dict:
    source_arch = ARCH_SOURCE_NAMES.get(arch_type, arch_type.lower())
    source_key = software_source_key(os_major, arch_type, channel, region)
    region_suffix = region_slug(region)
    os_family = OS_FAMILY_NAMES[os_major]
    channel_display = "BaseOS latest" if channel == "baseos" else "AppStream"
    display_channel = "baseos-latest" if channel == "baseos" else "appstream"
    lookup_name = f"ol{os_major}_{'baseos_latest' if channel == 'baseos' else 'appstream'}-{source_arch}"

    return {
        "enabled": True,
        "region": region,
        "display_name": f"ol{os_major}-{ARCH_KEY_NAMES.get(arch_type, arch_type.lower())}-{display_channel}-{region_suffix}",
        "description": f"Oracle Linux {os_major} {channel_display} {source_arch} source for {region}.",
        "software_source_type": "VENDOR",
        "origin_lookup": {
            "display_name": lookup_name,
            "software_source_type": [
                "VENDOR",
            ],
            "os_family": [
                os_family,
            ],
            "arch_type": [
                arch_type,
            ],
            "vendor_name": "ORACLE",
        },
        "freeform_tags": {
            "source_key": source_key,
        },
    }


def build_managed_instance_group(os_major: int, arch_type: str, region: str) -> dict:
    group_key = patch_group_key(os_major, arch_type, region)
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    arch_display = ARCH_DISPLAY_NAMES.get(arch_type, arch_type)
    region_suffix = region_slug(region)
    source_keys = [
        software_source_key(os_major, arch_type, "baseos", region),
        software_source_key(os_major, arch_type, "appstream", region),
    ]

    return {
        "enabled": True,
        "region": region,
        "display_name": f"ol{os_major}-{arch_key}-{region_suffix}",
        "description": f"Oracle Linux {os_major} {arch_display} instances in {region}.",
        "arch_type": arch_type,
        "os_family": OS_FAMILY_NAMES[os_major],
        "vendor_name": "ORACLE",
        "location": "OCI_COMPUTE",
        "software_source_keys": source_keys,
        "managed_instance_ids": [],
        "freeform_tags": {
            "patch_group": group_key,
        },
    }


def build_profile(os_major: int, arch_type: str, region: str) -> dict:
    group_key = patch_group_key(os_major, arch_type, region)
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    arch_display = ARCH_DISPLAY_NAMES.get(arch_type, arch_type)
    region_name = region_display_name(region)
    region_suffix = region_slug(region)

    return {
        "enabled": True,
        "region": region,
        "display_name": f"ol{os_major}-{arch_key}-{region_suffix}-profile",
        "description": f"Registration profile for Oracle Linux {os_major} {arch_display} {region_name} patch group.",
        "profile_type": "GROUP",
        "managed_instance_group_key": group_key,
        "registration_type": "OCI_LINUX",
    }


def build_scheduled_job(os_major: int, arch_type: str, region: str) -> dict:
    group_key = patch_group_key(os_major, arch_type, region)
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    arch_display = ARCH_DISPLAY_NAMES.get(arch_type, arch_type)
    region_name = region_display_name(region)
    region_suffix = region_slug(region)

    return {
        "enabled": True,
        "region": region,
        "display_name": f"{region_suffix}-ol{os_major}-{arch_key}-weekly-dnf-upgrade",
        "description": f"Weekly all-package update for Oracle Linux {os_major} {arch_display} {region_name} instances.",
        "schedule_type": "RECURRING",
        "time_next_execution": "2026-06-06T17:30:00Z",
        "recurring_rule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=SA",
        "retry_intervals": [
            5,
            15,
            30,
        ],
        "operations": [
            {
                "operation_type": "UPDATE_ALL",
            },
        ],
        "target": {
            "managed_instance_group_keys": [
                group_key,
            ],
        },
    }


def supported_osmh_targets(instances: list[dict]) -> list[tuple[int, str, str]]:
    targets = set()
    for instance in instances:
        osmh = instance.get("osmh", {})
        if not osmh.get("supported"):
            continue

        os_major = infer_os_major(instance.get("os_distro", ""))
        arch_type = osmh.get("arch_type") or infer_arch(instance.get("shape", ""))
        region = instance.get("region", "")
        if os_major and arch_type and region:
            targets.add((os_major, arch_type, region))

    return sorted(targets, key=lambda item: (item[2], item[0], item[1]))


def ensure_osmh_definitions(config: dict, instances: list[dict]) -> None:
    osmh_config = config.setdefault("osmh", {})
    software_sources = osmh_config.setdefault("software_sources", {})
    managed_groups = osmh_config.setdefault("managed_instance_groups", {})
    profiles = osmh_config.setdefault("profiles", {})
    scheduled_jobs = osmh_config.setdefault("scheduled_jobs", {})

    for os_major, arch_type, region in supported_osmh_targets(instances):
        for channel in ("baseos", "appstream"):
            key = software_source_key(os_major, arch_type, channel, region)
            software_sources.setdefault(key, build_software_source(os_major, arch_type, channel, region))

        group_key = patch_group_key(os_major, arch_type, region)
        managed_groups.setdefault(group_key, build_managed_instance_group(os_major, arch_type, region))

        profile_key = f"{group_key}_profile"
        profiles.setdefault(profile_key, build_profile(os_major, arch_type, region))

        job_key = f"{region_key_name(region)}_ol{os_major}_{ARCH_KEY_NAMES.get(arch_type, arch_type.lower())}_weekly_upgrade"
        scheduled_jobs.setdefault(job_key, build_scheduled_job(os_major, arch_type, region))


def validate_osmh_references(config: dict, instances: list[dict]) -> None:
    osmh_config = config.get("osmh", {})
    software_sources = osmh_config.get("software_sources", {})
    managed_groups = osmh_config.get("managed_instance_groups", {})
    profiles = osmh_config.get("profiles", {})

    missing_groups = set()
    missing_profiles = set()
    missing_sources = set()

    for instance in instances:
        osmh = instance.get("osmh", {})
        if not osmh.get("supported"):
            continue

        group_key = osmh.get("managed_instance_group_key")
        profile_key = osmh.get("profile_key")

        if group_key not in managed_groups:
            missing_groups.add(group_key)
        else:
            for source_key in managed_groups[group_key].get("software_source_keys", []):
                if source_key not in software_sources:
                    missing_sources.add(source_key)

        if profile_key not in profiles:
            missing_profiles.add(profile_key)
        elif profiles[profile_key].get("managed_instance_group_key") not in managed_groups:
            missing_groups.add(profiles[profile_key].get("managed_instance_group_key"))

    errors = []
    if missing_groups:
        errors.append(f"managed instance groups: {', '.join(sorted(missing_groups))}")
    if missing_profiles:
        errors.append(f"profiles: {', '.join(sorted(missing_profiles))}")
    if missing_sources:
        errors.append(f"software sources: {', '.join(sorted(missing_sources))}")
    if errors:
        raise SystemExit("Missing OSMH config references for " + "; ".join(errors))


def merge_config(config_path: Path, instances: list[dict], compartments: dict) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["compartments"] = compartments
    config.setdefault("identity", {})["managed_compartment_names"] = list(compartments)
    config.setdefault("fleet", {})["instances"] = instances
    ensure_osmh_definitions(config, instances)
    validate_osmh_references(config, instances)
    return config


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        help="Populate a new osmh_config.json from this template.",
    )
    parser.add_argument(
        "--merge-config",
        type=Path,
        help="Merge CSV-derived compartments and fleet.instances into an existing osmh_config.json.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="When used with --merge-config, overwrite that config file instead of writing --out.",
    )
    args = parser.parse_args()

    with args.csv_file.open(newline="", encoding="utf-8-sig") as handle:
        instances = [clean_row(row) for row in csv.DictReader(handle)]

    compartments = build_compartment_map(instances)

    if args.template and args.merge_config:
        raise SystemExit("Use either --template or --merge-config, not both.")

    if args.template or args.merge_config:
        source_path = args.template or args.merge_config
        payload = merge_config(source_path, instances, compartments)
        if args.merge_config and args.in_place:
            output_path = args.merge_config
        else:
            output_path = args.out or Path("config/osmh_config.json")
        write_json(output_path, payload)
        print(
            f"Populated {len(instances)} instances and {len(compartments)} compartments into {output_path}"
        )
        return

    payload = {
        "compartments": compartments,
        "instances": instances,
    }
    output_path = args.out or Path("fleet_from_csv.json")
    write_json(output_path, payload)
    print(f"Wrote {len(instances)} instances to {output_path}")


if __name__ == "__main__":
    main()
