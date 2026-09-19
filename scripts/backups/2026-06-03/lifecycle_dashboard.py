"""Burrow Lifecycle Performance Dashboard
Run: streamlit run scripts/lifecycle_dashboard.py
"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).parent.parent))

import lifecycle_dashboard_base as _base

_base.APP_GROUP_ID  = "67093a1f24ebbe0065cb9c77"
_base.GA4_TABLE     = "AIRBYTE_DATABASE.LANDING_BURROW_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"
_base.ACCENT        = "#e94560"
_base.BRAND_CODE    = "BUR"
_base.BRAND_NAME    = "Burrow"
_base.HAS_FORECAST          = True
_base.FINANCE_FORECAST_COL  = "BW_ECOMM_ADJUSTED_GROSS_REVENUE"
_base.MODES         = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# Canvas grouping rules (order matters — first match wins)
_base.CANVAS_GROUP_RULES = [
    (["reclaim", "grow"],                                                        "Retention.com"),
    (["welcome"],                                                                "Welcome"),
    (["[new - shopify]"],                                                        None),  # keep raw
    (["shipping confirmation", "order confirmation",
      "out for delivery", "delivery confirmation"],                              "Transactional"),
    (["cart"],                                                                   "Abandon Cart"),
    (["browse"],                                                                 "Abandon Browse"),
]
_base.GA4_CANVAS_RULES = [
    (["reclaim", "grow"],                                                        "Retention.com"),
    (["welcome"],                                                                "Welcome"),
    (["shipping", "order confirm", "out for delivery", "delivery confirm"],      "Transactional"),
    (["cart"],                                                                   "Abandon Cart"),
    (["browse"],                                                                 "Abandon Browse"),
]

# Forecast — BUR
# Benchmarks: median GA4 lifecycle revenue on send days by category (329 BUR sends, Apr–Nov 2025)
# SMS uplift: median incremental revenue on Email+SMS days vs Email-only days (historical analysis)
_base.CATEGORY_BENCHMARKS  = {
    "sale_urgency":    16051,
    "sale_reminder":    6021,
    "plain_text":       5353,
    "sale_launch":      5234,
    "other":            3826,
    "product_specific": 1971,
    "editorial":        1652,
}
_base.CATEGORY_LABELS = {
    "sale_urgency":    "Sale Urgency",
    "sale_reminder":   "Sale Reminder",
    "plain_text":      "Plain Text",
    "sale_launch":     "Sale Launch / EA",
    "other":           "Other",
    "product_specific":"Product Spotlight",
    "editorial":       "Editorial",
}
_base.SMS_UPLIFT = 1859

# ── Forecast months ────────────────────────────────────────────────────────────
# Add new months by appending to FORECAST_MONTHS. Past months auto-collapse to
# a summary card; the last entry is shown as the full daily chart.
# Sends: Asana Master CRM (project 1207522423363072)
_MAY_SENDS = {
    "2026-05-09": {"name": "Clearance Spotlight — EA",              "category": "sale_launch",     "if_needed": False, "has_sms": False},
    "2026-05-10": {"name": "Best Seat in the House — Game Day",      "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-11": {"name": "Sectionals Guide — Early Access",        "category": "sale_launch",     "if_needed": False, "has_sms": False},
    "2026-05-12": {"name": "Memorial Day EA — Last Day",             "category": "sale_urgency",    "if_needed": False, "has_sms": True},
    "2026-05-13": {"name": "Memorial Day Main Sale — Launch",        "category": "sale_launch",     "if_needed": False, "has_sms": True},
    "2026-05-14": {"name": "Range Collection — Memorial Day Sale",   "category": "product_specific","if_needed": True,  "has_sms": False},
    "2026-05-15": {"name": "Small Space Solutions",                  "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-16": {"name": "Quick Ship — Memorial Day Sale",         "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-17": {"name": "Sleepers — Summer Guest Prep",           "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-18": {"name": "NBA/NHL Playoffs — Living Room Upgrade", "category": "product_specific","if_needed": True,  "has_sms": False},
    "2026-05-19": {"name": "Mid-Sale Check-In (PT)",                 "category": "plain_text",      "if_needed": False, "has_sms": True},
    "2026-05-20": {"name": "Opera Collection",                       "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-21": {"name": "Nomad New Fabrics — Launch",             "category": "product_specific","if_needed": False, "has_sms": False},
    "2026-05-22": {"name": "Style Edit: Hamptons Hideaway",          "category": "editorial",       "if_needed": False, "has_sms": False},
    "2026-05-23": {"name": "Accent Seating + Dining",                "category": "product_specific","if_needed": True,  "has_sms": False},
    "2026-05-24": {"name": "Memorial Day Sale — One Week Left",      "category": "sale_reminder",   "if_needed": False, "has_sms": True},
    "2026-05-25": {"name": "Memorial Day — Last 2 Days",             "category": "sale_urgency",    "if_needed": False, "has_sms": True},
    "2026-05-26": {"name": "Memorial Day Sale — Last Day",           "category": "sale_urgency",    "if_needed": False, "has_sms": False},
    "2026-05-27": {"name": "Memorial Day Extension — Launch",        "category": "sale_launch",     "if_needed": False, "has_sms": True},
    "2026-05-28": {"name": "Quick Ship — Extension Sale",            "category": "product_specific","if_needed": True,  "has_sms": False},
    "2026-05-29": {"name": "Clearance — Final Days",                 "category": "sale_urgency",    "if_needed": False, "has_sms": False},
    "2026-05-30": {"name": "Grad Picks — Apartment Living",          "category": "product_specific","if_needed": True,  "has_sms": False},
    "2026-05-31": {"name": "Outdoor — Summer Ready",                 "category": "product_specific","if_needed": True,  "has_sms": False},
}

# June 2026 sends — Asana Master CRM, pulled 2026-06-02
_JUN_SENDS = {
    "2026-06-04": {"name": "Quick Ship",                             "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-07": {"name": "Summer Ready Sale Reminder (PT)",        "category": "sale_reminder",    "if_needed": False, "has_sms": False},
    "2026-06-08": {"name": "Summer Ready Flash Sale Final Hours (PT)","category": "sale_urgency",    "if_needed": False, "has_sms": False},
    "2026-06-10": {"name": "Watch the World Cup in Comfort",         "category": "editorial",        "if_needed": False, "has_sms": False},
    "2026-06-11": {"name": "Grad Picks — Apartment Living",          "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-13": {"name": "Quick Ship",                             "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-14": {"name": "Pet-Friendly Picks",                     "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-15": {"name": "Social Proof (PT)",                      "category": "plain_text",       "if_needed": False, "has_sms": False},
    "2026-06-16": {"name": "Newness Roundup",                        "category": "product_specific", "if_needed": False, "has_sms": True},
    "2026-06-17": {"name": "4th of July EA Launch",                  "category": "sale_launch",      "if_needed": False, "has_sms": True},
    "2026-06-18": {"name": "EA — Seating Feature",                   "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-19": {"name": "EA Reminder (PT)",                       "category": "sale_reminder",    "if_needed": False, "has_sms": False},
    "2026-06-20": {"name": "EA — Outdoor",                           "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-21": {"name": "Father's Day + EA Last Chance",          "category": "sale_urgency",     "if_needed": False, "has_sms": True},
    "2026-06-22": {"name": "4th of July Sale Launch + PM PT",        "category": "sale_launch",      "if_needed": False, "has_sms": True},
    "2026-06-23": {"name": "Sofa Feature",                           "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-24": {"name": "Sale Reminder (PT)",                     "category": "sale_reminder",    "if_needed": False, "has_sms": False},
    "2026-06-25": {"name": "Outdoor Collection",                     "category": "product_specific", "if_needed": False, "has_sms": False},
    "2026-06-26": {"name": "Bestsellers (PT)",                       "category": "plain_text",       "if_needed": False, "has_sms": False},
    "2026-06-27": {"name": "Order Now for Pre-Holiday Delivery",     "category": "other",            "if_needed": False, "has_sms": False},
    "2026-06-28": {"name": "Summer Hosting Essentials",              "category": "editorial",        "if_needed": False, "has_sms": True},
    "2026-06-29": {"name": "Sale Ongoing (PT)",                      "category": "sale_reminder",    "if_needed": False, "has_sms": False},
    "2026-06-30": {"name": "Storage & Accents",                      "category": "product_specific", "if_needed": False, "has_sms": False},
}

_base.FORECAST_MONTHS = [
    {"start": date(2026, 5, 1), "end": date(2026, 5, 31), "label": "May 2026", "sends": _MAY_SENDS},
    {"start": date(2026, 6, 1), "end": date(2026, 6, 30), "label": "June 2026", "sends": _JUN_SENDS},
]

_base.main()
