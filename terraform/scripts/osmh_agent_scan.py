#!/usr/bin/env python3
"""Scan fleet instances and optionally enable the OS Management Hub agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_PLUGIN = "OS Management Hub Agent"


def run_oci(args: list[str], *, quiet: bool = False) -> dict | list | str | None:
    command = ["oci", *args, "--output", "json"]
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
    except json.JSONDecodeError:
        return output


def run_terraform_output(name: str) -> dict:
    result = subprocess.run(
        ["terraform", "output", "-json", name],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Could not read Terraform output {name!r}. Run from the terraform directory "
            "after applying the stack.\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return json.loads(result.stdout)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fleet_instances(config: dict, selected_region: str | None) -> list[dict]:
    instances = []
    for instance in config.get("fleet", {}).get("instances", []):
        if selected_region and instance.get("region") != selected_region:
            continue
        if instance.get("lifecycle_state") != "RUNNING":
            continue
        if not instance.get("osmh", {}).get("supported", False):
            continue
        instances.append(instance)
    return instances


def resolve_instance_id(instance: dict) -> str | None:
    if instance.get("instance_id"):
        return instance["instance_id"]

    compartment_id = instance.get("compartment_id")
    display_name = instance.get("display_name")
    region = instance.get("region")
    if not compartment_id or not display_name or not region:
        return None

    response = run_oci(
        [
            "compute",
            "instance",
            "list",
            "--region",
            region,
            "--compartment-id",
            compartment_id,
            "--display-name",
            display_name,
            "--lifecycle-state",
            "RUNNING",
            "--all",
        ],
        quiet=True,
    )
    items = response.get("data", []) if isinstance(response, dict) else []
    if len(items) != 1:
        return None
    return items[0]["id"]


def get_instance(region: str, instance_id: str) -> dict | None:
    response = run_oci(
        ["compute", "instance", "get", "--region", region, "--instance-id", instance_id],
        quiet=True,
    )
    if not isinstance(response, dict):
        return None
    return response.get("data")


def plugin_config(agent_config: dict, plugin_name: str) -> dict | None:
    for plugin in (agent_config or {}).get("plugins-config") or []:
        if plugin.get("name") == plugin_name:
            return plugin
    return None


def build_agent_config(agent_config: dict, plugin_name: str) -> dict:
    plugins = []
    found = False
    for plugin in (agent_config or {}).get("plugins-config") or []:
        item = {
            "name": plugin.get("name"),
            "desiredState": plugin.get("desired-state", "DISABLED"),
        }
        if item["name"] == plugin_name:
            item["desiredState"] = "ENABLED"
            found = True
        plugins.append(item)

    if not found:
        plugins.append({"name": plugin_name, "desiredState": "ENABLED"})

    return {
        "areAllPluginsDisabled": (agent_config or {}).get("are-all-plugins-disabled", False),
        "isManagementDisabled": (agent_config or {}).get("is-management-disabled", False),
        "isMonitoringDisabled": (agent_config or {}).get("is-monitoring-disabled", False),
        "pluginsConfig": plugins,
    }


def attach_profile(region: str, instance_id: str, profile_id: str) -> bool:
    result = subprocess.run(
        [
            "oci",
            "os-management-hub",
            "managed-instance",
            "attach-profile",
            "--region",
            region,
            "--managed-instance-id",
            instance_id,
            "--profile-id",
            profile_id,
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    print(
        f"  profile attach warning: {result.stderr.strip() or result.stdout.strip()}",
        file=sys.stderr,
    )
    return False


def enable_plugin(region: str, instance_id: str, agent_config: dict, plugin_name: str) -> bool:
    payload = build_agent_config(agent_config, plugin_name)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        payload_path = handle.name

    result = subprocess.run(
        [
            "oci",
            "compute",
            "instance",
            "update",
            "--region",
            region,
            "--instance-id",
            instance_id,
            "--agent-config",
            f"file://{payload_path}",
            "--force",
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    Path(payload_path).unlink(missing_ok=True)
    if result.returncode == 0:
        return True

    print(
        f"  plugin enable error: {result.stderr.strip() or result.stdout.strip()}",
        file=sys.stderr,
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/osmh_config.json"))
    parser.add_argument("--region", help="Only process instances in this OCI region.")
    parser.add_argument("--plugin", default=DEFAULT_PLUGIN)
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable the plugin when it is not already enabled.",
    )
    parser.add_argument(
        "--attach-profile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When --enable is used, attach the Terraform profile before enabling the plugin.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    selected_region = args.region or config.get("region") or config.get("home_region")
    profiles = run_terraform_output("profile_ids") if args.enable and args.attach_profile else {}

    rows = []
    for instance in fleet_instances(config, selected_region):
        name = instance.get("display_name", "")
        region = instance.get("region", selected_region)
        profile_key = instance.get("osmh", {}).get("profile_key")
        instance_id = resolve_instance_id(instance)
        if not instance_id:
            rows.append((name, region, "NO_INSTANCE_ID", "not changed"))
            continue

        compute_instance = get_instance(region, instance_id)
        if not compute_instance:
            rows.append((name, region, "GET_FAILED", "not changed"))
            continue

        agent_config = compute_instance.get("agent-config", {})
        plugin = plugin_config(agent_config, args.plugin)
        desired_state = plugin.get("desired-state", "MISSING") if plugin else "MISSING"
        action = "already enabled" if desired_state == "ENABLED" else "not changed"

        if args.enable and desired_state != "ENABLED":
            profile_id = profiles.get(profile_key)
            if args.attach_profile and profile_key and profile_id:
                attach_profile(region, instance_id, profile_id)
            elif args.attach_profile:
                print(f"  profile attach warning: no profile id for {profile_key}", file=sys.stderr)

            if enable_plugin(region, instance_id, agent_config, args.plugin):
                action = "enabled"
            else:
                action = "enable failed"

        rows.append((name, region, desired_state, action))

    print("display_name\tregion\tplugin_state\taction")
    for row in rows:
        print("\t".join(row))


if __name__ == "__main__":
    main()
