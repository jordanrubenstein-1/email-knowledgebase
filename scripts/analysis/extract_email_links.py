#!/usr/bin/env python3
"""
Extract and categorize all links used in emails across brands (last year).
BUR: only August 2025+, others: March 2025+
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

# Date cutoffs
BUR_CUTOFF = datetime(2025, 8, 1, tzinfo=timezone.utc)
DEFAULT_CUTOFF = datetime(2025, 3, 6, tzinfo=timezone.utc)

BRANDS = ["HAV", "CZ", "ID", "BUR", "STF", "TI"]


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
            # Skip Braze click-tracking wrappers — try to extract destination
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


def get_root_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Strip www. prefix
        if host.startswith("www."):
            host = host[4:]
        return host
    except:
        return url


def get_path_category(url: str) -> str:
    """Classify URL by path structure."""
    try:
        parsed = urlparse(url)
        path = parsed.path.lower().strip("/")
        domain = parsed.netloc.lower()

        # Social / unsubscribe first
        if any(d in domain for d in [
            "instagram.com", "facebook.com", "pinterest.com", "tiktok.com",
            "twitter.com", "x.com", "youtube.com", "linkedin.com"
        ]):
            return "social_media"
        if any(k in domain for k in ["unsubscribe", "optout"]):
            return "unsubscribe"
        if "klaviyo" in domain or "braze" in domain:
            return "email_service_link"

        if not path:
            return "homepage"

        segments = [s for s in path.split("/") if s]
        first = segments[0] if segments else ""

        if "unsubscribe" in path or "optout" in path or "opt-out" in path:
            return "unsubscribe"
        if "preferences" in path and ("email" in path or "notification" in path):
            return "email_preferences"

        if first in ("products", "product"):
            return "product_page"
        if first in ("collections", "collection", "shop", "category", "categories", "c"):
            return "collection_page"
        if first in ("cart", "checkout", "bag"):
            return "cart_checkout"
        if first in ("sale", "clearance", "deals", "outlet"):
            return "sale_page"
        if first in ("blogs", "blog", "journal", "editorial", "stories", "story",
                     "notes", "articles", "article", "press", "news"):
            return "editorial_blog"
        if first in ("pages", "page"):
            sub = segments[1] if len(segments) > 1 else ""
            if "about" in sub or "story" in sub:
                return "about_page"
            if any(k in sub for k in ["shipping", "returns", "faq", "help", "contact", "warranty", "care"]):
                return "support_page"
            if any(k in sub for k in ["design", "service", "how-it-works", "get-started", "consult"]):
                return "service_page"
            return "static_page"
        if first in ("about", "our-story", "mission", "who-we-are"):
            return "about_page"
        if first in ("shipping", "returns", "faq", "help", "support", "contact", "warranty", "care-guide"):
            return "support_page"
        if first in ("design-services", "design", "services", "how-it-works",
                     "how-we-work", "get-started", "interior-design-services",
                     "consult", "consultation"):
            return "service_page"
        if first in ("account", "accounts", "my-account", "login", "signin",
                     "sign-in", "register", "signup", "sign-up", "profile"):
            return "account_page"
        if first in ("rooms", "room", "inspiration", "lookbook", "style-guide", "idea",
                     "ideas", "mood-board", "gallery"):
            return "inspiration_page"
        if first in ("interior-design", "designers", "designer", "find-a-designer",
                     "professionals", "havenly"):
            return "designer_page"
        if first in ("trade", "trade-program", "business", "professionals"):
            return "trade_page"
        if first in ("gift-cards", "gift-card", "gifts", "gift"):
            return "gift_page"
        if first in ("showroom", "stores", "store-locator", "locations", "location"):
            return "showroom_page"
        if first in ("quiz", "quizzes", "style-quiz"):
            return "quiz_page"
        if first in ("refer", "referral", "referrals", "refer-a-friend"):
            return "referral_page"
        if "wishlist" in path or "wish-list" in path or "favorites" in path or "saved" in path:
            return "wishlist_page"
        if "review" in path or "reviews" in path:
            return "review_page"
        if first in ("new", "new-arrivals", "whats-new", "just-in"):
            return "new_arrivals"
        if first in ("custom", "customize", "customizer", "build", "configure"):
            return "customizer"
        if "survey" in path or "feedback" in path:
            return "survey"
        if "track" in path or "order-status" in path or "orders" in path:
            return "order_tracking"
        if first in ("affiliate", "ambassador", "partnership"):
            return "partnership"
        if first in ("sustainability", "impact", "values"):
            return "sustainability"
        if first in ("financing", "affirm", "sezzle", "klarna"):
            return "financing"
        if first in ("",):
            return "homepage"
        return "other"
    except:
        return "other"


def load_qualifying_campaigns():
    """Load campaign YAMLs that qualify by date/brand, return those with HTML files."""
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
            channel = data.get("channel", "").lower()
            if channel not in ("email", "multi", ""):
                continue

            # Derive HTML path from YAML slug
            slug = yaml_file.stem
            html_path = HTML_DIR / f"{slug}.html"

            # Get send date
            dates = data.get("dates", {}) or {}
            first_sent_str = dates.get("first_sent")
            if not first_sent_str:
                continue
            if isinstance(first_sent_str, str):
                first_sent = datetime.fromisoformat(first_sent_str)
                if first_sent.tzinfo is None:
                    first_sent = first_sent.replace(tzinfo=timezone.utc)
            else:
                continue

            cutoff = BUR_CUTOFF if brand == "BUR" else DEFAULT_CUTOFF
            if first_sent < cutoff:
                continue

            results.append({
                "brand": brand,
                "name": data.get("name", slug),
                "date": first_sent,
                "html_path": html_path,
                "yaml_path": yaml_file,
            })
        except Exception:
            pass
    return results


def main():
    print("Loading qualifying campaigns...")
    campaigns = load_qualifying_campaigns()
    print(f"Found {len(campaigns)} qualifying campaigns (email, post-cutoff)")

    brand_counts = defaultdict(int)
    for c in campaigns:
        brand_counts[c["brand"]] += 1
    for brand, count in sorted(brand_counts.items()):
        print(f"  {brand}: {count}")

    # brand -> domain -> {categories, example_urls, campaign_count, path_examples}
    brand_domain = defaultdict(lambda: defaultdict(lambda: {
        "categories": set(),
        "example_paths": set(),
        "campaign_count": 0,
    }))

    html_found = 0
    html_missing = 0

    for c in campaigns:
        brand = c["brand"]
        html_path = c["html_path"]

        if not html_path.exists():
            html_missing += 1
            continue
        html_found += 1

        links = extract_links_from_html(html_path)
        for url in links:
            domain = get_root_domain(url)
            cat = get_path_category(url)
            info = brand_domain[brand][domain]
            info["categories"].add(cat)
            info["campaign_count"] += 1
            # Store a cleaned path example (no query params)
            try:
                p = urlparse(url).path.strip("/")
                if p and len(info["example_paths"]) < 2:
                    info["example_paths"].add(p)
            except:
                pass

    print(f"\nHTML files found: {html_found}, missing: {html_missing}\n")

    # ─── Output ───
    print("=" * 80)
    print("EMAIL LINK AUDIT — ALL BRANDS (last year, BUR Aug 2025+)")
    print("=" * 80)

    # Cross-brand domain rollup
    all_domains = defaultdict(lambda: {"brands": set(), "categories": set(), "campaign_count": 0, "example_paths": set()})

    for brand in sorted(brand_domain.keys()):
        domains = brand_domain[brand]
        print(f"\n{'─'*70}")
        print(f"  {brand}  ({len(domains)} unique domains, {sum(v['campaign_count'] for v in domains.values())} link-occurrences)")
        print(f"{'─'*70}")

        sorted_domains = sorted(domains.items(), key=lambda x: x[1]["campaign_count"], reverse=True)
        for domain, info in sorted_domains:
            cats = sorted(info["categories"])
            examples = sorted(info["example_paths"])[:2]
            count = info["campaign_count"]
            print(f"  {domain:<50}  [{count:4d} hits]  {', '.join(cats)}")
            for ex in examples:
                print(f"    → /{ex[:80]}")

        # Aggregate
        for domain, info in domains.items():
            all_domains[domain]["brands"].add(brand)
            all_domains[domain]["categories"].update(info["categories"])
            all_domains[domain]["campaign_count"] += info["campaign_count"]
            all_domains[domain]["example_paths"].update(info["example_paths"])

    print("\n\n" + "=" * 80)
    print("CROSS-BRAND DOMAIN SUMMARY  (sorted by # brands using)")
    print("=" * 80)
    sorted_all = sorted(
        all_domains.items(),
        key=lambda x: (len(x[1]["brands"]), x[1]["campaign_count"]),
        reverse=True
    )
    for domain, info in sorted_all:
        brands_str = ", ".join(sorted(info["brands"]))
        cats_str = ", ".join(sorted(info["categories"]))
        print(f"\n{domain}")
        print(f"  brands:     {brands_str}")
        print(f"  categories: {cats_str}")
        examples = sorted(info["example_paths"])[:3]
        for ex in examples:
            print(f"  path ex:    /{ex[:90]}")


if __name__ == "__main__":
    main()
