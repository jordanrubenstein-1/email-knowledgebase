#!/usr/bin/env python3
"""
Audit sender info (From Name, From Email, Reply-To) for plain-text vs designed
promotional emails across all brands.

Queries the Braze API for recent P_*_PT_* and P_*_D_* campaigns, extracts
sender info from campaign details, and outputs a per-brand comparison.

Usage:
    # Audit all brands (requires BRAZE_API_KEY_{BRAND} in .env)
    uv run python scripts/analysis/audit_pt_sender_info.py

    # Single brand
    uv run python scripts/analysis/audit_pt_sender_info.py --brand HAV

    # Write markdown report
    uv run python scripts/analysis/audit_pt_sender_info.py --report
"""

import argparse
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root and scripts for import_braze
_root = Path(__file__).resolve().parent.parent.parent
_scripts = _root / "scripts"
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_scripts))
from dotenv import load_dotenv

load_dotenv(_root / ".env")

from import_braze import (
    init_config,
    get_campaigns,
    get_campaign_details,
    parse_date,
)

BRANDS = ["HAV", "CZ", "ID", "BUR", "STF", "TI"]
WORKERS = 8
LOOKBACK_DAYS = 90  # Look back 90 days to find enough PT campaigns


def parse_from_field(from_str: str) -> dict:
    """Parse a From header string like 'Display Name <email@domain.com>'.

    Returns dict with from_name, from_email. If the string is just an email
    address, from_name will be empty.
    """
    if not from_str:
        return {"from_name": "", "from_email": ""}
    # Match "Display Name <email@domain.com>"
    m = re.match(r"^(.*?)\s*<([^>]+)>$", from_str.strip())
    if m:
        return {"from_name": m.group(1).strip(), "from_email": m.group(2).strip()}
    # Just an email address
    if "@" in from_str:
        return {"from_name": "", "from_email": from_str.strip()}
    return {"from_name": from_str.strip(), "from_email": ""}


def is_pt_campaign(name: str) -> bool:
    """Check if campaign name indicates plain-text (PT)."""
    upper = name.upper()
    return upper.startswith("P_") and "_PT_" in upper


def is_designed_campaign(name: str) -> bool:
    """Check if campaign name indicates designed (D)."""
    upper = name.upper()
    return upper.startswith("P_") and "_D_" in upper


def fetch_sender_info_for_brand(brand: str, max_pt: int = 10, max_d: int = 5):
    """Fetch sender info for recent PT and D campaigns for a brand.

    Returns:
        dict with keys 'brand', 'pt_campaigns', 'd_campaigns', 'error'
    """
    result = {"brand": brand, "pt_campaigns": [], "d_campaigns": [], "error": None}

    try:
        init_config(brand)
    except SystemExit:
        result["error"] = f"No API key for {brand}"
        return result

    print(f"\n{'='*60}")
    print(f"  {brand}: Fetching campaigns...")
    print(f"{'='*60}")

    try:
        campaigns = get_campaigns(include_archived=False)
    except Exception as e:
        result["error"] = f"Failed to fetch campaigns: {e}"
        print(f"  ERROR: {result['error']}")
        return result

    if not campaigns:
        result["error"] = "No campaigns returned"
        print(f"  No campaigns found for {brand}")
        return result

    # Filter to P_ campaigns with PT or D
    pt_candidates = [c for c in campaigns if is_pt_campaign(c.get("name", ""))]
    d_candidates = [c for c in campaigns if is_designed_campaign(c.get("name", ""))]

    print(f"  Total campaigns: {len(campaigns)}")
    print(f"  PT candidates: {len(pt_candidates)}")
    print(f"  D candidates: {len(d_candidates)}")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    # Fetch details for PT campaigns
    if pt_candidates:
        print(f"  Fetching details for up to {max_pt} PT campaigns...")
        pt_found = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            future_to_c = {
                executor.submit(get_campaign_details, c["id"]): c
                for c in pt_candidates[:max_pt * 3]  # fetch extra in case some are old
            }
            for future in as_completed(future_to_c):
                c = future_to_c[future]
                try:
                    details = future.result()
                except Exception as e:
                    print(f"    Error {c.get('name', c['id'])}: {e}", file=sys.stderr)
                    continue
                if not details or "messages" not in details:
                    continue
                last_sent = parse_date(details.get("last_sent"))
                if last_sent:
                    if last_sent.tzinfo is None:
                        last_sent = last_sent.replace(tzinfo=timezone.utc)
                    if last_sent < cutoff:
                        continue

                for msg_id, msg in details.get("messages", {}).items():
                    if msg.get("channel") != "email":
                        continue
                    from_str = msg.get("from") or ""
                    reply_to = msg.get("reply_to") or ""
                    parsed = parse_from_field(from_str)
                    result["pt_campaigns"].append({
                        "name": c["name"],
                        "from_raw": from_str,
                        "from_name": parsed["from_name"],
                        "from_email": parsed["from_email"],
                        "reply_to": reply_to,
                        "last_sent": str(last_sent) if last_sent else "unknown",
                    })
                    pt_found += 1
                    break  # Only need first email message per campaign

                if pt_found >= max_pt:
                    break

    # Fetch details for D campaigns
    if d_candidates:
        print(f"  Fetching details for up to {max_d} D campaigns...")
        d_found = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            future_to_c = {
                executor.submit(get_campaign_details, c["id"]): c
                for c in d_candidates[:max_d * 3]
            }
            for future in as_completed(future_to_c):
                c = future_to_c[future]
                try:
                    details = future.result()
                except Exception as e:
                    print(f"    Error {c.get('name', c['id'])}: {e}", file=sys.stderr)
                    continue
                if not details or "messages" not in details:
                    continue
                last_sent = parse_date(details.get("last_sent"))
                if last_sent:
                    if last_sent.tzinfo is None:
                        last_sent = last_sent.replace(tzinfo=timezone.utc)
                    if last_sent < cutoff:
                        continue

                for msg_id, msg in details.get("messages", {}).items():
                    if msg.get("channel") != "email":
                        continue
                    from_str = msg.get("from") or ""
                    reply_to = msg.get("reply_to") or ""
                    parsed = parse_from_field(from_str)
                    result["d_campaigns"].append({
                        "name": c["name"],
                        "from_raw": from_str,
                        "from_name": parsed["from_name"],
                        "from_email": parsed["from_email"],
                        "reply_to": reply_to,
                        "last_sent": str(last_sent) if last_sent else "unknown",
                    })
                    d_found += 1
                    break

                if d_found >= max_d:
                    break

    print(f"  Found {len(result['pt_campaigns'])} PT, {len(result['d_campaigns'])} D")
    return result


def summarize_sender_info(campaigns: list) -> dict:
    """Summarize the most common sender info from a list of campaigns.

    Returns dict with from_name, from_email, reply_to (most common values).
    """
    if not campaigns:
        return {"from_name": "", "from_email": "", "reply_to": "", "count": 0}

    from_names = defaultdict(int)
    from_emails = defaultdict(int)
    reply_tos = defaultdict(int)

    for c in campaigns:
        if c["from_name"]:
            from_names[c["from_name"]] += 1
        if c["from_email"]:
            from_emails[c["from_email"]] += 1
        if c["reply_to"]:
            reply_tos[c["reply_to"]] += 1

    def most_common(d):
        if not d:
            return ""
        return max(d, key=d.get)

    return {
        "from_name": most_common(from_names),
        "from_email": most_common(from_emails),
        "reply_to": most_common(reply_tos),
        "count": len(campaigns),
        "all_from_names": dict(from_names),
        "all_from_emails": dict(from_emails),
        "all_reply_tos": dict(reply_tos),
    }


def print_report(all_results: list, write_file: bool = False):
    """Print and optionally write the audit report."""
    lines = []

    def p(text=""):
        print(text)
        lines.append(text)

    p("=" * 70)
    p("  PT vs Designed Email Sender Info Audit")
    p(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    p("=" * 70)

    # Summary table
    p()
    p("## Summary: PT Sender Info by Brand")
    p()
    p("| Brand | Type | From Name | From Email | Reply-To | Count |")
    p("|-------|------|-----------|------------|----------|-------|")

    brand_configs = {}  # For YAML output

    for r in all_results:
        brand = r["brand"]
        if r["error"]:
            p(f"| {brand} | -- | ERROR: {r['error']} | | | |")
            continue

        pt_summary = summarize_sender_info(r["pt_campaigns"])
        d_summary = summarize_sender_info(r["d_campaigns"])

        if pt_summary["count"] > 0:
            p(
                f"| {brand} | **PT** | {pt_summary['from_name']} "
                f"| {pt_summary['from_email']} "
                f"| {pt_summary['reply_to']} "
                f"| {pt_summary['count']} |"
            )
        else:
            p(f"| {brand} | **PT** | (no PT campaigns found) | | | 0 |")

        if d_summary["count"] > 0:
            p(
                f"| {brand} | D | {d_summary['from_name']} "
                f"| {d_summary['from_email']} "
                f"| {d_summary['reply_to']} "
                f"| {d_summary['count']} |"
            )
        else:
            p(f"| {brand} | D | (no D campaigns found) | | | 0 |")

        # Check for differences
        if pt_summary["count"] > 0 and d_summary["count"] > 0:
            diffs = []
            if pt_summary["from_name"] != d_summary["from_name"]:
                diffs.append(
                    f"From Name: PT='{pt_summary['from_name']}' vs D='{d_summary['from_name']}'"
                )
            if pt_summary["from_email"] != d_summary["from_email"]:
                diffs.append(
                    f"From Email: PT='{pt_summary['from_email']}' vs D='{d_summary['from_email']}'"
                )
            if pt_summary["reply_to"] != d_summary["reply_to"]:
                diffs.append(
                    f"Reply-To: PT='{pt_summary['reply_to']}' vs D='{d_summary['reply_to']}'"
                )
            if diffs:
                p(f"| | **DIFF** | {' / '.join(diffs)} | | | |")

        # Store for YAML config suggestion
        if pt_summary["count"] > 0:
            brand_configs[brand] = {
                "pt": {
                    "from_name": pt_summary["from_name"],
                    "from_email": pt_summary["from_email"],
                    "reply_to": pt_summary["reply_to"],
                },
            }
            if d_summary["count"] > 0:
                brand_configs[brand]["designed"] = {
                    "from_name": d_summary["from_name"],
                    "from_email": d_summary["from_email"],
                    "reply_to": d_summary["reply_to"],
                }

    # Detailed per-brand sections
    for r in all_results:
        if r["error"]:
            continue
        brand = r["brand"]
        p()
        p(f"## {brand} — Detailed Campaigns")
        p()

        if r["pt_campaigns"]:
            p(f"### PT Campaigns ({len(r['pt_campaigns'])})")
            p()
            for c in r["pt_campaigns"]:
                p(f"- **{c['name']}**")
                p(f"  - From: `{c['from_raw']}`")
                if c["reply_to"]:
                    p(f"  - Reply-To: `{c['reply_to']}`")
                p(f"  - Last sent: {c['last_sent']}")
            p()

        if r["d_campaigns"]:
            p(f"### D Campaigns ({len(r['d_campaigns'])})")
            p()
            for c in r["d_campaigns"]:
                p(f"- **{c['name']}**")
                p(f"  - From: `{c['from_raw']}`")
                if c["reply_to"]:
                    p(f"  - Reply-To: `{c['reply_to']}`")
                p(f"  - Last sent: {c['last_sent']}")
            p()

    # Suggested YAML config
    p()
    p("## Suggested sender_info Config (for brand_config.yaml)")
    p()
    p("```yaml")
    p("# Add under each brand entry in the brands: section")
    for brand, info in brand_configs.items():
        p(f"  # {brand}")
        p(f"  sender_info:")
        for email_type, fields in info.items():
            p(f"    {email_type}:")
            p(f"      from_name: \"{fields['from_name']}\"")
            p(f"      from_email: \"{fields['from_email']}\"")
            p(f"      reply_to: \"{fields['reply_to']}\"")
    p("```")

    if write_file:
        report_path = _root / "reports" / "pt-sender-info-audit.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nReport written to: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Audit sender info for PT vs D promotional emails"
    )
    parser.add_argument(
        "--brand",
        type=str,
        help="Audit a single brand (e.g. HAV, CZ, ID, BUR, STF, TI)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write report to reports/pt-sender-info-audit.md",
    )
    parser.add_argument(
        "--max-pt",
        type=int,
        default=10,
        help="Max PT campaigns to fetch per brand (default: 10)",
    )
    parser.add_argument(
        "--max-d",
        type=int,
        default=5,
        help="Max D campaigns to fetch per brand (default: 5)",
    )
    args = parser.parse_args()

    brands = [args.brand.upper()] if args.brand else BRANDS

    all_results = []
    for brand in brands:
        result = fetch_sender_info_for_brand(
            brand, max_pt=args.max_pt, max_d=args.max_d
        )
        all_results.append(result)

    print_report(all_results, write_file=args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
