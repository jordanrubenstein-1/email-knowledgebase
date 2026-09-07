#!/usr/bin/env python3
"""
Snowflake connection and query utilities for GA4 data.

Provides a reusable Snowflake client with connection pooling and error handling.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from dotenv import load_dotenv
import snowflake.connector
from snowflake.connector import DictCursor

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


class SnowflakeClient:
    """Snowflake client with connection management."""
    
    def __init__(self, schema=None, database=None):
        """Initialize Snowflake client with credentials from environment.

        Args:
            schema: Optional schema name to use (overrides SNOWFLAKE_SCHEMA)
            database: Optional database name to use (overrides SNOWFLAKE_DATABASE)
        """
        self.account = os.environ.get("SNOWFLAKE_ACCOUNT")
        self.user = os.environ.get("SNOWFLAKE_USER")
        self.password = os.environ.get("SNOWFLAKE_PASSWORD")
        self.warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE") or None  # Optional
        self.database = database or os.environ.get("SNOWFLAKE_DATABASE")
        self.schema = schema or os.environ.get("SNOWFLAKE_SCHEMA")
        self.role = os.environ.get("SNOWFLAKE_ROLE")
        self.authenticator = os.environ.get("SNOWFLAKE_AUTHENTICATOR")  # e.g., "externalbrowser"
        
        # Validate required config
        required = {
            "SNOWFLAKE_ACCOUNT": self.account,
            "SNOWFLAKE_USER": self.user,
            "SNOWFLAKE_DATABASE": self.database,
            "SNOWFLAKE_SCHEMA": self.schema,
        }
        
        # Password or authenticator must be set
        if not self.password and not self.authenticator:
            required["SNOWFLAKE_PASSWORD or SNOWFLAKE_AUTHENTICATOR"] = None
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            print(f"Error: Missing required Snowflake configuration in .env:")
            for key in missing:
                print(f"  - {key}")
            sys.exit(1)
        
        self._connection = None
    
    @contextmanager
    def get_connection(self):
        """Get a Snowflake connection (context manager for auto-close)."""
        try:
            if self._connection is None or self._connection.is_closed():
                # Build connection parameters
                conn_params = {
                    "account": self.account,
                    "user": self.user,
                    "database": self.database,
                    "schema": self.schema,
                }
                
                # Add warehouse if specified
                if self.warehouse:
                    conn_params["warehouse"] = self.warehouse
                
                # Add role if specified
                if self.role:
                    conn_params["role"] = self.role
                
                # Use authenticator if specified, otherwise use password
                if self.authenticator:
                    conn_params["authenticator"] = self.authenticator
                else:
                    conn_params["password"] = self.password
                
                self._connection = snowflake.connector.connect(**conn_params)
            yield self._connection
        except Exception as e:
            print(f"Error connecting to Snowflake: {e}")
            raise
    
    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results as list of dictionaries.
        
        Args:
            query: SQL query string (use %(param_name)s for parameterized queries)
            params: Dictionary of parameters for parameterized queries
            max_retries: Maximum number of retry attempts on failure
            
        Returns:
            List of dictionaries, one per row
        """
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor(DictCursor)
                    
                    # Execute with parameters if provided
                    # Snowflake connector uses %(name)s syntax for named parameters
                    if params:
                        # Convert dict to tuple for positional params, or use dict for named params
                        # Snowflake supports both, but named params use %(name)s syntax
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    
                    results = cursor.fetchall()
                    cursor.close()
                    return results
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Error executing query after {max_retries} attempts: {e}")
                    print(f"Query: {query[:200]}...")
                    raise
                # Exponential backoff
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
        
        return []
    
    def execute_query_iter(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        chunk_size: int = 5000,
    ):
        """Execute a query and yield rows in chunks instead of materializing all
        of them at once. Use for large result sets (e.g. per-user payloads with
        big nested arrays) where fetchall() would blow the process memory limit.

        Yields:
            Lists of dictionaries, at most `chunk_size` rows per list.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor(DictCursor)
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                while True:
                    rows = cursor.fetchmany(chunk_size)
                    if not rows:
                        break
                    yield rows
            finally:
                cursor.close()

    def test_connection(self) -> bool:
        """Test Snowflake connection by running a simple query."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 as test")
                result = cursor.fetchone()
                cursor.close()
                return result[0] == 1
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False
    
    def close(self):
        """Close the Snowflake connection."""
        if self._connection and not self._connection.is_closed():
            self._connection.close()
            self._connection = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()


def get_snowflake_client(schema=None, database=None) -> SnowflakeClient:
    """Get a configured Snowflake client instance.

    Args:
        schema: Optional schema name to use (overrides SNOWFLAKE_SCHEMA)
        database: Optional database name to use (overrides SNOWFLAKE_DATABASE)
    """
    return SnowflakeClient(schema=schema, database=database)


if __name__ == "__main__":
    # Test connection
    print("Testing Snowflake connection...")
    # Try with a default schema if SNOWFLAKE_SCHEMA is not set
    default_schema = os.environ.get("SNOWFLAKE_SCHEMA") or "LANDING_BURROW_GA4"
    client = get_snowflake_client(schema=default_schema)
    if client.test_connection():
        print(f"✓ Connection successful! (schema: {client.schema})")
    else:
        print("✗ Connection failed!")
        sys.exit(1)
