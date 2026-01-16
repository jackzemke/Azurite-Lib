"""
Check what metadata exists in Ajera for projects.
"""

import pyodbc

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
conn = pyodbc.connect(conn_str)
print("✓ Connected to Ajera\n")

cursor = conn.cursor()

# Get all columns from AxProject table
print("Columns in AxProject table:")
print("="*80)
cursor.execute("SELECT TOP 1 * FROM dbo.AxProject")
columns = [desc[0] for desc in cursor.description]

for i, col in enumerate(columns):
    print(f"{i+1:3}. {col}")

print("\n" + "="*80)
print("\nSample project data:")
print("="*80)

# Get a sample project with all fields
cursor.execute("""
    SELECT TOP 1 * 
    FROM dbo.AxProject 
    WHERE prjDescription IS NOT NULL
""")

row = cursor.fetchone()
if row:
    for col, val in zip(columns, row):
        # Only show fields that might be useful metadata
        if any(keyword in col.lower() for keyword in ['prj', 'client', 'name', 'desc', 'type', 'status', 'location', 'manager']):
            val_str = str(val)[:100] if val else "NULL"
            print(f"{col:35} = {val_str}")

print("\n" + "="*80)
print("\nChecking how many projects have various metadata:")
print("="*80)

# Count projects with different metadata fields
checks = [
    ("Projects with descriptions", "SELECT COUNT(*) FROM dbo.AxProject WHERE prjDescription IS NOT NULL AND prjDescription != ''"),
    ("Projects with client info", "SELECT COUNT(*) FROM dbo.AxProject WHERE prjClient IS NOT NULL"),
    ("Total projects", "SELECT COUNT(*) FROM dbo.AxProject"),
]

for label, query in checks:
    cursor.execute(query)
    count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM dbo.AxProject")
    total = cursor.fetchone()[0]
    pct = (count/total*100) if total > 0 else 0
    print(f"{label:40} {count:6} ({pct:.1f}%)")

conn.close()
