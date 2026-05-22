output "selected_region" {
  description = "The OCI region selected for this Terraform run."
  value       = local.provider_region
}

output "resolved_compartments" {
  description = "Compartment name to OCID map resolved from config.compartments plus fleet.instances[*].compartment_id."
  value       = local.compartments
}

output "fleet_compartment_conflicts" {
  description = "Compartment names that had multiple different OCIDs in the fleet inventory."
  value       = local.fleet_compartment_conflicts
}

output "compartment_lookup_missing" {
  description = "Compartment names that could not be resolved by OCI lookup."
  value       = local.compartment_lookup_missing
}

output "compartment_lookup_conflicts" {
  description = "Compartment names that matched multiple active OCI compartments during lookup."
  value       = local.compartment_lookup_conflicts
}

output "managed_instance_group_ids" {
  description = "OS Management Hub managed instance group OCIDs created for the selected region."
  value       = { for key, group in oci_os_management_hub_managed_instance_group.this : key => group.id }
}

output "software_source_ids" {
  description = "OS Management Hub software source OCIDs created or looked up for the selected region."
  value       = local.software_source_ids_by_key
}

output "profile_ids" {
  description = "OS Management Hub registration profile OCIDs created for the selected region."
  value       = { for key, profile in oci_os_management_hub_profile.this : key => profile.id }
}

output "scheduled_job_ids" {
  description = "OS Management Hub scheduled job OCIDs created for the selected region."
  value       = { for key, job in oci_os_management_hub_scheduled_job.this : key => job.id }
}

output "fleet_registration_plan" {
  description = "Supported instances from the JSON fleet and the profile key they should use."
  value = {
    for instance in local.supported_region_instances : instance.display_name => {
      region      = instance.region
      compartment = try(instance.compartment_name, null)
      os_distro   = try(instance.os_distro, null)
      arch_type   = try(instance.osmh.arch_type, null)
      group_key   = try(instance.osmh.managed_instance_group_key, null)
      profile_key = try(instance.osmh.profile_key, null)
      profile_id  = try(oci_os_management_hub_profile.this[instance.osmh.profile_key].id, null)
    }
  }
}

output "unsupported_or_special_case_instances" {
  description = "Instances from the selected region that the config does not target with standard OSMH."
  value = {
    for instance in local.unsupported_region_instances : instance.display_name => {
      os_distro = try(instance.os_distro, null)
      reason    = try(instance.osmh.reason, "Not targeted by this OSMH config.")
    }
  }
}
