"""The Citizenry Lifecycle Performance Dashboard
Run: streamlit run scripts/cz_lifecycle_dashboard.py
"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).parent.parent))

import lifecycle_dashboard_base as _base

_base.APP_GROUP_ID  = "666672a4d8965b005ac6c1bd"
_base.GA4_TABLE     = "AIRBYTE_DATABASE.LANDING_CITIZENRY_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"
_base.ACCENT        = "#8b6355"
_base.BRAND_CODE    = "CZ"
_base.BRAND_NAME    = "The Citizenry"
_base.HAS_FORECAST          = True
_base.FINANCE_FORECAST_COL  = "CZ_TOTAL_FORECAST"
_base.MODES         = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# CZ canvas groups: welcome/cart/browse combined; everything else stays as its own line
_base.CANVAS_GROUP_RULES = [
    (["welcome"],  "Welcome"),
    (["cart"],     "Abandon Cart"),
    (["browse"],   "Abandon Browse"),
]
_base.GA4_CANVAS_RULES = [
    (["welcome"],            "Welcome"),
    (["cart", "abandon"],    "Abandon Cart"),
    (["browse"],             "Abandon Browse"),
]

# Forecast — May 2026 (CZ)
# Benchmarks: median GA4 lifecycle revenue by category (16 months CZ historical data, Jan 2025–Apr 2026)
# SMS uplift: ~$1,000 estimated (scaled from BUR historical analysis)
_base.CATEGORY_BENCHMARKS  = {
    "sale_urgency":    32000,
    "sale_launch":     27000,
    "archive_sale":     9000,
    "sale_reminder":   10500,
    "editorial":       10000,
    "product_specific": 8000,
    "other":            5000,
}
_base.CATEGORY_LABELS = {
    "sale_urgency":    "Sale Urgency",
    "sale_launch":     "Sale Launch / EA",
    "archive_sale":    "Archive Sale",
    "sale_reminder":   "Sale Reminder",
    "editorial":       "Editorial",
    "product_specific":"Product Spotlight",
    "other":           "Other",
}
_base.SMS_UPLIFT = 1000

# ── Forecast months ────────────────────────────────────────────────────────────
# Sends: Asana Master CRM, pulled 2026-05-13
_MAY_SENDS = {
    "2026-05-15": {"name": "New Sofas — Full File",               "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-16": {"name": "Archive Sale Launch — Engaged",       "category": "archive_sale",    "if_needed": False, "has_sms": True},
    "2026-05-17": {"name": "Art + MDS Context — Full File",       "category": "editorial",       "if_needed": False, "has_sms": False},
    "2026-05-19": {"name": "MDS Reminder — Engaged",              "category": "sale_reminder",   "if_needed": False, "has_sms": False},
    "2026-05-20": {"name": "Rugs — Engaged",                      "category": "product_specific","if_needed": False, "has_sms": True},
    "2026-05-21": {"name": "Summer Trend Forecast — Engaged",     "category": "editorial",       "if_needed": False, "has_sms": False},
    "2026-05-22": {"name": "MTO Furniture — Full File",           "category": "product_specific","if_needed": False, "has_sms": True},
    "2026-05-23": {"name": "Mexico City Capsule — Engaged",       "category": "editorial",       "if_needed": False, "has_sms": False},
    "2026-05-25": {"name": "Back in Stock — Engaged",             "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-26": {"name": "MDS Last Day — Full File",            "category": "sale_urgency",    "if_needed": False, "has_sms": True},
    "2026-05-27": {"name": "Extension Launch — Full File",        "category": "sale_launch",     "if_needed": False, "has_sms": True},
    "2026-05-28": {"name": "Rugs by Material — Engaged",          "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-30": {"name": "Archive Sale — Full File",            "category": "archive_sale",    "if_needed": False, "has_sms": False},
}

# June 2026 sends — Asana Master CRM, pulled 2026-06-02
_JUN_SENDS = {
    "2026-06-03": {"name": "B2C Launch — New Sofas (MGBW)",          "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-05": {"name": "Summer Retreat Sale Launch",              "category": "sale_launch",      "if_needed": False, "has_sms": True},
    "2026-06-07": {"name": "MTO Furniture",                          "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-08": {"name": "Summer Retreat Sale Last Chance",         "category": "sale_urgency",     "if_needed": False, "has_sms": False},
    "2026-06-12": {"name": "Archive Sale",                           "category": "archive_sale",     "if_needed": False, "has_sms": False},
    "2026-06-16": {"name": "Washable Rugs",                          "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-17": {"name": "Fourth of July EA Launch",               "category": "sale_launch",      "if_needed": False, "has_sms": False},
    "2026-06-18": {"name": "Swatch Push",                            "category": "other",            "if_needed": False, "has_sms": False},
    "2026-06-21": {"name": "Fourth of July EA Last Chance",          "category": "sale_urgency",     "if_needed": False, "has_sms": False},
    "2026-06-22": {"name": "Fourth of July Event Launch",            "category": "sale_launch",      "if_needed": False, "has_sms": False},
    "2026-06-23": {"name": "Back in Stock",                          "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-25": {"name": "Archive Sale",                           "category": "archive_sale",     "if_needed": False, "has_sms": False},
    "2026-06-27": {"name": "The Portugal Capsule",                   "category": "editorial",        "if_needed": False, "has_sms": False},
    "2026-06-29": {"name": "Celebrating Summer",                     "category": "editorial",        "if_needed": False, "has_sms": False},
}

_base.FORECAST_MONTHS = [
    {"start": date(2026, 5, 1), "end": date(2026, 5, 31), "label": "May 2026", "sends": _MAY_SENDS},
    {"start": date(2026, 6, 1), "end": date(2026, 6, 30), "label": "June 2026", "sends": _JUN_SENDS},
]

_base.main()
