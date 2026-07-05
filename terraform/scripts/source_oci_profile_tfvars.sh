#!/usr/bin/env bash
# Source OCI profile values into Terraform/OCI CLI environment variables.
#
# Usage:
#   source scripts/source_oci_profile_tfvars.sh <oci_profile> [region|auto] [config_file] [osmh_compartment_id]
#
# Example:
#   source scripts/source_oci_profile_tfvars.sh apacanzset03child3 auto config/apacanzset03child3_osmh_config.json
#   source scripts/source_oci_profile_tfvars.sh apacanzset03child3 auto config/apacanzset03child3_osmh_config.json ocid1.compartment.oc1..example
#
# If osmh_compartment_id is omitted, the tenancy OCID from the OCI profile is
# used as TF_VAR_osmh_compartment_id. Pass a compartment OCID when OSMH resources
# should be created below the tenancy/root scope.
#
# This script must be sourced, not executed, if you want the exports to remain
# in your current shell.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "This script must be sourced so it can export variables into your shell." >&2
  echo "Usage: source $0 <oci_profile> [region|auto] [config_file] [osmh_compartment_id]" >&2
  exit 1
fi

_osmh_profile="${1:-}"
_osmh_region="${2:-}"
_osmh_config_file="${3:-}"
_osmh_compartment_id_arg="${4:-}"
_osmh_oci_config="${OCI_CONFIG_FILE:-$HOME/.oci/config}"

if [[ -z "$_osmh_profile" ]]; then
  echo "Usage: source scripts/source_oci_profile_tfvars.sh <oci_profile> [region|auto] [config_file] [osmh_compartment_id]" >&2
  return 2
fi

if [[ ! -f "$_osmh_oci_config" ]]; then
  echo "OCI config not found: $_osmh_oci_config" >&2
  return 2
fi

_osmh_profile_value() {
  local key="$1"
  awk -v section="[$_osmh_profile]" -v key="$key" '
    $0 == section { in_section=1; next }
    /^\[/ && in_section { exit }
    in_section {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line ~ "^" key "[[:space:]]*=") {
        sub("^" key "[[:space:]]*=[[:space:]]*", "", line)
        print line
        exit
      }
    }
  ' "$_osmh_oci_config"
}

_osmh_expand_path() {
  local value="$1"
  case "$value" in
    \~/*) printf '%s/%s\n' "$HOME" "${value#\~/}" ;;
    *) printf '%s\n' "$value" ;;
  esac
}

_osmh_region_from_instances_csv() {
  local csv_path="$1"
  if [[ ! -f "$csv_path" ]]; then
    return 1
  fi

  python3 - "$csv_path" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(newline="", encoding="utf-8-sig") as handle:
    reader = csv.DictReader(handle)
    regions = sorted({
        (row.get("region") or "").strip()
        for row in reader
        if (row.get("region") or "").strip()
    })

if len(regions) == 1:
    print(regions[0])
elif len(regions) > 1:
    print(",".join(regions))
    sys.exit(3)
else:
    sys.exit(1)
PY
}

_osmh_tenancy="$(_osmh_profile_value tenancy)"
_osmh_user="$(_osmh_profile_value user)"
_osmh_fingerprint="$(_osmh_profile_value fingerprint)"
_osmh_key_file="$(_osmh_profile_value key_file)"
_osmh_pass_phrase="$(_osmh_profile_value pass_phrase)"
_osmh_profile_region="$(_osmh_profile_value region)"

if [[ -z "$_osmh_tenancy" || -z "$_osmh_user" || -z "$_osmh_fingerprint" || -z "$_osmh_key_file" ]]; then
  echo "Profile $_osmh_profile in $_osmh_oci_config is missing tenancy, user, fingerprint, or key_file." >&2
  return 2
fi

if [[ -z "$_osmh_config_file" ]]; then
  _osmh_config_file="config/${_osmh_profile}_osmh_config.json"
fi

_osmh_instances_csv="config/${_osmh_profile}_instances.csv"

if [[ -z "$_osmh_region" || "$_osmh_region" == "auto" ]]; then
  _osmh_region="$(_osmh_region_from_instances_csv "$_osmh_instances_csv")"
  _osmh_region_status=$?

  if [[ $_osmh_region_status -eq 3 ]]; then
    echo "Multiple regions found in $_osmh_instances_csv: $_osmh_region" >&2
    echo "Source this script once per region, passing the intended region explicitly." >&2
    return 2
  fi

  if [[ $_osmh_region_status -ne 0 || -z "$_osmh_region" ]]; then
    _osmh_region="$_osmh_profile_region"
  fi
fi

if [[ -z "$_osmh_region" ]]; then
  echo "No region supplied, no single region found in $_osmh_instances_csv, and profile $_osmh_profile has no region entry." >&2
  return 2
fi

_osmh_compartment_id="${_osmh_compartment_id_arg:-${OSMH_COMPARTMENT_ID:-$_osmh_tenancy}}"

export OCI_CLI_PROFILE="$_osmh_profile"
export TF_VAR_tenancy_ocid="$_osmh_tenancy"
export TF_VAR_user_ocid="$_osmh_user"
export TF_VAR_fingerprint="$_osmh_fingerprint"
export TF_VAR_private_key_path="$(_osmh_expand_path "$_osmh_key_file")"
export TF_VAR_region="$_osmh_region"
export TF_VAR_config_file="$_osmh_config_file"

if [[ -n "$_osmh_profile_region" ]]; then
  export TF_VAR_home_region="$_osmh_profile_region"
fi

if [[ -n "$_osmh_compartment_id" ]]; then
  export TF_VAR_osmh_compartment_id="$_osmh_compartment_id"
fi

if [[ -n "$_osmh_pass_phrase" ]]; then
  export TF_VAR_private_key_password="$_osmh_pass_phrase"
else
  unset TF_VAR_private_key_password
fi

unset _osmh_profile _osmh_region _osmh_config_file _osmh_oci_config _osmh_instances_csv
unset _osmh_tenancy _osmh_user _osmh_fingerprint _osmh_key_file _osmh_pass_phrase _osmh_profile_region
unset _osmh_compartment_id_arg _osmh_compartment_id _osmh_region_status
unset -f _osmh_profile_value _osmh_expand_path _osmh_region_from_instances_csv

echo "Loaded OSMH Terraform env:"
echo "  OCI_CLI_PROFILE=$OCI_CLI_PROFILE"
echo "  TF_VAR_region=$TF_VAR_region"
if [[ -n "${TF_VAR_home_region:-}" ]]; then
  echo "  TF_VAR_home_region=$TF_VAR_home_region"
fi
echo "  TF_VAR_config_file=$TF_VAR_config_file"
echo "  TF_VAR_tenancy_ocid=$TF_VAR_tenancy_ocid"
echo "  TF_VAR_user_ocid=$TF_VAR_user_ocid"
echo "  TF_VAR_private_key_path=$TF_VAR_private_key_path"
if [[ -n "${TF_VAR_osmh_compartment_id:-}" ]]; then
  echo "  TF_VAR_osmh_compartment_id=$TF_VAR_osmh_compartment_id"
fi
