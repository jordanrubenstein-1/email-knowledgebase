#!/usr/bin/env python3
"""
Compare Braze vs GA4 revenue for email (and optionally SMS) campaigns.

Loads campaign YAMLs, filters by channel (email by default), and reports:
- Total Braze revenue (performance_summary.total_revenue)
- Total GA4 revenue (performance_summary.ga4.revenue)
- Percent difference overall and by brand
- Campaign-level ratio (GA4/Braze) distribution and whether GA4 can be inferred from Braze

Only campaigns that have BOTH Braze and GA4 revenue are included in the comparison.
GA4 data is populated by import_ga4_metrics_snowflake.py (BUR, CZ, ID only).

Usage:
    uv run python scripts/analysis/compare_braze_ga4_revenue.py
    uv run python scripts/analysis/compare_braze_ga4_revenue.py --channel sms
    uv run python scripts/analysis/compare_braze_ga4_revenue.py --brand ID
    uv run python scripts/analysis/compare_braze_ga4_revenue.py --min-braze 500  # stabler ratios
"""

import argparse
from pathlib import Path
from collections import defaultdict

import yaml


def _percentile(sorted_arr, p):
    """p in [0, 100]. Returns value at percentile."""
    if not sorted_arr:
        return None
    k = (len(sorted_arr) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_arr) else f
    return sorted_arr[f] + (k - f) * (sorted_arr[c] - sorted_arr[f]) if c > f else sorted_arr[f]

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"


def load_campaigns(brand=None, channel="email"):
    """Load campaign YAMLs, optionally filtered by brand and channel."""
    campaigns = []
    for f in CAMPAIGNS_DIR.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        try:
            with open(f) as file:
                data = yaml.safe_load(file)
                if not data:
                    continue
        except Exception:
            continue
        if brand and data.get("brand") != brand:
            continue
        ch = (data.get("channel") or "").strip().lower()
        if ch != channel:
            continue
        campaigns.append(data)
    return campaigns


def main():
    ap = argparse.ArgumentParser(description="Compare Braze vs GA4 revenue for campaigns")
    ap.add_argument("--channel", default="email", choices=["email", "sms"], help="Channel to analyze")
    ap.add_argument("--brand", default=None, help="Limit to one brand (e.g. ID, CZ, BUR)")
    ap.add_argument("--min-braze", type=float, default=0, help="Min Braze revenue to include in ratio/inference (avoids noisy ratios)")
    args = ap.parse_args()

    campaigns = load_campaigns(brand=args.brand, channel=args.channel)

    # Only include campaigns that have BOTH Braze revenue and GA4 revenue
    braze_total = 0.0
    ga4_total = 0.0
    by_brand = defaultdict(lambda: {"braze": 0.0, "ga4": 0.0, "count": 0})
    compared_count = 0
    braze_only_count = 0
    ga4_only_count = 0
    braze_only_revenue = 0.0
    ga4_only_revenue = 0.0
    # Per-campaign (braze, ga4, ratio) for ratio distribution and inference
    campaign_ratios = []  # (braze, ga4, ratio, brand)
    campaign_ratios_by_brand = defaultdict(list)

    for c in campaigns:
        perf = c.get("performance_summary") or {}
        braze_rev = perf.get("total_revenue") or 0.0
        ga4_block = perf.get("ga4") or {}
        ga4_rev = ga4_block.get("revenue") if ga4_block is not None else 0.0
        if ga4_rev is None:
            ga4_rev = 0.0

        has_braze = braze_rev > 0
        has_ga4 = ga4_rev > 0

        if has_braze and has_ga4:
            compared_count += 1
            braze_total += braze_rev
            ga4_total += ga4_rev
            b = c.get("brand") or "unknown"
            by_brand[b]["braze"] += braze_rev
            by_brand[b]["ga4"] += ga4_rev
            by_brand[b]["count"] += 1
            # Ratio = GA4/Braze (share of Braze that GA4 attributes)
            if braze_rev >= args.min_braze:
                ratio = ga4_rev / braze_rev
                campaign_ratios.append((braze_rev, ga4_rev, ratio, b))
                campaign_ratios_by_brand[b].append((braze_rev, ga4_rev, ratio))
        elif has_braze:
            braze_only_count += 1
            braze_only_revenue += braze_rev
        elif has_ga4:
            ga4_only_count += 1
            ga4_only_revenue += ga4_rev

    # Report
    print(f"Channel: {args.channel}")
    if args.brand:
        print(f"Brand: {args.brand}")
    print(f"Campaigns with both Braze and GA4 revenue: {compared_count}")
    print(f"Campaigns with Braze only: {braze_only_count} (Braze revenue: ${braze_only_revenue:,.2f})")
    print(f"Campaigns with GA4 only: {ga4_only_count} (GA4 revenue: ${ga4_only_revenue:,.2f})")
    print()

    if compared_count == 0:
        print("No campaigns with both Braze and GA4 revenue. Run import_ga4_metrics_snowflake.py for BUR, CZ, ID to populate GA4.")
        return

    print("--- Overall (email-attributed) ---")
    print(f"Braze total revenue:  ${braze_total:,.2f}")
    print(f"GA4 total revenue:    ${ga4_total:,.2f}")
    if braze_total != 0:
        pct_diff = ((ga4_total - braze_total) / braze_total) * 100
        print(f"Percent difference:   {pct_diff:+.1f}% (GA4 vs Braze)")
        print("  (Positive = GA4 reports more than Braze; negative = Braze reports more than GA4)")
    print()

    print("--- By brand ---")
    for b in sorted(by_brand.keys()):
        info = by_brand[b]
        br = info["braze"]
        gr = info["ga4"]
        n = info["count"]
        pct = ((gr - br) / br * 100) if br else 0
        print(f"  {b}: campaigns={n}, Braze=${br:,.2f}, GA4=${gr:,.2f}, diff={pct:+.1f}%")

    # --- Campaign-level ratio (GA4/Braze) and inference ---
    if not campaign_ratios:
        return

    ratios_only = [r[2] for r in campaign_ratios]
    ratios_sorted = sorted(ratios_only)
    n_rat = len(ratios_only)
    median_ratio = _percentile(ratios_sorted, 50)
    # Exclude outlier ratios (GA4 > 2x Braze) for "core" stats — aggregate is ~6% so ratio > 0.5 is outlier
    core_ratios = sorted([r for (_b, _g, r, _br) in campaign_ratios if 0 < r <= 0.5])
    n_core = len(core_ratios)
    if n_core:
        med_core = _percentile(core_ratios, 50)
        mean_core = sum(core_ratios) / n_core
        iqr = _percentile(core_ratios, 75) - _percentile(core_ratios, 25)
    else:
        med_core = mean_core = iqr = 0

    print()
    print("--- Campaign-level ratio (GA4 / Braze) ---")
    if args.min_braze > 0:
        print(f"  (Campaigns with Braze revenue >= ${args.min_braze:,.0f}: {n_rat})")
    print(f"  Count: {n_rat}")
    print(f"  Median: {median_ratio:.4f}  (GA4 ≈ {median_ratio*100:.1f}% of Braze)")
    print(f"  P10: {_percentile(ratios_sorted, 10):.4f}   P25: {_percentile(ratios_sorted, 25):.4f}   P75: {_percentile(ratios_sorted, 75):.4f}   P90: {_percentile(ratios_sorted, 90):.4f}")
    print(f"  Min: {ratios_sorted[0]:.4f}   Max: {ratios_sorted[-1]:.4f}  (max often outlier: GA4 > Braze)")
    print(f"  Excluding ratio > 0.5 (outliers): n={n_core}, median={med_core:.4f}, mean={mean_core:.4f}, IQR={iqr:.4f}")

    # By-brand ratio stats (median is stable; mean is skewed by outliers)
    print()
    print("--- Ratio by brand (median GA4/Braze) ---")
    for b in sorted(campaign_ratios_by_brand.keys()):
        lst = campaign_ratios_by_brand[b]
        ratios_b = sorted([x[2] for x in lst])
        med = _percentile(ratios_b, 50)
        p25 = _percentile(ratios_b, 25)
        p75 = _percentile(ratios_b, 75)
        print(f"  {b}: n={len(lst)}, median={med:.4f}  (P25–P75: {p25:.4f}–{p75:.4f})")

    # Infer GA4 from Braze: GA4_est = k * Braze. Use median ratio (robust to outliers).
    ga4_vals = [r[1] for r in campaign_ratios]
    braze_vals = [r[0] for r in campaign_ratios]
    ga4_mean = sum(ga4_vals) / len(ga4_vals)
    ss_tot = sum((g - ga4_mean) ** 2 for g in ga4_vals)
    # OLS single multiplier
    sum_gb = sum(g * b for g, b in zip(ga4_vals, braze_vals))
    sum_bb = sum(b * b for b in braze_vals)
    k_ols = sum_gb / sum_bb if sum_bb else 0
    ss_res_ols = sum((g - k_ols * b) ** 2 for g, b in zip(ga4_vals, braze_vals))
    r2_ols = 1 - (ss_res_ols / ss_tot) if ss_tot else 0
    # Using median ratio (recommended for inference)
    ga4_est_med = [median_ratio * b for b in braze_vals]
    ss_res_med = sum((g - e) ** 2 for g, e in zip(ga4_vals, ga4_est_med))
    r2_med = 1 - (ss_res_med / ss_tot) if ss_tot else 0

    print()
    print("--- Infer GA4 from Braze ---")
    print(f"  Rule: GA4_estimated = k * Braze")
    print(f"  k = median(GA4/Braze):  k = {median_ratio:.4f}  ->  R² = {r2_med:.4f}")
    print(f"  k = OLS (best fit):     k = {k_ols:.4f}  ->  R² = {r2_ols:.4f}")
    if r2_med >= 0.5:
        print("  -> Ratio is fairly consistent; inferring GA4 from Braze is reasonable.")
    elif r2_med >= 0.3:
        print("  -> Ratio is moderately consistent; inferred GA4 is a rough proxy.")
    else:
        print("  -> Campaign-level variance is high (many small campaigns); use for aggregates rather than single-campaign estimates.")
    print(f"  Example: Braze $10,000 -> GA4 ≈ ${median_ratio * 10000:,.0f} (using median ratio {median_ratio:.2%})")


if __name__ == "__main__":
    main()
