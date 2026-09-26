"""
Lifecycle Performance Dashboard — shared base module.
Do not run directly; use a brand entry point (e.g. lifecycle_dashboard.py, cz_lifecycle_dashboard.py).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

import yaml
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Credentials ───────────────────────────────────────────────────────────────

def _load_credentials():
    try:
        sec = st.secrets["snowflake"]
        for key, val in sec.items():
            os.environ.setdefault(f"SNOWFLAKE_{key.upper()}", str(val))
    except (KeyError, FileNotFoundError):
        from dotenv import load_dotenv
        _here = Path(__file__).resolve()
        for _parent in _here.parents:
            if (_parent / ".env").exists():
                load_dotenv(_parent / ".env")
                break

_load_credentials()

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.snowflake_client import SnowflakeClient

# ── Constants ─────────────────────────────────────────────────────────────────

BRAZE_DB      = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
BRAZE_SCHEMA  = "DATALAKE_SHARING"

# Tier-3 datashare (ID + STF, added 2026-05-22)
BRAZE_DB_TIER3     = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
BRAZE_SCHEMA_TIER3 = "DATALAKE_SHARING_TIERED"

# ── Brand-configurable globals (set by entry point before main()) ─────────────

APP_GROUP_ID: str = ""
GA4_TABLE:    str = ""
ACCENT:       str = "#e94560"
MUTED:        str = "#adb5bd"
BRAND_CODE:   str = ""
BRAND_NAME:   str = ""
HAS_FORECAST: bool = False
MODES: list = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# Canvas grouping rules: list of (keywords, label)
# keywords = list of lowercase strings; ANY match wins; label=None means keep raw canvas name
CANVAS_GROUP_RULES: list = []
# GA4 canvas attribution rules: same format, used to generate CASE WHEN SQL
GA4_CANVAS_RULES: list = []

# ── Forecast constants (set by entry point when HAS_FORECAST = True) ──────────
# FORECAST_MONTH_START / _END: first and last day of the forecast month
# CATEGORY_BENCHMARKS: median GA4 lifecycle revenue on send days by email category
# CATEGORY_LABELS: display names for each category key
# SMS_UPLIFT: median incremental revenue on days with a batch SMS send
# FORECAST_SENDS: dict keyed by "YYYY-MM-DD" → {name, category, if_needed, has_sms}

FORECAST_MONTH_START: Optional[date] = None
FORECAST_MONTH_END:   Optional[date] = None
FORECAST_MONTH_LABEL: str = "Forecast Month"

CATEGORY_BENCHMARKS: dict = {}
CATEGORY_LABELS:     dict = {}
SMS_UPLIFT:          float = 0.0
FORECAST_SENDS:      dict = {}

# Multi-month forecast list (preferred over single-month globals above).
# Each entry: {start: date, end: date, label: str, sends: dict}
# Past months (end < today) → compact summary card.
# Current/upcoming month → full daily chart.
# When empty, falls back to FORECAST_MONTH_START / _END / _LABEL / FORECAST_SENDS.
FORECAST_MONTHS: list = []

# ── YAML-mode support (brands not in Braze datashare, e.g. ID) ────────────────
# Set YAML_CAMPAIGNS_DIR to the campaigns folder path to load email metrics from
# YAML files instead of the Braze Snowflake datashare.
# Set HAS_SMS = False for brands with no SMS channel.
def _main_repo_campaigns() -> Optional[Path]:
    """Return the campaigns/ folder in the main repo, even when running from a worktree."""
    import subprocess
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=Path(__file__).parent, stderr=subprocess.DEVNULL
        ).decode().strip()
        p = Path(common).parent / "campaigns"
        return p if p.is_dir() else None
    except Exception:
        return None

YAML_CAMPAIGNS_DIR: Optional[Path] = None
# Email addresses to exclude from live Braze datashare queries (confirmed bot/fraud
# traffic — e.g. the mmcloughlin/laura ID signup-bombing wave, 2026-07). Set per-brand
# in the brand config script. Applied as a LOWER(EMAIL_ADDRESS) NOT IN (...) filter
# everywhere sends/opens/clicks are pulled straight from the datashare.
EXCLUDED_BOT_EMAILS: list = []
HAS_SMS: bool = True
HAS_SWATCHES: bool = False    # set True for brands with swatch data in GA4
SWATCH_GA4_COL: str = ""      # quoted column expr, e.g. '"KEYEVENTS:GENERATE_LEAD_SWATCH"'
BRAZE_TIER3: bool = False  # set True for brands in the tier-3 datashare (ID, STF)
FINANCE_FORECAST_COL: str = "BW_ECOMM_ADJUSTED_GROSS_REVENUE"  # brand-specific column in ALL_COMPANY_DAILY_FORECAST

# Triggered email detection
# Primary: TRG% prefix (current UTM convention)
# Fallback: keywords in campaign name, used only when no TRG sessions exist for the period
_TRG_KEYWORDS    = ("abandon", "browse", "cart", "welcome")
_TRG_PREFIX_SQL  = "UPPER(SESSIONCAMPAIGNNAME) LIKE 'TRG%'"
_KW_SQL          = " OR ".join(f"LOWER(SESSIONCAMPAIGNNAME) LIKE '%{kw}%'" for kw in _TRG_KEYWORDS)
_TRG_PREFIX_CASE = f"CASE WHEN {_TRG_PREFIX_SQL} THEN 'Triggered' ELSE 'B&B' END"
_KW_CASE         = f"CASE WHEN {_KW_SQL} THEN 'Triggered' ELSE 'B&B' END"


def _has_trg_sessions(df: pd.DataFrame) -> bool:
    """True if df (from fetch_ga4_revenue) contains any triggered email sessions."""
    if df.empty or "CHANNEL" not in df.columns or "PROGRAM" not in df.columns:
        return False
    mask = (df["CHANNEL"] == "Email") & (df["PROGRAM"] == "Triggered")
    return mask.any() and pd.to_numeric(df.loc[mask, "SESSIONS"], errors="coerce").sum() > 0


def _classify_triggered(names: pd.Series) -> pd.Series:
    """Boolean Series: True = triggered. Uses TRG prefix if any exist, else keyword fallback."""
    is_trg = names.str.upper().str.startswith("TRG", na=False)
    if is_trg.any():
        return is_trg
    return names.apply(lambda n: isinstance(n, str) and any(kw in n.lower() for kw in _TRG_KEYWORDS))

# ── Period helpers ────────────────────────────────────────────────────────────

@dataclass
class Period:
    start: date
    end:   date
    label: str


def _safe_yr(d: date, y: int) -> date:
    try:
        return d.replace(year=y)
    except ValueError:
        return d.replace(year=y, day=28)


def _month_start(ref: date, months_back: int = 0) -> date:
    t = ref.year * 12 + ref.month - 1 - months_back
    return date(t // 12, t % 12 + 1, 1)


def _month_end(d: date) -> date:
    return _month_start(d, months_back=-1) - timedelta(days=1)


def _quarter_start(d: date) -> date:
    return d.replace(month=((d.month - 1) // 3) * 3 + 1, day=1)


def get_period(mode: str) -> Period:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    if mode == "Yesterday":
        return Period(yesterday, yesterday, yesterday.strftime("%-d %b %Y"))
    if mode == "Last Week":
        sun = today - timedelta(days=today.weekday() + 1)
        mon = sun - timedelta(days=6)
        return Period(mon, sun, f"{mon.strftime('%-d %b')} – {sun.strftime('%-d %b %Y')}")
    if mode == "Last Month":
        ms = _month_start(today, months_back=1)
        return Period(ms, _month_end(ms), ms.strftime("%B %Y"))
    if mode == "MTD":
        ms = today.replace(day=1)
        return Period(ms, yesterday, f"{today.strftime('%B')} MTD")
    if mode == "Last Quarter":
        qs = _quarter_start(today)
        lqs = _quarter_start(qs - timedelta(days=1))
        lqe = qs - timedelta(days=1)
        lq  = (lqs.month - 1) // 3 + 1
        return Period(lqs, lqe, f"Q{lq} {lqs.year}")
    # QTD
    qs = _quarter_start(today)
    q  = (today.month - 1) // 3 + 1
    return Period(qs, yesterday, f"Q{q} {today.year} QTD")


def ly_for(p: Period, mode: str) -> Period:
    if mode in ("Yesterday", "Last Week", "Custom"):
        s = p.start - timedelta(weeks=52)
        e = p.end   - timedelta(weeks=52)
        if s == e:
            label = s.strftime("%-d %b %Y")
        else:
            label = f"{s.strftime('%-d %b')} – {e.strftime('%-d %b %Y')}"
        return Period(s, e, label)
    s = _safe_yr(p.start, p.start.year - 1)
    e = _safe_yr(p.end,   p.end.year   - 1)
    if mode == "Last Month":
        label = s.strftime("%B %Y")
    elif mode in ("MTD", "QTD"):
        label = p.label.replace(str(p.start.year), str(p.start.year - 1))
    elif mode == "Last Quarter":
        lq = (s.month - 1) // 3 + 1
        label = f"Q{lq} {s.year}"
    else:
        label = f"LY {p.label}"
    return Period(s, e, label)


def trend_periods(mode: str, current: Period) -> list[Period]:
    """Recent periods ending at current for trend sparklines."""
    if mode == "Yesterday":
        # Last 7 days as individual days
        return [
            Period(current.end - timedelta(days=i),
                   current.end - timedelta(days=i),
                   (current.end - timedelta(days=i)).strftime("%-d %b"))
            for i in range(6, -1, -1)
        ]
    if mode == "Last Week":
        return [
            Period(current.start - timedelta(weeks=i),
                   current.end   - timedelta(weeks=i),
                   (current.start - timedelta(weeks=i)).strftime("%-d %b"))
            for i in range(5, -1, -1)
        ]
    if mode == "Custom":
        span = (current.end - current.start).days + 1
        if span <= 31:
            return [
                Period(current.start + timedelta(days=i),
                       current.start + timedelta(days=i),
                       (current.start + timedelta(days=i)).strftime("%-d %b"))
                for i in range(span)
            ]
        elif span <= 91:
            out, d = [], current.start
            while d <= current.end:
                we = min(d + timedelta(days=6), current.end)
                out.append(Period(d, we, d.strftime("%-d %b")))
                d += timedelta(days=7)
            return out
        else:
            out, ms = [], current.start.replace(day=1)
            while ms <= current.end:
                me = min(_month_end(ms), current.end)
                out.append(Period(ms, me, ms.strftime("%b '%y")))
                ms = _month_start(ms, months_back=-1)
            return out
    # Monthly / MTD / QTD / Last Quarter / Last Month → last 6 calendar months
    out = []
    for i in range(5, -1, -1):
        ms = _month_start(current.start, months_back=i)
        me = _month_end(ms) if i > 0 else current.end
        out.append(Period(ms, me, ms.strftime("%b '%y")))
    return out


# ── Snowflake helpers ─────────────────────────────────────────────────────────

def _bot_email_sql_filter() -> str:
    """SQL fragment excluding EXCLUDED_BOT_EMAILS from a datashare query. Empty string
    if nothing is configured for this brand — safe to always append."""
    if not EXCLUDED_BOT_EMAILS:
        return ""
    emails = ", ".join("'" + e.lower().replace("'", "''") + "'" for e in EXCLUDED_BOT_EMAILS)
    return f"AND (EMAIL_ADDRESS IS NULL OR LOWER(EMAIL_ADDRESS) NOT IN ({emails}))"


@st.cache_resource(ttl=10800)  # 3h — Snowflake drops idle connections at ~4h
def _braze_client():
    if BRAZE_TIER3:
        return SnowflakeClient(schema=BRAZE_SCHEMA_TIER3, database=BRAZE_DB_TIER3)
    return SnowflakeClient(schema=BRAZE_SCHEMA, database=BRAZE_DB)


@st.cache_resource(ttl=10800)
def _ga4_client():
    # GA4_TABLE is fully-qualified; schema is parsed from it for SnowflakeClient
    parts = GA4_TABLE.split(".")
    db, schema = (parts[0], parts[1]) if len(parts) >= 2 else ("AIRBYTE_DATABASE", "LANDING_BURROW_GA4")
    return SnowflakeClient(schema=schema, database=db)


@st.cache_resource(ttl=10800)
def _fivetran_client():
    return SnowflakeClient(schema="UPLOADS", database="FIVETRAN_DB")


def _df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty:
        df.columns = [c.upper() for c in df.columns]
    return df


# ── Data fetching ─────────────────────────────────────────────────────────────

# ── YAML-mode helpers ─────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _load_yaml_campaigns(channel: str = "email") -> list:
    """Load brand campaigns from YAML files for a given channel. Cached 5 min."""
    if not YAML_CAMPAIGNS_DIR:
        return []
    campaigns = []
    for f in Path(YAML_CAMPAIGNS_DIR).glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            if (data and data.get("brand") == BRAND_CODE
                    and data.get("channel") == channel):
                campaigns.append(data)
        except Exception:
            pass
    return campaigns


def _yaml_sent_date(c: dict) -> Optional[date]:
    """Extract the intended send date for a campaign YAML.

    Priority:
    1. Date embedded in campaign name (YYYY_MM_DD pattern) — most reliable for
       Braze batch campaigns where first_sent can bleed into the prior UTC day.
    2. last_sent date — closer to the actual delivery window than first_sent.
    3. first_sent date — fallback.
    """
    import re
    from datetime import datetime as _dt

    # 1. Parse from name (e.g. P_EM_2026_06_01_ID_...)
    name = c.get("name") or ""
    m = re.search(r'(\d{4})[_-](\d{2})[_-](\d{2})', name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    def _parse(v):
        if not v:
            return None
        if isinstance(v, date) and not isinstance(v, _dt):
            return v
        if isinstance(v, _dt):
            return v.date()
        try:
            return _dt.fromisoformat(str(v).replace("Z", "+00:00")).date()
        except Exception:
            return None

    # 2. last_sent
    ls = _parse((c.get("dates") or {}).get("last_sent"))
    if ls:
        return ls

    # 3. first_sent
    return _parse((c.get("dates") or {}).get("first_sent"))


def _yaml_perf(c: dict) -> dict:
    p = c.get("performance_summary") or {}
    return {
        "sends":  int(p.get("total_sends",  0) or 0),
        "opens":  int(p.get("total_opens",  0) or 0),
        "clicks": int(p.get("total_clicks", 0) or 0),
    }


def _fetch_email_engagement_yaml(start: date, end: date) -> pd.DataFrame:
    # Only B&B (batch campaigns) are date-filterable from YAMLs.
    # Triggered (canvas_steps) are excluded — period-specific send counts aren't
    # available; GA4 data carries the Triggered section instead.
    b = {"sends": 0, "opens": 0, "clicks": 0}
    for c in _load_yaml_campaigns():
        if c.get("braze_type") == "canvas_step":
            continue
        d = _yaml_sent_date(c)
        if d is None or not (start <= d <= end):
            continue
        p = _yaml_perf(c)
        for k in ("sends", "opens", "clicks"):
            b[k] += p[k]
    s, o, cl = b["sends"], b["opens"], b["clicks"]
    return pd.DataFrame([{
        "PROGRAM":       "B&B",
        "SENDS":         s,
        "UNIQUE_OPENS":  o,
        "UNIQUE_CLICKS": cl,
        "OPEN_RATE":     o / s  if s > 0 else None,
        "CTR":           cl / s if s > 0 else None,
        "CTO":           cl / o if o > 0 else None,
    }])


def _fetch_bb_detail_yaml(start: date, end: date) -> pd.DataFrame:
    rows = []
    for c in _load_yaml_campaigns():
        if c.get("braze_type") == "canvas_step":
            continue
        d = _yaml_sent_date(c)
        if d is None or not (start <= d <= end):
            continue
        p = _yaml_perf(c)
        s, o, cl = p["sends"], p["opens"], p["clicks"]
        rows.append({
            "CAMPAIGN_NAME": c.get("name", ""),
            "SENDS":         s,
            "UNIQUE_OPENS":  o,
            "UNIQUE_CLICKS": cl,
            "OPEN_RATE":     o / s  if s > 0 else None,
            "CTR":           cl / s if s > 0 else None,
            "CTO":           cl / o if o > 0 else None,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("SENDS", ascending=False)


def _fetch_trigger_detail_yaml(start: date, end: date) -> pd.DataFrame:
    # Canvas steps are always-on flows — aggregate by canvas name (not step),
    # metrics are lifetime totals from YAMLs.
    from collections import defaultdict
    canvases: dict = defaultdict(lambda: {"sends": 0, "opens": 0, "clicks": 0})
    for c in _load_yaml_campaigns():
        if c.get("braze_type") != "canvas_step":
            continue
        p = _yaml_perf(c)
        cn = c.get("canvas_name") or c.get("name", "")
        for k in ("sends", "opens", "clicks"):
            canvases[cn][k] += p[k]
    rows = []
    for cn, b in canvases.items():
        s, o, cl = b["sends"], b["opens"], b["clicks"]
        rows.append({
            "CANVAS_NAME":      cn,
            "CANVAS_STEP_NAME": "(all steps)",
            "SENDS":            s,
            "UNIQUE_OPENS":     o,
            "UNIQUE_CLICKS":    cl,
            "OPEN_RATE":        o / s  if s > 0 else None,
            "CTR":              cl / s if s > 0 else None,
            "CTO":              cl / o if o > 0 else None,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values(["CANVAS_NAME", "SENDS"], ascending=[True, False])


def _fetch_sms_engagement_yaml(start: date, end: date) -> pd.DataFrame:
    total = 0
    for c in _load_yaml_campaigns("sms"):
        d = _yaml_sent_date(c)
        if d is None or not (start <= d <= end):
            continue
        total += _yaml_perf(c)["sends"]
    return pd.DataFrame([{"SMS_SENDS": total}])


def _fetch_sms_detail_yaml(start: date, end: date) -> pd.DataFrame:
    rows = []
    for c in _load_yaml_campaigns("sms"):
        is_canvas = c.get("braze_type") == "canvas_step"
        if is_canvas:
            pass  # always-on, include regardless of date
        else:
            d = _yaml_sent_date(c)
            if d is None or not (start <= d <= end):
                continue
        p = _yaml_perf(c)
        rows.append({
            "CAMPAIGN_NAME":    None if is_canvas else c.get("name", ""),
            "CANVAS_NAME":      c.get("canvas_name", "") if is_canvas else None,
            "CANVAS_STEP_NAME": c.get("name", "") if is_canvas else None,
            "SENDS":            p["sends"],
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values(["CANVAS_NAME", "SENDS"],
                          ascending=[True, False], na_position="first")


def _fetch_braze_sms_weekly_yaml(start: date, end: date) -> pd.DataFrame:
    from collections import defaultdict
    buckets: dict = defaultdict(int)
    for c in _load_yaml_campaigns("sms"):
        if c.get("braze_type") == "canvas_step":
            continue  # skip always-on flows from weekly chart
        d = _yaml_sent_date(c)
        if d is None or not (start <= d <= end):
            continue
        week_start = d - timedelta(days=d.weekday())
        buckets[week_start] += _yaml_perf(c)["sends"]
    rows = [{"WEEK_START": ws, "SENDS": s} for ws, s in sorted(buckets.items())]
    return pd.DataFrame(rows)


def _fetch_braze_email_weekly_yaml(start: date, end: date) -> pd.DataFrame:
    from collections import defaultdict
    buckets: dict = defaultdict(lambda: {"sends": 0, "opens": 0, "clicks": 0})
    for c in _load_yaml_campaigns():
        if c.get("braze_type") == "canvas_step":
            continue  # no period-specific data for triggered flows
        d = _yaml_sent_date(c)
        if d is None or not (start <= d <= end):
            continue
        week_start = d - timedelta(days=d.weekday())
        p = _yaml_perf(c)
        for k in ("sends", "opens", "clicks"):
            buckets[(week_start, "B&B")][k] += p[k]
    rows = []
    for (week_start, program), b in sorted(buckets.items()):
        s, o, cl = b["sends"], b["opens"], b["clicks"]
        rows.append({
            "WEEK_START": week_start,
            "PROGRAM":    program,
            "SENDS":      s,
            "OPENS":      o,
            "CLICKS":     cl,
            "OPEN_RATE":  o / s  if s > 0 else None,
            "CTR":        cl / s if s > 0 else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_email_engagement(start: date, end: date) -> pd.DataFrame:
    if YAML_CAMPAIGNS_DIR:
        return _fetch_email_engagement_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
               COUNT(DISTINCT ID)      AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1
    ),
    opens AS (
        SELECT program, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT
                   CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
                   DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1
    ),
    clicks AS (
        SELECT program, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT
                   CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
                   DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1
    )
    SELECT s.program, s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens             END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.program = o.program
    LEFT JOIN clicks c ON s.program = c.program
    """
    return _norm(_df(_braze_client().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_sms_engagement(start: date, end: date) -> pd.DataFrame:
    if not HAS_SMS:
        return pd.DataFrame()
    if YAML_CAMPAIGNS_DIR:
        return _fetch_sms_engagement_yaml(start, end)
    q = f"""
    SELECT
        (SELECT COALESCE(COUNT(DISTINCT ID), 0)
         FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
         WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
           AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}') AS sms_sends
    """
    df = _norm(_df(_braze_client().execute_query(q)))
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_revenue(start: date, end: date) -> pd.DataFrame:
    def _run(prog_case):
        q = f"""
        SELECT SESSIONPRIMARYCHANNELGROUP AS channel,
               {prog_case} AS program,
               SUM(ECOMMERCEPURCHASES) AS orders,
               SUM(TOTALREVENUE)       AS revenue,
               SUM(SESSIONS)           AS sessions
        FROM {GA4_TABLE}
        WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
          AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2
        """
        return _norm(_df(_ga4_client().execute_query(q)))

    df = _run(_TRG_PREFIX_CASE)
    if not _has_trg_sessions(df):
        df = _run(_KW_CASE)
    # Guarantee the expected schema even when the period has no rows yet
    # (e.g. the "Yesterday" tab before GA4 data has landed) so downstream
    # CHANNEL/PROGRAM lookups filter to empty instead of raising KeyError.
    if df.empty:
        df = pd.DataFrame(columns=["CHANNEL", "PROGRAM", "ORDERS", "REVENUE", "SESSIONS"])
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_share(start: date, end: date) -> dict:
    """Total vs lifecycle (Email+SMS) sessions and revenue for share-of-business calc."""
    q = f"""
    SELECT
        SUM(SESSIONS)                                                              AS total_sessions,
        SUM(TOTALREVENUE)                                                          AS total_revenue,
        SUM(CASE WHEN SESSIONPRIMARYCHANNELGROUP IN ('Email','SMS')
                 THEN SESSIONS ELSE 0 END)                                         AS lifecycle_sessions,
        SUM(CASE WHEN SESSIONPRIMARYCHANNELGROUP IN ('Email','SMS')
                 THEN TOTALREVENUE ELSE 0 END)                                     AS lifecycle_revenue
    FROM {GA4_TABLE}
    WHERE TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    """
    try:
        rows = _ga4_client().execute_query(q)
        if rows and rows[0]:
            r = {k.lower(): (v or 0) for k, v in rows[0].items()}
            return r
    except Exception:
        pass
    return {"total_sessions": 0, "total_revenue": 0,
            "lifecycle_sessions": 0, "lifecycle_revenue": 0}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_swatches(start: date, end: date) -> pd.DataFrame:
    """Swatch orders attributed to Email/SMS channels. ID-specific; returns empty when HAS_SWATCHES=False."""
    if not HAS_SWATCHES or not SWATCH_GA4_COL:
        return pd.DataFrame()
    q = f"""
    SELECT SESSIONPRIMARYCHANNELGROUP AS channel,
           SUM({SWATCH_GA4_COL})     AS swatches
    FROM {GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    GROUP BY 1
    """
    return _norm(_df(_ga4_client().execute_query(q)))


def _swatch_val(df: pd.DataFrame, channel: str) -> Optional[float]:
    """Extract swatch count for one channel from fetch_ga4_swatches result."""
    if df is None or df.empty or "CHANNEL" not in df.columns or "SWATCHES" not in df.columns:
        return None
    sub = df[df["CHANNEL"] == channel]
    if sub.empty:
        return None
    v = sub["SWATCHES"].sum()
    return float(v) if v is not None and not pd.isna(v) else None


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_campaign_detail(start: date, end: date) -> pd.DataFrame:
    q = f"""
    SELECT SESSIONCAMPAIGNNAME        AS campaign_name,
           SESSIONPRIMARYCHANNELGROUP AS channel,
           SUM(SESSIONS)              AS sessions,
           SUM(ECOMMERCEPURCHASES)    AS orders,
           SUM(TOTALREVENUE)          AS revenue
    FROM {GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND SESSIONCAMPAIGNNAME NOT IN ('(not set)', '(referral)')
    GROUP BY 1, 2
    """
    df = _norm(_df(_ga4_client().execute_query(q)))
    # Guarantee schema when the period has no rows yet so downstream
    # CHANNEL lookups filter to empty instead of raising KeyError.
    if df.empty:
        df = pd.DataFrame(columns=["CAMPAIGN_NAME", "CHANNEL", "SESSIONS", "ORDERS", "REVENUE"])
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_bb_detail(start: date, end: date) -> pd.DataFrame:
    if YAML_CAMPAIGNS_DIR:
        return _fetch_bb_detail_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT CAMPAIGN_NAME,
               COUNT(DISTINCT ID)      AS sends,

        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}' AND (CANVAS_ID IS NULL OR CANVAS_ID = '')
          AND CAMPAIGN_NAME IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1
    ),
    opens AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT CAMPAIGN_NAME, DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}' AND (CANVAS_ID IS NULL OR CANVAS_ID = '')
              AND CAMPAIGN_NAME IS NOT NULL
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1
    ),
    clicks AS (
        SELECT CAMPAIGN_NAME, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT CAMPAIGN_NAME, DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}' AND (CANVAS_ID IS NULL OR CANVAS_ID = '')
              AND CAMPAIGN_NAME IS NOT NULL
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1
    )
    SELECT s.CAMPAIGN_NAME, s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens                                   END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.CAMPAIGN_NAME = o.CAMPAIGN_NAME
    LEFT JOIN clicks c ON s.CAMPAIGN_NAME = c.CAMPAIGN_NAME
    ORDER BY s.sends DESC
    """
    return _norm(_df(_braze_client().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_trigger_detail(start: date, end: date) -> pd.DataFrame:
    if YAML_CAMPAIGNS_DIR:
        return _fetch_trigger_detail_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT CANVAS_NAME, CANVAS_STEP_NAME,
               COUNT(DISTINCT ID)      AS sends,

        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
          AND CANVAS_ID IS NOT NULL AND CANVAS_ID != '' AND CANVAS_NAME IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1, 2
    ),
    opens AS (
        SELECT CANVAS_NAME, CANVAS_STEP_NAME, COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT CANVAS_NAME, CANVAS_STEP_NAME, DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND CANVAS_ID IS NOT NULL AND CANVAS_ID != '' AND CANVAS_NAME IS NOT NULL
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1, 2
    ),
    clicks AS (
        SELECT CANVAS_NAME, CANVAS_STEP_NAME, COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT CANVAS_NAME, CANVAS_STEP_NAME, DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND CANVAS_ID IS NOT NULL AND CANVAS_ID != '' AND CANVAS_NAME IS NOT NULL
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1, 2
    )
    SELECT s.CANVAS_NAME, s.CANVAS_STEP_NAME, s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens, 0)::FLOAT / s.sends END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks,0)::FLOAT / s.sends END AS ctr,
           CASE WHEN COALESCE(o.unique_opens,0) > 0
                THEN COALESCE(c.unique_clicks,0)::FLOAT / o.unique_opens                                   END AS cto
    FROM sends s
    LEFT JOIN opens  o ON s.CANVAS_NAME = o.CANVAS_NAME AND s.CANVAS_STEP_NAME = o.CANVAS_STEP_NAME
    LEFT JOIN clicks c ON s.CANVAS_NAME = c.CANVAS_NAME AND s.CANVAS_STEP_NAME = c.CANVAS_STEP_NAME
    ORDER BY s.CANVAS_NAME, s.sends DESC
    """
    return _norm(_df(_braze_client().execute_query(q)))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_sms_detail(start: date, end: date) -> pd.DataFrame:
    if YAML_CAMPAIGNS_DIR:
        return _fetch_sms_detail_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT CAMPAIGN_NAME, CANVAS_NAME, CANVAS_STEP_NAME, COUNT(DISTINCT ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
          AND (CAMPAIGN_NAME IS NOT NULL OR CANVAS_NAME IS NOT NULL)
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2, 3
    )
    SELECT s.CAMPAIGN_NAME, s.CANVAS_NAME, s.CANVAS_STEP_NAME, s.sends
    FROM sends s
    ORDER BY s.CANVAS_NAME NULLS FIRST, s.sends DESC
    """
    return _norm(_df(_braze_client().execute_query(q)))


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ga4_weekly_series(start: date, end: date) -> pd.DataFrame:
    """Weekly revenue + sessions for YOY summary chart (2-year window)."""
    q = f"""
    SELECT DATE_TRUNC('week', TO_DATE(DATE, 'YYYYMMDD')) AS week_start,
           SUM(TOTALREVENUE) AS revenue,
           SUM(SESSIONS)     AS sessions
    FROM {GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    GROUP BY 1
    ORDER BY 1
    """
    df = _norm(_df(_ga4_client().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ga4_weekly_detail(start: date, end: date) -> pd.DataFrame:
    """Weekly GA4 revenue/sessions/orders broken down by channel + program."""
    def _run(prog_case):
        q = f"""
        SELECT DATE_TRUNC('week', TO_DATE(DATE, 'YYYYMMDD'))::DATE AS week_start,
               SESSIONPRIMARYCHANNELGROUP AS channel,
               {prog_case} AS program,
               SUM(TOTALREVENUE)        AS revenue,
               SUM(SESSIONS)            AS sessions,
               SUM(ECOMMERCEPURCHASES)  AS orders
        FROM {GA4_TABLE}
        WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
          AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
        GROUP BY 1, 2, 3
        ORDER BY 1
        """
        return _norm(_df(_ga4_client().execute_query(q)))

    # Check for TRG prefix first; fall back to keywords if no triggered sessions found
    df_check = fetch_ga4_revenue(start, end)
    prog_case = _TRG_PREFIX_CASE if _has_trg_sessions(df_check) else _KW_CASE
    df = _run(prog_case)
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_braze_email_weekly(start: date, end: date) -> pd.DataFrame:
    """Weekly email sends/opens/clicks by program (B&B vs Triggered)."""
    if YAML_CAMPAIGNS_DIR:
        return _fetch_braze_email_weekly_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(TIME)))::DATE AS week_start,
               CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
               COUNT(DISTINCT ID)      AS sends,

        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1, 2
    ),
    opens AS (
        SELECT week_start, program, COUNT(*) AS opens
        FROM (
            SELECT DISTINCT
                   DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(TIME)))::DATE AS week_start,
                   CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
                   DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1, 2
    ),
    clicks AS (
        SELECT week_start, program, COUNT(*) AS clicks
        FROM (
            SELECT DISTINCT
                   DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(TIME)))::DATE AS week_start,
                   CASE WHEN CANVAS_ID IS NULL OR CANVAS_ID = '' THEN 'B&B' ELSE 'Triggered' END AS program,
                   DISPATCH_ID, USER_ID
            FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {_bot_email_sql_filter()}
        )
        GROUP BY 1, 2
    )
    SELECT s.week_start, s.program, s.sends,
           COALESCE(o.opens,  0) AS opens,
           COALESCE(c.clicks, 0) AS clicks,
           COALESCE(o.opens,  0)::FLOAT / NULLIF(s.sends, 0) AS open_rate,
           COALESCE(c.clicks, 0)::FLOAT / NULLIF(s.sends, 0) AS ctr
    FROM sends s
    LEFT JOIN opens  o ON s.week_start = o.week_start AND s.program = o.program
    LEFT JOIN clicks c ON s.week_start = c.week_start AND s.program = c.program
    ORDER BY 1, 2
    """
    df = _norm(_df(_braze_client().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_braze_sms_weekly(start: date, end: date) -> pd.DataFrame:
    """Weekly SMS sends + clicks."""
    if not HAS_SMS:
        return pd.DataFrame()
    if YAML_CAMPAIGNS_DIR:
        return _fetch_braze_sms_weekly_yaml(start, end)
    q = f"""
    WITH sends AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(TIME)))::DATE AS week_start,
               COUNT(DISTINCT ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
        WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
        GROUP BY 1
    )
    SELECT s.week_start, s.sends
    FROM sends s
    ORDER BY 1
    """
    df = _norm(_df(_braze_client().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_canvas_step_map() -> pd.DataFrame:
    """Canvas step name → canvas name lookup from Braze sends. Cached 24 h."""
    q = f"""
    SELECT DISTINCT CANVAS_NAME,
                    LOWER(CANVAS_STEP_NAME) AS campaign_name
    FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
      AND CANVAS_ID IS NOT NULL AND CANVAS_ID != ''
      AND CANVAS_NAME IS NOT NULL AND CANVAS_STEP_NAME IS NOT NULL
    ORDER BY CANVAS_NAME
    """
    return _norm(_df(_braze_client().execute_query(q)))


def _ga4_canvas_case_sql() -> str:
    """Build CASE WHEN SQL from GA4_CANVAS_RULES for canvas group attribution."""
    if not GA4_CANVAS_RULES:
        return "NULL"
    cases = []
    for keywords, label in GA4_CANVAS_RULES:
        conds = " OR ".join(f"LOWER(SESSIONCAMPAIGNNAME) LIKE '%{kw}%'" for kw in keywords)
        cases.append(f"WHEN ({conds}) THEN '{label}'")
    return "CASE\n               " + "\n               ".join(cases) + "\n               ELSE NULL\n           END"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ga4_canvas_weekly(start: date, end: date) -> pd.DataFrame:
    """Weekly GA4 revenue/sessions/orders per canvas group (2-year window).

    Attribution uses keyword matching on SESSIONCAMPAIGNNAME → canvas group label,
    which is stable across canvas renames and works reliably for LY comparisons.
    """
    trg_filter = f"({_TRG_PREFIX_SQL}) OR ({_KW_SQL})"
    q = f"""
    SELECT DATE_TRUNC('week', TO_DATE(DATE, 'YYYYMMDD'))::DATE AS week_start,
           {_ga4_canvas_case_sql()} AS canvas_group,
           SUM(TOTALREVENUE)       AS revenue,
           SUM(SESSIONS)           AS sessions,
           SUM(ECOMMERCEPURCHASES) AS orders
    FROM {GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP = 'Email'
      AND ({trg_filter})
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _norm(_df(_ga4_client().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    # Drop rows that didn't match any known group
    if not df.empty and "CANVAS_GROUP" in df.columns:
        df = df[df["CANVAS_GROUP"].notna()].reset_index(drop=True)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_canvas_braze_weekly(start: date, end: date) -> pd.DataFrame:
    """Weekly Braze sends/opens/clicks per canvas name.

    Old canvas sends have CANVAS_NAME = NULL in the event rows — we fill those
    in by joining the most recent name from CHANGELOGS_CANVAS_SHARED.
    """
    if YAML_CAMPAIGNS_DIR:
        return pd.DataFrame()
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
            WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
        )
    ),
    sends AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(s.TIME)))::DATE AS week_start,
               COALESCE(s.CANVAS_NAME, cn.canvas_name) AS canvas_name,
               COUNT(DISTINCT s.ID) AS sends
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
        LEFT JOIN canvas_names cn ON s.CANVAS_ID = cn.CANVAS_ID
        WHERE s.APP_GROUP_ID = '{APP_GROUP_ID}'
          AND s.CANVAS_ID IS NOT NULL AND s.CANVAS_ID != ''
          AND COALESCE(s.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(s.TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1, 2
    ),
    opens AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(o.TIME)))::DATE AS week_start,
               COALESCE(o.CANVAS_NAME, cn.canvas_name) AS canvas_name,
               COUNT(DISTINCT o.USER_ID) AS opens
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED o
        LEFT JOIN canvas_names cn ON o.CANVAS_ID = cn.CANVAS_ID
        WHERE o.APP_GROUP_ID = '{APP_GROUP_ID}'

          AND o.CANVAS_ID IS NOT NULL AND o.CANVAS_ID != ''
          AND COALESCE(o.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(o.TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
        GROUP BY 1, 2
    ),
    clicks AS (
        SELECT DATE_TRUNC('week', TO_DATE(TO_TIMESTAMP(c.TIME)))::DATE AS week_start,
               COALESCE(c.CANVAS_NAME, cn.canvas_name) AS canvas_name,
               COUNT(DISTINCT c.USER_ID) AS clicks
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED c
        LEFT JOIN canvas_names cn ON c.CANVAS_ID = cn.CANVAS_ID
        WHERE c.APP_GROUP_ID = '{APP_GROUP_ID}'

          AND c.CANVAS_ID IS NOT NULL AND c.CANVAS_ID != ''
          AND COALESCE(c.CANVAS_NAME, cn.canvas_name) IS NOT NULL
          AND TO_DATE(TO_TIMESTAMP(c.TIME)) BETWEEN '{start}' AND '{end}'
          {_bot_email_sql_filter()}
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
    df = _norm(_df(_braze_client().execute_query(q)))
    if not df.empty and "WEEK_START" in df.columns:
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
    return df


# ── Campaign subject line lookup ──────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def load_campaign_subject_map() -> dict[str, str]:
    """BUR campaign name → subject line, loaded from YAML files. Cached 24 h."""
    campaigns_dir = Path(__file__).parent.parent / "campaigns"
    mapping: dict[str, str] = {}
    if not campaigns_dir.exists():
        return mapping
    for f in campaigns_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            if data.get("brand") != BRAND_CODE or data.get("channel") != "email":
                continue
            name  = data.get("name", "")
            sends = data.get("sends") or []
            if name and sends and isinstance(sends, list):
                subject = (sends[0] or {}).get("subject", "")
                if subject:
                    mapping[name] = subject
        except Exception:
            continue
    return mapping


# ── Forecast data fetchers ────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_finance_forecast(start: date, end: date) -> pd.DataFrame:
    """Daily total revenue forecast from finance upload table (FIVETRAN_DB)."""
    q = f"""
    SELECT DATE::DATE                  AS dt,
           {FINANCE_FORECAST_COL}      AS adjusted_revenue
    FROM FIVETRAN_DB.UPLOADS.ALL_COMPANY_DAILY_FORECAST
    WHERE DATE::DATE BETWEEN '{start}' AND '{end}'
    ORDER BY 1
    """
    try:
        df = _norm(_df(_fivetran_client().execute_query(q)))
    except Exception:
        return pd.DataFrame()
    if not df.empty and "DT" in df.columns:
        df["DT"] = pd.to_datetime(df["DT"]).dt.date
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_daily_lifecycle_actuals(start: date, end: date) -> pd.DataFrame:
    """Daily GA4 lifecycle revenue + sessions + orders (Email + SMS channels)."""
    q = f"""
    SELECT TO_DATE(DATE, 'YYYYMMDD') AS dt,
           SUM(TOTALREVENUE)         AS revenue,
           SUM(SESSIONS)             AS sessions,
           SUM(ECOMMERCEPURCHASES)   AS orders
    FROM {GA4_TABLE}
    WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    GROUP BY 1
    ORDER BY 1
    """
    df = _norm(_df(_ga4_client().execute_query(q)))
    if not df.empty and "DT" in df.columns:
        df["DT"] = pd.to_datetime(df["DT"]).dt.date
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_lifecycle_baseline() -> float:
    """Trailing 8-week daily average of total lifecycle revenue (Email + SMS GA4)."""
    end   = date.today() - timedelta(days=1)
    start = end - timedelta(weeks=8)
    q = f"""
    SELECT AVG(daily_rev) AS baseline
    FROM (
        SELECT TO_DATE(DATE, 'YYYYMMDD') AS dt,
               SUM(TOTALREVENUE)         AS daily_rev
        FROM {GA4_TABLE}
        WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
          AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
        GROUP BY 1
    )
    """
    try:
        rows = _ga4_client().execute_query(q)
        if rows and rows[0]:
            v = list(rows[0].values())[0]
            if v is not None:
                return float(v)
    except Exception:
        pass
    return 2500.0


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_lifecycle_share_trailing() -> Optional[float]:
    """Trailing 8-week lifecycle revenue as a fraction of total site revenue (from GA4)."""
    end   = date.today() - timedelta(days=1)
    start = end - timedelta(weeks=8)
    share = fetch_ga4_share(start, end)
    total = share.get("total_revenue", 0)
    lc    = share.get("lifecycle_revenue", 0)
    if total and lc:
        return lc / total
    return None


# ── GA4 lookup helper ─────────────────────────────────────────────────────────

def _ga4_vals(ga4_df: pd.DataFrame, channel: str, program: Optional[str] = None) -> dict:
    """Sum sessions/orders/revenue for a channel, with optional program filter + fallback."""
    if ga4_df is None or ga4_df.empty or "CHANNEL" not in ga4_df.columns:
        return {}
    sub = ga4_df[ga4_df["CHANNEL"] == channel]
    if program:
        p_sub = sub[sub["PROGRAM"] == program]
        if not p_sub.empty:
            sub = p_sub
    if sub.empty:
        return {}
    return {"SESSIONS": float(sub["SESSIONS"].sum()),
            "ORDERS":   float(sub["ORDERS"].sum()),
            "REVENUE":  float(sub["REVENUE"].sum())}


# ── Formatting ────────────────────────────────────────────────────────────────

def pct(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.1%}"


def num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def money(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:,.0f}"


def delta_pct(ty, ly):
    if ty is None or ly is None or ly == 0:
        return None
    return (ty - ly) / abs(ly)


def delta_label(ty, ly):
    d = delta_pct(ty, ly)
    if d is None:
        return None
    return f"{'+' if d >= 0 else ''}{d:.1%} vs LY"


# ── Metric grid ───────────────────────────────────────────────────────────────

_VAL_STYLE = "font-size:1.1rem;font-weight:600;line-height:1.2;margin:0"


def _pill(d, higher_is_better, is_rate):
    """Colored pill badge HTML for a delta value."""
    if d is None:
        return ""
    if is_rate:
        effective = d if higher_is_better else -d
        if effective > 0.05:
            bg, fg = "#d4edda", "#155724"
        elif effective >= -0.05:
            bg, fg = "#fff3cd", "#7d4e00"
        else:
            bg, fg = "#f8d7da", "#721c24"
    else:
        good = (d >= 0) == higher_is_better
        bg, fg = ("#d4edda", "#155724") if good else ("#f8d7da", "#721c24")
    arrow = "▲" if d >= 0 else "▼"
    sign  = "+" if d >= 0 else ""
    return (
        f'<span style="display:inline-block;margin-top:4px;padding:2px 8px;'
        f'border-radius:12px;background:{bg};color:{fg};font-size:0.78rem;font-weight:600">'
        f'{arrow} {sign}{d:.1%} vs LY</span>'
    )


def _cell_html(value_str, badge=""):
    return (
        f'<div style="padding:0.3rem 0">'
        f'<div style="{_VAL_STYLE}">{value_str}</div>'
        f'{"<div>" + badge + "</div>" if badge else ""}'
        f'</div>'
    )


def make_row(label, ty_val, ly_val, fmt_fn, higher_is_better=True, is_rate=False):
    d = delta_pct(ty_val, ly_val)
    ty_str = fmt_fn(ty_val) if ty_val is not None else "—"
    ly_str = fmt_fn(ly_val) if ly_val is not None else "—"
    return {
        "label":            label,
        "ty_html":          _cell_html(ty_str, _pill(d, higher_is_better, is_rate)),
        "ly_html":          _cell_html(ly_str),
    }


def render_metric_grid(rows: list[dict]):
    h1, h2, h3 = st.columns([1.4, 1, 1])
    h1.markdown("**Metric**"); h2.markdown("**Last Year**"); h3.markdown("**This Period**")
    st.divider()
    for row in rows:
        c1, c2, c3 = st.columns([1.4, 1, 1])
        c1.markdown(f"**{row['label']}**")
        c2.markdown(row["ly_html"], unsafe_allow_html=True)
        c3.markdown(row["ty_html"], unsafe_allow_html=True)


# ── Trend chart ───────────────────────────────────────────────────────────────

def trend_chart(periods: list[Period], values: list, label: str, fmt_fn, key: str = "", title: str = ""):
    labels = [p.label for p in periods]
    clean  = [v if v is not None and not (isinstance(v, float) and pd.isna(v)) else None
              for v in values]
    if title:
        st.caption(title)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=clean, mode="lines+markers",
                             line=dict(color=ACCENT, width=2),
                             marker=dict(size=6, color=ACCENT),
                             hovertemplate=f"%{{x}}<br>{label}: %{{y}}<extra></extra>"))
    if clean and clean[-1] is not None:
        fig.add_trace(go.Scatter(x=[labels[-1]], y=[clean[-1]], mode="markers",
                                 marker=dict(size=10, color=ACCENT,
                                             line=dict(width=2, color="white")),
                                 showlegend=False, hoverinfo="skip"))
    fig.update_layout(height=160, margin=dict(l=10, r=10, t=10, b=10),
                      showlegend=False,
                      xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                      yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=10)),
                      plot_bgcolor="white", paper_bgcolor="white")
    if any(k in label for k in ("%", "Rate", "CTR", "CTO")):
        fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True, key=key or label,
                    config={"displayModeBar": False})


# ── YOY chart ─────────────────────────────────────────────────────────────────

def render_yoy_charts():
    today     = date.today()
    yoy_end   = today - timedelta(days=1)
    yoy_start = yoy_end - timedelta(weeks=104)
    df = fetch_ga4_weekly_series(yoy_start, yoy_end)
    if df.empty:
        st.caption("No GA4 data available for YOY chart.")
        return

    cutoff = today - timedelta(weeks=52)
    ty = df[df["WEEK_START"] >= cutoff].copy()
    ly = df[df["WEEK_START"] <  cutoff].copy()
    ly["WEEK_START"] = ly["WEEK_START"].apply(lambda d: d + timedelta(weeks=52))

    merged = ty.merge(ly, on="WEEK_START", how="outer", suffixes=("_TY", "_LY"))
    merged = merged.sort_values("WEEK_START")
    labels    = [w.strftime("%-d %b '%y") for w in merged["WEEK_START"]]
    ly_labels = [(w - timedelta(weeks=52)).strftime("%-d %b '%y") for w in merged["WEEK_START"]]

    def _chart(col_ty, col_ly, title):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels, y=merged.get(col_ly, pd.Series(dtype=float)).tolist(),
            name="LY", mode="lines",
            line=dict(color=MUTED, width=1.5, dash="dot"),
            customdata=ly_labels,
            hovertemplate="%{customdata}<br>LY: %{y}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=labels, y=merged.get(col_ty, pd.Series(dtype=float)).tolist(),
            name="TY", mode="lines+markers",
            line=dict(color=ACCENT, width=2),
            marker=dict(size=4, color=ACCENT),
            hovertemplate="%{x}<br>TY: %{y}<extra></extra>"))
        fig.update_layout(
            title=dict(text=title, font=dict(size=13)),
            height=240, margin=dict(l=10, r=10, t=35, b=10),
            legend=dict(orientation="h", y=1.18, x=1, xanchor="right", font=dict(size=10)),
            xaxis=dict(showgrid=False, tickfont=dict(size=9),
                       tickmode="array",
                       tickvals=labels[::4], ticktext=labels[::4]),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9)),
            plot_bgcolor="white", paper_bgcolor="white")
        return fig

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(_chart("REVENUE_TY", "REVENUE_LY", "Revenue — TY vs LY"),
                        use_container_width=True, key="yoy_revenue",
                        config={"displayModeBar": False})
    with c2:
        st.plotly_chart(_chart("SESSIONS_TY", "SESSIONS_LY", "Sessions — TY vs LY"),
                        use_container_width=True, key="yoy_sessions",
                        config={"displayModeBar": False})


# ── YOY explore ───────────────────────────────────────────────────────────────

def render_yoy_explore():
    today     = date.today()
    yoy_end   = today - timedelta(days=1)
    yoy_start = yoy_end - timedelta(weeks=104)

    ga4_w   = fetch_ga4_weekly_detail(yoy_start, yoy_end)
    email_w = fetch_braze_email_weekly(yoy_start, yoy_end)
    sms_w   = fetch_braze_sms_weekly(yoy_start, yoy_end)

    sel_col, met_col = st.columns([1, 3])
    with sel_col:
        channel = st.radio("Channel", ["All Lifecycle", "B&B", "Triggers", "SMS"],
                           key="yoy_ex_channel")
    with met_col:
        # Open Rate and CTR are email-only; hide both for SMS
        avail = (["Revenue", "AOV", "Sessions", "Orders", "Sends"]
                 if channel == "SMS"
                 else ["Revenue", "AOV", "Sessions", "Orders", "Sends", "Open Rate", "CTR"])
        metric = st.radio("Metric", avail, horizontal=True, key="yoy_ex_metric")

    if channel == "All Lifecycle" and metric == "Open Rate":
        st.caption("Open Rate shown for email only (B&B + Triggers); SMS has no open tracking.")

    # ── Build VALUE series ────────────────────────────────────────────────────

    def _ga4(ch_filter, prog=None, col=None):
        sub = ga4_w[ga4_w["CHANNEL"] == ch_filter]
        if prog:
            sub = sub[sub["PROGRAM"] == prog]
        col = col or {"Revenue": "REVENUE", "Sessions": "SESSIONS",
                      "Orders": "ORDERS", "AOV": "REVENUE"}[metric]
        return sub.groupby("WEEK_START")[col].sum().reset_index().rename(columns={col: "VALUE"})

    def _ga4_aov(ch_filter, prog=None):
        rev = _ga4(ch_filter, prog, col="REVENUE")
        ord_ = _ga4(ch_filter, prog, col="ORDERS")
        m = rev.merge(ord_, on="WEEK_START", suffixes=("_R", "_O"))
        m["VALUE"] = m["VALUE_R"] / m["VALUE_O"].replace(0, float("nan"))
        return m[["WEEK_START", "VALUE"]]

    def _email(prog=None):
        sub = email_w if prog is None else email_w[email_w["PROGRAM"] == prog]
        if metric == "Sends":
            g = sub.groupby("WEEK_START")["SENDS"].sum().reset_index()
            return g.rename(columns={"SENDS": "VALUE"})
        g = sub.groupby("WEEK_START").agg(s=("SENDS", "sum"),
                                          n=("OPENS" if metric == "Open Rate" else "CLICKS", "sum")
                                          ).reset_index()
        g["VALUE"] = g["n"] / g["s"].replace(0, float("nan"))
        return g[["WEEK_START", "VALUE"]]

    def _combine_weeks(a, b):
        """Sum two VALUE series by week."""
        m = a.merge(b, on="WEEK_START", how="outer", suffixes=("_A", "_B"))
        m["VALUE"] = m["VALUE_A"].fillna(0) + m["VALUE_B"].fillna(0)
        return m[["WEEK_START", "VALUE"]]

    if metric == "AOV":
        prog = None if channel in ("All Lifecycle", "SMS") else ("B&B" if channel == "B&B" else "Triggered")
        ch_f = "SMS" if channel == "SMS" else "Email"
        if channel == "All Lifecycle":
            rev = _combine_weeks(_ga4("Email", col="REVENUE"), _ga4("SMS", col="REVENUE"))
            ord_ = _combine_weeks(_ga4("Email", col="ORDERS"), _ga4("SMS", col="ORDERS"))
            m = rev.merge(ord_, on="WEEK_START", suffixes=("_R", "_O"))
            m["VALUE"] = m["VALUE_R"] / m["VALUE_O"].replace(0, float("nan"))
            series = m[["WEEK_START", "VALUE"]]
        else:
            series = _ga4_aov(ch_f, prog)
    elif metric in ("Revenue", "Sessions", "Orders"):
        if channel == "All Lifecycle":
            series = _combine_weeks(_ga4("Email"), _ga4("SMS"))
        elif channel == "SMS":
            series = _ga4("SMS")
        else:
            prog = "B&B" if channel == "B&B" else "Triggered"
            series = _ga4("Email", prog)
    elif metric == "Sends":
        sms_sends = sms_w[["WEEK_START", "SENDS"]].rename(columns={"SENDS": "VALUE"})
        if channel == "All Lifecycle":
            series = _combine_weeks(_email(), sms_sends)
        elif channel == "SMS":
            series = sms_sends
        else:
            series = _email("B&B" if channel == "B&B" else "Triggered")
    elif metric == "Open Rate":
        # Email only regardless of channel selection (SMS has no opens)
        series = _email(None if channel == "All Lifecycle"
                        else "B&B" if channel == "B&B" else "Triggered")
    else:  # CTR (email only — SMS has no click tracking)
        if channel == "All Lifecycle":
            series = _email()
        else:
            series = _email("B&B" if channel == "B&B" else "Triggered")

    series = series.copy()
    series["WEEK_START"] = pd.to_datetime(series["WEEK_START"]).dt.date

    # ── TY / LY split ─────────────────────────────────────────────────────────

    cutoff    = today - timedelta(weeks=52)
    ty        = series[series["WEEK_START"] >= cutoff].copy()
    ly        = series[series["WEEK_START"] <  cutoff].copy()
    ly["WEEK_START"] = [d + timedelta(weeks=52) for d in ly["WEEK_START"]]

    merged    = ty.merge(ly, on="WEEK_START", how="outer", suffixes=("_TY", "_LY"))
    merged    = merged.sort_values("WEEK_START")
    labels    = [w.strftime("%-d %b '%y") for w in merged["WEEK_START"]]
    ly_labels = [(w - timedelta(weeks=52)).strftime("%-d %b '%y") for w in merged["WEEK_START"]]

    is_pct  = metric in ("Open Rate", "CTR")
    is_money = metric in ("Revenue", "AOV")
    hover_fmt = ".1%" if is_pct else ("$,.0f" if is_money else ",.0f")
    tick_fmt  = ".1%" if is_pct else ("$,.0f" if is_money else ",.0f")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=merged.get("VALUE_LY", pd.Series(dtype=float)).tolist(),
        name="LY", mode="lines",
        line=dict(color=MUTED, width=1.5, dash="dot"),
        customdata=ly_labels,
        hovertemplate=f"%{{customdata}}<br>LY: %{{y:{hover_fmt}}}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=labels, y=merged.get("VALUE_TY", pd.Series(dtype=float)).tolist(),
        name="TY", mode="lines+markers",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=4, color=ACCENT),
        hovertemplate=f"%{{x}}<br>TY: %{{y:{hover_fmt}}}<extra></extra>"))
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=15, b=10),
        legend=dict(orientation="h", y=1.1, x=1, xanchor="right", font=dict(size=10)),
        xaxis=dict(showgrid=False, tickfont=dict(size=9),
                   tickmode="array", tickvals=labels[::4], ticktext=labels[::4]),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9),
                   tickformat=tick_fmt),
        plot_bgcolor="white", paper_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                    key=f"yoy_ex_{channel}_{metric}")


# ── Canvas YOY ────────────────────────────────────────────────────────────────

_CANVAS_GA4_METRICS   = ["Revenue", "AOV", "Sessions", "Orders"]
_CANVAS_BRAZE_METRICS = ["Sends", "Open Rate", "CTR"]
_ALL_CANVAS_METRICS   = _CANVAS_GA4_METRICS + _CANVAS_BRAZE_METRICS


def _group_canvas(name: str) -> str:
    """Map a raw canvas name to its display group label."""
    n = name.lower()
    for keywords, label in CANVAS_GROUP_RULES:
        if any(kw in n for kw in keywords):
            return name if label is None else label
    return name


def _canvas_ty_ly_chart(series: pd.DataFrame, title: str,
                         fmt: str, key: str,
                         overlay: Optional[pd.DataFrame] = None,
                         overlay_label: str = "", overlay_fmt: str = ",.0f"):
    """TY vs LY line chart. overlay adds a second metric on a right y-axis.
    Renders an empty chart when series has no rows (data not yet available)."""
    if series.empty and (overlay is None or overlay.empty):
        fig = go.Figure()
        fig.update_layout(
            height=300, margin=dict(l=10, r=10, t=15, b=10),
            xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
            plot_bgcolor="white", paper_bgcolor="white",
            annotations=[dict(text="No data yet", x=0.5, y=0.5, xref="paper",
                               yref="paper", showarrow=False,
                               font=dict(size=13, color="#cccccc"))])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=key)
        return
    today  = date.today()
    cutoff = today - timedelta(weeks=52)

    def _split_merge(df: pd.DataFrame):
        df = df.copy()
        df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
        ty = df[df["WEEK_START"] >= cutoff]
        ly = df[df["WEEK_START"] <  cutoff].copy()
        ly["WEEK_START"] = [d + timedelta(weeks=52) for d in ly["WEEK_START"]]
        return ty.merge(ly, on="WEEK_START", how="outer", suffixes=("_TY", "_LY")).sort_values("WEEK_START")

    m  = _split_merge(series)
    om = _split_merge(overlay) if overlay is not None and not overlay.empty else None

    # Build a single unified, chronologically-sorted axis so all traces share the
    # same categorical positions (prevents Plotly from reordering and drawing the
    # "two lines" artifact when primary and overlay have different week coverage).
    all_weeks = sorted(set(m["WEEK_START"]) | (set(om["WEEK_START"]) if om is not None else set()))
    all_labels    = [w.strftime("%-d %b '%y") for w in all_weeks]
    all_ly_labels = [(w - timedelta(weeks=52)).strftime("%-d %b '%y") for w in all_weeks]
    week_to_label    = {w: l for w, l in zip(all_weeks, all_labels)}
    week_to_ly_label = {w: l for w, l in zip(all_weeks, all_ly_labels)}

    def _align(df_merged, col):
        """Map a merged TY/LY df onto the unified week axis, NaN for missing weeks."""
        lookup = dict(zip(df_merged["WEEK_START"], df_merged[col]))
        return [lookup.get(w, float("nan")) for w in all_weeks]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=all_labels, y=_align(m, "VALUE_LY"),
        name=f"LY {title}", mode="lines",
        line=dict(color=MUTED, width=1.5, dash="dot"),
        customdata=all_ly_labels,
        hovertemplate=f"%{{customdata}}<br>LY {title}: %{{y:{fmt}}}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=all_labels, y=_align(m, "VALUE_TY"),
        name=f"TY {title}", mode="lines+markers",
        line=dict(color=ACCENT, width=2), marker=dict(size=4, color=ACCENT),
        hovertemplate=f"%{{x}}<br>TY {title}: %{{y:{fmt}}}<extra></extra>"))

    layout_kw = {}
    if om is not None:
        OVERLAY_COLOR = "#7b61ff"
        fig.add_trace(go.Scatter(
            x=all_labels, y=_align(om, "VALUE_LY"),
            name=f"LY {overlay_label}", mode="lines", yaxis="y2",
            line=dict(color=OVERLAY_COLOR, width=1.5, dash="dot"),
            customdata=all_ly_labels,
            hovertemplate=f"%{{customdata}}<br>LY {overlay_label}: %{{y:{overlay_fmt}}}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=all_labels, y=_align(om, "VALUE_TY"),
            name=f"TY {overlay_label}", mode="lines+markers", yaxis="y2",
            line=dict(color=OVERLAY_COLOR, width=2), marker=dict(size=4, color=OVERLAY_COLOR),
            hovertemplate=f"%{{x}}<br>TY {overlay_label}: %{{y:{overlay_fmt}}}<extra></extra>"))
        layout_kw["yaxis2"] = dict(overlaying="y", side="right",
                                    showgrid=False, tickfont=dict(size=9),
                                    tickformat=overlay_fmt)

    tick_step = max(1, len(all_labels) // 13)
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=15, b=10),
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right", font=dict(size=10)),
        xaxis=dict(showgrid=False, tickfont=dict(size=9),
                   categoryorder="array", categoryarray=all_labels,
                   tickmode="array",
                   tickvals=all_labels[::tick_step],
                   ticktext=all_labels[::tick_step]),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9),
                   tickformat=fmt),
        plot_bgcolor="white", paper_bgcolor="white",
        **layout_kw)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=key)


def render_canvas_yoy():
    today     = date.today()
    yoy_end   = today - timedelta(days=1)
    yoy_start = yoy_end - timedelta(weeks=104)

    ga4_weekly   = fetch_ga4_canvas_weekly(yoy_start, yoy_end)
    braze_weekly = fetch_canvas_braze_weekly(yoy_start, yoy_end)

    if braze_weekly.empty:
        st.caption("No canvas send data available.")
        return

    # ── Build group mapping (from Braze canvas names) ─────────────────────────
    raw_canvases = sorted(braze_weekly["CANVAS_NAME"].dropna().unique())
    group_map    = {c: _group_canvas(c) for c in raw_canvases}
    _std_groups  = [label for _, label in CANVAS_GROUP_RULES if label is not None]
    groups = (
        [g for g in _std_groups if g in group_map.values()]
        + sorted(g for g in set(group_map.values()) if g not in _std_groups)
    )
    raw_for = {g: [c for c, v in group_map.items() if v == g] for g in groups}

    # GA4 data is already keyed by canvas_group — only available for std groups
    ga4_groups = set(ga4_weekly["CANVAS_GROUP"].dropna().unique()) if not ga4_weekly.empty else set()

    # ── Controls ──────────────────────────────────────────────────────────────
    cv_col, m1_col, m2_col = st.columns([2, 1, 1])
    with cv_col:
        group = st.selectbox("Canvas group", groups, key="canvas_yoy_select")
        members = raw_for[group]
        if len(members) > 1:
            st.caption(f"Combines: {', '.join(sorted(members))}")
    with m1_col:
        metric = st.radio("Primary metric", _ALL_CANVAS_METRICS,
                          horizontal=False, key="canvas_yoy_metric")
    with m2_col:
        overlay_opts = ["None"] + [m for m in _ALL_CANVAS_METRICS if m != metric]
        overlay_metric = st.radio("Overlay metric", overlay_opts,
                                  horizontal=False, key="canvas_yoy_overlay")

    # ── Build series for selected group ───────────────────────────────────────
    def _ga4_series(col):
        if ga4_weekly.empty or group not in ga4_groups:
            return pd.DataFrame(columns=["WEEK_START", "VALUE"])
        sub = ga4_weekly[ga4_weekly["CANVAS_GROUP"] == group]
        agg = sub.groupby("WEEK_START")[col].sum().reset_index()
        return agg.rename(columns={col: "VALUE"})

    def _braze_series(col):
        sub = braze_weekly[braze_weekly["CANVAS_NAME"].isin(members)]
        if col == "OPEN_RATE":
            agg = sub.groupby("WEEK_START").agg(
                OPENS=("OPENS", "sum"), SENDS=("SENDS", "sum")
            ).reset_index()
            agg["VALUE"] = agg["OPENS"] / agg["SENDS"].replace(0, float("nan"))
            return agg[["WEEK_START", "VALUE"]]
        if col == "CTR":
            agg = sub.groupby("WEEK_START").agg(
                CLICKS=("CLICKS", "sum"), SENDS=("SENDS", "sum")
            ).reset_index()
            agg["VALUE"] = agg["CLICKS"] / agg["SENDS"].replace(0, float("nan"))
            return agg[["WEEK_START", "VALUE"]]
        agg = sub.groupby("WEEK_START")[col].sum().reset_index()
        return agg.rename(columns={col: "VALUE"})

    def _series_for(m):
        if m == "AOV":
            rev  = _ga4_series("REVENUE")
            ord_ = _ga4_series("ORDERS")
            if rev.empty or ord_.empty:
                return pd.DataFrame(columns=["WEEK_START", "VALUE"])
            mg = rev.merge(ord_, on="WEEK_START", suffixes=("_R", "_O"))
            mg["VALUE"] = mg["VALUE_R"] / mg["VALUE_O"].replace(0, float("nan"))
            return mg[["WEEK_START", "VALUE"]]
        _col = {"Revenue": "REVENUE", "Sessions": "SESSIONS", "Orders": "ORDERS",
                "Sends": "SENDS", "Open Rate": "OPEN_RATE", "CTR": "CTR"}
        if m in _CANVAS_GA4_METRICS:
            return _ga4_series(_col[m])
        return _braze_series(_col[m])

    def _fmt_for(m):
        if m in ("Revenue", "AOV"): return "$,.0f"
        if m in ("Open Rate", "CTR"): return ".1%"
        return ",.0f"

    series  = _series_for(metric)
    overlay = _series_for(overlay_metric) if overlay_metric != "None" else None

    _canvas_ty_ly_chart(
        series, metric, _fmt_for(metric),
        key=f"canvas_yoy_{group}_{metric}_{overlay_metric}",
        overlay=overlay,
        overlay_label=overlay_metric if overlay_metric != "None" else "",
        overlay_fmt=_fmt_for(overlay_metric) if overlay_metric != "None" else ",.0f",
    )


# ── Detail table helpers ──────────────────────────────────────────────────────

# col_map entry: (src_col, display_name, type)
# types: 'text' | 'int' | 'pct' | 'money'
_EMAIL_DETAIL_MAP = [
    ("CAMPAIGN_NAME",    "Campaign",   "text"),
    ("CANVAS_STEP_NAME", "Step",       "text"),
    ("SUBJECT",          "Subject",    "text"),
    ("SENDS",            "Sends",      "int"),
    ("UNIQUE_OPENS",     "Opens",      "int"),
    ("OPEN_RATE",        "Open Rate",  "pct"),
    ("UNIQUE_CLICKS",    "Clicks",     "int"),
    ("CTR",              "CTR",        "pct"),
    ("CTO",              "CTO",        "pct"),
    ("GA4_SESSIONS",     "Sessions",   "int"),
    ("GA4_ORDERS",       "Orders",     "int"),
    ("GA4_REVENUE",      "Revenue",    "money"),
    ("CONV_RATE",        "Conv Rate",  "pct"),
    ("DPM",              "$/M Sent",   "money"),
]

_SMS_DETAIL_MAP = [
    ("NAME",             "Campaign",  "text"),
    ("SENDS",            "Sends",         "int"),
    ("GA4_SESSIONS",     "Sessions",      "int"),
    ("GA4_ORDERS",       "Orders",        "int"),
    ("GA4_REVENUE",      "Revenue",       "money"),
    ("CONV_RATE",        "Conv Rate",     "pct"),
    ("DPM",              "$/M Sent",      "money"),
]


def _prepare_detail_df(df: pd.DataFrame, col_map: list):
    """Return (display_df with raw numerics, column_config dict) for st.dataframe."""
    out = {}
    cfg = {}
    for src, display, kind in col_map:
        if src not in df.columns:
            continue
        raw = df[src]
        if kind == "text":
            out[display] = raw.where(raw.notna(), "—")
            cfg[display] = st.column_config.TextColumn(display)
        elif kind == "int":
            out[display] = pd.to_numeric(raw, errors="coerce")
            cfg[display] = st.column_config.NumberColumn(display, format="%.0f")
        elif kind == "pct":
            # multiply to 0-100 so sort is correct; format string adds %
            out[display] = pd.to_numeric(raw, errors="coerce") * 100
            cfg[display] = st.column_config.NumberColumn(display, format="%.1f%%")
        elif kind == "money":
            out[display] = pd.to_numeric(raw, errors="coerce")
            cfg[display] = st.column_config.NumberColumn(display, format="$%.0f")
    return pd.DataFrame(out), cfg


def _add_derived(df: pd.DataFrame, sends_col: str) -> pd.DataFrame:
    df = df.copy()
    df["CONV_RATE"] = df.apply(
        lambda r: r["GA4_ORDERS"] / r["GA4_SESSIONS"]
        if pd.notna(r.get("GA4_SESSIONS")) and r.get("GA4_SESSIONS", 0) > 0 else None, axis=1)
    df["DPM"] = df.apply(
        lambda r: r["GA4_REVENUE"] / r[sends_col] * 1000
        if pd.notna(r.get("GA4_REVENUE")) and r.get(sends_col, 0) > 0 else None, axis=1)
    return df


def _render_bb_detail_table(df: pd.DataFrame, ga4_df: pd.DataFrame):
    ga4_bb = ga4_df[
        (ga4_df["CHANNEL"] == "Email") &
        (~_classify_triggered(ga4_df["CAMPAIGN_NAME"]))
    ][["CAMPAIGN_NAME", "SESSIONS", "ORDERS", "REVENUE"]].rename(
        columns={"SESSIONS": "GA4_SESSIONS", "ORDERS": "GA4_ORDERS", "REVENUE": "GA4_REVENUE"})

    if df.empty:
        merged = ga4_bb.assign(SENDS=0, UNIQUE_OPENS=0, UNIQUE_CLICKS=0,
                               OPEN_RATE=None, CTR=None, CTO=None)
    else:
        merged = df.merge(ga4_bb, on="CAMPAIGN_NAME", how="outer")
        for col in ["SENDS", "UNIQUE_OPENS", "UNIQUE_CLICKS"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)
        merged["OPEN_RATE"] = merged.apply(
            lambda r: r["UNIQUE_OPENS"] / r["SENDS"] if r["SENDS"] > 0 else None, axis=1)
        merged["CTR"] = merged.apply(
            lambda r: r["UNIQUE_CLICKS"] / r["SENDS"] if r["SENDS"] > 0 else None, axis=1)
        merged["CTO"] = merged.apply(
            lambda r: r["UNIQUE_CLICKS"] / r["UNIQUE_OPENS"] if r["UNIQUE_OPENS"] > 0 else None, axis=1)

    subject_map = load_campaign_subject_map()
    merged["SUBJECT"] = merged["CAMPAIGN_NAME"].map(subject_map)
    merged = _add_derived(merged, "SENDS")
    merged = merged.sort_values(["SENDS", "GA4_REVENUE"], ascending=[False, False], na_position="last")
    _ddf, _cfg = _prepare_detail_df(merged, _EMAIL_DETAIL_MAP)
    st.dataframe(_ddf, hide_index=True, use_container_width=True, column_config=_cfg)


def _canvas_total_row(merged: pd.DataFrame) -> pd.DataFrame:
    t_s = merged["SENDS"].sum()
    t_o = merged["UNIQUE_OPENS"].sum()
    t_c = merged["UNIQUE_CLICKS"].sum()
    t_sess = merged["GA4_SESSIONS"].sum() if "GA4_SESSIONS" in merged else 0
    t_ord  = merged["GA4_ORDERS"].sum()   if "GA4_ORDERS"   in merged else 0
    t_rev  = merged["GA4_REVENUE"].sum()  if "GA4_REVENUE"  in merged else 0
    return pd.DataFrame([{
        "CANVAS_STEP_NAME": "— Canvas Total —",
        "SENDS": t_s, "UNIQUE_OPENS": t_o, "UNIQUE_CLICKS": t_c,
        "OPEN_RATE": t_o / t_s if t_s else None,
        "CTR":  t_c / t_s if t_s else None,
        "CTO":  t_c / t_o if t_o else None,
        "GA4_SESSIONS": t_sess or None, "GA4_ORDERS": t_ord or None,
        "GA4_REVENUE":  t_rev  or None,
        "CONV_RATE": t_ord / t_sess if t_sess else None,
        "DPM":  t_rev / t_s * 1000 if t_s else None,
    }])


def _touchpoint_sort_key(names: pd.Series) -> pd.Series:
    """Extract the T-number (T1, T2, …) from canvas step names for ordering.
    Steps without a _T<n>_ token sort last (large sentinel)."""
    nums = names.astype(str).str.extract(r"_[Tt](\d+)(?:_|$)", expand=False)
    return pd.to_numeric(nums, errors="coerce").fillna(10**6)


def _render_trigger_detail_table(df: pd.DataFrame, ga4_df: pd.DataFrame):
    ga4_trg = ga4_df[
        (ga4_df["CHANNEL"] == "Email") &
        (_classify_triggered(ga4_df["CAMPAIGN_NAME"]))
    ][["CAMPAIGN_NAME", "SESSIONS", "ORDERS", "REVENUE"]].rename(
        columns={"CAMPAIGN_NAME": "CANVAS_STEP_NAME",
                 "SESSIONS": "GA4_SESSIONS", "ORDERS": "GA4_ORDERS", "REVENUE": "GA4_REVENUE"})

    matched: set[str] = set()

    for canvas in df["CANVAS_NAME"].dropna().unique():
        st.markdown(f"**{canvas}**")
        sub = df[df["CANVAS_NAME"] == canvas].copy()
        sub = sub.sort_values(
            by="CANVAS_STEP_NAME", key=_touchpoint_sort_key, kind="stable")
        merged = sub.merge(ga4_trg, on="CANVAS_STEP_NAME", how="left")
        for col in ["SENDS", "UNIQUE_OPENS", "UNIQUE_CLICKS"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)
        merged["OPEN_RATE"] = merged.apply(
            lambda r: r["UNIQUE_OPENS"] / r["SENDS"] if r["SENDS"] > 0 else None, axis=1)
        merged["CTR"] = merged.apply(
            lambda r: r["UNIQUE_CLICKS"] / r["SENDS"] if r["SENDS"] > 0 else None, axis=1)
        merged["CTO"] = merged.apply(
            lambda r: r["UNIQUE_CLICKS"] / r["UNIQUE_OPENS"] if r["UNIQUE_OPENS"] > 0 else None, axis=1)
        merged = _add_derived(merged, "SENDS")
        matched |= set(merged["CANVAS_STEP_NAME"].dropna())
        merged = pd.concat([merged, _canvas_total_row(merged)], ignore_index=True)
        _ddf, _cfg = _prepare_detail_df(merged, _EMAIL_DETAIL_MAP)
        st.dataframe(_ddf, hide_index=True, use_container_width=True, column_config=_cfg)

    unmatched = ga4_trg[~ga4_trg["CANVAS_STEP_NAME"].isin(matched)]
    if not unmatched.empty:
        st.markdown("**Other Triggered Traffic**")
        unmatched = unmatched.assign(
            SENDS=0, UNIQUE_OPENS=0, UNIQUE_CLICKS=0,
            OPEN_RATE=None, CTR=None, CTO=None,
            CONV_RATE=unmatched.apply(
                lambda r: r["GA4_ORDERS"] / r["GA4_SESSIONS"]
                if r.get("GA4_SESSIONS", 0) > 0 else None, axis=1),
            DPM=None)
        _ddf, _cfg = _prepare_detail_df(unmatched, _EMAIL_DETAIL_MAP)
        st.dataframe(_ddf, hide_index=True, use_container_width=True, column_config=_cfg)


def _sms_canvas_total(sub: pd.DataFrame) -> pd.DataFrame:
    t_s    = sub["SENDS"].sum()
    t_sess = sub["GA4_SESSIONS"].sum() if "GA4_SESSIONS" in sub else 0
    t_ord  = sub["GA4_ORDERS"].sum()   if "GA4_ORDERS"   in sub else 0
    t_rev  = sub["GA4_REVENUE"].sum()  if "GA4_REVENUE"  in sub else 0
    return pd.DataFrame([{
        "CANVAS_STEP_NAME": "— Canvas Total —",
        "SENDS": t_s,
        "GA4_SESSIONS": t_sess or None, "GA4_ORDERS": t_ord or None,
        "GA4_REVENUE":  t_rev  or None,
        "CONV_RATE": t_ord / t_sess if t_sess else None,
        "DPM": t_rev / t_s * 1000 if t_s else None,
    }])


def _render_sms_triggered_canvases(df: pd.DataFrame, ga4_df: pd.DataFrame):
    triggered = df[df["CANVAS_NAME"].notna()].copy()
    if triggered.empty:
        return
    ga4_keyed = ga4_df[ga4_df["CHANNEL"] == "SMS"][
        ["CAMPAIGN_NAME", "SESSIONS", "ORDERS", "REVENUE"]
    ].rename(columns={"CAMPAIGN_NAME": "CANVAS_STEP_NAME",
                      "SESSIONS": "GA4_SESSIONS", "ORDERS": "GA4_ORDERS",
                      "REVENUE": "GA4_REVENUE"})
    for canvas in triggered["CANVAS_NAME"].dropna().unique():
        st.markdown(f"**{canvas}** *(SMS)*")
        sub = triggered[triggered["CANVAS_NAME"] == canvas].copy()
        sub = sub.sort_values(
            by="CANVAS_STEP_NAME", key=_touchpoint_sort_key, kind="stable")
        sub = sub.merge(ga4_keyed, on="CANVAS_STEP_NAME", how="left")
        sub = _add_derived(sub, "SENDS")
        sub = pd.concat([sub, _sms_canvas_total(sub)], ignore_index=True)
        sub["NAME"] = sub.get("CANVAS_STEP_NAME", pd.Series(dtype=str))
        _ddf, _cfg = _prepare_detail_df(sub, _SMS_DETAIL_MAP)
        st.dataframe(_ddf, hide_index=True, use_container_width=True, column_config=_cfg)


def _render_sms_detail_table(df: pd.DataFrame, ga4_df: pd.DataFrame):
    batch = df[df["CANVAS_NAME"].isna() & df["CAMPAIGN_NAME"].notna()].copy()
    if not batch.empty:
        ga4 = ga4_df[ga4_df["CHANNEL"] == "SMS"][
            ["CAMPAIGN_NAME", "SESSIONS", "ORDERS", "REVENUE"]
        ].rename(columns={"SESSIONS": "GA4_SESSIONS", "ORDERS": "GA4_ORDERS",
                          "REVENUE": "GA4_REVENUE"})
        merged = batch.merge(ga4, on="CAMPAIGN_NAME", how="left")
        merged = _add_derived(merged, "SENDS")
        merged["NAME"] = merged["CAMPAIGN_NAME"]
        _ddf, _cfg = _prepare_detail_df(merged, _SMS_DETAIL_MAP)
        st.dataframe(_ddf, hide_index=True, use_container_width=True, column_config=_cfg)


# ── Section renderers ─────────────────────────────────────────────────────────

def render_email_section(title: str, program: str,
                         ty_email: pd.DataFrame, ly_email: pd.DataFrame,
                         ty_ga4: pd.DataFrame,   ly_ga4: pd.DataFrame,
                         ty_period: Period, t_periods: list[Period],
                         ty_swatches: Optional[pd.DataFrame] = None,
                         ly_swatches: Optional[pd.DataFrame] = None):
    st.subheader(title)

    def e(df, col):
        sub = df[df["PROGRAM"] == program] if not df.empty and "PROGRAM" in df.columns else df
        if sub.empty:
            return None
        try:
            v = sub.iloc[0][col]
            return None if pd.isna(v) else float(v)
        except (TypeError, ValueError):
            return None

    ty   = {c: e(ty_email, c) for c in ["SENDS","UNIQUE_OPENS","UNIQUE_CLICKS","OPEN_RATE","CTR","CTO"]}
    ly   = {c: e(ly_email, c) for c in ["SENDS","UNIQUE_OPENS","UNIQUE_CLICKS","OPEN_RATE","CTR","CTO"]}
    ty_g = _ga4_vals(ty_ga4, "Email", program)
    ly_g = _ga4_vals(ly_ga4, "Email", program)

    def _conv(g):  return g["ORDERS"] / g["SESSIONS"] if g.get("SESSIONS") else None
    def _aov(g):   return g["REVENUE"] / g["ORDERS"]  if g.get("ORDERS")   else None
    def _dpm(g, r): return g["REVENUE"] / r.get("SENDS") * 1000 if g.get("REVENUE") and r.get("SENDS") else None

    ty_sw = _swatch_val(ty_swatches, "Email")
    ly_sw = _swatch_val(ly_swatches, "Email")

    col_table, col_trend = st.columns([1, 1])
    with col_table:
        rows = [
            make_row("Sends",      ty.get("SENDS"),      ly.get("SENDS"),      num),
            make_row("Open Rate",  ty.get("OPEN_RATE"),  ly.get("OPEN_RATE"),  pct,   is_rate=True),
            make_row("CTR",        ty.get("CTR"),        ly.get("CTR"),        pct,   is_rate=True),
            make_row("CTO",        ty.get("CTO"),        ly.get("CTO"),        pct,   is_rate=True),
            make_row("Sessions",   ty_g.get("SESSIONS"), ly_g.get("SESSIONS"), num),
        ]
        if HAS_SWATCHES:
            rows.append(make_row("Swatches", ty_sw, ly_sw, num))
        rows += [
            make_row("Orders",     ty_g.get("ORDERS"),   ly_g.get("ORDERS"),   num),
            make_row("Revenue",    ty_g.get("REVENUE"),  ly_g.get("REVENUE"),  money),
            make_row("AOV",        _aov(ty_g),           _aov(ly_g),           money, is_rate=True),
            make_row("Conv. Rate", _conv(ty_g),          _conv(ly_g),          pct,   is_rate=True),
            make_row("$/M Sent",   _dpm(ty_g, ty),       _dpm(ly_g, ly),       money, is_rate=True),
        ]
        render_metric_grid(rows)

    with col_trend:
        sess_vals = [_ga4_vals(fetch_ga4_revenue(p.start, p.end), "Email", program).get("SESSIONS")
                     for p in t_periods]
        trend_chart(t_periods, sess_vals, "Sessions", num, key=f"{program}_sessions", title="Sessions")
        if HAS_SWATCHES:
            sw_vals = [_swatch_val(fetch_ga4_swatches(p.start, p.end), "Email")
                       for p in t_periods]
            trend_chart(t_periods, sw_vals, "Swatches", num, key=f"{program}_swatches", title="Swatches")
        rev_vals  = [_ga4_vals(fetch_ga4_revenue(p.start, p.end), "Email", program).get("REVENUE")
                     for p in t_periods]
        trend_chart(t_periods, rev_vals, "Revenue", money, key=f"{program}_revenue", title="Revenue")

    ga4_detail = fetch_ga4_campaign_detail(ty_period.start, ty_period.end)

    if program == "B&B":
        with st.expander("Campaign detail"):
            detail = fetch_bb_detail(ty_period.start, ty_period.end)
            if detail.empty and ga4_detail.empty:
                st.caption("No data for this period.")
            else:
                _render_bb_detail_table(detail, ga4_detail)
    else:
        with st.expander("Canvas / step detail"):
            detail = fetch_trigger_detail(ty_period.start, ty_period.end)
            if not detail.empty:
                _render_trigger_detail_table(detail, ga4_detail)
            sms_detail = fetch_sms_detail(ty_period.start, ty_period.end)
            if not sms_detail.empty:
                _render_sms_triggered_canvases(sms_detail, ga4_detail)
            if detail.empty and (sms_detail.empty or
                                  sms_detail[sms_detail["CANVAS_NAME"].notna()].empty):
                st.caption("No data for this period.")


def render_sms_section(ty_sms: pd.DataFrame, ly_sms: pd.DataFrame,
                       ty_ga4: pd.DataFrame,  ly_ga4: pd.DataFrame,
                       ty_period: Period, t_periods: list[Period],
                       ty_swatches: Optional[pd.DataFrame] = None,
                       ly_swatches: Optional[pd.DataFrame] = None):
    st.subheader("SMS")

    def s(df, col):
        if df.empty or col not in df.columns:
            return None
        v = df.iloc[0][col]
        return float(v) if not pd.isna(v) else None

    ty_g = _ga4_vals(ty_ga4, "SMS")
    ly_g = _ga4_vals(ly_ga4, "SMS")
    def _conv(g):     return g["ORDERS"] / g["SESSIONS"] if g.get("SESSIONS") else None
    def _aov(g):      return g["REVENUE"] / g["ORDERS"]  if g.get("ORDERS")   else None
    def _dpm(g, snd): return g["REVENUE"] / snd * 1000   if g.get("REVENUE") and snd else None

    ty_sw = _swatch_val(ty_swatches, "SMS")
    ly_sw = _swatch_val(ly_swatches, "SMS")

    col_table, col_trend = st.columns([1, 1])
    with col_table:
        rows = [
            make_row("Sends",    s(ty_sms,"SMS_SENDS"),  s(ly_sms,"SMS_SENDS"),  num),
            make_row("Sessions", ty_g.get("SESSIONS"),   ly_g.get("SESSIONS"),   num),
        ]
        if HAS_SWATCHES:
            rows.append(make_row("Swatches", ty_sw, ly_sw, num))
        rows += [
            make_row("Orders",     ty_g.get("ORDERS"),     ly_g.get("ORDERS"),     num),
            make_row("Revenue",    ty_g.get("REVENUE"),    ly_g.get("REVENUE"),    money),
            make_row("AOV",        _aov(ty_g),             _aov(ly_g),             money, is_rate=True),
            make_row("Conv. Rate", _conv(ty_g),            _conv(ly_g),            pct,   is_rate=True),
            make_row("$/M Sent",   _dpm(ty_g, s(ty_sms,"SMS_SENDS")),
                                   _dpm(ly_g, s(ly_sms,"SMS_SENDS")), money,       is_rate=True),
        ]
        render_metric_grid(rows)

    with col_trend:
        sess_vals = [_ga4_vals(fetch_ga4_revenue(p.start, p.end), "SMS").get("SESSIONS")
                     for p in t_periods]
        trend_chart(t_periods, sess_vals, "Sessions", num, key="sms_sessions", title="Sessions")
        if HAS_SWATCHES:
            sw_vals = [_swatch_val(fetch_ga4_swatches(p.start, p.end), "SMS")
                       for p in t_periods]
            trend_chart(t_periods, sw_vals, "Swatches", num, key="sms_swatches", title="Swatches")
        rev_vals  = [_ga4_vals(fetch_ga4_revenue(p.start, p.end), "SMS").get("REVENUE")
                     for p in t_periods]
        trend_chart(t_periods, rev_vals, "Revenue", money, key="sms_revenue", title="Revenue")

    ga4_detail = fetch_ga4_campaign_detail(ty_period.start, ty_period.end)
    sms_detail = fetch_sms_detail(ty_period.start, ty_period.end)
    with st.expander("Campaign detail"):
        if sms_detail.empty:
            st.caption("No data for this period.")
        else:
            _render_sms_detail_table(sms_detail, ga4_detail)
            _render_sms_triggered_canvases(sms_detail, ga4_detail)


def render_summary_banner(ty_email, ly_email, ty_sms, ly_sms, ty_ga4, ly_ga4,
                          ty_share=None, ly_share=None,
                          ty_swatches=None, ly_swatches=None):
    def e(df, prog, col):
        sub = df[df["PROGRAM"] == prog] if not df.empty and "PROGRAM" in df.columns else df
        if sub.empty:
            return None
        v = sub.iloc[0][col]
        return float(v) if not pd.isna(v) else None
    def s(df, col):
        if df.empty or col not in df.columns:
            return None
        v = df.iloc[0][col]
        return float(v) if not pd.isna(v) else None

    ty_sends = (e(ty_email,"B&B","SENDS") or 0) + (e(ty_email,"Triggered","SENDS") or 0)
    ly_sends = (e(ly_email,"B&B","SENDS") or 0) + (e(ly_email,"Triggered","SENDS") or 0)
    ty_opens = (e(ty_email,"B&B","UNIQUE_OPENS") or 0) + (e(ty_email,"Triggered","UNIQUE_OPENS") or 0)
    ly_opens = (e(ly_email,"B&B","UNIQUE_OPENS") or 0) + (e(ly_email,"Triggered","UNIQUE_OPENS") or 0)
    ty_or = ty_opens / ty_sends if ty_sends else None
    ly_or = ly_opens / ly_sends if ly_sends else None

    ty_email_rev  = _ga4_vals(ty_ga4, "Email").get("REVENUE") or 0
    ty_sms_rev    = _ga4_vals(ty_ga4, "SMS").get("REVENUE")   or 0
    ly_email_rev  = _ga4_vals(ly_ga4, "Email").get("REVENUE") or 0
    ly_sms_rev    = _ga4_vals(ly_ga4, "SMS").get("REVENUE")   or 0
    ty_total_rev  = ty_email_rev + ty_sms_rev
    ly_total_rev  = ly_email_rev + ly_sms_rev

    ty_email_sess = _ga4_vals(ty_ga4, "Email").get("SESSIONS") or 0
    ty_sms_sess   = _ga4_vals(ty_ga4, "SMS").get("SESSIONS")   or 0
    ly_email_sess = _ga4_vals(ly_ga4, "Email").get("SESSIONS") or 0
    ly_sms_sess   = _ga4_vals(ly_ga4, "SMS").get("SESSIONS")   or 0
    ty_total_sess = ty_email_sess + ty_sms_sess
    ly_total_sess = ly_email_sess + ly_sms_sess

    ty_trg_rev = _ga4_vals(ty_ga4, "Email", "Triggered").get("REVENUE") or 0
    ly_trg_rev = _ga4_vals(ly_ga4, "Email", "Triggered").get("REVENUE") or 0
    ty_trg_pct = ty_trg_rev / ty_total_rev if ty_total_rev else None
    ly_trg_pct = ly_trg_rev / ly_total_rev if ly_total_rev else None
    if ty_trg_pct is not None and ly_trg_pct is not None:
        pp = ty_trg_pct - ly_trg_pct
        trg_delta = f"{'+' if pp >= 0 else ''}{pp:.1%} pp vs LY"
    else:
        trg_delta = None

    ty_sms_sends = s(ty_sms, "SMS_SENDS")
    ly_sms_sends = s(ly_sms, "SMS_SENDS")

    metrics_col, bur_col = st.columns([5, 1])
    with metrics_col:
        n_cols = 6 if HAS_SWATCHES else 5
        cols = st.columns(n_cols)
        with cols[0]:
            st.metric("Email Sends", num(ty_sends), delta=delta_label(ty_sends, ly_sends))
        with cols[1]:
            st.metric("SMS Sends", num(ty_sms_sends), delta=delta_label(ty_sms_sends, ly_sms_sends))
        with cols[2]:
            st.metric("Sessions", num(ty_total_sess), delta=delta_label(ty_total_sess, ly_total_sess))
        if HAS_SWATCHES:
            ty_sw_tot = (_swatch_val(ty_swatches, "Email") or 0) + (_swatch_val(ty_swatches, "SMS") or 0) or None
            ly_sw_tot = (_swatch_val(ly_swatches, "Email") or 0) + (_swatch_val(ly_swatches, "SMS") or 0) or None
            with cols[3]:
                st.metric("Swatches", num(ty_sw_tot), delta=delta_label(ty_sw_tot, ly_sw_tot))
            trg_col, rev_col = 4, 5
        else:
            trg_col, rev_col = 3, 4
        with cols[trg_col]:
            st.metric("Triggered % of Revenue", pct(ty_trg_pct), delta=trg_delta)
        with cols[rev_col]:
            st.metric("Lifecycle Revenue", money(ty_total_rev), delta=delta_label(ty_total_rev, ly_total_rev))

    with bur_col:
        if ty_share and ly_share:
            bur_ty_rev  = ty_share.get("total_revenue",  0)
            bur_ly_rev  = ly_share.get("total_revenue",  0)
            bur_ty_sess = ty_share.get("total_sessions", 0)
            bur_ly_sess = ly_share.get("total_sessions", 0)

            def _g(ty, ly):
                if ty and ly:
                    pct_val = (ty - ly) / ly
                    sign = "+" if pct_val >= 0 else ""
                    color = "#2d7d46" if pct_val >= 0 else "#c0392b"
                    arrow = "▲" if pct_val >= 0 else "▼"
                    return (f"<span style='color:{color}'>{arrow} {sign}{pct_val:.1%} vs LY</span>")
                return "<span style='color:#aaa'>— vs LY</span>"

            st.markdown(
                "<div style='border:1px solid #e0e0e0; border-radius:6px; "
                "padding:8px 12px; background:#fafafa; font-size:0.78rem; line-height:1.8;'>"
                f"<div style='font-weight:600; color:#555; margin-bottom:4px;'>{BRAND_NAME} overall</div>"
                f"<div>Revenue &nbsp;<b>{money(bur_ty_rev)}</b><br>{_g(bur_ty_rev, bur_ly_rev)}</div>"
                f"<div style='margin-top:4px;'>Sessions &nbsp;<b>{num(bur_ty_sess)}</b><br>{_g(bur_ty_sess, bur_ly_sess)}</div>"
                "</div>",
                unsafe_allow_html=True,
            )


# ── Forecast section ──────────────────────────────────────────────────────────

def _build_forecast_days(m_start: date, m_end: date, sends: dict,
                          baseline: float, actuals_by_date: dict,
                          finance_by_date: dict) -> list:
    """Build per-day forecast rows for one forecast month."""
    today     = date.today()
    yesterday = today - timedelta(days=1)
    days = []
    for i in range((m_end - m_start).days + 1):
        d     = m_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        send  = sends.get(d_str)
        _fallback = CATEGORY_BENCHMARKS.get("other", baseline)

        if send:
            bmark    = CATEGORY_BENCHMARKS.get(send["category"], _fallback)
            w        = 0.5 if send["if_needed"] else 1.0
            sms_add  = SMS_UPLIFT if send.get("has_sms") else 0
            forecast = w * bmark + (1 - w) * baseline + sms_add
        else:
            bmark    = None
            sms_add  = 0
            forecast = baseline

        days.append({
            "date":      d,
            "day":       d.day,
            "label":     str(d.day),
            "forecast":  forecast,
            "actual":    actuals_by_date.get(d),
            "finance":   finance_by_date.get(d),
            "is_past":   d <= yesterday,
            "has_send":  send is not None,
            "has_sms":   send.get("has_sms", False) if send else False,
            "if_needed": send["if_needed"] if send else False,
            "send_name": send["name"]      if send else None,
            "send_cat":  CATEGORY_LABELS.get(send["category"], "") if send else "No batch send",
            "benchmark": bmark,
            "sms_add":   sms_add,
        })
    return days


def _fetch_month_data(m_start: date, m_end: date):
    """Fetch actuals + finance forecast for one month. Returns (actuals_by_date, finance_by_date)."""
    today     = date.today()
    yesterday = today - timedelta(days=1)
    act_end   = min(m_end, yesterday)
    actuals_df = (fetch_daily_lifecycle_actuals(m_start, act_end)
                  if act_end >= m_start else pd.DataFrame())
    finance_df = fetch_finance_forecast(m_start, m_end)

    actuals_by_date: dict = {}
    if not actuals_df.empty and "DT" in actuals_df.columns:
        for _, row in actuals_df.iterrows():
            if row.get("REVENUE") is not None:
                actuals_by_date[row["DT"]] = float(row["REVENUE"])

    finance_by_date: dict = {}
    if not finance_df.empty:
        rev_col = ("ADJUSTED_REVENUE" if "ADJUSTED_REVENUE" in finance_df.columns
                   else "GROSS_REVENUE" if "GROSS_REVENUE" in finance_df.columns else None)
        if rev_col:
            for _, row in finance_df.iterrows():
                v = row.get(rev_col)
                if v is not None:
                    finance_by_date[row["DT"]] = float(v)

    return actuals_by_date, finance_by_date


def _render_prior_months_chart(prior_months_data: list, key_suffix: str):
    """Compact grouped bar chart for up to 3 completed forecast months (actual vs forecast)."""
    if not prior_months_data:
        return

    labels    = [d["label"] for d in prior_months_data]
    actuals   = [d["actual_total"] for d in prior_months_data]
    forecasts = [d["fcast_total"]  for d in prior_months_data]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Actual", x=labels, y=actuals,
        marker_color="#444444",
        text=[money(v) for v in actuals],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="%{x}<br><b>Actual: $%{y:,.0f}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        name="Forecast", x=labels, y=forecasts,
        mode="lines+markers",
        line=dict(color=ACCENT, width=2, dash="dot"),
        marker=dict(size=8, color=ACCENT),
        hovertemplate="%{x}<br><b>Forecast: $%{y:,.0f}</b><extra></extra>",
    ))
    fig.update_layout(
        height=200, margin=dict(l=0, r=0, t=24, b=0),
        bargap=0.4,
        legend=dict(orientation="h", y=1.18, x=1, xanchor="right", font=dict(size=10)),
        xaxis=dict(showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9),
                   tickformat="$,.0f", range=[0, max(max(actuals), max(forecasts)) * 1.25]),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                    key=f"prior_months_{key_suffix}")


def _render_forecast_chart(days: list, label: str, baseline: float,
                            fin_total, lc_share, key_suffix: str):
    """Full daily chart for the active (current/upcoming) forecast month."""
    today     = date.today()
    yesterday = today - timedelta(days=1)

    mtd_actual  = sum(r["actual"] for r in days if r["actual"] is not None)
    month_fcast = sum(r["forecast"] for r in days)
    pace        = mtd_actual / month_fcast if month_fcast else None
    lc_pct      = month_fcast / fin_total  if fin_total  else None

    # Label "MTD Actual" vs "Final Actual" depending on whether month is complete
    month_is_complete = all(r["is_past"] for r in days)
    actual_label = "Final Actual" if month_is_complete else "MTD Actual"
    fcast_label  = f"{label} Forecast"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(actual_label,            money(mtd_actual) if mtd_actual else "—")
    m2.metric(fcast_label,             money(month_fcast))
    m3.metric("Pace (actual / fcst)",  pct(pace)   if pace  is not None else "—")
    m4.metric("Lifecycle % of Finance", pct(lc_pct) if lc_pct is not None else "—")

    all_labels = [r["label"] for r in days]
    fig = go.Figure()

    # Past actuals
    past = [r for r in days if r["is_past"] and r["actual"] is not None]
    if past:
        fig.add_trace(go.Bar(
            x=[r["label"] for r in past],
            y=[r["actual"] for r in past],
            name="Actual",
            marker_color="#444444",
            hovertext=[
                f"{label[:3]} {r['day']}<br>{r['send_name'] or 'No batch send'}<br>{r['send_cat']}"
                for r in past
            ],
            hovertemplate="%{hovertext}<br><b>Actual: $%{y:,.0f}</b><extra></extra>",
        ))

    # Confirmed future sends
    conf = [r for r in days if not r["is_past"] and r["has_send"] and not r["if_needed"]]
    if conf:
        fig.add_trace(go.Bar(
            x=[r["label"] for r in conf],
            y=[r["forecast"] for r in conf],
            name="Forecast (confirmed)",
            marker_color=ACCENT,
            hovertext=[
                f"{label[:3]} {r['day']}: {r['send_name']}<br>{r['send_cat']}<br>Benchmark: {money(r['benchmark'])}"
                + (f"<br>+ SMS uplift: {money(r['sms_add'])}" if r['sms_add'] else "")
                for r in conf
            ],
            hovertemplate="%{hovertext}<br><b>Forecast: $%{y:,.0f}</b><extra></extra>",
        ))

    # If Needed future sends
    ifn = [r for r in days if not r["is_past"] and r["if_needed"]]
    if ifn:
        fig.add_trace(go.Bar(
            x=[r["label"] for r in ifn],
            y=[r["forecast"] for r in ifn],
            name="Forecast (if needed, 50%)",
            marker_color=ACCENT,
            opacity=0.45,
            hovertext=[
                f"{label[:3]} {r['day']}: {r['send_name']}<br>{r['send_cat']} · 50% probability<br>Benchmark: {money(r['benchmark'])}"
                + (f"<br>+ SMS uplift: {money(r['sms_add'])}" if r['sms_add'] else "")
                for r in ifn
            ],
            hovertemplate="%{hovertext}<br><b>Forecast: $%{y:,.0f}</b><extra></extra>",
        ))

    # No-send future days
    nbs = [r for r in days if not r["is_past"] and not r["has_send"]]
    if nbs:
        fig.add_trace(go.Bar(
            x=[r["label"] for r in nbs],
            y=[r["forecast"] for r in nbs],
            name="Triggered baseline",
            marker_color="#d4d4d4",
            hovertext=[f"{label[:3]} {r['day']}: No batch send" for r in nbs],
            hovertemplate="%{hovertext}<br><b>Baseline: $%{y:,.0f}</b><extra></extra>",
        ))

    # Forecast line
    fig.add_trace(go.Scatter(
        x=all_labels,
        y=[r["forecast"] for r in days],
        name="Forecast",
        mode="lines+markers",
        line=dict(color="#666666", width=1.5, dash="dot"),
        marker=dict(size=5, color="#666666"),
        hovertext=[
            f"{label[:3]} {r['day']}: {r['send_name'] or 'No batch send'}<br>{r['send_cat']}<br>Forecast: {money(r['forecast'])}"
            + (f"<br>Actual: {money(r['actual'])}" if r["actual"] is not None else "")
            + (f"<br>vs forecast: {'+' if r['actual'] >= r['forecast'] else ''}{(r['actual'] - r['forecast']) / r['forecast']:.1%}" if r["actual"] is not None else "")
            for r in days
        ],
        hovertemplate="%{hovertext}<extra></extra>",
    ))

    fig.add_hline(
        y=baseline, line_dash="dot", line_color=MUTED, line_width=1.2,
        annotation_text=f"Daily baseline ~{money(baseline)}",
        annotation_position="bottom right",
        annotation_font_size=10,
    )
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", y=1.13, x=1, xanchor="right", font=dict(size=10)),
        xaxis=dict(showgrid=False, tickfont=dict(size=9), type="category",
                   categoryorder="array", categoryarray=all_labels,
                   title_text=label, title_font=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9),
                   tickformat="$,.0f"),
        plot_bgcolor="white", paper_bgcolor="white",
        bargap=0.18,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                    key=f"forecast_chart_{key_suffix}")

    with st.expander("Send schedule & benchmarks"):
        rows_out = []
        for r in days:
            rows_out.append({
                "Date":      r["date"].strftime("%a %-d"),
                "Send":      r["send_name"] or "—",
                "Type":      r["send_cat"],
                "Confirmed": "50%" if r["if_needed"] else ("Yes" if r["has_send"] else "—"),
                "Benchmark": money(r["benchmark"]) if r["benchmark"] else money(baseline),
                "Forecast":  money(r["forecast"]),
                "Actual":    money(r["actual"]) if r["actual"] is not None else "—",
            })
        st.dataframe(pd.DataFrame(rows_out), hide_index=True, use_container_width=True)

    bm_note = "  ·  ".join(
        f"{CATEGORY_LABELS.get(k, k)}: {money(v)}"
        for k, v in sorted(CATEGORY_BENCHMARKS.items(), key=lambda x: -x[1])
    )
    scale_note = ""
    if fin_total and lc_share:
        scale_note = (
            f" Forecast scaled to {lc_share:.1%} of finance target "
            f"({money(fin_total * lc_share)} lifecycle of {money(fin_total)} total), "
            f"based on 8-week trailing lifecycle share."
        )
    st.caption(
        f"**Model:** Send schedule shapes the daily curve (category benchmarks — {bm_note}); "
        f"total month is anchored to finance target × trailing lifecycle share."
        + scale_note
        + (" 'If Needed' = 50% probability." if any(r["if_needed"] for r in days) else "")
    )


def render_forecast_section():
    today = date.today()

    # Resolve month list — prefer FORECAST_MONTHS, fall back to single-month globals
    if FORECAST_MONTHS:
        months = FORECAST_MONTHS
    else:
        months = [{
            "start": FORECAST_MONTH_START,
            "end":   FORECAST_MONTH_END,
            "label": FORECAST_MONTH_LABEL,
            "sends": FORECAST_SENDS,
        }]

    # Active month = last entry (most recent / current). Everything before it = past summaries.
    active = months[-1]
    past_months = months[:-1]

    # Determine section header from active month
    active_is_complete = active["end"] < today
    header_suffix = " — Final" if active_is_complete else " — Lifecycle Revenue Forecast"
    st.subheader(f"{active['label']}{header_suffix}")

    with st.spinner("Loading forecast data…"):
        baseline       = fetch_lifecycle_baseline()
        lc_share       = fetch_lifecycle_share_trailing()

        # Fetch data for all months
        all_month_data = {}
        for m in months:
            all_month_data[m["label"]] = _fetch_month_data(m["start"], m["end"])

    # Build prior months data (up to last 3) and render as compact grouped bar chart
    recent_past = past_months[-3:]
    prior_months_data = []
    for m in recent_past:
        actuals_by_date, finance_by_date = all_month_data[m["label"]]
        days_m = _build_forecast_days(m["start"], m["end"], m["sends"],
                                      baseline, actuals_by_date, finance_by_date)
        prior_months_data.append({
            "label":        m["label"],
            "actual_total": sum(r["actual"] for r in days_m if r["actual"] is not None),
            "fcast_total":  sum(r["forecast"] for r in days_m),
        })

    if prior_months_data:
        st.markdown("##### Prior months — actual vs forecast")
        _render_prior_months_chart(prior_months_data,
                                   key_suffix="_".join(d["label"].replace(" ", "") for d in prior_months_data))

    # Render active month as full chart
    actuals_by_date, finance_by_date = all_month_data[active["label"]]
    days = _build_forecast_days(active["start"], active["end"], active["sends"],
                                baseline, actuals_by_date, finance_by_date)
    fin_total = sum(finance_by_date.values()) if finance_by_date else None

    # Scale forecasts so month total = finance_total × trailing lifecycle share.
    # This anchors the model to the business forecast while preserving the
    # relative shape driven by the send schedule.
    if fin_total and lc_share and fin_total > 0:
        raw_total = sum(r["forecast"] for r in days)
        target_total = fin_total * lc_share
        if raw_total > 0:
            scale = target_total / raw_total
            for r in days:
                r["forecast"] = r["forecast"] * scale

    _render_forecast_chart(days, active["label"], baseline, fin_total, lc_share,
                           key_suffix=active["label"].replace(" ", "_"))


# ── Main ──────────────────────────────────────────────────────────────────────

_DATA_ISSUES_PATH = Path(__file__).resolve().parents[1] / "data" / "dashboard_data_issues.yaml"


@st.cache_data(ttl=300, show_spinner=False)
def _load_data_issues() -> list:
    """Load the known-data-issues registry (data/dashboard_data_issues.yaml)."""
    try:
        with open(_DATA_ISSUES_PATH) as f:
            return (yaml.safe_load(f) or {}).get("issues", []) or []
    except FileNotFoundError:
        return []


def render_data_issue_banners(brand_code: str, ty_period: "Period", ly_p: "Period"):
    """Render banners for known data-quality issues affecting `brand_code`.

    A dated issue is shown when its active range overlaps the current or last-year window
    being viewed (an open issue — end_date null — runs through today). So the default/current
    view always surfaces active problems, resolved issues surface when you view the dates they
    hit, and periods before an issue began stay clean instead of crying wolf. A structural
    limitation (always_show: true, no dates) is shown on every period.
    """
    issues = [i for i in _load_data_issues()
              if str(i.get("brand", "")).upper() == (brand_code or "").upper()]
    if not issues:
        return

    def _overlaps(start, end, win_start, win_end) -> bool:
        if start is None:
            return False
        end = end or date.today()
        return start <= win_end and end >= win_start

    for issue in issues:
        start, end = issue.get("start_date"), issue.get("end_date")
        always = bool(issue.get("always_show"))
        ongoing = end is None
        show = always \
            or _overlaps(start, end, ty_period.start, ty_period.end) \
            or _overlaps(start, end, ly_p.start, ly_p.end)
        if not show:
            continue

        metrics = ", ".join(str(m) for m in (issue.get("metrics") or [])) or "—"
        if start is None:
            scope = "**Scope:** all periods (known limitation)"
        else:
            span = (f"{start:%b %-d, %Y} – "
                    + ("ongoing (not yet fixed)" if ongoing else f"{end:%b %-d, %Y}"))
            scope = f"**Affected:** {span}"
        parts = [
            f"**⚠️ Data note — {issue.get('summary', '')}**",
            f"{scope}  ·  **Metrics:** {metrics}",
            (issue.get("detail") or "").strip(),
        ]
        link = issue.get("link")
        if link:
            parts.append(f"[Tracking ticket]({link})")
        body = "\n\n".join(p for p in parts if p)

        sev = str(issue.get("severity", "warning")).lower()
        if sev == "critical":
            st.error(body, icon="🚨")
        elif sev == "info":
            st.info(body, icon="ℹ️")
        else:
            st.warning(body, icon="⚠️")


def main():
    st.set_page_config(page_title=f"{BRAND_NAME} Lifecycle Dashboard",
                       layout="wide", initial_sidebar_state="collapsed")
    st.markdown("""
        <style>
        .block-container { padding-top: 1.5rem; }
        h1 { font-size: 1.6rem; }
        h2 { font-size: 1.2rem; border-bottom: 2px solid #e94560; padding-bottom: 4px; }
        [data-testid="stMetricValue"] { font-size: 1.3rem; font-weight: 600; }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"{BRAND_NAME} — Lifecycle Performance")

    # ── Period toggle ────────────────────────────────────────────────────────
    toggle_col, share_col = st.columns([4, 1])

    with toggle_col:
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
            if custom_start == custom_end:
                label = custom_start.strftime("%-d %b %Y")
            else:
                label = f"{custom_start.strftime('%-d %b')} – {custom_end.strftime('%-d %b %Y')}"
            ty_period = Period(custom_start, custom_end, label)
        else:
            ty_period = get_period(mode)

        ly_p      = ly_for(ty_period, mode)
        t_periods = trend_periods(mode, ty_period)

        if mode == "Custom":
            trend_note = (f"  ·  Chart: daily" if len(t_periods) > 1 and (t_periods[1].start - t_periods[0].start).days == 1
                          else f"  ·  Chart: weekly" if len(t_periods) > 1
                          else "")
            st.caption(
                f"**{ty_period.label}**  ·  "
                f"vs LY (52 weeks prior): {ly_p.label}"
                + trend_note
            )
        else:
            st.caption(
                f"**{ty_period.label}**  ·  "
                f"vs LY: {ly_p.label}  ·  "
                f"Trend: {t_periods[0].label} – {t_periods[-1].label}"
            )

    # ── Known data-quality issues ─────────────────────────────────────────────
    render_data_issue_banners(BRAND_CODE, ty_period, ly_p)

    # ── Fetch current + LY periods ───────────────────────────────────────────
    with st.spinner("Loading data…"):
        ty_email    = fetch_email_engagement(ty_period.start, ty_period.end)
        ly_email    = fetch_email_engagement(ly_p.start,      ly_p.end)
        ty_sms      = fetch_sms_engagement(ty_period.start,   ty_period.end)
        ly_sms      = fetch_sms_engagement(ly_p.start,        ly_p.end)
        ty_ga4      = fetch_ga4_revenue(ty_period.start,      ty_period.end)
        ly_ga4      = fetch_ga4_revenue(ly_p.start,           ly_p.end)
        ty_share    = fetch_ga4_share(ty_period.start,        ty_period.end)
        ly_share    = fetch_ga4_share(ly_p.start,             ly_p.end)
        ty_swatches = fetch_ga4_swatches(ty_period.start,     ty_period.end)
        ly_swatches = fetch_ga4_swatches(ly_p.start,          ly_p.end)

    # ── Lifecycle share box (rendered into right column defined above) ────────
    with share_col:
        def _share(d, key_lc, key_tot):
            tot = d.get(key_tot, 0)
            return d.get(key_lc, 0) / tot if tot else None

        ty_rev_sh   = _share(ty_share, "lifecycle_revenue",  "total_revenue")
        ly_rev_sh   = _share(ly_share, "lifecycle_revenue",  "total_revenue")
        ty_sess_sh  = _share(ty_share, "lifecycle_sessions", "total_sessions")
        ly_sess_sh  = _share(ly_share, "lifecycle_sessions", "total_sessions")

        def _delta_pp(ty, ly):
            if ty is None or ly is None:
                return None
            return (ty - ly) * 100  # percentage points

        rev_delta  = _delta_pp(ty_rev_sh,  ly_rev_sh)
        sess_delta = _delta_pp(ty_sess_sh, ly_sess_sh)

        st.markdown(
            "<div style='border:1px solid #e0e0e0; border-radius:6px; "
            "padding:8px 12px; background:#fafafa; font-size:0.78rem; line-height:1.6;'>"
            f"<div style='font-weight:600; color:#555; margin-bottom:4px;'>Lifecycle share of {BRAND_NAME}</div>"
            + (f"<div>Revenue &nbsp;<b>{ty_rev_sh:.1%}</b>"
               + (f" &nbsp;<span style='color:{'#2d7d46' if rev_delta >= 0 else '#c0392b'}'>"
                  f"{'▲' if rev_delta >= 0 else '▼'}{abs(rev_delta):.1f}pp</span>" if rev_delta is not None else "")
               + "</div>" if ty_rev_sh is not None else "<div style='color:#aaa'>Revenue — no data</div>")
            + (f"<div>Sessions &nbsp;<b>{ty_sess_sh:.1%}</b>"
               + (f" &nbsp;<span style='color:{'#2d7d46' if sess_delta >= 0 else '#c0392b'}'>"
                  f"{'▲' if sess_delta >= 0 else '▼'}{abs(sess_delta):.1f}pp</span>" if sess_delta is not None else "")
               + "</div>" if ty_sess_sh is not None else "<div style='color:#aaa'>Sessions — no data</div>")
            + "</div>",
            unsafe_allow_html=True,
        )

    if ty_email.empty and ty_sms.empty:
        if YAML_CAMPAIGNS_DIR:
            st.info("No campaigns found for this date range.")
        else:
            st.error("No data returned. Check Snowflake connection or date range.")
        return

    # ── Summary banner ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("At a Glance")
    render_summary_banner(ty_email, ly_email, ty_sms, ly_sms, ty_ga4, ly_ga4,
                          ty_share=ty_share, ly_share=ly_share,
                          ty_swatches=ty_swatches, ly_swatches=ly_swatches)
    st.markdown("---")

    # ── Program sections ─────────────────────────────────────────────────────
    render_email_section("Email — Batch & Blast", "B&B",
                         ty_email, ly_email, ty_ga4, ly_ga4, ty_period, t_periods,
                         ty_swatches=ty_swatches, ly_swatches=ly_swatches)
    st.markdown("---")
    render_email_section("Triggers", "Triggered",
                         ty_email, ly_email, ty_ga4, ly_ga4, ty_period, t_periods,
                         ty_swatches=ty_swatches, ly_swatches=ly_swatches)
    if HAS_SMS:
        st.markdown("---")
        render_sms_section(ty_sms, ly_sms, ty_ga4, ly_ga4, ty_period, t_periods,
                           ty_swatches=ty_swatches, ly_swatches=ly_swatches)

    # ── YOY charts ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Year over Year — Revenue & Sessions")
    render_yoy_charts()

    st.markdown("---")
    st.subheader("Year over Year — Explore")
    render_yoy_explore()

    st.markdown("---")
    st.subheader("Triggered Canvas — Year over Year")
    render_canvas_yoy()

    # ── May 2026 Forecast ────────────────────────────────────────────────────
    if HAS_FORECAST:
        st.markdown("---")
        render_forecast_section()

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "**Sources:** Email engagement — Braze Raw Events Datashare. "
        "Revenue/sessions — GA4 via Airbyte. "
        "Triggered email identified by TRG UTM prefix or campaign name containing: abandon, browse, cart, welcome. "
        "LY = same period one year prior."
    )


if __name__ == "__main__":
    main()
