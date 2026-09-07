"""
BW popup variant performance analysis — all Email & Phone Capture Modal campaigns.

Pulls IAM impressions, clicks, and dismissals from Braze Snowflake datashare,
then attributes "Subscribed to Promotions" events via 30-minute time-window join.
Outputs reports/bw-popup-variant-analysis.md.
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR = "67093a1f24ebbe0065cb9c77"
EVERGREEN_API_ID = "5b0c85a9-8dcc-4a9f-b0cb-c4e5876ff747"

EVERGREEN_VARIANT_LABELS = {
    "8ccce2bd-f77a-420c-b224-ce80aca48b96": "V1: 15% off first order",
    "cdaab2a0-90af-4fe8-a771-dc13def7811d": "V2: Early sale alerts",
    "9fbbe502-f4d7-4216-9ec9-be2a7ff141e3": "V3: Free shipping >$1,500",
    "6912b802-ed00-4f2d-b706-e3182206a45b": "Control (no popup)",
}

client = get_snowflake_client(schema=SCHEMA, database=DB)


def discover_campaigns():
    """Return {api_id: latest_name} for all Email & Phone Capture Modal campaigns."""
    sql = f"""
        WITH ranked AS (
            SELECT
                API_ID,
                NAME,
                ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) AS rn
            FROM {DB}.{SCHEMA}.CHANGELOGS_CAMPAIGN_SHARED
            WHERE NAME ILIKE '%Email%Phone%Capture%Modal%'
               OR NAME ILIKE '%Phone%Email%Capture%Modal%'
        )
        SELECT API_ID, NAME
        FROM ranked
        WHERE rn = 1
        ORDER BY NAME
    """
    rows = client.execute_query(sql)
    return {r["API_ID"]: r["NAME"] for r in rows}


def in_clause(api_ids):
    return ", ".join(f"'{aid}'" for aid in api_ids)


def query_campaign_iam(view_name, api_ids):
    """Return {(campaign_api_id, month): unique_users} for a list of campaign IDs."""
    sql = f"""
        SELECT
            CAMPAIGN_API_ID,
            TO_CHAR(DATE_TRUNC('month', TO_TIMESTAMP(TIME)), 'YYYY-MM') AS month,
            COUNT(DISTINCT USER_ID) AS unique_users
        FROM {DB}.{SCHEMA}.{view_name}
        WHERE APP_GROUP_ID = '{BUR}'
          AND CAMPAIGN_API_ID IN ({in_clause(api_ids)})
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    rows = client.execute_query(sql)
    return {(r["CAMPAIGN_API_ID"], r["MONTH"]): r["UNIQUE_USERS"] for r in rows}


def query_campaign_subs(api_ids):
    """Attribute Subscribed to Promotions to campaigns via 30-min window after impression."""
    sql = f"""
        WITH impressions AS (
            SELECT USER_ID, CAMPAIGN_API_ID, TIME AS imp_time
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_INAPPMESSAGE_IMPRESSION_SHARED
            WHERE APP_GROUP_ID = '{BUR}'
              AND CAMPAIGN_API_ID IN ({in_clause(api_ids)})
        ),
        subs AS (
            SELECT USER_ID, TIME AS sub_time
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
            WHERE APP_GROUP_ID = '{BUR}'
              AND NAME = 'Subscribed to Promotions'
        ),
        attributed AS (
            SELECT
                i.USER_ID,
                i.CAMPAIGN_API_ID,
                i.imp_time,
                s.sub_time,
                ROW_NUMBER() OVER (
                    PARTITION BY i.USER_ID, s.sub_time
                    ORDER BY i.imp_time DESC
                ) AS rn
            FROM impressions i
            JOIN subs s
                ON i.USER_ID = s.USER_ID
                AND s.sub_time BETWEEN i.imp_time AND i.imp_time + 1800
        )
        SELECT
            CAMPAIGN_API_ID,
            TO_CHAR(DATE_TRUNC('month', TO_TIMESTAMP(imp_time)), 'YYYY-MM') AS month,
            COUNT(DISTINCT USER_ID) AS attributed_subscriptions
        FROM attributed
        WHERE rn = 1
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    rows = client.execute_query(sql)
    return {(r["CAMPAIGN_API_ID"], r["MONTH"]): r["ATTRIBUTED_SUBSCRIPTIONS"] for r in rows}


def query_variant_iam(view_name):
    """For Evergreen only — return {(month, variant_api_id): unique_users}."""
    sql = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('month', TO_TIMESTAMP(TIME)), 'YYYY-MM') AS month,
            MESSAGE_VARIATION_API_ID AS variant_api_id,
            MESSAGE_VARIATION_NAME AS variant_name,
            COUNT(DISTINCT USER_ID) AS unique_users
        FROM {DB}.{SCHEMA}.{view_name}
        WHERE CAMPAIGN_API_ID = '{EVERGREEN_API_ID}'
          AND APP_GROUP_ID = '{BUR}'
        GROUP BY 1, 2, 3
        ORDER BY 1, 3
    """
    rows = client.execute_query(sql)
    return rows


def query_variant_subs():
    """For Evergreen only — attribute subscriptions by variant."""
    sql = f"""
        WITH impressions AS (
            SELECT
                USER_ID,
                MESSAGE_VARIATION_API_ID AS variant_api_id,
                MESSAGE_VARIATION_NAME AS variant_name,
                TIME AS imp_time
            FROM {DB}.{SCHEMA}.USERS_MESSAGES_INAPPMESSAGE_IMPRESSION_SHARED
            WHERE CAMPAIGN_API_ID = '{EVERGREEN_API_ID}'
              AND APP_GROUP_ID = '{BUR}'
        ),
        subs AS (
            SELECT USER_ID, TIME AS sub_time
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
            WHERE APP_GROUP_ID = '{BUR}'
              AND NAME = 'Subscribed to Promotions'
        ),
        attributed AS (
            SELECT
                i.USER_ID, i.variant_api_id, i.variant_name, i.imp_time, s.sub_time,
                ROW_NUMBER() OVER (
                    PARTITION BY i.USER_ID, s.sub_time
                    ORDER BY i.imp_time DESC
                ) AS rn
            FROM impressions i
            JOIN subs s
                ON i.USER_ID = s.USER_ID
                AND s.sub_time BETWEEN i.imp_time AND i.imp_time + 1800
        )
        SELECT
            TO_CHAR(DATE_TRUNC('month', TO_TIMESTAMP(imp_time)), 'YYYY-MM') AS month,
            variant_api_id,
            variant_name,
            COUNT(DISTINCT USER_ID) AS attributed_subscriptions
        FROM attributed
        WHERE rn = 1
        GROUP BY 1, 2, 3
        ORDER BY 1, 3
    """
    return client.execute_query(sql)


def aggregate_by_campaign(imp, clk, ab, sub, api_ids):
    """Roll up monthly dicts to lifetime totals per campaign."""
    out = defaultdict(lambda: defaultdict(int))
    for (aid, month), v in imp.items():
        out[aid]["impressions"] += v
    for (aid, month), v in clk.items():
        out[aid]["clicks"] += v
    for (aid, month), v in ab.items():
        out[aid]["aborts"] += v
    for (aid, month), v in sub.items():
        out[aid]["subs"] += v
    return out


def aggregate_variants(imp_rows, clk_rows, ab_rows, sub_rows):
    variants = {}
    months = set()
    for row in imp_rows + clk_rows + ab_rows + sub_rows:
        aid = row.get("VARIANT_API_ID", "")
        name = row.get("VARIANT_NAME", "")
        if aid:
            variants[aid] = EVERGREEN_VARIANT_LABELS.get(aid, name or aid)
        month = row.get("MONTH", "")
        if month:
            months.add(month)

    def to_dict(rows, key="UNIQUE_USERS"):
        return {(r["MONTH"], r["VARIANT_API_ID"]): r[key] for r in rows}

    return (
        variants,
        sorted(months),
        to_dict(imp_rows),
        to_dict(clk_rows),
        to_dict(ab_rows),
        {(r["MONTH"], r["VARIANT_API_ID"]): r["ATTRIBUTED_SUBSCRIPTIONS"] for r in sub_rows},
    )


def fmt_pct(num, denom, decimals=2):
    if not denom:
        return "—"
    val = num / denom * 100
    return f"{val:.{decimals}f}%"


def fmt_num(n):
    return f"{n:,}" if n else "0"


def generate_report(campaign_names, campaign_totals, api_ids_ordered,
                    variants, v_months, v_imp, v_clk, v_ab, v_sub):
    lines = []

    lines.append("# BW Popup — Email & Phone Capture Modal Performance")
    lines.append("")
    lines.append("**Data source:** Braze Snowflake datashare (IAM events + custom events)  ")
    lines.append("**Subscription attribution:** Subscribed to Promotions event within 30 min of impression  ")
    lines.append("**Click rate:** unique users who clicked CTA / unique users shown  ")
    lines.append("**Sub rate:** attributed subscriptions / impressions  ")
    lines.append("")

    # Variant lifetime totals (for inline expansion of Evergreen)
    lifetime_v = defaultdict(lambda: defaultdict(int))
    for (month, aid), v in v_imp.items():
        lifetime_v[aid]["impressions"] += v
    for (month, aid), v in v_clk.items():
        lifetime_v[aid]["clicks"] += v
    for (month, aid), v in v_sub.items():
        lifetime_v[aid]["subs"] += v

    sorted_variants = sorted(
        variants.keys(),
        key=lambda aid: lifetime_v[aid]["impressions"],
        reverse=True,
    )

    # ── All campaigns lifetime summary ───────────────────────────────────────
    lines.append("## All Modal Campaigns — Lifetime Summary")
    lines.append("")
    lines.append("| Campaign | Impressions | Clicks | Click Rate | Subs | Sub Rate |")
    lines.append("|----------|-------------|--------|------------|------|----------|")

    for aid in api_ids_ordered:
        name = campaign_names.get(aid, aid)
        d = campaign_totals[aid]
        impr = d["impressions"]
        clk = d["clicks"]
        sub = d["subs"]
        if aid == EVERGREEN_API_ID:
            # Expand into per-variant rows
            for v_aid in sorted_variants:
                v_label = variants[v_aid]
                vd = lifetime_v[v_aid]
                lines.append(
                    f"| Evergreen — {v_label} | {fmt_num(vd['impressions'])} | "
                    f"{fmt_num(vd['clicks'])} | {fmt_pct(vd['clicks'], vd['impressions'])} | "
                    f"{fmt_num(vd['subs'])} | {fmt_pct(vd['subs'], vd['impressions'])} |"
                )
        else:
            lines.append(
                f"| {name} | {fmt_num(impr)} | {fmt_num(clk)} | {fmt_pct(clk, impr)} | "
                f"{fmt_num(sub)} | {fmt_pct(sub, impr)} |"
            )

    lines.append("")

    # ── Evergreen: monthly click rate by variant ──────────────────────────────
    lines.append("## Evergreen — Monthly Click Rate by Variant")
    lines.append("")
    variant_cols = [variants[aid] for aid in sorted_variants]
    header = "| Month | " + " | ".join(variant_cols) + " |"
    sep = "|-------|" + "|".join(["--------"] * len(sorted_variants)) + "|"
    lines.append(header)
    lines.append(sep)

    for month in v_months:
        row_vals = []
        for aid in sorted_variants:
            impr = v_imp.get((month, aid), 0)
            clk = v_clk.get((month, aid), 0)
            row_vals.append(fmt_pct(clk, impr) if impr else "—")
        lines.append(f"| {month} | " + " | ".join(row_vals) + " |")

    lines.append("")

    # ── Evergreen: monthly sub rate by variant ────────────────────────────────
    lines.append("## Evergreen — Monthly Subscription Rate by Variant")
    lines.append("")
    lines.append(header)
    lines.append(sep)

    for month in v_months:
        row_vals = []
        for aid in sorted_variants:
            impr = v_imp.get((month, aid), 0)
            sub = v_sub.get((month, aid), 0)
            row_vals.append(fmt_pct(sub, impr) if impr else "—")
        lines.append(f"| {month} | " + " | ".join(row_vals) + " |")

    lines.append("")

    # ── Evergreen: monthly impressions by variant ─────────────────────────────
    lines.append("## Evergreen — Monthly Impressions by Variant")
    lines.append("")
    lines.append(header)
    lines.append(sep)

    for month in v_months:
        row_vals = []
        for aid in sorted_variants:
            impr = v_imp.get((month, aid), 0)
            row_vals.append(fmt_num(impr) if impr else "—")
        lines.append(f"| {month} | " + " | ".join(row_vals) + " |")

    lines.append("")

    return "\n".join(lines)


def main():
    print("Discovering campaigns…")
    campaign_names = discover_campaigns()
    api_ids = list(campaign_names.keys())
    print(f"  Found {len(api_ids)} campaigns: {', '.join(campaign_names.values())}")

    print("\nQuerying all-campaign impressions…")
    camp_imp = query_campaign_iam("USERS_MESSAGES_INAPPMESSAGE_IMPRESSION_SHARED", api_ids)
    print("Querying all-campaign clicks…")
    camp_clk = query_campaign_iam("USERS_MESSAGES_INAPPMESSAGE_CLICK_SHARED", api_ids)
    print("Querying all-campaign subscription attribution…")
    camp_sub = query_campaign_subs(api_ids)

    camp_totals = aggregate_by_campaign(camp_imp, camp_clk, {}, camp_sub, api_ids)

    # Sort campaigns by total impressions desc
    api_ids_ordered = sorted(api_ids, key=lambda aid: camp_totals[aid]["impressions"], reverse=True)

    print("\nQuerying Evergreen variant impressions…")
    v_imp_rows = query_variant_iam("USERS_MESSAGES_INAPPMESSAGE_IMPRESSION_SHARED")
    print("Querying Evergreen variant clicks…")
    v_clk_rows = query_variant_iam("USERS_MESSAGES_INAPPMESSAGE_CLICK_SHARED")
    print("Querying Evergreen variant dismissals…")
    v_ab_rows = query_variant_iam("USERS_MESSAGES_INAPPMESSAGE_ABORT_SHARED")
    print("Querying Evergreen variant subscription attribution…")
    v_sub_rows = query_variant_subs()

    variants, v_months, v_imp, v_clk, v_ab, v_sub = aggregate_variants(
        v_imp_rows, v_clk_rows, v_ab_rows, v_sub_rows
    )

    report = generate_report(
        campaign_names, camp_totals, api_ids_ordered,
        variants, v_months, v_imp, v_clk, v_ab, v_sub,
    )

    out_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../reports/bw-popup-variant-analysis.md")
    )
    with open(out_path, "w") as f:
        f.write(report)

    print(f"\nReport saved → {out_path}")

    print("\n── Campaign totals ──")
    for aid in api_ids_ordered:
        d = camp_totals[aid]
        if d["impressions"]:
            print(
                f"  {campaign_names[aid]}: {d['impressions']:,} impr, "
                f"{d['subs']:,} subs ({fmt_pct(d['subs'], d['impressions'])} sub rate)"
            )


if __name__ == "__main__":
    main()
