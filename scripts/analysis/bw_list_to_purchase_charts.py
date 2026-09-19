"""
Burrow: Time from joining email list (first Braze send) to first purchase.
Chart 1: All purchasers
Chart 2: Email cohort (click before purchase)
No 365-day cap — includes 365d+ bucket.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR_APP_GROUP = "67093a1f24ebbe0065cb9c77"

client = get_snowflake_client(schema=SCHEMA, database=DB)

# ── Query 1: all purchasers ───────────────────────────────────────────────────
print("Querying all purchasers…")
q_all = f"""
WITH first_sends AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_send_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP}'
    GROUP BY USER_ID
),
first_purchases AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_purchase_at
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP}'
    GROUP BY USER_ID
)
SELECT
    DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) AS hours_to_purchase
FROM first_purchases fp
JOIN first_sends fs ON fp.USER_ID = fs.USER_ID
WHERE fp.first_purchase_at >= fs.first_send_at
"""
rows_all = client.execute_query(q_all)
hours_all = [r["HOURS_TO_PURCHASE"] for r in rows_all]
print(f"  Total purchasers: {len(hours_all):,}")

# ── Query 2: email cohort ────────────────────────────────────────────────────
print("Querying email cohort…")
q_cohort = f"""
WITH first_sends AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_send_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP}'
    GROUP BY USER_ID
),
first_purchases AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_purchase_at
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP}'
    GROUP BY USER_ID
),
email_clickers AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_click_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP}'
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
    GROUP BY USER_ID
)
SELECT
    DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) AS hours_to_purchase
FROM first_purchases fp
JOIN first_sends fs ON fp.USER_ID = fs.USER_ID
JOIN email_clickers ec ON fp.USER_ID = ec.USER_ID
    AND ec.first_click_at <= fp.first_purchase_at
WHERE fp.first_purchase_at >= fs.first_send_at
"""
rows_cohort = client.execute_query(q_cohort)
hours_cohort = [r["HOURS_TO_PURCHASE"] for r in rows_cohort]
print(f"  Email cohort purchasers: {len(hours_cohort):,}")


def bucket(hours_list):
    """Assign each value to a named bucket. Returns list of bucket labels."""
    labels = []
    for h in hours_list:
        if h < 24:
            labels.append("<24h")
        elif h < 24 * 30:
            labels.append("1–29d")
        elif h < 24 * 60:
            labels.append("30–59d")
        elif h < 24 * 90:
            labels.append("60–89d")
        elif h < 24 * 120:
            labels.append("90–119d")
        elif h < 24 * 150:
            labels.append("120–149d")
        elif h < 24 * 180:
            labels.append("150–179d")
        elif h < 24 * 210:
            labels.append("180–209d")
        elif h < 24 * 240:
            labels.append("210–239d")
        elif h < 24 * 270:
            labels.append("240–269d")
        elif h < 24 * 365:
            labels.append("270–364d")
        else:
            labels.append("365d+")
    return labels


BUCKET_ORDER = [
    "<24h", "1–29d", "30–59d", "60–89d", "90–119d",
    "120–149d", "150–179d", "180–209d", "210–239d", "240–269d",
    "270–364d", "365d+",
]


def count_buckets(hours_list):
    labels = bucket(hours_list)
    counts = {b: 0 for b in BUCKET_ORDER}
    for lbl in labels:
        counts[lbl] += 1
    return counts


def make_chart(hours_list, title, subtitle, out_path, bar_color_start="#1a3a5c", bar_color_end="#c0d8f0"):
    counts = count_buckets(hours_list)
    n = len(hours_list)
    names = BUCKET_ORDER
    vals = [counts[b] for b in names]
    pcts = [v / n * 100 for v in vals]
    cumulative = np.cumsum(pcts)

    # Color gradient
    cmap_blues = plt.cm.Blues
    colors = [cmap_blues(0.9 - i * 0.06) for i in range(10)]
    # Last two buckets slightly different shade to signal "beyond prior cap"
    colors += [plt.cm.Oranges(0.55), plt.cm.Oranges(0.35)]

    fig, ax1 = plt.subplots(figsize=(14, 7))
    ax2 = ax1.twinx()

    x = np.arange(len(names))
    bars = ax1.bar(x, vals, color=colors, width=0.7, zorder=2)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, fontsize=11)
    ax1.set_ylabel("Customers", fontsize=12)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax1.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax1.set_axisbelow(True)

    # Labels on bars
    for bar, v, p in zip(bars, vals, pcts):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + n * 0.003,
                 f"{v:,}\n({p:.0f}%)", ha="center", va="bottom", fontsize=9, fontweight="bold")

    # Cumulative line
    ax2.plot(x, cumulative, color="#d45f00", marker="o", linewidth=2.5, zorder=5)
    for xi, cv in zip(x, cumulative):
        if xi % 2 == 1 or xi == len(names) - 1 or xi == 0:
            ax2.text(xi, cv + 2, f"{cv:.0f}%", ha="center", va="bottom",
                     color="#d45f00", fontsize=9, fontweight="bold")
    ax2.set_ylabel("Cumulative %", color="#d45f00", fontsize=12)
    ax2.set_ylim(0, 110)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax2.tick_params(axis="y", colors="#d45f00")
    ax2.legend(handles=[plt.Line2D([0], [0], color="#d45f00", marker="o", linewidth=2)],
               labels=["Cumulative %"], loc="upper right", fontsize=10)

    ax1.set_title(f"{title}\n({subtitle})", fontsize=14, fontweight="bold", pad=14)
    ax1.set_xlabel(
        "Days from First Email Received → First Purchase  (equal 30-day windows; Braze first-send as list entry)",
        fontsize=10, labelpad=8)

    # Annotation note
    ax1.annotate("Note: <24h = 1 day;\nall others = 30 days\nexcept 270–364d (95d)\nand 365d+ (open-ended)",
                 xy=(0, vals[0]), xytext=(2.5, vals[0] * 0.85),
                 arrowprops=dict(arrowstyle="->", color="gray"),
                 fontsize=8, color="gray",
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out_path}")


print("Generating charts…")
make_chart(
    hours_all,
    "Burrow — Time from Joining Email List to First Purchase",
    f"Braze first-send as list entry, n={len(hours_all):,} purchasers",
    "reports/bw_list_to_first_purchase_braze.png",
)
make_chart(
    hours_cohort,
    "Burrow — Email Cohort: Time from Joining List to First Purchase",
    f"email click before purchase, n={len(hours_cohort):,} customers",
    "reports/bw_email_cohort_30d.png",
)
print("Done.")
