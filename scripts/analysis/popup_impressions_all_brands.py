#!/usr/bin/env python3
"""
Popup impressions over time — one stacked bar chart per brand, all on one page.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv()

from scripts.braze_api_client import get_campaign_analytics

# ── Campaign registry ─────────────────────────────────────────────────────────

BRANDS = {
    "BUR": {
        "label": "Burrow",
        "color_base": ["#4e79a7", "#76b7b2", "#59a14f", "#edc948", "#f28e2b",
                        "#e15759", "#b07aa1", "#9c755f", "#bab0ac", "#ff9da7",
                        "#79706e", "#d4a6c8", "#86bcb6", "#499894", "#a0cbe8", "#ffbe7d"],
        "campaigns": [
            {"id": "57cbf9ea-1ac7-47ab-a0c7-61cc1383134f", "name": "BFCM Lightbox v2",
             "start": datetime(2024, 11, 1), "end": datetime(2024, 11, 1)},
            {"id": "9b24272e-51c4-4949-a45a-075523f482c9", "name": "BFCM Lightbox",
             "start": datetime(2024, 11, 1), "end": datetime(2024, 11, 29)},
            {"id": "1df8c121-5b96-4b33-8ee7-c403fc148406", "name": "BFCM Modal",
             "start": datetime(2024, 11, 28), "end": datetime(2024, 12, 11)},
            {"id": "46f42b1b-9ce5-4fc0-ab17-4cef54741bc7", "name": "EOY Sale",
             "start": datetime(2024, 12, 20), "end": datetime(2025, 1, 3)},
            {"id": "70d13314-3749-4e67-b699-984f2d3da044", "name": "Evergreen",
             "start": datetime(2024, 12, 11), "end": datetime(2025, 6, 10)},
            {"id": "5d7e7d31-d094-44d3-8a60-f6615c17d3e3", "name": "Winter Refresh",
             "start": datetime(2025, 1, 16), "end": datetime(2025, 1, 29)},
            {"id": "4aebff2a-4e32-4e55-b3b1-25c7e3d7eeba", "name": "PDS",
             "start": datetime(2025, 2, 6), "end": datetime(2025, 2, 26)},
            {"id": "b6b69de8-045e-4075-9324-9537e846d522", "name": "Spring Event",
             "start": datetime(2025, 3, 12), "end": datetime(2025, 4, 1)},
            {"id": "a1a0f483-8555-4981-9e3e-228d41c8e035", "name": "Friends & Family",
             "start": datetime(2025, 4, 10), "end": datetime(2025, 5, 1)},
            {"id": "0f787ff7-2852-4933-9cc5-6ad70162fc09", "name": "Memorial Day",
             "start": datetime(2025, 5, 12), "end": datetime(2025, 6, 3)},
            {"id": "07de05aa-2b15-446f-8907-fff9e154fc53", "name": "Summer Ready Flash",
             "start": datetime(2025, 6, 6), "end": datetime(2025, 6, 10)},
            {"id": "d00b2916-d983-40cb-98d2-b1e2d7ec7796", "name": "4th of July",
             "start": datetime(2025, 6, 20), "end": datetime(2025, 6, 23)},
            {"id": "6da55f4a-944d-4e84-895d-35ddb568c066", "name": "4th of July (v2)",
             "start": datetime(2025, 6, 23), "end": datetime(2025, 7, 15)},
            {"id": "5b0c85a9-8dcc-4a9f-b0cb-c4e5876ff747", "name": "Evergreen (live)",
             "start": datetime(2025, 7, 15), "end": datetime.now() - timedelta(days=10)},
            {"id": "def309d0-346a-417f-a567-7596f668376c", "name": "Labor Day",
             "start": datetime(2025, 8, 19), "end": datetime(2025, 8, 25)},
            {"id": "664275cc-eab4-4c6e-b207-4c8196424c5e", "name": "Labor Day Launch",
             "start": datetime(2025, 8, 21), "end": datetime(2025, 9, 12)},
        ],
    },
    "ID": {
        "label": "Interior Define",
        "color_base": ["#767749", "#a59b3e", "#c8b84a", "#e8d97a"],
        "campaigns": [
            {"id": "4d1d8601-593a-42dc-aa92-0aeef1fcb9f8", "name": "March 2025 (evergreen)",
             "start": datetime(2025, 3, 18), "end": datetime(2025, 12, 21)},
            {"id": "c9ebcdfd-fb47-44fd-9070-296156301e60", "name": "Winter Refresh Jan 2026",
             "start": datetime(2026, 1, 15), "end": datetime(2026, 1, 28)},
            {"id": "e9838982-7af0-4ecf-8e26-7c4dcc49f136", "name": "Jan 2026",
             "start": datetime(2026, 1, 28), "end": datetime(2026, 1, 29)},
            {"id": "a452f69f-7e71-49be-b0f0-5999715de15f", "name": "Sale March 2026",
             "start": datetime(2026, 3, 11), "end": datetime(2026, 3, 28)},
        ],
    },
    "CZ": {
        "label": "The Citizenry",
        "color_base": ["#2d6a4f", "#52b788", "#95d5b2", "#b7e4c7"],
        "campaigns": [],
    },
    "STF": {
        "label": "St. Frank",
        "color_base": ["#9e2a2b", "#c44b4b", "#e07070", "#f5a8a8"],
        "campaigns": [],
    },
    "HAV": {
        "label": "Havenly",
        "color_base": ["#1a3a5c", "#2c6194", "#4a90c4", "#82b8e0"],
        "campaigns": [],
    },
}

BRANDS["CZ"]["campaigns"] = [
    {"id": "0fd137e8-138d-4cb1-aa52-069783fad9d9", "name": "BFCM 2025",
     "start": datetime(2025, 12, 4), "end": datetime(2025, 12, 18)},
    {"id": "832c66b7-cdcd-4abd-b80e-a4bddda75903", "name": "PDS 2026",
     "start": datetime(2026, 2, 9), "end": datetime(2026, 3, 26)},
    {"id": "4ac83797-f7f3-428c-b318-633f22d7d708", "name": "10% Off Evergreen",
     "start": datetime(2026, 3, 11), "end": datetime(2026, 3, 24)},
    {"id": "50182a94-0a1d-479e-a043-12c76258c1b7", "name": "Spring Event 2026",
     "start": datetime(2026, 3, 17), "end": datetime(2026, 3, 28)},
]

BRANDS["STF"]["campaigns"] = [
    {"id": "d2908776-d152-4b66-965e-c13db5f6ac2e", "name": "Mobile (live)",
     "start": datetime(2025, 10, 3), "end": datetime.now() - timedelta(days=10)},
    {"id": "0768c951-ad8d-4a43-997f-79d2c9ca7b49", "name": "Mobile BFCM 2025",
     "start": datetime(2025, 11, 26), "end": datetime(2025, 12, 11)},
    {"id": "20352eb7-74a4-4dd4-98e0-8b13fe942ac3", "name": "Mobile EOY Sale 2025",
     "start": datetime(2025, 12, 22), "end": datetime(2026, 1, 6)},
    {"id": "4cedc54e-3028-422a-b5b3-33bde4897eef", "name": "Mobile Winter Refresh 2026",
     "start": datetime(2026, 1, 15), "end": datetime(2026, 1, 28)},
]

BRANDS["HAV"]["campaigns"] = [
    {"id": "c9d4e276-6ee6-4374-a3a3-8140010cf9e0", "name": "Presidents Day Sale",
     "start": datetime(2026, 2, 4), "end": datetime(2026, 2, 11)},
    {"id": "360f1db0-549b-40c4-8b56-e3db99e577a0", "name": "Birthday Sale (Conv)",
     "start": datetime(2026, 3, 13), "end": datetime(2026, 3, 28)},
]

# ── Helpers ───────────────────────────────────────────────────────────────────

MAX_WINDOW = 100


def fetch_all_daily(campaign_id, start, end, brand):
    import requests
    rows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=MAX_WINDOW - 1), end)
        try:
            data = get_campaign_analytics(campaign_id, cursor, window_end, brand=brand)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                cursor = window_end + timedelta(days=1)
                time.sleep(0.15)
                continue
            raise
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
        time.sleep(0.15)
    return rows


def build_brand_data(brand_key, brand_cfg):
    campaign_daily = {}
    for c in brand_cfg["campaigns"]:
        key = c["name"]
        print(f"  [{brand_key}] {key}...")
        rows = fetch_all_daily(c["id"], c["start"], c["end"], brand=brand_key)
        day_map = defaultdict(int)
        for r in rows:
            day_map[r["date"]] += r["impressions"]
        total = sum(day_map.values())
        print(f"    → {total:,} impressions")
        if total > 0:
            campaign_daily[key] = dict(day_map)
    return campaign_daily


# ── Chart builder ─────────────────────────────────────────────────────────────

def make_chart_js(brand_key, brand_cfg, campaign_daily):
    if not campaign_daily:
        return None

    all_dates = sorted({d for day_map in campaign_daily.values() for d in day_map})
    if not all_dates:
        return None

    colors = brand_cfg["color_base"]
    datasets = []
    grand_total = 0
    for i, (name, day_map) in enumerate(campaign_daily.items()):
        pts = [day_map.get(d, 0) for d in all_dates]
        grand_total += sum(pts)
        color = colors[i % len(colors)]
        safe_name = name.replace('"', '\\"')
        datasets.append(
            f'{{"label":"{safe_name}","data":[{",".join(map(str,pts))}],'
            f'"backgroundColor":"{color}","stack":"s"}}'
        )

    labels_js = ",".join(f'"{d}"' for d in all_dates)
    label_str = brand_cfg["label"]
    date_range = f"{all_dates[0]} → {all_dates[-1]}"

    return f"""
<div class="chart-section">
  <h2>{label_str}</h2>
  <p class="meta">{date_range} &nbsp;·&nbsp; {grand_total:,} total impressions</p>
  <canvas id="chart-{brand_key}" class="chart-canvas"></canvas>
</div>
<script>
new Chart(document.getElementById("chart-{brand_key}"), {{
  type: "bar",
  data: {{
    labels: [{labels_js}],
    datasets: [{",".join(datasets)}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: "top" }},
      tooltip: {{ mode: "index", intersect: false }}
    }},
    scales: {{
      x: {{ stacked: true, ticks: {{ maxTicksLimit: 20, maxRotation: 45 }} }},
      y: {{ stacked: true, title: {{ display: true, text: "Impressions" }} }}
    }}
  }}
}});
</script>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    chart_blocks = []

    for brand_key, brand_cfg in BRANDS.items():
        if not brand_cfg["campaigns"]:
            continue
        print(f"\n── {brand_cfg['label']} ──")
        campaign_daily = build_brand_data(brand_key, brand_cfg)
        block = make_chart_js(brand_key, brand_cfg, campaign_daily)
        if block:
            chart_blocks.append(block)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Popup Impressions — All Brands</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          padding: 2rem; background: #f8f8f6; color: #222; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.1rem; }}
  h2 {{ font-size: 1.1rem; margin: 0 0 0.15rem; color: #444; }}
  .subtitle {{ color: #777; font-size: 0.85rem; margin-bottom: 2.5rem; }}
  .meta {{ color: #888; font-size: 0.8rem; margin: 0 0 0.75rem; }}
  .chart-section {{ background: #fff; border-radius: 10px; padding: 1.5rem 1.75rem;
                    margin-bottom: 2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .chart-canvas {{ max-height: 380px; }}
</style>
</head><body>
<h1>Popup Impressions — All Brands</h1>
<p class="subtitle">Daily in-app message impressions by campaign · stacked by variant campaign</p>
{"".join(chart_blocks)}
</body></html>"""

    out = os.path.join(os.path.dirname(__file__), "../../reports/popup_impressions_all_brands.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"\n✓ Saved → {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
