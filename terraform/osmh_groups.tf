resource "oci_os_management_hub_managed_instance_group" "this" {
  for_each = local.managed_instance_groups

  depends_on = [
    oci_os_management_hub_software_source_change_availability_management.vendor_selected
  ]

  arch_type      = each.value.arch_type
  compartment_id = each.value.compartment_id
  display_name   = each.value.display_name
  os_family      = each.value.os_family
  vendor_name    = each.value.vendor_name

  description           = try(each.value.description, null)
  defined_tags          = try(each.value.defined_tags, null)
  freeform_tags         = each.value.freeform_tags
  location              = try(each.value.location, "OCI_COMPUTE")
  managed_instance_ids  = length(each.value.managed_instance_ids) > 0 ? each.value.managed_instance_ids : null
  notification_topic_id = try(each.value.notification_topic_id, null)
  software_source_ids   = length(each.value.software_source_ids) > 0 ? each.value.software_source_ids : null

  lifecycle {
    precondition {
      condition = try(
        length(regexall("replace_", each.value.compartment_id)) == 0 &&
        length(regexall("^ocid1\\.compartment\\.oc1\\.", each.value.compartment_id)) > 0,
        false
      )
      error_message = "Replace osmh.compartment_id or this managed instance group's compartment_id with a real compartment OCID."
    }

    precondition {
      condition     = length(setsubtract(toset(try(each.value.software_source_keys, [])), toset(keys(local.software_source_ids_by_key)))) == 0
      error_message = "One or more software_source_keys for this managed instance group do not match osmh.software_sources keys."
    }
  }

  dynamic "autonomous_settings" {
    for_each = try(each.value.autonomous_settings, null) == null ? [] : [each.value.autonomous_settings]

    content {
      is_data_collection_authorized = try(autonomous_settings.value.is_data_collection_authorized, null)
    }
  }
}
