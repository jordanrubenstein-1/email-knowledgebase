#!/usr/bin/env python3
"""
Explore Snowflake access to find Braze Datashare tables.

This script checks what databases and schemas you have access to,
specifically looking for Braze Datashare data.

Usage:
    python3 scripts/explore_braze_datashare.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Ensure scripts dir is on path
scripts_dir = Path(__file__).parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from snowflake_client import SnowflakeClient
import snowflake.connector
from snowflake.connector import DictCursor


def explore_snowflake_access():
    """Explore what databases/schemas you have access to."""
    
    # Connect without specifying schema to explore
    account = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    password = os.environ.get("SNOWFLAKE_PASSWORD")
    database = os.environ.get("SNOWFLAKE_DATABASE")
    role = os.environ.get("SNOWFLAKE_ROLE")
    authenticator = os.environ.get("SNOWFLAKE_AUTHENTICATOR")
    
    conn_params = {
        "account": account,
        "user": user,
    }
    
    if role:
        conn_params["role"] = role
    
    if authenticator:
        conn_params["authenticator"] = authenticator
    else:
        conn_params["password"] = password
    
    print(f"Connecting to Snowflake as {user} with role {role}...")
    print()
    
    try:
        conn = snowflake.connector.connect(**conn_params)
        cursor = conn.cursor(DictCursor)
        
        # 1. List all databases you have access to
        print("=" * 60)
        print("DATABASES YOU HAVE ACCESS TO")
        print("=" * 60)
        cursor.execute("SHOW DATABASES")
        databases = cursor.fetchall()
        
        braze_databases = []
        for db in databases:
            db_name = db.get("name", "")
            origin = db.get("origin", "")
            print(f"  - {db_name}")
            if origin:
                print(f"      (shared from: {origin})")
            # Look for Braze-related databases
            if "BRAZE" in db_name.upper() or "BRAZE" in origin.upper():
                braze_databases.append(db_name)
        
        print()
        
        # 2. If we found Braze databases, explore their schemas
        if braze_databases:
            print("=" * 60)
            print("BRAZE-RELATED DATABASES FOUND!")
            print("=" * 60)
            for db_name in braze_databases:
                print(f"\nDatabase: {db_name}")
                print("-" * 40)
                
                try:
                    cursor.execute(f"SHOW SCHEMAS IN DATABASE {db_name}")
                    schemas = cursor.fetchall()
                    
                    for schema in schemas:
                        schema_name = schema.get("name", "")
                        print(f"  Schema: {schema_name}")
                        
                        # List tables in schema
                        try:
                            cursor.execute(f"SHOW TABLES IN {db_name}.{schema_name}")
                            tables = cursor.fetchall()
                            for table in tables[:10]:  # First 10 tables
                                table_name = table.get("name", "")
                                print(f"    - {table_name}")
                            if len(tables) > 10:
                                print(f"    ... and {len(tables) - 10} more tables")
                        except Exception as e:
                            print(f"    (Could not list tables: {e})")
                except Exception as e:
                    print(f"  Could not access schemas: {e}")
        else:
            print("No Braze-specific databases found in your accessible databases.")
            print("Let me also search within the current database for Braze schemas...")
            print()
        
        # 3. Check current database for Braze-related schemas
        print("=" * 60)
        print(f"SCHEMAS IN {database} DATABASE")
        print("=" * 60)
        cursor.execute(f"SHOW SCHEMAS IN DATABASE {database}")
        schemas = cursor.fetchall()
        
        braze_schemas = []
        for schema in schemas:
            schema_name = schema.get("name", "")
            print(f"  - {schema_name}")
            if "BRAZE" in schema_name.upper():
                braze_schemas.append(schema_name)
        
        if braze_schemas:
            print()
            print("=" * 60)
            print("BRAZE SCHEMAS FOUND IN AIRBYTE_DATABASE!")
            print("=" * 60)
            for schema_name in braze_schemas:
                print(f"\nSchema: {schema_name}")
                print("-" * 40)
                try:
                    cursor.execute(f"SHOW TABLES IN {database}.{schema_name}")
                    tables = cursor.fetchall()
                    for table in tables:
                        table_name = table.get("name", "")
                        print(f"  - {table_name}")
                except Exception as e:
                    print(f"  Could not list tables: {e}")
        
        # 4. Also check for any schemas that might have Braze data
        print()
        print("=" * 60)
        print("CHECKING FOR BRAZE DATA IN EXISTING SCHEMAS")
        print("=" * 60)
        
        # Common Braze Datashare table names
        braze_table_patterns = [
            "USERS_MESSAGES_EMAIL%",
            "USERS_MESSAGES_SMS%",
            "USERS_CAMPAIGNS%",
            "USERS_CANVAS%",
            "MESSAGES%",
            "EVENTS%",
        ]
        
        for schema in schemas[:20]:  # Check first 20 schemas
            schema_name = schema.get("name", "")
            if schema_name.startswith("INFORMATION_SCHEMA"):
                continue
                
            try:
                cursor.execute(f"SHOW TABLES IN {database}.{schema_name}")
                tables = cursor.fetchall()
                braze_tables = [t for t in tables if any(
                    pattern.replace("%", "") in t.get("name", "").upper()
                    for pattern in braze_table_patterns
                )]
                
                if braze_tables:
                    print(f"\n  Schema {schema_name} has Braze-like tables:")
                    for t in braze_tables[:5]:
                        print(f"    - {t.get('name', '')}")
                    if len(braze_tables) > 5:
                        print(f"    ... and {len(braze_tables) - 5} more")
            except Exception:
                pass
        
        # 5. Try to find Braze data share specifically
        print()
        print("=" * 60)
        print("CHECKING FOR DATA SHARES")
        print("=" * 60)
        try:
            cursor.execute("SHOW SHARES")
            shares = cursor.fetchall()
            if shares:
                print("Data shares available:")
                for share in shares:
                    print(f"  - {share}")
            else:
                print("No data shares visible (may need different permissions)")
        except Exception as e:
            print(f"Could not list shares: {e}")
        
        cursor.close()
        conn.close()
        
        # Summary
        print()
        print("=" * 60)
        print("SUMMARY & NEXT STEPS")
        print("=" * 60)
        
        if braze_databases or braze_schemas:
            print("""
✓ Braze data found in Snowflake!

Next steps:
1. Identify which tables contain the engagement data you need
   (typically: USERS_MESSAGES_EMAIL_SEND, USERS_MESSAGES_EMAIL_OPEN, 
    USERS_MESSAGES_EMAIL_CLICK, etc.)

2. Update scripts to query these tables instead of Braze API

3. Run: python3 scripts/explore_braze_datashare.py --sample <table_name>
   to see sample data and column structure
""")
        else:
            print("""
⚠ No Braze Datashare tables found with MCP_READER role.

Possible reasons:
1. Braze Datashare is in a different database you don't have access to
2. You need a different role to access Braze Datashare
3. Datashare exists but uses different naming conventions

Next steps:
1. Ask your Snowflake admin which database/schema has Braze Datashare
2. Check if you need a different role (BRAZE_READER, DATA_READER, etc.)
3. Verify the Datashare is actually configured for your brands
""")
        
    except Exception as e:
        print(f"Error connecting to Snowflake: {e}")
        sys.exit(1)


def sample_table(table_name: str, database: str = None):
    """Show sample data and schema from a specific table."""
    database = database or os.environ.get("SNOWFLAKE_DATABASE")
    
    account = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    password = os.environ.get("SNOWFLAKE_PASSWORD")
    role = os.environ.get("SNOWFLAKE_ROLE")
    authenticator = os.environ.get("SNOWFLAKE_AUTHENTICATOR")
    
    conn_params = {
        "account": account,
        "user": user,
    }
    
    if role:
        conn_params["role"] = role
    
    if authenticator:
        conn_params["authenticator"] = authenticator
    else:
        conn_params["password"] = password
    
    conn = snowflake.connector.connect(**conn_params)
    cursor = conn.cursor(DictCursor)
    
    print(f"Schema for {table_name}:")
    print("-" * 40)
    cursor.execute(f"DESCRIBE TABLE {table_name}")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col.get('name', '')}: {col.get('type', '')}")
    
    print()
    print(f"Sample data (5 rows):")
    print("-" * 40)
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Explore Braze Datashare in Snowflake")
    parser.add_argument("--sample", type=str, help="Sample data from specific table")
    args = parser.parse_args()
    
    if args.sample:
        sample_table(args.sample)
    else:
        explore_snowflake_access()
