resource "oci_os_management_hub_scheduled_job" "this" {
  for_each = local.scheduled_jobs

  compartment_id      = each.value.compartment_id
  schedule_type       = try(each.value.schedule_type, "RECURRING")
  time_next_execution = each.value.time_next_execution

  description                = try(each.value.description, null)
  display_name               = each.value.display_name
  defined_tags               = try(each.value.defined_tags, null)
  freeform_tags              = each.value.freeform_tags
  is_subcompartment_included = try(each.value.is_subcompartment_included, null)
  lifecycle_stage_ids        = length(try(each.value.target.lifecycle_stage_ids, [])) > 0 ? each.value.target.lifecycle_stage_ids : null
  locations                  = length(try(each.value.locations, [])) > 0 ? each.value.locations : null
  managed_compartment_ids    = length(try(each.value.target.managed_compartment_ids, [])) > 0 ? each.value.target.managed_compartment_ids : null
  managed_instance_group_ids = length(local.scheduled_job_managed_instance_group_ids[each.key]) > 0 ? local.scheduled_job_managed_instance_group_ids[each.key] : null
  managed_instance_ids       = length(try(each.value.target.managed_instance_ids, [])) > 0 ? each.value.target.managed_instance_ids : null
  recurring_rule             = try(each.value.recurring_rule, null)
  retry_intervals            = length(try(each.value.retry_intervals, [])) > 0 ? each.value.retry_intervals : null

  lifecycle {
    precondition {
      condition = try(
        length(regexall("replace_", each.value.compartment_id)) == 0 &&
        (
          length(regexall("^ocid1\\.compartment\\.oc1\\.", each.value.compartment_id)) > 0 ||
          length(regexall("^ocid1\\.tenancy\\.oc1\\.", each.value.compartment_id)) > 0
        ),
        false
      )
      error_message = "Replace osmh.compartment_id or this scheduled job's compartment_id with a real compartment or tenancy OCID."
    }

    precondition {
      condition = length(setsubtract(
        toset(distinct(flatten([
          for operation in each.value.operations : try(operation.software_source_keys, [])
        ]))),
        toset(keys(local.software_source_ids_by_key))
      )) == 0
      error_message = "One or more software_source_keys for this scheduled job do not match osmh.software_sources keys."
    }
  }

  dynamic "operations" {
    for_each = each.value.operations

    content {
      operation_type         = operations.value.operation_type
      package_names          = length(try(operations.value.package_names, [])) > 0 ? operations.value.package_names : null
      reboot_timeout_in_mins = try(operations.value.reboot_timeout_in_mins, null)
      software_source_ids    = length(try(operations.value.software_source_ids, [])) > 0 ? operations.value.software_source_ids : null
      windows_update_names   = length(try(operations.value.windows_update_names, [])) > 0 ? operations.value.windows_update_names : null
    }
  }
}
