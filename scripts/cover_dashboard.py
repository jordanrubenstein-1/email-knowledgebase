"""
Lifecycle Marketing Dashboard — Cover Page
Multi-brand summary for ID, BUR, CZ, TI, STF.
Run: streamlit run scripts/cover_dashboard.py --server.port 8500
"""

import os
import sys
import threading
from pathlib import Path
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import traceback

import streamlit as st
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent.parent))
CAMPAIGNS_DIR = _HERE.parent.parent / "campaigns"

# ── Credentials ────────────────────────────────────────────────────────────────

def _load_credentials():
    try:
        sec = st.secrets["snowflake"]
        for key, val in sec.items():
            os.environ.setdefault(f"SNOWFLAKE_{key.upper()}", str(val))
    except (KeyError, FileNotFoundError):
        from dotenv import load_dotenv
        for _parent in _HERE.parents:
            if (_parent / ".env").exists():
                load_dotenv(_parent / ".env")
                break

_load_credentials()

from scripts.snowflake_client import SnowflakeClient  # noqa: E402

# ── Background wake-up pings ───────────────────────────────────────────────────
# On Streamlit Cloud, brand dashboards sleep when idle. Fire a GET request to
# each one as soon as the cover page loads so they're warm by the time the user
# clicks through. Runs in daemon threads — never blocks the cover page render.
#
# Streamlit reruns this whole module on every widget interaction, not just on
# first page load — guard on session_state so this only fires once per browser
# session instead of re-pinging (and re-waking) every brand app on every click.

def _ping_dashboards():
    if st.session_state.get("_dashboards_pinged"):
        return
    st.session_state["_dashboards_pinged"] = True
    try:
        import requests
        _deployed_urls = st.secrets.get("dashboard_urls", {})
    except Exception:
        return
    urls = [v for v in _deployed_urls.values() if v.startswith("http")]
    def _ping(url):
        try:
            requests.get(url, timeout=60)
        except Exception:
            pass
    for url in urls:
        t = threading.Thread(target=_ping, args=(url,), daemon=True)
        t.start()

_ping_dashboards()

# ── Brand configs ──────────────────────────────────────────────────────────────

BRANDS = [
    {
        "name": "Havenly", "code": "HAV", "port": 8504, "accent": "#5B7FA6",
        "hidden": True,
        "app_group_id": "664223fb71bcf3005760dfc2",
        "braze_db": "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206",
        "braze_schema": "DATALAKE_SHARING",
        "ga4_table": "AIRBYTE_DATABASE.LANDING_HAVENLY_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
    },
    {
        "name": "Interior Define", "code": "ID", "port": 8505, "accent": "#3E6D9C",
        "app_group_id": "6666726b459b5e0059d7d687",
        "braze_db": "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF",
        "braze_schema": "DATALAKE_SHARING_TIERED",
        "ga4_table": "AIRBYTE_DATABASE.LANDING_INTERIORDEFINE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
        # Confirmed bot/fraud signup-bombing traffic (2026-07) — excluded from live email metrics.
        "excluded_bot_emails": ["mmcloughlin@boarsheadresort.com", "laura@legallycopied.com", "cdelpriore@graceofny.org"],
    },
    {
        "name": "Burrow", "code": "BUR", "port": 8502, "accent": "#e94560",
        "app_group_id": "67093a1f24ebbe0065cb9c77",
        "braze_db": "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206",
        "braze_schema": "DATALAKE_SHARING",
        "ga4_table": "AIRBYTE_DATABASE.LANDING_BURROW_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
    },
    {
        "name": "The Citizenry", "code": "CZ", "port": 8503, "accent": "#C8A96E",
        "app_group_id": "666672a4d8965b005ac6c1bd",
        "braze_db": "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206",
        "braze_schema": "DATALAKE_SHARING",
        "ga4_table": "AIRBYTE_DATABASE.LANDING_CITIZENRY_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
    },
    {
        "name": "The Inside", "code": "TI", "port": 8510, "accent": "#2d6a4f",
        "email_source": "yaml",  # no Braze datashare — TI is Klaviyo; metrics from campaigns/*.yaml
        "ga4_table": "AIRBYTE_DATABASE.LANDING_THE_INSIDE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
    },
    {
        "name": "St. Frank", "code": "STF", "port": 8506, "accent": "#8B6F4E",
        "app_group_id": "666716b3858150005b566956",
        "braze_db": "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF",
        "braze_schema": "DATALAKE_SHARING_TIERED",
        "ga4_table": "AIRBYTE_DATABASE.LANDING_ST_FRANK_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY",
    },
]

MODES = ["Yesterday", "Last Week", "Last Month", "MTD", "QTD", "Last Quarter", "Custom"]

# ── Known data-issue banners (short cover-page version) ────────────────────────
# Full detail lives on each brand's own dashboard (render_data_issue_banners in
# lifecycle_dashboard_base.py); here we just surface a one-line flag so a viewer
# knows not to trust a metric before clicking through. Structural/always_show
# limitations (e.g. HAV's in-app attribution note) are intentionally excluded —
# those are permanent caveats, not dated incidents, and belong on the full page only.

_DATA_ISSUES_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_data_issues.yaml"
_METRIC_ORDER = ["revenue", "sessions", "orders"]
_SEVERITY_RANK = {"critical": 2, "warning": 1, "info": 0}
_SEVERITY_COLOR = {"critical": "#c0392b", "warning": "#b8860b", "info": "#2980b9"}


@st.cache_data(ttl=300, show_spinner=False)
def _load_data_issues() -> list:
    try:
        with open(_DATA_ISSUES_PATH) as f:
            return (yaml.safe_load(f) or {}).get("issues", []) or []
    except FileNotFoundError:
        return []


def _issue_overlaps(start, end, win_start, win_end) -> bool:
    if start is None:
        return False
    end = end or date.today()
    return start <= win_end and end >= win_start


def brand_issue_badge(brand_code: str, win_start: date, win_end: date) -> Optional[dict]:
    """Return {'label': ..., 'color': ...} for the worst dated, non-structural issue
    affecting brand_code that overlaps [win_start, win_end]; None if brand is clean."""
    matches = [
        i for i in _load_data_issues()
        if str(i.get("brand", "")).upper() == (brand_code or "").upper()
        and not i.get("always_show")
        and _issue_overlaps(i.get("start_date"), i.get("end_date"), win_start, win_end)
    ]
    if not matches:
        return None

    metrics = set()
    for i in matches:
        metrics.update(str(m).lower() for m in (i.get("metrics") or []))
    ordered = [m for m in _METRIC_ORDER if m in metrics] + sorted(metrics - set(_METRIC_ORDER))

    worst_sev = max((str(i.get("severity", "warning")).lower() for i in matches),
                    key=lambda s: _SEVERITY_RANK.get(s, 1))
    return {
        "label": f"{'/'.join(ordered)} data unreliable".capitalize(),
        "color": _SEVERITY_COLOR.get(worst_sev, "#b8860b"),
    }

# ── Period helpers ─────────────────────────────────────────────────────────────

def _month_start(ref: date, months_back: int = 0) -> date:
    t = ref.year * 12 + ref.month - 1 - months_back
    return date(t // 12, t % 12 + 1, 1)


def _month_end(d: date) -> date:
    return _month_start(d, months_back=-1) - timedelta(days=1)


def _quarter_start(d: date) -> date:
    return d.replace(month=((d.month - 1) // 3) * 3 + 1, day=1)


def get_period(mode: str) -> tuple[date, date, str]:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    if mode == "Yesterday":
        return yesterday, yesterday, yesterday.strftime("%-d %b %Y")
    if mode == "Last Week":
        sun = today - timedelta(days=today.weekday() + 1)
        mon = sun - timedelta(days=6)
        return mon, sun, f"{mon.strftime('%-d %b')} – {sun.strftime('%-d %b %Y')}"
    if mode == "Last Month":
        ms = _month_start(today, months_back=1)
        me = _month_end(ms)
        return ms, me, ms.strftime("%B %Y")
    if mode == "MTD":
        ms = today.replace(day=1)
        return ms, yesterday, f"{today.strftime('%B')} MTD"
    if mode == "QTD":
        qs = _quarter_start(today)
        q  = (today.month - 1) // 3 + 1
        return qs, yesterday, f"Q{q} {today.year} QTD"
    if mode == "Last Quarter":
        qs  = _quarter_start(today)
        lqs = _quarter_start(qs - timedelta(days=1))
        lqe = qs - timedelta(days=1)
        lq  = (lqs.month - 1) // 3 + 1
        return lqs, lqe, f"Q{lq} {lqs.year}"
    # fallback QTD
    qs = _quarter_start(today)
    q  = (today.month - 1) // 3 + 1
    return qs, yesterday, f"Q{q} {today.year} QTD"


def ly_dates(start: date, end: date, mode: str) -> tuple[date, date]:
    """Return LY start/end: 52-week shift for week/custom/yesterday, else calendar year-1."""
    if mode in ("Yesterday", "Last Week", "Custom"):
        return start - timedelta(weeks=52), end - timedelta(weeks=52)
    def _safe(d, y):
        try:
            return d.replace(year=y)
        except ValueError:
            return d.replace(year=y, day=28)
    return _safe(start, start.year - 1), _safe(end, end.year - 1)


# ── Query functions ────────────────────────────────────────────────────────────

def _braze_client(brand: dict) -> SnowflakeClient:
    return SnowflakeClient(schema=brand["braze_schema"], database=brand["braze_db"])


def _ga4_client(brand: dict) -> SnowflakeClient:
    parts = brand["ga4_table"].split(".")
    db, schema = parts[0], parts[1]
    return SnowflakeClient(schema=schema, database=db)


@st.cache_data(ttl=1800, show_spinner=False)
def _bot_email_sql_filter(excluded_bot_emails: Optional[list] = None) -> str:
    """SQL fragment excluding known bot/fraud email addresses from a datashare query.
    Empty string if none configured for this brand — safe to always append."""
    if not excluded_bot_emails:
        return ""
    emails = ", ".join("'" + e.lower().replace("'", "''") + "'" for e in excluded_bot_emails)
    return f"AND (EMAIL_ADDRESS IS NULL OR LOWER(EMAIL_ADDRESS) NOT IN ({emails}))"


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_email_metrics(
    app_group_id: str,
    braze_db: str,
    braze_schema: str,
    start: str,
    end: str,
    excluded_bot_emails: Optional[list] = None,
) -> dict:
    """Returns sends, unique_opens, unique_clicks, open_rate, ctr."""
    bot_filter = _bot_email_sql_filter(excluded_bot_emails)
    q = f"""
    WITH sends AS (
        SELECT COUNT(DISTINCT ID) AS sends
        FROM {braze_db}.{braze_schema}.USERS_MESSAGES_EMAIL_SEND_SHARED
        WHERE APP_GROUP_ID = '{app_group_id}'
          AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
          {bot_filter}
    ),
    opens AS (
        SELECT COUNT(*) AS unique_opens
        FROM (
            SELECT DISTINCT DISPATCH_ID, USER_ID
            FROM {braze_db}.{braze_schema}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{app_group_id}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {bot_filter}
        )
    ),
    clicks AS (
        SELECT COUNT(*) AS unique_clicks
        FROM (
            SELECT DISTINCT DISPATCH_ID, USER_ID
            FROM {braze_db}.{braze_schema}.USERS_MESSAGES_EMAIL_CLICK_SHARED
            WHERE APP_GROUP_ID = '{app_group_id}'
              AND TO_DATE(TO_TIMESTAMP(TIME)) BETWEEN '{start}' AND '{end}'
              {bot_filter}
        )
    )
    SELECT s.sends,
           COALESCE(o.unique_opens,  0) AS unique_opens,
           COALESCE(c.unique_clicks, 0) AS unique_clicks,
           CASE WHEN s.sends > 0 THEN COALESCE(o.unique_opens,  0)::FLOAT / s.sends END AS open_rate,
           CASE WHEN s.sends > 0 THEN COALESCE(c.unique_clicks, 0)::FLOAT / s.sends END AS ctr
    FROM sends s, opens o, clicks c
    """
    try:
        client = SnowflakeClient(schema=braze_schema, database=braze_db)
        rows = client.execute_query(q)
        if rows and rows[0]:
            r = {k.lower(): (v or 0) for k, v in rows[0].items()}
            return r
    except Exception:
        pass
    return {"sends": 0, "unique_opens": 0, "unique_clicks": 0, "open_rate": None, "ctr": None}


@st.cache_data(ttl=3600, show_spinner=False)
def _load_ti_campaigns() -> list[dict]:
    """TI batch email campaigns (klaviyo_type: campaign) read from the YAML knowledgebase.
    TI has no Braze raw-events datashare — this is the Klaviyo equivalent of fetch_email_metrics's
    source data. YAMLs sync from Klaviyo weekly, so recent days (e.g. Yesterday) may show as empty
    until the next sync, unlike the Braze brands which query live."""
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
            first_sent = datetime.fromisoformat(str(first_sent_str).replace("Z", "+00:00")).date()
        except Exception:
            continue
        perf = data.get("performance_summary") or {}
        rows.append({
            "first_sent":    first_sent,
            "sends":         perf.get("total_sends", 0) or 0,
            "unique_opens":  perf.get("unique_opens", 0) or 0,
            "unique_clicks": perf.get("unique_clicks", 0) or 0,
        })
    return rows


def fetch_ti_email_metrics(start: str, end: str) -> dict:
    """Returns sends, unique_opens, unique_clicks, open_rate, ctr — same shape as
    fetch_email_metrics, sourced from YAML instead of a Braze datashare query."""
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    sends = opens = clicks = 0
    for row in _load_ti_campaigns():
        if start_d <= row["first_sent"] <= end_d:
            sends  += row["sends"]
            opens  += row["unique_opens"]
            clicks += row["unique_clicks"]
    return {
        "sends": sends,
        "unique_opens": opens,
        "unique_clicks": clicks,
        "open_rate": (opens / sends) if sends else None,
        "ctr": (clicks / sends) if sends else None,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ga4_metrics(
    ga4_table: str,
    start: str,
    end: str,
) -> dict:
    """Returns revenue, sessions for Email+SMS lifecycle channels."""
    q = f"""
    SELECT SUM(TOTALREVENUE) AS revenue,
           SUM(SESSIONS)     AS sessions
    FROM {ga4_table}
    WHERE SESSIONPRIMARYCHANNELGROUP IN ('Email', 'SMS')
      AND TO_DATE(DATE, 'YYYYMMDD') BETWEEN '{start}' AND '{end}'
    """
    try:
        parts = ga4_table.split(".")
        db, schema = parts[0], parts[1]
        client = SnowflakeClient(schema=schema, database=db)
        rows = client.execute_query(q)
        if rows and rows[0]:
            r = {k.lower(): (v or 0) for k, v in rows[0].items()}
            return r
    except Exception:
        pass
    return {"revenue": 0, "sessions": 0}


def _fetch_brand_all(brand: dict, ty_start: str, ty_end: str, ly_start: str, ly_end: str) -> dict:
    """Fetch TY + LY email + GA4 for one brand. Called from ThreadPoolExecutor."""
    code = brand["code"]
    results = {
        "code": code,
        "ty_email": None,
        "ly_email": None,
        "ty_ga4":   None,
        "ly_ga4":   None,
        "error":    None,
    }
    try:
        if brand.get("email_source") == "yaml":
            results["ty_email"] = fetch_ti_email_metrics(ty_start, ty_end)
            results["ly_email"] = fetch_ti_email_metrics(ly_start, ly_end)
        else:
            results["ty_email"] = fetch_email_metrics(
                brand["app_group_id"], brand["braze_db"], brand["braze_schema"], ty_start, ty_end,
                excluded_bot_emails=brand.get("excluded_bot_emails"),
            )
            results["ly_email"] = fetch_email_metrics(
                brand["app_group_id"], brand["braze_db"], brand["braze_schema"], ly_start, ly_end,
                excluded_bot_emails=brand.get("excluded_bot_emails"),
            )
        results["ty_ga4"] = fetch_ga4_metrics(brand["ga4_table"], ty_start, ty_end)
        results["ly_ga4"] = fetch_ga4_metrics(brand["ga4_table"], ly_start, ly_end)
    except Exception as exc:
        results["error"] = str(exc)
    return results


# ── Formatting helpers ─────────────────────────────────────────────────────────

def fmt_compact(v) -> str:
    """Format currency compactly: $1.2M, $234K, $12K."""
    if v is None:
        return "—"
    v = float(v)
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{float(v)*100:.1f}%"


def fmt_num(v) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def delta_arrow(ty, ly, is_pct: bool = False) -> str:
    """Return colored delta string with arrow."""
    if ty is None or ly is None or ly == 0:
        return ""
    if is_pct:
        diff = float(ty) - float(ly)
        sign = "↑" if diff >= 0 else "↓"
        color = "green" if diff >= 0 else "red"
        return f'<span style="color:{color};font-size:0.8em">{sign} {abs(diff)*100:.1f}pp</span>'
    else:
        pct_chg = (float(ty) - float(ly)) / float(ly)
        sign = "↑" if pct_chg >= 0 else "↓"
        color = "green" if pct_chg >= 0 else "red"
        return f'<span style="color:{color};font-size:0.8em">{sign} {abs(pct_chg)*100:.0f}%</span>'


def delta_arrow_revenue(ty, ly) -> str:
    """Colored revenue delta."""
    if ty is None or ly is None or ly == 0:
        return ""
    diff = float(ty) - float(ly)
    pct  = diff / float(ly)
    sign = "↑" if pct >= 0 else "↓"
    color = "green" if pct >= 0 else "red"
    return f'<span style="color:{color};font-size:0.8em">{sign} {abs(pct)*100:.0f}% ({fmt_compact(abs(diff))})</span>'


# ── Main app ───────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Lifecycle Marketing Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # ── Global CSS ─────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    h1 { font-size: 1.8rem !important; margin-bottom: 0.2rem !important; }
    h2 { font-size: 1.2rem !important; margin-top: 1.2rem !important; }
    .metric-label { font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-value { font-size: 1.35rem; font-weight: 700; line-height: 1.1; }
    .metric-delta { font-size: 0.78rem; margin-top: 0.1rem; }
    .brand-card {
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 1rem 1.1rem 0.8rem;
        margin-bottom: 0.5rem;
        background: #fafafa;
    }
    .brand-card-title {
        font-weight: 700;
        font-size: 1.05rem;
        margin-bottom: 0.6rem;
    }
    .brand-metric-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.4rem 0.8rem;
        margin-bottom: 0.6rem;
    }
    .brand-metric-item { }
    table.glance { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    table.glance th { border-bottom: 2px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; color: #555; font-weight: 600; }
    table.glance td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }
    table.glance tr:last-child td { border-bottom: none; }
    .period-badge { background: #f0f0f0; border-radius: 6px; padding: 0.15rem 0.5rem; font-size: 0.78rem; color: #555; }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ─────────────────────────────────────────────────────────────────
    st.markdown("<h1>Lifecycle Marketing Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#888;margin-top:0'>All-brand summary · Email & SMS channels · Lifecycle GA4 revenue</p>", unsafe_allow_html=True)

    # ── Period toggle ───────────────────────────────────────────────────────────
    col_mode, col_spacer = st.columns([3, 7])
    with col_mode:
        mode = st.selectbox("Period", MODES, index=0, label_visibility="collapsed")

    # Custom date pickers
    today     = date.today()
    yesterday = today - timedelta(days=1)

    if mode == "Custom":
        c1, c2 = st.columns(2)
        with c1:
            custom_start = st.date_input("From", value=yesterday - timedelta(days=6), max_value=yesterday)
        with c2:
            custom_end   = st.date_input("To",   value=yesterday, max_value=yesterday)
        ty_start, ty_end = custom_start, custom_end
        period_label = f"{ty_start.strftime('%-d %b')} – {ty_end.strftime('%-d %b %Y')}"
    else:
        ty_start, ty_end, period_label = get_period(mode)

    ly_start, ly_end = ly_dates(ty_start, ty_end, mode)

    st.markdown(
        f'<span class="period-badge">📅 {period_label} vs LY {ly_start.strftime("%-d %b")}–{ly_end.strftime("%-d %b %Y")}</span>',
        unsafe_allow_html=True
    )
    st.markdown("<br>", unsafe_allow_html=True)

    ty_s, ty_e = str(ty_start), str(ty_end)
    ly_s, ly_e = str(ly_start), str(ly_end)

    # ── Fetch all brands in parallel ───────────────────────────────────────────
    brand_results = {}
    with st.spinner("Loading data for all brands…"):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_fetch_brand_all, brand, ty_s, ty_e, ly_s, ly_e): brand["code"]
                for brand in BRANDS if not brand.get("hidden")
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    result = future.result()
                    brand_results[code] = result
                except Exception as exc:
                    brand_results[code] = {
                        "code": code, "ty_email": None, "ly_email": None,
                        "ty_ga4": None, "ly_ga4": None, "error": str(exc),
                    }

    # ── Brand cards ─────────────────────────────────────────────────────────────
    st.subheader("At a Glance")

    try:
        _deployed_urls = st.secrets.get("dashboard_urls", {})
    except Exception:
        _deployed_urls = {}

    visible_brands = [b for b in BRANDS if not b.get("hidden")]
    cols = st.columns(len(visible_brands))
    for i, brand in enumerate(visible_brands):
        code = brand["code"]
        res  = brand_results.get(code, {})
        ty_e_ = res.get("ty_email") or {}
        ly_e_ = res.get("ly_email") or {}
        ty_g  = res.get("ty_ga4")   or {}
        ly_g  = res.get("ly_ga4")   or {}
        error = res.get("error")

        with cols[i]:
            accent = brand["accent"]
            st.markdown(
                f'<div style="border-left:4px solid {accent};padding-left:0.6rem;margin-bottom:0.4rem">'
                f'<span style="font-weight:700;font-size:1.05rem">{brand["name"]}</span></div>',
                unsafe_allow_html=True
            )

            if error:
                st.error(f"Data error: {error[:80]}")
            else:
                sends     = ty_e_.get("sends", 0)
                open_rate = ty_e_.get("open_rate")
                ctr       = ty_e_.get("ctr")
                sessions  = ty_g.get("sessions", 0)
                revenue   = ty_g.get("revenue", 0)

                ly_or      = ly_e_.get("open_rate")
                ly_ctr     = ly_e_.get("ctr")
                ly_sessions = ly_g.get("sessions", 0)
                ly_revenue  = ly_g.get("revenue", 0)
                ly_sends    = ly_e_.get("sends", 0)

                def _metric_block(label: str, value: str, delta_html: str) -> str:
                    return (
                        f'<div style="margin-bottom:0.5rem">'
                        f'<div class="metric-label">{label}</div>'
                        f'<div class="metric-value">{value}</div>'
                        f'<div class="metric-delta">{delta_html}</div>'
                        f'</div>'
                    )

                metrics_html = "".join([
                    _metric_block("Sends",     fmt_num(sends),    delta_arrow(sends, ly_sends)),
                    _metric_block("Open Rate", fmt_pct(open_rate), delta_arrow(open_rate, ly_or, is_pct=True)),
                    _metric_block("CTR",       fmt_pct(ctr),      delta_arrow(ctr, ly_ctr, is_pct=True)),
                    _metric_block("Sessions",  fmt_num(sessions), delta_arrow(sessions, ly_sessions)),
                    _metric_block("Revenue",   fmt_compact(revenue), delta_arrow_revenue(revenue, ly_revenue)),
                ])

                st.markdown(metrics_html, unsafe_allow_html=True)

            port = brand["port"]
            _url = _deployed_urls.get(brand["code"].lower(), f"http://localhost:{port}")
            st.markdown(
                f'<a href="{_url}" target="_blank" '
                f'style="display:inline-block;margin-top:0.4rem;padding:0.3rem 0.8rem;'
                f'background:{accent};color:#fff;border-radius:6px;text-decoration:none;'
                f'font-size:0.82rem;font-weight:600">→ Full Dashboard</a>',
                unsafe_allow_html=True
            )

            if brand.get("email_source") == "yaml":
                st.markdown(
                    '<div style="margin-top:0.4rem;font-size:0.72rem;color:#999">'
                    'Sends = Batch &amp; Blast only (Klaviyo triggered flows not included)</div>',
                    unsafe_allow_html=True
                )

            badge = brand_issue_badge(code, ty_start, ty_end)
            if badge:
                st.markdown(
                    f'<div style="margin-top:0.4rem;display:flex;align-items:center;gap:5px;'
                    f'font-size:0.72rem;color:{badge["color"]}">⚠️ {badge["label"]}</div>',
                    unsafe_allow_html=True
                )

    # ── Footer ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f'<p style="color:#aaa;font-size:0.75rem">Data refreshes every 30 min. '
        f'Lifecycle = Email + SMS GA4 channel groups. Email metrics from Braze datashare '
        f'(TI from Klaviyo YAMLs, synced weekly — recent days may show as empty). '
        f'LY = {ly_start.strftime("%-d %b %Y")} – {ly_end.strftime("%-d %b %Y")}.</p>',
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
