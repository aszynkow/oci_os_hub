#!/usr/bin/env python3
import csv
import shutil
from datetime import datetime
from pathlib import Path
import argparse

OCID_REGION_MAP = {
    "ap-sydney-1": "ap-sydney-1",
    "ap-melbourne-1": "ap-melbourne-1",
    "ap-tokyo-1": "ap-tokyo-1",
    "iad": "us-ashburn-1",
}


def infer_region_from_instance_id(instance_id: str, default: str = "ap-sydney-1") -> str:
    parts = instance_id.split(".")
    if len(parts) > 3 and parts[:3] == ["ocid1", "instance", "oc1"]:
        return OCID_REGION_MAP.get(parts[3], parts[3])
    return default


def main():
    parser = argparse.ArgumentParser(description="Transform ANZ CSV to OSMH instances CSV")
    parser.add_argument('--source-csv', default='anz_cloud_team_book_new.csv', help='Source multi-account CSV')
    parser.add_argument('--account-name', default='apacanzset03', help='Account name to filter')
    parser.add_argument('--target-csv', default='terraform/config/apacanzset03_instances.csv', help='Target instances CSV')
    args = parser.parse_args()

    base_dir = Path("terraform/config")
    source_csv = Path(args.source_csv)
    template_csv = base_dir / "template_instances.csv"
    target_csv = Path(args.target_csv)
    backup_dir = base_dir / "backup"
    account_name = args.account_name

    print("=== OCI OS Hub CSV Transformation ===")
    print(f"Source: {source_csv} (filter: {account_name})")
    print(f"Template: {template_csv}")
    print(f"Target: {target_csv}")

    # 1. Create backup directory and backup existing apacanzset03_instances.csv
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if target_csv.exists():
        backup_path = backup_dir / f"{target_csv.name}.{timestamp}"
        shutil.copy2(target_csv, backup_path)
        print(f"✓ Backed up existing {target_csv.name} to: {backup_path}")
    else:
        print(f"No existing {target_csv.name} to backup (first run)")

    # 2. Read template headers
    with open(template_csv, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)

    print(f"✓ Using template columns: {len(headers)} fields")

    # 3. Read source CSV and filter for target account only
    filtered_rows = []
    with open(source_csv, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('account_name', '').strip() == account_name:
                new_row = {header: '' for header in headers}

                # Map available fields from source - use unique compartment_name to prevent conflicts
                # (this matches the HIGH risk identified in .agent-plan.md: "Compartment ID Conflicts")
                row_account = row.get('account_name', account_name).strip()
                compartment_id = row.get('RESOURCE_COMPARTMENT_ID', '').strip()
                # Make compartment_name unique by appending short suffix of compartment_id when needed
                if compartment_id and len(compartment_id) > 6:
                    short_id = compartment_id[-6:]
                    new_row['compartment_name'] = f"{row_account}-{short_id}"
                else:
                    new_row['compartment_name'] = row_account
                new_row['compartment_id'] = compartment_id

                instance_id = row.get('RESOURCE_INSTANCE_ID', '').strip()
                if instance_id and 'instance_id' in new_row:
                    new_row['instance_id'] = instance_id
                if instance_id:
                    # Use last 8 chars of OCID for display name (common pattern)
                    short_id = instance_id[-8:] if len(instance_id) > 8 else instance_id
                    new_row['display_name'] = f"anz-{short_id}"
                    new_row['error'] = ''
                else:
                    new_row['display_name'] = 'unknown-instance'

                # Default values for missing metadata (requires OCI enrichment for production)
                new_row['region'] = infer_region_from_instance_id(instance_id)
                new_row['lifecycle_state'] = 'RUNNING'
                new_row['shape'] = 'VM.Standard.E4.Flex'
                new_row['os_distro'] = 'Oracle Linux 8'
                new_row['availability_domain'] = 'TBD'
                new_row['time_created'] = datetime.now().isoformat()
                new_row['created_by'] = row.get('admin_email', 'unknown@anz.com')
                new_row['created_on'] = datetime.now().strftime("%Y-%m-%d")
                new_row['freeform_tags'] = f'{{"source": "anz_cloud_team_book", "account": "{account_name}"}}'
                new_row['defined_tags'] = ''

                filtered_rows.append(new_row)

    print(f"✓ Filtered {len(filtered_rows)} {account_name} rows from source")

    # 4. Write the new target instances CSV
    with open(target_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(filtered_rows)

    print(f"✓ Successfully wrote {len(filtered_rows)} rows to {target_csv}")
    print("\n=== Transformation Complete ===")
    print("Note: Many fields were defaulted because anz_cloud_team_book_new.csv")
    print("is a security findings export and lacks full instance metadata.")
    print("Production use would require OCI SDK enrichment step using RESOURCE_INSTANCE_ID OCIDs.")

    # Show summary
    print("\nSummary:")
    print(f"  - Rows in {target_csv.name}: {len(filtered_rows)}")
    print(f"  - Backup created: {'Yes' if 'backup_path' in locals() else 'No'}")
    regions = sorted({row["region"] for row in filtered_rows if row.get("region")})
    print(f"  - Regions used: {', '.join(regions) if regions else 'none'}")
    print(f"  - Account processed: {account_name}")

if __name__ == "__main__":
    main()
