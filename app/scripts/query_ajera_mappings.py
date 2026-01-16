#!/usr/bin/env python3
"""
Query Ajera database to build employee-project mappings.

Generates two dictionaries:
1. employee_to_projects: {employee_id: [project_numbers]}
2. project_to_employees: {project_number: [employee_ids]}

Usage:
    python query_ajera_mappings.py --output mappings.json
    python query_ajera_mappings.py --employee "John Doe"
    python query_ajera_mappings.py --project "2024-001"
"""

import pyodbc
import argparse
import json
from typing import Dict, List, Any
from pathlib import Path
from collections import defaultdict
import yaml


def get_config():
    """Load config with database connection details."""
    config_path = Path(__file__).parent.parent.parent / "app/backend/config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config


def get_connection(config: dict) -> pyodbc.Connection:
    """Create ODBC connection to Ajera via HDP."""
    db_config = config.get("database", {})
    
    # Use DSN-based connection (credentials passed at runtime)
    if "dsn" in db_config:
        dsn = db_config.get("dsn")
        username = db_config.get("username", "")
        password = db_config.get("password", "")
        
        conn_str = f"DSN={dsn};UID={username};PWD={password};"
        conn = pyodbc.connect(conn_str, timeout=30)
        print(f"✓ Connected to Ajera via DSN: {dsn}")
    else:
        # Direct connection fallback
        driver = db_config.get("driver", "HPD ODBC Driver")
        service = db_config.get("service", "")
        port = db_config.get("port", 443)
        source = db_config.get("source", "")
        username = db_config.get("username", "")
        password = db_config.get("password", "")
        
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"Service={service};"
            f"Port={port};"
            f"Source={source};"
            f"UID={username};"
            f"PWD={password};"
        )
        conn = pyodbc.connect(conn_str, timeout=30)
        print(f"✓ Connected to Ajera database")
    
    return conn


def query_employee_project_mappings(conn: pyodbc.Connection) -> tuple[Dict, Dict]:
    """
    Query Ajera to build employee-project mappings.
    
    Returns:
        (employee_to_projects, project_to_employees)
    
    Note: Adjust table/column names based on your Ajera schema.
    Common Ajera tables: PR (projects), EM (employees), TM (time entries)
    """
    cursor = conn.cursor()
    
    # TODO: Adjust this query based on actual Ajera schema
    # This is a typical pattern - adjust table/column names as needed
    query = """
        SELECT DISTINCT
            e.Employee AS employee_id,
            e.Name AS employee_name,
            p.Project AS project_number,
            p.Name AS project_name
        FROM TM AS t  -- Time entries (adjust table name)
        INNER JOIN EM AS e ON t.Employee = e.Employee  -- Employees
        INNER JOIN PR AS p ON t.Project = p.Project     -- Projects
        WHERE t.Project IS NOT NULL 
          AND t.Employee IS NOT NULL
        ORDER BY e.Employee, p.Project
    """
    
    print("\nQuerying employee-project relationships...")
    
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"✓ Found {len(rows)} employee-project relationships")
        
        # Build dictionaries
        employee_to_projects = defaultdict(list)
        project_to_employees = defaultdict(list)
        employee_names = {}
        project_names = {}
        
        for row in rows:
            emp_id, emp_name, proj_num, proj_name = row
            
            # Store names for reference
            employee_names[emp_id] = emp_name
            project_names[proj_num] = proj_name
            
            # Build mappings
            if proj_num not in employee_to_projects[emp_id]:
                employee_to_projects[emp_id].append(proj_num)
            
            if emp_id not in project_to_employees[proj_num]:
                project_to_employees[proj_num].append(emp_id)
        
        # Convert defaultdict to regular dict
        result_emp_to_proj = {
            emp_id: {
                "name": employee_names.get(emp_id, ""),
                "projects": projects
            }
            for emp_id, projects in employee_to_projects.items()
        }
        
        result_proj_to_emp = {
            proj_num: {
                "name": project_names.get(proj_num, ""),
                "employees": employees
            }
            for proj_num, employees in project_to_employees.items()
        }
        
        return result_emp_to_proj, result_proj_to_emp
        
    except pyodbc.Error as e:
        print(f"\n✗ Query failed: {e}")
        print("\nCommon issues:")
        print("  1. Table names incorrect (check with explore_ajera_db.py --list-tables)")
        print("  2. Column names don't match schema")
        print("  3. Permissions issue")
        print("\nTry exploring the schema first:")
        print("  python app/scripts/explore_ajera_db.py --search time")
        print("  python app/scripts/explore_ajera_db.py --search employee")
        print("  python app/scripts/explore_ajera_db.py --search project")
        raise


def print_summary(emp_to_proj: Dict, proj_to_emp: Dict):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("MAPPING SUMMARY")
    print("="*80)
    
    print(f"\nTotal employees: {len(emp_to_proj)}")
    print(f"Total projects: {len(proj_to_emp)}")
    
    # Top employees by project count
    top_employees = sorted(
        emp_to_proj.items(),
        key=lambda x: len(x[1]["projects"]),
        reverse=True
    )[:5]
    
    print("\nTop 5 employees by project count:")
    for emp_id, data in top_employees:
        print(f"  {emp_id} ({data['name']}): {len(data['projects'])} projects")
    
    # Top projects by employee count
    top_projects = sorted(
        proj_to_emp.items(),
        key=lambda x: len(x[1]["employees"]),
        reverse=True
    )[:5]
    
    print("\nTop 5 projects by employee count:")
    for proj_num, data in top_projects:
        print(f"  {proj_num} ({data['name']}): {len(data['employees'])} employees")


def lookup_employee(emp_to_proj: Dict, employee_id: str):
    """Lookup projects for a specific employee."""
    if employee_id in emp_to_proj:
        data = emp_to_proj[employee_id]
        print(f"\nEmployee: {employee_id} ({data['name']})")
        print(f"Projects: {len(data['projects'])}")
        for proj in data['projects']:
            print(f"  - {proj}")
    else:
        print(f"\n✗ Employee '{employee_id}' not found")


def lookup_project(proj_to_emp: Dict, project_number: str):
    """Lookup employees for a specific project."""
    if project_number in proj_to_emp:
        data = proj_to_emp[project_number]
        print(f"\nProject: {project_number} ({data['name']})")
        print(f"Employees: {len(data['employees'])}")
        for emp in data['employees']:
            print(f"  - {emp}")
    else:
        print(f"\n✗ Project '{project_number}' not found")


def main():
    parser = argparse.ArgumentParser(description="Query Ajera employee-project mappings")
    parser.add_argument("--output", type=str, help="Save mappings to JSON file")
    parser.add_argument("--employee", type=str, help="Lookup specific employee")
    parser.add_argument("--project", type=str, help="Lookup specific project")
    
    args = parser.parse_args()
    
    # Load config and connect
    config = get_config()
    conn = get_connection(config)
    
    try:
        # Query mappings
        emp_to_proj, proj_to_emp = query_employee_project_mappings(conn)
        
        # Show summary
        print_summary(emp_to_proj, proj_to_emp)
        
        # Handle specific lookups
        if args.employee:
            lookup_employee(emp_to_proj, args.employee)
        
        if args.project:
            lookup_project(proj_to_emp, args.project)
        
        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            output_data = {
                "employee_to_projects": emp_to_proj,
                "project_to_employees": proj_to_emp,
                "metadata": {
                    "total_employees": len(emp_to_proj),
                    "total_projects": len(proj_to_emp),
                    "generated_at": str(Path(__file__).parent.parent.parent / "app/backend/config.yaml")
                }
            }
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"\n✓ Saved mappings to: {output_path}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
