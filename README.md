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
The committed CSV shape example is `terraform/config/template_instances.csv`.

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
    ├── config/template_instances.csv
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

1. Clone the repository and enter it:

```sh
git clone https://github.com/aszynkow/oci_os_hub.git
cd oci_os_hub
```

2. Export the OCI provider credentials so Terraform can authenticate. Use the
   secrets store / dotfile of your choice — the stack only needs these
   `TF_VAR_*` variables in your shell:

```sh
export TF_VAR_tenancy_ocid=ocid1.tenancy.oc1..xxxx
export TF_VAR_user_ocid=ocid1.user.oc1..xxxx
export TF_VAR_fingerprint=aa:bb:cc:dd:...
export TF_VAR_private_key_path=$HOME/.oci/oci_api_key.pem
export TF_VAR_region=ap-sydney-1
```

3. Export the OCI instance list to `terraform/config/instances.csv`. Use
   `terraform/config/template_instances.csv` as the column template if needed.
4. Generate your local config from the tracked template:

```sh
cd terraform
python3 scripts/csv_to_osmh_config.py config/instances.csv --template config/osmh_config.template.json --out config/osmh_config.json
```

5. Keep real values in `terraform/config/osmh_config.json` only. It is ignored
   by Git. Edit it locally if you need to adjust schedules, software sources,
   managed instance groups, or profiles.
6. Set the central OSMH resource compartment (`osmh_compartment_id`). Terraform
   blocks applies while this is a placeholder. Pick **one** of the following:

   - As an environment variable (matches the other `TF_VAR_*` exports above):

     ```sh
     export TF_VAR_osmh_compartment_id=ocid1.compartment.oc1..xxxx
     ```

   - As a `terraform.tfvars` file, if you don't already have one. Copy the
     tracked example and fill in real values:

     ```sh
     cd terraform
     cp terraform.tfvars.example terraform.tfvars
     # then edit terraform.tfvars and uncomment osmh_compartment_id
     ```

     `terraform.tfvars` is ignored by Git, so it is safe to keep real OCIDs in
     it locally.

   - Or pass it inline on every Terraform command:

     ```sh
     terraform apply -var='osmh_compartment_id=ocid1.compartment.oc1..xxxx' -var='region=ap-sydney-1'
     ```

7. Run one Terraform state per OCI region:

```sh
cd terraform
terraform init
terraform plan  -var='region=ap-sydney-1'
terraform apply -var='region=ap-sydney-1'
terraform apply -var='region=ap-melbourne-1' -var='enable_identity=false'
terraform apply -var='region=ap-tokyo-1'     -var='enable_identity=false'
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

The stack reads its OCI provider credentials from these `TF_VAR_*` environment
variables (see the Workflow section for example `export` commands):

- `TF_VAR_tenancy_ocid`
- `TF_VAR_region`
- `TF_VAR_user_ocid`
- `TF_VAR_fingerprint`
- `TF_VAR_private_key_path`

Any other `TF_VAR_*` values you export for unrelated stacks (Exadata, subnet,
SSH, admin password, etc.) are ignored by this Terraform.

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

The expected CSV columns are shown in
`terraform/config/template_instances.csv`. The real `config/instances.csv`
export is ignored by Git.

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
