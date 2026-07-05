data "oci_identity_compartments" "by_name" {
  provider = oci.home

  for_each = local.compartment_lookup_names

  compartment_id            = local.tenancy_ocid
  compartment_id_in_subtree = true
  access_level              = "ACCESSIBLE"
  name                      = each.key
  state                     = "ACTIVE"
}
