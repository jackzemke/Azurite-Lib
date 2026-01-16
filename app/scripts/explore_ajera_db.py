#!/usr/bin/env python3
"""
Explore Ajera SQL Server database schema via ODBC.

Usage:
    python explore_ajera_db.py --list-tables
    python explore_ajera_db.py --describe-table PR
    python explore_ajera_db.py --sample-table PR --limit 5
"""

import pyodbc
import argparse
from typing import List, Dict, Any
from pathlib import Path
import yaml
import sys


def get_config():
    """Load config with database connection details."""
    config_path = Path(__file__).parent.parent.parent / "app/backend/config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config


def get_connection(config: dict) -> pyodbc.Connection:
    """Create ODBC connection to Ajera via HDP."""
    db_config = config.get("database", {})
    
    # Check if using DSN (preferred for HDP)
    if "dsn" in db_config:
        # DSN-based connection (uses credentials from ODBC Administrator + runtime auth)
        dsn = db_config.get("dsn")
        username = db_config.get("username", "")
        password = db_config.get("password", "")
        
        conn_str = f"DSN={dsn};UID={username};PWD={password};"
        
        try:
            conn = pyodbc.connect(conn_str, timeout=30)
            print(f"✓ Connected via DSN: {dsn}")
            return conn
        except pyodbc.Error as e:
            print(f"✗ Connection failed: {e}")
            print("\nTroubleshooting:")
            print(f"  1. Verify DSN exists: odbcinst -q -s")
            print(f"  2. Check DSN '{dsn}' is configured in ODBC Administrator")
            print(f"  3. Verify username/password are correct")
            print(f"  4. Test connection in ODBC Administrator first")
            sys.exit(1)
    else:
        # Direct connection (alternative)
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
        
        try:
            conn = pyodbc.connect(conn_str, timeout=30)
            print(f"✓ Connected to {service}")
            return conn
        except pyodbc.Error as e:
            print(f"✗ Connection failed: {e}")
            sys.exit(1)


def list_tables(conn: pyodbc.Connection) -> List[str]:
    """List all tables in the database."""
    cursor = conn.cursor()
    tables = []
    
    # Query system catalog
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    
    print("\n" + "="*80)
    print("AVAILABLE TABLES")
    print("="*80)
    
    for row in cursor.fetchall():
        schema, name, table_type = row
        table_full = f"{schema}.{name}" if schema != 'dbo' else name
        tables.append(table_full)
        print(f"  {table_full}")
    
    print(f"\nTotal: {len(tables)} tables")
    return tables


def describe_table(conn: pyodbc.Connection, table_name: str):
    """Describe table schema (columns, types, constraints)."""
    cursor = conn.cursor()
    
    # Parse schema if provided
    parts = table_name.split('.')
    if len(parts) == 2:
        schema, table = parts
    else:
        schema, table = 'dbo', table_name
    
    # Get column information
    cursor.execute("""
        SELECT 
            COLUMN_NAME,
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            IS_NULLABLE,
            COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, (schema, table))
    
    columns = cursor.fetchall()
    
    if not columns:
        print(f"✗ Table '{table_name}' not found")
        return
    
    print("\n" + "="*80)
    print(f"TABLE: {schema}.{table}")
    print("="*80)
    
    print(f"\n{'Column':<30} {'Type':<20} {'Nullable':<10} {'Default':<20}")
    print("-"*80)
    
    for col in columns:
        col_name, data_type, max_len, nullable, default = col
        
        # Format type with length
        if max_len:
            type_str = f"{data_type}({max_len})"
        else:
            type_str = data_type
        
        nullable_str = "YES" if nullable == "YES" else "NO"
        default_str = str(default)[:20] if default else ""
        
        print(f"{col_name:<30} {type_str:<20} {nullable_str:<10} {default_str:<20}")
    
    # Get row count
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        count = cursor.fetchone()[0]
        print(f"\nTotal rows: {count:,}")
    except Exception as e:
        print(f"\nCouldn't get row count: {e}")


def sample_table(conn: pyodbc.Connection, table_name: str, limit: int = 10):
    """Show sample rows from table."""
    cursor = conn.cursor()
    
    # Parse schema if provided
    parts = table_name.split('.')
    if len(parts) == 2:
        schema, table = parts
    else:
        schema, table = 'dbo', table_name
    
    try:
        cursor.execute(f"SELECT TOP {limit} * FROM {schema}.{table}")
        rows = cursor.fetchall()
        
        if not rows:
            print(f"Table '{table_name}' is empty")
            return
        
        # Get column names
        columns = [desc[0] for desc in cursor.description]
        
        print("\n" + "="*80)
        print(f"SAMPLE ROWS: {schema}.{table} (showing {len(rows)} of {limit})")
        print("="*80 + "\n")
        
        # Print rows as dict-like format
        for i, row in enumerate(rows, 1):
            print(f"Row {i}:")
            for col, val in zip(columns, row):
                # Truncate long values
                val_str = str(val)[:100] if val else "NULL"
                print(f"  {col}: {val_str}")
            print()
        
    except Exception as e:
        print(f"✗ Error sampling table: {e}")


def search_tables(conn: pyodbc.Connection, keyword: str):
    """Search for tables matching keyword."""
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND (TABLE_NAME LIKE ? OR TABLE_SCHEMA LIKE ?)
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """, (f"%{keyword}%", f"%{keyword}%"))
    
    results = cursor.fetchall()
    
    print("\n" + "="*80)
    print(f"TABLES MATCHING '{keyword}'")
    print("="*80)
    
    if not results:
        print("  No matches found")
    else:
        for schema, name in results:
            print(f"  {schema}.{name}")
    
    print(f"\nFound: {len(results)} tables")


def main():
    parser = argparse.ArgumentParser(description="Explore Ajera SQL Server database")
    parser.add_argument("--list-tables", action="store_true", help="List all tables")
    parser.add_argument("--describe-table", type=str, help="Describe table schema")
    parser.add_argument("--sample-table", type=str, help="Show sample rows from table")
    parser.add_argument("--limit", type=int, default=10, help="Limit for sample rows")
    parser.add_argument("--search", type=str, help="Search for tables matching keyword")
    
    args = parser.parse_args()
    
    # Load config and connect
    config = get_config()
    conn = get_connection(config)
    
    try:
        if args.list_tables:
            list_tables(conn)
        elif args.describe_table:
            describe_table(conn, args.describe_table)
        elif args.sample_table:
            sample_table(conn, args.sample_table, args.limit)
        elif args.search:
            search_tables(conn, args.search)
        else:
            print("No action specified. Use --help for usage.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
