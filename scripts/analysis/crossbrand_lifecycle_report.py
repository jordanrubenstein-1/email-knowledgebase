"""
Cross-Brand Lifecycle Attribution Report

Finds sessions, purchases, and revenue in each brand's GA4 that came from
another brand's email campaign (identified by brand code in the UTM campaign name).

Usage:
    uv run python scripts/analysis/crossbrand_lifecycle_report.py [--days N]

Outputs: reports/crossbrand-lifecycle-attribution.html
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.snowflake_client import get_snowflake_client

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")

BRAND_LABELS = {
    "HAV": "Havenly",
    "BUR": "Burrow",
    "CZ":  "The Citizenry",
    "ID":  "Interior Define",
    "STF": "St. Frank",
    "TI":  "The Inside",
}

# GA4 schemas per destination brand
GA4_SCHEMAS = {
    "BUR": "LANDING_BURROW_GA4",
    "CZ":  "LANDING_CITIZENRY_GA4",
    "ID":  "LANDING_INTERIORDEFINE_GA4",
    "STF": "LANDING_ST_FRANK_GA4",
    "TI":  "LANDING_THE_INSIDE_GA4",
}

# Brand code to look for in campaign names (as it appears between underscores)
BRAND_CODES = {
    "HAV": "_HAV_",
    "BUR": "_BW_",
    "CZ":  "_CZ_",
    "ID":  "_ID_",
    "STF": "_SF_",
    "TI":  "_TI_",
}

DB = "AIRBYTE_DATABASE"


def build_summary_query(dest_brand, start_date):
    schema = GA4_SCHEMAS[dest_brand]
    dest_code = BRAND_CODES[dest_brand]

    # Build CASE for source brand detection (exclude dest brand's own code)
    cases = []
    for src_brand, code in BRAND_CODES.items():
        if src_brand == dest_brand:
            continue
        cases.append(f"      WHEN CONTAINS(SESSIONCAMPAIGNNAME, '{code}') THEN '{src_brand}'")

    # Build WHERE filter: must contain at least one other brand's code, not own
    other_codes = [f"CONTAINS(SESSIONCAMPAIGNNAME, '{code}')" for b, code in BRAND_CODES.items() if b != dest_brand]
    where_other = " OR ".join(other_codes)

    return f"""
    SELECT
      CASE
{chr(10).join(cases)}
      END AS source_brand,
      SESSIONCAMPAIGNNAME,
      SUM(SESSIONS) AS sessions,
      SUM(ECOMMERCEPURCHASES) AS purchases,
      SUM(TOTALREVENUE) AS revenue
    FROM {DB}.{schema}.TRAFFIC_SESSION_PERFORMANCE_DAILY
    WHERE DATE >= '{start_date}'
      AND UPPER(SESSIONPRIMARYCHANNELGROUP) = 'EMAIL'
      AND NOT CONTAINS(SESSIONCAMPAIGNNAME, '{dest_code}')
      AND NOT CONTAINS(UPPER(SESSIONCAMPAIGNNAME), '_TRADE')
      AND ({where_other})
    GROUP BY 1, 2
    HAVING source_brand IS NOT NULL
    ORDER BY source_brand, sessions DESC
    """


def run(days):
    client = get_snowflake_client(schema="LANDING_BURROW_GA4", database=DB)
    start_date = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")
    start_label = (datetime.today() - timedelta(days=days)).strftime("%b %-d, %Y")
    today_label = datetime.today().strftime("%b %-d, %Y")

    # { (dest, src): [campaign_rows] }
    results = {}

    for dest_brand in GA4_SCHEMAS:
        print(f"  Querying {dest_brand}...")
        q = build_summary_query(dest_brand, start_date)
        rows = client.execute_query(q)
        for row in rows:
            src = row["SOURCE_BRAND"]
            key = (dest_brand, src)
            if key not in results:
                results[key] = []
            results[key].append({
                "campaign": row["SESSIONCAMPAIGNNAME"],
                "sessions": int(row["SESSIONS"] or 0),
                "purchases": int(row["PURCHASES"] or 0),
                "revenue": float(row["REVENUE"] or 0),
            })

    # Aggregate summary rows
    summary = {}
    for (dest, src), campaigns in results.items():
        key = (dest, src)
        summary[key] = {
            "unique_campaigns": len(campaigns),
            "sessions": sum(c["sessions"] for c in campaigns),
            "purchases": sum(c["purchases"] for c in campaigns),
            "revenue": sum(c["revenue"] for c in campaigns),
        }

    html = render_html(summary, results, start_label, today_label, days)
    out_path = os.path.join(REPORTS_DIR, "crossbrand-lifecycle-attribution.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"\nReport written to {out_path}")


def fmt_sessions(n):
    return f"{n:,}"

def fmt_revenue(v):
    if v == 0:
        return "—"
    return f"${v:,.0f}"

def fmt_pct_of(num, den):
    if not den:
        return ""
    return f"{num/den*100:.0f}%"


def render_html(summary, results, start_label, today_label, days):
    # Group by destination brand for the summary table
    dest_brands = sorted(set(dest for dest, _ in summary))

    # Build summary table rows
    summary_rows_html = ""
    for dest in dest_brands:
        src_pairs = [(src, summary[(dest, src)]) for src in sorted(BRAND_LABELS) if (dest, src) in summary]
        if not src_pairs:
            continue
        dest_total_sessions = sum(v["sessions"] for _, v in src_pairs)
        dest_total_revenue = sum(v["revenue"] for _, v in src_pairs)
        first = True
        for src, v in src_pairs:
            dest_cell = f'<td rowspan="{len(src_pairs)}" class="brand-cell">{BRAND_LABELS[dest]}</td>' if first else ""
            first = False
            summary_rows_html += f"""
        <tr>
          {dest_cell}
          <td>{BRAND_LABELS[src]}</td>
          <td class="num">{v['unique_campaigns']}</td>
          <td class="num">{fmt_sessions(v['sessions'])}</td>
          <td class="num">{fmt_revenue(v['revenue'])}</td>
          <td class="num">{v['purchases'] if v['purchases'] else '—'}</td>
        </tr>"""

    # Build detail sections grouped by source brand (each pair gets a <details>)
    detail_sections_html = ""
    # Group by source brand first
    src_brands = sorted(set(src for _, src in summary))
    for src in src_brands:
        dest_pairs = [(dest, results[(dest, src)]) for dest in sorted(GA4_SCHEMAS) if (dest, src) in results and results[(dest, src)]]
        if not dest_pairs:
            continue

        pairs_html = ""
        for dest, campaigns in dest_pairs:
            top = sorted(campaigns, key=lambda c: c["sessions"], reverse=True)
            rows_html = ""
            for c in top:
                name = c["campaign"]
                # Strip "Copy of " prefix
                if name.startswith("Copy of "):
                    name = name[8:]
                rows_html += f"""
              <tr>
                <td class="campaign-name">{name}</td>
                <td class="num">{fmt_sessions(c['sessions'])}</td>
                <td class="num">{fmt_revenue(c['revenue'])}</td>
                <td class="num">{c['purchases'] if c['purchases'] else '—'}</td>
              </tr>"""

            total_sessions = sum(c["sessions"] for c in campaigns)
            total_revenue = sum(c["revenue"] for c in campaigns)
            total_purchases = sum(c["purchases"] for c in campaigns)

            pairs_html += f"""
        <details class="pair-details">
          <summary>
            <span class="pair-label">{BRAND_LABELS[src]} → {BRAND_LABELS[dest]}</span>
            <span class="pair-stats">{len(campaigns)} campaigns &nbsp;·&nbsp; {fmt_sessions(total_sessions)} sessions &nbsp;·&nbsp; {fmt_revenue(total_revenue)}</span>
          </summary>
          <table class="campaign-table">
            <thead>
              <tr>
                <th>Campaign (UTM)</th>
                <th class="num">Sessions</th>
                <th class="num">Revenue</th>
                <th class="num">Purchases</th>
              </tr>
            </thead>
            <tbody>{rows_html}
            </tbody>
            <tfoot>
              <tr>
                <td><strong>Total</strong></td>
                <td class="num"><strong>{fmt_sessions(total_sessions)}</strong></td>
                <td class="num"><strong>{fmt_revenue(total_revenue)}</strong></td>
                <td class="num"><strong>{total_purchases if total_purchases else '—'}</strong></td>
              </tr>
            </tfoot>
          </table>
        </details>"""

        detail_sections_html += f"""
      <div class="source-section">
        <h2>{BRAND_LABELS[src]} as Source Brand</h2>
        {pairs_html}
      </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Cross-Brand Lifecycle Attribution</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 2rem 2.5rem;
    background: #f8f8f6;
    color: #222;
    max-width: 960px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1.05rem; color: #444; margin: 2rem 0 0.5rem; }}
  .subtitle {{ color: #777; font-size: 0.85rem; margin-bottom: 2rem; }}
  .card {{
    background: #fff;
    border-radius: 10px;
    padding: 1.5rem 1.75rem;
    margin-bottom: 2rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.875rem; }}
  th {{ text-align: left; font-weight: 600; color: #555; border-bottom: 2px solid #e8e8e4;
        padding: 0.5rem 0.75rem; }}
  td {{ padding: 0.45rem 0.75rem; border-bottom: 1px solid #f0f0ec; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .brand-cell {{ font-weight: 600; vertical-align: middle; }}
  .note {{ font-size: 0.78rem; color: #888; margin-top: 0.75rem; }}

  /* Detail sections */
  .source-section {{ margin-bottom: 1.5rem; }}
  details.pair-details {{
    background: #fff;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    overflow: hidden;
  }}
  details.pair-details summary {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    padding: 0.85rem 1.25rem;
    list-style: none;
    user-select: none;
  }}
  details.pair-details summary::-webkit-details-marker {{ display: none; }}
  details.pair-details summary::before {{
    content: "▶";
    font-size: 0.7rem;
    margin-right: 0.6rem;
    color: #999;
    transition: transform 0.15s;
  }}
  details[open].pair-details summary::before {{ transform: rotate(90deg); }}
  .pair-label {{ font-weight: 600; font-size: 0.9rem; }}
  .pair-stats {{ font-size: 0.8rem; color: #777; }}
  .campaign-table {{ margin: 0; font-size: 0.82rem; }}
  .campaign-table th {{ background: #fafaf8; }}
  .campaign-name {{ font-family: "SF Mono", "Menlo", monospace; font-size: 0.78rem; color: #333; word-break: break-all; }}
  tfoot td {{ background: #fafaf8; font-size: 0.82rem; }}
</style>
</head>
<body>
<h1>Cross-Brand Lifecycle Attribution</h1>
<p class="subtitle">Sessions, purchases, and revenue in each brand's GA4 driven by another brand's email campaign UTM &nbsp;·&nbsp; {start_label} – {today_label} (last {days} days)</p>

<div class="card">
  <table>
    <thead>
      <tr>
        <th>Destination Brand (GA4)</th>
        <th>Source Brand (Email)</th>
        <th class="num">Campaigns</th>
        <th class="num">Sessions</th>
        <th class="num">Revenue</th>
        <th class="num">Purchases</th>
      </tr>
    </thead>
    <tbody>
      {summary_rows_html}
    </tbody>
  </table>
  <p class="note">Source brand identified by brand code in GA4 <code>SESSIONCAMPAIGNNAME</code> (e.g. <code>_CZ_</code>, <code>_BW_</code>). Only Email channel sessions included. "Copy of" prefix stripped from campaign names in detail view.</p>
</div>

<h2 style="margin-top:0">Campaign Detail</h2>
{detail_sections_html}

<p class="note" style="margin-top:2rem">Generated {today_label} · GA4 data via Snowflake Airbyte connector · Revenue = GA4 last-click</p>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-brand lifecycle attribution report")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days (default: 180)")
    args = parser.parse_args()
    print(f"Querying last {args.days} days...")
    run(args.days)
