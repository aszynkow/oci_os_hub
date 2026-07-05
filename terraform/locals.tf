locals {
  config = jsondecode(file(var.config_file))

  provider_region     = coalesce(var.region, try(local.config.region, null), try(local.config.home_region, null), "ap-sydney-1")
  home_region         = coalesce(var.home_region, try(local.config.home_region, null), local.provider_region)
  tenancy_ocid        = coalesce(var.tenancy_ocid, try(local.config.tenancy_ocid, null))
  osmh_compartment_id = coalesce(var.osmh_compartment_id, try(local.config.osmh.compartment_id, null))

  fleet_instances = try(local.config.fleet.instances, [])

  configured_compartments = {
    for name, id in try(local.config.compartments, {}) : name => id
    if id != "" && length(regexall("replace_", id)) == 0
  }

  fleet_compartment_id_groups = {
    for instance in local.fleet_instances :
    try(instance.compartment_name, "") => try(instance.compartment_id, "")...
    if try(instance.compartment_name, "") != "" &&
    try(instance.compartment_id, "") != "" &&
    length(regexall("replace_", try(instance.compartment_id, ""))) == 0
  }

  fleet_compartments = {
    for name, ids in local.fleet_compartment_id_groups : name => distinct(ids)[0]
    if length(distinct(ids)) == 1
  }

  fleet_compartment_conflicts = {
    for name, ids in local.fleet_compartment_id_groups : name => distinct(ids)
    if length(distinct(ids)) > 1
  }

  default_freeform_tags = merge(
    {
      managed_by = "terraform"
      repo       = "oci_os_hub"
    },
    try(local.config.default_freeform_tags, {})
  )

  identity_config  = try(local.config.identity, {})
  identity_enabled = var.enable_identity != null ? var.enable_identity : try(local.identity_config.enabled, true)

  enable_source_creation = var.enable_source_creation != null ? var.enable_source_creation : try(local.config.osmh.enable_source_creation, true)

  managed_compartment_names = distinct(try(local.identity_config.managed_compartment_names, []))

  base_compartments = merge(local.fleet_compartments, local.configured_compartments)

  compartment_lookup_names = toset([
    for name in local.managed_compartment_names : name
    if !contains(keys(local.base_compartments), name)
  ])

  looked_up_compartment_id_groups = {
    for name, lookup in data.oci_identity_compartments.by_name : name => [
      for compartment in lookup.compartments : compartment.id
      if compartment.name == name && compartment.state == "ACTIVE"
    ]
  }

  looked_up_compartments = {
    for name, ids in local.looked_up_compartment_id_groups : name => distinct(ids)[0]
    if length(distinct(ids)) == 1
  }

  compartment_lookup_missing = [
    for name, ids in local.looked_up_compartment_id_groups : name
    if length(distinct(ids)) == 0
  ]

  compartment_lookup_conflicts = {
    for name, ids in local.looked_up_compartment_id_groups : name => distinct(ids)
    if length(distinct(ids)) > 1
  }

  compartments = merge(local.looked_up_compartments, local.fleet_compartments, local.configured_compartments)

  use_existing_dynamic_group = try(local.identity_config.use_existing_dynamic_group, false)
  existing_dynamic_group_id  = try(local.identity_config.existing_dynamic_group_id, null)
  create_identity_policy     = try(local.identity_config.create_policy, true)

  dynamic_group_name = try(local.identity_config.dynamic_group_name, "osmh-instances")
  dynamic_group_compartment_ids = compact(distinct(concat(
    try(local.identity_config.managed_compartment_ids, []),
    [
      for compartment_name in local.managed_compartment_names :
      try(local.compartments[compartment_name], null)
    ]
  )))

  dynamic_group_matching_rule = try(local.identity_config.matching_rule, null) != null ? local.identity_config.matching_rule : (
    length(local.dynamic_group_compartment_ids) == 1 ?
    "ALL {instance.compartment.id='${local.dynamic_group_compartment_ids[0]}'}" :
    "ANY {${join(",", [for id in local.dynamic_group_compartment_ids : "instance.compartment.id='${id}'"])}}"
  )

  identity_policy_name        = try(local.identity_config.policy_name, "osmh-policy")
  identity_policy_description = try(local.identity_config.policy_description, "Allow OCI instances and administrators to use OS Management Hub.")
  osmh_admin_group_name       = try(local.identity_config.admin_group_name, "osmh-admins")
  identity_policy_scope       = try(local.identity_config.policy_scope, "tenancy")

  identity_policy_statements = concat(
    [
      "allow dynamic-group ${local.dynamic_group_name} to {OSMH_MANAGED_INSTANCE_ACCESS} in ${local.identity_policy_scope} where request.principal.id = target.managed-instance.id",
      "allow group ${local.osmh_admin_group_name} to manage osmh-family in ${local.identity_policy_scope}"
    ],
    try(local.identity_config.extra_policy_statements, [])
  )

  software_sources_raw = try(local.config.osmh.software_sources, {})
  software_sources = {
    for key, source in local.software_sources_raw : key => merge(source, {
      compartment_id = coalesce(
        try(source.compartment_id, null),
        try(local.compartments[source.compartment_name], null),
        local.osmh_compartment_id
      )
      display_name            = try(source.display_name, key)
      freeform_tags           = merge(local.default_freeform_tags, try(source.freeform_tags, {}))
      select_availability     = try(source.select_availability, true)
      software_source_type    = upper(try(source.software_source_type, "VENDOR"))
      vendor_software_sources = try(source.vendor_software_sources, [])
    })
    if try(source.enabled, true) && try(source.region, local.provider_region) == local.provider_region
  }

  software_sources_to_create = {
    for key, source in local.software_sources : key => source
    if local.enable_source_creation && source.software_source_type != "VENDOR"
  }

  software_source_origin_lookup_requests = {
    for key, source in local.software_sources : key => try(source.origin_lookup, {})
    if try(source.origin_software_source_id, null) == null && try(source.origin_lookup, null) != null
  }

  software_source_vendor_lookup_requests = {
    for item in flatten([
      for source_key, source in local.software_sources : [
        for idx, vendor_source in try(source.vendor_software_sources, []) : merge(vendor_source, {
          key        = "${source_key}.${idx}"
          source_key = source_key
          idx        = idx
        })
        if local.enable_source_creation && try(vendor_source.id, null) == null
      ]
    ]) : item.key => item
  }

  created_software_source_ids = {
    for key, source in oci_os_management_hub_software_source.this : key => source.id
  }

  origin_software_source_ids = {
    for key, source in data.oci_os_management_hub_software_sources.origin : key => try(source.software_source_collection[0].items[0].id, null)
    if try(source.software_source_collection[0].items[0].id, null) != null
  }

  existing_software_source_ids = {
    for key, source in data.oci_os_management_hub_software_sources.existing : key => try(source.software_source_collection[0].items[0].id, null)
    if try(source.software_source_collection[0].items[0].id, null) != null
  }

  configured_software_source_ids = {
    for key, source in local.software_sources : key => try(source.id, null)
    if try(source.id, null) != null
  }

  vendor_software_source_ids_to_select = {
    for key, source in local.software_sources : key => try(local.software_source_ids_by_key[key], null)
    if source.software_source_type == "VENDOR" &&
    try(source.select_availability, true) &&
    try(local.software_source_ids_by_key[key], null) != null
  }

  software_source_ids_by_key = merge(
    local.configured_software_source_ids,
    local.origin_software_source_ids,
    local.existing_software_source_ids,
    local.created_software_source_ids
  )

  managed_instance_groups_raw = try(local.config.osmh.managed_instance_groups, {})
  managed_instance_groups = {
    for key, group in local.managed_instance_groups_raw : key => merge(group, {
      compartment_id = coalesce(
        try(group.compartment_id, null),
        try(local.compartments[group.compartment_name], null),
        local.osmh_compartment_id
      )
      display_name         = try(group.display_name, key)
      freeform_tags        = merge(local.default_freeform_tags, try(group.freeform_tags, {}))
      managed_instance_ids = compact(try(group.managed_instance_ids, []))
      software_source_ids = sort(compact(concat(
        try(group.software_source_ids, []),
        [
          for source_key in try(group.software_source_keys, []) :
          try(local.software_source_ids_by_key[source_key], null)
        ]
      )))
    })
    if try(group.enabled, true) && try(group.region, local.provider_region) == local.provider_region
  }

  profiles_raw = try(local.config.osmh.profiles, {})
  profiles = {
    for key, profile in local.profiles_raw : key => merge(profile, {
      compartment_id = coalesce(
        try(profile.compartment_id, null),
        try(local.compartments[profile.compartment_name], null),
        local.osmh_compartment_id
      )
      display_name  = try(profile.display_name, key)
      freeform_tags = merge(local.default_freeform_tags, try(profile.freeform_tags, {}))
      profile_type  = try(profile.profile_type, "GROUP")
      software_source_ids = sort(compact(concat(
        try(profile.software_source_ids, []),
        [
          for source_key in try(profile.software_source_keys, []) :
          try(local.software_source_ids_by_key[source_key], null)
        ]
      )))
    })
    if try(profile.enabled, true) && try(profile.region, local.provider_region) == local.provider_region
  }

  scheduled_jobs_raw = try(local.config.osmh.scheduled_jobs, {})
  scheduled_jobs = {
    for key, job in local.scheduled_jobs_raw : key => merge(job, {
      compartment_id = coalesce(
        try(job.compartment_id, null),
        try(local.compartments[job.compartment_name], null),
        local.osmh_compartment_id
      )
      display_name  = try(job.display_name, key)
      freeform_tags = merge(local.default_freeform_tags, try(job.freeform_tags, {}))
      operations = [
        for operation in try(job.operations, [{ operation_type = try(job.operation_type, "UPDATE_ALL") }]) : merge(operation, {
          software_source_ids = sort(compact(concat(
            try(operation.software_source_ids, []),
            [
              for source_key in try(operation.software_source_keys, []) :
              try(local.software_source_ids_by_key[source_key], null)
            ]
          )))
        })
      ]
    })
    if try(job.enabled, true) && try(job.region, local.provider_region) == local.provider_region
  }

  scheduled_job_managed_instance_group_ids = {
    for key, job in local.scheduled_jobs : key => compact(concat(
      try(job.target.managed_instance_group_ids, []),
      [
        for group_key in try(job.target.managed_instance_group_keys, []) :
        try(oci_os_management_hub_managed_instance_group.this[group_key].id, null)
      ]
    ))
  }

  selected_region_instances  = [for instance in local.fleet_instances : instance if try(instance.region, null) == local.provider_region]
  supported_region_instances = [for instance in local.selected_region_instances : instance if try(instance.osmh.supported, false)]
  unsupported_region_instances = [
    for instance in local.selected_region_instances : instance
    if !try(instance.osmh.supported, false)
  ]
}
