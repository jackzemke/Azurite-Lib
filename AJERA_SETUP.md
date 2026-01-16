# Ajera Database Integration Guide

## Quick Start

### 1. Install Dependencies
```bash
source .venv/bin/activate
pip install pyodbc
```

### 2. Configure Database Connection
Edit `app/backend/config.yaml` and update the `database` section:
```yaml
database:
  driver: "HPD ODBC Driver"
  server: "your-server-hostname"  # e.g., "sql.company.com" or "192.168.1.100"
  database: "Ajera"
  username: "your-username"
  password: "your-password"
```

### 3. Explore Database Schema
```bash
# List all tables
python app/scripts/explore_ajera_db.py --list-tables

# Search for specific tables (employee, project, time, etc.)
python app/scripts/explore_ajera_db.py --search employee
python app/scripts/explore_ajera_db.py --search project
python app/scripts/explore_ajera_db.py --search time

# Describe a specific table
python app/scripts/explore_ajera_db.py --describe-table EM  # Employee table
python app/scripts/explore_ajera_db.py --describe-table PR  # Project table
python app/scripts/explore_ajera_db.py --describe-table TM  # Time entries

# Sample rows from a table
python app/scripts/explore_ajera_db.py --sample-table EM --limit 5
```

### 4. Generate Employee-Project Mappings
```bash
# Generate mappings
python app/scripts/query_ajera_mappings.py --output data/ajera_mappings.json

# Lookup specific employee
python app/scripts/query_ajera_mappings.py --employee "EMP123"

# Lookup specific project
python app/scripts/query_ajera_mappings.py --project "2024-001"
```

## Common Ajera Tables

Based on typical Ajera installations (adjust based on your schema):

- **EM** - Employees (Employee, Name, Title, Department)
- **PR** - Projects (Project, Name, Client, Status)
- **TM** - Time Entries (Employee, Project, Date, Hours)
- **CL** - Clients (Client, Name, Address)
- **DT** - Departments (Department, Name)

## Troubleshooting

### Connection Issues
```bash
# Test ODBC driver is installed
odbcinst -q -d

# Should show "HPD ODBC Driver" in list
```

### Schema Discovery
If table names don't match expectations:
```bash
# List ALL tables
python app/scripts/explore_ajera_db.py --list-tables

# Search for keywords
python app/scripts/explore_ajera_db.py --search emp
python app/scripts/explore_ajera_db.py --search proj
```

### Query Adjustments
If `query_ajera_mappings.py` fails, you need to adjust the SQL query:

1. Find the correct table names:
   ```bash
   python app/scripts/explore_ajera_db.py --search time
   python app/scripts/explore_ajera_db.py --search employee
   ```

2. Inspect the table structure:
   ```bash
   python app/scripts/explore_ajera_db.py --describe-table YOUR_TIME_TABLE
   ```

3. Edit `app/scripts/query_ajera_mappings.py` line ~36 to match your schema:
   ```python
   query = """
       SELECT DISTINCT
           e.EmployeeID AS employee_id,      -- Adjust column name
           e.EmployeeName AS employee_name,  -- Adjust column name
           p.ProjectNumber AS project_number, -- Adjust column name
           p.ProjectName AS project_name      -- Adjust column name
       FROM YourTimeTable AS t
       INNER JOIN YourEmployeeTable AS e ON t.EmpID = e.EmpID
       INNER JOIN YourProjectTable AS p ON t.ProjID = p.ProjID
       WHERE t.ProjectNumber IS NOT NULL
   """
   ```

## Output Format

The mappings JSON will have this structure:
```json
{
  "employee_to_projects": {
    "EMP001": {
      "name": "John Doe",
      "projects": ["2024-001", "2024-005", "2024-012"]
    },
    "EMP002": {
      "name": "Jane Smith",
      "projects": ["2024-001", "2024-003"]
    }
  },
  "project_to_employees": {
    "2024-001": {
      "name": "Highway Bridge Project",
      "employees": ["EMP001", "EMP002", "EMP005"]
    },
    "2024-003": {
      "name": "Drainage System Design",
      "employees": ["EMP002", "EMP007"]
    }
  }
}
```

## Next Steps

Once you have the mappings:
1. Use them to enrich document metadata during ingestion
2. Filter queries by employee or project
3. Build project-specific document collections
4. Create employee work history reports
