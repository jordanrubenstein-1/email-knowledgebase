#!/usr/bin/env python3
"""
BW Memorial Day Canvas Test — Performance comparison: test vs control.

Compares the 30% test group vs 30% control group only (excluded group ignored).
All metrics are user-level from the Braze datashare so they can be cleanly
split by group assignment.

  - Sessions proxy : unique users who clicked any email (USERS_MESSAGES_EMAIL_CLICK_SHARED)
  - Purchases      : USERS_BEHAVIORS_PURCHASE_SHARED (any purchase, not click-gated)
  - Revenue        : SUM(PRICE) from USERS_BEHAVIORS_PURCHASE_SHARED

Test period: May 7, 2026 – June 2, 2026 EOD ET (midnight)
"""

import sys
import math
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snowflake_client import get_snowflake_client

DB     = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR    = "67093a1f24ebbe0065cb9c77"

# May 7 2026 00:00:00 UTC
TEST_START_UNIX = 1778112000
# June 2 2026 midnight ET = June 3 2026 04:00:00 UTC
TEST_END_UNIX   = 1780459200


def query_user_events(client, table: str, extra_where: str = "") -> pd.DataFrame:
    """Pull distinct EXTERNAL_USER_IDs from a datashare event table for the test window."""
    rows = client.execute_query(f"""
        SELECT DISTINCT EXTERNAL_USER_ID
        FROM {DB}.{SCHEMA}.{table}
        WHERE APP_GROUP_ID = '{BUR}'
          AND TIME >= {TEST_START_UNIX}
          AND TIME <= {TEST_END_UNIX}
          AND EXTERNAL_USER_ID IS NOT NULL
          {extra_where}
    """)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["EXTERNAL_USER_ID"])
    df.columns = [c.lower() for c in df.columns]
    return df


def prop_pvalue(n1: int, x1: int, n2: int, x2: int) -> float:
    """Two-tailed p-value for difference between two proportions (z-test)."""
    p1 = x1 / n1 if n1 else 0
    p2 = x2 / n2 if n2 else 0
    p_hat = (x1 + x2) / (n1 + n2) if (n1 + n2) else 0
    if p_hat in (0, 1):
        return 1.0
    se = math.sqrt(p_hat * (1 - p_hat) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(p1 - p2) / se
    return math.erfc(z / math.sqrt(2))   # two-tailed, uses normal approx


def mean_pvalue(a: pd.Series, b: pd.Series) -> float:
    """Two-tailed Welch's t-test p-value for difference in means.
    Uses normal approximation (valid for large n like 69K)."""
    n1, n2 = len(a), len(b)
    m1, m2 = a.mean(), b.mean()
    v1 = a.var(ddof=1) if n1 > 1 else 0.0
    v2 = b.var(ddof=1) if n2 > 1 else 0.0
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 1.0
    t = abs(m1 - m2) / se
    return math.erfc(t / math.sqrt(2))   # normal approx fine for n=69K


def sig_label(p: float) -> str:
    if p < 0.01:  return "**"
    if p < 0.05:  return "*"
    if p < 0.10:  return "~"
    return "ns"


def main():
    import datetime
    def ts(): return datetime.datetime.now().strftime("%H:%M:%S")

    print(f"[{ts()}] Connecting to Snowflake...")
    client = get_snowflake_client(schema=SCHEMA, database=DB)
    print(f"[{ts()}] Connected.")

    # ── Load test + control assignments only ─────────────────────────────────
    csv_path = Path(__file__).resolve().parents[2] / "exports/bw_memorial_day_test_assignments.csv"
    assignments = pd.read_csv(csv_path)[["external_user_id", "group"]]
    tc = assignments[assignments["group"].isin(["test", "control"])].copy()
    print(f"Audience: {tc['group'].value_counts().to_dict()}")
    print(f"Test period: May 7 – June 2 2026 (EOD ET)\n")

    # ── Pull user-level events since May 7 ───────────────────────────────────
    import datetime
    def ts(): return datetime.datetime.now().strftime("%H:%M:%S")

    print(f"[{ts()}] Pulling clicks (sessions proxy)...")
    click_rows = client.execute_query(f"""
        SELECT
            EXTERNAL_USER_ID,
            COUNT(*) AS total_clicks
        FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
        WHERE APP_GROUP_ID = '{BUR}'
          AND TIME >= {TEST_START_UNIX}
          AND EXTERNAL_USER_ID IS NOT NULL
          AND TIME <= {TEST_END_UNIX}
          AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
        GROUP BY EXTERNAL_USER_ID
    """)
    clicks_df = pd.DataFrame(click_rows) if click_rows else pd.DataFrame(columns=["EXTERNAL_USER_ID", "total_clicks"])
    clicks_df.columns = [c.lower() for c in clicks_df.columns]
    print(f"[{ts()}] Clicks done — {len(clicks_df):,} users with clicks.")

    print(f"[{ts()}] Pulling purchases and revenue...")
    purchase_rows = client.execute_query(f"""
        SELECT
            EXTERNAL_USER_ID,
            COUNT(*)              AS order_count,
            SUM(PRICE)            AS revenue
        FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
        WHERE APP_GROUP_ID = '{BUR}'
          AND TIME >= {TEST_START_UNIX}
          AND TIME <= {TEST_END_UNIX}
          AND EXTERNAL_USER_ID IS NOT NULL
        GROUP BY EXTERNAL_USER_ID
    """)
    if purchase_rows:
        purchases_df = pd.DataFrame(purchase_rows)
        purchases_df.columns = [c.lower() for c in purchases_df.columns]
    else:
        purchases_df = pd.DataFrame(columns=["external_user_id", "order_count", "revenue"])
    print(f"[{ts()}] Purchases done — {len(purchases_df):,} users with purchases.")

    print(f"[{ts()}] Pulling unsubscribes...")
    unsubs_df = query_user_events(client, "USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED")
    unsubs_df["unsubbed"] = True
    print(f"[{ts()}] Unsubscribes done — {len(unsubs_df):,} users unsubbed.")

    # ── Merge everything onto test+control users ─────────────────────────────
    merged = (
        tc
        .merge(clicks_df,    on="external_user_id", how="left")
        .merge(purchases_df, on="external_user_id", how="left")
        .merge(unsubs_df,    on="external_user_id", how="left")
    )
    merged["total_clicks"] = merged["total_clicks"].fillna(0).astype(int)
    merged["clicked"]      = merged["total_clicks"] > 0
    merged["order_count"]  = merged["order_count"].fillna(0)
    merged["revenue"]      = merged["revenue"].fillna(0)
    merged["unsubbed"]     = merged["unsubbed"].fillna(False)
    merged["purchased"]    = merged["order_count"] > 0

    # ── Print results ────────────────────────────────────────────────────────
    print(f"\n{'='*74}")
    print(f"  BW MEMORIAL DAY CANVAS TEST  —  May 7 – June 2 2026")
    print(f"{'='*74}")

    rows_out = []
    for grp in ["test", "control"]:
        g            = merged[merged["group"] == grp]
        n            = len(g)
        total_clicks = int(g["total_clicks"].sum())
        clickers     = int(g["clicked"].sum())
        buyers       = int(g["purchased"].sum())
        purch_events = int(g["order_count"].sum())
        revenue      = g["revenue"].sum()
        unsubs       = int(g["unsubbed"].sum())
        clicker_rate = clickers      / n if n else 0
        clicks_pu    = total_clicks  / n if n else 0
        buy_rate     = buyers        / n if n else 0
        unsub_rate   = unsubs        / n if n else 0
        aov          = revenue / buyers if buyers else 0
        rpu          = revenue / n
        rows_out.append(dict(
            group=grp, n=n,
            total_clicks=total_clicks, clickers=clickers,
            clicker_rate=clicker_rate, clicks_pu=clicks_pu,
            buyers=buyers, buy_rate=buy_rate,
            purch_events=purch_events,
            revenue=revenue, aov=aov, rpu=rpu,
            unsubs=unsubs, unsub_rate=unsub_rate,
        ))

    t_grp = merged[merged["group"] == "test"]
    c_grp = merged[merged["group"] == "control"]
    t_r, c_r = rows_out[0], rows_out[1]

    # Compute p-values
    p_clicker = prop_pvalue(t_r["n"], t_r["clickers"],    c_r["n"], c_r["clickers"])
    p_clicks  = mean_pvalue(t_grp["total_clicks"].astype(float), c_grp["total_clicks"].astype(float))
    p_buy     = prop_pvalue(t_r["n"], t_r["buyers"],      c_r["n"], c_r["buyers"])
    p_rpu     = mean_pvalue(t_grp["revenue"],              c_grp["revenue"])
    # AOV: compare revenue among buyers only
    t_buyers  = t_grp[t_grp["purchased"]]["revenue"]
    c_buyers  = c_grp[c_grp["purchased"]]["revenue"]
    p_aov     = mean_pvalue(t_buyers, c_buyers) if (len(t_buyers) > 1 and len(c_buyers) > 1) else 1.0
    p_unsub   = prop_pvalue(t_r["n"], t_r["unsubs"],      c_r["n"], c_r["unsubs"])

    # Header
    print(f"{'':10} {'Users':>8} {'Clicks':>8} {'Clickers':>10} {'Clkr%':>7} {'Clk/User':>9} "
          f"{'Buyers':>8} {'Buy%':>7} {'Revenue':>12} {'AOV':>8} {'Rev/User':>10} {'Unsubs':>8} {'Unsub%':>7}")
    print("-" * 114)
    for r in rows_out:
        print(
            f"{r['group']:<10} {r['n']:>8,} {r['total_clicks']:>8,} {r['clickers']:>10,} "
            f"{r['clicker_rate']*100:>6.2f}% {r['clicks_pu']:>9.4f} "
            f"{r['buyers']:>8,} {r['buy_rate']*100:>6.2f}% "
            f"${r['revenue']:>10,.2f} ${r['aov']:>6.2f} ${r['rpu']:>8.4f} "
            f"{r['unsubs']:>8,} {r['unsub_rate']*100:>6.3f}%"
        )

    print(f"\n  Note: AOV = revenue ÷ buyers. Braze fires one purchase event per SKU,")
    print(f"  so a single checkout with multiple items counts as multiple events.")
    print(f"  Purchase event counts: test={t_r['purch_events']}, control={c_r['purch_events']}")

    # Lift + significance
    sign = lambda x, fmt: (f"+{x:{fmt}}" if x >= 0 else f"{x:{fmt}}")
    clicker_lift = (t_r["clicker_rate"] - c_r["clicker_rate"]) * 100
    clicks_lift  = t_r["clicks_pu"]     - c_r["clicks_pu"]
    buy_lift     = (t_r["buy_rate"]     - c_r["buy_rate"])     * 100
    rpu_lift     = t_r["rpu"]           - c_r["rpu"]
    unsub_lift   = (t_r["unsub_rate"]   - c_r["unsub_rate"])   * 100

    aov_lift = t_r["aov"] - c_r["aov"]

    print(f"\n  {'Metric':<16} {'Test':>10} {'Control':>10} {'Diff':>10} {'p-value':>9} {'Sig':>4}")
    print(f"  {'-'*62}")
    print(f"  {'Clicker rate':<16} {t_r['clicker_rate']*100:>9.2f}% {c_r['clicker_rate']*100:>9.2f}% "
          f"{sign(clicker_lift, '.2f')+'pp':>10} {p_clicker:>9.4f} {sig_label(p_clicker):>4}")
    print(f"  {'Clicks/user':<16} {t_r['clicks_pu']:>10.4f} {c_r['clicks_pu']:>10.4f} "
          f"{sign(clicks_lift, '.4f'):>10} {p_clicks:>9.4f} {sig_label(p_clicks):>4}")
    print(f"  {'Buy rate':<16} {t_r['buy_rate']*100:>9.3f}% {c_r['buy_rate']*100:>9.3f}% "
          f"{sign(buy_lift, '.3f')+'pp':>10} {p_buy:>9.4f} {sig_label(p_buy):>4}")
    print(f"  {'AOV':<16} ${t_r['aov']:>9.2f} ${c_r['aov']:>9.2f} "
          f"{sign(aov_lift, '.2f'):>10} {p_aov:>9.4f} {sig_label(p_aov):>4}")
    print(f"  {'Rev/user':<16} {t_r['rpu']:>10.4f} {c_r['rpu']:>10.4f} "
          f"{sign(rpu_lift, '.4f'):>10} {p_rpu:>9.4f} {sig_label(p_rpu):>4}")
    print(f"  {'Unsub rate':<16} {t_r['unsub_rate']*100:>9.3f}% {c_r['unsub_rate']*100:>9.3f}% "
          f"{sign(unsub_lift, '.3f')+'pp':>10} {p_unsub:>9.4f} {sig_label(p_unsub):>4}")
    print(f"\n  ** p<0.01  * p<0.05  ~ p<0.10  ns = not significant")
    print()


if __name__ == "__main__":
    main()
