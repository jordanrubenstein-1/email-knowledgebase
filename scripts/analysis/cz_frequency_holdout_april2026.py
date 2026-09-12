#!/usr/bin/env python3
"""
CZ Frequency Holdout Test — April 2026 Statistical Analysis
============================================================
Verifies Mina Cohen's holdout analysis using raw Braze + Shopify Snowflake data.

Background: The original report showed holdout (fewer emails) unsubscribing at 5–7×
the rate of control (more emails), which is counterintuitive. The likely cause is
a per-send denominator (unsub events / total sends) rather than a per-user rate
(unique unsubs / users in group). This script computes all metrics per-user.

Holdout  = Braze random bucket 0–1999   (CSV: Full_File_List-Holdout.csv)
Control  = Braze random bucket 2000–3999 (CSV: Full_File_List-Non-Holdout.csv)

Users are matched from Braze datashare on EXTERNAL_USER_ID (non-UUID) and EMAIL_ADDRESS.
Shopify orders matched on email only (Braze purchase events for CZ ended Aug 2025).

Stat tests:
  - Proportions (opens, clicks, unsubs, purchase rate): two-sided z-test
  - Revenue/user, AOV: Mann-Whitney U (non-normal, zero-inflated)

Usage:
    uv run python scripts/analysis/cz_frequency_holdout_april2026.py

Inputs (not committed — local downloads):
    ~/Downloads/Full_File_List-Holdout (1).csv
    ~/Downloads/Full_File_List-Non-Holdout (1).csv
"""

import csv
import os
import re
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from scripts.snowflake_client import get_snowflake_client

DB = 'BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206'
SCHEMA = 'DATALAKE_SHARING'
CZ = '666672a4d8965b005ac6c1bd'

HOLDOUT_CSV = os.path.expanduser('~/Downloads/Full_File_List-Holdout (1).csv')
CONTROL_CSV = os.path.expanduser('~/Downloads/Full_File_List-Non-Holdout (1).csv')


def is_uuid(s):
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', s, re.I))


def load_list(path):
    """Return (emails_set, ext_ids_set) from a Braze segment export CSV."""
    emails, ext_ids = set(), set()
    for row in csv.DictReader(open(path)):
        e = (row.get('email') or '').strip().lower()
        u = (row.get('user_id') or '').strip()
        if e:
            emails.add(e)
        if u and not is_uuid(u):
            ext_ids.add(u)
    return emails, ext_ids


def assign_group(ext, email, h_ext, h_emails, c_ext, c_emails):
    ext = (ext or '').strip()
    email = (email or '').strip().lower()
    in_h = (ext and ext in h_ext) or (email and email in h_emails)
    in_c = (ext and ext in c_ext) or (email and email in c_emails)
    if in_h:
        return 'holdout'
    if in_c:
        return 'control'
    return None


def prop_ztest_pval(count_h, count_c, n_h, n_c):
    """Two-sided z-test for difference in proportions."""
    p_pool = (count_h + count_c) / (n_h + n_c)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n_h + 1 / n_c))
    if se == 0:
        return 1.0
    z = (count_h / n_h - count_c / n_c) / se
    return float(2 * (1 - stats.norm.cdf(abs(z))))


def mwu_pval(a, b):
    """Two-sided Mann-Whitney U test p-value."""
    if len(a) < 2 or len(b) < 2:
        return 1.0
    _, p = stats.mannwhitneyu(a, b, alternative='two-sided')
    return float(p)


def fmt_pct(n, d):
    return f"{100 * n / d:.2f}%" if d else "N/A"


def fmt_p(p):
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}"


def sig(p):
    if p < 0.05:
        return "Yes **"
    if p < 0.10:
        return "Marginal *"
    return "No"


def main():
    h_emails, h_ext = load_list(HOLDOUT_CSV)
    c_emails, c_ext = load_list(CONTROL_CSV)
    print(f"Holdout:  {len(h_emails):,} emails, {len(h_ext):,} ext_ids")
    print(f"Control:  {len(c_emails):,} emails, {len(c_ext):,} ext_ids")

    client = get_snowflake_client(schema=SCHEMA, database=DB)

    def tag(ext, email):
        return assign_group(ext, email, h_ext, h_emails, c_ext, c_emails)

    def unique_key(ext, email):
        return (ext or '') + '|' + (email or '').lower()

    # Opens
    print("Fetching opens...")
    rows = client.execute_query(f"""
        SELECT DISTINCT EXTERNAL_USER_ID, EMAIL_ADDRESS
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
        WHERE APP_GROUP_ID = '{CZ}'
          AND TO_TIMESTAMP(TIME) >= '2026-04-01'
          AND TO_TIMESTAMP(TIME) <  '2026-05-01'
          AND (MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false')
    """)
    h_opened, c_opened = set(), set()
    for r in rows:
        g = tag(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        k = unique_key(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        if g == 'holdout':
            h_opened.add(k)
        elif g == 'control':
            c_opened.add(k)
    print(f"  Holdout: {len(h_opened):,}  Control: {len(c_opened):,}")

    # Clicks
    print("Fetching clicks...")
    rows = client.execute_query(f"""
        SELECT DISTINCT EXTERNAL_USER_ID, EMAIL_ADDRESS
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
        WHERE APP_GROUP_ID = '{CZ}'
          AND TO_TIMESTAMP(TIME) >= '2026-04-01'
          AND TO_TIMESTAMP(TIME) <  '2026-05-01'
          AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
    """)
    h_clicked, c_clicked = set(), set()
    for r in rows:
        g = tag(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        k = unique_key(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        if g == 'holdout':
            h_clicked.add(k)
        elif g == 'control':
            c_clicked.add(k)
    print(f"  Holdout: {len(h_clicked):,}  Control: {len(c_clicked):,}")

    # Unsubs
    print("Fetching unsubs...")
    rows = client.execute_query(f"""
        SELECT DISTINCT EXTERNAL_USER_ID, EMAIL_ADDRESS
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
        WHERE APP_GROUP_ID = '{CZ}'
          AND TO_TIMESTAMP(TIME) >= '2026-04-01'
          AND TO_TIMESTAMP(TIME) <  '2026-05-01'
    """)
    h_unsubbed, c_unsubbed = set(), set()
    for r in rows:
        g = tag(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        k = unique_key(r['EXTERNAL_USER_ID'], r['EMAIL_ADDRESS'])
        if g == 'holdout':
            h_unsubbed.add(k)
        elif g == 'control':
            c_unsubbed.add(k)
    print(f"  Holdout: {len(h_unsubbed):,}  Control: {len(c_unsubbed):,}")

    # Shopify orders (Braze purchase events for CZ ended Aug 2025)
    print("Fetching Shopify orders...")
    shopify_client = get_snowflake_client(schema='LANDING_CZ_SHOPIFY', database='FIVETRAN_DB')
    order_rows = shopify_client.execute_query("""
        SELECT LOWER(EMAIL) AS EMAIL, TOTAL_PRICE
        FROM FIVETRAN_DB.LANDING_CZ_SHOPIFY."ORDER"
        WHERE PROCESSED_AT >= '2026-04-01'
          AND PROCESSED_AT <  '2026-05-01'
          AND CANCELLED_AT IS NULL
          AND (_FIVETRAN_DELETED = FALSE OR _FIVETRAN_DELETED IS NULL)
          AND (TEST = FALSE OR TEST IS NULL)
          AND FINANCIAL_STATUS IN ('paid','partially_paid','partially_refunded')
          AND EMAIL IS NOT NULL
    """)
    h_rev_by_user, c_rev_by_user = {}, {}
    for r in order_rows:
        email = (r['EMAIL'] or '').strip().lower()
        price = float(r['TOTAL_PRICE'] or 0)
        if email in h_emails:
            h_rev_by_user[email] = h_rev_by_user.get(email, 0) + price
        elif email in c_emails:
            c_rev_by_user[email] = c_rev_by_user.get(email, 0) + price

    h_buyer_emails = set(h_rev_by_user)
    c_buyer_emails = set(c_rev_by_user)
    print(f"  Holdout buyers: {len(h_buyer_emails):,}  Control buyers: {len(c_buyer_emails):,}")

    h_n = len(h_emails)
    c_n = len(c_emails)

    h_rev_vec = [h_rev_by_user.get(e, 0.0) for e in h_emails]
    c_rev_vec = [c_rev_by_user.get(e, 0.0) for e in c_emails]
    h_rev_total = sum(h_rev_vec)
    c_rev_total = sum(c_rev_vec)

    h_aov_vec = list(h_rev_by_user.values())
    c_aov_vec = list(c_rev_by_user.values())

    # Results table
    print("\n" + "=" * 90)
    print(f"{'Metric':<26} {'Holdout':>12} {'Control':>12} {'Delta':>10} {'p-value':>10} {'Sig?':>10}")
    print("=" * 90)

    proportion_metrics = [
        ("% opened any email",   len(h_opened),       len(c_opened),       h_n, c_n),
        ("% clicked any email",  len(h_clicked),      len(c_clicked),      h_n, c_n),
        ("% unsubscribed",       len(h_unsubbed),     len(c_unsubbed),     h_n, c_n),
        ("% made a purchase",    len(h_buyer_emails), len(c_buyer_emails), h_n, c_n),
    ]
    for label, h_cnt, c_cnt, hn, cn in proportion_metrics:
        delta = (h_cnt / hn) - (c_cnt / cn)
        p = prop_ztest_pval(h_cnt, c_cnt, hn, cn)
        print(f"{label:<26} {fmt_pct(h_cnt, hn):>12} {fmt_pct(c_cnt, cn):>12} {delta * 100:>+9.2f}% {fmt_p(p):>10} {sig(p):>10}")

    p_rev = mwu_pval(h_rev_vec, c_rev_vec)
    h_rpu = h_rev_total / h_n
    c_rpu = c_rev_total / c_n
    print(f"{'Rev/user (MWU)':<26} {h_rpu:>12.2f} {c_rpu:>12.2f} {h_rpu - c_rpu:>+9.2f}  {fmt_p(p_rev):>10} {sig(p_rev):>10}")

    h_aov = np.mean(h_aov_vec) if h_aov_vec else 0
    c_aov = np.mean(c_aov_vec) if c_aov_vec else 0
    p_aov = mwu_pval(h_aov_vec, c_aov_vec)
    print(f"{'AOV (MWU)':<26} {h_aov:>12.2f} {c_aov:>12.2f} {h_aov - c_aov:>+9.2f}  {fmt_p(p_aov):>10} {sig(p_aov):>10}")

    print("=" * 90)
    print(f"\nGroup sizes:  Holdout n={h_n:,}  |  Control n={c_n:,}")
    print(f"Total revenue: Holdout ${h_rev_total:,.0f}  |  Control ${c_rev_total:,.0f}")
    print(f"Total orders:  Holdout {len(h_aov_vec):,}  |  Control {len(c_aov_vec):,}")
    print("\n* Marginal (p<0.10)  ** Significant (p<0.05)")
    print("\nNote: All engagement metrics are per-user (unique users / group size),")
    print("not per-send. The original report's 5–7× unsub difference was likely")
    print("caused by a per-send denominator inflated by ~5× more sends in control.")


if __name__ == '__main__':
    main()
