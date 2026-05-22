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
}


def infer_arch(shape: str) -> str:
    if ".A1." in shape or shape.endswith(".A1.Flex"):
        return "AARCH64"
    return "X86_64"


def patch_group_key(os_major: int, arch_type: str, region: str) -> str:
    arch_key = ARCH_KEY_NAMES.get(arch_type, arch_type.lower())
    region_key = REGION_KEY_NAMES.get(region, region.replace("-", "_"))
    return f"ol{os_major}_{arch_key}_{region_key}"


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

    if "oracle linux 9" in distro:
        group_key = patch_group_key(9, arch_type, region)
        return {
            "supported": True,
            "arch_type": arch_type,
            "managed_instance_group_key": group_key,
            "profile_key": f"{group_key}_profile",
        }

    if "oracle linux" in distro:
        group_key = patch_group_key(8, arch_type, region)
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


def merge_config(config_path: Path, instances: list[dict], compartments: dict) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["compartments"] = compartments
    config.setdefault("identity", {})["managed_compartment_names"] = list(compartments)
    config.setdefault("fleet", {})["instances"] = instances
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
