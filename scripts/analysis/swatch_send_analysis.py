"""
Swatch vs General email send count analysis.

Compares total send volume for campaigns with "Swatch" in the name
against all other batch/blast email campaigns, from the earliest record
through Dec 31, 2025.
"""

import glob
import sys
from collections import defaultdict
from pathlib import Path

import yaml

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
CUTOFF_DATE = "2025-12-31"


def is_batch_email(c: dict) -> bool:
    channel = c.get("channel", "email")
    if channel not in ("email", None, ""):
        return False
    braze_type = c.get("braze_type", "") or ""
    klaviyo_type = c.get("klaviyo_type", "") or ""
    if braze_type in ("canvas_step", "canvas"):
        return False
    if klaviyo_type == "flow":
        return False
    return True


def load_campaigns() -> list[dict]:
    seen_ids: set[str] = set()
    campaigns = []
    paths = sorted(glob.glob(str(CAMPAIGNS_DIR / "*.yaml")))
    for path in paths:
        try:
            with open(path) as f:
                c = yaml.safe_load(f)
            if not isinstance(c, dict):
                continue
            cid = c.get("id", "")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            campaigns.append(c)
        except Exception:
            continue
    return campaigns


def main():
    print(f"Loading campaigns from {CAMPAIGNS_DIR}...")
    all_campaigns = load_campaigns()
    print(f"  Loaded {len(all_campaigns):,} YAMLs")

    # Filter to batch email campaigns through cutoff date
    batch_email = []
    skipped_type = 0
    skipped_date = 0
    skipped_no_date = 0

    for c in all_campaigns:
        if not is_batch_email(c):
            skipped_type += 1
            continue
        first_sent = (c.get("dates") or {}).get("first_sent", "")
        if not first_sent:
            skipped_no_date += 1
            continue
        if str(first_sent)[:10] > CUTOFF_DATE:
            skipped_date += 1
            continue
        batch_email.append(c)

    print(f"  After filters: {len(batch_email):,} batch email campaigns")
    print(f"  Skipped — triggered/canvas: {skipped_type:,} | post-cutoff: {skipped_date:,} | no date: {skipped_no_date:,}")

    # Separate campaigns with zero sends (Klaviyo analytics gaps)
    with_sends = [c for c in batch_email if (c.get("performance_summary") or {}).get("total_sends", 0) > 0]
    zero_sends = [c for c in batch_email if (c.get("performance_summary") or {}).get("total_sends", 0) == 0]
    print(f"  With send data: {len(with_sends):,} | Zero sends (excluded): {len(zero_sends):,}")

    # Classify and aggregate
    summary = defaultdict(lambda: {"campaigns": 0, "sends": 0})
    by_brand = defaultdict(lambda: {"swatch": {"campaigns": 0, "sends": 0}, "other": {"campaigns": 0, "sends": 0}})
    by_month = defaultdict(lambda: {"swatch": 0, "other": 0})
    swatch_campaigns_list = []

    for c in with_sends:
        name = c.get("name", "") or ""
        brand = c.get("brand", "UNKNOWN") or "UNKNOWN"
        sends = (c.get("performance_summary") or {}).get("total_sends", 0)
        first_sent = str((c.get("dates") or {}).get("first_sent", ""))[:7]  # YYYY-MM

        category = "swatch" if "swatch" in name.lower() else "other"

        summary[category]["campaigns"] += 1
        summary[category]["sends"] += sends
        by_brand[brand][category]["campaigns"] += 1
        by_brand[brand][category]["sends"] += sends
        if first_sent:
            by_month[first_sent][category] += sends

        if category == "swatch":
            swatch_campaigns_list.append((first_sent, brand, name, sends))

    swatch_campaigns_list.sort(key=lambda x: x[3], reverse=True)

    # Build report
    lines = []
    lines.append("# Swatch vs General Email Send Count Analysis")
    lines.append(f"\n**Date range:** Earliest record – Dec 31, 2025  ")
    lines.append(f"**Scope:** Batch/blast email campaigns only (canvas steps and triggered flows excluded)  ")
    lines.append("**Swatch definition:** Campaign name contains \"Swatch\" (case-insensitive)  ")
    lines.append(f"**Campaigns with zero sends excluded:** {len(zero_sends):,} (Klaviyo analytics gap)  ")

    # Summary table
    lines.append("\n## Summary\n")
    lines.append("| Category | Campaigns | Total Sends | Avg Sends/Campaign |")
    lines.append("|----------|----------:|------------:|------------------:|")
    total_sends_all = sum(v["sends"] for v in summary.values())
    for cat in ("swatch", "other"):
        d = summary[cat]
        avg = d["sends"] // d["campaigns"] if d["campaigns"] else 0
        pct = d["sends"] / total_sends_all * 100 if total_sends_all else 0
        label = "Swatch" if cat == "swatch" else "Other (general/purchase)"
        lines.append(f"| {label} | {d['campaigns']:,} | {d['sends']:,} ({pct:.1f}%) | {avg:,} |")
    lines.append(f"| **Total** | **{sum(v['campaigns'] for v in summary.values()):,}** | **{total_sends_all:,}** | |")

    # By brand
    lines.append("\n## By Brand\n")
    lines.append("| Brand | Swatch Campaigns | Swatch Sends | Other Campaigns | Other Sends | Swatch % of Brand Sends |")
    lines.append("|-------|----------------:|-------------:|----------------:|------------:|------------------------:|")
    for brand in sorted(by_brand.keys()):
        s = by_brand[brand]["swatch"]
        o = by_brand[brand]["other"]
        brand_total = s["sends"] + o["sends"]
        swatch_pct = s["sends"] / brand_total * 100 if brand_total else 0
        lines.append(
            f"| {brand} | {s['campaigns']:,} | {s['sends']:,} | {o['campaigns']:,} | {o['sends']:,} | {swatch_pct:.1f}% |"
        )

    # Monthly trend
    lines.append("\n## Monthly Send Trend\n")
    lines.append("| Month | Swatch Sends | Other Sends | Swatch % |")
    lines.append("|-------|------------:|------------:|---------:|")
    for month in sorted(by_month.keys()):
        sw = by_month[month]["swatch"]
        ot = by_month[month]["other"]
        total = sw + ot
        pct = sw / total * 100 if total else 0
        lines.append(f"| {month} | {sw:,} | {ot:,} | {pct:.1f}% |")

    # Top swatch campaigns
    lines.append("\n## Top Swatch Campaigns by Send Volume\n")
    lines.append("| Month | Brand | Campaign Name | Sends |")
    lines.append("|-------|-------|---------------|------:|")
    for month, brand, name, sends in swatch_campaigns_list[:30]:
        lines.append(f"| {month} | {brand} | {name} | {sends:,} |")

    report = "\n".join(lines)

    out_path = REPORTS_DIR / "swatch-send-analysis.md"
    out_path.write_text(report)
    print(f"\nReport written to {out_path}")

    # Print summary to stdout
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for cat in ("swatch", "other"):
        d = summary[cat]
        avg = d["sends"] // d["campaigns"] if d["campaigns"] else 0
        label = "Swatch" if cat == "swatch" else "Other"
        print(f"{label:6s}: {d['campaigns']:4,} campaigns | {d['sends']:>12,} sends | avg {avg:,}/campaign")
    print(f"{'Total':6s}: {sum(v['campaigns'] for v in summary.values()):4,} campaigns | {total_sends_all:>12,} sends")

    print("\nBy brand (swatch):")
    for brand in sorted(by_brand.keys()):
        s = by_brand[brand]["swatch"]
        if s["campaigns"] > 0:
            print(f"  {brand}: {s['campaigns']} campaigns, {s['sends']:,} sends")


if __name__ == "__main__":
    main()
