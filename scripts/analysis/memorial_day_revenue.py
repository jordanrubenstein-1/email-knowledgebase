#!/usr/bin/env python3
"""Memorial Day 2025 revenue analysis - sale vs rest-of-year comparison."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = 'AIRBYTE_DATABASE'

BRANDS = {
    'TI': {
        'schema': 'LANDING_THE_INSIDE_GA4',
        'sale_start': '20250508',
        'sale_end': '20250602',
        'label': 'The Inside',
    },
    'ID': {
        'schema': 'LANDING_INTERIORDEFINE_GA4',
        'sale_start': '20250509',
        'sale_end': '20250602',
        'label': 'Interior Define',
    },
    'BUR': {
        'schema': 'LANDING_BURROW_GA4',
        'sale_start': '20250509',
        'sale_end': '20250602',
        'label': 'Burrow',
    },
    'HAV': {
        'schema': 'LANDING_HAVENLY_GA4',
        'sale_start': '20250501',  # DPS starts 5/1; CONV starts 5/8 — use broader window
        'sale_end': '20250529',
        'label': 'Havenly',
    },
    'CZ': {
        'schema': 'LANDING_CITIZENRY_GA4',
        'sale_start': '20250513',
        'sale_end': '20250602',
        'label': 'The Citizenry',
    },
}


def run_brand_query(client, schema, sale_start, sale_end):
    """Query GA4 all-channel revenue split by Memorial Day sale vs rest of 2025."""
    query = f"""
    SELECT
        CASE
            WHEN DATE >= '{sale_start}' AND DATE <= '{sale_end}' THEN 'Memorial Day Sale'
            ELSE 'Rest of Year'
        END AS period,
        COUNT(DISTINCT DATE) AS days,
        SUM(TOTALREVENUE) AS total_revenue,
        SUM(ECOMMERCEPURCHASES) AS total_orders,
        ROUND(SUM(TOTALREVENUE) / NULLIF(COUNT(DISTINCT DATE), 0), 2) AS revenue_per_day,
        ROUND(SUM(ECOMMERCEPURCHASES) / NULLIF(COUNT(DISTINCT DATE), 0), 2) AS orders_per_day
    FROM {DB}.{schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
    WHERE DATE >= '20250101' AND DATE <= '20251231'
    GROUP BY 1
    ORDER BY period DESC
    """
    return client.execute_query(query)


def fmt(n):
    if n is None:
        return 'N/A'
    return f"${n:,.0f}"


def main():
    client = get_snowflake_client(schema='LANDING_BURROW_GA4', database=DB)

    print("\n=== Memorial Day 2025 Revenue Analysis (All Channels) ===\n")
    print(f"{'Brand':<20} {'Period':<22} {'Days':>5} {'Total Rev':>12} {'Rev/Day':>12} {'Orders':>8} {'Ord/Day':>9}")
    print("-" * 95)

    totals = {'sale_rev': 0, 'nonsale_rev': 0, 'sale_days': 0, 'nonsale_days': 0,
              'sale_orders': 0, 'nonsale_orders': 0}

    for code, info in BRANDS.items():
        try:
            rows = run_brand_query(client, info['schema'], info['sale_start'], info['sale_end'])
        except Exception as e:
            print(f"{info['label']:<20} ERROR: {e}")
            continue

        brand_data = {}
        for row in rows:
            period = row['PERIOD']
            days = row['DAYS'] or 0
            rev = row['TOTAL_REVENUE'] or 0
            orders = row['TOTAL_ORDERS'] or 0
            rpd = row['REVENUE_PER_DAY'] or 0
            opd = row['ORDERS_PER_DAY'] or 0
            brand_data[period] = {'days': days, 'rev': rev, 'orders': orders, 'rpd': rpd, 'opd': opd}

            if period == 'Memorial Day Sale':
                totals['sale_rev'] += rev
                totals['sale_days'] += days
                totals['sale_orders'] += orders
            else:
                totals['nonsale_rev'] += rev
                totals['nonsale_days'] += days
                totals['nonsale_orders'] += orders

        sale = brand_data.get('Memorial Day Sale', {})
        rest = brand_data.get('Rest of Year', {})
        lift = (sale.get('rpd', 0) / rest.get('rpd', 1) - 1) * 100 if rest.get('rpd') else 0

        print(f"{info['label']:<20} {'Memorial Day Sale':<22} {sale.get('days',0):>5} {fmt(sale.get('rev',0)):>12} {fmt(sale.get('rpd',0)):>12} {sale.get('orders',0):>8,.0f}  {lift:>+.0f}%")
        print(f"{info['label']:<20} {'Rest of Year':<22} {rest.get('days',0):>5} {fmt(rest.get('rev',0)):>12} {fmt(rest.get('rpd',0)):>12} {rest.get('orders',0):>8,.0f}")
        print()

    # Summary
    print("=" * 95)
    sale_rpd = totals['sale_rev'] / totals['sale_days'] if totals['sale_days'] else 0
    nonsale_rpd = totals['nonsale_rev'] / totals['nonsale_days'] if totals['nonsale_days'] else 0
    lift = (sale_rpd / nonsale_rpd - 1) * 100 if nonsale_rpd else 0

    print(f"\n{'TOTAL':<20} {'Memorial Day Sale':<22} {totals['sale_days']:>5} {fmt(totals['sale_rev']):>12} {fmt(sale_rpd):>12} {totals['sale_orders']:>8,.0f}  {lift:>+.0f}%")
    print(f"{'TOTAL':<20} {'Rest of Year':<22} {totals['nonsale_days']:>5} {fmt(totals['nonsale_rev']):>12} {fmt(nonsale_rpd):>12} {totals['nonsale_orders']:>8,.0f}")


if __name__ == '__main__':
    main()
