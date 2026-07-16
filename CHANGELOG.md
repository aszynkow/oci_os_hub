# Changelog

All notable changes to the OCI OS Management Hub Terraform automation are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses release versions for remote/public milestones.

## [1.0.1] - 2026-07-16

### Added - Terraform multi-tenancy workflow

- **Tenancy-specific inventory files.** Added support for generated `terraform/config/<tenancy>_instances.csv` files so each OCI tenancy can be processed independently while keeping generated inventory out of Git.
- **Tenancy-specific OSMH configs.** Added support for generated `terraform/config/<tenancy>_osmh_config.json` files, allowing each tenancy to carry its own compartments, fleet, identity mode, software sources, groups, profiles, and scheduled jobs.
- **Per tenancy-region Terraform workspace model.** Documented and supported the pattern of one workspace/state per tenancy-region, for example `apacanzset03child2-ap-melbourne-1`.
- **Agent-orchestrated onboarding path.** Added documentation for using the companion `agent_orchestrator` repo with the `oci-osmh-tenancy-onboarding` skill.

### Added - Helper scripts

- **`terraform/scripts/transform_anz_to_instances.py`.** Converts the multi-account ANZ cloud team CSV into tenancy-specific instance inventory, including region inference from instance OCIDs.
- **`terraform/scripts/source_oci_profile_tfvars.sh`.** Sources Terraform provider variables and `OCI_CLI_PROFILE` from an OCI CLI profile, with optional OSMH compartment override.
- **`terraform/scripts/enrich_instances_from_oci.py`.** Uses the Python OCI SDK to resolve real compartment names and instance display names from OCIDs before generating the OSMH config.
- **`terraform/scripts/osmh_managed_instance_status.py`.** Reports which configured instances are visible to OS Management Hub as managed instances.

### Changed - OSMH resources

- **Identity handling.** Added explicit existing-identity mode so Terraform can reuse an existing dynamic group and skip policy creation when onboarding later regions or tenancies with pre-existing IAM resources.
- **Regional OSMH definitions.** Extended regional software source, managed instance group, profile, and scheduled job handling, including support for Ashburn/IAD (`us-ashburn-1`) alongside Sydney and Melbourne.
- **Scheduled jobs.** Improved the workflow around checking running OSMH work requests, dry-running job execution, and running jobs by Terraform output key.

### Changed - Documentation

- **README rewrite.** Reworked the README in the same style as `oci_enterprise_ai_chat`, with front-loaded repository purpose, companion repo guidance, quick start, config/state table, tenancy onboarding workflow, identity mode, agent checks, scheduled jobs, common commands, and troubleshooting.
- **Generated-file guidance.** Clarified which inventory/config files are tracked templates and which tenancy-specific files remain local/untracked.

### Why this matters

The repository is now safer for repeated OSMH onboarding across multiple OCI tenancies and regions. The main operational risk was accidentally creating duplicate IAM resources, mixing regional state, or relying on generated aliases instead of real OCI names. The new workflow makes tenancy-region boundaries explicit, enriches inventory from OCI before config generation, and gives operators a clear path to reuse identity, check agents, verify OSMH registration, and run scheduled jobs.

## [1.0.0] - Initial release

- Initial Terraform automation for OCI OS Management Hub software sources, managed instance groups, registration profiles, scheduled jobs, IAM dynamic group, and policy.
- Initial CSV-to-config workflow using `terraform/config/osmh_config.template.json` and `terraform/config/template_instances.csv`.
- Initial helper scripts for agent scanning and scheduled job execution.
