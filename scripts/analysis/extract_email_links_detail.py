#!/usr/bin/env python3
"""
Detailed link extraction — show actual paths used per brand, deduplicated and categorized.
"""

import re
import yaml
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from urllib.parse import urlparse, unquote
from html.parser import HTMLParser

CAMPAIGNS_DIR = Path(__file__).parents[2] / "campaigns"
HTML_DIR = CAMPAIGNS_DIR / "html"

BUR_CUTOFF = datetime(2025, 8, 1, tzinfo=timezone.utc)
DEFAULT_CUTOFF = datetime(2025, 3, 6, tzinfo=timezone.utc)
BRANDS = ["HAV", "CZ", "ID", "BUR", "STF", "TI"]

# Primary domain for each brand (own-brand links only)
BRAND_DOMAIN = {
    "HAV": "havenly.com",
    "CZ": "the-citizenry.com",
    "ID": "interiordefine.com",
    "BUR": "burrow.com",
    "STF": "stfrank.com",
    "TI": "theinside.com",
}

# Sister-brand domains
SISTER_DOMAINS = {
    "havenly.com", "the-citizenry.com", "interiordefine.com",
    "burrow.com", "stfrank.com", "theinside.com"
}


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, val in attrs:
                if attr == "href" and val:
                    self.links.append(val)


def extract_links_from_html(html_path: Path) -> list[str]:
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        parser = LinkExtractor()
        parser.feed(content)
        links = []
        for link in parser.links:
            link = link.strip()
            if not link or link.startswith("mailto:") or link.startswith("#"):
                continue
            if any(d in link for d in ["click.e.burrow.com", "click.mail.", "trk.klclick", "links.e.", "click.e."]):
                m = re.search(r'[?&](?:u|url|redirect|r)=([^&]+)', link)
                if m:
                    link = unquote(m.group(1))
                else:
                    continue
            if link.startswith("http"):
                links.append(link)
        return list(set(links))
    except Exception:
        return []


def clean_path(url: str) -> str:
    """Return path without query string, lowercase."""
    try:
        p = urlparse(url)
        path = p.path.lower().strip("/")
        return path or "/"
    except:
        return "/"


def get_root_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except:
        return url


def load_qualifying():
    results = []
    for yaml_file in sorted(CAMPAIGNS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            if not data:
                continue
            brand = data.get("brand", "").upper()
            if brand not in BRANDS:
                continue
            if data.get("channel", "").lower() not in ("email", "multi", ""):
                continue
            slug = yaml_file.stem
            html_path = HTML_DIR / f"{slug}.html"
            dates = data.get("dates", {}) or {}
            first_sent_str = dates.get("first_sent")
            if not first_sent_str:
                continue
            first_sent = datetime.fromisoformat(str(first_sent_str))
            if first_sent.tzinfo is None:
                first_sent = first_sent.replace(tzinfo=timezone.utc)
            cutoff = BUR_CUTOFF if brand == "BUR" else DEFAULT_CUTOFF
            if first_sent < cutoff:
                continue
            results.append({"brand": brand, "html_path": html_path, "date": first_sent})
        except Exception:
            pass
    return results


def main():
    campaigns = load_qualifying()
    print(f"Loaded {len(campaigns)} qualifying campaigns\n")

    # brand -> {own_domain: {path: count}, sister_domain: {domain: {path: count}}, third_party: {domain: [paths]}}
    brand_own = defaultdict(lambda: defaultdict(int))     # brand -> path -> count
    brand_sister = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # brand -> domain -> path -> count
    brand_third = defaultdict(lambda: defaultdict(set))   # brand -> domain -> set of paths

    for c in campaigns:
        brand = c["brand"]
        own_domain = BRAND_DOMAIN.get(brand, "")
        html_path = c["html_path"]
        if not html_path.exists():
            continue
        links = extract_links_from_html(html_path)
        for url in links:
            domain = get_root_domain(url)
            path = clean_path(url)
            if domain == own_domain:
                brand_own[brand][path] += 1
            elif domain in SISTER_DOMAINS:
                brand_sister[brand][domain][path] += 1
            else:
                brand_third[brand][domain].add(path)

    # ─── Print detailed own-domain paths per brand ───
    for brand in sorted(brand_own.keys()):
        own_domain = BRAND_DOMAIN.get(brand, "?")
        print(f"\n{'='*70}")
        print(f"  {brand} — own domain: {own_domain}")
        print(f"{'='*70}")

        # Sort by frequency
        paths_sorted = sorted(brand_own[brand].items(), key=lambda x: x[1], reverse=True)
        for path, count in paths_sorted:
            print(f"  [{count:3d}x]  /{path}")

        # Sister brand links
        if brand_sister[brand]:
            print(f"\n  ── Sister-brand links ──")
            for domain in sorted(brand_sister[brand].keys()):
                paths = sorted(brand_sister[brand][domain].items(), key=lambda x: x[1], reverse=True)
                total = sum(v for _, v in paths)
                print(f"  {domain}  ({total} hits)")
                for path, count in paths[:5]:
                    print(f"    [{count:3d}x]  /{path}")

        # Third-party links
        if brand_third[brand]:
            print(f"\n  ── Third-party links ──")
            for domain in sorted(brand_third[brand].keys()):
                paths = sorted(brand_third[brand][domain])
                print(f"  {domain}")
                for p in paths[:3]:
                    print(f"    /{p}")


if __name__ == "__main__":
    main()
