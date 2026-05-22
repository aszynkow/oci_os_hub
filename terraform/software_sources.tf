data "oci_os_management_hub_software_sources" "origin" {
  for_each = local.software_source_origin_lookup_requests

  arch_type             = contains(try(each.value.software_source_type, []), "VENDOR") ? null : try(each.value.arch_type, null)
  availability          = try(each.value.availability, null)
  availability_anywhere = try(each.value.availability_anywhere, null)
  availability_at_oci   = try(each.value.availability_at_oci, null)
  compartment_id        = coalesce(try(each.value.compartment_id, null), local.tenancy_ocid)
  display_name          = try(each.value.display_name, null)
  display_name_contains = try(each.value.display_name_contains, null)
  os_family             = contains(try(each.value.software_source_type, []), "VENDOR") ? null : try(each.value.os_family, null)
  software_source_type  = try(each.value.software_source_type, ["VENDOR"])
  state                 = try(each.value.state, null)
  vendor_name           = try(each.value.vendor_name, null)
}

data "oci_os_management_hub_software_sources" "vendor" {
  for_each = local.software_source_vendor_lookup_requests

  arch_type             = contains(try(each.value.lookup.software_source_type, []), "VENDOR") ? null : try(each.value.lookup.arch_type, null)
  availability          = try(each.value.lookup.availability, null)
  availability_anywhere = try(each.value.lookup.availability_anywhere, null)
  availability_at_oci   = try(each.value.lookup.availability_at_oci, null)
  compartment_id        = coalesce(try(each.value.lookup.compartment_id, null), local.tenancy_ocid)
  display_name          = try(each.value.lookup.display_name, try(each.value.display_name, null))
  display_name_contains = try(each.value.lookup.display_name_contains, null)
  os_family             = contains(try(each.value.lookup.software_source_type, []), "VENDOR") ? null : try(each.value.lookup.os_family, null)
  software_source_type  = try(each.value.lookup.software_source_type, ["VENDOR"])
  state                 = try(each.value.lookup.state, null)
  vendor_name           = try(each.value.lookup.vendor_name, null)
}

data "oci_os_management_hub_software_sources" "existing" {
  for_each = local.enable_source_creation ? {} : local.software_sources

  arch_type             = contains(try(each.value.lookup.software_source_type, try(each.value.origin_lookup.software_source_type, [each.value.software_source_type])), "VENDOR") ? null : try(each.value.lookup.arch_type, null)
  availability          = try(each.value.lookup.availability, null)
  availability_anywhere = try(each.value.lookup.availability_anywhere, null)
  availability_at_oci   = try(each.value.lookup.availability_at_oci, null)
  compartment_id        = try(each.value.lookup.compartment_id, try(each.value.origin_lookup.compartment_id, local.tenancy_ocid))
  display_name          = try(each.value.lookup.display_name, try(each.value.origin_lookup.display_name, each.value.display_name))
  display_name_contains = try(each.value.lookup.display_name_contains, null)
  os_family             = contains(try(each.value.lookup.software_source_type, try(each.value.origin_lookup.software_source_type, [each.value.software_source_type])), "VENDOR") ? null : try(each.value.lookup.os_family, try(each.value.origin_lookup.os_family, null))
  software_source_type  = try(each.value.lookup.software_source_type, try(each.value.origin_lookup.software_source_type, [each.value.software_source_type]))
  state                 = try(each.value.lookup.state, null)
  vendor_name           = try(each.value.lookup.vendor_name, try(each.value.origin_lookup.vendor_name, null))
}

resource "oci_os_management_hub_software_source" "this" {
  for_each = local.software_sources_to_create

  compartment_id       = each.value.compartment_id
  software_source_type = each.value.software_source_type

  advanced_repo_options        = try(each.value.advanced_repo_options, null)
  arch_type                    = try(each.value.arch_type, null)
  defined_tags                 = try(each.value.defined_tags, null)
  description                  = try(each.value.description, null)
  display_name                 = each.value.display_name
  freeform_tags                = each.value.freeform_tags
  gpg_key_url                  = try(each.value.gpg_key_url, null)
  is_auto_resolve_dependencies = try(each.value.is_auto_resolve_dependencies, null)
  is_automatically_updated     = try(each.value.is_automatically_updated, null)
  is_created_from_package_list = try(each.value.is_created_from_package_list, null)
  is_gpg_check_enabled         = try(each.value.is_gpg_check_enabled, null)
  is_latest_content_only       = try(each.value.is_latest_content_only, null)
  is_mirror_sync_allowed       = try(each.value.is_mirror_sync_allowed, null)
  is_ssl_verify_enabled        = try(each.value.is_ssl_verify_enabled, null)
  origin_software_source_id = try(coalesce(
    try(each.value.origin_software_source_id, null),
    try(data.oci_os_management_hub_software_sources.origin[each.key].software_source_collection[0].items[0].id, null)
  ), null)
  os_family                = try(each.value.os_family, null)
  packages                 = try(each.value.packages, null)
  software_source_sub_type = try(each.value.software_source_sub_type, null)
  software_source_version  = try(each.value.software_source_version, null)
  url                      = try(each.value.url, null)

  dynamic "vendor_software_sources" {
    for_each = each.value.vendor_software_sources

    content {
      display_name = vendor_software_sources.value.display_name
      id = try(coalesce(
        try(vendor_software_sources.value.id, null),
        try(data.oci_os_management_hub_software_sources.vendor["${each.key}.${vendor_software_sources.key}"].software_source_collection[0].items[0].id, null)
      ), null)
    }
  }

  lifecycle {
    precondition {
      condition = try(
        length(regexall("replace_", each.value.compartment_id)) == 0 &&
        length(regexall("^ocid1\\.compartment\\.oc1\\.", each.value.compartment_id)) > 0,
        false
      )
      error_message = "Replace osmh.compartment_id or this software source's compartment_id with a real compartment OCID before creating software sources."
    }
  }
}

resource "oci_os_management_hub_software_source_change_availability_management" "vendor_selected" {
  for_each = local.vendor_software_source_ids_to_select

  software_source_availabilities {
    software_source_id  = each.value
    availability_at_oci = "SELECTED"
  }
}
