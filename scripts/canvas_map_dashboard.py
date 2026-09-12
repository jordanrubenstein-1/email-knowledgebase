"""
Lifecycle Canvas Map Dashboard — Streamlit app

Shows email creative thumbnails + performance metrics for every active
lifecycle canvas across all brands. Run alongside the other dashboards:

    streamlit run scripts/canvas_map_dashboard.py --server.port 8507
    # or via: bash scripts/start_dashboards.sh
"""

import base64
import fnmatch
import io
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))        # scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Lifecycle Canvas Map",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Import canvas definitions from the HTML dashboard script ─────────────────
# Re-use the same CANVASES config, BRAND_SNOWFLAKE, CANVAS_IDS, GA4_PATTERNS, etc.
from lifecycle_canvas_map_dashboard import (
    CANVASES,
    BRAND_SNOWFLAKE,
    RENDERED,
    fetch_klaviyo_stats_batch,
    fmt_n,
    fmt_pct,
)


# ── Batch stats fetcher (Braze brands) ───────────────────────────────────────

def _ilike(s: str, pattern: str) -> bool:
    """Python equivalent of SQL ILIKE — case-insensitive, % and _ wildcards."""
    py_pat = pattern.upper().replace("%", "*").replace("_", "?")
    return fnmatch.fnmatchcase((s or "").upper(), py_pat)


def fetch_all_stats_batch(brand: str, rows: list, client) -> dict:
    """
    Fetch 12-week rolling stats for ALL canvas rows in a brand.

    Replaces calling fetch_stats() once per row. Reduces from ~3-4 Snowflake
    queries per row to ~5 queries total for the entire brand, regardless of
    how many canvas rows exist.

    Returns a dict keyed by row['name'], same structure as fetch_stats().
    """
    cfg = BRAND_SNOWFLAKE[brand]
    db, schema, app = cfg["db"], cfg["schema"], cfg["app_group_id"]

    # ── Classify each row ─────────────────────────────────────────────────
    # sends_ch: which table counts "total sends" for this row
    # t1_ch:    which table the T1 step lives in
    classified = []
    for row in rows:
        ids = row.get("canvas_ids", [])
        t1_step = next(
            (s for s in row["steps"] if s.get("t", "").lstrip().startswith("T1")),
            row["steps"][0] if row["steps"] else {},
        )
        t1_ch = t1_step.get("channel", "email")
        is_sms_only = all(s.get("channel") == "sms" for s in row["steps"])
        sends_ch = "sms" if is_sms_only else "email"
        t1_filter = row.get("t1_step_filter", "%_T1%")
        classified.append((row, ids, sends_ch, t1_ch, t1_filter, is_sms_only))

    # ── Collect canvas IDs needed per table ───────────────────────────────
    email_ids = set()
    sms_ids   = set()
    push_ids  = set()
    for row, ids, sends_ch, t1_ch, _, _ in classified:
        if sends_ch == "email":
            email_ids.update(ids)
        else:
            sms_ids.update(ids)
        if t1_ch == "sms":
            sms_ids.update(ids)
        elif t1_ch == "push":
            push_ids.update(ids)

    def run_sends_query(canvas_ids, channel):
        if not canvas_ids:
            return {}
        ids_sql = ", ".join(f"'{i}'" for i in canvas_ids)
        if channel == "push":
            table = f"{db}.{schema}.USERS_MESSAGES_PUSHNOTIFICATION_SEND_SHARED"
        else:
            ch_upper = {"email": "EMAIL", "sms": "SMS"}[channel]
            table = f"{db}.{schema}.USERS_MESSAGES_{ch_upper}_SEND_SHARED"
        rows_data = client.execute_query(f"""
            SELECT CANVAS_ID, CANVAS_STEP_NAME,
                   COUNT(DISTINCT ID)      AS n,
                   COUNT(DISTINCT USER_ID) AS u
            FROM {table}
            WHERE APP_GROUP_ID = '{app}' AND CANVAS_ID IN ({ids_sql})
              AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
            GROUP BY CANVAS_ID, CANVAS_STEP_NAME
        """)
        result: dict = {}
        for r in rows_data:
            cid   = r.get("CANVAS_ID")
            sname = r.get("CANVAS_STEP_NAME") or ""
            result.setdefault(cid, {})[sname] = {"n": r.get("N") or 0, "u": r.get("U") or 0}
        return result

    def run_opens_query(canvas_ids):
        if not canvas_ids:
            return {}
        ids_sql = ", ".join(f"'{i}'" for i in canvas_ids)
        rows_data = client.execute_query(f"""
            SELECT CANVAS_ID, COUNT(DISTINCT USER_ID) AS o
            FROM {db}.{schema}.USERS_MESSAGES_EMAIL_OPEN_SHARED
            WHERE APP_GROUP_ID = '{app}' AND CANVAS_ID IN ({ids_sql})
              AND TO_TIMESTAMP(TIME) >= DATEADD('week', -12, CURRENT_TIMESTAMP())
            GROUP BY CANVAS_ID
        """)
        return {r["CANVAS_ID"]: r.get("O") or 0 for r in rows_data}

    def run_ga4_query():
        ga4_rows = [
            (row["name"], row["ga4_pattern"], row.get("ga4_channel", "EMAIL"))
            for row, ids, *_ in classified
            if row.get("ga4_pattern") and ids
        ]
        if not ga4_rows:
            return {}
        where_parts = " OR ".join(
            f"SESSIONCAMPAIGNNAME ILIKE '{pat}'" for _, pat, _ in ga4_rows
        )
        rows_data = client.execute_query(f"""
            SELECT SESSIONCAMPAIGNNAME,
                   UPPER(SESSIONPRIMARYCHANNELGROUP) AS ch,
                   SUM(SESSIONS)     AS sess,
                   SUM(TOTALREVENUE) AS rev
            FROM AIRBYTE_DATABASE.{cfg['ga4']}.TRAFFIC_SESSION_PERFORMANCE_DAILY
            WHERE DATE >= TO_CHAR(DATEADD('week', -12, CURRENT_DATE()), 'YYYYMMDD')
              AND UPPER(SESSIONPRIMARYCHANNELGROUP) IN ('EMAIL', 'SMS')
              AND ({where_parts})
            GROUP BY SESSIONCAMPAIGNNAME, ch
        """)
        result: dict = {}
        for r in rows_data:
            cname = r.get("SESSIONCAMPAIGNNAME") or ""
            ch    = r.get("CH") or ""
            for row_name, pat, expected_ch in ga4_rows:
                if ch == expected_ch.upper() and _ilike(cname, pat):
                    entry = result.setdefault(row_name, {"sess": 0.0, "rev": 0.0})
                    entry["sess"] += r.get("SESS") or 0
                    entry["rev"]  += r.get("REV")  or 0
                    break
        return result

    email_sends = run_sends_query(email_ids, "email")
    sms_sends   = run_sends_query(sms_ids,   "sms")
    push_sends  = run_sends_query(push_ids,  "push")
    email_opens = run_opens_query(email_ids)
    ga4_data    = run_ga4_query()

    result = {}
    for row, ids, sends_ch, t1_ch, t1_filter, is_sms_only in classified:
        rname = row["name"]
        if not ids:
            result[rname] = {}
            continue

        sends_dict = sms_sends if is_sms_only else email_sends
        t1_dict    = {"email": email_sends, "sms": sms_sends, "push": push_sends}.get(t1_ch, email_sends)

        total_sends = total_recip = t1_total = 0
        for cid in ids:
            for sname, step in sends_dict.get(cid, {}).items():
                total_sends += step["n"]
                total_recip += step["u"]
            for sname, step in t1_dict.get(cid, {}).items():
                if _ilike(sname, t1_filter):
                    t1_total += step["n"]

        opens = 0 if is_sms_only else sum(email_opens.get(cid, 0) for cid in ids)
        uor   = round(opens * 100.0 / total_recip, 1) if total_recip and not is_sms_only else None

        ga4  = ga4_data.get(rname, {})
        sess = ga4.get("sess", 0)
        rev  = ga4.get("rev",  0)

        result[rname] = {
            "sends_wk": round(total_sends / 12) if total_sends else None,
            "t1_wk":    round(t1_total    / 12) if t1_total    else None,
            "opens_wk": round(opens       / 12) if opens       else None,
            "uor":      uor,
            "sess_wk":  round(sess        / 12) if sess        else None,
            "rev_wk":   round(rev         / 12) if rev         else None,
            "rev_m":    round(rev / 12 * 1000 / (total_sends / 12)) if total_sends else None,
            "is_sms":   is_sms_only,
        }

    return result

SMS_ONLY = {"bur::sms-welcome", "id::sms-welcome", "cz::sms-welcome", "stf::sms-welcome"}

# ── Top header + brand tabs ───────────────────────────────────────────────────

BRAND_LABELS = {
    "bur": "🛋 Burrow",
    "id":  "🪑 Interior Define",
    "hav": "🏠 Havenly",
    "cz":  "🌍 The Citizenry",
    "stf": "🎨 St. Frank",
    "ti":  "🏡 The Inside",
    "te":  "⭐ The Expert",
}

header_col, refresh_col = st.columns([6, 1])
with header_col:
    st.markdown("## 📬 Lifecycle Canvas Map")
    st.caption("Rolling 12-week weekly averages · Braze sends/opens · GA4 sessions/revenue · TI: GA4 only (Klaviyo) · v2")
with refresh_col:
    if st.button("🔄 Refresh", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k.startswith("stats_"):
                del st.session_state[k]

brand_tabs = st.tabs(list(BRAND_LABELS.values()))
brand_keys = list(BRAND_LABELS.keys())

# ── Stats cache ───────────────────────────────────────────────────────────────

def load_stats(brand: str) -> dict:
    """Fetch 12-week stats for all canvases in a brand. Cached in session state."""
    cache_key = f"stats_{brand}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        cfg = BRAND_SNOWFLAKE[brand]
        # TE has no GA4 or Braze data — return empty stats immediately
        if cfg["app_group_id"] is None and not cfg.get("ga4"):
            result = {row["name"]: {"klaviyo": True} for row in CANVASES[brand]["rows"]}
            st.session_state[cache_key] = result
            return result
        from snowflake_client import get_snowflake_client
        sf_db     = cfg["db"]     or "AIRBYTE_DATABASE"
        sf_schema = cfg["schema"] or (cfg.get("ga4") or "PUBLIC")
        client = get_snowflake_client(schema=sf_schema, database=sf_db)
        if cfg["app_group_id"] is None:
            # Klaviyo brand — one batch GA4 query instead of N per-row queries
            result = fetch_klaviyo_stats_batch(brand, CANVASES[brand]["rows"], client)
        else:
            # Braze brand — 5 batch queries instead of ~3-4 per canvas row
            result = fetch_all_stats_batch(brand, CANVASES[brand]["rows"], client)
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        import traceback
        err = {"_error": f"{e}\n{traceback.format_exc()}"}
        st.session_state[cache_key] = err
        return err


# ── Image helper ──────────────────────────────────────────────────────────────

THUMB_W = 320       # CSS display width
THUMB_SCALE = 2     # render at 2x display width so retina/high-DPI renders stay crisp
SCROLL_THUMB_W = 290        # display width for cards in horizontally-scrolling rows — tuned so ~4 fit on a 14" MBP (1512pt logical width) without squeezing
SCROLL_STEP_THRESHOLD = 7   # rows with more steps than this scroll horizontally instead of squeezing into equal-width columns

@st.cache_data(show_spinner=False)
def load_thumb(fname: str, f_dir: str = "rendered", display_w: int = THUMB_W) -> bytes | None:
    base = RENDERED
    path = base / fname
    if not path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        target_w = display_w * THUMB_SCALE
        if img.width > target_w:
            new_h = int(img.height * target_w / img.width)
            # LANCZOS is a high-quality downscaler — far sharper than BILINEAR
            # for text-heavy (plain-text) email thumbnails.
            img = img.resize((target_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.step-card { border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;
             background: #fff; margin-bottom: 4px; }
.step-badge { background: #1a1a1a; color: #d4a83a; font-size: 11px;
              font-weight: 700; padding: 5px 10px; }
.step-subject { font-size: 11px; padding: 5px 10px 6px; color: #333;
                border-bottom: 1px solid #eee; line-height: 1.4;
                background: #fafafa; }
.sms-card { border: 1px solid #c9c0f0; border-radius: 8px; overflow: hidden;
            background: #ede9fb; margin-bottom: 4px; }
.sms-badge { background: #6b4fcf; color: #fff; font-size: 11px;
             font-weight: 700; padding: 5px 10px; }
.sms-subject { font-size: 11px; padding: 5px 10px 4px; color: #4a3a80;
               font-weight: 600; }
.sms-body { font-size: 10px; padding: 4px 10px 8px; color: #5a4a90;
            line-height: 1.5; }
.push-card { border: 1px solid #f0d9b0; border-radius: 8px; overflow: hidden;
             background: #fdf5e8; margin-bottom: 4px; }
.push-badge { background: #b86a00; color: #fff; font-size: 11px;
              font-weight: 700; padding: 5px 10px; }
.push-subject { font-size: 11px; padding: 5px 10px 4px; color: #7a4400;
                font-weight: 600; }
.push-body { font-size: 10px; padding: 4px 10px 8px; color: #8a5500;
             line-height: 1.5; }
.stat-box { text-align: center; padding: 8px 4px; }
.stat-val  { font-size: 18px; font-weight: 700; color: #1a1a1a; }
.stat-lbl  { font-size: 10px; color: #888; text-transform: uppercase;
             letter-spacing: 0.5px; margin-top: 2px; }
.canvas-header { font-size: 14px; font-weight: 700; margin-bottom: 2px; }
.canvas-entry  { font-size: 11px; color: #777; margin-bottom: 12px; }
.hscroll-row { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 14px; }
.hscroll-item { flex: 0 0 auto; width: 290px; }
</style>
""", unsafe_allow_html=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def render_brand(brand: str):
    cfg = CANVASES[brand]

    with st.spinner(f"Loading {cfg['label']} stats from Snowflake…"):
        stats_map = load_stats(brand)
    has_error = "_error" in stats_map
    if has_error:
        st.error(f"Stats error:\n```\n{stats_map['_error']}\n```")

    for row in cfg["rows"]:
        cname = row["name"]
        stats = stats_map.get(cname, {}) if not has_error else {}
        is_sms_only = all(s.get("channel") == "sms" for s in row["steps"])

        with st.expander(f"**{cname}**  ·  ↳ {row['entry']}", expanded=True):

            # ── Stats row ─────────────────────────────────────────────────
            if stats and not has_error:
                is_klaviyo = stats.get("klaviyo", False)
                sess_wk  = stats.get("sess_wk") or 0
                rev_wk   = stats.get("rev_wk") or 0

                if is_klaviyo:
                    metrics = [("Sessions/wk", fmt_n(sess_wk)),
                               ("Rev/wk", fmt_n(rev_wk, "$"))]
                else:
                    sends_wk = stats.get("sends_wk") or 0
                    t1_wk    = stats.get("t1_wk") or 0
                    opens_wk = stats.get("opens_wk") or 0
                    uor      = stats.get("uor")
                    rev_m    = stats.get("rev_m")
                    metrics  = [("T1/wk", fmt_n(t1_wk)), ("Sends/wk", fmt_n(sends_wk))]
                    if not is_sms_only:
                        metrics += [("Opens/wk", fmt_n(opens_wk)), ("UOR", fmt_pct(uor))]
                    metrics += [("Sessions/wk", fmt_n(sess_wk)), ("Rev/wk", fmt_n(rev_wk, "$"))]
                    if not is_sms_only:
                        metrics.append(("Rev/M", fmt_n(rev_m, "$")))

                n_metrics = len(metrics)
                cols = st.columns(n_metrics)

                for col, (lbl, val) in zip(cols, metrics):
                    col.markdown(
                        f'<div class="stat-box"><div class="stat-val">{val}</div>'
                        f'<div class="stat-lbl">{lbl}</div></div>',
                        unsafe_allow_html=True,
                    )
                st.divider()
            elif has_error:
                st.caption(f"⚠ Stats unavailable: {stats_map['_error'][:80]}")

            # ── Step thumbnails ───────────────────────────────────────────
            # Rows with many touchpoints get squeezed to near-nothing in equal-width
            # st.columns (e.g. 12 steps in a ~1200px page = ~90px thumbnails). Past
            # SCROLL_STEP_THRESHOLD, render as a horizontally-scrolling strip with
            # larger, fixed-width cards instead.
            use_scroll = len(row["steps"]) > SCROLL_STEP_THRESHOLD

            def _card_html(step, display_w: int) -> str:
                timing  = step["t"]
                subject = step["s"]
                channel = step.get("channel")
                is_sms  = channel == "sms"
                is_push = channel == "push"
                body    = step.get("body", "")
                fname   = step.get("f")

                if is_sms:
                    return (
                        f'<div class="sms-card">'
                        f'<div class="sms-badge">{timing}</div>'
                        f'<div class="sms-subject">{subject}</div>'
                        f'<div class="sms-body">{body}</div>'
                        f'</div>'
                    )
                if is_push:
                    return (
                        f'<div class="push-card">'
                        f'<div class="push-badge">{timing}</div>'
                        f'<div class="push-subject">{subject}</div>'
                        f'<div class="push-body">{body}</div>'
                        f'</div>'
                    )

                f_dir = step.get("f_dir", "rendered")
                img_bytes = load_thumb(fname, f_dir, display_w) if fname else None
                card = (
                    f'<div class="step-card">'
                    f'<div class="step-badge">{timing}</div>'
                    f'<div class="step-subject">{subject}</div>'
                    f'</div>'
                )
                if img_bytes:
                    # Embed as a base64 <img> at native 2x resolution with a
                    # CSS-constrained display width. st.image(width=…) resamples
                    # the served bytes down to the display width (blurring text
                    # thumbnails); this keeps the full-res image and lets the
                    # browser downscale for a crisp, retina-quality render.
                    b64 = base64.b64encode(img_bytes).decode()
                    card += (
                        f'<img src="data:image/jpeg;base64,{b64}" '
                        f'style="width:100%;max-width:{display_w}px;height:auto;'
                        f'border:1px solid #eee;border-radius:4px;display:block;" />'
                    )
                else:
                    card += (
                        '<div style="height:80px;background:#f5f5f5;border-radius:4px;'
                        'display:flex;align-items:center;justify-content:center;'
                        'color:#bbb;font-size:10px;">No preview</div>'
                    )
                return card

            if use_scroll:
                items = "".join(
                    f'<div class="hscroll-item">{_card_html(step, SCROLL_THUMB_W)}</div>'
                    for step in row["steps"]
                )
                st.markdown(f'<div class="hscroll-row">{items}</div>', unsafe_allow_html=True)
            else:
                cols = st.columns(len(row["steps"]))
                for col, step in zip(cols, row["steps"]):
                    with col:
                        st.markdown(_card_html(step, THUMB_W), unsafe_allow_html=True)


# ── Render selected tab ───────────────────────────────────────────────────────

for tab, brand in zip(brand_tabs, brand_keys):
    with tab:
        render_brand(brand)
