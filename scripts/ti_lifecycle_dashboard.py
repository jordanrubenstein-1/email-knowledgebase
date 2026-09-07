"""
The Inside (TI) Lifecycle Performance Dashboard — Klaviyo edition.

Run locally:
    python3 -m streamlit run scripts/ti_lifecycle_dashboard.py

Data sources:
  - campaigns/*.yaml (brand: TI, klaviyo_type: campaign) — batch email metrics
  - campaigns/*.yaml (brand: TI, klaviyo_type: flow)     — triggered flow catalog
  - GA4 Snowflake (LANDING_THE_INSIDE_GA4)               — revenue & sessions

Note: TI uses Klaviyo, not Braze. Engagement metrics come from YAML files
(open rate, CTR, etc. as recorded by Klaviyo). Triggered flow metrics are
all-time totals — they are not filterable to a specific period without the
Klaviyo flow-values API, which is not yet implemented.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

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

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"
GA4_DB        = os.environ.get("SNOWFLAKE_DATABASE", "AIRBYTE_DATABASE")
GA4_SCHEMA    = "LANDING_THE_INSIDE_GA4"
GA4_TABLE     = f"{GA4_DB}.{GA4_SCHEMA}.TRAFFIC_SESSION_PERFORMANCE_DAILY"

ACCENT = "#2d6a4f"   # TI brand green
MUTED  = "#adb5bd"
BRAND_CODE = "TI"

MODES = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

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
        qs  = _quarter_start(today)
        lqs = _quarter_start(qs - timedelta(days=1))
        lqe = qs - timedelta(days=1)
        lq  = (lqs.month - 1) // 3 + 1
        return Period(lqs, lqe, f"Q{lq} {lqs.year}")
    # QTD
    qs = _quarter_start(today)
    q  = (today.month - 1) // 3 + 1
    return Period(qs, yesterday, f"Q{q} {today.year} QTD")


def render_analytics_freshness_warning(*dfs: pd.DataFrame) -> None:
    """Warn about sends in the selected period with zero recorded engagement.

    TI has no live datashare like the Braze brands. New campaigns/SMS are
    imported daily via GitLab CI but with `--skip-analytics`, and the only
    *guaranteed* backfill is the weekly `refresh-analytics` CI job (Mondays) —
    but analytics can also be refreshed ad hoc any time someone runs
    `backfill_klaviyo_analytics.py` manually, so freshness doesn't follow a
    fixed schedule. Rather than assume a cadence, detect it directly: a
    campaign/SMS send that's already gone out but still shows 0 sends in the
    YAML almost certainly hasn't been backfilled yet.
    """
    stale = []
    for df in dfs:
        if df is None or df.empty or "sends" not in df.columns:
            continue
        stale.extend(df.loc[df["sends"] == 0, "name"].tolist())
    if not stale:
        return
    shown = "; ".join(stale[:5])
    more  = f" (+{len(stale) - 5} more)" if len(stale) > 5 else ""
    st.warning(
        f"⚠️ {len(stale)} send(s) in this period show **zero** sends/opens/clicks: {shown}{more}. "
        f"TI has no live datashare like other brands — Klaviyo analytics get backfilled weekly "
        f"via GitLab CI, plus occasional manual runs in between, so recently-sent campaigns can "
        f"show zero here simply because the backfill hasn't caught up yet, not because they "
        f"actually underperformed."
    )


def ly_for(p: Period, mode: str) -> Period:
    if mode in ("Yesterday", "Last Week", "Custom"):
        ly_start = p.start - timedelta(weeks=52)
        ly_end   = p.end   - timedelta(weeks=52)
        if ly_start == ly_end:
            ly_label = f"LY {ly_start.strftime('%-d %b %Y')}"
        else:
            ly_label = f"LY {ly_start.strftime('%-d %b')} – {ly_end.strftime('%-d %b %Y')}"
        return Period(ly_start, ly_end, ly_label)
    return Period(_safe_yr(p.start, p.start.year - 1),
                  _safe_yr(p.end,   p.end.year   - 1),
                  f"LY {p.label}")


def trend_periods(mode: str, current: Period) -> list[Period]:
    if mode == "Yesterday":
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
    out = []
    for i in range(5, -1, -1):
        ms = _month_start(current.start, months_back=i)
        me = _month_end(ms) if i > 0 else current.end
        out.append(Period(ms, me, ms.strftime("%b '%y")))
    return out


# ── YAML data loading ─────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_all_campaigns() -> pd.DataFrame:
    """Load all TI batch campaigns (klaviyo_type: campaign) into a DataFrame."""
    rows = []
    for f in sorted(CAMPAIGNS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != "TI" or data.get("channel") != "email":
            continue
        ktype = data.get("klaviyo_type")
        if ktype and ktype != "campaign":
            continue
        first_sent_str = (data.get("dates") or {}).get("first_sent")
        if not first_sent_str:
            continue
        try:
            first_sent = datetime.fromisoformat(
                str(first_sent_str).replace("Z", "+00:00")
            ).date()
        except Exception:
            continue
        perf      = data.get("performance_summary") or {}
        sends_lst = data.get("sends") or []
        subject   = sends_lst[0].get("subject", "") if sends_lst else ""
        sends     = perf.get("total_sends", 0) or 0
        delivered = perf.get("total_delivered", 0) or sends
        opens     = perf.get("unique_opens", 0) or 0
        clicks    = perf.get("unique_clicks", 0) or 0
        rows.append({
            "name":         data.get("name", f.stem),
            "subject":      subject,
            "first_sent":   first_sent,
            "sends":        sends,
            "delivered":    delivered,
            "unique_opens": opens,
            "unique_clicks":clicks,
            "unsubscribes": perf.get("total_unsubscribes", 0) or 0,
            "open_rate":    perf.get("open_rate", 0.0) or 0.0,
            "click_rate":   perf.get("click_rate", 0.0) or 0.0,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_flows() -> pd.DataFrame:
    """Load all TI flows (klaviyo_type: flow) into a DataFrame."""
    rows = []
    for f in sorted(CAMPAIGNS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != "TI" or data.get("channel") != "email":
            continue
        if data.get("klaviyo_type") != "flow":
            continue
        perf      = data.get("performance_summary") or {}
        sends_lst = data.get("sends") or []
        subject   = sends_lst[0].get("subject", "") if sends_lst else ""
        sends     = perf.get("total_sends", 0) or 0
        if sends == 0:
            continue
        delivered = perf.get("total_delivered", 0) or sends
        opens     = perf.get("unique_opens", 0) or 0
        clicks    = perf.get("unique_clicks", 0) or 0
        rows.append({
            "canvas_name":     data.get("canvas_name") or data.get("name", f.stem),
            "name":            data.get("name", f.stem),
            "subject":         subject,
            "sequence_position": data.get("sequence_position", 0) or 0,
            "flow_type":       data.get("flow_type", ""),
            "sends":           sends,
            "delivered":       delivered,
            "unique_opens":    opens,
            "unique_clicks":   clicks,
            "open_rate":       perf.get("open_rate", 0.0) or 0.0,
            "click_rate":      perf.get("click_rate", 0.0) or 0.0,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["canvas_name", "sequence_position"])
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_sms_campaigns() -> pd.DataFrame:
    """Load all TI SMS batch campaigns into a DataFrame."""
    rows = []
    for f in sorted(CAMPAIGNS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != "TI" or data.get("channel") != "sms":
            continue
        if data.get("klaviyo_type") != "campaign":
            continue
        first_sent_str = (data.get("dates") or {}).get("first_sent")
        if not first_sent_str:
            continue
        try:
            first_sent = datetime.fromisoformat(
                str(first_sent_str).replace("Z", "+00:00")
            ).date()
        except Exception:
            continue
        perf     = data.get("performance_summary") or {}
        sends_lst = data.get("sends") or []
        body     = sends_lst[0].get("body", "") if sends_lst else ""
        sends    = perf.get("total_sends", 0) or 0
        delivered = perf.get("total_delivered", 0) or sends
        clicks   = perf.get("unique_clicks", 0) or 0
        rows.append({
            "name":          data.get("name", f.stem),
            "body":          body,
            "first_sent":    first_sent,
            "sends":         sends,
            "delivered":     delivered,
            "unique_clicks": clicks,
            "unsubscribes":  perf.get("total_unsubscribes", 0) or 0,
            "delivery_rate": round(delivered / sends, 4) if sends else 0.0,
            "click_rate":    perf.get("click_rate", 0.0) or 0.0,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_sms_flows() -> pd.DataFrame:
    """Load all TI SMS flows into a DataFrame."""
    rows = []
    for f in sorted(CAMPAIGNS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("brand") != "TI" or data.get("channel") != "sms":
            continue
        if data.get("klaviyo_type") != "flow":
            continue
        perf     = data.get("performance_summary") or {}
        sends_lst = data.get("sends") or []
        body     = sends_lst[0].get("body", "") if sends_lst else ""
        sends    = perf.get("total_sends", 0) or 0
        if sends == 0:
            continue
        delivered = perf.get("total_delivered", 0) or sends
        clicks   = perf.get("unique_clicks", 0) or 0
        rows.append({
            "canvas_name":       data.get("canvas_name") or data.get("name", f.stem),
            "name":              data.get("name", f.stem),
            "body":              body,
            "sequence_position": data.get("sequence_position", 0) or 0,
            "flow_type":         data.get("flow_type", ""),
            "sends":             sends,
            "delivered":         delivered,
            "unique_clicks":     clicks,
            "delivery_rate":     round(delivered / sends, 4) if sends else 0.0,
            "click_rate":        perf.get("click_rate", 0.0) or 0.0,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["canvas_name", "sequence_position"])
    return df


def campaigns_for_period(p: Period) -> pd.DataFrame:
    df = load_all_campaigns()
    if df.empty:
        return df
    return df[(df["first_sent"] >= p.start) & (df["first_sent"] <= p.end)].copy()


def sms_campaigns_for_period(p: Period) -> pd.DataFrame:
    df = load_all_sms_campaigns()
    if df.empty:
        return df
    return df[(df["first_sent"] >= p.start) & (df["first_sent"] <= p.end)].copy()


def _aggregate_sms(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sends": 0, "delivered": 0, "unique_clicks": 0,
                "unsubscribes": 0, "delivery_rate": None, "click_rate": None}
    sends     = int(df["sends"].sum())
    delivered = int(df["delivered"].sum())
    clicks    = int(df["unique_clicks"].sum())
    return {
        "sends":         sends,
        "delivered":     delivered,
        "unique_clicks": clicks,
        "unsubscribes":  int(df["unsubscribes"].sum()),
        "delivery_rate": _safe_div(delivered, sends),
        "click_rate":    _safe_div(clicks, sends),
    }


# ── GA4 Snowflake queries ─────────────────────────────────────────────────────

def _ga4_client():
    return SnowflakeClient(schema=GA4_SCHEMA, database=GA4_DB)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty:
        df.columns = [c.upper() for c in df.columns]
    return df


def _df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_revenue(start: date, end: date) -> pd.DataFrame:
    """Revenue/sessions for the period, Email channel only."""
    start_s = start.strftime("%Y%m%d")
    end_s   = end.strftime("%Y%m%d")
    q = f"""
    SELECT
        SESSIONCAMPAIGNNAME        AS campaign_name,
        SUM(SESSIONS)              AS sessions,
        SUM(ECOMMERCEPURCHASES)    AS orders,
        SUM(TOTALREVENUE)          AS revenue
    FROM {GA4_TABLE}
    WHERE DATE >= '{start_s}' AND DATE <= '{end_s}'
      AND UPPER(SESSIONPRIMARYCHANNELGROUP) = 'EMAIL'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND TRIM(SESSIONCAMPAIGNNAME) NOT IN ('', '(not set)', '(referral)')
    GROUP BY 1
    """
    try:
        client = _ga4_client()
        rows   = client.execute_query(q)
        client.close()
        return _norm(_df(rows))
    except Exception as e:
        st.warning(f"GA4 query failed: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_revenue_sms(start: date, end: date) -> pd.DataFrame:
    """Revenue/sessions for the period, SMS channel only."""
    start_s = start.strftime("%Y%m%d")
    end_s   = end.strftime("%Y%m%d")
    q = f"""
    SELECT
        SESSIONCAMPAIGNNAME        AS campaign_name,
        SUM(SESSIONS)              AS sessions,
        SUM(ECOMMERCEPURCHASES)    AS orders,
        SUM(TOTALREVENUE)          AS revenue
    FROM {GA4_TABLE}
    WHERE DATE >= '{start_s}' AND DATE <= '{end_s}'
      AND UPPER(SESSIONPRIMARYCHANNELGROUP) = 'SMS'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND TRIM(SESSIONCAMPAIGNNAME) NOT IN ('', '(not set)', '(referral)')
    GROUP BY 1
    """
    try:
        client = _ga4_client()
        rows   = client.execute_query(q)
        client.close()
        return _norm(_df(rows))
    except Exception as e:
        st.warning(f"GA4 query failed: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ga4_revenue_all_time(channel: str) -> pd.DataFrame:
    """All-time revenue/sessions by campaign name, for a given GA4 channel.

    Triggered flow metrics are all-time totals (not period-scoped), so flow
    steps need an all-time GA4 lookup rather than the period-scoped queries
    used for Batch & Blast. Verified flow step `name` values match GA4
    SESSIONCAMPAIGNNAME exactly, same as batch campaigns.
    """
    q = f"""
    SELECT
        SESSIONCAMPAIGNNAME        AS campaign_name,
        SUM(SESSIONS)              AS sessions,
        SUM(ECOMMERCEPURCHASES)    AS orders,
        SUM(TOTALREVENUE)          AS revenue
    FROM {GA4_TABLE}
    WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) = '{channel.upper()}'
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND TRIM(SESSIONCAMPAIGNNAME) NOT IN ('', '(not set)', '(referral)')
    GROUP BY 1
    """
    try:
        client = _ga4_client()
        rows   = client.execute_query(q)
        client.close()
        return _norm(_df(rows))
    except Exception as e:
        st.warning(f"GA4 query failed: {e}")
        return pd.DataFrame()


# Campaign-name markers that identify GA4 rows belonging to another brand's
# sends. TI's GA4 property is not brand-clean like the Braze brands' dedicated
# schemas -- confirmed 2026-07-28 it picks up a small amount (~3% of email
# sessions, $0 revenue in a June 2026 sample) of cross-brand session data.
# Excluded here rather than positively matching "_TI_", since ~80% of TI's own
# real campaign names (legacy/freeform Klaviyo names predating the naming
# convention, e.g. "Sofa Update (September 11)") don't contain "_TI_" either --
# a positive match would drop most of TI's real volume.
_FOREIGN_BRAND_MARKERS = ("_CZ_", "_HAV_", "_BW_", "_ID_", "_SF_", "_STF_")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_by_program(start: date, end: date) -> pd.DataFrame:
    """Sessions/orders/revenue for the period, split by channel (Email/SMS) and
    program (B&B vs Triggered), using the same TRG_ campaign-name-prefix
    convention the other brands' dashboards use to split GA4 data. Excludes
    rows carrying another brand's campaign-name marker (see
    _FOREIGN_BRAND_MARKERS)."""
    start_s = start.strftime("%Y%m%d")
    end_s   = end.strftime("%Y%m%d")
    exclude_sql = " AND ".join(
        f"POSITION('{marker}' IN UPPER(SESSIONCAMPAIGNNAME)) = 0"
        for marker in _FOREIGN_BRAND_MARKERS
    )
    q = f"""
    SELECT
        UPPER(SESSIONPRIMARYCHANNELGROUP) AS channel,
        CASE WHEN UPPER(SESSIONCAMPAIGNNAME) LIKE 'TRG%' THEN 'Triggered' ELSE 'B&B' END AS program,
        SUM(SESSIONS)           AS sessions,
        SUM(ECOMMERCEPURCHASES) AS orders,
        SUM(TOTALREVENUE)       AS revenue
    FROM {GA4_TABLE}
    WHERE DATE >= '{start_s}' AND DATE <= '{end_s}'
      AND UPPER(SESSIONPRIMARYCHANNELGROUP) IN ('EMAIL', 'SMS')
      AND SESSIONCAMPAIGNNAME IS NOT NULL
      AND {exclude_sql}
    GROUP BY 1, 2
    """
    try:
        client = _ga4_client()
        rows   = client.execute_query(q)
        client.close()
        df = _norm(_df(rows))
    except Exception as e:
        st.warning(f"GA4 query failed: {e}")
        df = pd.DataFrame()
    if df.empty:
        df = pd.DataFrame(columns=["CHANNEL", "PROGRAM", "SESSIONS", "ORDERS", "REVENUE"])
    return df


def _ga4_vals(df: pd.DataFrame, channel: str, program: Optional[str] = None) -> dict:
    """Extract summed sessions/orders/revenue for one channel [+ program] from
    a fetch_ga4_by_program() result."""
    if df is None or df.empty or "CHANNEL" not in df.columns:
        return {}
    sub = df[df["CHANNEL"] == channel.upper()]
    if program is not None and "PROGRAM" in sub.columns:
        sub = sub[sub["PROGRAM"] == program]
    if sub.empty:
        return {}
    return {
        "SESSIONS": float(sub["SESSIONS"].sum()),
        "ORDERS":   float(sub["ORDERS"].sum()),
        "REVENUE":  float(sub["REVENUE"].sum()),
    }


def _merge_ga4_by_name(camps: pd.DataFrame, ga4: pd.DataFrame,
                        ambiguous_names: set = None) -> pd.DataFrame:
    """Left-merge per-campaign GA4 sessions/orders/revenue onto a campaign detail df.

    Matches on exact campaign name (Klaviyo `name` == GA4 SESSIONCAMPAIGNNAME) —
    verified to match cleanly for TI's standard-format campaign names.

    `ambiguous_names`: names that are NOT reliably unique identifiers (e.g. legacy
    Klaviyo flow steps auto-named "Email #1" — 23 different flows share that exact
    name). Matching these against GA4 would silently attribute one campaign's
    sessions/revenue to every other row sharing the generic name, so their GA4
    columns are left blank instead of merged.
    """
    if camps.empty:
        return camps
    merged = camps.copy()
    if ga4 is None or ga4.empty or "CAMPAIGN_NAME" not in ga4.columns:
        merged["ga4_sessions"] = None
        merged["ga4_orders"]   = None
        merged["ga4_revenue"]  = None
        return merged
    ga4_slim = ga4[["CAMPAIGN_NAME", "SESSIONS", "ORDERS", "REVENUE"]].rename(columns={
        "CAMPAIGN_NAME": "name", "SESSIONS": "ga4_sessions",
        "ORDERS": "ga4_orders", "REVENUE": "ga4_revenue",
    })
    if ambiguous_names:
        ga4_slim = ga4_slim[~ga4_slim["name"].isin(ambiguous_names)]
    return merged.merge(ga4_slim, on="name", how="left")


def _ambiguous_names(all_names: pd.Series) -> set:
    """Names shared by more than one row — not safe to use as a GA4 match key."""
    counts = all_names.value_counts()
    return set(counts[counts > 1].index)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ga4_weekly_series(start: date, end: date) -> pd.DataFrame:
    start_s = start.strftime("%Y%m%d")
    end_s   = end.strftime("%Y%m%d")
    q = f"""
    SELECT DATE_TRUNC('week', TO_DATE(DATE, 'YYYYMMDD'))::DATE AS week_start,
           SUM(TOTALREVENUE) AS revenue,
           SUM(SESSIONS)     AS sessions
    FROM {GA4_TABLE}
    WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) = 'EMAIL'
      AND DATE >= '{start_s}' AND DATE <= '{end_s}'
    GROUP BY 1
    ORDER BY 1
    """
    try:
        client = _ga4_client()
        rows   = client.execute_query(q)
        client.close()
        df = _norm(_df(rows))
        if not df.empty and "WEEK_START" in df.columns:
            df["WEEK_START"] = pd.to_datetime(df["WEEK_START"]).dt.date
        return df
    except Exception as e:
        st.warning(f"GA4 weekly series failed: {e}")
        return pd.DataFrame()


# ── Metric helpers ────────────────────────────────────────────────────────────

def _safe_div(a, b) -> Optional[float]:
    try:
        b = float(b)
        return float(a) / b if b > 0 else None
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "—"


def _comma(v) -> str:
    return f"{int(v):,}" if v is not None else "—"


def _dollar(v) -> str:
    return f"${float(v):,.0f}" if v is not None else "—"


def _delta_pct(ty, ly) -> Optional[float]:
    if ly and float(ly) > 0 and ty is not None:
        return float(ty) / float(ly) - 1
    return None


def _aggregate_campaigns(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sends": 0, "delivered": 0, "unique_opens": 0, "unique_clicks": 0,
                "unsubscribes": 0, "open_rate": None, "click_rate": None}
    sends     = int(df["sends"].sum())
    delivered = int(df["delivered"].sum())
    opens     = int(df["unique_opens"].sum())
    clicks    = int(df["unique_clicks"].sum())
    return {
        "sends":         sends,
        "delivered":     delivered,
        "unique_opens":  opens,
        "unique_clicks": clicks,
        "unsubscribes":  int(df["unsubscribes"].sum()),
        "open_rate":     _safe_div(opens, sends),
        "click_rate":    _safe_div(clicks, sends),
        "cto":           _safe_div(clicks, opens),
    }


def _ga4_totals(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sessions": 0, "orders": 0, "revenue": 0.0}
    return {
        "sessions": int(df["SESSIONS"].sum()) if "SESSIONS" in df.columns else 0,
        "orders":   int(df["ORDERS"].sum())   if "ORDERS"   in df.columns else 0,
        "revenue":  float(df["REVENUE"].sum()) if "REVENUE" in df.columns else 0.0,
    }


# ── Sparkline helper ──────────────────────────────────────────────────────────

def _sparkline(values: list, labels: list, title: str,
               fmt: str = ",.0f", color: str = ACCENT) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=labels, y=values, mode="lines+markers",
        line=dict(color=color, width=2),
        marker=dict(size=4, color=color),
        hovertemplate=f"%{{x}}<br>%{{y:{fmt}}}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=11)),
        height=160, margin=dict(l=4, r=4, t=28, b=4),
        xaxis=dict(showgrid=False, tickfont=dict(size=8),
                   tickmode="array", tickvals=labels[::max(1, len(labels)//5)],
                   ticktext=labels[::max(1, len(labels)//5)]),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=8),
                   tickformat=fmt),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


def _render_ga4_program_metrics(ty_g: dict, ly_g: dict, t_periods: list["Period"],
                                channel: str, program: str, key_prefix: str) -> None:
    """Sessions + Revenue metric tiles (this period vs LY) and trend sparklines,
    sourced from GA4 and split by channel/program via fetch_ga4_by_program() --
    the same GA4-only approach the other brands' dashboards use, so these are
    available for TI regardless of the Klaviyo send-data limitations above."""
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Sessions", _comma(ty_g.get("SESSIONS")),
                  delta=f"{(_delta_pct(ty_g.get('SESSIONS'), ly_g.get('SESSIONS')) or 0):.1%}"
                  if ly_g.get("SESSIONS") else None)
    with c2:
        st.metric("Revenue", _dollar(ty_g.get("REVENUE")),
                  delta=f"{(_delta_pct(ty_g.get('REVENUE'), ly_g.get('REVENUE')) or 0):.1%}"
                  if ly_g.get("REVENUE") else None)

    t_sess = [_ga4_vals(fetch_ga4_by_program(p.start, p.end), channel, program).get("SESSIONS") or 0
              for p in t_periods]
    t_rev  = [_ga4_vals(fetch_ga4_by_program(p.start, p.end), channel, program).get("REVENUE") or 0
              for p in t_periods]
    t_labels = [p.label for p in t_periods]

    c3, c4 = st.columns(2)
    with c3:
        if any(t_sess):
            st.plotly_chart(_sparkline(t_sess, t_labels, "Sessions (trend)", fmt=",.0f"),
                            use_container_width=True, config={"displayModeBar": False},
                            key=f"{key_prefix}_sessions_spark")
    with c4:
        if any(t_rev):
            st.plotly_chart(_sparkline(t_rev, t_labels, "Revenue (trend)", fmt="$,.0f"),
                            use_container_width=True, config={"displayModeBar": False},
                            key=f"{key_prefix}_revenue_spark")


# ── Summary banner ────────────────────────────────────────────────────────────

def render_summary_banner(ty_camps: pd.DataFrame, ly_camps: pd.DataFrame,
                          ty_ga4: pd.DataFrame, ly_ga4: pd.DataFrame) -> None:
    ty = _aggregate_campaigns(ty_camps)
    ly = _aggregate_campaigns(ly_camps)
    ty_r = _ga4_totals(ty_ga4)
    ly_r = _ga4_totals(ly_ga4)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Email Sends", _comma(ty["sends"]),
                  delta=f"{_delta_pct(ty['sends'], ly['sends']):.1%}" if ly["sends"] else None)
    with c2:
        st.metric("Unique Open Rate", _pct(ty["open_rate"]),
                  delta=f"{(_delta_pct(ty['open_rate'], ly['open_rate']) or 0):.1%}" if ly["open_rate"] else None)
    with c3:
        st.metric("Unique CTR", _pct(ty["click_rate"]),
                  delta=f"{(_delta_pct(ty['click_rate'], ly['click_rate']) or 0):.1%}" if ly["click_rate"] else None)
    with c4:
        st.metric("GA4 Sessions", _comma(ty_r["sessions"]),
                  delta=f"{(_delta_pct(ty_r['sessions'], ly_r['sessions']) or 0):.1%}" if ly_r["sessions"] else None)
    with c5:
        st.metric("GA4 Revenue", _dollar(ty_r["revenue"]),
                  delta=f"{(_delta_pct(ty_r['revenue'], ly_r['revenue']) or 0):.1%}" if ly_r["revenue"] else None)


# ── B&B email section ─────────────────────────────────────────────────────────

def render_bb_section(ty_camps: pd.DataFrame, ly_camps: pd.DataFrame,
                      t_periods: list[Period], ty_ga4: pd.DataFrame = None,
                      ty_ga4_program: pd.DataFrame = None, ly_ga4_program: pd.DataFrame = None) -> None:
    st.subheader("Email — Batch & Blast")

    ty = _aggregate_campaigns(ty_camps)
    ly = _aggregate_campaigns(ly_camps)

    if ty["sends"] == 0:
        st.caption("No campaigns sent in this period.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Sends", _comma(ty["sends"]),
                      delta=f"{(_delta_pct(ty['sends'], ly['sends']) or 0):.1%}" if ly["sends"] else None)
        with c2:
            st.metric("Open Rate", _pct(ty["open_rate"]),
                      delta=f"{(_delta_pct(ty['open_rate'], ly['open_rate']) or 0):.1%}" if ly["open_rate"] else None)
        with c3:
            st.metric("CTR", _pct(ty["click_rate"]),
                      delta=f"{(_delta_pct(ty['click_rate'], ly['click_rate']) or 0):.1%}" if ly["click_rate"] else None)
        with c4:
            st.metric("CTO", _pct(ty.get("cto")))

    # Sparklines — sends and open rate by period
    t_sends     = [_aggregate_campaigns(campaigns_for_period(p))["sends"]     for p in t_periods]
    t_open_rate = [_aggregate_campaigns(campaigns_for_period(p))["open_rate"] for p in t_periods]
    t_labels    = [p.label for p in t_periods]

    c1, c2 = st.columns(2)
    with c1:
        if any(v for v in t_sends if v):
            st.plotly_chart(_sparkline(t_sends, t_labels, "Sends (trend)", fmt=",.0f"),
                            use_container_width=True, config={"displayModeBar": False},
                            key="bb_sends_spark")
    with c2:
        t_or_vals = [v if v is not None else 0 for v in t_open_rate]
        if any(t_or_vals):
            st.plotly_chart(_sparkline(t_or_vals, t_labels, "Open Rate (trend)", fmt=".1%"),
                            use_container_width=True, config={"displayModeBar": False},
                            key="bb_or_spark")

    # Sessions + Revenue (GA4, batch/blast campaigns only)
    ty_g = _ga4_vals(ty_ga4_program, "EMAIL", "B&B")
    ly_g = _ga4_vals(ly_ga4_program, "EMAIL", "B&B")
    _render_ga4_program_metrics(ty_g, ly_g, t_periods, "EMAIL", "B&B", key_prefix="bb")

    # Campaign detail table
    if not ty_camps.empty:
        with st.expander(f"Campaign detail ({len(ty_camps)} campaigns)", expanded=False):
            enriched = _merge_ga4_by_name(ty_camps, ty_ga4)
            display = enriched[[
                "first_sent", "name", "subject", "sends", "unique_opens",
                "open_rate", "unique_clicks", "click_rate", "unsubscribes",
                "ga4_sessions", "ga4_orders", "ga4_revenue",
            ]].copy()
            display.columns = [
                "Date", "Campaign", "Subject", "Sends", "Opens",
                "Open Rate", "Clicks", "CTR", "Unsubs",
                "Sessions", "Orders", "Revenue",
            ]
            display["Open Rate"] = display["Open Rate"].map("{:.1%}".format)
            display["CTR"]       = display["CTR"].map("{:.2%}".format)
            display["Revenue"]   = display["Revenue"].map(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.caption(
                "Sessions/Orders/Revenue from GA4, matched by exact campaign name. "
                "Blank = no GA4 session data found under that name for this period."
            )


# ── Triggered flows section ───────────────────────────────────────────────────

def render_flows_section(t_periods: list[Period] = None,
                         ty_ga4_program: pd.DataFrame = None, ly_ga4_program: pd.DataFrame = None) -> None:
    st.subheader("Triggered Flows")
    st.caption(
        "⚠️ Sends/Opens/Clicks below are **all-time totals** — not filtered to the selected period. "
        "Per-period flow send analytics require the Klaviyo flow-values API (not yet implemented). "
        "Totals refresh periodically (weekly via GitLab CI, plus occasional manual runs) — "
        "not in real time like other brands' live datashare. Sessions/Revenue below, however, "
        "come from GA4 and ARE scoped to the selected period, same as Batch & Blast."
    )

    flows = load_all_flows()
    if flows.empty:
        st.caption("No flow data found.")
        return

    total_sends  = int(flows["sends"].sum())
    total_opens  = int(flows["unique_opens"].sum())
    total_clicks = int(flows["unique_clicks"].sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Active Flows", flows["canvas_name"].nunique())
    with c2:
        st.metric("Total Steps", len(flows))
    with c3:
        st.metric("All-Time Sends", _comma(total_sends))
    with c4:
        avg_or = _safe_div(total_opens, total_sends)
        st.metric("Avg Open Rate", _pct(avg_or))

    if t_periods:
        ty_g = _ga4_vals(ty_ga4_program, "EMAIL", "Triggered")
        ly_g = _ga4_vals(ly_ga4_program, "EMAIL", "Triggered")
        _render_ga4_program_metrics(ty_g, ly_g, t_periods, "EMAIL", "Triggered", key_prefix="trg")

    ga4_flows = fetch_ga4_revenue_all_time("EMAIL")
    dup_names = _ambiguous_names(flows["name"])
    with st.expander("Flow catalog", expanded=False):
        for canvas_name, steps in flows.groupby("canvas_name", sort=True):
            st.markdown(f"**{canvas_name}**")
            enriched = _merge_ga4_by_name(steps, ga4_flows, dup_names)
            display = enriched[[
                "sequence_position", "name", "subject", "sends", "unique_opens",
                "open_rate", "unique_clicks", "click_rate",
                "ga4_sessions", "ga4_orders", "ga4_revenue",
            ]].copy()
            display.columns = ["Seq", "Step Name", "Subject", "Sends", "Opens", "Open Rate", "Clicks", "CTR",
                                "Sessions", "Orders", "Revenue"]
            display["Open Rate"] = display["Open Rate"].map("{:.1%}".format)
            display["CTR"]       = display["CTR"].map("{:.2%}".format)
            display["Revenue"]   = display["Revenue"].map(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.markdown("")
        st.caption(
            "Sessions/Orders/Revenue are **all-time** GA4 totals matched by exact campaign name "
            "(same limitation as the sends/opens/clicks above — not period-scoped). Blank for "
            "steps with a generic, non-unique name (e.g. \"Email #1\", shared by many legacy "
            "flows) — matching those would misattribute one campaign's numbers to every other "
            "flow sharing that name."
        )


# ── SMS sections ─────────────────────────────────────────────────────────────

def render_sms_bb_section(ty_sms: pd.DataFrame, ly_sms: pd.DataFrame,
                          t_periods: list[Period], ty_ga4_sms: pd.DataFrame = None,
                          ty_ga4_program: pd.DataFrame = None, ly_ga4_program: pd.DataFrame = None) -> None:
    st.subheader("SMS — Batch & Blast")

    ty = _aggregate_sms(ty_sms)
    ly = _aggregate_sms(ly_sms)

    if ty["sends"] == 0:
        st.caption("No SMS sends in this period.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Sends", _comma(ty["sends"]),
                      delta=f"{(_delta_pct(ty['sends'], ly['sends']) or 0):.1%}" if ly["sends"] else None)
        with c2:
            st.metric("Delivery Rate", _pct(ty["delivery_rate"]),
                      delta=f"{(_delta_pct(ty['delivery_rate'], ly['delivery_rate']) or 0):.1%}" if ly["delivery_rate"] else None)
        with c3:
            st.metric("CTR", _pct(ty["click_rate"]),
                      delta=f"{(_delta_pct(ty['click_rate'], ly['click_rate']) or 0):.1%}" if ly["click_rate"] else None)
        with c4:
            st.metric("Opt-Outs", _comma(ty["unsubscribes"]),
                      delta=f"{(_delta_pct(ty['unsubscribes'], ly['unsubscribes']) or 0):.1%}" if ly["unsubscribes"] else None)

    # Sparkline — sends trend
    t_sends  = [_aggregate_sms(sms_campaigns_for_period(p))["sends"] for p in t_periods]
    t_labels = [p.label for p in t_periods]
    if any(t_sends):
        st.plotly_chart(
            _sparkline(t_sends, t_labels, "SMS Sends (trend)", fmt=",.0f"),
            use_container_width=True, config={"displayModeBar": False}, key="sms_sends_spark",
        )

    # Sessions + Revenue (GA4, batch/blast SMS only)
    ty_g = _ga4_vals(ty_ga4_program, "SMS", "B&B")
    ly_g = _ga4_vals(ly_ga4_program, "SMS", "B&B")
    _render_ga4_program_metrics(ty_g, ly_g, t_periods, "SMS", "B&B", key_prefix="sms_bb")

    if not ty_sms.empty:
        with st.expander(f"SMS campaign detail ({len(ty_sms)} campaigns)", expanded=False):
            enriched = _merge_ga4_by_name(ty_sms, ty_ga4_sms)
            display = enriched[["first_sent", "name", "body", "sends", "delivered",
                                 "delivery_rate", "unique_clicks", "click_rate", "unsubscribes",
                                 "ga4_sessions", "ga4_orders", "ga4_revenue"]].copy()
            display.columns = ["Date", "Campaign", "Body", "Sends", "Delivered",
                                "Delivery Rate", "Clicks", "CTR", "Opt-Outs",
                                "Sessions", "Orders", "Revenue"]
            display["Delivery Rate"] = display["Delivery Rate"].map("{:.1%}".format)
            display["CTR"]           = display["CTR"].map("{:.2%}".format)
            display["Revenue"]       = display["Revenue"].map(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.caption(
                "Sessions/Orders/Revenue from GA4, matched by exact campaign name. "
                "Blank = no GA4 session data found under that name for this period."
            )


def render_sms_flows_section(t_periods: list[Period] = None,
                             ty_ga4_program: pd.DataFrame = None, ly_ga4_program: pd.DataFrame = None) -> None:
    st.subheader("SMS — Triggered Flows")
    st.caption(
        "⚠️ Sends/Clicks below are **all-time totals** — not filtered to the selected period. "
        "Totals refresh periodically (weekly via GitLab CI, plus occasional manual runs) — "
        "not in real time like other brands' live datashare. Sessions/Revenue below, however, "
        "come from GA4 and ARE scoped to the selected period, same as SMS Batch & Blast."
    )

    flows = load_all_sms_flows()
    if flows.empty:
        st.caption("No SMS flow data found.")
        return

    total_sends  = int(flows["sends"].sum())
    total_clicks = int(flows["unique_clicks"].sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Active Flows", flows["canvas_name"].nunique())
    with c2:
        st.metric("Total Steps", len(flows))
    with c3:
        st.metric("All-Time Sends", _comma(total_sends))
    with c4:
        avg_ctr = _safe_div(total_clicks, total_sends)
        st.metric("Avg CTR", _pct(avg_ctr))

    if t_periods:
        ty_g = _ga4_vals(ty_ga4_program, "SMS", "Triggered")
        ly_g = _ga4_vals(ly_ga4_program, "SMS", "Triggered")
        _render_ga4_program_metrics(ty_g, ly_g, t_periods, "SMS", "Triggered", key_prefix="sms_trg")

    ga4_sms_flows = fetch_ga4_revenue_all_time("SMS")
    dup_names = _ambiguous_names(flows["name"])
    with st.expander("SMS flow catalog", expanded=False):
        for canvas_name, steps in flows.groupby("canvas_name", sort=True):
            st.markdown(f"**{canvas_name}**")
            enriched = _merge_ga4_by_name(steps, ga4_sms_flows, dup_names)
            display = enriched[["sequence_position", "name", "body", "sends", "delivered",
                                 "delivery_rate", "unique_clicks", "click_rate",
                                 "ga4_sessions", "ga4_orders", "ga4_revenue"]].copy()
            display.columns = ["Seq", "Step Name", "Body", "Sends", "Delivered", "Delivery Rate", "Clicks", "CTR",
                                "Sessions", "Orders", "Revenue"]
            display["Delivery Rate"] = display["Delivery Rate"].map("{:.1%}".format)
            display["CTR"]           = display["CTR"].map("{:.2%}".format)
            display["Revenue"]       = display["Revenue"].map(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.markdown("")
        st.caption(
            "Sessions/Orders/Revenue are **all-time** GA4 totals matched by exact campaign name "
            "(same limitation as the sends/clicks above — not period-scoped). Blank for steps "
            "with a generic, non-unique name (e.g. \"SMS #1\") — matching those would "
            "misattribute one campaign's numbers to every other flow sharing that name."
        )


# ── YOY charts ────────────────────────────────────────────────────────────────

def render_yoy_charts() -> None:
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

    def _chart(col_ty, col_ly, title, fmt=".0f"):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels, y=merged.get(col_ly, pd.Series(dtype=float)).tolist(),
            name="LY", mode="lines",
            line=dict(color=MUTED, width=1.5, dash="dot"),
            customdata=ly_labels,
            hovertemplate=f"%{{customdata}}<br>LY: %{{y:{fmt}}}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=labels, y=merged.get(col_ty, pd.Series(dtype=float)).tolist(),
            name="TY", mode="lines+markers",
            line=dict(color=ACCENT, width=2),
            marker=dict(size=4, color=ACCENT),
            hovertemplate=f"%{{x}}<br>TY: %{{y:{fmt}}}<extra></extra>"))
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
        st.plotly_chart(_chart("REVENUE_TY", "REVENUE_LY", "GA4 Email Revenue — TY vs LY", "$,.0f"),
                        use_container_width=True, key="yoy_revenue",
                        config={"displayModeBar": False})
    with c2:
        st.plotly_chart(_chart("SESSIONS_TY", "SESSIONS_LY", "GA4 Email Sessions — TY vs LY", ",.0f"),
                        use_container_width=True, key="yoy_sessions",
                        config={"displayModeBar": False})


# ── Monthly B&B trend ─────────────────────────────────────────────────────────

def render_sends_trend() -> None:
    """Monthly send volume and open rate over the last 12 months."""
    today = date.today()
    months: list[Period] = []
    for i in range(11, -1, -1):
        ms = _month_start(today, months_back=i)
        me = _month_end(ms) if i > 0 else today - timedelta(days=1)
        months.append(Period(ms, me, ms.strftime("%b '%y")))

    sends_vals  = []
    or_vals     = []
    labels      = [p.label for p in months]
    for p in months:
        agg = _aggregate_campaigns(campaigns_for_period(p))
        sends_vals.append(agg["sends"])
        or_vals.append(agg["open_rate"] or 0)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            _sparkline(sends_vals, labels, "Monthly Sends — Last 12 Months", ",.0f"),
            use_container_width=True, config={"displayModeBar": False}, key="monthly_sends")
    with c2:
        st.plotly_chart(
            _sparkline(or_vals, labels, "Monthly Open Rate — Last 12 Months", ".1%"),
            use_container_width=True, config={"displayModeBar": False}, key="monthly_or")


# ── Known data-quality issues ─────────────────────────────────────────────────

_DATA_ISSUES_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_data_issues.yaml"


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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="The Inside — Lifecycle Dashboard",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown("""
        <style>
        .block-container { padding-top: 1.5rem; }
        h1 { font-size: 1.6rem; }
        h2 { font-size: 1.2rem; border-bottom: 2px solid #2d6a4f; padding-bottom: 4px; }
        [data-testid="stMetricValue"] { font-size: 1.3rem; font-weight: 600; }
        </style>
    """, unsafe_allow_html=True)

    st.title("The Inside — Lifecycle Performance")

    # ── Period toggle ────────────────────────────────────────────────────────
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

    # ── Load data ────────────────────────────────────────────────────────────
    with st.spinner("Loading data…"):
        ty_camps = campaigns_for_period(ty_period)
        ly_camps = campaigns_for_period(ly_p)
        ty_sms   = sms_campaigns_for_period(ty_period)
        ly_sms   = sms_campaigns_for_period(ly_p)
        ty_ga4   = fetch_ga4_revenue(ty_period.start, ty_period.end)
        ly_ga4   = fetch_ga4_revenue(ly_p.start, ly_p.end)
        ty_ga4_sms = fetch_ga4_revenue_sms(ty_period.start, ty_period.end)
        ty_ga4_program = fetch_ga4_by_program(ty_period.start, ty_period.end)
        ly_ga4_program = fetch_ga4_by_program(ly_p.start, ly_p.end)

    render_analytics_freshness_warning(ty_camps, ty_sms)

    # ── Summary banner ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("At a Glance")
    render_summary_banner(ty_camps, ly_camps, ty_ga4, ly_ga4)
    st.markdown("---")

    # ── B&B section ──────────────────────────────────────────────────────────
    render_bb_section(ty_camps, ly_camps, t_periods, ty_ga4, ty_ga4_program, ly_ga4_program)
    st.markdown("---")

    # ── Triggered flows section ───────────────────────────────────────────────
    render_flows_section(t_periods, ty_ga4_program, ly_ga4_program)
    st.markdown("---")

    # ── SMS B&B section ───────────────────────────────────────────────────────
    render_sms_bb_section(ty_sms, ly_sms, t_periods, ty_ga4_sms, ty_ga4_program, ly_ga4_program)
    st.markdown("---")

    # ── SMS Triggered flows section ───────────────────────────────────────────
    render_sms_flows_section(t_periods, ty_ga4_program, ly_ga4_program)
    st.markdown("---")

    # ── Monthly trend (12 months) ─────────────────────────────────────────────
    st.subheader("Monthly Trends — Last 12 Months")
    render_sends_trend()
    st.markdown("---")

    # ── YOY charts ────────────────────────────────────────────────────────────
    st.subheader("Year over Year — Revenue & Sessions (GA4)")
    render_yoy_charts()

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "**Sources:** Email engagement (sends/opens/clicks) — Klaviyo via YAML archive, "
        "refreshed periodically (weekly via GitLab CI, plus occasional manual runs) — not a "
        "live datashare like other brands. "
        "Revenue & sessions — GA4 via Airbyte/Snowflake. "
        "Triggered flow metrics are all-time totals. "
        "LY = same period one year prior. "
        "Data coverage: Jul 2024 – present."
    )


if __name__ == "__main__":
    main()
