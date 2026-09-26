"""
Email Deliverability Dashboard — Braze brands (BUR · HAV · CZ)

Replicates and extends the domain-breakdown report from
scripts/analysis/deliverability_by_domain.py, adding:
  - Brand tabs (BUR, HAV, CZ)
  - Interactive date-range selector with presets
  - Daily trend chart (delivery rate, hard bounce rate, complaint rate)

Run locally:
    python3 -m streamlit run scripts/deliverability_dashboard.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

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

DB     = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"

BRANDS: dict[str, dict] = {
    "BUR": {"name": "Burrow",        "app_group_id": "67093a1f24ebbe0065cb9c77", "color": "#FF6B35"},
    "HAV": {"name": "Havenly",       "app_group_id": "664223fb71bcf3005760dfc2", "color": "#2d6a4f"},
    "CZ":  {"name": "The Citizenry", "app_group_id": "666672a4d8965b005ac6c1bd", "color": "#8B6914"},
}

MODES = ["Last 7 days", "Last 30 days", "MTD", "Last Month", "Custom"]

# ── Period helpers ────────────────────────────────────────────────────────────

@dataclass
class Period:
    start: date
    end:   date
    label: str


def _month_start(ref: date, months_back: int = 0) -> date:
    t = ref.year * 12 + ref.month - 1 - months_back
    return date(t // 12, t % 12 + 1, 1)


def _month_end(d: date) -> date:
    return _month_start(d, months_back=-1) - timedelta(days=1)


def get_period(mode: str, custom_start: Optional[date] = None, custom_end: Optional[date] = None) -> Period:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    if mode == "Last 7 days":
        start = today - timedelta(days=7)
        return Period(start, yesterday, f"{start.strftime('%-d %b')} – {yesterday.strftime('%-d %b %Y')}")
    if mode == "Last 30 days":
        start = today - timedelta(days=30)
        return Period(start, yesterday, f"{start.strftime('%-d %b')} – {yesterday.strftime('%-d %b %Y')}")
    if mode == "MTD":
        start = today.replace(day=1)
        return Period(start, yesterday, f"{today.strftime('%B')} MTD")
    if mode == "Last Month":
        ms = _month_start(today, months_back=1)
        me = _month_end(ms)
        return Period(ms, me, ms.strftime("%B %Y"))
    # Custom
    s = custom_start or (today - timedelta(days=7))
    e = custom_end   or yesterday
    return Period(s, e, f"{s.strftime('%-d %b')} – {e.strftime('%-d %b %Y')}")

def get_prior_period(period: Period) -> Period:
    """Return a period of equal length immediately preceding `period`."""
    length = (period.end - period.start).days + 1
    prior_end   = period.start - timedelta(days=1)
    prior_start = prior_end   - timedelta(days=length - 1)
    return Period(
        prior_start, prior_end,
        f"{prior_start.strftime('%-d %b')} – {prior_end.strftime('%-d %b %Y')}",
    )

# ── Snowflake queries ─────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_client() -> SnowflakeClient:
    return SnowflakeClient(schema=SCHEMA, database=DB)


def _q(sql: str) -> list[dict]:
    return _get_client().execute_query(sql)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_domain_breakdown(app_group_id: str, start: str, end_exclusive: str, limit: int) -> pd.DataFrame:
    sql = f"""
WITH sends AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT ID) AS sent
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
deliveries AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT ID) AS delivered
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_DELIVERY_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
soft_bounces AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT ID) AS soft_bounces
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
hard_bounces AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT ID) AS hard_bounces
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
opens AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS opens_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
clicks AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS clicks_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
    GROUP BY 1
),
complaints AS (
    SELECT LOWER(SPLIT_PART(EMAIL_ADDRESS, '@', 2)) AS domain,
           COUNT(DISTINCT ID) AS complaints
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_MARKASSPAM_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
)
SELECT
    s.domain                                                                       AS DOMAIN,
    s.sent                                                                         AS SENT,
    COALESCE(d.delivered,     0)                                                   AS DELIVERED,
    ROUND(COALESCE(d.delivered,     0) / NULLIF(s.sent, 0) * 100, 2)              AS DELIVERY_RATE,
    COALESCE(sb.soft_bounces, 0)                                                   AS SOFT_BOUNCES,
    ROUND(COALESCE(sb.soft_bounces, 0) / NULLIF(s.sent, 0) * 100, 2)             AS SOFT_BOUNCE_RATE,
    COALESCE(hb.hard_bounces, 0)                                                   AS HARD_BOUNCES,
    ROUND(COALESCE(hb.hard_bounces, 0) / NULLIF(s.sent, 0) * 100, 2)             AS HARD_BOUNCE_RATE,
    COALESCE(o.opens_unique,  0)                                                   AS OPENS_UNIQUE,
    ROUND(COALESCE(o.opens_unique,  0) / NULLIF(s.sent, 0) * 100, 2)             AS OPEN_UNIQUE_RATE,
    COALESCE(cl.clicks_unique, 0)                                                  AS CLICKS_UNIQUE,
    ROUND(COALESCE(cl.clicks_unique, 0) / NULLIF(s.sent, 0) * 100, 2)            AS CLICKS_UNIQUE_RATE,
    COALESCE(c.complaints,    0)                                                   AS COMPLAINTS,
    ROUND(COALESCE(c.complaints,    0) / NULLIF(s.sent, 0) * 100, 4)             AS COMPLAINT_RATE
FROM sends s
LEFT JOIN deliveries   d  ON s.domain = d.domain
LEFT JOIN soft_bounces sb ON s.domain = sb.domain
LEFT JOIN hard_bounces hb ON s.domain = hb.domain
LEFT JOIN opens        o  ON s.domain = o.domain
LEFT JOIN clicks       cl ON s.domain = cl.domain
LEFT JOIN complaints   c  ON s.domain = c.domain
ORDER BY s.sent DESC
LIMIT {limit}
"""
    rows = _q(sql)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_daily_trend(app_group_id: str, start: str, end_exclusive: str) -> pd.DataFrame:
    sql = f"""
WITH sends AS (
    SELECT DATE_TRUNC('day', TO_TIMESTAMP(TIME)) AS day,
           COUNT(DISTINCT ID) AS sent
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
deliveries AS (
    SELECT DATE_TRUNC('day', TO_TIMESTAMP(TIME)) AS day,
           COUNT(DISTINCT ID) AS delivered
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_DELIVERY_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
hard_bounces AS (
    SELECT DATE_TRUNC('day', TO_TIMESTAMP(TIME)) AS day,
           COUNT(DISTINCT ID) AS hard_bounces
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_BOUNCE_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
),
complaints AS (
    SELECT DATE_TRUNC('day', TO_TIMESTAMP(TIME)) AS day,
           COUNT(DISTINCT ID) AS complaints
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_MARKASSPAM_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}'
      AND TO_TIMESTAMP(TIME) <  '{end_exclusive}'
    GROUP BY 1
)
SELECT
    s.day                                                                          AS DAY,
    s.sent                                                                         AS SENT,
    LEAST(ROUND(COALESCE(d.delivered, 0) / NULLIF(s.sent, 0) * 100, 2), 100)    AS DELIVERY_RATE,
    ROUND(COALESCE(hb.hard_bounces,0) / NULLIF(s.sent, 0) * 100, 2)             AS HARD_BOUNCE_RATE,
    ROUND(COALESCE(c.complaints,   0) / NULLIF(s.sent, 0) * 100, 4)             AS COMPLAINT_RATE
FROM sends s
LEFT JOIN deliveries   d  ON s.day = d.day
LEFT JOIN hard_bounces hb ON s.day = hb.day
LEFT JOIN complaints   c  ON s.day = c.day
ORDER BY s.day
"""
    rows = _q(sql)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["DAY"] = pd.to_datetime(df["DAY"])
    return df

# ── Styling helpers ───────────────────────────────────────────────────────────

def _style_delivery_rate(val):
    if pd.isna(val):
        return ""
    if val >= 99:
        return "background-color: #d4edda; color: #155724; font-weight: 600"
    if val < 95:
        return "background-color: #ea4335; color: #ffffff; font-weight: 600"
    return "background-color: #fff3cd; color: #856404; font-weight: 600"


def _style_hard_bounce(val):
    if pd.isna(val):
        return ""
    if val > 0.5:
        return "background-color: #ea4335; color: #ffffff; font-weight: 600"
    if val > 0.1:
        return "background-color: #fff3cd; color: #856404; font-weight: 600"
    return ""


def _style_complaint(val):
    if pd.isna(val):
        return ""
    if val > 0.08:
        return "background-color: #ea4335; color: #ffffff; font-weight: 600"
    if val > 0.03:
        return "background-color: #fff3cd; color: #856404; font-weight: 600"
    return ""


def _style_open_rate(val):
    if pd.isna(val):
        return ""
    if val >= 20:
        return "background-color: #d4edda; color: #155724; font-weight: 600"
    return ""


def apply_table_style(df: pd.DataFrame, display_cols: dict) -> pd.io.formats.style.Styler:
    """Apply color highlights and number formatting, then rename columns for display.

    Must be called with original (pre-rename) column names still present.
    """
    # Number formatting — commas for integers, % suffix for rates
    fmt: dict[str, str] = {}
    for c in df.columns:
        if c in ("SENT", "DELIVERED", "SOFT_BOUNCES", "HARD_BOUNCES",
                 "OPENS_UNIQUE", "CLICKS_UNIQUE", "COMPLAINTS"):
            fmt[c] = "{:,.0f}"
        elif c == "COMPLAINT_RATE":
            fmt[c] = "{:.4f}%"
        elif "RATE" in c:
            fmt[c] = "{:.2f}%"

    styler = df.style.format(fmt)

    if "DELIVERY_RATE" in df.columns:
        styler = styler.map(_style_delivery_rate, subset=["DELIVERY_RATE"])
    if "HARD_BOUNCE_RATE" in df.columns:
        styler = styler.map(_style_hard_bounce, subset=["HARD_BOUNCE_RATE"])
    if "COMPLAINT_RATE" in df.columns:
        styler = styler.map(_style_complaint, subset=["COMPLAINT_RATE"])
    if "OPEN_UNIQUE_RATE" in df.columns:
        styler = styler.map(_style_open_rate, subset=["OPEN_UNIQUE_RATE"])

    # Rename columns for display after styling so subset names still match
    styler = styler.relabel_index(
        [display_cols.get(c, c) for c in df.columns], axis="columns"
    )
    return styler

# ── Trend chart ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_overview_stats(app_group_id: str, start: str, end_exclusive: str) -> dict:
    """Single-row aggregate: sent, delivery rate, open rate, click rate."""
    sql = f"""
WITH sends AS (
    SELECT COUNT(DISTINCT ID) AS sent
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}' AND TO_TIMESTAMP(TIME) < '{end_exclusive}'
),
deliveries AS (
    SELECT COUNT(DISTINCT ID) AS delivered
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_DELIVERY_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}' AND TO_TIMESTAMP(TIME) < '{end_exclusive}'
),
opens AS (
    SELECT COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS opens_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}' AND TO_TIMESTAMP(TIME) < '{end_exclusive}'
),
clicks AS (
    SELECT COUNT(DISTINCT USER_ID || '|' || DISPATCH_ID) AS clicks_unique
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{app_group_id}'
      AND TO_TIMESTAMP(TIME) >= '{start}' AND TO_TIMESTAMP(TIME) < '{end_exclusive}'
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
)
SELECT
    s.sent,
    COALESCE(d.delivered,    0)                                          AS delivered,
    COALESCE(o.opens_unique, 0)                                          AS opens_unique,
    COALESCE(c.clicks_unique,0)                                          AS clicks_unique,
    ROUND(COALESCE(d.delivered,    0) / NULLIF(s.sent, 0) * 100, 2)    AS delivery_rate,
    ROUND(COALESCE(o.opens_unique, 0) / NULLIF(s.sent, 0) * 100, 2)    AS open_rate,
    ROUND(COALESCE(c.clicks_unique,0) / NULLIF(s.sent, 0) * 100, 2)    AS click_rate
FROM sends s, deliveries d, opens o, clicks c
"""
    rows = _q(sql)
    return dict(rows[0]) if rows else {}


INT_COLS = {"SENT", "DELIVERED", "SOFT_BOUNCES", "HARD_BOUNCES",
            "OPENS_UNIQUE", "CLICKS_UNIQUE", "COMPLAINTS"}


def _fmt_cell(val, col_key: str) -> str:
    if col_key == "DOMAIN":
        return str(val)
    if col_key in INT_COLS:
        return f"{int(val):,}"
    if col_key == "COMPLAINT_RATE":
        return f"{float(val):.4f}%"
    if "RATE" in col_key:
        return f"{float(val):.2f}%"
    return str(val)


def _cell_bg(val, col_key: str) -> str:
    """Return inline style string for highlighted cells, or ''."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return ""
    if col_key == "DELIVERY_RATE":
        return _style_delivery_rate(f)
    if col_key == "HARD_BOUNCE_RATE":
        return _style_hard_bounce(f)
    if col_key == "COMPLAINT_RATE":
        return _style_complaint(f)
    if col_key == "OPEN_UNIQUE_RATE":
        return _style_open_rate(f)
    return ""


def render_domain_table(df: pd.DataFrame, display_cols: dict) -> None:
    """Render the domain breakdown as a sticky-first-column HTML table."""
    cols = [c for c in display_cols if c in df.columns]

    header_cells = "<th>#</th>" + "".join(
        f"<th>{display_cols[c]}</th>" for c in cols
    )

    body_rows = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        cells = [f'<td class="sticky-col row-num">{i}</td>']
        for j, col in enumerate(cols):
            val   = row.get(col, 0) or 0
            txt   = _fmt_cell(val, col)
            style = _cell_bg(val, col)
            extra = ' class="sticky-col"' if j == 0 else ""
            cells.append(f'<td{extra}{" style=" + repr(style) if style else ""}>{txt}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    html = f"""
<style>
  .tbl-wrap {{
    overflow-x: auto;
    max-height: 520px;
    overflow-y: auto;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 13px;
  }}
  table {{
    border-collapse: collapse;
    width: max-content;
    min-width: 100%;
    background: #fff;
  }}
  th {{
    position: sticky;
    top: 0;
    background: #f4f4f4;
    border: 1px solid #e0e0e0;
    padding: 7px 10px;
    font-weight: 600;
    white-space: nowrap;
    font-size: 12px;
    z-index: 2;
  }}
  td {{
    border: 1px solid #e8e8e8;
    padding: 6px 10px;
    white-space: nowrap;
    background: #fff;
  }}
  tr:nth-child(even) td {{ background: #fdfdfb; }}
  tr:hover td {{ background: #f5f5f5 !important; }}
  .sticky-col {{
    position: sticky;
    left: 0;
    z-index: 1;
    background: inherit;
  }}
  th:nth-child(1), th:nth-child(2) {{
    position: sticky;
    z-index: 3;
  }}
  th:nth-child(1) {{ left: 0; }}
  th:nth-child(2) {{ left: 32px; }}
  td.row-num {{
    left: 0;
    color: #999;
    font-size: 11px;
    width: 28px;
    text-align: right;
    padding-right: 6px;
  }}
  td.sticky-col:not(.row-num) {{ left: 32px; font-weight: 500; }}
</style>
<div class="tbl-wrap">
  <table>
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{"".join(body_rows)}</tbody>
  </table>
</div>
"""
    components.html(html, height=560, scrolling=False)


CHART_COLORS = {
    "delivery":    "#1976D2",  # blue
    "hard_bounce": "#D32F2F",  # red
    "complaint":   "#7B1FA2",  # purple
}


def render_trend_chart(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No trend data for this period.")
        return

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["DAY"], y=df["DELIVERY_RATE"],
        name="Delivery Rate %",
        mode="lines+markers",
        line=dict(color=CHART_COLORS["delivery"], width=2),
        marker=dict(size=5),
        yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=df["DAY"], y=df["HARD_BOUNCE_RATE"],
        name="Hard Bounce Rate %",
        mode="lines+markers",
        line=dict(color=CHART_COLORS["hard_bounce"], width=2),
        marker=dict(size=5),
        yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=df["DAY"], y=df["COMPLAINT_RATE"],
        name="Complaint Rate %",
        mode="lines+markers",
        line=dict(color=CHART_COLORS["complaint"], width=2),
        marker=dict(size=5),
        yaxis="y2",
    ))

    # Threshold reference lines on y1
    fig.add_hline(y=99, line=dict(color="#d4edda", width=1, dash="dot"),
                  annotation_text="99% target", annotation_position="top left",
                  yref="y1")
    fig.add_hline(y=95, line=dict(color="#ea4335", width=1, dash="dot"),
                  annotation_text="95% floor", annotation_position="bottom left",
                  yref="y1")

    fig.update_layout(
        height=340,
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(
            title="Delivery Rate %",
            range=[max(0, (df["DELIVERY_RATE"].min() or 90) - 2), 100.5],
            showgrid=True, gridcolor="#f0f0f0",
        ),
        yaxis2=dict(
            title="Bounce / Complaint %",
            overlaying="y", side="right",
            range=[0, max(2, float(df["HARD_BOUNCE_RATE"].max() or 1) * 3)],
            showgrid=False,
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    st.plotly_chart(fig, use_container_width=True)

# ── Overview banner ───────────────────────────────────────────────────────────

def _fmt_large(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def _delta(curr_val: float, prior_val: float, is_count: bool = False) -> tuple[str, str]:
    """Return (formatted delta string, CSS color). Rates → pp delta; counts → % change."""
    if not prior_val:
        return "—", "#a78bfa"
    if is_count:
        pct = (curr_val - prior_val) / prior_val * 100
        txt = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    else:
        pp = curr_val - prior_val
        txt = f"+{pp:.2f}pp" if pp >= 0 else f"{pp:.2f}pp"
    color = "#86efac" if (curr_val >= prior_val) else "#fca5a5"
    return txt, color


def render_overview_banner(curr: dict, prior: dict, prior_label: str) -> None:
    if not curr:
        return

    sent_curr  = int(curr.get("SENT", 0) or 0)
    sent_prior = int(prior.get("SENT", 0) or 0)

    def g(key):
        return float(curr.get(key) or 0), float(prior.get(key) or 0)

    dr_c, dr_p   = g("DELIVERY_RATE")
    or_c, or_p   = g("OPEN_RATE")
    cr_c, cr_p   = g("CLICK_RATE")

    sent_delta,  sent_color  = _delta(sent_curr,  sent_prior,  is_count=True)
    dr_delta,    dr_color    = _delta(dr_c,  dr_p)
    or_delta,    or_color    = _delta(or_c,  or_p)
    cr_delta,    cr_color    = _delta(cr_c,  cr_p)

    metrics = [
        ("Emails Sent",       _fmt_large(sent_curr),   f"{sent_curr:,}",        sent_delta,  sent_color),
        ("Delivery Rate",     f"{dr_c:.1f}%",          f"{dr_p:.1f}%",          dr_delta,    dr_color),
        ("Unique Open Rate",  f"{or_c:.1f}%",          f"{or_p:.1f}%",          or_delta,    or_color),
        ("Unique Click Rate", f"{cr_c:.2f}%",          f"{cr_p:.2f}%",          cr_delta,    cr_color),
    ]

    cards_parts = []
    for i, (label, value, prior_value, delta_txt, delta_color) in enumerate(metrics):
        border = "border-right:1px solid #e2e8f0;" if i < len(metrics) - 1 else ""
        delta_color_css = "#16a34a" if delta_color == "#86efac" else "#dc2626"
        cards_parts.append(
            f'<div style="text-align:center;flex:1;padding:0 24px;{border}">'
            f'<div style="font-size:48px;font-weight:700;color:#1e293b;line-height:1.05;letter-spacing:-1px">{value}</div>'
            f'<div style="font-size:11px;font-weight:600;color:#64748b;margin-top:8px;text-transform:uppercase;letter-spacing:1.2px">{label}</div>'
            f'<div style="margin-top:18px;font-size:20px;font-weight:700;color:{delta_color_css}">{delta_txt}</div>'
            f'<div style="font-size:11px;color:#94a3b8;margin-top:4px">vs. {prior_label} &nbsp;({prior_value})</div>'
            f'</div>'
        )

    html = (
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;'
        'padding:32px 24px;box-shadow:0 1px 4px rgba(0,0,0,0.06);margin-bottom:4px;">'
        '<div style="display:flex;justify-content:space-around;align-items:flex-start">'
        + "".join(cards_parts)
        + '</div></div>'
    )
    components.html(html, height=220, scrolling=False)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Email Deliverability",
        page_icon="📬",
        layout="wide",
    )

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("📬 Deliverability")
        st.markdown("---")

        mode = st.selectbox("Period", MODES, index=0)

        custom_start: Optional[date] = None
        custom_end:   Optional[date] = None
        if mode == "Custom":
            today = date.today()
            custom_start = st.date_input("Start date", value=today - timedelta(days=7),
                                          max_value=today - timedelta(days=1))
            custom_end   = st.date_input("End date",   value=today - timedelta(days=1),
                                          min_value=custom_start, max_value=today - timedelta(days=1))

        limit = st.selectbox("Top domains", [25, 50, 100], index=1)

        st.markdown("---")
        st.caption("Data: Braze Raw Events Datashare\nBrands: BUR · HAV · CZ")

    period       = get_period(mode, custom_start, custom_end)
    prior_period = get_prior_period(period)
    end_exclusive       = (period.end       + timedelta(days=1)).isoformat()
    prior_end_exclusive = (prior_period.end + timedelta(days=1)).isoformat()

    st.header(f"Email Deliverability — {period.label}")

    # ── Brand tabs ────────────────────────────────────────────────────────────
    tabs = st.tabs([f"{BRANDS[code]['name']} ({code})" for code in BRANDS])

    for tab, (code, brand) in zip(tabs, BRANDS.items()):
        with tab:
            app_group_id = brand["app_group_id"]

            with st.spinner(f"Loading {brand['name']} data…"):
                curr_stats = fetch_overview_stats(
                    app_group_id, period.start.isoformat(), end_exclusive
                )
                prior_stats = fetch_overview_stats(
                    app_group_id, prior_period.start.isoformat(), prior_end_exclusive
                )
                df_domains = fetch_domain_breakdown(
                    app_group_id, period.start.isoformat(), end_exclusive, limit
                )
                df_trend = fetch_daily_trend(
                    app_group_id, period.start.isoformat(), end_exclusive
                )

            if not curr_stats and df_domains.empty:
                st.warning(f"No send data for {brand['name']} in this period.")
                continue

            # Overview banner
            render_overview_banner(curr_stats, prior_stats, prior_period.label)

            st.markdown("---")

            # Trend chart
            st.subheader("Daily Trend")
            render_trend_chart(df_trend)

            st.markdown("---")

            # Domain breakdown table
            st.subheader(f"Receiver Domain Breakdown — Top {len(df_domains)}")

            display_cols = {
                "DOMAIN":            "Domain",
                "SENT":              "Sent",
                "DELIVERED":         "Delivered",
                "DELIVERY_RATE":     "Delivery %",
                "SOFT_BOUNCES":      "Soft Bounces",
                "SOFT_BOUNCE_RATE":  "Soft Bounce %",
                "HARD_BOUNCES":      "Hard Bounces",
                "HARD_BOUNCE_RATE":  "Hard Bounce %",
                "OPENS_UNIQUE":      "Opens (Uniq)",
                "OPEN_UNIQUE_RATE":  "Open %",
                "CLICKS_UNIQUE":     "Clicks (Uniq)",
                "CLICKS_UNIQUE_RATE":"Click %",
                "COMPLAINTS":        "Complaints",
                "COMPLAINT_RATE":    "Complaint %",
            }
            render_domain_table(df_domains, display_cols)


if __name__ == "__main__":
    main()
