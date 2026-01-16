"""
Comprehensive search for employee-project mappings in Ajera.
This script searches ALL tables for columns containing employee and project references.
"""

import pyodbc
import json
from pathlib import Path
from collections import defaultdict

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

def search_all_tables_for_mappings():
    """Search every table for employee + project columns."""
    
    conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
    conn = pyodbc.connect(conn_str)
    print("✓ Connected to Ajera\n")
    
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    
    tables = [(s, t) for s, t in cursor.fetchall()]
    print(f"Searching {len(tables)} tables for employee-project links...\n")
    
    candidates = []
    
    for i, (schema, table_name) in enumerate(tables):
        if i % 20 == 0:
            print(f"Progress: {i}/{len(tables)} tables checked...")
        
        try:
            # Get columns for this table
            cursor.execute(f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (schema, table_name))
            
            columns = [row[0] for row in cursor.fetchall()]
            col_lower = [c.lower() for c in columns]
            
            # Check if table has both employee and project references
            has_employee = any('emp' in c for c in col_lower)
            has_project = any('prj' in c or 'project' in c for c in col_lower)
            
            if has_employee and has_project:
                # Found a candidate! Get sample data
                cursor.execute(f"SELECT TOP 3 * FROM {schema}.{table_name}")
                rows = cursor.fetchall()
                
                if rows:
                    candidates.append({
                        'table': f"{schema}.{table_name}",
                        'columns': columns,
                        'sample': dict(zip(columns, rows[0])),
                        'row_count': len(rows)
                    })
        
        except Exception as e:
            # Skip tables we can't access
            pass
    
    print(f"\n{'='*80}")
    print(f"FOUND {len(candidates)} TABLES WITH EMPLOYEE + PROJECT COLUMNS")
    print('='*80)
    
    for i, cand in enumerate(candidates, 1):
        print(f"\n{i}. {cand['table']}")
        print(f"   Columns ({len(cand['columns'])}): {', '.join(cand['columns'][:20])}")
        if len(cand['columns']) > 20:
            print(f"   ... and {len(cand['columns']) - 20} more")
        
        # Show fields that look like employee or project
        emp_cols = [c for c in cand['columns'] if 'emp' in c.lower()]
        proj_cols = [c for c in cand['columns'] if 'prj' in c.lower() or 'project' in c.lower()]
        
        print(f"   Employee fields: {emp_cols}")
        print(f"   Project fields: {proj_cols}")
        print(f"   Sample row: {dict(list(cand['sample'].items())[:8])}")
    
    # Now test the most promising candidates
    print(f"\n{'='*80}")
    print("TESTING CANDIDATE TABLES")
    print('='*80)
    
    for cand in candidates[:10]:  # Test top 10
        table = cand['table']
        columns = cand['columns']
        
        # Find employee and project column names
        emp_col = next((c for c in columns if 'employee' in c.lower()), None)
        if not emp_col:
            emp_col = next((c for c in columns if c.lower().endswith('emp') or c.lower().startswith('emp')), None)
        
        proj_col = next((c for c in columns if 'project' in c.lower()), None)
        if not proj_col:
            proj_col = next((c for c in columns if c.lower().endswith('prj') or 'prj' in c.lower()), None)
        
        if emp_col and proj_col:
            print(f"\n{table}:")
            print(f"  Employee column: {emp_col}")
            print(f"  Project column: {proj_col}")
            
            try:
                query = f"""
                    SELECT DISTINCT {emp_col}, {proj_col}
                    FROM {table}
                    WHERE {emp_col} IS NOT NULL AND {proj_col} IS NOT NULL
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                
                print(f"  ✓ Query works! Found {len(rows)} distinct employee-project pairs")
                
                if len(rows) > 0:
                    print(f"  Sample pairs:")
                    for row in rows[:5]:
                        print(f"    Employee {row[0]} → Project {row[1]}")
                    
                    # This table can build mappings!
                    print(f"\n  ✓✓ THIS TABLE CAN BUILD YOUR MAPPINGS!")
                    
                    # Ask if we should use it
                    print(f"\n  Use this table? It has {len(rows)} employee-project relationships")
                    
                    # Build mappings from this table
                    employee_to_projects = defaultdict(list)
                    project_to_employees = defaultdict(list)
                    
                    for emp_id, proj_id in rows:
                        if proj_id not in employee_to_projects[emp_id]:
                            employee_to_projects[emp_id].append(proj_id)
                        if emp_id not in project_to_employees[proj_id]:
                            project_to_employees[proj_id].append(emp_id)
                    
                    result = {
                        "source_table": table,
                        "employee_column": emp_col,
                        "project_column": proj_col,
                        "employee_to_projects": {
                            emp_id: {"name": "", "projects": projects}
                            for emp_id, projects in employee_to_projects.items()
                        },
                        "project_to_employees": {
                            proj_id: {"name": "", "employees": employees}
                            for proj_id, employees in project_to_employees.items()
                        },
                        "metadata": {
                            "total_employees": len(employee_to_projects),
                            "total_projects": len(project_to_employees),
                            "total_relationships": len(rows)
                        }
                    }
                    
                    # Save it
                    output_file = Path(__file__).parent.parent.parent / "data" / "ajera_mappings.json"
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(output_file, 'w') as f:
                        json.dump(result, f, indent=2)
                    
                    print(f"\n✓ SAVED MAPPINGS TO: {output_file}")
                    print(f"\nSummary:")
                    print(f"  Source: {table}")
                    print(f"  Employees: {result['metadata']['total_employees']}")
                    print(f"  Projects: {result['metadata']['total_projects']}")
                    print(f"  Relationships: {result['metadata']['total_relationships']}")
                    
                    # Show top contributors
                    top_emp = sorted(employee_to_projects.items(), key=lambda x: len(x[1]), reverse=True)[:5]
                    print(f"\n  Top 5 employees by project count:")
                    for emp_id, projects in top_emp:
                        print(f"    Employee {emp_id}: {len(projects)} projects")
                    
                    conn.close()
                    return
                    
            except Exception as e:
                print(f"  ✗ Query failed: {str(e)[:100]}")
    
    print("\n" + "="*80)
    print("SEARCH COMPLETE")
    print("="*80)
    print(f"\nReview the {len(candidates)} candidate tables above.")
    print("The data exists - it's in one of these tables!")
    
    conn.close()


if __name__ == "__main__":
    search_all_tables_for_mappings()
