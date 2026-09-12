#!/usr/bin/env python3
"""
Audit canvas email steps for non-HTTPS links by fetching HTML from Braze API.

Fetches canvas details for all canvases, extracts the HTML body from each email
step, and scans for links that use http:// or bare www. (no protocol).

These break both Braze click tracking and GA4 attribution.

Usage:
    uv run python scripts/audit_canvas_https.py
    uv run python scripts/audit_canvas_https.py --brand ID
    uv run python scripts/audit_canvas_https.py --canvas-id <UUID>
"""

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

# Reuse Braze API helpers from import_braze
sys.path.insert(0, str(Path(__file__).parent))
from import_braze import (
    init_config,
    get_canvases,
    get_canvas_details,
    normalize_brand,
)

# Patterns for problematic links
HTTP_PATTERN = re.compile(r'href=["\']?(http://[^"\'>\s]+)', re.IGNORECASE)
BARE_WWW_PATTERN = re.compile(r'href=["\']?(www\.[^"\'>\s]+)', re.IGNORECASE)
# Bare domain (no protocol) — catches drag-and-drop editor links like "interiordefine.com?lid=..."
# Must look like a domain (word.word) and not be a valid protocol or special href
BARE_DOMAIN_PATTERN = re.compile(
    r'href=["\'](?!https?://)(?!mailto:)(?!tel:)(?!#)(?!{{)(?!{%)(?!www\.)'
    r'((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|co|shop|store)[^"\'>\s]*)',
    re.IGNORECASE,
)


def extract_domain(url):
    """Extract domain from a URL."""
    url = url.lower()
    for prefix in ["http://", "https://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].split("?")[0]


def scan_html_for_issues(html_content):
    """Scan HTML content for non-HTTPS links. Returns list of issues."""
    if not html_content:
        return []

    issues = []
    for match in HTTP_PATTERN.finditer(html_content):
        url = match.group(1)
        issues.append({"type": "http_not_https", "url": url})

    for match in BARE_WWW_PATTERN.finditer(html_content):
        url = match.group(1)
        issues.append({"type": "missing_protocol_www", "url": url})

    for match in BARE_DOMAIN_PATTERN.finditer(html_content):
        url = match.group(1)
        issues.append({"type": "missing_protocol_bare", "url": url})

    return issues


def get_brand_from_canvas(canvas_name, canvas_data, default_brand=None):
    """Infer brand from canvas name or metadata."""
    name_lower = canvas_name.lower()
    brand_patterns = {
        "ID": [r"\bid\b", r"interior.?define", r"interiordefine"],
        "CZ": [r"\bcz\b", r"citizenry"],
        "HAV": [r"\bhav\b", r"havenly", r"hip\b", r"room.profile", r"design.fee"],
        "BUR": [r"\bbur\b", r"\bbw\b", r"burrow"],
        "STF": [r"\bstf?\b", r"st.?frank"],
        "TI": [r"\bti\b", r"the.inside"],
    }
    for brand, patterns in brand_patterns.items():
        for pat in patterns:
            if re.search(pat, name_lower):
                return brand
    return default_brand or "UNKNOWN"


def audit_canvases(brand_filter=None, canvas_id_filter=None):
    """Fetch all canvases and audit their email HTML for non-HTTPS links."""

    # Determine which brands to check
    # Canvas APIs are per-workspace, so we need to iterate brand configs
    brands_to_check = []
    if brand_filter:
        brands_to_check = [normalize_brand(brand_filter)]
    else:
        # Check all brands that have Braze configs
        for brand in ["ID", "CZ", "HAV", "BUR", "STF", "TI"]:
            brands_to_check.append(brand)

    all_findings = []
    canvases_checked = 0
    steps_checked = 0

    for brand in brands_to_check:
        print(f"\n{'='*60}")
        print(f"Checking brand: {brand}")
        print(f"{'='*60}")

        try:
            init_config(brand)
        except Exception as e:
            print(f"  Skipping {brand}: {e}")
            continue

        # Get all canvases
        try:
            canvases = get_canvases()
        except Exception as e:
            print(f"  Error fetching canvases for {brand}: {e}")
            continue

        if not canvases:
            print(f"  No canvases found for {brand}")
            continue

        print(f"  Found {len(canvases)} canvases")

        for canvas in canvases:
            canvas_id = canvas["id"]
            canvas_name = canvas.get("name", "Unknown")

            # Filter by canvas ID if specified
            if canvas_id_filter and canvas_id != canvas_id_filter:
                continue

            canvases_checked += 1

            try:
                details = get_canvas_details(canvas_id)
                time.sleep(0.1)  # Rate limit
            except Exception as e:
                print(f"  Error fetching details for {canvas_name}: {e}")
                continue

            if not details:
                continue

            steps = details.get("steps", [])
            canvas_issues = []

            for step in steps:
                if step.get("type") != "message":
                    continue

                messages = step.get("messages", {})
                for msg_id, msg_data in messages.items():
                    if not isinstance(msg_data, dict):
                        continue
                    if msg_data.get("channel") != "email":
                        continue

                    steps_checked += 1
                    step_name = step.get("name", "")
                    html_body = msg_data.get("body", "")

                    issues = scan_html_for_issues(html_body)
                    if issues:
                        canvas_issues.append({
                            "step_name": step_name,
                            "step_id": step.get("id", ""),
                            "msg_id": msg_id,
                            "subject": msg_data.get("subject", ""),
                            "issues": issues,
                        })

            if canvas_issues:
                finding = {
                    "canvas_name": canvas_name,
                    "canvas_id": canvas_id,
                    "brand": brand,
                    "workspace_brand": brand,
                    "steps_with_issues": canvas_issues,
                    "total_issues": sum(len(s["issues"]) for s in canvas_issues),
                }
                all_findings.append(finding)
                print(f"  !! {canvas_name}: {finding['total_issues']} non-HTTPS links in {len(canvas_issues)} steps")
            else:
                # Only print clean canvases if we're doing a focused check
                if canvas_id_filter:
                    print(f"  OK {canvas_name}: no issues")

    return all_findings, canvases_checked, steps_checked


def generate_report(findings, canvases_checked, steps_checked):
    """Generate audit report."""
    lines = []
    lines.append("# Canvas Non-HTTPS Link Audit Report")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Canvases checked:** {canvases_checked}")
    lines.append(f"**Email steps checked:** {steps_checked}")
    lines.append(f"**Canvases with issues:** {len(findings)}")
    total_issues = sum(f["total_issues"] for f in findings)
    lines.append(f"**Total problematic links:** {total_issues}")
    lines.append("")

    if not findings:
        lines.append("No non-HTTPS links found in any canvas email steps.")
        return "\n".join(lines)

    # Summary by brand
    brand_summary = defaultdict(lambda: {"canvases": 0, "steps": 0, "links": 0})
    for f in findings:
        brand = f["workspace_brand"]
        brand_summary[brand]["canvases"] += 1
        brand_summary[brand]["steps"] += len(f["steps_with_issues"])
        brand_summary[brand]["links"] += f["total_issues"]

    lines.append("## Summary by Brand/Workspace")
    lines.append("")
    lines.append("| Workspace | Canvases | Steps | Links |")
    lines.append("|-----------|----------|-------|-------|")
    for brand in sorted(brand_summary.keys()):
        s = brand_summary[brand]
        lines.append(f"| {brand} | {s['canvases']} | {s['steps']} | {s['links']} |")
    lines.append("")

    # Affected domains
    domain_counts = defaultdict(int)
    for f in findings:
        for step in f["steps_with_issues"]:
            for issue in step["issues"]:
                domain_counts[extract_domain(issue["url"])] += 1

    lines.append("## Affected Domains")
    lines.append("")
    lines.append("| Domain | Occurrences |")
    lines.append("|--------|-------------|")
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{domain}` | {count} |")
    lines.append("")

    # Detailed findings
    lines.append("## Detailed Findings")
    lines.append("")
    lines.append("These are **active triggered flows** — every new user/event hits these emails.")
    lines.append("Fixing these has immediate and ongoing impact on tracking.")
    lines.append("")

    for f in sorted(findings, key=lambda x: (x["workspace_brand"], x["canvas_name"])):
        lines.append(f"### {f['canvas_name']}")
        lines.append(f"- **Workspace:** {f['workspace_brand']}")
        lines.append(f"- **Canvas ID:** `{f['canvas_id']}`")
        lines.append(f"- **Steps affected:** {len(f['steps_with_issues'])}")
        lines.append(f"- **Total bad links:** {f['total_issues']}")
        lines.append("")

        for step in f["steps_with_issues"]:
            lines.append(f"  **{step['step_name']}** (Subject: _{step['subject'][:60]}_)")
            for issue in step["issues"]:
                type_labels = {
                    "http_not_https": "`http://`",
                    "missing_protocol_www": "no protocol (`www.`)",
                    "missing_protocol_bare": "no protocol (bare domain)",
                }
                prefix = type_labels.get(issue["type"], issue["type"])
                url = issue["url"]
                if len(url) > 100:
                    url = url[:97] + "..."
                lines.append(f"  - [{prefix}] `{url}`")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit canvas emails for non-HTTPS links")
    parser.add_argument("--brand", help="Only check this brand (ID, CZ, HAV, BUR, STF, TI)")
    parser.add_argument("--canvas-id", help="Only check this specific canvas ID")
    args = parser.parse_args()

    print("Canvas Non-HTTPS Link Audit")
    print("=" * 40)

    findings, canvases_checked, steps_checked = audit_canvases(
        brand_filter=args.brand,
        canvas_id_filter=args.canvas_id,
    )

    report = generate_report(findings, canvases_checked, steps_checked)

    # Write report
    report_dir = Path(__file__).parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "canvas-non-https-audit.md"
    with open(report_path, "w") as f:
        f.write(report)

    print(f"\n{'='*60}")
    print(f"Report written to: {report_path}")
    print(f"\nSummary: {len(findings)} canvases with issues out of {canvases_checked} checked")
    print(f"         {sum(f['total_issues'] for f in findings)} total problematic links across {steps_checked} email steps")

    # Also print report
    print(f"\n{'='*60}")
    print(report)


if __name__ == "__main__":
    main()
