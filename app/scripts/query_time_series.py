"""
Query Ajera for employee-project-time series data.
Tracks when employees worked on projects over time.
"""

import pyodbc
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

def query_time_series():
    """Query AxTransaction for time series employee-project data."""
    
    conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
    conn = pyodbc.connect(conn_str)
    print("✓ Connected to Ajera\n")
    
    cursor = conn.cursor()
    
    # Get ALL employees (don't filter by status - we'll filter by recent activity instead)
    print("Fetching employee information...")
    cursor.execute("""
        SELECT vecKey, vecFirstName, vecLastName, vecStatus 
        FROM dbo.AxVEC 
        WHERE vecIsEmployee = 1
    """)
    all_employees = cursor.fetchall()
    employee_names = {row[0]: f"{row[1]} {row[2]}".strip() for row in all_employees if row[1] or row[2]}
    all_employee_ids = {row[0] for row in all_employees}
    
    print(f"  Total employees: {len(all_employee_ids)}")
    
    # Get project names
    print("Fetching project names...")
    cursor.execute("SELECT prjKey, prjDescription FROM dbo.AxProject")
    project_names = {row[0]: row[1] for row in cursor.fetchall() if row[1]}
    
    # First, check what columns exist in AxTransaction
    print("\nChecking AxTransaction columns...")
    cursor.execute("SELECT TOP 1 * FROM dbo.AxTransaction WHERE tEmployee IS NOT NULL AND tProject IS NOT NULL")
    cols = [desc[0] for desc in cursor.description]
    
    # Find hours-related columns
    hours_cols = [c for c in cols if 'hour' in c.lower() or 'time' in c.lower() or 'qty' in c.lower() or 'amount' in c.lower()]
    print(f"  Potential hours/quantity columns: {hours_cols[:10]}")
    
    # Query transactions with date information
    # Try common column names for hours/quantity
    hours_col = None
    for candidate in ['tUnits', 'tHours', 'tQuantity', 'tQty', 'tAmount', 'tTimeHours', 'tLabor']:
        if candidate in cols:
            hours_col = candidate
            break
    
    if not hours_col:
        print("  Warning: No hours column found, will use NULL")
        hours_col = "NULL"
    else:
        print(f"  Using hours column: {hours_col}")
    
    print("\nQuerying transactions with dates...")
    print("  Note: Limiting to last 2 years to avoid query limits...")
    
    query = f"""
        SELECT 
            tEmployee,
            tProject,
            tDate,
            {hours_col} as hours
        FROM dbo.AxTransaction
        WHERE tEmployee IS NOT NULL 
          AND tProject IS NOT NULL
          AND tDate IS NOT NULL
          AND tDate >= DATEADD(year, -2, GETDATE())  -- Last 2 years only
        ORDER BY tDate DESC
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    print(f"✓ Found {len(rows)} time entries")
    
    # Filter to active employees and build time series
    print("\nBuilding time series data...")
    
    employee_project_timeline = defaultdict(lambda: defaultdict(list))  # {emp_id: {proj_id: [dates]}}
    project_employee_timeline = defaultdict(lambda: defaultdict(list))  # {proj_id: {emp_id: [dates]}}
    employee_to_projects = defaultdict(set)
    project_to_employees = defaultdict(set)
    
    skipped = 0
    earliest_date = None
    latest_date = None
    
    for emp_id, proj_id, date, hours in rows:
        # Include all employees who have transaction data (they worked in last 2 years)
        if emp_id not in all_employee_ids:
            skipped += 1
            continue
        
        # Track date range
        if earliest_date is None or date < earliest_date:
            earliest_date = date
        if latest_date is None or date > latest_date:
            latest_date = date
        
        # Build mappings
        employee_to_projects[emp_id].add(proj_id)
        project_to_employees[proj_id].add(emp_id)
        
        # Add to timeline
        date_str = date.strftime('%Y-%m-%d') if date else None
        if date_str:
            employee_project_timeline[emp_id][proj_id].append({
                "date": date_str,
                "hours": float(hours) if hours else 0.0
            })
            project_employee_timeline[proj_id][emp_id].append({
                "date": date_str,
                "hours": float(hours) if hours else 0.0
            })
    
    print(f"  Processed: {len(rows) - skipped} entries")
    print(f"  Skipped (inactive): {skipped} entries")
    print(f"  Date range: {earliest_date.strftime('%Y-%m-%d') if earliest_date else 'N/A'} to {latest_date.strftime('%Y-%m-%d') if latest_date else 'N/A'}")
    
    # Build result with time series
    result = {
        "source_table": "dbo.AxTransaction",
        "filter": "employees_with_recent_activity (last 2 years)",
        "date_range": {
            "earliest": earliest_date.strftime('%Y-%m-%d') if earliest_date else None,
            "latest": latest_date.strftime('%Y-%m-%d') if latest_date else None
        },
        "employee_to_projects": {
            str(emp_id): {
                "name": employee_names.get(emp_id, ""),
                "projects": [str(p) for p in sorted(projects)],
                "timeline": {
                    str(proj_id): entries
                    for proj_id, entries in employee_project_timeline[emp_id].items()
                }
            }
            for emp_id, projects in employee_to_projects.items()
        },
        "project_to_employees": {
            str(proj_id): {
                "name": project_names.get(proj_id, ""),
                "employees": [str(e) for e in sorted(employees)],
                "timeline": {
                    str(emp_id): entries
                    for emp_id, entries in project_employee_timeline[proj_id].items()
                }
            }
            for proj_id, employees in project_to_employees.items()
        },
        "metadata": {
            "active_employees": len(employee_to_projects),
            "projects": len(project_to_employees),
            "time_entries": len(rows) - skipped
        }
    }
    
    # Save to file
    output_file = Path("C:/temp/ajera_time_series.json")
    
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✓ SAVED TIME SERIES DATA TO: {output_file}")
    print(f"   (Also accessible from WSL at: /mnt/c/temp/ajera_time_series.json)")
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY (TIME SERIES DATA)")
    print("="*80)
    print(f"\nEmployees with Recent Activity: {result['metadata']['active_employees']}")
    print(f"Projects: {result['metadata']['projects']}")
    print(f"Time Entries: {result['metadata']['time_entries']}")
    print(f"Date Range: {result['date_range']['earliest']} to {result['date_range']['latest']}")
    
    # Show top contributors
    top_emp = sorted(employee_to_projects.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    print(f"\nTop 10 employees by project count:")
    for emp_id, projects in top_emp:
        emp_name = employee_names.get(emp_id, f"Employee {emp_id}")
        total_hours = sum(
            e['hours'] for proj_id in employee_project_timeline[emp_id].values() 
            for e in proj_id
        )
        print(f"  {emp_name} (ID: {emp_id}): {len(projects)} projects, {total_hours:.1f} hours")
    
    conn.close()
    print("\n✓ Complete!")


if __name__ == "__main__":
    query_time_series()
