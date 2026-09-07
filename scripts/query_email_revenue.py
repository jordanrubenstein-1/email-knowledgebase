#!/usr/bin/env python3
"""
Query Snowflake GA4 data to find email-attributable revenue and total revenue across brands.

For each brand (BUR, CZ, ID), calculates:
- Total revenue across ALL channels
- Email-attributable revenue (SESSIONPRIMARYCHANNELGROUP = 'Email')
- Email's % of total revenue
- Date range available in data

Usage:
    uv run python scripts/query_email_revenue.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from dotenv import load_dotenv

# Add scripts directory to path
scripts_dir = Path(__file__).parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from snowflake_client import get_snowflake_client

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


def format_currency(amount: float) -> str:
    """Format amount as currency."""
    return f"${amount:,.2f}"


def query_brand_revenue(brand_code: str, schema_name: str) -> Dict[str, Any]:
    """Query revenue metrics for a single brand.

    Args:
        brand_code: Brand code (BUR, CZ, ID)
        schema_name: Snowflake schema name

    Returns:
        Dictionary with total_revenue, email_revenue, date_range, record_count
    """
    table = "TRAFFIC_SESSION_PERFORMANCE_DAILY"
    database = os.environ.get("SNOWFLAKE_DATABASE", "AIRBYTE_DATABASE")
    full_table = f"{database}.{schema_name}.{table}"

    print(f"\n{brand_code} ({schema_name}):")
    print("-" * 60)

    # Create brand-specific client
    try:
        client = get_snowflake_client(schema=schema_name)
        if not client.test_connection():
            print(f"  ERROR: Failed to connect to Snowflake")
            return None
        print(f"  ✓ Connected to Snowflake")
    except Exception as e:
        print(f"  ERROR: Connection failed: {e}")
        return None

    try:
        # Query 1: Date range and record count
        date_query = f"""
            SELECT
                MIN(DATE) AS min_date,
                MAX(DATE) AS max_date,
                COUNT(*) AS record_count
            FROM {full_table}
            WHERE TOTALREVENUE IS NOT NULL
        """

        print(f"  Querying date range...")
        date_results = client.execute_query(date_query)

        if not date_results:
            print(f"  ERROR: No data found")
            return None

        date_info = date_results[0]
        min_date = date_info.get('MIN_DATE') or date_info.get('min_date')
        max_date = date_info.get('MAX_DATE') or date_info.get('max_date')
        record_count = date_info.get('RECORD_COUNT') or date_info.get('record_count')

        print(f"  Date range: {min_date} to {max_date}")
        print(f"  Total records: {record_count:,}")

        # Query 2: Total revenue (all channels)
        total_revenue_query = f"""
            SELECT
                SUM(TOTALREVENUE) AS total_revenue,
                SUM(ECOMMERCEPURCHASES) AS total_purchases,
                SUM(SESSIONS) AS total_sessions
            FROM {full_table}
            WHERE TOTALREVENUE IS NOT NULL
        """

        print(f"  Querying total revenue...")
        total_results = client.execute_query(total_revenue_query)

        if not total_results:
            print(f"  ERROR: No revenue data found")
            return None

        total_row = total_results[0]
        total_revenue = float(total_row.get('TOTAL_REVENUE') or total_row.get('total_revenue') or 0)
        total_purchases = int(total_row.get('TOTAL_PURCHASES') or total_row.get('total_purchases') or 0)
        total_sessions = int(total_row.get('TOTAL_SESSIONS') or total_row.get('total_sessions') or 0)

        print(f"  Total revenue (all channels): {format_currency(total_revenue)}")
        print(f"  Total purchases: {total_purchases:,}")
        print(f"  Total sessions: {total_sessions:,}")

        # Query 3: Email-attributable revenue
        email_revenue_query = f"""
            SELECT
                SUM(TOTALREVENUE) AS email_revenue,
                SUM(ECOMMERCEPURCHASES) AS email_purchases,
                SUM(SESSIONS) AS email_sessions
            FROM {full_table}
            WHERE UPPER(TRIM(SESSIONPRIMARYCHANNELGROUP)) = 'EMAIL'
                AND TOTALREVENUE IS NOT NULL
        """

        print(f"  Querying email-attributable revenue...")
        email_results = client.execute_query(email_revenue_query)

        if not email_results:
            print(f"  ERROR: No email data found")
            return None

        email_row = email_results[0]
        email_revenue = float(email_row.get('EMAIL_REVENUE') or email_row.get('email_revenue') or 0)
        email_purchases = int(email_row.get('EMAIL_PURCHASES') or email_row.get('email_purchases') or 0)
        email_sessions = int(email_row.get('EMAIL_SESSIONS') or email_row.get('email_sessions') or 0)

        print(f"  Email revenue: {format_currency(email_revenue)}")
        print(f"  Email purchases: {email_purchases:,}")
        print(f"  Email sessions: {email_sessions:,}")

        # Calculate percentage
        email_pct = (email_revenue / total_revenue * 100) if total_revenue > 0 else 0
        print(f"  Email % of total: {email_pct:.2f}%")

        return {
            'brand': brand_code,
            'schema': schema_name,
            'date_range': f"{min_date} to {max_date}",
            'min_date': min_date,
            'max_date': max_date,
            'record_count': record_count,
            'total_revenue': total_revenue,
            'total_purchases': total_purchases,
            'total_sessions': total_sessions,
            'email_revenue': email_revenue,
            'email_purchases': email_purchases,
            'email_sessions': email_sessions,
            'email_pct': email_pct,
        }

    except Exception as e:
        print(f"  ERROR: Query failed: {e}")
        return None
    finally:
        client.close()


def main():
    """Main entry point."""
    print("=" * 60)
    print("Email Revenue Attribution Analysis")
    print("=" * 60)
    print(f"Query timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Brand configurations
    brands = [
        ("BUR", "LANDING_BURROW_GA4"),
        ("CZ", "LANDING_CITIZENRY_GA4"),
        ("ID", "LANDING_INTERIORDEFINE_GA4"),
    ]

    # Query each brand
    results = []
    for brand_code, schema_name in brands:
        result = query_brand_revenue(brand_code, schema_name)
        if result:
            results.append(result)

    # Print summary
    if results:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        total_revenue_all = sum(r['total_revenue'] for r in results)
        total_email_revenue = sum(r['email_revenue'] for r in results)
        total_purchases_all = sum(r['total_purchases'] for r in results)
        total_email_purchases = sum(r['email_purchases'] for r in results)
        total_sessions_all = sum(r['total_sessions'] for r in results)
        total_email_sessions = sum(r['email_sessions'] for r in results)

        print(f"\nTotal across all brands:")
        print(f"  All channels revenue: {format_currency(total_revenue_all)}")
        print(f"  Email revenue: {format_currency(total_email_revenue)}")
        print(f"  Email % of total: {(total_email_revenue / total_revenue_all * 100):.2f}%")
        print(f"\n  All channels purchases: {total_purchases_all:,}")
        print(f"  Email purchases: {total_email_purchases:,}")
        print(f"  Email % of purchases: {(total_email_purchases / total_purchases_all * 100):.2f}%")
        print(f"\n  All channels sessions: {total_sessions_all:,}")
        print(f"  Email sessions: {total_email_sessions:,}")
        print(f"  Email % of sessions: {(total_email_sessions / total_sessions_all * 100):.2f}%")

        print(f"\nBy brand:")
        print(f"{'Brand':<6} {'Total Revenue':<20} {'Email Revenue':<20} {'Email %':<10}")
        print("-" * 60)
        for r in results:
            print(f"{r['brand']:<6} {format_currency(r['total_revenue']):<20} "
                  f"{format_currency(r['email_revenue']):<20} {r['email_pct']:>6.2f}%")

        print(f"\nDate ranges:")
        for r in results:
            print(f"  {r['brand']}: {r['date_range']}")
    else:
        print("\nERROR: No results obtained from any brand")
        sys.exit(1)


if __name__ == "__main__":
    main()
