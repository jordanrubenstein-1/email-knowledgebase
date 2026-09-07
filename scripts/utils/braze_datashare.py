"""
Braze Raw Events Datashare — shared location/brand constants.

Centralizes the datashare database/schema names and the brand -> APP_GROUP_ID
map that were previously copy-pasted across update_lifecycle_stats.py,
lifecycle_dashboard_base.py, generate_lifecycle_report.py, cover_dashboard.py,
and sync_hav_hip_audience.py. New Braze-datashare consumers should import
from here instead of re-declaring the map.

See CLAUDE.md "Braze Raw Events Datashare (Snowflake)" for the source table.
"""

DB_PRIMARY = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA_PRIMARY = "DATALAKE_SHARING"

DB_TIER3 = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
SCHEMA_TIER3 = "DATALAKE_SHARING_TIERED"

# Brands served by the TIER3 datashare rather than the primary one.
TIER3_BRANDS = {"ID", "STF"}

APP_GROUP_IDS = {
    "BUR": "67093a1f24ebbe0065cb9c77",
    "HAV": "664223fb71bcf3005760dfc2",
    "CZ": "666672a4d8965b005ac6c1bd",
    "ID": "6666726b459b5e0059d7d687",
    "STF": "666716b3858150005b566956",
}


def get_datashare_location(brand: str) -> tuple[str, str]:
    """Return (database, schema) for the datashare that covers `brand`."""
    brand = brand.upper()
    if brand in TIER3_BRANDS:
        return DB_TIER3, SCHEMA_TIER3
    return DB_PRIMARY, SCHEMA_PRIMARY


def get_app_group_id(brand: str) -> str:
    brand = brand.upper()
    if brand not in APP_GROUP_IDS:
        raise ValueError(f"No APP_GROUP_ID configured for brand '{brand}'")
    return APP_GROUP_IDS[brand]


def qualified_view(view_name: str, brand: str) -> str:
    """Fully-qualified `db.schema.view` name for `view_name`, routed to the
    correct datashare (primary vs TIER3) for `brand`."""
    db, schema = get_datashare_location(brand)
    return f"{db}.{schema}.{view_name}"
