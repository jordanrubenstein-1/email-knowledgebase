"""Interior Define Lifecycle Performance Dashboard
Run: streamlit run scripts/id_lifecycle_dashboard.py
Email metrics sourced from campaign YAMLs (not Braze datashare — ID not included).
GA4 sessions + revenue sourced from Snowflake as normal.
"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).parent.parent))

import lifecycle_dashboard_base as _base

_base.APP_GROUP_ID  = "6666726b459b5e0059d7d687"
_base.BRAZE_DB      = _base.BRAZE_DB_TIER3
_base.BRAZE_SCHEMA  = _base.BRAZE_SCHEMA_TIER3
_base.GA4_TABLE     = "AIRBYTE_DATABASE.LANDING_INTERIORDEFINE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"
_base.ACCENT        = "#3E6D9C"
_base.BRAND_CODE    = "ID"
_base.BRAND_NAME    = "Interior Define"
_base.HAS_FORECAST          = True
_base.FINANCE_FORECAST_COL  = "ID_FORECASTED_ADJUSTED_GROSS_BOOKINGS"
_base.HAS_SMS       = True
_base.BRAZE_TIER3   = True
_base.MODES         = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# Canvas grouping rules (order matters — first match wins)
_base.CANVAS_GROUP_RULES = [
    (["welcome"],                                          "Welcome"),
    (["swatch cart", "swatch"],                           "Swatch Abandon"),
    (["cart"],                                            "Abandon Cart"),
    (["browse", "collection abandon", "category abandon"],"Abandon Browse"),
    (["post purchase"],                                   "Post Purchase"),
    (["trade"],                                           "Trade Welcome"),
]
_base.GA4_CANVAS_RULES = [
    (["welcome"],                                          "Welcome"),
    (["swatch"],                                          "Swatch Abandon"),
    (["cart"],                                            "Abandon Cart"),
    (["browse", "collection", "category"],                "Abandon Browse"),
    (["post purchase", "post-purchase"],                  "Post Purchase"),
    (["trade"],                                           "Trade Welcome"),
]

# Forecast — benchmarks from GA4 Apr–Jun 2026 (limited history; refine as data accumulates)
# Sale urgency days (Last Chance, Final Hours): ~$22K median
# Sale launch (EA Launch, Sale Launch): ~$18K
# Sale reminder (mid-sale): ~$15K
# Product spotlight: ~$12K  |  Editorial: ~$9K  |  Other: ~$8K
_base.CATEGORY_BENCHMARKS = {
    "sale_urgency":     22000,
    "sale_launch":      18000,
    "sale_reminder":    15000,
    "product_specific": 12000,
    "editorial":         9000,
    "other":             8000,
}
_base.CATEGORY_LABELS = {
    "sale_urgency":     "Sale Urgency",
    "sale_launch":      "Sale Launch / EA",
    "sale_reminder":    "Sale Reminder",
    "product_specific": "Product Spotlight",
    "editorial":        "Editorial",
    "other":            "Other",
}
_base.SMS_UPLIFT = 2000  # estimated; refine with historical analysis

# June 2026 sends — Asana Master CRM, pulled 2026-06-02
_JUN_SENDS = {
    "2026-06-05": {"name": "Weekender Sale Sectionals Spotlight",    "category": "sale_reminder",    "if_needed": False, "has_sms": False},
    "2026-06-06": {"name": "Editor's Picks",                         "category": "editorial",        "if_needed": False, "has_sms": False},
    "2026-06-07": {"name": "Made for Me: Jasper Ottoman",            "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-08": {"name": "Weekender Sale Final Hours",             "category": "sale_urgency",     "if_needed": False, "has_sms": True},
    "2026-06-09": {"name": "Swatch Talk: Summer Blues",              "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-10": {"name": "Comfort Guide",                          "category": "editorial",        "if_needed": False, "has_sms": False},
    "2026-06-12": {"name": "Pet-Friendly Fabrics",                   "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-13": {"name": "Maxwell Bed Spotlight",                  "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-14": {"name": "Sectionals Buying Guide",                "category": "editorial",        "if_needed": False, "has_sms": False},
    "2026-06-16": {"name": "Swatch Talk: Performance Fabrics",       "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-17": {"name": "4th of July Early Access Launch",        "category": "sale_launch",      "if_needed": False, "has_sms": True},
    "2026-06-18": {"name": "Outdoor Feature: Riva Collection",       "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-19": {"name": "James Collection Spotlight",             "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-20": {"name": "Graham Bed Spotlight",                   "category": "product_specific", "if_needed": False, "has_sms": True},
    "2026-06-21": {"name": "4th of July EA Final Day",               "category": "sale_urgency",     "if_needed": False, "has_sms": False},
    "2026-06-22": {"name": "4th of July Sale Launch",                "category": "sale_launch",      "if_needed": False, "has_sms": True},
    "2026-06-23": {"name": "Swatch Talk: Coastal Hues",              "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-24": {"name": "Saylor Collection Spotlight",            "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-25": {"name": "Tatum Modular Sectional Spotlight",      "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-26": {"name": "Get the Look: Lee",                      "category": "editorial",        "if_needed": False, "has_sms": True},
    "2026-06-27": {"name": "Skylar Collection Spotlight",            "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-28": {"name": "Green Sofas: Coriander",                 "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-29": {"name": "Pet-Friendly Sofas",                     "category": "product_specific", "if_needed": False, "has_sms": True},
    "2026-06-30": {"name": "Swatch Talk: Red, White & Blue",         "category": "product_specific", "if_needed": False, "has_sms": False},
}

_base.FORECAST_MONTHS = [
    {"start": date(2026, 6, 1), "end": date(2026, 6, 30), "label": "June 2026", "sends": _JUN_SENDS},
]

_base.main()
