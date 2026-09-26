#!/usr/bin/env python3
"""
Audit Braze content blocks for non-HTTPS links.

Fetches all content blocks across all workspaces, scans their HTML content
for http://, bare www., and bare domain links.

Usage:
    uv run python scripts/audit_content_blocks_https.py
    uv run python scripts/audit_content_blocks_https.py --brand ID
"""

import argparse
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from import_braze import init_config, braze_request, normalize_brand

# Patterns for problematic links
HTTP_PATTERN = re.compile(r'href=["\']?(http://[^"\'>\s]+)', re.IGNORECASE)
BARE_WWW_PATTERN = re.compile(r'href=["\']?(www\.[^"\'>\s]+)', re.IGNORECASE)
BARE_DOMAIN_PATTERN = re.compile(
    r'href=["\'](?!https?://)(?!mailto:)(?!tel:)(?!#)(?!{{)(?!{%)(?!www\.)'
    r'((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|co|shop|store)[^"\'>\s]*)',
    re.IGNORECASE,
)


def extract_domain(url):
    url = url.lower()
    for prefix in ["http://", "https://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].split("?")[0]


def scan_for_issues(content):
    if not content:
        return []
    issues = []
    for match in HTTP_PATTERN.finditer(content):
        issues.append({"type": "http_not_https", "url": match.group(1)})
    for match in BARE_WWW_PATTERN.finditer(content):
        issues.append({"type": "missing_protocol_www", "url": match.group(1)})
    for match in BARE_DOMAIN_PATTERN.finditer(content):
        issues.append({"type": "missing_protocol_bare", "url": match.group(1)})
    return issues


def list_content_blocks(limit=1000):
    """List all content blocks in the current workspace."""
    all_blocks = []
    offset = 0
    page = 0
    while True:
        params = {"limit": min(limit, 1000)}
        # Braze requires offset > 0, so only include it after first page
        if offset > 0:
            params["offset"] = offset
        data = braze_request("content_blocks/list", params)
        if not data or "content_blocks" not in data:
            break
        blocks = data["content_blocks"]
        if not blocks:
            break
        all_blocks.extend(blocks)
        page += 1
        if len(blocks) < min(limit, 1000):
            break
        offset += len(blocks)
        time.sleep(0.1)
    return all_blocks


def get_content_block_info(block_id, include_inclusion=True):
    """Get content block details including HTML content."""
    params = {
        "content_block_id": block_id,
        "include_inclusion_data": "true" if include_inclusion else "false",
    }
    return braze_request("content_blocks/info", params)


def audit_content_blocks(brand_filter=None):
    brands_to_check = [normalize_brand(brand_filter)] if brand_filter else ["ID", "CZ", "HAV", "BUR", "STF", "TI"]

    all_findings = []
    total_blocks = 0
    total_active = 0

    for brand in brands_to_check:
        print(f"\n{'='*60}")
        print(f"Checking brand: {brand}")
        print(f"{'='*60}")

        try:
            init_config(brand)
        except Exception as e:
            print(f"  Skipping {brand}: {e}")
            continue

        blocks = list_content_blocks()
        if not blocks:
            print(f"  No content blocks found")
            continue

        print(f"  Found {len(blocks)} content blocks")
        total_blocks += len(blocks)

        for i, block in enumerate(blocks):
            block_id = block["content_block_id"]
            block_name = block.get("name", "Unknown")
            content_type = block.get("content_type", "")
            inclusion_count = block.get("inclusion_count", 0)
            liquid_tag = block.get("liquid_tag", "")

            # Fetch full content
            try:
                info = get_content_block_info(block_id)
                time.sleep(0.05)  # Light rate limiting
            except Exception as e:
                print(f"  Error fetching {block_name}: {e}")
                continue

            if not info:
                continue

            content = info.get("content", "")
            inclusion_count = info.get("inclusion_count", 0)
            inclusion_data = info.get("inclusion_data", [])

            if inclusion_count > 0:
                total_active += 1

            issues = scan_for_issues(content)
            if issues:
                # Categorize inclusions
                campaign_ids = []
                canvas_ids = []
                for inc in (inclusion_data or []):
                    if isinstance(inc, dict):
                        if inc.get("type") == "canvas":
                            canvas_ids.append(inc)
                        else:
                            campaign_ids.append(inc)

                finding = {
                    "block_id": block_id,
                    "block_name": block_name,
                    "liquid_tag": liquid_tag,
                    "content_type": content_type,
                    "workspace": brand,
                    "inclusion_count": inclusion_count,
                    "inclusion_data": inclusion_data,
                    "campaign_count": len(campaign_ids),
                    "canvas_count": len(canvas_ids),
                    "issues": issues,
                    "last_edited": info.get("last_edited", ""),
                    "tags": info.get("tags", []),
                }
                all_findings.append(finding)

                status = "ACTIVE" if inclusion_count > 0 else "unused"
                print(f"  !! [{status}] {block_name}: {len(issues)} bad links, used in {inclusion_count} places")
            
            if (i + 1) % 25 == 0:
                print(f"  ... checked {i+1}/{len(blocks)} blocks")

    return all_findings, total_blocks, total_active


def generate_report(findings, total_blocks, total_active):
    lines = []
    lines.append("# Content Block Non-HTTPS Link Audit Report")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Content blocks checked:** {total_blocks}")
    lines.append(f"**Active blocks (inclusion_count > 0):** {total_active}")
    lines.append(f"**Blocks with issues:** {len(findings)}")

    active_findings = [f for f in findings if f["inclusion_count"] > 0]
    unused_findings = [f for f in findings if f["inclusion_count"] == 0]
    lines.append(f"**Active blocks with issues:** {len(active_findings)}")
    lines.append(f"**Unused blocks with issues:** {len(unused_findings)}")

    total_issues = sum(len(f["issues"]) for f in findings)
    lines.append(f"**Total problematic links:** {total_issues}")
    lines.append("")

    if not findings:
        lines.append("No non-HTTPS links found in any content blocks.")
        return "\n".join(lines)

    # Summary by workspace
    ws_summary = defaultdict(lambda: {"blocks": 0, "active": 0, "links": 0})
    for f in findings:
        ws = f["workspace"]
        ws_summary[ws]["blocks"] += 1
        ws_summary[ws]["links"] += len(f["issues"])
        if f["inclusion_count"] > 0:
            ws_summary[ws]["active"] += 1

    lines.append("## Summary by Workspace")
    lines.append("")
    lines.append("| Workspace | Blocks w/ Issues | Active | Bad Links |")
    lines.append("|-----------|-----------------|--------|-----------|")
    for ws in sorted(ws_summary.keys()):
        s = ws_summary[ws]
        lines.append(f"| {ws} | {s['blocks']} | {s['active']} | {s['links']} |")
    lines.append("")

    # Affected domains
    domain_counts = defaultdict(int)
    for f in findings:
        for issue in f["issues"]:
            domain_counts[extract_domain(issue["url"])] += 1

    lines.append("## Affected Domains")
    lines.append("")
    lines.append("| Domain | Occurrences |")
    lines.append("|--------|-------------|")
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{domain}` | {count} |")
    lines.append("")

    # Active blocks (priority)
    if active_findings:
        lines.append("## PRIORITY: Active Content Blocks with Issues")
        lines.append("")
        lines.append("These blocks are referenced by live campaigns/canvases. Fixing them")
        lines.append("will fix all emails that include them.")
        lines.append("")

        for f in sorted(active_findings, key=lambda x: -x["inclusion_count"]):
            lines.append(f"### {f['block_name']}")
            lines.append(f"- **Workspace:** {f['workspace']}")
            lines.append(f"- **Liquid tag:** `{f['liquid_tag']}`")
            lines.append(f"- **Used in:** {f['inclusion_count']} campaigns/canvases")
            lines.append(f"- **Last edited:** {f['last_edited'][:10] if f['last_edited'] else '?'}")
            if f["tags"]:
                lines.append(f"- **Tags:** {', '.join(f['tags'])}")
            lines.append(f"- **Bad links:** {len(f['issues'])}")
            lines.append("")

            type_labels = {
                "http_not_https": "`http://`",
                "missing_protocol_www": "no protocol (`www.`)",
                "missing_protocol_bare": "no protocol (bare domain)",
            }
            for issue in f["issues"]:
                prefix = type_labels.get(issue["type"], issue["type"])
                url = issue["url"]
                if len(url) > 100:
                    url = url[:97] + "..."
                lines.append(f"  - [{prefix}] `{url}`")
            lines.append("")

    # Unused blocks
    if unused_findings:
        lines.append("## Unused Content Blocks with Issues (Lower Priority)")
        lines.append("")
        lines.append("These blocks have `inclusion_count: 0` — not actively referenced.")
        lines.append("Consider deleting or archiving if no longer needed.")
        lines.append("")

        for f in sorted(unused_findings, key=lambda x: x["block_name"]):
            lines.append(f"- **{f['block_name']}** ({f['workspace']}) — {len(f['issues'])} bad links")
            lines.append(f"  Liquid tag: `{f['liquid_tag']}`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit Braze content blocks for non-HTTPS links")
    parser.add_argument("--brand", help="Only check this brand")
    args = parser.parse_args()

    print("Content Block Non-HTTPS Link Audit")
    print("=" * 40)

    findings, total_blocks, total_active = audit_content_blocks(brand_filter=args.brand)

    report = generate_report(findings, total_blocks, total_active)

    report_dir = Path(__file__).parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "content-block-non-https-audit.md"
    with open(report_path, "w") as f:
        f.write(report)

    print(f"\n{'='*60}")
    print(f"Report written to: {report_path}")
    active_findings = [f for f in findings if f["inclusion_count"] > 0]
    print(f"\nSummary: {len(findings)} blocks with issues ({len(active_findings)} active)")
    print(f"         {sum(len(f['issues']) for f in findings)} total problematic links")

    print(f"\n{'='*60}")
    print(report)


if __name__ == "__main__":
    main()
