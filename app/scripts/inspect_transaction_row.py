"""
Inspect a single AxTransaction row to see all columns and their values.
"""

import pyodbc

DSN = "Ajera"
USERNAME = "04864.DRodriguez.prd"
PASSWORD = "auQdQ#OV0BN0"

conn_str = f"DSN={DSN};UID={USERNAME};PWD={PASSWORD};"
conn = pyodbc.connect(conn_str)
print("✓ Connected to Ajera\n")

cursor = conn.cursor()

# Get one transaction with all fields
cursor.execute("""
    SELECT TOP 1 * 
    FROM dbo.AxTransaction 
    WHERE tEmployee IS NOT NULL 
      AND tProject IS NOT NULL 
      AND tDate IS NOT NULL
      AND tDate >= DATEADD(year, -1, GETDATE())
""")

row = cursor.fetchone()
columns = [desc[0] for desc in cursor.description]

print("Sample Transaction Row:")
print("="*80)
for col, val in zip(columns, row):
    # Only show columns that might be hours/time/quantity related
    col_lower = col.lower()
    if any(keyword in col_lower for keyword in ['hour', 'time', 'qty', 'quantity', 'amount', 'labor', 'unit']):
        print(f"{col:40} = {val}")

print("\n" + "="*80)
print("\nALL COLUMNS (for reference):")
print("="*80)
for col, val in zip(columns, row):
    val_str = str(val)[:60] if val is not None else "NULL"
    print(f"{col:40} = {val_str}")

conn.close()
