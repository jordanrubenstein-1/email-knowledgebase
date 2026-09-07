"""
Burrow: First-24-hour breakdown for all purchasers and email cohort.
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
BUR = "67093a1f24ebbe0065cb9c77"

client = get_snowflake_client(schema=SCHEMA, database=DB)

print("Querying all purchasers <24h by hour…")
q_all = f"""
WITH first_sends AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_send_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR}'
    GROUP BY USER_ID
),
first_purchases AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_purchase_at
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
    WHERE APP_GROUP_ID = '{BUR}'
    GROUP BY USER_ID
)
SELECT DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) AS hour_gap
FROM first_purchases fp
JOIN first_sends fs ON fp.USER_ID = fs.USER_ID
WHERE fp.first_purchase_at >= fs.first_send_at
  AND DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) < 24
"""
rows_all = client.execute_query(q_all)
hours_all = [r["HOUR_GAP"] for r in rows_all]
print(f"  n={len(hours_all):,}")

print("Querying email cohort <24h by hour…")
q_cohort = f"""
WITH first_sends AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_send_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR}'
    GROUP BY USER_ID
),
first_purchases AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_purchase_at
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_PURCHASE_SHARED
    WHERE APP_GROUP_ID = '{BUR}'
    GROUP BY USER_ID
),
email_clickers AS (
    SELECT USER_ID, TO_TIMESTAMP(MIN(TIME)) AS first_click_at
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_CLICK_SHARED
    WHERE APP_GROUP_ID = '{BUR}'
      AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
    GROUP BY USER_ID
)
SELECT DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) AS hour_gap
FROM first_purchases fp
JOIN first_sends fs ON fp.USER_ID = fs.USER_ID
JOIN email_clickers ec ON fp.USER_ID = ec.USER_ID
    AND ec.first_click_at <= fp.first_purchase_at
WHERE fp.first_purchase_at >= fs.first_send_at
  AND DATEDIFF('hour', fs.first_send_at, fp.first_purchase_at) < 24
"""
rows_cohort = client.execute_query(q_cohort)
hours_cohort = [r["HOUR_GAP"] for r in rows_cohort]
print(f"  n={len(hours_cohort):,}")


def make_hourly_chart(hour_list, title, subtitle, out_path):
    counts = [0] * 24
    for h in hour_list:
        counts[int(h)] += 1
    n = len(hour_list)
    pcts = [c / n * 100 for c in counts]

    fig, ax = plt.subplots(figsize=(13, 6))
    x = np.arange(24)
    colors = [plt.cm.Blues(0.4 + 0.5 * (c / max(counts))) for c in counts]
    bars = ax.bar(x, counts, color=colors, width=0.7, zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}h" for h in range(24)], fontsize=10)
    ax.set_xlabel("Hours after first email received (true 24h window)", fontsize=11, labelpad=8)
    ax.set_ylabel("Customers", fontsize=12)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)

    for bar, c, p in zip(bars, counts, pcts):
        if c > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + n * 0.003,
                    f"{c:,}\n({p:.1f}%)", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax.set_title(f"{title}\n({subtitle})", fontsize=13, fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out_path}")


print("Generating hourly charts…")
make_hourly_chart(
    hours_all,
    "Burrow — First 24 Hours: All Purchasers",
    f"n={len(hours_all):,} customers who purchased within 24h of first email",
    "reports/bw_same_day_hourly_all.png",
)
make_hourly_chart(
    hours_cohort,
    "Burrow — First 24 Hours: Email Cohort",
    f"n={len(hours_cohort):,} customers with email click before purchase",
    "reports/bw_same_day_hourly_cohort.png",
)
print("Done.")
