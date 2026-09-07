"""St. Frank Lifecycle Performance Dashboard
Run: streamlit run scripts/stf_lifecycle_dashboard.py
Email metrics sourced from campaign YAMLs (not Braze datashare — STF not included).
GA4 sessions + revenue sourced from Snowflake as normal.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import lifecycle_dashboard_base as _base

_base.APP_GROUP_ID  = "666716b3858150005b566956"
_base.BRAZE_DB      = _base.BRAZE_DB_TIER3
_base.BRAZE_SCHEMA  = _base.BRAZE_SCHEMA_TIER3
_base.GA4_TABLE     = "AIRBYTE_DATABASE.LANDING_ST_FRANK_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"
_base.ACCENT        = "#8B6F4E"
_base.BRAND_CODE    = "STF"
_base.BRAND_NAME    = "St. Frank"
_base.HAS_FORECAST  = False
_base.HAS_SMS       = False
_base.BRAZE_TIER3   = True
_base.MODES         = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

_base.CANVAS_GROUP_RULES = [
    (["welcome"],                                   "Welcome"),
    (["swatch post purchase", "swatch"],            "Swatch Post Purchase"),
    (["cart"],                                      "Abandon Cart"),
    (["browse", "product browse"],                  "Abandon Browse"),
    (["back in stock"],                             "Back in Stock"),
    (["order confirmation"],                        "Transactional"),
]
_base.GA4_CANVAS_RULES = [
    (["welcome"],                                   "Welcome"),
    (["swatch"],                                    "Swatch Post Purchase"),
    (["cart"],                                      "Abandon Cart"),
    (["browse"],                                    "Abandon Browse"),
    (["back in stock"],                             "Back in Stock"),
    (["order confirm"],                             "Transactional"),
]

_base.main()
