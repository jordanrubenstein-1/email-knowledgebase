#!/usr/bin/env python3
"""
Sync Burrow post-purchase flow routing + personalization attributes to Braze.

Runs daily via GitLab CI (2:15am UTC). For each flow, finds users whose
first-ever qualifying purchase was in the lookback window and writes all
personalization attributes in one pass.

────────────────────────────────────────────────────────────────────────────
PRIORITY (only ONE flow is assigned per user per run)
────────────────────────────────────────────────────────────────────────────
  1A > 1B > 2 > 3

If a user qualifies for multiple flows on the same day (e.g. bought a dining
table and a sofa in one order), only the highest-priority enrolled_at is set.

────────────────────────────────────────────────────────────────────────────
ROUTING ATTRIBUTES (written once, never overwritten)
────────────────────────────────────────────────────────────────────────────
  post_purchase_1a_enrolled_at  (string, ISO-8601)
      Set on first-ever dining TABLE purchase (when user has no chairs nearby).

  post_purchase_1b_enrolled_at  (string, ISO-8601)
      Set on first-ever indoor dining CHAIR purchase (Alto/Haiku/Sonnet), when the
      user has no dining table nearby (Flow 1B: chair → table recs). For 1B the
      rec slots below are filled with the 4 dining tables in the finish matching
      the purchased chair (Walnut/Oak), ordered by co-purchase (TABLE_RECS).

  post_purchase_2_enrolled_at   (string, ISO-8601)
      Set on first-ever non-sleeper sofa/sectional/loveseat purchase.

  post_purchase_3_enrolled_at   (string, ISO-8601)
      Set on first-ever sleeper sofa/sectional purchase.

────────────────────────────────────────────────────────────────────────────
PERSONALIZATION ATTRIBUTES (shared slots, overwritten on new enrollment)
────────────────────────────────────────────────────────────────────────────
  post_purchase_product_name    — e.g. "Serif Extendable Dining Table"
  post_purchase_product_img     — product hero image URL
  post_purchase_rec1_name       — e.g. "Haiku Dining Chairs (Moss Green)"
  post_purchase_rec1_img        — chair image URL
  post_purchase_rec1_url        — chair product page URL with ?variant=ID
  post_purchase_rec2_{name,img,url}
  post_purchase_rec3_{name,img,url}
  post_purchase_rec4_{name,img,url}

Rec slots are shared across all flows — since only one flow is active at a
time (enforced by canvas exception entry conditions), overwriting is correct.

────────────────────────────────────────────────────────────────────────────
ACCESSORY ATTRIBUTES
────────────────────────────────────────────────────────────────────────────
  post_purchase_has_ottoman      (boolean)  — flows 2 and 3 only
      True if the user has ever purchased any Ottoman from Burrow.
      Used in the Flow 2/3 emails to decide whether to include or skip
      ottoman upsell content.

  post_purchase_has_accent_chair (boolean)  — flows 2 and 3 only
      True if the user has ever purchased any Accent Chair from Burrow.
      Used in the Flow 2/3 emails similarly.

  post_purchase_has_dining_chairs (boolean)  — all flows
      True if the user has ever purchased an Alto, Haiku, or Sonnet
      Dining Chair. Used as a Flow 1A exception entry condition so that
      buyers who already own dining chairs are not enrolled.

  post_purchase_has_dining_tables (boolean)  — all flows
      True if the user has ever purchased a Serif/Harvest/Listo/Gallery
      dining table. Used as a Flow 1B exception entry condition so that
      buyers who already own a table are not enrolled.

────────────────────────────────────────────────────────────────────────────
FLOW 1A CHAIR SUPPRESSION
────────────────────────────────────────────────────────────────────────────
A user is NOT enrolled in Flow 1A if they have a dining chair purchase within
±14 days of their table purchase. The canvas Exit Criteria handle chairs
purchased during the 7-day wait period.

Usage:
  uv run python scripts/braze_automation/sync_bur_post_purchase_attributes.py
  uv run python scripts/braze_automation/sync_bur_post_purchase_attributes.py --dry-run
  uv run python scripts/braze_automation/sync_bur_post_purchase_attributes.py --backfill
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from snowflake_client import get_snowflake_client  # noqa: E402

# ── Braze ─────────────────────────────────────────────────────────────────────

BRAZE_BASE_URL = os.getenv("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")
BRAZE_API_KEY = os.getenv("BRAZE_API_KEY_BUR")

# ── Snowflake ─────────────────────────────────────────────────────────────────

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR_APP_GROUP_ID = "67093a1f24ebbe0065cb9c77"

# ── Product patterns ───────────────────────────────────────────────────────────

CHAIR_PATTERN = "%Dining Chair%"

TABLE_PATTERNS = [
    "%Gallery Dining Table%",
    "%Harvest Extendable Dining Table%",
    "%Listo Extendable Dining Table%",
    "%Serif Extendable Dining Table%",
]

SOFA_PATTERNS = ["%Sofa%", "%Sectional%", "%Loveseat%"]
SLEEPER_PATTERN = "%Sleep%"
OTTOMAN_PATTERN = "%Ottoman%"
ACCENT_CHAIR_PATTERN = "%Accent Chair%"
DINING_CHAIR_PATTERNS = ["%Alto Dining Chair%", "%Haiku Dining Chair%", "%Sonnet Dining Chair%"]

# ── Chair rec lookup ───────────────────────────────────────────────────────────
# Pre-computed chair recs per (collection, finish) from co-purchase analysis.
# Each rec is (display_name, img_url, product_url).

_IMG = "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/"
_HAIKU = "https://burrow.com/dining/haiku-dining-chairs?sku="
_ALTO = "https://burrow.com/dining/alto-dining-chairs?sku="


def _h(sku, v):
    return (_IMG + f"DRST-DC-HKU-S2-{sku}.jpg?v={v}", _HAIKU + f"DRST-DC-HKU-S2-{sku}")


def _a(sku, v):
    return (_IMG + f"DRST-DC-ALT-S2-{sku}.webp?v={v}", _ALTO + f"DRST-DC-ALT-S2-{sku}")


# (img_url, product_url) for each chair SKU suffix
_CHAIR = {
    "HKU-PYOK": _h("PYOK", "1744521831"),
    "HKU-MGOK": _h("MGOK", "1744521806"),
    "HKU-TNOK": _h("TNOK", "1744521868"),
    "HKU-MGWN": _h("MGWN", "1744521819"),
    "HKU-SGWN": _h("SGWN", "1744521855"),
    "HKU-PYWN": _h("PYWN", "1744521844"),
    "ALT-MGOK": _a("MGOK", "1747772306"),
    "ALT-PYOK": _a("PYOK", "1747772371"),
    "ALT-MGWN": _a("MGWN", "1747772332"),
    "ALT-PYWN": _a("PYWN", "1747772360"),
    "ALT-SGWN": _a("SGWN", "1747772278"),
}


def _rec(name, key):
    img, url = _CHAIR[key]
    return (name, img, url)


# Map (collection, finish) → [rec1, rec2, rec3, rec4]
# Rankings from co-purchase analysis Jul 2024–present.
CHAIR_RECS = {
    ("Serif", "Walnut"): [
        _rec("Haiku Dining Chairs (Moss Green / Walnut)", "HKU-MGWN"),
        _rec("Alto Dining Chairs (Moss Green / Walnut)",  "ALT-MGWN"),
        _rec("Haiku Dining Chairs (Stone Grey / Walnut)", "HKU-SGWN"),
        _rec("Haiku Dining Chairs (Papyrus / Walnut)",    "HKU-PYWN"),
    ],
    ("Serif", "Oak"): [
        _rec("Haiku Dining Chairs (Papyrus / Oak)",       "HKU-PYOK"),
        _rec("Haiku Dining Chairs (Moss Green / Oak)",    "HKU-MGOK"),
        _rec("Haiku Dining Chairs (Camel Leather / Oak)", "HKU-TNOK"),
        _rec("Alto Dining Chairs (Moss Green / Oak)",     "ALT-MGOK"),
    ],
    ("Harvest", "Walnut"): [
        _rec("Haiku Dining Chairs (Moss Green / Walnut)", "HKU-MGWN"),
        _rec("Haiku Dining Chairs (Papyrus / Walnut)",    "HKU-PYWN"),
        _rec("Alto Dining Chairs (Moss Green / Walnut)",  "ALT-MGWN"),
        _rec("Alto Dining Chairs (Papyrus / Walnut)",     "ALT-PYWN"),
    ],
    ("Harvest", "Oak"): [
        _rec("Haiku Dining Chairs (Moss Green / Oak)",    "HKU-MGOK"),
        _rec("Haiku Dining Chairs (Camel Leather / Oak)", "HKU-TNOK"),
        _rec("Haiku Dining Chairs (Papyrus / Oak)",       "HKU-PYOK"),
        _rec("Alto Dining Chairs (Moss Green / Oak)",     "ALT-MGOK"),
    ],
    ("Listo", "Walnut"): [
        _rec("Haiku Dining Chairs (Moss Green / Walnut)", "HKU-MGWN"),
        _rec("Alto Dining Chairs (Papyrus / Walnut)",     "ALT-PYWN"),
        _rec("Alto Dining Chairs (Moss Green / Walnut)",  "ALT-MGWN"),
        _rec("Haiku Dining Chairs (Papyrus / Walnut)",    "HKU-PYWN"),
    ],
    ("Listo", "Oak"): [
        _rec("Alto Dining Chairs (Moss Green / Oak)",     "ALT-MGOK"),
        _rec("Haiku Dining Chairs (Camel Leather / Oak)", "HKU-TNOK"),
        _rec("Haiku Dining Chairs (Moss Green / Oak)",    "HKU-MGOK"),
        _rec("Alto Dining Chairs (Papyrus / Oak)",        "ALT-PYOK"),
    ],
    ("Gallery", "Walnut"): [
        _rec("Haiku Dining Chairs (Papyrus / Walnut)",    "HKU-PYWN"),
        _rec("Haiku Dining Chairs (Moss Green / Walnut)", "HKU-MGWN"),
        _rec("Alto Dining Chairs (Stone Grey / Walnut)",  "ALT-SGWN"),
        _rec("Alto Dining Chairs (Papyrus / Walnut)",     "ALT-PYWN"),
    ],
    ("Gallery", "Oak"): [
        _rec("Haiku Dining Chairs (Camel Leather / Oak)", "HKU-TNOK"),
        _rec("Haiku Dining Chairs (Moss Green / Oak)",    "HKU-MGOK"),
        _rec("Alto Dining Chairs (Moss Green / Oak)",     "ALT-MGOK"),
        _rec("Alto Dining Chairs (Papyrus / Oak)",        "ALT-PYOK"),
    ],
}

# Table hero images by (collection, finish)
# All entries are plain-background product shots (matching Harvest/Gallery style) —
# picked from the product's live Shopify media (PRODUCT_MEDIA/MEDIA_IMAGE), not the
# lifestyle/detail/spec-diagram shots also attached to these products.
#
# Listo note (confirmed 2026-07-26 against the live PDP, burrow.com/products/listo-dining-table
# with ?Wood+Finish=Walnut selected): the CDN filenames' WN/OK suffixes are SWAPPED from the
# actual finish shown on-site — the file named "...LS-OK_EX..." is the Walnut image and
# "...LS-WN_EX..." is the Oak image. Mapped by verified rendered color/PDP behavior below,
# not by filename.
#
# Harvest Oak note (confirmed 2026-07-26): the old graphassets.com fallback 404s (403 on
# direct fetch) — swapped to "DRTB-DT-HV-OK.jpg?v=1744521888", which shares the exact
# upload timestamp with the already-live Harvest Walnut file (DRTB-DT-HV-WN.jpg, same
# version query) — the true matched pair, not the separate later "_extended" batch.
#
# Gallery Oak note (confirmed 2026-07-26 against the live PDP): a real Oak product shot
# exists (DRID-DT-GL-OK_AA...) — previously this incorrectly fell back to the Walnut image.
#
# Serif note (confirmed 2026-07-26 against the live PDP, both finishes clicked and
# checked): the Snowflake-listed hash-suffixed "_short_<hash>" files are valid images but
# aren't in the product's current live gallery (stale/replaced uploads). Using the
# "08_..._short" pair instead, confirmed present in both live Walnut and Oak galleries.
TABLE_IMAGES = {
    ("Serif",   "Walnut"): _IMG + "08_FDRTB-EXDT-SR-WN_short.jpg?v=1744520604",
    ("Serif",   "Oak"):    _IMG + "08_FDRTB-EXDT-SR-OK_short.jpg?v=1744520602",
    ("Harvest", "Walnut"): _IMG + "DRTB-DT-HV-WN.jpg?v=1744521888",
    ("Harvest", "Oak"):    _IMG + "DRTB-DT-HV-OK.jpg?v=1744521888",
    ("Listo",   "Walnut"): _IMG + "DRID-DT-LS-OK_EX_7c31c422-c449-4fef-90bc-7c23b646cc08.jpg?v=1755194645",
    ("Listo",   "Oak"):    _IMG + "DRID-DT-LS-WN_EX_5b170f8c-412d-433d-aa20-faef4fd9e8a2.jpg?v=1755194656",
    ("Gallery", "Walnut"): _IMG + "DRID-DT-GL-WN_AA.jpg?v=1754678751",
    ("Gallery", "Oak"):    _IMG + "DRID-DT-GL-OK_AA_8e7600ca-ee4b-481a-85b1-3642dd652e41.jpg?v=1754678751",
}

# ── Flow 1B: table recs (chair buyer → table recommendations) ───────────────────
# Finish-specific product page URLs, confirmed against campaigns/html/. The
# ?Wood+Finish= query param pre-selects the matching finish on the PDP.
_TBL_HANDLE = {
    "Serif":   "serif-extendable-dining-table",
    "Harvest": "harvest-extendable-dining-table",
    "Listo":   "listo-dining-table",
    "Gallery": "gallery-dining-table",
}
_TBL_DISPLAY = {
    "Serif":   "Serif Extendable Dining Table",
    "Harvest": "Harvest Extendable Dining Table",
    "Listo":   "Listo Extendable Dining Table",
    "Gallery": "Gallery Dining Table",
}


def _table_rec(coll: str, finish: str) -> tuple[str, str, str]:
    """Return (display_name, img_url, product_url) for a (table, finish)."""
    url = (
        f"https://burrow.com/products/{_TBL_HANDLE[coll]}"
        f"?Wood%2BFinish={finish}%20-%20Wood"
    )
    return (f"{_TBL_DISPLAY[coll]} ({finish})", TABLE_IMAGES[(coll, finish)], url)


def _table_recs(order: list[str], finish: str) -> list[tuple]:
    """Build the 4-table rec list for a finish from an ordered collection list."""
    return [_table_rec(coll, finish) for coll in order]


# Order of the 4 tables by co-purchase with dining chairs (Braze purchase
# datashare, all-time Jul 2024–present). DISTINCT chair-buyers who also bought
# each matched-finish table:
#   Oak    → Serif 78, Harvest 39, Listo 28, Gallery 11
#   Walnut → Serif 148, Harvest 37, Listo 36, Gallery 14
# Default (fallback) order per finish:
TABLE_RECS_DEFAULT = {
    "Walnut": _table_recs(["Serif", "Harvest", "Listo", "Gallery"], "Walnut"),
    "Oak":    _table_recs(["Serif", "Harvest", "Listo", "Gallery"], "Oak"),
}

# Per-(chair_line, finish) overrides — applied ONLY for cells with enough
# co-purchase volume (≥~40 matched-finish co-purchasers) AND a clear, non-noise
# deviation from the finish default. Everything else falls back to the default.
#   Alto/Walnut  (119): Serif 81, Listo 18, Harvest 15, Gallery 5  → Listo ahead of Harvest
#   Sonnet/Walnut (44): Serif 22, Listo 14, Gallery 5, Harvest 3   → Listo ≫ Harvest
# (Alto/Oak 37 and Sonnet/Oak 20 are too sparse/noisy — top ranks within ~1 user
#  — so they keep the finish default. Haiku cells match the default already.)
TABLE_RECS = {
    ("Alto",   "Walnut"): _table_recs(["Serif", "Listo", "Harvest", "Gallery"], "Walnut"),
    ("Sonnet", "Walnut"): _table_recs(["Serif", "Listo", "Gallery", "Harvest"], "Walnut"),
}

# Clean chair display name per line (for post_purchase_product_name / slice-2 copy).
_CHAIR_DISPLAY = {
    "Alto":   "Alto Dining Chairs",
    "Haiku":  "Haiku Dining Chairs",
    "Sonnet": "Sonnet Dining Chairs",
}


def _parse_branch(product_id: str) -> tuple[str, str] | None:
    """
    Return (collection, finish) from a dining table PRODUCT_ID string, or None.
    Examples:
      "Serif Extendable Dining Table (59 to 79) - Walnut - Wood" → ("Serif", "Walnut")
      "Harvest Extendable Dining Table (59' to 79') - Oak - Wood" → ("Harvest", "Oak")
    """
    pid = product_id or ""
    for coll in ("Serif", "Harvest", "Listo", "Gallery"):
        if coll.lower() in pid.lower():
            finish = "Walnut" if "Walnut" in pid else "Oak" if "Oak" in pid else None
            if finish:
                return (coll, finish)
    return None


def _parse_chair(product_id: str) -> tuple[str, str] | None:
    """
    Return (chair_line, finish) from a dining-chair PRODUCT_ID, or None.
    Examples:
      "Alto Dining Chairs (Set of 2) - Moss Green/Walnut" → ("Alto", "Walnut")
      "Haiku Dining Chairs (Set of 2) - Camel Leather/Oak" → ("Haiku", "Oak")
      "Sonnet Dining Chairs (Set of 2)"  → None  (no finish in the string)
    Only the three indoor lines (Alto/Haiku/Sonnet) qualify; finish (Walnut/Oak)
    must be present. Bare product records without a finish return None → the
    template's abort-guard skips the send (same behaviour as 1A on bare tables).
    """
    pid = product_id or ""
    for line in ("Alto", "Haiku", "Sonnet"):
        if line.lower() in pid.lower():
            finish = "Walnut" if "Walnut" in pid else "Oak" if "Oak" in pid else None
            if finish:
                return (line, finish)
    return None


# ── SQL helpers ────────────────────────────────────────────────────────────────

def _table_where():
    parts = [f"PRODUCT_ID ILIKE '{pat}'" for pat in TABLE_PATTERNS]
    return "(" + " OR ".join(parts) + ")"


def _sofa_where():
    parts = [f"PRODUCT_ID ILIKE '{pat}'" for pat in SOFA_PATTERNS]
    return "(" + " OR ".join(parts) + ")"


def _chair_where():
    # Flow 1B targets the three indoor dining-chair lines (Alto/Haiku/Sonnet) —
    # not the broad %Dining Chair% (which also matches Relay Outdoor / Dunes Teak,
    # for which we have no matched-finish table recs).
    parts = [f"PRODUCT_ID ILIKE '{pat}'" for pat in DINING_CHAIR_PATTERNS]
    return "(" + " OR ".join(parts) + ")"


# ── Fetch functions ────────────────────────────────────────────────────────────

def fetch_flow_1a_buyers(client, backfill: bool) -> list[dict]:
    """
    Return users whose first-ever dining TABLE purchase was in the lookback
    window AND who have no dining chair purchase within ±14 days of that table
    purchase. Returns [{"user_id": ..., "purchased_at": ISO-str, "product_id": ...}].
    """
    time_filter = (
        ""
        if backfill
        else "WHERE first_purchase_time >= DATEADD('hour', -48, CURRENT_TIMESTAMP())"
    )
    table_where = _table_where()
    sql = f"""
        WITH first_table_buys AS (
            SELECT EXTERNAL_USER_ID, TO_TIMESTAMP(TIME) AS first_purchase_time, PRODUCT_ID AS first_product_id
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IS NOT NULL
              AND {table_where}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY EXTERNAL_USER_ID ORDER BY TIME ASC) = 1
        ),
        qualified AS (
            SELECT EXTERNAL_USER_ID, first_purchase_time, first_product_id
            FROM first_table_buys
            {time_filter}
        )
        SELECT q.EXTERNAL_USER_ID, q.first_purchase_time, q.first_product_id
        FROM qualified q
        WHERE NOT EXISTS (
            SELECT 1
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED c
            WHERE c.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND c.EXTERNAL_USER_ID = q.EXTERNAL_USER_ID
              AND c.PRODUCT_ID ILIKE '{CHAIR_PATTERN}'
              AND TO_TIMESTAMP(c.TIME) BETWEEN
                    DATEADD('day', -14, q.first_purchase_time)
                AND DATEADD('day', +14, q.first_purchase_time)
        )
    """
    rows = client.execute_query(sql)
    return [
        {
            "user_id": r["EXTERNAL_USER_ID"],
            "purchased_at": (
                r["FIRST_PURCHASE_TIME"].isoformat()
                if hasattr(r["FIRST_PURCHASE_TIME"], "isoformat")
                else str(r["FIRST_PURCHASE_TIME"])
            ),
            "product_id": r["FIRST_PRODUCT_ID"],
        }
        for r in rows
    ]


def fetch_flow_1b_buyers(client, backfill: bool) -> list[dict]:
    """
    Return users whose first-ever indoor dining-CHAIR purchase (Alto/Haiku/Sonnet)
    was in the lookback window AND who have no dining-table purchase within ±14
    days of that chair purchase (enforces "haven't purchased a dining table").
    Mirrors fetch_flow_1a_buyers, chair↔table swapped.
    Returns [{"user_id": ..., "purchased_at": ISO-str, "product_id": ...}].
    """
    time_filter = (
        ""
        if backfill
        else "WHERE first_purchase_time >= DATEADD('hour', -48, CURRENT_TIMESTAMP())"
    )
    chair_where = _chair_where()
    table_where = _table_where()
    sql = f"""
        WITH first_chair_buys AS (
            SELECT EXTERNAL_USER_ID, TO_TIMESTAMP(TIME) AS first_purchase_time, PRODUCT_ID AS first_product_id
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IS NOT NULL
              AND {chair_where}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY EXTERNAL_USER_ID ORDER BY TIME ASC) = 1
        ),
        qualified AS (
            SELECT EXTERNAL_USER_ID, first_purchase_time, first_product_id
            FROM first_chair_buys
            {time_filter}
        )
        SELECT q.EXTERNAL_USER_ID, q.first_purchase_time, q.first_product_id
        FROM qualified q
        WHERE NOT EXISTS (
            SELECT 1
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED t
            WHERE t.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND t.EXTERNAL_USER_ID = q.EXTERNAL_USER_ID
              AND {table_where.replace("PRODUCT_ID", "t.PRODUCT_ID")}
              AND TO_TIMESTAMP(t.TIME) BETWEEN
                    DATEADD('day', -14, q.first_purchase_time)
                AND DATEADD('day', +14, q.first_purchase_time)
        )
    """
    rows = client.execute_query(sql)
    return [
        {
            "user_id": r["EXTERNAL_USER_ID"],
            "purchased_at": (
                r["FIRST_PURCHASE_TIME"].isoformat()
                if hasattr(r["FIRST_PURCHASE_TIME"], "isoformat")
                else str(r["FIRST_PURCHASE_TIME"])
            ),
            "product_id": r["FIRST_PRODUCT_ID"],
        }
        for r in rows
    ]


def _fetch_simple_flow(client, backfill: bool, where_clause: str) -> list[dict]:
    """Generic first-ever-purchase fetcher for flows 2, 3."""
    time_filter = (
        ""
        if backfill
        else "WHERE first_purchase_time >= DATEADD('hour', -48, CURRENT_TIMESTAMP())"
    )
    sql = f"""
        WITH first_buys AS (
            SELECT EXTERNAL_USER_ID, TO_TIMESTAMP(TIME) AS first_purchase_time
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IS NOT NULL
              AND {where_clause}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY EXTERNAL_USER_ID ORDER BY TIME ASC) = 1
        )
        SELECT EXTERNAL_USER_ID, first_purchase_time
        FROM first_buys
        {time_filter}
    """
    rows = client.execute_query(sql)
    return [
        {
            "user_id": r["EXTERNAL_USER_ID"],
            "purchased_at": (
                r["FIRST_PURCHASE_TIME"].isoformat()
                if hasattr(r["FIRST_PURCHASE_TIME"], "isoformat")
                else str(r["FIRST_PURCHASE_TIME"])
            ),
        }
        for r in rows
    ]


def fetch_all_buyers(client, backfill: bool) -> dict:
    """Fetch first-time buyers for all 4 flows."""
    sofa_clause = (
        _sofa_where()
        + f" AND PRODUCT_ID NOT ILIKE '{SLEEPER_PATTERN}'"
    )
    return {
        "1A": fetch_flow_1a_buyers(client, backfill),
        "1B": fetch_flow_1b_buyers(client, backfill),
        "2":  _fetch_simple_flow(client, backfill, sofa_clause),
        "3":  _fetch_simple_flow(client, backfill, f"PRODUCT_ID ILIKE '{SLEEPER_PATTERN}'"),
    }


# ── Attribute builder ─────────────────────────────────────────────────────────

FLOW_ATTR = {
    "1A": "post_purchase_1a_enrolled_at",
    "1B": "post_purchase_1b_enrolled_at",
    "2":  "post_purchase_2_enrolled_at",
    "3":  "post_purchase_3_enrolled_at",
}

# Priority order — only the first matching flow is assigned to each user.
FLOW_PRIORITY = ("1A", "1B", "2", "3")


def _rec_attrs(recs: list[tuple]) -> dict:
    """Build post_purchase_rec{1-4}_{name,img,url} from a recs list."""
    attrs = {}
    for i, (name, img, url) in enumerate(recs[:4], start=1):
        attrs[f"post_purchase_rec{i}_name"] = name
        attrs[f"post_purchase_rec{i}_img"]  = img
        attrs[f"post_purchase_rec{i}_url"]  = url
    return attrs


def fetch_accessory_ownership(client, user_ids: list[str]) -> tuple[set, set, set, set]:
    """
    For the given user IDs, return
    (ottoman_owners, accent_chair_owners, dining_chair_owners, dining_table_owners) —
    sets of external_user_ids who have ever purchased those products.
    Queried in one pass; chunked to avoid oversized IN clauses.
    """
    ottoman_owners: set[str] = set()
    accent_chair_owners: set[str] = set()
    dining_chair_owners: set[str] = set()
    dining_table_owners: set[str] = set()

    dining_chair_where = " OR ".join(
        f"PRODUCT_ID ILIKE '{p}'" for p in DINING_CHAIR_PATTERNS
    )
    dining_table_where = " OR ".join(
        f"PRODUCT_ID ILIKE '{p}'" for p in TABLE_PATTERNS
    )

    chunk_size = 500
    for i in range(0, len(user_ids), chunk_size):
        chunk = user_ids[i : i + chunk_size]
        id_list = ", ".join(f"'{uid}'" for uid in chunk)
        sql = f"""
            SELECT
                EXTERNAL_USER_ID,
                MAX(CASE WHEN PRODUCT_ID ILIKE '{OTTOMAN_PATTERN}' THEN 1 ELSE 0 END)      AS has_ottoman,
                MAX(CASE WHEN PRODUCT_ID ILIKE '{ACCENT_CHAIR_PATTERN}' THEN 1 ELSE 0 END) AS has_accent_chair,
                MAX(CASE WHEN {dining_chair_where} THEN 1 ELSE 0 END)                       AS has_dining_chairs,
                MAX(CASE WHEN {dining_table_where} THEN 1 ELSE 0 END)                       AS has_dining_tables
            FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
            WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
              AND EXTERNAL_USER_ID IN ({id_list})
              AND (
                    PRODUCT_ID ILIKE '{OTTOMAN_PATTERN}'
                 OR PRODUCT_ID ILIKE '{ACCENT_CHAIR_PATTERN}'
                 OR {dining_chair_where}
                 OR {dining_table_where}
              )
            GROUP BY EXTERNAL_USER_ID
        """
        for row in client.execute_query(sql):
            uid = row["EXTERNAL_USER_ID"]
            if row["HAS_OTTOMAN"]:
                ottoman_owners.add(uid)
            if row["HAS_ACCENT_CHAIR"]:
                accent_chair_owners.add(uid)
            if row["HAS_DINING_CHAIRS"]:
                dining_chair_owners.add(uid)
            if row["HAS_DINING_TABLES"]:
                dining_table_owners.add(uid)

    return ottoman_owners, accent_chair_owners, dining_chair_owners, dining_table_owners


def build_braze_updates(all_buyers: dict, client) -> list[dict]:
    """
    Assign each user to exactly one flow (highest priority) and build the
    attribute dict for Braze Users/Track.

    Priority: 1A > 1B > 2 > 3. If a user qualifies for multiple flows on the
    same day (e.g. bought a dining table and a sofa), only the highest-priority
    enrolled_at is written.

    Flows 2 and 3 also receive post_purchase_has_ottoman and
    post_purchase_has_accent_chair booleans, queried from purchase history.
    """
    # Build fast lookup: flow -> {user_id -> buyer_dict}
    buyers_by_flow: dict[str, dict[str, dict]] = {
        flow: {b["user_id"]: b for b in buyers}
        for flow, buyers in all_buyers.items()
    }

    # Assign each user to exactly one flow by priority
    assigned: dict[str, str] = {}  # user_id -> flow
    for flow in FLOW_PRIORITY:
        for uid in buyers_by_flow[flow]:
            if uid not in assigned:
                assigned[uid] = flow

    updates: dict[str, dict] = {}

    for uid, flow in assigned.items():
        b = buyers_by_flow[flow][uid]
        attrs: dict = {FLOW_ATTR[flow]: b["purchased_at"]}

        if flow == "1A":
            branch = _parse_branch(b.get("product_id", ""))
            if branch and branch in CHAIR_RECS:
                coll, _ = branch
                attrs["post_purchase_product_name"] = (
                    f"{coll} Extendable Dining Table" if coll != "Gallery" else "Gallery Dining Table"
                )
                attrs["post_purchase_product_img"] = TABLE_IMAGES[branch]
                attrs.update(_rec_attrs(CHAIR_RECS[branch]))
            else:
                attrs["post_purchase_product_name"] = (b.get("product_id") or "").split(" - ")[0]

        elif flow == "1B":
            chair = _parse_chair(b.get("product_id", ""))
            if chair:
                line, finish = chair
                attrs["post_purchase_product_name"] = _CHAIR_DISPLAY[line]
                # Per-(chair_line, finish) order where co-purchase data is strong;
                # otherwise the per-finish default. Always all 4 tables, matched finish.
                recs = TABLE_RECS.get((line, finish)) or TABLE_RECS_DEFAULT[finish]
                attrs.update(_rec_attrs(recs))
            else:
                # Bare chair record with no parseable finish → no recs written;
                # the template abort-guard skips the send (same as 1A on bare tables).
                attrs["post_purchase_product_name"] = (b.get("product_id") or "").split(" - ")[0]

        updates[uid] = attrs

    # Fetch accessory ownership for all enrolled users.
    # post_purchase_has_dining_chairs is written for every flow (exception entry condition for 1A).
    # post_purchase_has_ottoman and post_purchase_has_accent_chair are written for flows 2 + 3 only.
    all_users = list(assigned.keys())
    if all_users:
        ottoman_owners, accent_chair_owners, dining_chair_owners, dining_table_owners = (
            fetch_accessory_ownership(client, all_users)
        )
        for uid, flow in assigned.items():
            updates[uid]["post_purchase_has_dining_chairs"] = uid in dining_chair_owners
            # Written for every flow — the Flow 1B canvas uses it as an exception
            # entry condition so buyers who already own a table aren't enrolled
            # (mirrors post_purchase_has_dining_chairs for Flow 1A).
            updates[uid]["post_purchase_has_dining_tables"] = uid in dining_table_owners
            if flow in ("2", "3"):
                updates[uid]["post_purchase_has_ottoman"]      = uid in ottoman_owners
                updates[uid]["post_purchase_has_accent_chair"] = uid in accent_chair_owners

    return [{"external_id": uid, **attrs} for uid, attrs in updates.items()]


# ── Braze push ─────────────────────────────────────────────────────────────────

def push_to_braze(updates: list[dict], dry_run: bool) -> None:
    if not BRAZE_API_KEY:
        raise RuntimeError("BRAZE_API_KEY_BUR not set in .env")

    total = len(updates)
    sent = 0
    for i in range(0, total, 75):
        batch = updates[i : i + 75]
        if dry_run:
            print(f"  [dry-run] batch {i // 75 + 1}: {len(batch)} users")
            for u in batch[:2]:
                print(f"    {u}")
            if len(batch) > 2:
                print(f"    ... ({len(batch) - 2} more)")
            sent += len(batch)
            continue

        resp = requests.post(
            f"{BRAZE_BASE_URL}/users/track",
            headers={"Authorization": f"Bearer {BRAZE_API_KEY}", "Content-Type": "application/json"},
            json={"attributes": batch},
            timeout=30,
        )
        if not resp.ok:
            print(f"  [error] batch {i // 75 + 1} ({resp.status_code}): {resp.text[:300]}")
        else:
            sent += len(batch)
            print(f"  Batch {i // 75 + 1}: {len(batch)} users updated")

    print(f"\n{'[dry-run] ' if dry_run else ''}Total: {sent}/{total} users processed")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--backfill", action="store_true", help="Process all-time (first deploy)")
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}{'[BACKFILL] ' if args.backfill else ''}"
          f"BUR post-purchase attribute sync — lookback: {'all time' if args.backfill else 'last 48h'}\n")

    client = get_snowflake_client(schema=SCHEMA, database=DB)

    print("Querying first-time buyers for all flows...")
    all_buyers = fetch_all_buyers(client, backfill=args.backfill)
    for flow, buyers in all_buyers.items():
        print(f"  Flow {flow}: {len(buyers)} first-time buyers → {FLOW_ATTR[flow]}")

    updates = build_braze_updates(all_buyers, client)
    print(f"\n{len(updates)} unique users to update in Braze\n")

    if not updates:
        print("Nothing to do.")
        return

    push_to_braze(updates, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
