"""
Merge project metadata with time series data.
Creates unified Ajera dataset with employee + project info.
"""

import json
from pathlib import Path

print("Loading data files...")

# Load time series data
time_series_path = Path("/mnt/c/temp/ajera_time_series.json")
with open(time_series_path) as f:
    time_series = json.load(f)

# Load project metadata
metadata_path = Path("/mnt/c/temp/ajera_project_metadata.json")
with open(metadata_path) as f:
    project_metadata = json.load(f)

print(f"✓ Loaded {len(time_series['employee_to_projects'])} employees")
print(f"✓ Loaded {len(project_metadata)} project metadata records\n")

# Merge metadata into project_to_employees
print("Merging project metadata...")
merged_count = 0

for proj_id, proj_data in time_series["project_to_employees"].items():
    if proj_id in project_metadata:
        # Add metadata fields
        proj_data["metadata"] = project_metadata[proj_id]
        merged_count += 1
    else:
        # No metadata found
        proj_data["metadata"] = {
            "name": proj_data.get("name", ""),
            "project_type": None,
            "project_manager": None,
            "principal": None,
            "location": None,
            "marketing_description": None,
            "marketing_scope": None,
            "marketing_notes": None,
            "notes": None,
            "estimated_start": None,
            "estimated_completion": None,
            "actual_start": None,
            "actual_completion": None,
            "status": None
        }

print(f"✓ Merged metadata for {merged_count} projects")

# Add metadata summary
time_series["metadata"]["projects_with_metadata"] = merged_count
time_series["metadata"]["total_projects"] = len(time_series["project_to_employees"])

# Save merged data
output_path = Path("/mnt/c/temp/ajera_unified.json")
with open(output_path, 'w') as f:
    json.dump(time_series, f, indent=2)

print(f"\n✓ SAVED UNIFIED DATA TO: {output_path}")
print(f"   Copy to project: cp /mnt/c/temp/ajera_unified.json ~/lib/project-library/data/ajera_unified.json")

# Show sample
print("\n" + "="*80)
print("SAMPLE ENRICHED PROJECT")
print("="*80)

for proj_id, proj_data in list(time_series["project_to_employees"].items())[:10]:
    meta = proj_data.get("metadata", {})
    if meta.get("location") or meta.get("marketing_description"):
        print(f"\nProject {proj_id}: {meta.get('name', 'N/A')}")
        print(f"  Employees: {len(proj_data['employees'])}")
        if meta.get("location"):
            print(f"  Location: {meta['location']}")
        if meta.get("project_type"):
            print(f"  Type: {meta['project_type']}")
        if meta.get("marketing_description"):
            print(f"  Marketing: {meta['marketing_description'][:80]}...")
        break

print("\n✓ Complete!")
