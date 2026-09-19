"""
Update lifecycle FigJam board stats — rolling 12-week weekly averages.

Queries Snowflake for the latest metrics for each canvas row on the
Burrow and Interior Define FigJam boards, then updates the stats text
nodes in place using the Figma Plugin API.

Each stats text node is named with a stable identifier:
    lifecycle-stats::{brand}::{canvas-slug}

Most nodes carry email (or SMS-only) stats. Some carry extra structure that
this script reproduces so an update never regresses the board:
    • SMS sub-section — canvases that also send SMS (see SMS_SUBSECTION) get a
      "── SMS ──" block. SMS sends are per-canvas from the datashare; SMS
      sessions/revenue come from GA4, or render "—" when SMS campaign names are
      shared across canvases and can't be split.
    • Swatch orders — ID swatch canvases (see SWATCH_CANVASES) append a
      "Swatch Orders/wk" line from GA4 generate_lead_swatch (EMAIL, last-click).

The script only computes the payloads — it cannot call the Figma MCP itself.
Run it via Claude, which applies the JSON payloads to the boards. Full runbook:
    docs/lifecycle-figjam-stats-update.md

Usage:
    uv run python scripts/update_lifecycle_stats.py
    uv run python scripts/update_lifecycle_stats.py --dry-run
    uv run python scripts/update_lifecycle_stats.py --board id
    uv run python scripts/update_lifecycle_stats.py --board bur
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

# Allow `from scripts.xxx import ...` when invoked as a file path
# (uv run python scripts/update_lifecycle_stats.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────

BOARDS = {
    "bur": "VxjmwZuwCf3bsWfMGLOlOm",
    "id":  "IHASW2pUj5Zfy4ZKJlTyDR",
}

# Braze raw events datashare
DB_PRIMARY = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA_PRIMARY = "DATALAKE_SHARING"
DB_TIER3 = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
SCHEMA_TIER3 = "DATALAKE_SHARING_TIERED"

# Brand → datashare config
BRAND_CONFIG = {
    "bur": {
        "app_group_id": "67093a1f24ebbe0065cb9c77",
        "db": DB_PRIMARY,
        "schema": SCHEMA_PRIMARY,
        "ga4_schema": "LANDING_BURROW_GA4",
    },
    "id": {
        "app_group_id": "6666726b459b5e0059d7d687",
        "db": DB_TIER3,
        "schema": SCHEMA_TIER3,
        "ga4_schema": "LANDING_INTERIORDEFINE_GA4",
    },
}

# Canvas hex IDs for the datashare — maps node name slug → hex canvas ID(s)
# Lists support canvases split across multiple hex IDs (e.g. Swatch PP old+new)
CANVAS_IDS = {
    # BUR
    "bur::welcome-general":             ["67227526a4311300737cee81"],
    "bur::post-order-welcome":          ["6941ce9f44fe4b00643a081c"],
    "bur::abandon-browse-multi":        ["69fd3b44bafe140081cff59e"],
    "bur::abandon-browse-product-viewed": ["6917427b99358600634fe4e5"],
    "bur::abandon-cart":                ["6969482705594d00645ea309"],
    "bur::swatch-post-purchase":        ["69715b92b5e08d0065edaf50"],
    "bur::sms-welcome":                 ["673649e7f9dee40073052292"],  # SMS only
    "bur::post-order-cross-sell":       ["69f8a9b37836af007fe3b29f"],
    # ID
    "id::cart-abandon":                 ["6938e165e6ccb600638bd400"],
    "id::sms-welcome":                  ["67c1d8240164820062088bbb"],  # SMS only
    "id::welcome-series":               ["66cfcbced4b53b0065d07435"],
    "id::collection-abandon":           ["69165689e57910006306426e"],
    "id::category-abandon":             ["69e7bd9e0606b500c4e2cc59"],
    "id::swatch-post-purchase":         ["69ea5da43ffb4800c3029b14", "66be3a290645240075070a3d"],
    "id::browse-abandon-multi":         ["699a006c97ee4600633a266d"],
    "id::swatch-cart-abandon":          ["6974a5ce1e4d7c0065a37547"],
    "id::post-purchase":                ["69d28b4766794500632e0822"],
}

# GA4 campaign name patterns for session/revenue attribution
GA4_PATTERNS = {
    "bur::welcome-general":              "TRG_EM%Welcome%",
    "bur::post-order-welcome":           "TRG_EM%Welcome_New_Purchaser%",
    "bur::abandon-browse-multi":         "TRG_EM%Abandon_Browse_T%V3%",
    "bur::abandon-browse-product-viewed": "TRG_EM%Abandon_Browse_T%V2%",
    "bur::abandon-cart":                 "TRG_EM%Cart_Abandon%",
    "bur::swatch-post-purchase":         "TRG_EM%Swatch%",
    "bur::sms-welcome":                  "TRG_SMS%Welcome%",
    "bur::post-order-cross-sell":        None,  # too few sends to attribute
    "id::cart-abandon":                  "TRG_EM%Cart_Abandon%",
    "id::sms-welcome":                   "TRG_SMS%Welcome%",
    "id::welcome-series":                "TRG_EM%Welcome%",
    "id::collection-abandon":            "TRG_EM%Collection%Abandon%",
    "id::category-abandon":              "TRG_EM%Category%Abandon%",
    "id::swatch-post-purchase":          "TRG_EM%Swatch%",
    "id::browse-abandon-multi":          "TRG_EM%Browse_Abandon%",
    "id::swatch-cart-abandon":           "TRG_EM%Swatch_Cart%",
    "id::post-purchase":                 "TRG_EM%Post_Purchase%",
}

# SMS-only canvases (no email opens/UOR)
SMS_ONLY = {"bur::sms-welcome", "id::sms-welcome"}

# Canvases that ALSO send SMS within the same canvas — render an "── SMS ──"
# sub-section below the email stats. SMS sends come from the datashare per
# CANVAS_ID (always reliable). SMS sessions/revenue come from GA4 by campaign
# name; set "sms_ga4_pattern": None when the SMS steps share campaign names with
# another canvas (GA4 can't split them) — sessions/revenue then render as "—".
#   NOTE: bur::abandon-browse-multi and bur::abandon-browse-product-viewed both
#   use TRG_SMS_..._BW_Abandon_Browse_T2/T5_V1, so neither can claim GA4 SMS
#   sessions/revenue individually (combined ≈ the "Abandon_Browse" SMS total).
SMS_SUBSECTION = {
    "bur::abandon-browse-multi":          {"sms_ga4_pattern": None},
    "bur::abandon-browse-product-viewed": {"sms_ga4_pattern": None},
    "bur::abandon-cart":                  {"sms_ga4_pattern": "TRG_SMS%Cart_Abandon%"},
    "id::cart-abandon":                   {"sms_ga4_pattern": "TRG_SMS%Cart_Abandon%"},
}

# ID canvases that also report swatch orders — appended as a "Swatch Orders/wk"
# line. Uses GA4 KEYEVENTS:GENERATE_LEAD_SWATCH (EMAIL channel, last-click, same
# attribution basis as revenue). That column exists only in the ID GA4 table.
SWATCH_CANVASES = {
    "id::swatch-cart-abandon": {"ga4_pattern": "TRG_EM%Swatch_Cart%"},
}


# ── Snowflake queries ─────────────────────────────────────────────────────────

def get_braze_stats(client, brand: str, canvas_slug: str) -> dict:
    """Pull sends, unique opens, UOR, and T1 sends for a canvas."""
    cfg = BRAND_CONFIG[brand]
    canvas_ids = CANVAS_IDS.get(f"{brand}::{canvas_slug}", [])
    if not canvas_ids:
        return {}

    ids_sql = ", ".join(f"'{cid}'" for cid in canvas_ids)
    db, schema = cfg["db"], cfg["schema"]
    app = cfg["app_group_id"]
    is_sms = f"{brand}::{canvas_slug}" in SMS_ONLY

    send_table  = f"{db}.{schema}.USERS_MESSAGES_{'SMS' if is_sms else 'EMAIL'}_SEND_SHARED"
    open_table  = f"{db}.{schema}.USERS_MESSAGES_EMAIL_OPEN_SHARED"

    # Total sends + unique recipients (12 weeks)
    rows = client.execute_query(f"""
        SELECT
          COUNT(DISTINCT ID)      AS total_sends,
          COUNT(DISTINCT USER_ID) AS unique_recipients,
          MIN(TO_TIMESTAMP(TIME)) AS first_send
        FROM {send_table}
        WHERE APP_GROUP_ID = '{app}'
          AND CANVAS_ID IN ({ids_sql})
          AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
    """)
    row = rows[0] if rows else {}
    total_sends      = row.get("TOTAL_SENDS") or 0
    unique_recipients = row.get("UNIQUE_RECIPIENTS") or 0

    # T1 sends (step name contains _T1_)
    t1_rows = client.execute_query(f"""
        SELECT COUNT(DISTINCT ID) AS t1_sends
        FROM {send_table}
        WHERE APP_GROUP_ID = '{app}'
          AND CANVAS_ID IN ({ids_sql})
          AND CANVAS_STEP_NAME ILIKE '%_T1_%'
          AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
    """)
    t1_sends = (t1_rows[0].get("T1_SENDS") or 0) if t1_rows else 0

    result = {
        "sends_12w": total_sends,
        "t1_sends_12w": t1_sends,
    }

    if not is_sms:
        # Unique opens (machine opens included — matches Braze dashboard)
        open_rows = client.execute_query(f"""
            SELECT COUNT(DISTINCT USER_ID) AS unique_openers
            FROM {open_table}
            WHERE APP_GROUP_ID = '{app}'
              AND CANVAS_ID IN ({ids_sql})
              AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
        """)
        unique_openers = (open_rows[0].get("UNIQUE_OPENERS") or 0) if open_rows else 0
        result["unique_opens_12w"] = unique_openers
        result["uor_pct"] = (
            round(unique_openers * 100.0 / unique_recipients, 1)
            if unique_recipients else None
        )

    return result


def get_ga4_stats(client, brand: str, canvas_slug: str) -> dict:
    """Pull sessions and revenue from GA4 for a canvas."""
    cfg = BRAND_CONFIG[brand]
    pattern = GA4_PATTERNS.get(f"{brand}::{canvas_slug}")
    is_sms = f"{brand}::{canvas_slug}" in SMS_ONLY
    channel = "'SMS'" if is_sms else "'EMAIL'"
    if not pattern:
        return {}

    ga4_table = f"AIRBYTE_DATABASE.{cfg['ga4_schema']}.TRAFFIC_SESSION_PERFORMANCE_DAILY"
    rows = client.execute_query(f"""
        SELECT SUM(SESSIONS) AS sessions, SUM(TOTALREVENUE) AS revenue
        FROM {ga4_table}
        WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) = {channel}
          AND DATE >= TO_CHAR(DATEADD('week', -12, CURRENT_DATE()), 'YYYYMMDD')
          AND SESSIONCAMPAIGNNAME ILIKE '{pattern}'
    """)
    row = rows[0] if rows else {}
    return {
        "sessions_12w": row.get("SESSIONS") or 0,
        "revenue_12w": row.get("REVENUE") or 0,
    }


def get_sms_stats(client, brand: str, canvas_slug: str) -> dict:
    """SMS sends (datashare, per-canvas) + SMS sessions/revenue (GA4, if attributable).

    Returns {} for canvases that don't carry an SMS sub-section. When the
    canvas's SMS steps share campaign names with another canvas
    (sms_ga4_pattern=None), sessions/revenue are returned as None → rendered "—".
    """
    key = f"{brand}::{canvas_slug}"
    if key not in SMS_SUBSECTION:
        return {}

    cfg = BRAND_CONFIG[brand]
    canvas_ids = CANVAS_IDS.get(key, [])
    if not canvas_ids:
        return {}
    ids_sql = ", ".join(f"'{cid}'" for cid in canvas_ids)
    db, schema, app = cfg["db"], cfg["schema"], cfg["app_group_id"]

    rows = client.execute_query(f"""
        SELECT COUNT(DISTINCT ID) AS sms_sends
        FROM {db}.{schema}.USERS_MESSAGES_SMS_SEND_SHARED
        WHERE APP_GROUP_ID = '{app}'
          AND CANVAS_ID IN ({ids_sql})
          AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
    """)
    result = {"sms_sends_12w": (rows[0].get("SMS_SENDS") or 0) if rows else 0}

    pattern = SMS_SUBSECTION[key]["sms_ga4_pattern"]
    if pattern:
        g = client.execute_query(f"""
            SELECT SUM(SESSIONS) AS sessions, SUM(TOTALREVENUE) AS revenue
            FROM AIRBYTE_DATABASE.{cfg['ga4_schema']}.TRAFFIC_SESSION_PERFORMANCE_DAILY
            WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) = 'SMS'
              AND DATE >= TO_CHAR(DATEADD('week', -12, CURRENT_DATE()), 'YYYYMMDD')
              AND SESSIONCAMPAIGNNAME ILIKE '{pattern}'
        """)
        row = g[0] if g else {}
        result["sms_sessions_12w"] = row.get("SESSIONS") or 0
        result["sms_revenue_12w"] = row.get("REVENUE") or 0
    else:
        result["sms_sessions_12w"] = None
        result["sms_revenue_12w"] = None

    return result


def get_swatch_stats(client, brand: str, canvas_slug: str) -> dict:
    """GA4 generate_lead_swatch (EMAIL, last-click) for ID swatch canvases.

    Returns {} for canvases not in SWATCH_CANVASES.
    """
    key = f"{brand}::{canvas_slug}"
    if key not in SWATCH_CANVASES:
        return {}

    cfg = BRAND_CONFIG[brand]
    pattern = SWATCH_CANVASES[key]["ga4_pattern"]
    ga4_table = f"AIRBYTE_DATABASE.{cfg['ga4_schema']}.TRAFFIC_SESSION_PERFORMANCE_DAILY"
    rows = client.execute_query(f"""
        SELECT SUM("KEYEVENTS:GENERATE_LEAD_SWATCH") AS swatches
        FROM {ga4_table}
        WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) = 'EMAIL'
          AND DATE >= TO_CHAR(DATEADD('week', -12, CURRENT_DATE()), 'YYYYMMDD')
          AND SESSIONCAMPAIGNNAME ILIKE '{pattern}'
    """)
    return {"swatches_12w": (rows[0].get("SWATCHES") or 0) if rows else 0}


# ── Stats text formatter ───────────────────────────────────────────────────────

def fmt(n, prefix="", suffix="", decimals=0, dash_if_zero=False):
    """Format a number with commas, or — if zero and dash_if_zero."""
    if n is None or (dash_if_zero and n == 0):
        return "—"
    if decimals:
        return f"{prefix}{n:,.{decimals}f}{suffix}"
    return f"{prefix}{int(round(n)):,}{suffix}"


def build_stats_text(brand: str, canvas_slug: str, braze: dict, ga4: dict,
                     sms: dict = None, swatch: dict = None, weeks: int = 12) -> str:
    """Compose the stacked stats string for a canvas node.

    Optional add-ons, rendered to match the board layout:
      • swatch — appends a "Swatch Orders/wk" line (ID swatch canvases)
      • sms    — appends a "── SMS ──" sub-section (canvases that also send SMS)
    """
    is_sms = f"{brand}::{canvas_slug}" in SMS_ONLY

    sends_wk     = round((braze.get("sends_12w") or 0) / weeks)
    t1_sends_wk  = round((braze.get("t1_sends_12w") or 0) / weeks)
    sessions_wk  = round((ga4.get("sessions_12w") or 0) / weeks)
    revenue_wk   = round((ga4.get("revenue_12w") or 0) / weeks)
    opens_wk     = round((braze.get("unique_opens_12w") or 0) / weeks)
    uor          = braze.get("uor_pct")
    rev_per_m    = (
        round(revenue_wk * 1000 / sends_wk) if sends_wk and revenue_wk else None
    )

    lines = [
        f"T1 Sends/wk: {fmt(t1_sends_wk, dash_if_zero=True)}",
        f"Sends/wk: {fmt(sends_wk, dash_if_zero=True)}",
    ]
    if not is_sms:
        lines.append(f"Unique Opens/wk: {fmt(opens_wk, dash_if_zero=True)}")
        lines.append(f"UOR: {fmt(uor, suffix='%', decimals=1) if uor else '—'}")
    lines.append(f"Sessions/wk: {fmt(sessions_wk, dash_if_zero=True)}")
    lines.append(f"Rev/wk: {fmt(revenue_wk, prefix='$', dash_if_zero=True)}")
    if not is_sms:
        lines.append(f"Rev/M: {fmt(rev_per_m, prefix='$', dash_if_zero=True)}")

    # Swatch orders (ID swatch canvases) — GA4 generate_lead_swatch, last-click.
    if swatch:
        sw_wk = round((swatch.get("swatches_12w") or 0) / weeks)
        lines.append(f"Swatch Orders/wk: {fmt(sw_wk, dash_if_zero=True)}")

    # SMS sub-section (canvases that also send SMS within the same canvas).
    if sms:
        sms_sends_wk = round((sms.get("sms_sends_12w") or 0) / weeks)
        sms_sess = sms.get("sms_sessions_12w")
        sms_rev  = sms.get("sms_revenue_12w")
        lines.append("── SMS ──")
        lines.append(f"Sends/wk: {fmt(sms_sends_wk, dash_if_zero=True)}")
        lines.append(
            "Sessions/wk: " + (fmt(round(sms_sess / weeks), dash_if_zero=True)
                               if sms_sess is not None else "—")
        )
        lines.append(
            "Rev/wk: " + (fmt(round(sms_rev / weeks), prefix='$', dash_if_zero=True)
                          if sms_rev is not None else "—")
        )

    return "\n".join(lines)


# ── Figma update ──────────────────────────────────────────────────────────────

def update_figma_node(figma_client, file_key: str, node_name: str,
                      new_text: str, dry_run: bool = False) -> bool:
    """Find a node by name and update its characters via the Figma Plugin API."""
    js = f"""
const page = figma.currentPage;
function findByName(name) {{
  for (const node of page.children) {{
    if (node.name === name && node.type === 'TEXT') return node;
  }}
  return null;
}}
const node = findByName({repr(node_name)});
if (!node) return 'NOT_FOUND';
node.characters = {repr(new_text)};
return 'OK';
"""
    if dry_run:
        print(f"  [dry-run] would update '{node_name}'")
        return True

    result = figma_client.use_figma(file_key=file_key, code=js,
                                     description=f"Update {node_name}")
    return result == "OK"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", choices=["bur", "id", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Import here to avoid circular imports at module load time
    from scripts.snowflake_client import get_snowflake_client

    # We can't easily call the Figma MCP from a script — this script is designed
    # to be invoked BY a Claude Code agent which has Figma MCP access.
    # When run directly it prints the update payloads for the agent to apply.

    brands = ["bur", "id"] if args.board == "all" else [args.board]
    today = datetime.date.today().isoformat()

    print(f"\n📊 Lifecycle FigJam Stats Update — {today}")
    print(f"   Rolling 12-week weekly averages\n")

    all_updates = {}  # node_name → new_text, grouped by board

    for brand in brands:
        cfg = BRAND_CONFIG[brand]
        board_key = BOARDS[brand]
        print(f"── {brand.upper()} ─────────────────────────────────────")

        # Use the Snowflake Havenly analytics connection
        client = get_snowflake_client(schema=cfg["schema"], database=cfg["db"])

        slugs = [k.split("::")[1] for k in CANVAS_IDS if k.startswith(f"{brand}::")]

        for slug in slugs:
            node_name = f"lifecycle-stats::{brand}::{slug}"
            print(f"  {slug}...")

            braze  = get_braze_stats(client, brand, slug)
            ga4    = get_ga4_stats(client, brand, slug)
            sms    = get_sms_stats(client, brand, slug) or None
            swatch = get_swatch_stats(client, brand, slug) or None
            text   = build_stats_text(brand, slug, braze, ga4,
                                      sms=sms, swatch=swatch)

            print(f"    {text.split(chr(10))[0]}")  # show first line
            all_updates.setdefault(board_key, {})[node_name] = text

    # Emit JSON payloads for the Figma-updating agent (see the runbook in
    # docs/lifecycle-figjam-stats-update.md). ensure_ascii=False keeps the
    # em-dashes and box-drawing chars readable. The calling Claude agent finds
    # each TEXT node by name and applies the new characters via the Figma MCP.
    print("\n===PAYLOADS_JSON===")
    print(json.dumps({"boards": BOARDS, "updates": all_updates},
                     indent=2, ensure_ascii=False))
    print("\n✅ Queries complete. Payloads ready for Figma update.")
    return all_updates


if __name__ == "__main__":
    main()
