resource "oci_identity_dynamic_group" "osmh_instances" {
  provider = oci.home

  count = local.identity_enabled && !local.use_existing_dynamic_group ? 1 : 0

  compartment_id = local.tenancy_ocid
  name           = local.dynamic_group_name
  description    = try(local.identity_config.dynamic_group_description, "OCI compute instances that can register with OS Management Hub.")
  matching_rule  = local.dynamic_group_matching_rule

  lifecycle {
    precondition {
      condition     = length(local.compartment_lookup_missing) == 0
      error_message = "Could not look up one or more identity.managed_compartment_names. Add real IDs to config.compartments or fleet.instances[*].compartment_id, or set identity.matching_rule explicitly."
    }

    precondition {
      condition     = length(local.compartment_lookup_conflicts) == 0
      error_message = "One or more identity.managed_compartment_names matched multiple active compartments. Add the intended OCID to config.compartments or fleet.instances[*].compartment_id."
    }

    precondition {
      condition     = local.dynamic_group_matching_rule != "ANY {}" && length(regexall("replace_", local.dynamic_group_matching_rule)) == 0
      error_message = "No real workload compartment OCIDs were resolved for the dynamic group matching rule."
    }
  }
}

resource "oci_identity_policy" "osmh" {
  provider = oci.home

  count = local.identity_enabled && local.create_identity_policy ? 1 : 0

  compartment_id = local.tenancy_ocid
  name           = local.identity_policy_name
  description    = local.identity_policy_description
  statements     = local.identity_policy_statements

  depends_on = [oci_identity_dynamic_group.osmh_instances]
}
