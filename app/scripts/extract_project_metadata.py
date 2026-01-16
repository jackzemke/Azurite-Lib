"""
Extract enriched project metadata from Ajera.
Includes marketing fields, project manager, location, etc.
"""

import pyodbc
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

def query_enriched_projects():
    """Query AxProject for enriched metadata."""
    
    conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
    conn = pyodbc.connect(conn_str)
    print("✓ Connected to Ajera\n")
    
    cursor = conn.cursor()
    
    print("Fetching enriched project metadata...")
    cursor.execute("""
        SELECT 
            prjKey,
            prjDescription,
            prjProjectType,
            prjProjectManager,
            prjPrincipalInCharge,
            prjLocation,
            prjMarketingDescription,
            prjMarketingScopeOfWork,
            prjMarketingNotes,
            prjNotes,
            prjEstimatedStartDate,
            prjEstimatedCompletionDate,
            prjActualStartDate,
            prjActualCompletionDate,
            prjStatus
        FROM dbo.AxProject
        WHERE prjDescription IS NOT NULL
    """)
    
    projects = cursor.fetchall()
    print(f"  Found {len(projects)} projects with metadata\n")
    
    # Build enriched project dict
    project_metadata = {}
    
    for row in projects:
        proj_id = str(row[0])
        
        # Convert dates to strings
        start_date = row[10].strftime('%Y-%m-%d') if row[10] else None
        end_date = row[11].strftime('%Y-%m-%d') if row[11] else None
        actual_start = row[12].strftime('%Y-%m-%d') if row[12] else None
        actual_end = row[13].strftime('%Y-%m-%d') if row[13] else None
        
        project_metadata[proj_id] = {
            "name": row[1] or "",
            "project_type": row[2] or None,
            "project_manager": row[3] or None,
            "principal": row[4] or None,
            "location": row[5] or None,
            "marketing_description": row[6] or None,
            "marketing_scope": row[7] or None,
            "marketing_notes": row[8] or None,
            "notes": row[9] or None,
            "estimated_start": start_date,
            "estimated_completion": end_date,
            "actual_start": actual_start,
            "actual_completion": actual_end,
            "status": row[14]
        }
    
    # Save to file
    output_file = Path("C:/temp/ajera_project_metadata.json")
    
    with open(output_file, 'w') as f:
        json.dump(project_metadata, f, indent=2)
    
    print(f"✓ SAVED PROJECT METADATA TO: {output_file}")
    print(f"   (Also accessible from WSL at: /mnt/c/temp/ajera_project_metadata.json)")
    
    # Show sample
    print("\n" + "="*80)
    print("SAMPLE PROJECT METADATA")
    print("="*80)
    
    # Find a project with marketing data
    for proj_id, meta in list(project_metadata.items())[:5]:
        if meta.get('marketing_description') or meta.get('location'):
            print(f"\nProject {proj_id}: {meta['name']}")
            if meta.get('location'):
                print(f"  Location: {meta['location']}")
            if meta.get('project_type'):
                print(f"  Type: {meta['project_type']}")
            if meta.get('marketing_description'):
                print(f"  Marketing: {meta['marketing_description'][:100]}")
            if meta.get('marketing_scope'):
                print(f"  Scope: {meta['marketing_scope'][:100]}")
            break
    
    conn.close()
    print("\n✓ Complete!")


if __name__ == "__main__":
    query_enriched_projects()
