"""
WELCOME15-A6J8D3 usage over time for Interior Define.
Shades ID sale periods from sale_schedules.yaml, labels active between-sale clusters.
Output: reports/id_welcome15_usage.png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import pandas as pd

# --- Redemption data — ORDER_CREATED_AT converted to America/Denver (MT) ---
# (date, redemptions, revenue, discount)
raw = [
    ("2025-10-22", 3,  11049.09, -1557.75), ("2025-10-23", 4,  17983.23, -2573.25),
    ("2025-10-24", 2,   6285.81,  -882.75), ("2025-10-25", 1,   2004.98,  -265.50),
    ("2025-10-26", 7,  17574.54, -2438.25),
    ("2025-11-04", 2,   2532.88,  -300.00), ("2025-11-05", 1,   4342.48,  -622.50),
    ("2025-11-06", 3,   5926.16,  -785.25), ("2025-11-07", 1,   1267.04,  -147.00),
    ("2025-11-10", 5,  17388.86, -2420.25), ("2025-11-12", 1,   2057.47,  -274.50),
    ("2025-11-20", 1,   1656.75,  -207.00),
    ("2025-12-01", 1,   4022.12,  -580.50),
    ("2025-12-11", 1,   2363.03,  -320.25), ("2025-12-12", 2,   2719.17,  -347.25),
    ("2025-12-14", 1,   5642.53,  -834.00), ("2025-12-15", 4,  14817.90, -2135.40),
    ("2025-12-16", 2,   4372.40,  -564.00), ("2025-12-17", 3,  13641.16, -1999.80),
    ("2026-01-08", 3,   9982.08, -1409.10), ("2026-01-09", 3,  17278.43, -2520.00),
    ("2026-01-10", 4,   7290.35,  -949.50), ("2026-01-11", 6,  20675.88, -2940.00),
    ("2026-01-12", 2,   6186.69,  -860.25), ("2026-01-13", 2,   8133.83, -1154.25),
    ("2026-01-14", 2,   6562.28,  -953.25), ("2026-01-16", 1,   1249.51,  -159.75),
    ("2026-01-28", 1,   1263.24,  -144.75), ("2026-01-29", 1,   2552.01,  -342.00),
    ("2026-01-31", 2,   3556.60,  -452.25),
    ("2026-02-01", 6,  18076.29, -2508.75), ("2026-02-02", 2,   5182.76,  -666.75),
    ("2026-02-03", 2,   3143.94,  -365.25), ("2026-02-04", 2,   7338.64, -1038.75),
    ("2026-02-05", 3,  17542.93, -2708.25), ("2026-02-07", 1,   1747.80,  -228.75),
    ("2026-02-14", 1,   2411.42,  -342.00), ("2026-02-17", 1,   2358.25,  -319.50),
    ("2026-02-28", 1,   1501.58,  -182.25),
    ("2026-03-01", 3,  11697.04, -1661.25), ("2026-03-02", 5,  17658.09, -2533.50),
    ("2026-03-03", 1,   1260.99,  -144.75), ("2026-03-04", 4,   8340.70, -1086.00),
    ("2026-03-05", 3,  13403.51, -1975.50), ("2026-03-06", 2,   4719.14,  -652.50),
    ("2026-03-07", 3,   8998.58, -1251.00), ("2026-03-08", 9,  24974.26, -3498.00),
    ("2026-03-09", 3,   6808.81,  -912.75), ("2026-03-10", 2,   8506.43, -1230.75),
    ("2026-03-12", 1,   2292.34,  -312.00),
    ("2026-04-01", 2,  16241.84, -2472.75), ("2026-04-03", 2,   1515.28,  -168.00),
    ("2026-04-04", 3,   7348.44,  -959.25), ("2026-04-05", 8,  23851.57, -3368.25),
    ("2026-04-06", 3,  13832.07, -2054.25), ("2026-04-07", 6,  16188.40, -2169.75),
    ("2026-04-08", 4,  21203.15, -3120.75),
    ("2026-04-29", 3,   5853.53,  -748.50), ("2026-04-30", 6,  23688.29, -4121.25),
    ("2026-05-04", 1,   3630.92,  -503.25),
    ("2026-06-03", 2,   6731.37,  -980.25), ("2026-06-04", 1,   1573.65,  -199.50),
    ("2026-06-05", 1,   2115.58,  -276.75), ("2026-06-07", 1,   2533.93,  -336.00),
    ("2026-06-09", 5,  18473.04, -2625.00), ("2026-06-10", 2,   6715.83, -1011.75),
    ("2026-06-12", 1,   1070.85,  -115.50), ("2026-06-13", 4,   7901.21, -1135.50),
]
df = pd.DataFrame(raw, columns=["date", "redemptions", "revenue", "discount"])
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()

total_uses     = int(df["redemptions"].sum())
total_revenue  = df["revenue"].sum()
total_discount = abs(df["discount"].sum())
avg_order      = total_revenue / total_uses if total_uses else 0

full_range = pd.date_range("2025-10-22", "2026-06-13", freq="D")
df = df.reindex(full_range, fill_value=0)

XMIN = pd.Timestamp("2025-10-15")
XMAX = pd.Timestamp("2026-06-21")

# --- Sale periods ---
# (label, start, end, row)  row=0 top strip, row=1 alternate strip height
sale_periods = [
    ("Autumn Event",          "2025-10-09", "2025-10-21", 1),
    ("BF Backpocket",         "2025-10-24", "2025-10-26", 0),
    ("Black Friday Now",      "2025-10-27", "2025-11-03", 1),
    ("BF Event (Paid)",       "2025-11-04", "2025-11-12", 0),
    ("BFCM + Ext",            "2025-11-11", "2025-12-09", 1),
    ("End of Year + Ext",     "2025-12-18", "2026-01-06", 1),
    ("Winter Refresh",        "2026-01-15", "2026-01-27", 0),
    ("Presidents Day + Ext",  "2026-02-06", "2026-02-26", 1),
    ("Spring Refresh",        "2026-03-10", "2026-03-31", 1),
    ("April Reset",           "2026-04-09", "2026-04-28", 0),
    ("MDW Preview → Ext",     "2026-05-01", "2026-06-02", 1),
    ("Weekender Sale",        "2026-06-05", "2026-06-08", 0),
]

# --- Active clusters (between sales) ---
# counts derived from MT-corrected data
active_clusters = [
    ("Launch\n17 uses",           "2025-10-24",  17, "#2980B9"),
    ("Post-BF Now\n14 uses",      "2025-11-08",  14, "#2980B9"),
    ("Post-BFCM\n14 uses",        "2025-12-12",  14, "#2980B9"),
    ("Post-EOY\n23 uses",         "2026-01-11",  23, "#27AE60"),
    ("Post-Winter\n22 uses",      "2026-02-02",  22, "#27AE60"),
    ("Post-Pres Day\n37 uses",    "2026-03-05",  37, "#27AE60"),
    ("Post-Spring\n28 uses",      "2026-04-05",  28, "#E67E22"),
    ("Post-April Reset\n10 uses", "2026-04-30",  10, "#E67E22"),
    ("Post-MDW\n17 uses",         "2026-06-09",  17, "#8E44AD"),
]

# ─── Figure: 2-row layout ───────────────────────────────────────────────────
fig = plt.figure(figsize=(20, 8.5))
gs = fig.add_gridspec(2, 1, height_ratios=[1, 4], hspace=0.05)
ax_timeline = fig.add_subplot(gs[0])
ax_main     = fig.add_subplot(gs[1], sharex=ax_timeline)

# ── Timeline strip (top) ─────────────────────────────────────────────────────
ax_timeline.set_xlim(XMIN, XMAX)
ax_timeline.set_ylim(0, 2)
ax_timeline.set_yticks([])
ax_timeline.set_ylabel("Sales", fontsize=8, rotation=0, labelpad=38)
for spine in ax_timeline.spines.values():
    spine.set_visible(False)

SALE_COLORS = ["#E74C3C", "#C0392B"]
for (name, start, end, row) in sale_periods:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    # clamp to visible range
    s_plot = max(s, XMIN)
    e_plot = min(e, XMAX)
    if s_plot >= e_plot:
        continue
    ylo, yhi = (0.05, 0.95) if row == 1 else (0.55, 1.45)
    rect = mpatches.FancyBboxPatch(
        (mdates.date2num(s_plot), ylo),
        mdates.date2num(e_plot) - mdates.date2num(s_plot),
        yhi - ylo,
        boxstyle="square,pad=0",
        linewidth=0,
        facecolor=SALE_COLORS[row],
        alpha=0.80,
        zorder=3,
        transform=ax_timeline.transData
    )
    ax_timeline.add_patch(rect)
    mid = s_plot + (e_plot - s_plot) / 2
    y_txt = (ylo + yhi) / 2
    label_w = (e_plot - s_plot).days
    fontsize = 7.5 if label_w >= 7 else 6.5
    ax_timeline.text(
        mdates.date2num(mid), y_txt, name,
        ha="center", va="center", fontsize=fontsize,
        color="white", fontweight="bold", zorder=4,
        transform=ax_timeline.transData
    )

ax_timeline.axhline(0.05, color="#aaa", linewidth=0.4, zorder=1)
ax_timeline.axhline(1.45, color="#aaa", linewidth=0.4, zorder=1)
ax_timeline.set_title(
    "WELCOME15-A6J8D3 — ID Welcome Discount (15% off)  ·  Usage vs. Sale Calendar  (dates in MT)",
    fontsize=13, fontweight="bold", pad=9
)

# ── Main chart (bottom) ───────────────────────────────────────────────────────
# Shade sale bands lightly in main chart too
for (name, start, end, row) in sale_periods:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    ax_main.axvspan(s, e, alpha=0.10, color="#E74C3C", zorder=1)

# Bars, colored by which cluster they belong to
bar_colors = []
cluster_map = {}
for (lbl, cdate, cnt, col) in active_clusters:
    # find the date range for this cluster from raw data around that center
    pass

# Just use uniform blue for bars, highlight active clusters with background tint
ax_main.bar(df.index, df["redemptions"], color="#3498DB", width=0.92, alpha=0.85, zorder=3)

# Vertical dashed lines at sale boundaries
for (name, start, end, row) in sale_periods:
    ax_main.axvline(pd.Timestamp(start), color="#c0392b", linewidth=0.6,
                    linestyle="--", alpha=0.45, zorder=2)
    ax_main.axvline(pd.Timestamp(end),   color="#c0392b", linewidth=0.6,
                    linestyle="--", alpha=0.45, zorder=2)

# Active cluster labels with brackets
cluster_y = 13.0
for (lbl, cdate, cnt, col) in active_clusters:
    cx = pd.Timestamp(cdate)
    ax_main.annotate(
        lbl,
        xy=(cx, cluster_y), xycoords="data",
        ha="center", va="bottom", fontsize=7.8,
        color=col, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.22", facecolor="white",
                  edgecolor=col, linewidth=0.9, alpha=0.9),
        zorder=6,
    )

# X axis
ax_main.xaxis.set_major_locator(mdates.MonthLocator())
ax_main.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
ax_main.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))
ax_main.tick_params(axis="x", which="major", labelsize=9, pad=4)
ax_main.set_xlim(XMIN, XMAX)
ax_main.set_ylim(0, 14.5)
ax_main.set_ylabel("Daily Redemptions", fontsize=11)
ax_main.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=6))
ax_main.grid(axis="y", linestyle="--", alpha=0.35, zorder=0)
ax_main.set_axisbelow(True)

# Legend
sale_patch = mpatches.Patch(color="#E74C3C", alpha=0.65, label="ID Sale Period (code suppressed)")
code_patch = mpatches.Patch(color="#3498DB", alpha=0.85, label="WELCOME15 daily redemptions")
ax_main.legend(handles=[code_patch, sale_patch], loc="upper left", fontsize=9, framealpha=0.95)

# Stats box
ax_main.annotate(
    f"{total_uses} total uses  ·  ${total_revenue/1000:.0f}K revenue  ·  ${total_discount/1000:.0f}K discounts  ·  Avg ${avg_order:,.0f}/order",
    xy=(0.995, 0.015), xycoords="axes fraction",
    ha="right", va="bottom", fontsize=8.5,
    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#ccc", alpha=0.95),
    zorder=7,
)

plt.setp(ax_timeline.get_xticklabels(), visible=False)
fig.patch.set_facecolor("white")

out = "/Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase/reports/id_welcome15_usage.png"
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Saved: {out}")

