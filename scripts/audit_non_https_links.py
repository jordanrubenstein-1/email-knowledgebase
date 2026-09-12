#!/usr/bin/env python3
"""Audit email HTML files for non-HTTPS links that break Braze/GA4 tracking.

Scans all campaign HTML files for:
  1. href="http://..." links (should be https://)
  2. href="www...." links (missing protocol entirely)

Cross-references with campaign YAML metadata to identify brand, canvas, etc.
"""

import glob
import os
import re
import yaml
from collections import defaultdict

CAMPAIGNS_DIR = os.path.join(os.path.dirname(__file__), "..", "campaigns")
HTML_DIR = os.path.join(CAMPAIGNS_DIR, "html")

# Patterns to find problematic links
HTTP_PATTERN = re.compile(r'href="(http://[^"]+)"', re.IGNORECASE)
BARE_WWW_PATTERN = re.compile(r'href="(www\.[^"]+)"', re.IGNORECASE)
# Also catch single-quoted variants
HTTP_PATTERN_SQ = re.compile(r"href='(http://[^']+)'", re.IGNORECASE)
BARE_WWW_PATTERN_SQ = re.compile(r"href='(www\.[^']+)'", re.IGNORECASE)
# Bare domain (no protocol at all) — catches drag-and-drop editor links like "interiordefine.com?lid=..."
BARE_DOMAIN_PATTERN = re.compile(
    r'href="(?!https?://)(?!mailto:)(?!tel:)(?!#)(?!{{)(?!{%)(?!www\.)'
    r'((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|co|shop|store)[^"]*)"',
    re.IGNORECASE,
)
BARE_DOMAIN_PATTERN_SQ = re.compile(
    r"href='(?!https?://)(?!mailto:)(?!tel:)(?!#)(?!{{)(?!{%)(?!www\.)"
    r"((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|co|shop|store)[^']*)'",
    re.IGNORECASE,
)


def load_campaign_metadata():
    """Load all campaign YAML files and build html_file -> metadata lookup.

    Matches by campaign name slug since sends don't have html_file references.
    """
    html_to_campaign = {}
    yaml_files = glob.glob(os.path.join(CAMPAIGNS_DIR, "*.yaml"))
    for yf in yaml_files:
        try:
            with open(yf) as f:
                data = yaml.safe_load(f)
            if not data or not data.get("name"):
                continue

            meta = {
                "yaml_file": os.path.basename(yf),
                "name": data.get("name", ""),
                "brand": data.get("brand", "UNKNOWN"),
                "braze_type": data.get("braze_type", "campaign"),
                "canvas_name": data.get("canvas_name", ""),
                "canvas_id": data.get("canvas_id", ""),
                "flow_type": data.get("flow_type", ""),
                "channel": data.get("channel", ""),
                "first_sent": str(data.get("dates", {}).get("first_sent", "")),
                "campaign_type": data.get("campaign_type", ""),
            }

            # Map by YAML filename (without extension) -> metadata
            yaml_basename = os.path.basename(yf).replace(".yaml", "")
            html_to_campaign[yaml_basename] = meta

            # Also map by lowercased campaign name as slug
            name_slug = data["name"].lower().replace(" ", "_")
            html_to_campaign[name_slug] = meta

            # Map by html_file if present in sends
            for send in data.get("sends", []):
                html_file = send.get("html_file")
                if html_file:
                    html_basename = os.path.basename(html_file)
                    html_to_campaign[html_basename] = meta
        except Exception:
            continue
    return html_to_campaign


def extract_domain(url):
    """Extract domain from a URL for grouping."""
    url = url.lower()
    for prefix in ["http://", "https://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].split("?")[0]


def audit_html_files():
    """Scan all HTML files for non-HTTPS links."""
    html_files = glob.glob(os.path.join(HTML_DIR, "*.html"))
    findings = []

    for hf in sorted(html_files):
        basename = os.path.basename(hf)
        with open(hf, encoding="utf-8", errors="replace") as f:
            content = f.read()

        issues = []
        # Check http:// links
        for pattern in [HTTP_PATTERN, HTTP_PATTERN_SQ]:
            for match in pattern.finditer(content):
                url = match.group(1)
                issues.append({"type": "http_not_https", "url": url})

        # Check bare www links
        for pattern in [BARE_WWW_PATTERN, BARE_WWW_PATTERN_SQ]:
            for match in pattern.finditer(content):
                url = match.group(1)
                issues.append({"type": "missing_protocol", "url": url})

        # Check bare domain links (no protocol at all)
        for pattern in [BARE_DOMAIN_PATTERN, BARE_DOMAIN_PATTERN_SQ]:
            for match in pattern.finditer(content):
                url = match.group(1)
                issues.append({"type": "missing_protocol_bare", "url": url})

        if issues:
            findings.append({"file": basename, "issues": issues})

    return findings


def resolve_metadata(html_filename, html_to_campaign):
    """Resolve metadata for an HTML file by trying multiple matching strategies."""
    basename = html_filename.replace(".html", "")

    # Direct match by filename
    if basename in html_to_campaign:
        return html_to_campaign[basename]

    # Match by lowercase slug
    slug = basename.lower()
    if slug in html_to_campaign:
        return html_to_campaign[slug]

    # Fuzzy: try prefix matching (some filenames are truncated)
    for key, meta in html_to_campaign.items():
        if len(key) > 20 and (slug.startswith(key[:30]) or key.startswith(slug[:30])):
            return meta

    return {}


def generate_report(findings, html_to_campaign):
    """Generate a readable audit report."""
    lines = []
    lines.append("# Non-HTTPS Link Audit Report")
    lines.append("")
    lines.append(f"**Files scanned:** {len(glob.glob(os.path.join(HTML_DIR, '*.html')))}")
    lines.append(f"**Files with issues:** {len(findings)}")
    total_issues = sum(len(f["issues"]) for f in findings)
    lines.append(f"**Total problematic links:** {total_issues}")
    lines.append("")

    # ── Summary by issue type ──
    http_count = sum(1 for f in findings for i in f["issues"] if i["type"] == "http_not_https")
    bare_www_count = sum(1 for f in findings for i in f["issues"] if i["type"] == "missing_protocol")
    bare_domain_count = sum(1 for f in findings for i in f["issues"] if i["type"] == "missing_protocol_bare")
    lines.append("## Issue Types")
    lines.append(f"- **`http://` instead of `https://`:** {http_count} links")
    lines.append(f"- **Missing protocol (`www.` only):** {bare_www_count} links")
    lines.append(f"- **Missing protocol (bare domain):** {bare_domain_count} links")
    lines.append("")

    # ── Summary by brand ──
    brand_issues = defaultdict(lambda: {"files": set(), "links": 0, "canvas_files": set()})
    for f in findings:
        meta = resolve_metadata(f["file"], html_to_campaign)
        brand = meta.get("brand", "UNKNOWN")
        braze_type = meta.get("braze_type", "unknown")
        brand_issues[brand]["files"].add(f["file"])
        brand_issues[brand]["links"] += len(f["issues"])
        if braze_type == "canvas_step":
            brand_issues[brand]["canvas_files"].add(f["file"])

    lines.append("## Summary by Brand")
    lines.append("")
    lines.append("| Brand | Files | Links | Canvas Files |")
    lines.append("|-------|-------|-------|-------------|")
    for brand in sorted(brand_issues.keys()):
        info = brand_issues[brand]
        lines.append(
            f"| {brand} | {len(info['files'])} | {info['links']} | {len(info['canvas_files'])} |"
        )
    lines.append("")

    # ── Summary by domain ──
    domain_issues = defaultdict(int)
    for f in findings:
        for issue in f["issues"]:
            domain = extract_domain(issue["url"])
            domain_issues[domain] += 1

    lines.append("## Affected Domains")
    lines.append("")
    lines.append("| Domain | Occurrences |")
    lines.append("|--------|-------------|")
    for domain, count in sorted(domain_issues.items(), key=lambda x: -x[1]):
        lines.append(f"| `{domain}` | {count} |")
    lines.append("")

    # ── Canvas-specific section ──
    lines.append("## Canvas Step Details (Lifecycle/Triggered Emails)")
    lines.append("")
    lines.append("These are **active triggered flows** — fixing these has ongoing impact.")
    lines.append("")

    canvas_findings = []
    for f in findings:
        meta = resolve_metadata(f["file"], html_to_campaign)
        if meta.get("braze_type") == "canvas_step":
            canvas_findings.append((f, meta))

    if canvas_findings:
        # Group by canvas
        canvas_groups = defaultdict(list)
        for f, meta in canvas_findings:
            key = meta.get("canvas_name", "Unknown Canvas")
            canvas_groups[key].append((f, meta))

        for canvas_name in sorted(canvas_groups.keys()):
            items = canvas_groups[canvas_name]
            meta0 = items[0][1]
            lines.append(f"### {canvas_name}")
            lines.append(f"- **Brand:** {meta0.get('brand', '?')}")
            lines.append(f"- **Flow type:** {meta0.get('flow_type', '?')}")
            lines.append(f"- **Steps affected:** {len(items)}")
            lines.append("")
            for f, meta in items:
                lines.append(f"  **{meta.get('name', f['file'])}**")
                for issue in f["issues"]:
                    prefix = "http://" if issue["type"] == "http_not_https" else "missing protocol"
                    # Truncate long URLs
                    url = issue["url"]
                    if len(url) > 100:
                        url = url[:97] + "..."
                    lines.append(f"  - [{prefix}] `{url}`")
                lines.append("")
    else:
        lines.append("No canvas steps found with non-HTTPS links.")
        lines.append("")

    # ── Batch campaign section ──
    lines.append("## Batch Campaign Details (One-Time Sends)")
    lines.append("")
    lines.append("These are historical sends. Fix the templates to prevent recurrence.")
    lines.append("")

    batch_findings = []
    for f in findings:
        meta = resolve_metadata(f["file"], html_to_campaign)
        if meta.get("braze_type") != "canvas_step":
            batch_findings.append((f, meta))

    # Group by brand
    brand_groups = defaultdict(list)
    for f, meta in batch_findings:
        brand = meta.get("brand", "UNKNOWN")
        brand_groups[brand].append((f, meta))

    for brand in sorted(brand_groups.keys()):
        items = brand_groups[brand]
        lines.append(f"### {brand}")
        lines.append("")
        for f, meta in sorted(items, key=lambda x: x[1].get("first_sent", ""), reverse=True):
            campaign_name = meta.get("name", f["file"])
            date = meta.get("first_sent", "?")[:10]
            issue_types = set(i["type"] for i in f["issues"])
            type_labels = {
                "http_not_https": "http://",
                "missing_protocol": "no protocol (www.)",
                "missing_protocol_bare": "no protocol (bare domain)",
            }
            type_str = ", ".join(type_labels.get(t, t) for t in issue_types)
            link_count = len(f["issues"])
            lines.append(f"- **{campaign_name}** ({date}) — {link_count} link(s) [{type_str}]")
            for issue in f["issues"]:
                url = issue["url"]
                if len(url) > 120:
                    url = url[:117] + "..."
                lines.append(f"  - `{url}`")
        lines.append("")

    return "\n".join(lines)


def main():
    print("Loading campaign metadata...")
    html_to_campaign = load_campaign_metadata()
    print(f"  Loaded metadata for {len(html_to_campaign)} HTML files")

    print("Scanning HTML files for non-HTTPS links...")
    findings = audit_html_files()
    print(f"  Found {len(findings)} files with issues")

    report = generate_report(findings, html_to_campaign)

    # Write report
    report_path = os.path.join(os.path.dirname(__file__), "..", "reports", "non-https-link-audit.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nReport written to: {report_path}")

    # Also print to stdout
    print("\n" + "=" * 80)
    print(report)


if __name__ == "__main__":
    main()
