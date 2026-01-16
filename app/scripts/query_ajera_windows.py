"""
Query Ajera from Windows and save results.

Run this from Windows PowerShell with Windows Python:
    python.exe app/scripts/query_ajera_windows.py

This will query via the Windows ODBC DSN and save results to JSON.
Then you can use the results in WSL/Linux.
"""

import pyodbc
import json
from pathlib import Path
from collections import defaultdict

# Windows ODBC DSN configuration
DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

def query_employee_project_mappings():
    """Query via Windows ODBC DSN."""
    
    # Connect using DSN
    conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
    
    print(f"Connecting to {DSN}...")
    conn = pyodbc.connect(conn_str)
    print("✓ Connected")
    
    cursor = conn.cursor()
    
    # First, let's discover tables
    print("\nDiscovering tables...")
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    
    tables = cursor.fetchall()
    print(f"Found {len(tables)} tables:")
    for schema, name in tables[:20]:  # Show first 20
        print(f"  {schema}.{name}")
    
    if len(tables) > 20:
        print(f"  ... and {len(tables) - 20} more")
    
    # Search for time-related tables more broadly
    print("\n" + "="*80)
    print("SEARCHING FOR TIME ENTRY TABLES")
    print("="*80)
    
    time_related = [t for s, t in tables if any(word in t.lower() for word in ['time', 'labor', 'hour', 'entry'])]
    print(f"Found {len(time_related)} time-related tables:")
    for t in time_related:
        print(f"  {t}")
    
    # Inspect key tables
    print("\n" + "="*80)
    print("INSPECTING KEY TABLES")
    print("="*80)
    
    tables_to_inspect = [
        'AxTimesheet',
        'AxTimesheetBreakTime',  # Might contain detail records
        'AxProject', 
        'AxActivity'
    ]
    
    # Also try to find any table with "detail", "line", "entry" in the name
    detail_tables = [t for s, t in tables if any(word in t.lower() for word in ['detail', 'line', 'entry']) and 'time' in t.lower()]
    if detail_tables:
        print(f"\nFound potential detail tables: {detail_tables}")
        tables_to_inspect.extend(detail_tables[:3])
    
    for table in tables_to_inspect:
        print(f"\n{table}:")
        try:
            cursor.execute(f"SELECT TOP 3 * FROM dbo.{table}")
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            print(f"  Columns ({len(cols)}): {', '.join(cols)}")
            if rows:
                print(f"  Sample row 1: {dict(zip(cols, rows[0]))}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    # Now look for the DETAIL table that links timesheets to projects
    print("\n" + "="*80)
    print("LOOKING FOR TIME ENTRY DETAIL TABLE")
    print("="*80)
    
    # Common patterns for detail tables in Ajera
    detail_candidates = [
        'AxTimesheetDetail',
        'AxTimesheetLine', 
        'AxTimeEntry',
        'AxLaborDetail',
        'AxLabor',
        'AxProjectLabor',
        'AxTimesheetActivity',  # Activities might link to projects
    ]
    
    # Filter to only tables that exist
    existing_detail = [t for t in detail_candidates if t in [name for _, name in tables]]
    
    if not existing_detail:
        # Search more broadly
        print("Standard detail tables not found. Searching for any table with time/labor + detail/line/entry...")
        existing_detail = [name for _, name in tables if 
                          ('time' in name.lower() or 'labor' in name.lower()) and 
                          ('detail' in name.lower() or 'line' in name.lower() or 'entry' in name.lower())]
    
    print(f"Potential detail tables: {existing_detail[:10]}")
    
    # Inspect each candidate
    for table_name in existing_detail[:5]:
        print(f"\n{table_name}:")
        try:
            cursor.execute(f"SELECT TOP 3 * FROM dbo.{table_name}")
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            print(f"  Columns ({len(cols)}): {', '.join(cols[:15])}")  # Show first 15 columns
            if len(cols) > 15:
                print(f"    ... and {len(cols) - 15} more")
            if rows:
                print(f"  Sample: {dict(list(zip(cols, rows[0]))[:10])}")  # Show first 10 fields
                
                # Check if this table has what we need
                has_employee = any('employee' in c.lower() or 'emp' in c.lower() for c in cols)
                has_project = any('project' in c.lower() or 'prj' in c.lower() for c in cols)
                
                if has_employee and has_project:
                    print(f"  ✓ This table has both employee and project fields!")
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:150]}")
    
    # Try to build a working query
    print("\n" + "="*80)
    print("ATTEMPTING TO BUILD EMPLOYEE-PROJECT MAPPING")
    print("="*80)
    
    # We'll try different approaches based on what tables exist
    queries_to_try = []
    
    # If we found a detail table, try joining it
    if existing_detail:
        for detail_table in existing_detail[:3]:
            queries_to_try.append((
                f"Using {detail_table}",
                f"""
                SELECT TOP 10 * 
                FROM dbo.{detail_table}
                """
            ))
    
    # Also try if AxActivity links to projects somehow
    queries_to_try.append((
        "Check if AxActivity links timesheets to projects",
        """
        SELECT TOP 10 *
        FROM dbo.AxActivity
        """
    ))
    
    working_query = None
    working_table = None
    
    for name, query in queries_to_try:
        print(f"\n{name}...")
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            print(f"  ✓ Works! Columns: {', '.join(cols[:20])}")
            
            if rows:
                sample = dict(list(zip(cols, rows[0]))[:10])
                print(f"  Sample: {sample}")
                
                # Check if this has employee and project info
                has_employee = any('employee' in c.lower() or c.lower().startswith('ts') and 'emp' in c.lower() for c in cols)
                has_project = any('project' in c.lower() or c.lower().startswith('ts') and 'proj' in c.lower() or c.lower().startswith('ts') and 'prj' in c.lower() for c in cols)
                
                if has_employee and has_project:
                    print(f"  ✓✓ FOUND IT! This table can build employee-project mappings!")
                    working_table = name.split()[-1] if 'FROM' in name else existing_detail[0]
                    working_query = query
                    break
        except Exception as e:
            print(f"  ✗ Failed: {str(e)[:100]}")
    
    if not working_query:
        print("\n" + "="*80)
        print("CANNOT FIND TIME ENTRY DETAIL TABLE")
        print("="*80)
        print("\nThe database structure doesn't match expected Ajera patterns.")
        print("Please manually inspect the tables to find where time entries link to projects.")
        print("\nLikely the data is in a table not yet checked, or uses a different naming convention.")
        conn.close()
        return
    
    # Build the final query
    print("\n" + "="*80)
    print("BUILDING FINAL QUERY")
    print("="*80)
    
    # This will be adjusted based on what we found above
    query = """
        SELECT DISTINCT
            td.employee_column AS employee_id,
            td.project_column AS project_number
        FROM dbo.DetailTable td
        WHERE td.project_column IS NOT NULL 
          AND td.employee_column IS NOT NULL
        ORDER BY td.employee_column, td.project_column
    """
    
    print("⚠️  Query template created but needs manual adjustment based on findings above.")
    
    try:
        print(f"\nExecuting query...")
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"✓ Found {len(rows)} employee-project relationships")
        
        # Build dictionaries
        employee_to_projects = defaultdict(list)
        project_to_employees = defaultdict(list)
        
        for row in rows:
            emp_id, proj_num = row
            
            if proj_num not in employee_to_projects[emp_id]:
                employee_to_projects[emp_id].append(proj_num)
            
            if emp_id not in project_to_employees[proj_num]:
                project_to_employees[proj_num].append(emp_id)
        
        # Convert to final format (names will be empty for now)
        result = {
            "employee_to_projects": {
                emp_id: {
                    "name": "",
                    "projects": projects
                }
                for emp_id, projects in employee_to_projects.items()
            },
            "project_to_employees": {
                proj_num: {
                    "name": "",
                    "employees": employees
                }
                for proj_num, employees in project_to_employees.items()
            },
            "metadata": {
                "total_employees": len(employee_to_projects),
                "total_projects": len(project_to_employees),
            }
        }
        
        # Save to file
        output_file = Path(__file__).parent.parent.parent / "data" / "ajera_mappings.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"\n✓ Saved mappings to: {output_file}")
        print(f"\nSummary:")
        print(f"  Employees: {len(employee_to_projects)}")
        print(f"  Projects: {len(project_to_employees)}")
        
        # Show top contributors
        top_employees = sorted(
            employee_to_projects.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )[:5]
        
        print(f"\nTop 5 employees by project count:")
        for emp_id, projects in top_employees:
            print(f"  {emp_id}: {len(projects)} projects")
        
        conn.close()
        
    except pyodbc.Error as e:
        print(f"\n✗ Query failed: {e}")
        print("\nThe table/column names might be different.")
        print("Check the table list above and adjust the query.")
        conn.close()
        raise


if __name__ == "__main__":
    query_employee_project_mappings()
