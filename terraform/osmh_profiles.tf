resource "oci_os_management_hub_profile" "this" {
  for_each = local.profiles

  compartment_id = each.value.compartment_id
  display_name   = each.value.display_name
  profile_type   = each.value.profile_type

  arch_type          = try(each.value.arch_type, null)
  description        = try(each.value.description, null)
  defined_tags       = try(each.value.defined_tags, null)
  freeform_tags      = each.value.freeform_tags
  is_default_profile = try(each.value.is_default_profile, null)
  lifecycle_stage_id = try(each.value.lifecycle_stage_id, null)
  managed_instance_group_id = try(coalesce(
    try(each.value.managed_instance_group_id, null),
    try(oci_os_management_hub_managed_instance_group.this[each.value.managed_instance_group_key].id, null)
  ), null)
  management_station_id = try(each.value.management_station_id, null)
  os_family             = try(each.value.os_family, null)
  registration_type     = try(each.value.registration_type, null)
  software_source_ids   = length(try(each.value.software_source_ids, [])) > 0 ? each.value.software_source_ids : null
  vendor_name           = try(each.value.vendor_name, null)

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
      error_message = "Replace osmh.compartment_id or this profile's compartment_id with a real compartment or tenancy OCID."
    }

    precondition {
      condition     = length(setsubtract(toset(try(each.value.software_source_keys, [])), toset(keys(local.software_source_ids_by_key)))) == 0
      error_message = "One or more software_source_keys for this profile do not match osmh.software_sources keys."
    }
  }
}
