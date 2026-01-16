"""
Query AxTransaction table for employee-project mappings.
This is the actual time/labor transaction table in Ajera.
"""

import pyodbc
import json
from pathlib import Path
from collections import defaultdict

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

def query_transactions():
    """Query AxTransaction for employee-project relationships."""
    
    conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
    conn = pyodbc.connect(conn_str)
    print("✓ Connected to Ajera\n")
    
    cursor = conn.cursor()
    
    # First, inspect AxTransaction structure
    print("="*80)
    print("INSPECTING AxTransaction TABLE")
    print("="*80)
    
    cursor.execute("SELECT TOP 5 * FROM dbo.AxTransaction WHERE tEmployee IS NOT NULL AND tProject IS NOT NULL")
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    
    print(f"\nColumns ({len(cols)}): {', '.join(cols[:30])}")
    if len(cols) > 30:
        print(f"... and {len(cols) - 30} more")
    
    print(f"\nSample transactions:")
    for i, row in enumerate(rows[:3], 1):
        sample = dict(zip(cols, row))
        print(f"\n  Transaction {i}:")
        print(f"    tKey: {sample.get('tKey')}")
        print(f"    tType: {sample.get('tType')}")
        print(f"    tDate: {sample.get('tDate')}")
        print(f"    tEmployee: {sample.get('tEmployee')}")
        print(f"    tProject: {sample.get('tProject')}")
        print(f"    tActivity: {sample.get('tActivity')}")
        print(f"    Hours/Amount: {sample.get('tHours', 'N/A')} / {sample.get('tAmount', 'N/A')}")
    
    # Now build the mappings
    print("\n" + "="*80)
    print("BUILDING EMPLOYEE-PROJECT MAPPINGS FROM TRANSACTIONS")
    print("="*80)
    
    query = """
        SELECT DISTINCT
            tEmployee,
            tProject
        FROM dbo.AxTransaction
        WHERE tEmployee IS NOT NULL 
          AND tProject IS NOT NULL
          AND tType = 1  -- Type 1 is typically time entries
        ORDER BY tEmployee, tProject
    """
    
    # FIRST: Get employee info to determine who is active
    print("\nFetching employee information...")
    cursor.execute("""
        SELECT vecKey, vecFirstName, vecLastName, vecStatus 
        FROM dbo.AxVEC 
        WHERE vecIsEmployee = 1
    """)
    all_employees = cursor.fetchall()
    employee_names = {row[0]: f"{row[1]} {row[2]}".strip() for row in all_employees if row[1] or row[2]}
    active_employee_ids = {row[0] for row in all_employees if row[3] == 0}  # vecStatus = 0 is active
    
    print(f"  Total employees in database: {len(employee_names)}")
    print(f"  Active employees (vecStatus = 0): {len(active_employee_ids)}")
    
    # NOW: Query transactions
    print("\nQuerying distinct employee-project pairs...")
    cursor.execute(query)
    rows = cursor.fetchall()
    
    print(f"✓ Found {len(rows)} unique employee-project relationships")
    
    if len(rows) == 0:
        print("\n✗ No relationships found. Trying without tType filter...")
        query = """
            SELECT DISTINCT
                tEmployee,
                tProject
            FROM dbo.AxTransaction
            WHERE tEmployee IS NOT NULL 
              AND tProject IS NOT NULL
            ORDER BY tEmployee, tProject
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        print(f"✓ Found {len(rows)} relationships")
    
    # Build dictionaries - FILTER TO ACTIVE EMPLOYEES ONLY
    print(f"\nFiltering to active employees only...")
    employee_to_projects = defaultdict(list)
    project_to_employees = defaultdict(list)
    
    skipped = 0
    for emp_id, proj_id in rows:
        # Skip inactive employees completely
        if emp_id not in active_employee_ids:
            skipped += 1
            continue
            
        if proj_id not in employee_to_projects[emp_id]:
            employee_to_projects[emp_id].append(int(proj_id))
        if emp_id not in project_to_employees[proj_id]:
            project_to_employees[proj_id].append(int(emp_id))
    
    print(f"  Kept: {len(rows) - skipped} relationships")
    print(f"  Skipped (inactive): {skipped} relationships")
    
    print("Fetching project names...")
    cursor.execute("SELECT prjKey, prjDescription FROM dbo.AxProject")
    project_names = {row[0]: row[1] for row in cursor.fetchall() if row[1]}
    
    # Build final result - ACTIVE EMPLOYEES ONLY
    result = {
        "source_table": "dbo.AxTransaction",
        "employee_column": "tEmployee",
        "project_column": "tProject",
        "filter": "active_employees_only (vecStatus = 0)",
        "employee_to_projects": {
            str(emp_id): {
                "name": employee_names.get(emp_id, ""),
                "projects": [str(p) for p in projects]
            }
            for emp_id, projects in employee_to_projects.items()
        },
        "project_to_employees": {
            str(proj_id): {
                "name": project_names.get(proj_id, ""),
                "employees": [str(e) for e in employees]
            }
            for proj_id, employees in project_to_employees.items()
        },
        "metadata": {
            "active_employees": len(employee_to_projects),
            "projects": len(project_to_employees),
            "relationships": len([(e, p) for e, projects in employee_to_projects.items() for p in projects])
        }
    }
    
    # Save to file (use absolute Windows path)
    output_file = Path("C:/temp/ajera_mappings.json")
    
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✓ SAVED MAPPINGS TO: {output_file}")
    print(f"   (Also accessible from WSL at: /mnt/c/temp/ajera_mappings.json)")
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY (ACTIVE EMPLOYEES ONLY)")
    print("="*80)
    print(f"\nSource: AxTransaction (time/labor entries)")
    print(f"Filter: Active employees only (vecStatus = 0)")
    print(f"Active Employees: {result['metadata']['active_employees']}")
    print(f"Projects: {result['metadata']['projects']}")
    print(f"Relationships: {result['metadata']['relationships']}")
    
    # Show top contributors
    top_emp = sorted(employee_to_projects.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    print(f"\nTop 10 employees by project count:")
    for emp_id, projects in top_emp:
        emp_name = employee_names.get(emp_id, f"Employee {emp_id}")
        print(f"  {emp_name} (ID: {emp_id}): {len(projects)} projects")
    
    top_proj = sorted(project_to_employees.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    print(f"\nTop 10 projects by employee count:")
    for proj_id, employees in top_proj:
        proj_name = project_names.get(proj_id, f"Project {proj_id}")
        print(f"  {proj_name[:60]} (ID: {proj_id}): {len(employees)} employees")
    
    conn.close()
    print("\n✓ Complete!")


if __name__ == "__main__":
    query_transactions()
