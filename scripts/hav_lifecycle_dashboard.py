"""Havenly Lifecycle Performance Dashboard
Run: streamlit run scripts/hav_lifecycle_dashboard.py --server.port 8504
"""
import os
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Shared utilities from base ────────────────────────────────────────────────
import lifecycle_dashboard_base as _base
from lifecycle_dashboard_base import (
    Period, get_period, ly_for, trend_periods,
    money, pct, num, delta_pct,
    make_row, render_metric_grid, trend_chart,
    _df, _norm, _load_credentials, _prepare_detail_df,
    _canvas_ty_ly_chart,
    render_data_issue_banners,
    BRAZE_DB, BRAZE_SCHEMA,
)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_load_credentials()

from scripts.snowflake_client import SnowflakeClient

# ── HAV constants ─────────────────────────────────────────────────────────────

HAV_APP_GROUP_ID = "664223fb71bcf3005760dfc2"
HAV_GA4_TABLE    = "AIRBYTE_DATABASE.LANDING_HAVENLY_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"
ACCENT           = "#4a7c8e"   # Havenly teal
MUTED            = "#adb5bd"
BRAND_NAME       = "Havenly"

MODES = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# Canvas group rules: keyword list → friendly label for the dropdown.
# Keyword matching is case-insensitive, applied to the raw canvas name (Oct 2025+)
# OR — when the canvas name is unavailable — to the raw canvas step / UTM_CAMPAIGN name.
# The latter matters for LY revenue: pre-~June-2025 triggered sends use an older step-name
# format (e.g. TRG_2024_D_HAV_CON_Onboarding_T1_Email) that never carries a canvas name in
# the datashare, so each flow's keywords must also match its old step-name spelling. Without
# that, pre-June-2025 rooms fall into ungrouped buckets instead of the right flow line.
# First match wins, so keep more-specific rules ahead of broader ones.
HAV_CANVAS_GROUP_RULES: list[tuple[list[str], str]] = [
    (["new_messages", "new messages"],              "New Messages Notification"),
    # "onboarding" catches the old Welcome step names (…_Onboarding_…_Email); the only
    # canvas containing "onboarding" is "Welcome Stream / Onboarding Series".
    (["welcome", "onboarding"],                      "Welcome Series"),
    (["cart", "abandon_cart"],                       "Cart Abandonment"),
    (["browse", "abandon_browse"],                   "Browse Abandonment"),
    (["post_purchase", "post purchase"],             "Post-Purchase"),
    (["winback", "win_back", "re_engage", "reengag"], "Win-back / Re-engage"),
    # New canvas name → "Design Fee Abandon"; old step name → …_Design_Fee_Abandon_…_Email.
    (["design_fee_abandon", "design fee abandon"],   "Design Fee Abandon"),
    # New canvas name → "Shopping Prompts"; old step name → …_Shopping_Prompt_…_Email.
    # "finished_design" is the legacy alias for shopping-prompt steps (see the
    # _Finished_Design_ → _Shopping_Prompt_ remap in fetch_trg_detail_hav).
    (["shopping_prompt", "shopping prompt", "finished_design"], "Shopping Prompts"),
    # New canvas name → "Room Profile Complete"; old step name → …_Complete_Profile_…_Email.
    # Deliberately excludes bare "profile complete" so "HIP Profile Complete Series" stays
    # its own group.
    (["complete_profile", "complete profile", "room profile complete"], "Room Profile Complete"),
]

# ── Historical campaign name classification helpers ───────────────────────────

# Specific marketing campaign names that predate the P_/SEG_ prefix convention.
_HAV_OLD_BB_NAMES: tuple[str, ...] = (
    "Havenly Giveaway",
    "Meet the O&O Brands",
    "Meet the O&O Brands v1",
    "1/5/24: Havenly Home Makeover",
    "7/23: $50 off Havenly Code",
    "Studio 6 Beta Invite",
    "Studio 6 Follow Up 3D Room Generated",
    "December 2024 Rug Research Invite",
)

_BB_OLD_IN_SQL = ", ".join(f"'{n}'" for n in _HAV_OLD_BB_NAMES)


def _bb_conds_inner(col: str) -> str:
    """All B&B conditions (inner, no wrapping parens) for a given column name."""
    return (
        f"{col} LIKE 'P!_%' ESCAPE '!'"
        f" OR {col} LIKE 'SEG!_%' ESCAPE '!'"
        f" OR {col} LIKE 'Havenly Announcement:%'"
        f" OR {col} LIKE 'Havenly Reminder:%'"
        f" OR {col} LIKE 'AI UXR Segment%'"
        f" OR {col} LIKE 'Prototype UXR Segment%'"
        f" OR {col} IN ({_BB_OLD_IN_SQL})"
    )


def _bb_conds(col: str) -> str:
    """All B&B conditions wrapped in parens for a given column name."""
    return f"({_bb_conds_inner(col)})"


# Specific transactional campaign names not caught by '%Transactional Email' or '%System Email%'.
_HAV_OLD_TXNL_NAMES: tuple[str, ...] = (
    "Order Cancellation Confirmation",
    "Order ETA Email",
    "Order Quote Cancellation Confirmation Email",
    "Order Quote Request Received Email",
    "Prompt to Approve Order Quote Email",
    "Package Change Full to Mini Email",
    "Item Return Cancellation Request Received",
    "Card Declined Email",
    "Shopping List Updated",
    "Automated Email Order",
    "Automated Email Order Batch",
    "Cart Created from Board Quote",
    "Estimated Project Start Date Email",
    "Extension Request Approved (Designers)",
    "Extension Request Denied (Designers)",
    "Auto Extension Request Approved (Designers)",
    "Rooms Past Due Email (Designers)",
    "NPS Survey",
    "Send HIP NPS Survey",
    "Send In Home Meeting NPS Survey",
    "Send NPS Survey",
    "Send Zoom NPS Survey",
    "Email Alias for all users",
    "Merge new email alias only users",
    "Set New Users Email Alias webhook",
)

_TXNL_IN_SQL = ", ".join(f"'{n}'" for n in _HAV_OLD_TXNL_NAMES)

# ── Snowflake clients ─────────────────────────────────────────────────────────

def _braze():
    return SnowflakeClient(schema=BRAZE_SCHEMA, database=BRAZE_DB)

def _prod():
    return SnowflakeClient(schema="ANALYTICS", database="PROD")

def _ga4():
    return SnowflakeClient(schema="LANDING_HAVENLY_GA4", database="AIRBYTE_DATABASE")


# ── Audience / program helpers ────────────────────────────────────────────────

def _audience_sql(col: str, audience: Optional[str]) -> str:
    """Return a WHERE fragment filtering by PC / CONV / None (= both).
    Uses ! as ESCAPE character to avoid backslash-in-SQL-string issues.
    """
    if audience == "CONV":
        return f"AND {col} LIKE '%!_CONV!_%' ESCAPE '!'"
    if audience == "PC":
        return f"AND ({col} LIKE '%!_PC!_%' ESCAPE '!' OR {col} NOT LIKE '%!_CONV!_%' ESCAPE '!')"
    return ""  # All — no filter


def _audience_label(audience: Optional[str]) -> str:
    return {"PC": "Pre-Converted", "CONV": "Converted"}.get(audience or "", "All")


# ── Changelog name recovery ───────────────────────────────────────────────────
# The CAMPAIGN_NAME / CANVAS_NAME / CANVAS_STEP_NAME text columns are blank in the
# datashare before Oct 2025, but the CAMPAIGN_API_ID / CANVAS_API_ID columns are
# populated on 100% of rows. The changelog views map API_ID → latest NAME (deduped —
# one row per rename/save), so joining recovers the campaign name (with its P_/OT_
# prefix and _PC_/_CONV_ audience marker) and the canvas/flow name for historical
# sends. This lets program/audience filtering work for LY periods before Oct 2025.
#
# Add _name_joins(alias) to a query's FROM (aliases the changelog subqueries cc/cv),
# then use _eff_campaign(alias)/_eff_canvas(alias) in place of the raw name columns.

def _cc_subq() -> str:
    return (f"(SELECT API_ID, NAME "
            f"FROM {BRAZE_DB}.{BRAZE_SCHEMA}.CHANGELOGS_CAMPAIGN_SHARED "
            f"WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}' "
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1)")

def _cv_subq() -> str:
    return (f"(SELECT API_ID, NAME "
            f"FROM {BRAZE_DB}.{BRAZE_SCHEMA}.CHANGELOGS_CANVAS_SHARED "
            f"WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}' "
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1)")

def _name_joins(alias: str) -> str:
    """LEFT JOINs (1:1, deduped) recovering campaign+canvas names for event view `alias`."""
    return (f" LEFT JOIN {_cc_subq()} cc ON cc.API_ID = {alias}.CAMPAIGN_API_ID"
            f" LEFT JOIN {_cv_subq()} cv ON cv.API_ID = {alias}.CANVAS_API_ID ")

def _eff_campaign(alias: str) -> str:
    """Changelog-resolved campaign name for event view `alias` (batch sends)."""
    return f"COALESCE(NULLIF({alias}.CAMPAIGN_NAME,''), cc.NAME)"

def _eff_canvas(alias: str) -> str:
    """Changelog-resolved canvas / flow name for event view `alias` (triggered sends)."""
    return f"COALESCE(NULLIF({alias}.CANVAS_NAME,''), cv.NAME)"

def _eff_aud_name(alias: str) -> str:
    """Name carrying the _PC_/_CONV_ audience marker: step name if present (canvas sends),
    else the resolved campaign name (batch sends)."""
    return f"COALESCE(NULLIF({alias}.CANVAS_STEP_NAME,''), {_eff_campaign(alias)})"

def _trg_cond(alias: str) -> str:
    """Triggered identifier: a canvas send (CANVAS_ID present) OR a campaign named TRG_.
    Pre-Oct step names are blank, so canvas presence — not the TRG_ step prefix — is the
    reliable signal. Post-Oct, 100% of canvas step names are TRG_-prefixed, so equivalent."""
    return (f"(({alias}.CANVAS_ID IS NOT NULL AND {alias}.CANVAS_ID != '')"
            f" OR {_eff_campaign(alias)} LIKE 'TRG!_%' ESCAPE '!')")

def _prog_click(alias: str, program: Optional[str]) -> str:
    """Program WHERE-fragment for a Braze click/send event alias, using changelog-resolved
    names and canvas presence for triggered — parallels the engagement fetchers. (The
    last-click revenue path keeps _program_filter, since the session model's UTM_CAMPAIGN
    already carries TRG_/P_ prefixes.)"""
    if program == "BB":
        return f"AND {_bb_conds(_eff_campaign(alias))}"
    if program == "TRG":
        return f"AND {_trg_cond(alias)}"
    return f"AND ({_bb_conds_inner(_eff_campaign(alias))} OR {_trg_cond(alias)})"


# ── Data fetchers — Braze email ───────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_email_engagement(start: date, end: date,
                           program: Optional[str] = None,
                           audience: Optional[str] = None) -> pd.DataFrame:
    """
    Braze email sends/opens/clicks for HAV.
    program: 'BB' | 'TRG' | None (all marketing)
    audience: 'PC' | 'CONV' | None (all)

    HAV note: triggered sends are canvas-based — the TRG_ prefix lives on CANVAS_STEP_NAME
    and B&B sends use CAMPAIGN_NAME with a P_ prefix. Both name columns are blank in the
    datashare before Oct 2025, so filters run on changelog-resolved names (_eff_campaign)
    and canvas presence (_trg_cond) rather than the raw columns.
    """
    a = "e"
    # Program filter — resolved campaign name for B&B; canvas presence (or TRG_ campaign) for triggered
    if program == "BB":
        prog_filter = f"AND {_bb_conds(_eff_campaign(a))}"
    elif program == "TRG":
        prog_filter = f"AND {_trg_cond(a)}"
    else:  # None = all marketing (B&B or triggered)
        prog_filter = f"AND ({_bb_conds_inner(_eff_campaign(a))} OR {_trg_cond(a)})"

    aud_filter = _audience_sql(_eff_aud_name(a), audience)
    joins = _name_joins(a)

    q = f"""
    WITH sends AS (
        SELECT COUNT(DISTINCT e.ID)      AS sends,
               COUNT(DISTINCT e.USER_ID) AS unique_users
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED e
        {joins}
        WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
          {prog_filter} {aud_filter}
    ),
    opens AS (
        SELECT COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {prog_filter} {aud_filter}
        )
    ),
    clicks AS (
        SELECT COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {prog_filter} {aud_filter}
        )
    )
    SELECT s.sends, s.unique_users,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens             END AS cto
    FROM sends s, opens o, clicks c
    """
    return _norm(_df(_braze().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_email_all_crm(start: date, end: date) -> pd.DataFrame:
    """All Braze email sends (marketing + transactional + other) for At a Glance."""
    q = f"""
    WITH sends AS (
        SELECT COUNT(DISTINCT ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
    ),
    opens AS (
        SELECT COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
        )
    ),
    clicks AS (
        SELECT COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
        )
    )
    SELECT s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr
    FROM sends s, opens o, clicks c
    """
    return _norm(_df(_braze().execute_query(q)))


# ── Data fetchers — Push ──────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_push_engagement(start: date, end: date) -> pd.DataFrame:
    """Braze push notification sends + opens (taps)."""
    q = f"""
    WITH sends AS (
        SELECT COUNT(DISTINCT ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_PUSHNOTIFICATION_SEND_SHARED
        WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
    ),
    opens AS (
        SELECT COUNT(DISTINCT ID) AS taps
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_PUSHNOTIFICATION_OPEN_SHARED
        WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
    )
    SELECT s.sends,
           COALESCE(o.taps, 0) AS taps,
           CASE WHEN s.sends > 0 THEN COALESCE(o.taps, 0)::FLOAT / s.sends END AS tap_rate
    FROM sends s, opens o
    """
    try:
        return _norm(_df(_braze().execute_query(q)))
    except Exception:
        return pd.DataFrame()


# ── Data fetchers — Revenue (Havenly session model) ───────────────────────────

def _program_filter(col: str, program: Optional[str]) -> str:
    """WHERE fragment filtering by program type. Uses ! as ESCAPE character."""
    if program == "BB":
        return f"AND {_bb_conds(col)}"
    if program == "TRG":
        return f"AND {col} LIKE 'TRG!_%' ESCAPE '!'"
    # None = all marketing (B&B or TRG)
    return f"AND ({_bb_conds_inner(col)} OR {col} LIKE 'TRG!_%' ESCAPE '!')"


def _merch_revenue_last_click(start: date, end: date,
                               audience: Optional[str],
                               program: Optional[str] = None,
                               filter_program: bool = True) -> dict:
    """Last-click merch revenue via MERCH_ORDER_SESSIONS → SESSIONS → ORDER_SUMMARY."""
    aud_filter  = _audience_sql("s.UTM_CAMPAIGN", audience)
    prog_filter = _program_filter("s.UTM_CAMPAIGN", program) if filter_program else ""
    q = f"""
    SELECT
        COUNT(DISTINCT mos.ORDER_ID)   AS orders,
        SUM(os.NET_ORDER_REVENUE)      AS merch_revenue
    FROM PROD.ANALYTICS.MERCH_ORDER_SESSIONS mos
    JOIN PROD.ANALYTICS.SESSIONS      s  ON s.SESSION_ID  = mos.SESSION_ID
    JOIN PROD.ANALYTICS.ORDER_SUMMARY os ON os.ORDER_ID   = mos.ORDER_ID
    WHERE mos.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
      AND s.UTM_SOURCE = 'braze_havenly'
      {prog_filter}
      {aud_filter}
      AND mos.ORDER_CREATED::DATE BETWEEN '{start}' AND '{end}'
    """
    rows = _prod().execute_query(q)
    if rows and rows[0]:
        r = {k.lower(): (v or 0) for k, v in rows[0].items()}
        return r
    return {"orders": 0, "merch_revenue": 0}


def _design_fee_last_click(start: date, end: date,
                            audience: Optional[str],
                            program: Optional[str] = None,
                            filter_program: bool = True) -> dict:
    """Last-click design fee revenue + rooms sold."""
    aud_filter  = _audience_sql("s.UTM_CAMPAIGN", audience)
    prog_filter = _program_filter("s.UTM_CAMPAIGN", program) if filter_program else ""
    q = f"""
    SELECT
        COUNT(DISTINCT dfs.ROOM_ID)  AS rooms,
        SUM(df.NET_REVENUE)          AS design_fee_revenue
    FROM PROD.ANALYTICS.DESIGN_FEE_SESSIONS dfs
    JOIN PROD.ANALYTICS.SESSIONS            s  ON s.SESSION_ID = dfs.SESSION_ID
    JOIN PROD.ANALYTICS.DESIGN_FEES         df ON df.ROOM_ID   = dfs.ROOM_ID
    WHERE dfs.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
      AND s.UTM_SOURCE = 'braze_havenly'
      {prog_filter}
      {aud_filter}
      AND df.IS_PAID = 1
      AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN '{start}' AND '{end}'
    """
    rows = _prod().execute_query(q)
    if rows and rows[0]:
        r = {k.lower(): (v or 0) for k, v in rows[0].items()}
        return r
    return {"rooms": 0, "design_fee_revenue": 0}


def _merch_revenue_3day(start: date, end: date,
                        audience: Optional[str],
                        program: Optional[str] = None,
                        filter_program: bool = True) -> dict:
    """3-day post-click merch revenue: click → order within 3 days, same user."""
    aud_filter  = _audience_sql(_eff_aud_name("c"), audience)
    prog_filter = _prog_click("c", program) if filter_program else ""
    q = f"""
    SELECT
        COUNT(DISTINCT os.ORDER_ID) AS orders,
        SUM(os.NET_ORDER_REVENUE)   AS merch_revenue
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
    JOIN PROD.ANALYTICS.ORDER_SUMMARY os
      ON os.USER_ID = TRY_TO_NUMBER(c.EXTERNAL_USER_ID)
     AND os.ORDER_CREATED::DATE BETWEEN TO_DATE(TO_TIMESTAMP(c.TIME)) AND DATEADD('day', 3, TO_DATE(TO_TIMESTAMP(c.TIME)))
    {_name_joins("c")}
    WHERE c.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
      AND COALESCE(c.IS_SUSPECTED_BOT_CLICK, 'false') != 'true'
      {prog_filter}
      {aud_filter}
      AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
      AND os.ORDER_CREATED::DATE BETWEEN '{start}' AND DATEADD('day', 3, '{end}'::DATE)
    """
    rows = _prod().execute_query(q)
    if rows and rows[0]:
        r = {k.lower(): (v or 0) for k, v in rows[0].items()}
        return r
    return {"orders": 0, "merch_revenue": 0}


def _design_fee_3day(start: date, end: date,
                     audience: Optional[str],
                     program: Optional[str] = None,
                     filter_program: bool = True) -> dict:
    """3-day post-click design fee revenue + rooms."""
    aud_filter  = _audience_sql(_eff_aud_name("c"), audience)
    prog_filter = _prog_click("c", program) if filter_program else ""
    q = f"""
    SELECT
        COUNT(DISTINCT df.ROOM_ID) AS rooms,
        SUM(df.NET_REVENUE)        AS design_fee_revenue
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
    JOIN PROD.ANALYTICS.DESIGN_FEES df
      ON df.USER_ID = TRY_TO_NUMBER(c.EXTERNAL_USER_ID)
     AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN TO_DATE(TO_TIMESTAMP(c.TIME)) AND DATEADD('day', 3, TO_DATE(TO_TIMESTAMP(c.TIME)))
    {_name_joins("c")}
    WHERE c.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
      AND COALESCE(c.IS_SUSPECTED_BOT_CLICK, 'false') != 'true'
      {prog_filter}
      {aud_filter}
      AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
      AND df.IS_PAID = 1
      AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN '{start}' AND DATEADD('day', 3, '{end}'::DATE)
    """
    rows = _prod().execute_query(q)
    if rows and rows[0]:
        r = {k.lower(): (v or 0) for k, v in rows[0].items()}
        return r
    return {"rooms": 0, "design_fee_revenue": 0}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_revenue(start: date, end: date,
                  audience: Optional[str],
                  attribution: str,
                  program: Optional[str] = None,
                  filter_program: bool = True) -> dict:
    """Merch + design fee revenue. attribution: 'last_click' | '3day'. program: 'BB' | 'TRG' | None.
    filter_program=False skips UTM_CAMPAIGN prefix filter (used for LY fallback before Oct 2025)."""
    if attribution == "3day":
        m = _merch_revenue_3day(start, end, audience, program, filter_program=filter_program)
        d = _design_fee_3day(start, end, audience, program, filter_program=filter_program)
    else:
        m = _merch_revenue_last_click(start, end, audience, program, filter_program=filter_program)
        d = _design_fee_last_click(start, end, audience, program, filter_program=filter_program)
    return {**m, **d}


# ── Data fetchers — Everything Else ──────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_other_engagement(start: date, end: date) -> pd.DataFrame:
    """Sends/opens/clicks for non-marketing campaigns (OT_, and everything else)."""
    a = "e"
    eff = _eff_campaign(a)
    joins = _name_joins(a)
    cat_case = (
        f"CASE"
        f" WHEN {eff} LIKE 'OT!_%' ESCAPE '!'     THEN 'Transactional'"
        f" WHEN {eff} LIKE '%Transactional Email' THEN 'Transactional'"
        f" WHEN {eff} LIKE '%System Email%'        THEN 'Transactional'"
        f" WHEN {eff} IN ({_TXNL_IN_SQL})          THEN 'Transactional'"
        f" ELSE 'Other' END"
    )
    excl = f"AND NOT {_bb_conds(eff)} AND NOT {_trg_cond(a)}"
    q = f"""
    WITH sends AS (
        SELECT
            {cat_case} AS category,
            COUNT(DISTINCT e.ID)      AS sends,
            COUNT(DISTINCT e.USER_ID) AS unique_users
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED e
        {joins}
        WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
          {excl}
        GROUP BY 1
    ),
    opens AS (
        SELECT category, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT
                {cat_case} AS category,
                e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {excl}
        )
        GROUP BY 1
    ),
    clicks AS (
        SELECT category, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT
                {cat_case} AS category,
                e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {excl}
        )
        GROUP BY 1
    )
    SELECT s.category, s.sends, s.unique_users,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr
    FROM sends s
    LEFT JOIN opens  o ON s.category = o.category
    LEFT JOIN clicks c ON s.category = c.category
    ORDER BY s.sends DESC
    """
    return _norm(_df(_braze().execute_query(q)))


# ── Campaign detail fetchers ──────────────────────────────────────────────────

_HAV_BB_DETAIL_MAP = [
    ("CAMPAIGN_NAME",      "Campaign",   "text"),
    ("SENDS",              "Sends",      "int"),
    ("UNIQUE_OPENS",       "Opens",      "int"),
    ("OPEN_RATE",          "Open Rate",  "pct"),
    ("UNIQUE_CLICKS",      "Clicks",     "int"),
    ("CTR",                "CTR",        "pct"),
    ("CTO",                "CTO",        "pct"),
    ("GA4_SESSIONS",       "Sessions",   "int"),
    ("ORDERS",             "Orders",     "int"),
    ("ROOMS",              "Rooms",      "int"),
    ("MERCH_REVENUE",      "Merch Rev",  "money"),
    ("DESIGN_FEE_REVENUE", "DF Rev",     "money"),
]

# Keep legacy name for anything still referencing it
_HAV_DETAIL_MAP = _HAV_BB_DETAIL_MAP


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_bb_detail_hav(start: date, end: date, audience: Optional[str]) -> pd.DataFrame:
    """Per-campaign B&B (P_) detail — sends/opens/clicks."""
    a = "e"
    eff = _eff_campaign(a)
    joins = _name_joins(a)
    prog_filter = f"AND {_bb_conds(eff)}"
    aud_filter  = _audience_sql(eff, audience)
    q = f"""
    WITH sends AS (
        SELECT {eff} AS CAMPAIGN_NAME, COUNT(DISTINCT e.ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED e
        {joins}
        WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
          {prog_filter} {aud_filter}
        GROUP BY 1
    ),
    opens AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT {eff} AS CAMPAIGN_NAME, e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {prog_filter} {aud_filter}
        )
        GROUP BY 1
    ),
    clicks AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT {eff} AS CAMPAIGN_NAME, e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {prog_filter} {aud_filter}
        )
        GROUP BY 1
    )
    SELECT s.CAMPAIGN_NAME, s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens             END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.CAMPAIGN_NAME = o.CAMPAIGN_NAME
    LEFT JOIN clicks c ON s.CAMPAIGN_NAME = c.CAMPAIGN_NAME
    ORDER BY s.sends DESC
    """
    return _norm(_df(_braze().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_trg_detail_hav(start: date, end: date, audience: Optional[str]) -> pd.DataFrame:
    """Per-step Triggered detail, keyed by (CANVAS_NAME, CANVAS_STEP_NAME).

    Returns CANVAS_NAME (human-readable flow name) and CANVAS_STEP_NAME (TRG_ step name)
    as separate columns so the renderer can group steps under each canvas header.
    For the rare campaign-based TRG_ send, CANVAS_NAME is NULL and CANVAS_STEP_NAME
    holds the campaign name.
    """
    a = "e"
    joins = _name_joins(a)
    trg = _trg_cond(a)
    aud_filter = _audience_sql(_eff_aud_name(a), audience)
    # canvas_name recovered from the changelog (blank column pre-Oct); canvas_step_name is
    # not changelog-recoverable, so pre-Oct steps fall back to the resolved campaign name
    # (populated only for campaign-based TRG_ sends).
    cn_expr   = f"NULLIF({_eff_canvas(a)}, '')"
    step_expr = (f"REPLACE(COALESCE(NULLIF({a}.CANVAS_STEP_NAME, ''), {_eff_campaign(a)}),"
                 f" '_Finished_Design_', '_Shopping_Prompt_')")
    q = f"""
    WITH sends AS (
        SELECT
            {cn_expr}   AS canvas_name,
            {step_expr} AS canvas_step_name,
            COUNT(DISTINCT e.ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED e
        {joins}
        WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
          AND {trg}
          {aud_filter}
        GROUP BY 1, 2
    ),
    opens AS (
        SELECT canvas_name, canvas_step_name, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT
                {cn_expr}   AS canvas_name,
                {step_expr} AS canvas_step_name,
                e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              AND {trg}
              {aud_filter}
        )
        GROUP BY 1, 2
    ),
    clicks AS (
        SELECT canvas_name, canvas_step_name, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT
                {cn_expr}   AS canvas_name,
                {step_expr} AS canvas_step_name,
                e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              AND {trg}
              {aud_filter}
        )
        GROUP BY 1, 2
    )
    SELECT s.canvas_name    AS CANVAS_NAME,
           s.canvas_step_name AS CANVAS_STEP_NAME,
           s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens             END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.canvas_name IS NOT DISTINCT FROM o.canvas_name
                      AND s.canvas_step_name = o.canvas_step_name
    LEFT JOIN clicks c ON s.canvas_name IS NOT DISTINCT FROM c.canvas_name
                      AND s.canvas_step_name = c.canvas_step_name
    ORDER BY s.sends DESC, s.canvas_step_name
    """
    return _norm(_df(_braze().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_other_detail_hav(start: date, end: date) -> pd.DataFrame:
    """Per-campaign detail for non-marketing (OT_ + other) sends."""
    a = "e"
    eff = _eff_campaign(a)
    joins = _name_joins(a)
    excl = f"AND NOT {_bb_conds(eff)} AND NOT {_trg_cond(a)}"
    q = f"""
    WITH sends AS (
        SELECT {eff} AS CAMPAIGN_NAME, COUNT(DISTINCT e.ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED e
        {joins}
        WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
          {excl}
        GROUP BY 1
    ),
    opens AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT {eff} AS CAMPAIGN_NAME, e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {excl}
        )
        GROUP BY 1
    ),
    clicks AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT {eff} AS CAMPAIGN_NAME, e.DISPATCH_ID, e.USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
            {joins}
            WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
              {excl}
        )
        GROUP BY 1
    )
    SELECT s.CAMPAIGN_NAME, s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends  END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends  END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens             END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.CAMPAIGN_NAME = o.CAMPAIGN_NAME
    LEFT JOIN clicks c ON s.CAMPAIGN_NAME = c.CAMPAIGN_NAME
    ORDER BY s.sends DESC
    """
    return _norm(_df(_braze().execute_query(q)))


_HAV_TRG_STEP_MAP = [
    ("CANVAS_STEP_NAME",   "Step",       "text"),
    ("SENDS",              "Sends",      "int"),
    ("UNIQUE_OPENS",       "Opens",      "int"),
    ("OPEN_RATE",          "Open Rate",  "pct"),
    ("UNIQUE_CLICKS",      "Clicks",     "int"),
    ("CTR",                "CTR",        "pct"),
    ("CTO",                "CTO",        "pct"),
    ("GA4_SESSIONS",       "Sessions",   "int"),
    ("ORDERS",             "Orders",     "int"),
    ("ROOMS",              "Rooms",      "int"),
    ("MERCH_REVENUE",      "Merch Rev",  "money"),
    ("DESIGN_FEE_REVENUE", "DF Rev",     "money"),
]


# ── Per-campaign / per-step GA4 sessions detail ──────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_hav_ga4_detail(start: date, end: date) -> pd.DataFrame:
    """GA4 sessions (and orders) per campaign name from the HAV GA4 table.
    SESSIONCAMPAIGNNAME matches both CAMPAIGN_NAME (B&B) and CANVAS_STEP_NAME (triggered).
    """
    q = f"""
    SELECT SESSIONCAMPAIGNNAME          AS name,
           SUM(SESSIONS)                AS ga4_sessions,
           SUM(ECOMMERCEPURCHASES)      AS ga4_orders
    FROM {HAV_GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP = 'Email'
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND SESSIONCAMPAIGNNAME NOT IN ('(not set)', '(referral)')
    GROUP BY 1
    """
    try:
        return _norm(_df(_ga4().execute_query(q)))
    except Exception:
        return pd.DataFrame()


# ── Per-campaign / per-step revenue detail ────────────────────────────────────

def _rev_detail_lc_sql(name_col: str, prog_filter_sql: str,
                       aud_filter_sql: str, start: date, end: date) -> str:
    """Last-click revenue SQL grouped by {name_col} (UTM_CAMPAIGN in SESSIONS)."""
    return f"""
    WITH merch AS (
        SELECT s.UTM_CAMPAIGN AS name,
               COUNT(DISTINCT mos.ORDER_ID) AS orders,
               SUM(os.NET_ORDER_REVENUE)    AS merch_revenue
        FROM PROD.ANALYTICS.MERCH_ORDER_SESSIONS mos
        JOIN PROD.ANALYTICS.SESSIONS      s  ON s.SESSION_ID  = mos.SESSION_ID
        JOIN PROD.ANALYTICS.ORDER_SUMMARY os ON os.ORDER_ID   = mos.ORDER_ID
        WHERE mos.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
          AND s.UTM_SOURCE = 'braze_havenly'
          {prog_filter_sql}
          {aud_filter_sql}
          AND mos.ORDER_CREATED::DATE BETWEEN '{start}' AND '{end}'
        GROUP BY 1
    ),
    design AS (
        SELECT s.UTM_CAMPAIGN AS name,
               COUNT(DISTINCT dfs.ROOM_ID) AS rooms,
               SUM(df.NET_REVENUE)         AS design_fee_revenue
        FROM PROD.ANALYTICS.DESIGN_FEE_SESSIONS dfs
        JOIN PROD.ANALYTICS.SESSIONS   s  ON s.SESSION_ID = dfs.SESSION_ID
        JOIN PROD.ANALYTICS.DESIGN_FEES df ON df.ROOM_ID   = dfs.ROOM_ID
        WHERE dfs.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
          AND s.UTM_SOURCE = 'braze_havenly'
          {prog_filter_sql}
          {aud_filter_sql}
          AND df.IS_PAID = 1
          AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN '{start}' AND '{end}'
        GROUP BY 1
    ),
    names AS (SELECT name FROM merch UNION SELECT name FROM design)
    SELECT n.name                             AS {name_col},
           COALESCE(m.orders,             0)  AS ORDERS,
           COALESCE(m.merch_revenue,      0)  AS MERCH_REVENUE,
           COALESCE(d.rooms,              0)  AS ROOMS,
           COALESCE(d.design_fee_revenue, 0)  AS DESIGN_FEE_REVENUE
    FROM names n
    LEFT JOIN merch  m ON m.name = n.name
    LEFT JOIN design d ON d.name = n.name
    """


def _rev_detail_3d_sql(name_col: str, prog_filter_sql: str,
                       aud_filter_sql: str, start: date, end: date) -> str:
    """3-day post-click revenue SQL from Braze click events, grouped by {name_col}."""
    name_expr = f"COALESCE(NULLIF(c.CANVAS_STEP_NAME,''), {_eff_campaign('c')})"
    return f"""
    WITH merch AS (
        SELECT {name_expr} AS name,
               COUNT(DISTINCT os.ORDER_ID) AS orders,
               SUM(os.NET_ORDER_REVENUE)   AS merch_revenue
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
        JOIN PROD.ANALYTICS.ORDER_SUMMARY os
          ON os.USER_ID = TRY_TO_NUMBER(c.EXTERNAL_USER_ID)
         AND os.ORDER_CREATED::DATE BETWEEN TO_DATE(TO_TIMESTAMP(c.TIME))
                                        AND DATEADD('day', 3, TO_DATE(TO_TIMESTAMP(c.TIME)))
        {_name_joins("c")}
        WHERE c.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND COALESCE(c.IS_SUSPECTED_BOT_CLICK, 'false') != 'true'
          {prog_filter_sql}
          {aud_filter_sql}
          AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
          AND os.ORDER_CREATED::DATE BETWEEN '{start}' AND DATEADD('day', 3, '{end}'::DATE)
        GROUP BY 1
    ),
    design AS (
        SELECT {name_expr} AS name,
               COUNT(DISTINCT df.ROOM_ID) AS rooms,
               SUM(df.NET_REVENUE)        AS design_fee_revenue
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
        JOIN PROD.ANALYTICS.DESIGN_FEES df
          ON df.USER_ID = TRY_TO_NUMBER(c.EXTERNAL_USER_ID)
         AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN TO_DATE(TO_TIMESTAMP(c.TIME))
                                              AND DATEADD('day', 3, TO_DATE(TO_TIMESTAMP(c.TIME)))
        {_name_joins("c")}
        WHERE c.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND COALESCE(c.IS_SUSPECTED_BOT_CLICK, 'false') != 'true'
          {prog_filter_sql}
          {aud_filter_sql}
          AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
          AND df.IS_PAID = 1
          AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN '{start}' AND DATEADD('day', 3, '{end}'::DATE)
        GROUP BY 1
    ),
    names AS (SELECT name FROM merch UNION SELECT name FROM design)
    SELECT n.name                             AS {name_col},
           COALESCE(m.orders,             0)  AS ORDERS,
           COALESCE(m.merch_revenue,      0)  AS MERCH_REVENUE,
           COALESCE(d.rooms,              0)  AS ROOMS,
           COALESCE(d.design_fee_revenue, 0)  AS DESIGN_FEE_REVENUE
    FROM names n
    LEFT JOIN merch  m ON m.name = n.name
    LEFT JOIN design d ON d.name = n.name
    """


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_bb_revenue_detail(start: date, end: date,
                             audience: Optional[str], attribution: str) -> pd.DataFrame:
    """Per-B&B-campaign revenue (merch + design fee). Keyed on CAMPAIGN_NAME."""
    aud_lc   = _audience_sql("s.UTM_CAMPAIGN", audience)
    aud_3d   = _audience_sql(_eff_aud_name("c"), audience)
    prog_lc  = f"AND {_bb_conds('s.UTM_CAMPAIGN')}"
    prog_3d  = _prog_click("c", "BB")
    if attribution == "last_click":
        q = _rev_detail_lc_sql("CAMPAIGN_NAME", prog_lc, aud_lc, start, end)
    else:
        q = _rev_detail_3d_sql("CAMPAIGN_NAME", prog_3d, aud_3d, start, end)
    try:
        return _norm(_df(_prod().execute_query(q)))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_trg_revenue_detail(start: date, end: date, attribution: str) -> pd.DataFrame:
    """Per-TRG-step revenue (merch + design fee). Keyed on CANVAS_STEP_NAME."""
    prog_lc = "AND s.UTM_CAMPAIGN LIKE 'TRG!_%' ESCAPE '!'"
    prog_3d = _prog_click("c", "TRG")
    if attribution == "last_click":
        q = _rev_detail_lc_sql("CANVAS_STEP_NAME", prog_lc, "", start, end)
    else:
        q = _rev_detail_3d_sql("CANVAS_STEP_NAME", prog_3d, "", start, end)
    try:
        return _norm(_df(_prod().execute_query(q)))
    except Exception:
        return pd.DataFrame()


def _hav_canvas_total_row(sub: pd.DataFrame) -> pd.DataFrame:
    """Aggregate totals row appended at bottom of each canvas group."""
    t_s = int(sub["SENDS"].sum())
    t_o = int(sub["UNIQUE_OPENS"].sum())
    t_c = int(sub["UNIQUE_CLICKS"].sum())
    row: dict = {
        "CANVAS_STEP_NAME": "— Canvas Total —",
        "SENDS":        t_s,
        "UNIQUE_OPENS": t_o,
        "UNIQUE_CLICKS": t_c,
        "OPEN_RATE": t_o / t_s if t_s else None,
        "CTR":       t_c / t_s if t_s else None,
        "CTO":       t_c / t_o if t_o else None,
    }
    for rev_col in ("GA4_SESSIONS", "ORDERS", "ROOMS", "MERCH_REVENUE", "DESIGN_FEE_REVENUE"):
        if rev_col in sub.columns:
            row[rev_col] = sub[rev_col].sum()
    return pd.DataFrame([row])


def _merge_ga4(df: pd.DataFrame, ga4_df: pd.DataFrame, join_col: str) -> pd.DataFrame:
    """Left-join GA4 sessions onto the detail df, if ga4_df is non-empty."""
    if ga4_df is None or ga4_df.empty or "NAME" not in ga4_df.columns:
        return df
    ga4_slim = ga4_df[["NAME", "GA4_SESSIONS"]].rename(columns={"NAME": join_col})
    return df.merge(ga4_slim, on=join_col, how="left")


def _render_detail_table(df: pd.DataFrame,
                         rev_df: Optional[pd.DataFrame] = None,
                         ga4_df: Optional[pd.DataFrame] = None):
    """Render a standard engagement detail table (B&B campaigns), optionally with revenue + sessions."""
    if df.empty:
        st.caption("No data for this period.")
        return
    df = _merge_ga4(df, ga4_df, "CAMPAIGN_NAME")
    if rev_df is not None and not rev_df.empty and "CAMPAIGN_NAME" in rev_df.columns:
        rev_cols = [c for c in ("ORDERS", "ROOMS", "MERCH_REVENUE", "DESIGN_FEE_REVENUE")
                    if c in rev_df.columns]
        df = df.merge(rev_df[["CAMPAIGN_NAME"] + rev_cols], on="CAMPAIGN_NAME", how="left")
    ddf, cfg = _prepare_detail_df(df, _HAV_BB_DETAIL_MAP)
    st.dataframe(ddf, hide_index=True, use_container_width=True, column_config=cfg)


def _render_trg_detail_table(df: pd.DataFrame,
                              rev_df: Optional[pd.DataFrame] = None,
                              ga4_df: Optional[pd.DataFrame] = None):
    """Render triggered detail grouped by canvas with steps and a total row under each."""
    if df.empty:
        st.caption("No data for this period.")
        return

    # Merge sessions and revenue onto step rows
    df = _merge_ga4(df, ga4_df, "CANVAS_STEP_NAME")
    if rev_df is not None and not rev_df.empty and "CANVAS_STEP_NAME" in rev_df.columns:
        rev_cols = [c for c in ("ORDERS", "ROOMS", "MERCH_REVENUE", "DESIGN_FEE_REVENUE")
                    if c in rev_df.columns]
        df = df.merge(rev_df[["CANVAS_STEP_NAME"] + rev_cols], on="CANVAS_STEP_NAME", how="left")

    # Canvas-based sends: group by CANVAS_NAME
    for canvas in sorted(df["CANVAS_NAME"].dropna().unique()):
        st.markdown(f"**{canvas}**")
        sub = df[df["CANVAS_NAME"] == canvas].copy()
        sub_with_total = pd.concat([sub, _hav_canvas_total_row(sub)], ignore_index=True)
        ddf, cfg = _prepare_detail_df(sub_with_total, _HAV_TRG_STEP_MAP)
        st.dataframe(ddf, hide_index=True, use_container_width=True, column_config=cfg)

    # Campaign-based TRG_ sends (rare — CANVAS_NAME is NULL)
    no_canvas = df[df["CANVAS_NAME"].isna()]
    if not no_canvas.empty:
        st.markdown("**Other Triggered (campaign-based)**")
        ddf, cfg = _prepare_detail_df(no_canvas, _HAV_TRG_STEP_MAP)
        st.dataframe(ddf, hide_index=True, use_container_width=True, column_config=cfg)


# ── Click reconciliation ──────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_click_reconciliation(start: date, end: date,
                               audience: Optional[str]) -> dict:
    """
    Compare real Braze clicks vs email-attributed sessions to estimate
    how many clicks resolved to Direct/iOS (app opens losing UTM).
    """
    # Changelog-resolved names so pre-Oct-2025 marketing clicks are recognized
    a = "e"
    joins = _name_joins(a)
    aud_filter = _audience_sql(_eff_aud_name(a), audience)
    mktg_filter = f"AND ({_bb_conds_inner(_eff_campaign(a))} OR {_trg_cond(a)})"

    # Real human clicks from Braze
    q_clicks = f"""
    SELECT COUNT(DISTINCT e.ID) AS real_clicks
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED e
    {joins}
    WHERE e.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
      AND COALESCE(e.IS_SUSPECTED_BOT_CLICK, 'false') != 'true'
      {mktg_filter}
      {aud_filter}
      AND TO_DATE(TO_TIMESTAMP(e.TIME)) BETWEEN '{start}' AND '{end}'
    """

    # Unsubscribes (to back out from clicks — these are real but not revenue-intent)
    q_unsubs = f"""
    SELECT COUNT(DISTINCT ID) AS unsubs
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED
    WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
      AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
    """

    # Email-attributed sessions from Havenly session model (last-click)
    q_sessions = f"""
    SELECT COUNT(DISTINCT mos.SESSION_ID) AS email_sessions
    FROM PROD.ANALYTICS.MERCH_ORDER_SESSIONS mos
    JOIN PROD.ANALYTICS.SESSIONS s ON s.SESSION_ID = mos.SESSION_ID
    WHERE mos.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
      AND s.UTM_SOURCE = 'braze_havenly'
      {_program_filter('s.UTM_CAMPAIGN', None)}
      {_audience_sql('s.UTM_CAMPAIGN', audience)}
      AND mos.ORDER_CREATED::DATE BETWEEN '{start}' AND '{end}'
    """

    try:
        r_clicks  = _braze().execute_query(q_clicks)
        r_unsubs  = _braze().execute_query(q_unsubs)
        r_sess    = _prod().execute_query(q_sessions)
        clicks    = int((r_clicks[0] or {}).get("REAL_CLICKS", 0))
        unsubs    = int((r_unsubs[0] or {}).get("UNSUBS", 0))
        sessions  = int((r_sess[0] or {}).get("EMAIL_SESSIONS", 0))
        intent_clicks = max(clicks - unsubs, 0)
        gap       = max(intent_clicks - sessions, 0)
        return {
            "raw_clicks":     clicks,
            "unsubs":         unsubs,
            "intent_clicks":  intent_clicks,
            "email_sessions": sessions,
            "gap":            gap,
            "gap_pct":        gap / intent_clicks if intent_clicks else None,
        }
    except Exception:
        return {}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _v(d: dict, key: float) -> Optional[float]:
    v = d.get(key)
    return float(v) if v is not None else None

def _e(df: pd.DataFrame, col: str) -> Optional[float]:
    return float(df.iloc[0][col]) if not df.empty and col in df.columns and df.iloc[0][col] is not None else None


def _metric(label, ty, ly, fmt, is_rate=False):
    if ty is None:
        st.metric(label, "—")
        return
    delta = None
    if ly:
        if is_rate:
            pp = (ty - ly) * 100
            delta = f"{'+' if pp >= 0 else ''}{pp:.1f}pp vs LY"
        else:
            d = delta_pct(ty, ly)
            delta = f"{d:+.1%} vs LY" if d is not None else None
    st.metric(label, fmt(ty), delta=delta)


# ── Canvas YoY — data fetchers ───────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_canvas_braze_weekly_hav(start: date, end: date) -> pd.DataFrame:
    """Weekly Braze sends/opens/clicks per canvas name for HAV (2-year window).
    Backfills NULL canvas names via CHANGELOGS_CANVAS_SHARED.
    """
    q = f"""
    WITH canvas_names AS (
        SELECT DISTINCT CANVAS_ID,
               FIRST_VALUE(NAME) OVER (
                   PARTITION BY CANVAS_ID ORDER BY TIME DESC
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
               ) AS canvas_name
        FROM (
            SELECT ID AS CANVAS_ID, NAME, TIME
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.CHANGELOGS_CANVAS_SHARED
            WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
        )
    ),
    sends AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(s.TIME)))::DATE AS week_start,
               COALESCE(s.CANVAS_NAME, cn.canvas_name)                 AS canvas_name,
               COUNT(DISTINCT s.ID)                                     AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
        LEFT JOIN canvas_names cn ON s.CANVAS_ID = cn.CANVAS_ID
        WHERE s.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND s.CANVAS_ID IS NOT NULL AND s.CANVAS_ID != ''
          AND COALESCE(s.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(s.TIME)) BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
    ),
    opens AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(o.TIME)))::DATE AS week_start,
               COALESCE(o.CANVAS_NAME, cn.canvas_name)                 AS canvas_name,
               COUNT(DISTINCT o.USER_ID)                               AS opens
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED o
        LEFT JOIN canvas_names cn ON o.CANVAS_ID = cn.CANVAS_ID
        WHERE o.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND o.CANVAS_ID IS NOT NULL AND o.CANVAS_ID != ''
          AND COALESCE(o.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(o.TIME)) BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
    ),
    clicks AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(c.TIME)))::DATE AS week_start,
               COALESCE(c.CANVAS_NAME, cn.canvas_name)                 AS canvas_name,
               COUNT(DISTINCT c.USER_ID)                               AS clicks
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
        LEFT JOIN canvas_names cn ON c.CANVAS_ID = cn.CANVAS_ID
        WHERE c.APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
          AND c.CANVAS_ID IS NOT NULL AND c.CANVAS_ID != ''
          AND COALESCE(c.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
    )
    SELECT s.week_start, s.canvas_name, s.sends,
           COALESCE(o.opens,  0) AS opens,
           COALESCE(c.clicks, 0) AS clicks,
           COALESCE(o.opens,  0)::FLOAT / NULLIF(s.sends, 0) AS open_rate,
           COALESCE(c.clicks, 0)::FLOAT / NULLIF(s.sends, 0) AS ctr
    FROM sends s
    LEFT JOIN opens  o ON s.week_start = o.week_start AND s.canvas_name = o.canvas_name
    LEFT JOIN clicks c ON s.week_start = c.week_start AND s.canvas_name = c.canvas_name
    ORDER BY 1, 2
    """
    df = _norm(_df(_braze().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_canvas_rooms_weekly_hav(start: date, end: date) -> pd.DataFrame:
    """Weekly rooms sold + DF revenue + merch revenue per canvas step (UTM_CAMPAIGN) for HAV.
    Groups by UTM_CAMPAIGN so Python-side keyword matching can assign canvas groups correctly —
    SQL keyword matching on step names is unreliable because step names differ from canvas names.
    """
    q = f"""
    WITH design_fees AS (
        SELECT
            DATE_TRUNC('week', df.DESIGN_PAYMENT_DATE)::DATE AS week_start,
            s.UTM_CAMPAIGN                                    AS utm_campaign,
            COUNT(DISTINCT dfs.ROOM_ID)                       AS rooms,
            SUM(df.NET_REVENUE)                               AS df_revenue
        FROM PROD.ANALYTICS.DESIGN_FEE_SESSIONS dfs
        JOIN PROD.ANALYTICS.SESSIONS            s  ON s.SESSION_ID = dfs.SESSION_ID
        JOIN PROD.ANALYTICS.DESIGN_FEES         df ON df.ROOM_ID   = dfs.ROOM_ID
        WHERE dfs.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
          AND s.UTM_SOURCE = 'braze_havenly'
          AND s.UTM_CAMPAIGN LIKE 'TRG!_%' ESCAPE '!'
          AND df.IS_PAID = 1
          AND df.DESIGN_PAYMENT_DATE::DATE BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
    ),
    merch AS (
        SELECT
            DATE_TRUNC('week', os.ORDER_CREATED)::DATE AS week_start,
            s.UTM_CAMPAIGN                              AS utm_campaign,
            COUNT(DISTINCT mos.ORDER_ID)                AS orders,
            SUM(os.NET_ORDER_REVENUE)                   AS merch_revenue
        FROM PROD.ANALYTICS.MERCH_ORDER_SESSIONS mos
        JOIN PROD.ANALYTICS.SESSIONS             s  ON s.SESSION_ID = mos.SESSION_ID
        JOIN PROD.ANALYTICS.ORDER_SUMMARY        os ON os.ORDER_ID  = mos.ORDER_ID
        WHERE mos.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
          AND s.UTM_SOURCE = 'braze_havenly'
          AND s.UTM_CAMPAIGN LIKE 'TRG!_%' ESCAPE '!'
          AND os.ORDER_CREATED::DATE BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
    ),
    all_steps AS (
        SELECT week_start, utm_campaign FROM design_fees
        UNION
        SELECT week_start, utm_campaign FROM merch
    )
    SELECT a.week_start, a.utm_campaign,
           COALESCE(d.rooms,         0) AS rooms,
           COALESCE(d.df_revenue,    0) AS df_revenue,
           COALESCE(m.merch_revenue, 0) AS merch_revenue
    FROM all_steps a
    LEFT JOIN design_fees d ON a.week_start = d.week_start AND a.utm_campaign = d.utm_campaign
    LEFT JOIN merch       m ON a.week_start = m.week_start AND a.utm_campaign = m.utm_campaign
    ORDER BY 1, 2
    """
    df = _norm(_df(_prod().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_canvas_step_map_hav() -> dict[str, str]:
    """Return {canvas_step_name → canvas_name} for all HAV canvases.
    Used to translate UTM_CAMPAIGN (step name) in PROD.ANALYTICS.SESSIONS to the
    human-readable canvas name so revenue data can be matched to canvas groups.
    """
    q = f"""
    SELECT DISTINCT
        COALESCE(NULLIF(CANVAS_STEP_NAME, ''), CAMPAIGN_NAME) AS step_name,
        COALESCE(NULLIF(CANVAS_NAME,      ''), CAMPAIGN_NAME) AS canvas_name
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{HAV_APP_GROUP_ID}'
      AND CANVAS_ID IS NOT NULL AND CANVAS_ID != ''
      AND CANVAS_STEP_NAME IS NOT NULL AND CANVAS_STEP_NAME != ''
    """
    df = _norm(_df(_braze().execute_query(q)))
    if df.empty or "STEP_NAME" not in df.columns or "CANVAS_NAME" not in df.columns:
        return {}
    return dict(zip(df["STEP_NAME"], df["CANVAS_NAME"]))


# ── Canvas YoY — render ───────────────────────────────────────────────────────

_HAV_CANVAS_BRAZE_METRICS = ["Sends", "Open Rate", "CTR"]
_HAV_CANVAS_REV_METRICS   = ["Rooms Sold", "DF Revenue", "Merch Revenue"]
_HAV_ALL_CANVAS_METRICS   = _HAV_CANVAS_REV_METRICS + _HAV_CANVAS_BRAZE_METRICS


def _hav_group_canvas(name: str) -> str:
    """Map a raw HAV canvas name to its display group label via keyword rules."""
    n = name.lower()
    for keywords, label in HAV_CANVAS_GROUP_RULES:
        if any(kw.lower() in n for kw in keywords):
            return label
    return name  # ungrouped: use the canvas name itself


def render_canvas_yoy_hav():
    today     = date.today()
    yoy_end   = today - timedelta(days=1)
    yoy_start = yoy_end - timedelta(weeks=104)

    with st.spinner("Loading canvas data…"):
        braze_weekly = fetch_canvas_braze_weekly_hav(yoy_start, yoy_end)
        rooms_weekly = fetch_canvas_rooms_weekly_hav(yoy_start, yoy_end)
        step_map     = fetch_canvas_step_map_hav()   # step_name → canvas_name

    if braze_weekly.empty:
        st.caption("No canvas send data available.")
        return

    # Build group mapping from actual canvas names in the datashare
    raw_canvases = sorted(braze_weekly["CANVAS_NAME"].dropna().unique())
    group_map    = {c: _hav_group_canvas(c) for c in raw_canvases}
    _std_groups  = [label for _, label in HAV_CANVAS_GROUP_RULES]
    groups = (
        [g for g in _std_groups if g in group_map.values()]
        + sorted(g for g in set(group_map.values()) if g not in _std_groups)
    )
    raw_for = {g: [c for c, v in group_map.items() if v == g] for g in groups}

    cv_col, m1_col, m2_col = st.columns([2, 1, 1])
    with cv_col:
        group = st.selectbox("Canvas group", groups, key="hav_canvas_yoy_select")
        members = raw_for[group]
        if len(members) > 1:
            st.caption(f"Combines: {', '.join(sorted(members))}")
    with m1_col:
        metric = st.radio("Primary metric", _HAV_ALL_CANVAS_METRICS,
                          horizontal=False, key="hav_canvas_yoy_metric")
    with m2_col:
        overlay_opts = ["None"] + [m for m in _HAV_ALL_CANVAS_METRICS if m != metric]
        overlay_metric = st.radio("Overlay metric", overlay_opts,
                                  horizontal=False, key="hav_canvas_yoy_overlay")

    def _braze_series(col):
        sub = braze_weekly[braze_weekly["CANVAS_NAME"].isin(members)]
        if col == "OPEN_RATE":
            agg = sub.groupby("WEEK_START").agg(OPENS=("OPENS", "sum"), SENDS=("SENDS", "sum")).reset_index()
            agg["VALUE"] = agg["OPENS"] / agg["SENDS"].replace(0, float("nan"))
            return agg[["WEEK_START", "VALUE"]]
        if col == "CTR":
            agg = sub.groupby("WEEK_START").agg(CLICKS=("CLICKS", "sum"), SENDS=("SENDS", "sum")).reset_index()
            agg["VALUE"] = agg["CLICKS"] / agg["SENDS"].replace(0, float("nan"))
            return agg[["WEEK_START", "VALUE"]]
        agg = sub.groupby("WEEK_START")[col].sum().reset_index()
        return agg.rename(columns={col: "VALUE"})

    def _rev_series(col):
        if rooms_weekly.empty:
            return pd.DataFrame(columns=["WEEK_START", "VALUE"])
        # Translate UTM_CAMPAIGN (step name) → canvas name → canvas group, then filter
        def _step_group(step_name: str) -> str:
            canvas_name = step_map.get(step_name, step_name)
            return _hav_group_canvas(canvas_name)
        mask = rooms_weekly["UTM_CAMPAIGN"].apply(lambda x: _step_group(x or "") == group)
        sub  = rooms_weekly[mask]
        if sub.empty:
            return pd.DataFrame(columns=["WEEK_START", "VALUE"])
        agg = (sub.groupby("WEEK_START")[col].sum()
                  .reset_index().rename(columns={col: "VALUE"}))
        # 0-fill missing weeks across the full chart window. Rooms/DF/Merch are counts —
        # a week with none is genuinely 0, not missing data. Without this, absent weeks
        # become NaN in the chart and Plotly (connectgaps=False) breaks the line into a
        # gap rather than dipping to zero. The weekly grid comes from rooms_weekly's own
        # DATE_TRUNC('week') Mondays, so a 7-day step stays aligned to real week starts.
        full_weeks = pd.date_range(rooms_weekly["WEEK_START"].min(),
                                   rooms_weekly["WEEK_START"].max(), freq="7D").date
        agg = (agg.set_index("WEEK_START")
                  .reindex(full_weeks, fill_value=0)
                  .rename_axis("WEEK_START").reset_index())
        return agg

    _col_map = {
        "Sends":         ("SENDS",         _braze_series),
        "Open Rate":     ("OPEN_RATE",     _braze_series),
        "CTR":           ("CTR",           _braze_series),
        "Rooms Sold":    ("ROOMS",         _rev_series),
        "DF Revenue":    ("DF_REVENUE",    _rev_series),
        "Merch Revenue": ("MERCH_REVENUE", _rev_series),
    }

    def _series_for(m):
        col, fn = _col_map[m]
        return fn(col)

    def _fmt_for(m):
        if m in ("DF Revenue", "Merch Revenue"): return "$,.0f"
        if m in ("Open Rate", "CTR"): return ".1%"
        return ",.0f"

    series  = _series_for(metric)
    overlay = _series_for(overlay_metric) if overlay_metric != "None" else None

    _canvas_ty_ly_chart(
        series, metric, _fmt_for(metric),
        key=f"hav_canvas_yoy_{group}_{metric}_{overlay_metric}",
        overlay=overlay,
        overlay_label=overlay_metric if overlay_metric != "None" else "",
        overlay_fmt=_fmt_for(overlay_metric) if overlay_metric != "None" else ",.0f",
    )


# ── Section renderers ─────────────────────────────────────────────────────────

def render_at_a_glance(ty_email, ly_email, ty_push, ly_push):
    st.subheader("At a Glance — All CRM")

    def e(df, col):
        return _e(df, col)

    ty_sends = e(ty_email, "SENDS")
    ly_sends = e(ly_email, "SENDS")
    ty_or    = e(ty_email, "OPEN_RATE")
    ly_or    = e(ly_email, "OPEN_RATE")
    ty_ctr   = e(ty_email, "CTR")
    ly_ctr   = e(ly_email, "CTR")
    ty_push_sends = e(ty_push, "SENDS")
    ly_push_sends = e(ly_push, "SENDS")
    ty_tap   = e(ty_push, "TAP_RATE")
    ly_tap   = e(ly_push, "TAP_RATE")

    cols = st.columns(5)
    with cols[0]: _metric("Email Sends",  ty_sends,      ly_sends,      num)
    with cols[1]: _metric("Open Rate",    ty_or,         ly_or,         pct, is_rate=True)
    with cols[2]: _metric("CTR",          ty_ctr,        ly_ctr,        pct, is_rate=True)
    with cols[3]: _metric("Push Sends",   ty_push_sends, ly_push_sends, num)
    with cols[4]: _metric("Tap Rate",     ty_tap,        ly_tap,        pct, is_rate=True)


def _revenue_metrics(ty_rev: dict, ly_rev: dict):
    """Render 3 revenue metric columns: Merch Revenue | Design Fee Revenue | Rooms Sold."""
    cols = st.columns(3)
    with cols[0]:
        _metric("Merch Revenue",       _v(ty_rev, "merch_revenue"),
                                       _v(ly_rev, "merch_revenue"), money)
    with cols[1]:
        _metric("Design Fee Revenue",  _v(ty_rev, "design_fee_revenue"),
                                       _v(ly_rev, "design_fee_revenue"), money)
    with cols[2]:
        _metric("Rooms Sold",          _v(ty_rev, "rooms"),
                                       _v(ly_rev, "rooms"), num)


def _engagement_metrics(ty_email: pd.DataFrame, ly_email: pd.DataFrame,
                         label_prefix: str = ""):
    """Sends / Open Rate / CTR / CTO in a 4-column row."""
    cols = st.columns(4)
    with cols[0]: _metric("Sends",     _e(ty_email,"SENDS"),     _e(ly_email,"SENDS"),     num)
    with cols[1]: _metric("Open Rate", _e(ty_email,"OPEN_RATE"), _e(ly_email,"OPEN_RATE"), pct, is_rate=True)
    with cols[2]: _metric("CTR",       _e(ty_email,"CTR"),       _e(ly_email,"CTR"),       pct, is_rate=True)
    with cols[3]: _metric("CTO",       _e(ty_email,"CTO"),       _e(ly_email,"CTO"),       pct, is_rate=True)


def _col(df: pd.DataFrame, col: str) -> Optional[float]:
    """Extract scalar from first row of DataFrame, None if missing."""
    if df.empty or col not in df.columns:
        return None
    v = df.iloc[0][col]
    return float(v) if v is not None else None


def _trend_values(mode: str, ty_period: Period,
                  program: Optional[str], audience: Optional[str],
                  col: str) -> tuple[list, list]:
    """Return (periods, values) for a trend chart over the recent periods."""
    periods = trend_periods(mode, ty_period)
    values = [_col(fetch_email_engagement(p.start, p.end, program, audience), col)
              for p in periods]
    return periods, values


def _email_rows(ty: pd.DataFrame, ty_rev: dict,
                ly: pd.DataFrame, ly_rev: dict,
                ly_rates: Optional[pd.DataFrame] = None) -> list:
    """Build make_row list for engagement + revenue."""
    r = ly_rates if (ly_rates is not None and not ly_rates.empty) else ly
    ly_rev_data = ly_rev if ly_rev else {}
    return [
        make_row("Sends",         _col(ty,"SENDS"),         _col(ly,"SENDS"),     num,  higher_is_better=True),
        make_row("Open Rate",     _col(ty,"OPEN_RATE"),     _col(r,"OPEN_RATE"),  pct,  higher_is_better=True, is_rate=True),
        make_row("CTR",           _col(ty,"CTR"),           _col(r,"CTR"),        pct,  higher_is_better=True, is_rate=True),
        make_row("CTO",           _col(ty,"CTO"),           _col(r,"CTO"),        pct,  higher_is_better=True, is_rate=True),
        make_row("Merch Revenue", ty_rev.get("merch_revenue"),      ly_rev_data.get("merch_revenue"),      money),
        make_row("Design Fee Rev",ty_rev.get("design_fee_revenue"), ly_rev_data.get("design_fee_revenue"), money),
        make_row("Rooms Sold",    ty_rev.get("rooms"),               ly_rev_data.get("rooms"),              num),
    ]


def _render_program_block(label: str, program: str,
                          ty_period: Period, ly_period: Period,
                          audience: Optional[str], attribution: str,
                          mode: str, detail_key: str):
    """Renders one B&B or Triggered sub-block with YOY grid + chart + detail."""
    st.markdown(f"#### {label}")
    if program == "TRG":
        st.caption("All audiences — triggered flows are audience-specific by design; "
                   "step names carry _PC_ / _CONV_ markers.")

    # LY program/audience filtering works for all periods: campaign/canvas names are blank
    # in the datashare before Oct 2025 but recovered from the changelog via *_API_ID (see the
    # "Changelog name recovery" helpers), so no all-email fallback is needed.
    with st.spinner(f"Loading {label}…"):
        ty_eng = fetch_email_engagement(ty_period.start, ty_period.end, program, audience)
        ty_rev = fetch_revenue(ty_period.start, ty_period.end, audience, attribution, program=program)
        ly_eng = fetch_email_engagement(ly_period.start, ly_period.end, program, audience)
        ly_rev = fetch_revenue(ly_period.start, ly_period.end, audience, attribution, program=program)

    render_metric_grid(_email_rows(ty_eng, ty_rev, ly_eng, ly_rev))

    # Trend chart — sends and open rate side by side
    t_periods, t_sends   = _trend_values(mode, ty_period, program, audience, "SENDS")
    t_periods, t_or      = _trend_values(mode, ty_period, program, audience, "OPEN_RATE")
    if any(v is not None for v in t_sends):
        c1, c2 = st.columns(2)
        with c1:
            trend_chart(t_periods, t_sends, "Sends", num,
                        key=f"trend_sends_{program}_{audience}_{detail_key}")
        with c2:
            trend_chart(t_periods, t_or,    "Open Rate", pct,
                        key=f"trend_or_{program}_{audience}_{detail_key}")

    expander_label = "Campaign detail" if program == "BB" else "Canvas / step detail"
    with st.expander(expander_label):
        with st.spinner("Loading…"):
            ga4_det = fetch_hav_ga4_detail(ty_period.start, ty_period.end)
            if program == "BB":
                detail  = fetch_bb_detail_hav(ty_period.start, ty_period.end, audience)
                rev_det = fetch_bb_revenue_detail(ty_period.start, ty_period.end, audience, attribution)
                _render_detail_table(detail, rev_df=rev_det, ga4_df=ga4_det)
            else:
                detail  = fetch_trg_detail_hav(ty_period.start, ty_period.end, audience)
                rev_det = fetch_trg_revenue_detail(ty_period.start, ty_period.end, attribution)
                _render_trg_detail_table(detail, rev_df=rev_det, ga4_df=ga4_det)


def render_marketing_section(ty_period: Period, ly_period: Period,
                              audience: Optional[str], attribution: str, mode: str):
    attr_label = "Last Click" if attribution == "last_click" else "3-Day Post-Click"
    aud_label  = _audience_label(audience)
    st.subheader(f"Marketing — {aud_label}")
    st.caption(f"Revenue attribution: {attr_label}")

    _render_program_block("Batch & Blast", "BB",  ty_period, ly_period, audience, attribution, mode, "bb")
    # Triggered: always show all audiences — each flow is inherently audience-specific
    # (step names encode _PC_ / _CONV_); filtering by audience toggle would hide most flows
    _render_program_block("Triggered",     "TRG", ty_period, ly_period, None, attribution, mode, "trg")

    with st.expander("Click attribution reconciliation"):
        with st.spinner("Calculating…"):
            rec = fetch_click_reconciliation(ty_period.start, ty_period.end, audience)
        if rec:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Real Clicks (Braze)",      num(rec.get("raw_clicks")))
            c2.metric("Unsubs (backed out)",       num(rec.get("unsubs")))
            c3.metric("Intent Clicks",             num(rec.get("intent_clicks")))
            c4.metric("Email-Attributed Sessions", num(rec.get("email_sessions")))
            gap     = rec.get("gap", 0)
            gap_pct = rec.get("gap_pct")
            if gap:
                st.caption(
                    f"**Estimated unattributed clicks: {num(gap)}**"
                    + (f" ({gap_pct:.1%} of intent clicks)" if gap_pct else "")
                    + " — likely app opens that resolved to Direct or iOS in the session model."
                )
        else:
            st.caption("Could not load reconciliation data.")


def render_push_section(ty_push: pd.DataFrame, ly_push: pd.DataFrame):
    st.subheader("Push Notifications")
    rows = [
        make_row("Sends",    _e(ty_push,"SENDS"),    _e(ly_push,"SENDS"),    num),
        make_row("Taps",     _e(ty_push,"TAPS"),     _e(ly_push,"TAPS"),     num),
        make_row("Tap Rate", _e(ty_push,"TAP_RATE"), _e(ly_push,"TAP_RATE"), pct, is_rate=True),
    ]
    render_metric_grid(rows)


def render_everything_else(ty_period: Period, ly_period: Period):
    st.subheader("Everything Else")
    st.caption("Transactional (OT_) and all other non-marketing sends")

    with st.spinner("Loading…"):
        ty_other = fetch_other_engagement(ty_period.start, ty_period.end)
        ly_other = fetch_other_engagement(ly_period.start, ly_period.end)

    def _row(cat):
        ty = ty_other[ty_other["CATEGORY"] == cat].iloc[0] if not ty_other.empty and cat in ty_other.get("CATEGORY", pd.Series()).values else {}
        ly = ly_other[ly_other["CATEGORY"] == cat].iloc[0] if not ly_other.empty and cat in ly_other.get("CATEGORY", pd.Series()).values else {}
        return ty, ly

    for cat in ["Transactional", "Other"]:
        ty_row, ly_row = _row(cat)
        if not isinstance(ty_row, dict) and ty_row.get("SENDS", 0):
            st.markdown(f"**{cat}**")
            rows = [
                make_row("Sends",     ty_row.get("SENDS"),     ly_row.get("SENDS"),     num),
                make_row("Open Rate", ty_row.get("OPEN_RATE"), ly_row.get("OPEN_RATE"), pct, is_rate=True),
                make_row("CTR",       ty_row.get("CTR"),       ly_row.get("CTR"),       pct, is_rate=True),
            ]
            render_metric_grid(rows)

    with st.expander("Campaign detail"):
        with st.spinner("Loading…"):
            _other_detail = _fetch_other_detail_hav(ty_period.start, ty_period.end)
        _render_detail_table(_other_detail)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="Havenly Lifecycle Dashboard",
                       layout="wide", initial_sidebar_state="collapsed")
    st.markdown("""
        <style>
        .block-container { padding-top: 1.5rem; }
        h1 { font-size: 1.6rem; }
        h2 { font-size: 1.2rem; border-bottom: 2px solid #4a7c8e; padding-bottom: 4px; }
        h4 { font-size: 1rem; color: #444; margin-top: 0.8rem; margin-bottom: 0.3rem; }
        [data-testid="stMetricValue"] { font-size: 1.3rem; font-weight: 600; }
        hr { margin: 1.5rem 0; border-color: #dee2e6; }
        </style>
    """, unsafe_allow_html=True)

    st.title("Havenly — Lifecycle Performance")

    # ── Period toggle ────────────────────────────────────────────────────────
    top_left, top_right = st.columns([5, 1])

    with top_left:
        mode = st.radio("Period", MODES, horizontal=True, label_visibility="collapsed")

        if mode == "Custom":
            today     = date.today()
            yesterday = today - timedelta(days=1)
            c1, c2, _ = st.columns([1, 1, 4])
            custom_start = c1.date_input("From", value=yesterday - timedelta(days=6),
                                         max_value=yesterday, key="custom_start")
            custom_end   = c2.date_input("To",   value=yesterday,
                                         min_value=custom_start, max_value=yesterday,
                                         key="custom_end")
            if custom_start > custom_end:
                st.warning("Start date must be before end date.")
                return
            label = (custom_start.strftime("%-d %b %Y") if custom_start == custom_end
                     else f"{custom_start.strftime('%-d %b')} – {custom_end.strftime('%-d %b %Y')}")
            ty_period = Period(custom_start, custom_end, label)
        else:
            ty_period = get_period(mode)

        ly_p = ly_for(ty_period, mode)

        # ── Attribution toggle ───────────────────────────────────────────────
        attribution = st.radio(
            "Attribution",
            ["Last Click", "3-Day Post-Click"],
            horizontal=True,
            label_visibility="collapsed",
            key="attribution",
        )
        attribution_key = "last_click" if attribution == "Last Click" else "3day"

        st.caption(
            f"**{ty_period.label}**  ·  vs LY: {ly_p.label}"
        )

    # ── Audience toggle ──────────────────────────────────────────────────────
    audience_label = st.radio(
        "Audience",
        ["Pre-Converted", "Converted", "All"],
        horizontal=True,
        label_visibility="collapsed",
        key="audience",
    )
    audience_key = {"Pre-Converted": "PC", "Converted": "CONV", "All": None}[audience_label]

    # ── Known data-quality issues ─────────────────────────────────────────────
    render_data_issue_banners("HAV", ty_period, ly_p)

    # ── Fetch At a Glance data ───────────────────────────────────────────────
    with st.spinner("Loading…"):
        ty_email_all = fetch_email_all_crm(ty_period.start, ty_period.end)
        ly_email_all = fetch_email_all_crm(ly_p.start,      ly_p.end)
        ty_push      = fetch_push_engagement(ty_period.start, ty_period.end)
        ly_push      = fetch_push_engagement(ly_p.start,      ly_p.end)

    # ── At a Glance ──────────────────────────────────────────────────────────
    st.markdown("---")
    render_at_a_glance(ty_email_all, ly_email_all, ty_push, ly_push)

    # ── Marketing ────────────────────────────────────────────────────────────
    st.markdown("---")
    render_marketing_section(ty_period, ly_p, audience_key, attribution_key, mode)

    # ── Triggered Canvas — Year over Year ────────────────────────────────────
    st.markdown("---")
    st.subheader("Triggered Canvas — Year over Year")
    render_canvas_yoy_hav()

    # ── Push ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    render_push_section(ty_push, ly_push)

    # ── Hard divider — non-marketing ─────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        "<div style='background:#f8f9fa; border-left:4px solid #dee2e6; "
        "padding:6px 12px; font-size:0.8rem; color:#6c757d; margin-bottom:1rem;'>"
        "Non-marketing sends below — transactional, system, and designer messages"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Everything Else ───────────────────────────────────────────────────────
    render_everything_else(ty_period, ly_p)

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "**Sources:** Email/Push engagement — Braze Raw Events Datashare. "
        "Revenue — Havenly session model (PROD.ANALYTICS). "
        f"Last-click: MERCH_ORDER_SESSIONS / DESIGN_FEE_SESSIONS where TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email') "
        f"(source renamed 2026-07-10; both matched). "
        f"3-day post-click: Braze click events → orders/rooms within 3 days."
    )


if __name__ == "__main__" or True:
    main()
