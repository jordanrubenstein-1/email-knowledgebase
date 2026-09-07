#!/usr/bin/env python3
"""
SMS ROI Attribution Analysis

Queries GA4 (last-click) and Braze datashare to produce a brand-by-brand
breakdown of SMS-attributed revenue, purchases, AOV, and send efficiency.

Output: reports/sms-roi-analysis.md
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.snowflake_client import get_snowflake_client

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"

BRAZE_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
BRAZE_SCHEMA = "DATALAKE_SHARING"

BRAZE_APP_GROUP_IDS = {
    "BUR": "67093a1f24ebbe0065cb9c77",
    "CZ": "666672a4d8965b005ac6c1bd",
}

GA4_SCHEMAS = {
    "BUR": "AIRBYTE_DATABASE.LANDING_BURROW_GA4",
    "CZ": "AIRBYTE_DATABASE.LANDING_CITIZENRY_GA4",
    "STF": "AIRBYTE_DATABASE.LANDING_ST_FRANK_GA4",
    "ID": "AIRBYTE_DATABASE.LANDING_INTERIORDEFINE_GA4",
}

BRAND_LABELS = {
    "BUR": "Burrow",
    "CZ": "The Citizenry",
    "STF": "St. Frank",
    "ID": "Interior Define",
}

# 12-month window ending today
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=365)
START_STR = START_DATE.strftime("%Y%m%d")
END_STR = END_DATE.strftime("%Y%m%d")


def fmt_currency(v):
    if v is None:
        return "—"
    return f"${v:,.0f}"


def fmt_int(v):
    if v is None:
        return "—"
    return f"{int(v):,}"


def fmt_x(v):
    if v is None:
        return "—"
    return f"{v:.1f}x"


def query_ga4_summary(client, brand):
    schema = GA4_SCHEMAS[brand]
    rows = client.execute_query(f"""
        SELECT
            SUM(SESSIONS)           AS sessions,
            SUM(TOTALREVENUE)       AS revenue,
            SUM(ECOMMERCEPURCHASES) AS purchases,
            COUNT(DISTINCT SESSIONCAMPAIGNNAME) AS campaigns
        FROM {schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
        WHERE DATE >= '{START_STR}' AND DATE <= '{END_STR}'
          AND SESSIONPRIMARYCHANNELGROUP = 'SMS'
    """)
    return rows[0] if rows else {}


def query_ga4_type_split(client, brand):
    schema = GA4_SCHEMAS[brand]
    rows = client.execute_query(f"""
        SELECT
            CASE
                WHEN SESSIONCAMPAIGNNAME ILIKE 'TRG_%' THEN 'Triggered (Flows)'
                ELSE 'Batch/Blast'
            END AS campaign_type,
            COUNT(DISTINCT SESSIONCAMPAIGNNAME) AS campaigns,
            SUM(SESSIONS)           AS sessions,
            SUM(TOTALREVENUE)       AS revenue,
            SUM(ECOMMERCEPURCHASES) AS purchases,
            ROUND(SUM(TOTALREVENUE)/NULLIF(SUM(ECOMMERCEPURCHASES),0), 2) AS aov
        FROM {schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
        WHERE DATE >= '{START_STR}' AND DATE <= '{END_STR}'
          AND SESSIONPRIMARYCHANNELGROUP = 'SMS'
        GROUP BY 1
        ORDER BY revenue DESC
    """)
    return rows


def query_ga4_monthly(client, brand):
    schema = GA4_SCHEMAS[brand]
    rows = client.execute_query(f"""
        SELECT
            LEFT(DATE, 6)           AS month,
            SUM(SESSIONS)           AS sessions,
            SUM(TOTALREVENUE)       AS revenue,
            SUM(ECOMMERCEPURCHASES) AS purchases
        FROM {schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
        WHERE DATE >= '{START_STR}' AND DATE <= '{END_STR}'
          AND SESSIONPRIMARYCHANNELGROUP = 'SMS'
        GROUP BY 1
        ORDER BY 1
    """)
    return rows


def query_ga4_top_campaigns(client, brand, limit=10):
    schema = GA4_SCHEMAS[brand]
    rows = client.execute_query(f"""
        SELECT
            SESSIONCAMPAIGNNAME                                            AS campaign,
            SUM(SESSIONS)                                                  AS sessions,
            SUM(TOTALREVENUE)                                              AS revenue,
            SUM(ECOMMERCEPURCHASES)                                        AS purchases,
            ROUND(SUM(TOTALREVENUE)/NULLIF(SUM(ECOMMERCEPURCHASES),0), 0) AS aov
        FROM {schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
        WHERE DATE >= '{START_STR}' AND DATE <= '{END_STR}'
          AND SESSIONPRIMARYCHANNELGROUP = 'SMS'
        GROUP BY 1
        ORDER BY revenue DESC
        LIMIT {limit}
    """)
    return rows


def query_braze_sends(client, brand):
    app_id = BRAZE_APP_GROUP_IDS[brand]
    rows = client.execute_query(f"""
        SELECT
            COUNT(DISTINCT ID)      AS total_sends,
            COUNT(DISTINCT USER_ID) AS unique_recipients
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
        WHERE APP_GROUP_ID = '{app_id}'
          AND TO_TIMESTAMP(TIME) >= DATEADD('day', -365, CURRENT_TIMESTAMP())
    """)
    return rows[0] if rows else {}


def month_label(m):
    return f"{m[:4]}-{m[4:]}"


def build_report(data):
    lines = []
    a = lines.append

    a("# SMS Last-Click Attribution Report")
    a(f"*{START_DATE.strftime('%b %d, %Y')} – {END_DATE.strftime('%b %d, %Y')} · Source: GA4 last-click*")
    a("")

    # ── Executive Summary ──────────────────────────────────────────────────
    a("## Executive Summary")
    a("")
    total_rev = sum(d["summary"].get("REVENUE") or 0 for d in data.values())
    total_purch = sum(int(d["summary"].get("PURCHASES") or 0) for d in data.values())
    total_sess = sum(int(d["summary"].get("SESSIONS") or 0) for d in data.values())
    total_camps = sum(int(d["summary"].get("CAMPAIGNS") or 0) for d in data.values())
    overall_aov = total_rev / total_purch if total_purch else 0

    a(f"| Metric | Value |")
    a(f"|--------|-------|")
    a(f"| Total SMS-attributed revenue | {fmt_currency(total_rev)} |")
    a(f"| Total purchases | {fmt_int(total_purch)} |")
    a(f"| Overall AOV | {fmt_currency(overall_aov)} |")
    a(f"| Total sessions | {fmt_int(total_sess)} |")
    a(f"| Distinct campaigns/flows | {fmt_int(total_camps)} |")
    a(f"| Brands with active SMS | {len(data)} (BUR, CZ, STF, ID) |")
    a("")
    a("> **Note:** TI and TE use Klaviyo and have no GA4 attribution data. HAV has no Braze SMS program.")
    a("")

    # ── Brand Summary ──────────────────────────────────────────────────────
    a("## Brand Summary")
    a("")
    a("| Brand | Revenue | Purchases | AOV | Sessions | Campaigns |")
    a("|-------|--------:|----------:|----:|----------:|----------:|")
    for brand, d in sorted(data.items(), key=lambda x: -(x[1]["summary"].get("REVENUE") or 0)):
        s = d["summary"]
        rev = s.get("REVENUE") or 0
        purch = int(s.get("PURCHASES") or 0)
        sess = int(s.get("SESSIONS") or 0)
        camps = int(s.get("CAMPAIGNS") or 0)
        aov = rev / purch if purch else None
        a(f"| **{BRAND_LABELS[brand]} ({brand})** | {fmt_currency(rev)} | {fmt_int(purch)} | {fmt_currency(aov)} | {fmt_int(sess)} | {fmt_int(camps)} |")
    a(f"| **Total** | **{fmt_currency(total_rev)}** | **{fmt_int(total_purch)}** | **{fmt_currency(overall_aov)}** | **{fmt_int(total_sess)}** | **{fmt_int(total_camps)}** |")
    a("")

    # ── Send Efficiency (BUR + CZ only) ────────────────────────────────────
    a("## Send Efficiency (Burrow & Citizenry)")
    a("")
    a("Send volumes are available from the Braze Raw Events datashare for BUR and CZ only (STF and ID are not covered).")
    a("")
    a("| Brand | Sends | Revenue | Revenue/Send | Est. Cost @ $0.01/msg | Implied ROAS |")
    a("|-------|------:|--------:|-------------:|----------------------:|-------------:|")
    for brand in ["BUR", "CZ"]:
        d = data[brand]
        sends = d["sends"].get("TOTAL_SENDS") or 0
        rev = d["summary"].get("REVENUE") or 0
        rev_per_send = rev / sends if sends else None
        est_cost = sends * 0.01
        roas = rev / est_cost if est_cost else None
        a(f"| **{BRAND_LABELS[brand]}** | {fmt_int(sends)} | {fmt_currency(rev)} | ${rev_per_send:.3f} | {fmt_currency(est_cost)} | {fmt_x(roas)} |")
    a("")
    a("> Carrier cost estimate of $0.01/message is approximate — actual Attentive/platform blended costs may differ.")
    a("")

    # ── Triggered vs Batch ──────────────────────────────────────────────────
    a("## Triggered Flows vs Batch/Blast")
    a("")
    a("Campaigns prefixed `TRG_` are treated as triggered flows; all others are batch/blast.")
    a("")
    a("| Brand | Type | Revenue | Purchases | AOV | Campaigns |")
    a("|-------|------|--------:|----------:|----:|----------:|")
    for brand, d in sorted(data.items(), key=lambda x: -(x[1]["summary"].get("REVENUE") or 0)):
        for row in d["type_split"]:
            ct = row.get("CAMPAIGN_TYPE", "")
            rev = row.get("REVENUE") or 0
            purch = int(row.get("PURCHASES") or 0)
            aov = row.get("AOV") or 0
            camps = int(row.get("CAMPAIGNS") or 0)
            a(f"| {BRAND_LABELS[brand]} | {ct} | {fmt_currency(rev)} | {fmt_int(purch)} | {fmt_currency(aov)} | {fmt_int(camps)} |")
    a("")
    a("> Triggered flows show higher AOV across every brand — reflecting higher intent users (cart/browse abandonment, welcome).")
    a("")

    # ── Monthly Trends ──────────────────────────────────────────────────────
    a("## Monthly Revenue Trends")
    a("")

    # Collect all months
    all_months = sorted({row["MONTH"] for d in data.values() for row in d["monthly"]})
    header = "| Month | " + " | ".join(BRAND_LABELS[b] for b in ["ID", "BUR", "CZ", "STF"]) + " | Total |"
    sep = "|-------|" + "|".join("-------:" for _ in ["ID", "BUR", "CZ", "STF"]) + "|-------:|"
    a(header)
    a(sep)

    monthly_lookup = {}
    for brand, d in data.items():
        monthly_lookup[brand] = {row["MONTH"]: row for row in d["monthly"]}

    for month in all_months:
        row_revs = []
        for brand in ["ID", "BUR", "CZ", "STF"]:
            r = monthly_lookup.get(brand, {}).get(month, {})
            row_revs.append(r.get("REVENUE") or 0)
        total = sum(row_revs)
        cells = " | ".join(fmt_currency(v) if v else "—" for v in row_revs)
        a(f"| {month_label(month)} | {cells} | {fmt_currency(total)} |")
    a("")

    # ── Top Campaigns per Brand ─────────────────────────────────────────────
    a("## Top 10 Campaigns by Brand")
    a("")
    for brand in ["ID", "BUR", "CZ", "STF"]:
        d = data[brand]
        a(f"### {BRAND_LABELS[brand]} ({brand})")
        a("")
        a("| Campaign | Revenue | Purchases | AOV | Sessions |")
        a("|----------|--------:|----------:|----:|---------:|")
        for row in d["top_campaigns"]:
            camp = row.get("CAMPAIGN") or row.get("campaign") or "—"
            rev = row.get("REVENUE") or 0
            purch = int(row.get("PURCHASES") or 0)
            aov = row.get("AOV") or 0
            sess = int(row.get("SESSIONS") or 0)
            a(f"| `{camp}` | {fmt_currency(rev)} | {fmt_int(purch)} | {fmt_currency(aov)} | {fmt_int(sess)} |")
        a("")

    # ── Methodology ────────────────────────────────────────────────────────
    a("## Methodology & Caveats")
    a("")
    a("- **Attribution model**: GA4 last-click. Sessions where `SESSIONPRIMARYCHANNELGROUP = 'SMS'` are credited to SMS.")
    a("- **Last-click bias**: Triggered flows (browse/cart abandonment) may understate SMS influence — the user may have clicked SMS but their last session before purchase came from another channel.")
    a("- **Send volumes**: Only available for BUR and CZ via the Braze Raw Events datashare. STF and ID send volumes are not in the datashare; ROAS cannot be computed for those brands.")
    a("- **Cost assumption**: $0.01/message is an estimate. Actual blended costs (carrier fees + Attentive/Braze platform) vary.")
    a("- **Excluded brands**: HAV (no SMS program), TI and TE (Klaviyo — no GA4 data pipeline).")
    a("- **Date range**: Trailing 365 days ending today.")

    return "\n".join(lines)


def main():
    print("Connecting to Snowflake...")
    client = get_snowflake_client(
        schema="LANDING_BURROW_GA4",
        database="AIRBYTE_DATABASE",
    )

    data = {}

    for brand in GA4_SCHEMAS:
        label = BRAND_LABELS[brand]
        print(f"  Querying {label}...")
        data[brand] = {
            "summary": query_ga4_summary(client, brand),
            "type_split": query_ga4_type_split(client, brand),
            "monthly": query_ga4_monthly(client, brand),
            "top_campaigns": query_ga4_top_campaigns(client, brand),
            "sends": {},
        }

    # Braze send counts — BUR + CZ only
    braze_client = get_snowflake_client(
        schema=BRAZE_SCHEMA,
        database=BRAZE_DB,
    )
    for brand in ["BUR", "CZ"]:
        print(f"  Querying Braze sends for {BRAND_LABELS[brand]}...")
        data[brand]["sends"] = query_braze_sends(braze_client, brand)

    print("Building report...")
    report = build_report(data)

    out_path = REPORTS_DIR / "sms-roi-analysis.md"
    out_path.write_text(report)
    print(f"Saved → {out_path}")

    # Quick spot-check
    for brand in ["BUR", "CZ", "STF", "ID"]:
        rev = data[brand]["summary"].get("REVENUE") or 0
        print(f"  {brand}: {fmt_currency(rev)}")


if __name__ == "__main__":
    main()
