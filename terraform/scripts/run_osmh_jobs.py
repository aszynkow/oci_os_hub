#!/usr/bin/env python3
"""Run OSMH scheduled jobs from Terraform output."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUNNING_WORK_REQUEST_STATUSES = ("WAITING", "ACCEPTED", "IN_PROGRESS")
OCID_PATTERN = re.compile(r"^ocid1\.[a-z0-9]+\.oc1\.")


def default_terraform_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def run_command(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def terraform_output(terraform_dir: Path, output_name: str) -> dict:
    result = run_command(
        ["terraform", "output", "-json", output_name],
        cwd=terraform_dir,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Could not read Terraform output {output_name!r} from {terraform_dir}.\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Terraform output {output_name!r} was not valid JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise SystemExit(f"Terraform output {output_name!r} must be a map of job names to OCIDs.")
    return value


def selected_region(terraform_dir: Path, explicit_region: str | None) -> str:
    if explicit_region:
        return explicit_region
    if os.environ.get("TF_VAR_region"):
        return os.environ["TF_VAR_region"]

    result = run_command(["terraform", "output", "-raw", "selected_region"], cwd=terraform_dir)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    return "ap-sydney-1"


def load_config(config_path: Path) -> dict:
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file is not valid JSON: {config_path}\n{exc}") from exc


def is_real_ocid(value: object) -> bool:
    return isinstance(value, str) and OCID_PATTERN.match(value) is not None and "replace_" not in value


def configured_compartments(config: dict) -> dict[str, str]:
    compartments: dict[str, str] = {}

    osmh_compartment_id = os.environ.get("TF_VAR_osmh_compartment_id") or config.get("osmh", {}).get(
        "compartment_id"
    )
    if is_real_ocid(osmh_compartment_id):
        compartments["osmh"] = osmh_compartment_id

    for name, compartment_id in config.get("compartments", {}).items():
        if is_real_ocid(compartment_id):
            compartments[name] = compartment_id

    for instance in config.get("fleet", {}).get("instances", []):
        compartment_id = instance.get("compartment_id")
        if not is_real_ocid(compartment_id):
            continue
        name = instance.get("compartment_name") or f"fleet:{compartment_id[-8:]}"
        compartments.setdefault(name, compartment_id)

    return compartments


def list_work_requests(region: str, compartment_id: str, status: str) -> list[dict]:
    result = run_command(
        [
            "oci",
            "os-management-hub",
            "work-request",
            "list",
            "--region",
            region,
            "--compartment-id",
            compartment_id,
            "--status",
            status,
            "--all",
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        print(
            f"  work-request list failed for {compartment_id} status={status}: "
            f"{result.stderr.strip() or result.stdout.strip()}",
            file=sys.stderr,
        )
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    data = payload.get("data", {})
    if isinstance(data, dict):
        return data.get("items", [])
    if isinstance(data, list):
        return data
    return []


def list_running_work_requests(region: str, config_path: Path) -> None:
    config = load_config(config_path)
    compartments = configured_compartments(config)
    if not compartments:
        raise SystemExit(f"No real compartment OCIDs found in {config_path}")

    seen = set()
    rows = []
    for compartment_name, compartment_id in sorted(compartments.items()):
        for status in RUNNING_WORK_REQUEST_STATUSES:
            for request in list_work_requests(region, compartment_id, status):
                request_id = request.get("id")
                if request_id in seen:
                    continue
                seen.add(request_id)
                rows.append(
                    {
                        "compartment": compartment_name,
                        "status": request.get("status", status),
                        "operation": request.get("operation-type", ""),
                        "display": request.get("display-name", ""),
                        "created": request.get("time-created", ""),
                        "id": request_id or "",
                    }
                )

    if not rows:
        print(
            "No OSMH work requests are currently WAITING, ACCEPTED, or IN_PROGRESS "
            f"across {len(compartments)} configured compartments."
        )
        return

    print("compartment\tstatus\toperation\tdisplay_name\ttime_created\twork_request_id")
    for row in rows:
        print(
            "\t".join(
                [
                    row["compartment"],
                    row["status"],
                    row["operation"],
                    row["display"],
                    row["created"],
                    row["id"],
                ]
            )
        )


def get_job(region: str, job_id: str) -> dict | None:
    result = run_command(
        [
            "oci",
            "os-management-hub",
            "scheduled-job",
            "get",
            "--region",
            region,
            "--scheduled-job-id",
            job_id,
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        print(f"  verify failed: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return payload.get("data")


def run_job(region: str, job_id: str) -> bool:
    result = run_command(
        [
            "oci",
            "os-management-hub",
            "scheduled-job",
            "run-now",
            "--region",
            region,
            "--scheduled-job-id",
            job_id,
            "--output",
            "json",
        ]
    )
    if result.returncode == 0:
        return True

    print(f"  run failed: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
    return False


def print_job_status(region: str, name: str, job_id: str) -> None:
    data = get_job(region, job_id)
    if not data:
        return
    display_name = data.get("display-name", name)
    state = data.get("lifecycle-state", "")
    last = data.get("time-last-execution", "")
    next_run = data.get("time-next-execution", "")
    print(f"  status: {display_name} state={state} last={last} next={next_run}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-dir", type=Path, default=default_terraform_dir())
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="OSMH JSON config. Defaults to <terraform-dir>/config/osmh_config.json.",
    )
    parser.add_argument("--region", help="OCI region. Defaults to TF_VAR_region or Terraform output.")
    parser.add_argument(
        "--list-running",
        action="store_true",
        help="List running OSMH work requests across compartments in the JSON config.",
    )
    parser.add_argument(
        "--job-key",
        action="append",
        help="Terraform scheduled_job_ids key to run. Repeat to run multiple jobs. Defaults to all.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print jobs without running them.")
    parser.add_argument("--no-verify", action="store_true", help="Skip status check after run.")
    args = parser.parse_args()

    terraform_dir = args.terraform_dir.resolve()
    config_path = args.config.resolve() if args.config else terraform_dir / "config/osmh_config.json"
    region = selected_region(terraform_dir, args.region)

    if args.list_running:
        list_running_work_requests(region, config_path)
        return

    jobs = terraform_output(terraform_dir, "scheduled_job_ids")

    if args.job_key:
        missing = [key for key in args.job_key if key not in jobs]
        if missing:
            raise SystemExit(f"Unknown job key(s): {', '.join(missing)}")
        jobs = {key: jobs[key] for key in args.job_key}

    jobs = {key: value for key, value in jobs.items() if value}
    if not jobs:
        raise SystemExit("No scheduled job OCIDs found in Terraform output scheduled_job_ids.")

    for name, job_id in jobs.items():
        print(f"Running {name}: {job_id}")
        if args.dry_run:
            continue
        if run_job(region, job_id) and not args.no_verify:
            print_job_status(region, name, job_id)


if __name__ == "__main__":
    main()
