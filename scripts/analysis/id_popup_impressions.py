#!/usr/bin/env python3
"""
ID popup impressions over time — daily chart across all active popup campaigns.
"""

import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv()

from scripts.braze_api_client import get_campaign_analytics

CAMPAIGNS = [
    {
        "id": "4d1d8601-593a-42dc-aa92-0aeef1fcb9f8",
        "name": "March 2025 (main)",
        "start": datetime(2025, 3, 18),
        "end":   datetime(2025, 12, 21),
    },
    {
        "id": "c9ebcdfd-fb47-44fd-9070-296156301e60",
        "name": "Winter Refresh Jan 2026",
        "start": datetime(2026, 1, 15),
        "end":   datetime(2026, 1, 28),
    },
    {
        "id": "e9838982-7af0-4ecf-8e26-7c4dcc49f136",
        "name": "Jan 2025",
        "start": datetime(2026, 1, 28),
        "end":   datetime(2026, 1, 29),
    },
    {
        "id": "a452f69f-7e71-49be-b0f0-5999715de15f",
        "name": "Sale March 2026",
        "start": datetime(2026, 3, 11),
        "end":   datetime(2026, 3, 28),
    },
]

MAX_WINDOW = 100  # Braze API max days per call


def fetch_all_daily(campaign_id, start, end, brand="ID"):
    """Fetch daily data in <=100-day windows, return list of {date, impressions}."""
    rows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=MAX_WINDOW - 1), end)
        data = get_campaign_analytics(campaign_id, cursor, window_end, brand=brand)
        if data and "data" in data:
            for day in data["data"]:
                date_str = day.get("time", "")[:10]
                impressions = 0
                for variants in day.get("messages", {}).values():
                    if isinstance(variants, list):
                        for v in variants:
                            impressions += v.get("impressions", 0)
                rows.append({"date": date_str, "impressions": impressions})
        cursor = window_end + timedelta(days=1)
    return rows


def main():
    daily = defaultdict(int)
    campaign_daily = {}

    for c in CAMPAIGNS:
        print(f"Fetching {c['name']}...")
        rows = fetch_all_daily(c["id"], c["start"], c["end"])
        campaign_daily[c["name"]] = {r["date"]: r["impressions"] for r in rows}
        for r in rows:
            daily[r["date"]] += r["impressions"]
        print(f"  {len(rows)} days, {sum(r['impressions'] for r in rows):,} total impressions")

    if not daily:
        print("No data returned — check BRAZE_API_KEY_ID in .env")
        return

    dates = sorted(daily.keys())
    total = sum(daily.values())
    print(f"\nTotal impressions across all campaigns: {total:,}")
    print(f"Date range: {dates[0]} → {dates[-1]}")

    # Build HTML chart
    labels = [f'"{d}"' for d in dates]
    values = [daily[d] for d in dates]

    # Per-campaign dataset colors
    colors = ["#767749", "#b5803a", "#4a7c9e", "#9e4a6b"]
    datasets = []
    for i, (name, day_map) in enumerate(campaign_daily.items()):
        pts = [day_map.get(d, 0) for d in dates]
        color = colors[i % len(colors)]
        datasets.append(
            f'{{"label":"{name}","data":[{",".join(map(str,pts))}],'
            f'"backgroundColor":"{color}","stack":"s"}}'
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>ID Popup Impressions</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ font-family: sans-serif; padding: 2rem; background: #fafafa; }}
  h1 {{ font-size: 1.2rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  canvas {{ max-height: 420px; }}
</style>
</head><body>
<h1>ID Popup — Daily Impressions</h1>
<p class="meta">All campaigns combined &nbsp;·&nbsp; {dates[0]} → {dates[-1]} &nbsp;·&nbsp; {total:,} total impressions</p>
<canvas id="chart"></canvas>
<script>
new Chart(document.getElementById("chart"), {{
  type: "bar",
  data: {{
    labels: [{",".join(labels)}],
    datasets: [{",".join(datasets)}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: "top" }},
      tooltip: {{ mode: "index" }}
    }},
    scales: {{
      x: {{ stacked: true, ticks: {{ maxTicksLimit: 24, maxRotation: 45 }} }},
      y: {{ stacked: true, title: {{ display: true, text: "Impressions" }} }}
    }}
  }}
}});
</script>
</body></html>"""

    out = os.path.join(os.path.dirname(__file__), "../../reports/id_popup_impressions.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"\nChart saved → {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
