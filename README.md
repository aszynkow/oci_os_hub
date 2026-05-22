# OCI OS Management Hub Terraform

Terraform to bootstrap OCI OS Management Hub for Linux patching. The Terraform
stack lives under `terraform/` and reads a local generated config at
`terraform/config/osmh_config.json`. It creates:

- IAM dynamic group and policy for OSMH-managed OCI instances.
- OS Management Hub software sources.
- OS Management Hub managed instance groups.
- OS Management Hub registration profiles.
- OS Management Hub scheduled jobs, for example `UPDATE_ALL`, which is the
  OSMH equivalent of fleet `dnf upgrade`.

The committed template is `terraform/config/osmh_config.template.json`. Keep
real inventory and OCIDs in the generated local file
`terraform/config/osmh_config.json`, which is ignored by Git.

Terraform now blocks applies when placeholder OCIDs remain. Pass the central
OSMH resource compartment with `-var='osmh_compartment_id=<compartment_ocid>'`
or `TF_VAR_osmh_compartment_id`. Workload compartment OCIDs can come from the
CSV/fleet inventory `compartment_id` column. The CSV helper populates the
`compartments` map, `identity.managed_compartment_names`, and `fleet.instances`
from the CSV. If the CSV/fleet value is missing, Terraform attempts to look up
each `identity.managed_compartment_names` entry by compartment name across the
tenancy.

## Layout

```text
.
├── LICENSE
├── README.md
└── terraform
    ├── config/osmh_config.template.json
    ├── identity.tf
    ├── locals.tf
    ├── osmh_groups.tf
    ├── osmh_profiles.tf
    ├── osmh_scheduled_jobs.tf
    ├── outputs.tf
    ├── provider.tf
    ├── software_sources.tf
    ├── scripts/csv_to_osmh_config.py
    ├── terraform.tfvars.example
    ├── variables.tf
    └── versions.tf
```

## Workflow

1. Export the OCI instance list to `terraform/config/instances.csv`.
2. Generate your local config from the tracked template:

```sh
cd terraform
python3 scripts/csv_to_osmh_config.py config/instances.csv --template config/osmh_config.template.json --out config/osmh_config.json
```

3. Keep real values in `terraform/config/osmh_config.json` only. It is ignored
   by Git. Edit it locally if you need to adjust schedules, software sources,
   managed instance groups, or profiles.
4. Run one Terraform state per OCI region:

```sh
source /Users/aszynkow/Documents/codex_project/repos/export_tfvars.sh
cd terraform
terraform init
terraform plan -var='region=ap-sydney-1'
terraform apply -var='region=ap-sydney-1'
terraform apply -var='region=ap-melbourne-1' -var='enable_identity=false'
terraform apply -var='region=ap-tokyo-1' -var='enable_identity=false'
```

Use separate Resource Manager stacks, workspaces, or state backends per region.
Do not switch `region` inside the same state unless you intend Terraform to
replace the region-filtered OSMH resources in that state.

## Software Sources

By default, the stack uses `osmh.software_sources` in
`terraform/config/osmh_config.json` to resolve source IDs:

```hcl
enable_source_creation = true
```

Entries with `software_source_type = "VENDOR"` are Oracle-provided sources, so
Terraform looks them up and attaches their IDs. Non-vendor entries are created
when source creation is enabled.

For vendor sources, Terraform also asserts `availability_at_oci = "SELECTED"`
before creating managed instance groups. This handles regions where the vendor
source exists but has not yet been selected for the tenancy.

Each managed instance group uses `software_source_keys` to reference those
sources. For example, the Sydney Oracle Linux 8 group references:

```json
"software_source_keys": [
  "ol8_x86_baseos_sydney",
  "ol8_x86_appstream_sydney"
]
```

If software sources already exist and you only want Terraform to look them up,
set:

```hcl
enable_source_creation = false
```

In lookup mode, Terraform uses each source's `lookup` block if present, or falls
back to the source `display_name`, `compartment_id`, and `software_source_type`.

## Running Scheduled Jobs

After Terraform creates the scheduled jobs, trigger all jobs for the selected
region with:

```sh
cd terraform
python3 scripts/run_osmh_jobs.py --region ap-sydney-1
```

Preview the jobs without running them:

```sh
python3 scripts/run_osmh_jobs.py --region ap-sydney-1 --dry-run
```

Run one job by Terraform output key:

```sh
python3 scripts/run_osmh_jobs.py --region ap-sydney-1 --job-key sydney_ol8_x86_weekly_upgrade
```

Check for currently running OSMH work requests across all compartments in
`config/osmh_config.json`:

```sh
python3 scripts/run_osmh_jobs.py --region ap-sydney-1 --list-running
```

## Partial Apply Recovery

If an early apply created IAM resources before failing on OSMH resources, do not
delete the state. Replace the placeholder compartment IDs, then run apply again.
Terraform will update the dynamic group matching rule and continue creating the
OSMH resources.

Check what was created:

```sh
cd terraform
terraform state list
```

At minimum, these values must be real OCIDs before apply:

- `osmh.compartment_id`, `TF_VAR_osmh_compartment_id`, or
  `-var='osmh_compartment_id=<compartment_ocid>'`
- every fleet `compartment_id` used to build the dynamic group matching rule

The top-level `compartments` map is optional when `fleet.instances` contains
real `compartment_name` and `compartment_id` values from the CSV. If both the
top-level map and fleet IDs are missing, Terraform will try an OCI compartment
lookup by name. If names are duplicated in the tenancy, provide the exact OCID
in `compartments` or in the fleet CSV.

## Existing Instances

For existing OCI instances:

1. Confirm Oracle Cloud Agent is installed and at least version `1.40`.
2. Enable the `OS Management Hub Agent` plugin.
3. Select the matching profile created by this Terraform.

You can scan the JSON fleet and optionally enable the plugin with:

```sh
cd terraform
python3 scripts/osmh_agent_scan.py --region ap-sydney-1
```

The scan reads `config/osmh_config.json`, resolves missing compute instance
OCIDs by `display_name` and `compartment_id`, and reports the Oracle Cloud
Agent plugin state. To attach the matching Terraform-created OSMH profile and
enable the plugin where needed:

```sh
cd terraform
python3 scripts/osmh_agent_scan.py --region ap-sydney-1 --enable
```

After enabling, wait a few minutes and rerun the scan. Registered instances
should then appear in OS Management Hub and in the target managed instance
groups.

For new instances, OCI also supports assigning a profile with the free-form tag:

```text
OsmhProfile = <profile_ocid>
```

The `profile_ids` output gives the values to use.

## Environment Variables

The stack accepts these variables from your existing `export_tfvars.sh` script:

- `TF_VAR_tenancy_ocid`
- `TF_VAR_region`
- `TF_VAR_user_ocid`
- `TF_VAR_fingerprint`
- `TF_VAR_private_key_path`

The script also exports variables for other repos, such as Exadata, subnet, SSH,
and admin password values. This Terraform stack ignores those.

## Unsupported Instances From The Attachment

The config marks unsupported or special cases in `fleet.instances[*].osmh`:

- `k8sworker2` is Rocky Linux 8. Use Ansible or OCI Run Command for that host.
- `ragllm` is Oracle Autonomous Linux. Treat it separately from standard OSMH
  groups unless you intentionally configure Autonomous Linux resources.

## CSV Conversion Helper

If you export the OCI instance list as CSV, generate the local config from the
tracked template:

```sh
cd terraform
python3 scripts/csv_to_osmh_config.py config/instances.csv --template config/osmh_config.template.json --out config/osmh_config.json
```

This populates:

- `compartments`
- `identity.managed_compartment_names`
- `fleet.instances`

with values from the CSV, including real `compartment_id` values. To refresh an
existing local config while keeping its non-inventory settings:

```sh
python3 scripts/csv_to_osmh_config.py config/instances.csv --merge-config config/osmh_config.json --in-place
```

To generate a standalone inventory JSON file instead, omit `--template` and
`--merge-config`:

```sh
python3 scripts/csv_to_osmh_config.py config/instances.csv --out fleet_from_csv.json
```
