#!/usr/bin/env python3
"""
BW (Burrow) trigger attribution comparison: April 2025 vs April 2026.

Queries GA4 last-click data from Snowflake and classifies sessions by channel
(email vs SMS) and type (trigger/canvas flow vs batch). Handles dual naming
conventions — the P_EM_ prefix was adopted ~mid-2025, so April 2025 data uses
old-format batch names (2025_04_XX_BW_D_...) and mixed trigger names (some
TRG_EM_..., some short forms like Abandon-Cart-1).
"""

import re
import sys
from pathlib import Path

import pandas as pd

scripts_dir = Path(__file__).parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from snowflake_client import get_snowflake_client

GA4_DB    = "AIRBYTE_DATABASE"
GA4_TABLE = f"{GA4_DB}.LANDING_BURROW_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY"

BRAZE_DB     = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
BRAZE_SCHEMA = "DATALAKE_SHARING"
BUR_APP_GROUP_ID = "67093a1f24ebbe0065cb9c77"

PERIODS = {
    "Apr 2025": ("20250401", "20250430"),
    "Apr 2026": ("20260401", "20260430"),
}


# ---------------------------------------------------------------------------
# Fuzzy trigger mapping — ports build_fuzzy_step_map from combine_braze_ga4.py
# Maps old-format GA4 step names (e.g. "Abandon-Cart-1") to TRG_ step names
# by matching touch number + description keywords.
# ---------------------------------------------------------------------------

def _step_desc_keywords(step: str) -> frozenset:
    parts = step.split("_")
    try:
        bw_idx = next(i for i, p in enumerate(parts) if p.upper() == "BW")
        desc = parts[bw_idx + 1:]
    except StopIteration:
        desc = parts
    if desc and desc[0].upper() in ("D", "H", "PT"):
        desc = desc[1:]
    desc = [p for p in desc if not re.match(r"^[TV]\d+$", p, re.I)]
    return frozenset(p.lower() for p in desc if p)


def build_fuzzy_step_map(ga4_campaigns: list, canvas_step_names: list) -> dict:
    """Map old-format GA4 step names to TRG_ canvas step names.

    Returns a dict of {ga4_name: trg_step_name}. When multiple TRG_ steps
    match (e.g. multiple vintages of Abandon-Browse_T2), we still map to the
    first match — the goal is trigger *detection*, not exact step attribution.
    """
    trg_steps = [s for s in canvas_step_names if str(s).startswith("TRG_")]
    step_kw = {s: _step_desc_keywords(s) for s in trg_steps}
    result = {}
    for name in ga4_campaigns:
        s = str(name)
        if s.startswith("TRG_"):
            continue
        m = re.search(r"[-_](\d+)$", s)
        if not m:
            continue
        t = int(m.group(1))
        base = s[: m.start()]
        ga4_kw = frozenset(w.lower() for w in re.split(r"[-_\s]", base) if w)
        t_tag = f"_t{t}_"
        matches = [c for c in trg_steps if t_tag in c.lower() and step_kw[c] == ga4_kw]
        if matches:
            # Take first match — multiple vintages exist for some flows but we
            # only need to know this is a trigger, not which exact step version.
            result[s] = matches[0]
    return result


def build_canvas_prefix_set(canvas_step_names: list) -> list:
    """Return sorted list of canvas step names for prefix matching.

    Handles suffix variants like '2025Q1_Welcome-Flow_Step-1_F' matching
    canvas step '2025Q1_Welcome-Flow_Step-1' when followed by _ or end.
    """
    return sorted(
        (s for s in canvas_step_names if s),
        key=len, reverse=True  # longest first for greedy prefix check
    )


def matches_canvas_prefix(name: str, canvas_prefixes: list) -> bool:
    for step in canvas_prefixes:
        if name == step:
            return True
        if name.startswith(step) and len(name) > len(step) and name[len(step)] in ("_", "-", " "):
            return True
    return False


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_ga4(start: str, end: str) -> pd.DataFrame:
    client = get_snowflake_client(schema="LANDING_BURROW_GA4", database=GA4_DB)
    rows = client.execute_query(f"""
        SELECT
            SESSIONCAMPAIGNNAME,
            SESSIONPRIMARYCHANNELGROUP,
            SUM(ECOMMERCEPURCHASES) AS ORDERS,
            SUM(TOTALREVENUE)       AS REVENUE,
            SUM(SESSIONS)           AS SESSIONS
        FROM {GA4_TABLE}
        WHERE DATE >= '{start}'
          AND DATE <= '{end}'
          AND SESSIONCAMPAIGNNAME IS NOT NULL
          AND TRIM(SESSIONCAMPAIGNNAME) != ''
        GROUP BY SESSIONCAMPAIGNNAME, SESSIONPRIMARYCHANNELGROUP
    """)
    df = pd.DataFrame(rows)
    # Normalize column names to lowercase for consistent access
    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_canvas_step_names() -> list:
    client = get_snowflake_client(schema=BRAZE_SCHEMA, database=BRAZE_DB)
    rows = client.execute_query(f"""
        SELECT NAME AS step_name
        FROM {BRAZE_DB}.{BRAZE_SCHEMA}.SNAPSHOTS_CANVAS_STEP_SHARED
        WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1
    """)
    # Snowflake DictCursor returns uppercase keys
    return [r.get("STEP_NAME") or r.get("step_name") for r in rows
            if r.get("STEP_NAME") or r.get("step_name")]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _safer_classify(df: pd.DataFrame, canvas_step_names: list) -> pd.DataFrame:
    """Vectorized classification (faster and avoids row-level indexing issues)."""
    if df.empty:
        return df

    df = df.copy()
    name    = df["sessioncampaignname"].astype(str)
    channel = df["sessionprimarychannelgroup"].fillna("").astype(str).str.strip().str.upper()

    is_trg      = name.str.upper().str.startswith("TRG_")
    is_p_em     = name.str.contains(r"\bP_EM_", na=False)
    is_p_sms    = name.str.contains(r"\bP_SMS_", na=False) | name.str.endswith("_SMS")
    is_p_year   = name.str.contains(r"\bP_\d{4}", na=False)
    is_old_em   = name.str.match(r"^\d{4}_\d{1,2}_\d{1,2}_", na=False) & ~is_p_sms

    # BW's 2024/2025 quarter-format canvas naming (2024Q4_Welcome-Flow_Step-1 etc.)
    # These old canvases were replaced before appearing in Braze's snapshot.
    is_quarter_canvas = name.str.match(r"^\d{4}Q\d_", na=False)

    canvas_set      = set(canvas_step_names)
    canvas_prefixes = build_canvas_prefix_set(canvas_step_names)
    fuzzy_map       = build_fuzzy_step_map(name.unique().tolist(), canvas_step_names)

    is_canvas_exact  = name.isin(canvas_set) | name.isin(fuzzy_map)
    is_canvas_prefix = name.apply(lambda n: matches_canvas_prefix(n, canvas_prefixes))
    is_canvas        = is_canvas_exact | is_canvas_prefix | is_quarter_canvas

    is_trigger  = is_trg | is_canvas

    # Assign categories in priority order
    cats = pd.Series("other", index=df.index)

    # SMS triggers: trigger + (name says P_SMS_ / _SMS, or GA4 channel = SMS)
    cats[is_trigger & (is_p_sms | (channel == "SMS"))]  = "trigger_sms"
    # Email triggers: trigger + not already SMS
    cats[is_trigger & (cats != "trigger_sms")]           = "trigger_email"
    # Batch SMS
    cats[(~is_trigger) & is_p_sms]                       = "batch_sms"
    # Batch email (new format, old format, or GA4 channel = EMAIL)
    cats[(~is_trigger) & ~is_p_sms & (is_p_em | is_old_em | (channel == "EMAIL"))] = "batch_email"
    # P_YYYY_ without _EM_ or _SMS_ — treat as batch email (e.g. P_2025_04_BW_...)
    cats[(~is_trigger) & ~is_p_sms & ~is_p_em & ~is_old_em & (channel != "SMS") &
         is_p_year]                                      = "batch_email"

    df["category"] = cats
    return df


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    g = df.groupby("category")[["orders", "revenue"]].sum(numeric_only=True)
    return g.to_dict("index")


def summarize(agg: dict) -> dict:
    def get(cat):
        return agg.get(cat, {"orders": 0, "revenue": 0})

    te = get("trigger_email")
    be = get("batch_email")
    ts = get("trigger_sms")
    bs = get("batch_sms")

    total_email_rev  = te["revenue"] + be["revenue"]
    total_email_ord  = te["orders"]  + be["orders"]
    total_sms_rev    = ts["revenue"] + bs["revenue"]
    total_sms_ord    = ts["orders"]  + bs["orders"]

    def pct(a, b): return a / b if b else None

    total_combined_rev = total_email_rev + total_sms_rev
    total_combined_ord = total_email_ord + total_sms_ord
    trigger_combined_rev = te["revenue"] + ts["revenue"]
    trigger_combined_ord = te["orders"]  + ts["orders"]
    batch_combined_rev   = be["revenue"] + bs["revenue"]
    batch_combined_ord   = be["orders"]  + bs["orders"]

    return {
        "email": {
            "trigger_rev":  te["revenue"],
            "batch_rev":    be["revenue"],
            "total_rev":    total_email_rev,
            "trigger_ord":  te["orders"],
            "batch_ord":    be["orders"],
            "total_ord":    total_email_ord,
            "trigger_rev_pct": pct(te["revenue"], total_email_rev),
            "trigger_ord_pct": pct(te["orders"],  total_email_ord),
        },
        "sms": {
            "trigger_rev":  ts["revenue"],
            "batch_rev":    bs["revenue"],
            "total_rev":    total_sms_rev,
            "trigger_ord":  ts["orders"],
            "batch_ord":    bs["orders"],
            "total_ord":    total_sms_ord,
            "trigger_rev_pct": pct(ts["revenue"], total_sms_rev),
            "trigger_ord_pct": pct(ts["orders"],  total_sms_ord),
        },
        "combined": {
            "trigger_rev":  trigger_combined_rev,
            "batch_rev":    batch_combined_rev,
            "total_rev":    total_combined_rev,
            "trigger_ord":  trigger_combined_ord,
            "batch_ord":    batch_combined_ord,
            "total_ord":    total_combined_ord,
            "trigger_rev_pct": pct(trigger_combined_rev, total_combined_rev),
            "trigger_ord_pct": pct(trigger_combined_ord, total_combined_ord),
        },
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def fmt_rev(v):
    if v is None: return "—"
    return f"${v:>9,.0f}"

def fmt_pct(v):
    if v is None: return "    —"
    return f"{v * 100:>6.1f}%"

def fmt_diff(a, b):
    if a is None or b is None: return ""
    diff = (b - a) * 100
    sign = "+" if diff >= 0 else ""
    return f"  ({sign}{diff:.1f}pp)"


def print_section(label: str, periods: dict, key: str):
    p1_lbl, p2_lbl = list(periods.keys())
    p1 = periods[p1_lbl][key]
    p2 = periods[p2_lbl][key]

    w = 14
    print(f"\n{'─' * 62}")
    print(f"  {label}")
    print(f"{'─' * 62}")
    header = f"  {'':32s}  {p1_lbl:>{w}}  {p2_lbl:>{w}}"
    print(header)
    print()

    rows = [
        ("Trigger Revenue",  "trigger_rev",     fmt_rev),
        ("Batch Revenue",    "batch_rev",        fmt_rev),
        ("Total Revenue",    "total_rev",        fmt_rev),
        ("Trigger Orders",   "trigger_ord",      lambda v: f"{v:>9,.0f}  " if v is not None else "         —"),
        ("Batch Orders",     "batch_ord",        lambda v: f"{v:>9,.0f}  " if v is not None else "         —"),
        ("Total Orders",     "total_ord",        lambda v: f"{v:>9,.0f}  " if v is not None else "         —"),
        ("Trigger % (rev)",  "trigger_rev_pct",  fmt_pct),
        ("Trigger % (ord)",  "trigger_ord_pct",  fmt_pct),
    ]
    for row_lbl, field, fmt in rows:
        v1 = p1.get(field)
        v2 = p2.get(field)
        diff = ""
        if "pct" in field:
            diff = fmt_diff(v1, v2)
        line = f"  {row_lbl:32s}  {fmt(v1):>{w}}  {fmt(v2):>{w}}{diff}"
        if "Trigger %" in row_lbl:
            print()
        print(line)


def print_debug_categories(df: pd.DataFrame, period_label: str):
    print(f"\n  [DEBUG {period_label}] Campaign name samples by category:")
    for cat, grp in df.groupby("category"):
        samples = grp.nlargest(3, "revenue")["sessioncampaignname"].tolist()
        rev = grp["revenue"].sum()
        print(f"    {cat:20s}  ${rev:>10,.0f}  e.g. {samples[:2]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Fetching BUR canvas step names from Braze datashare...")
    canvas_step_names = fetch_canvas_step_names()
    print(f"  {len(canvas_step_names)} canvas step names loaded")
    if canvas_step_names:
        trg_count = sum(1 for s in canvas_step_names if s.startswith("TRG_"))
        print(f"  {trg_count} start with TRG_ (eligible for fuzzy matching)")

    results = {}
    for label, (start, end) in PERIODS.items():
        print(f"\nFetching GA4 data for {label} ({start}–{end})...")
        df = fetch_ga4(start, end)
        print(f"  {len(df)} campaign×channel rows returned")
        if df.empty:
            print(f"  WARNING: no data for {label}")
            results[label] = {"email": {}, "sms": {}}
            continue

        df = _safer_classify(df, canvas_step_names)
        print_debug_categories(df, label)

        agg = aggregate(df)
        results[label] = summarize(agg)

    print("\n")
    print("=" * 62)
    print("  BW Last-Click Attribution — Triggers as % of Total")
    print("=" * 62)

    print_section("EMAIL",          results, "email")
    print_section("SMS",            results, "sms")
    print_section("EMAIL + SMS",    results, "combined")
    print()


if __name__ == "__main__":
    main()
