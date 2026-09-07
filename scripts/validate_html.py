#!/usr/bin/env python3
"""
HTML-level validation for email and SMS campaigns.

Checks image alt tags, unsubscribe link presence, link health,
UTM parameter enforcement, brand domain validation, Liquid syntax,
and HTML metadata.

Usage (standalone):
    from scripts.validate_html import validate_html

    errors, warnings = validate_html(
        html_content=html_string,
        brand="HAV",
        channel="email",
        subscription_group="Marketing",
        check_links=False,
    )

Network-dependent checks (link resolution, image size) are off by default
and enabled via ``check_links=True``.
"""

import asyncio
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Path setup — allow importing from sibling modules
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from validate_campaign_config import BRAND_DOMAINS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Domains that are always allowed in links (not subject to brand-domain check)
ALLOWED_EXTERNAL_DOMAINS = {
    # CDN / infrastructure
    "braze-images.com",
    "fonts.googleapis.com",
    "fonts.google.com",
    "cdn.shopify.com",
    # Deep link providers
    "app.link",  # Branch.io deep links (e.g. havenly.app.link)
    # Google services (surveys, forms, docs)
    "docs.google.com",
    "forms.gle",
    # Social media
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "www.pinterest.com",
    "tiktok.com",
    "www.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "linkedin.com",
    "www.linkedin.com",
}

# Sister brand domains — all brands are under the same parent company,
# so cross-linking between them is expected and allowed.
SISTER_BRAND_DOMAINS = {
    "havenly.com",
    "the-citizenry.com",
    "thecitizenry.com",
    "interiordefine.com",
    "burrow.com",
    "stfrank.com",
    "theinside.com",
}

# Known unsubscribe patterns in Braze emails
UNSUBSCRIBE_PATTERNS = [
    r"\{\{\s*\$\{set_user_to_unsubscribed_url\}\s*\}\}",
    r"\{\{content_blocks\.\$\{[^}]*unsub",
    r"\{\{content_blocks\.\$\{unsubscribe",
    r"set_user_to_unsubscribed_url",
    # Footer content blocks that typically contain the unsubscribe link
    r"\{\{content_blocks\.\$\{[^}]*footer[^}]*\}",
]

# Expected UTM sources per brand (from brand_config.yaml).
# Value is a tuple of accepted utm_source strings — index 0 is the current
# canonical value (used in warning messages); any other entries are legacy
# values still accepted without a warning during a migration window.
#
# BUR is mid-migration from "burrow" to "braze_BW" (to match the
# braze_<CODE> convention used by every other brand) — accept both until
# the old value stops appearing in new sends (tracked: several weeks from
# 2026-08-31).
BRAND_UTM_SOURCES: Dict[str, Tuple[str, ...]] = {
    "HAV": ("braze_HAV",),
    "CZ": ("braze_CZ",),
    "ID": ("braze_ID",),
    "BUR": ("braze_BW", "burrow"),
    "STF": ("braze_SF",),
    "TI": ("braze_TI",),
}

# Maximum image file size before warning (bytes)
MAX_IMAGE_SIZE_BYTES = 1_000_000  # 1 MB
MAX_TOTAL_IMAGE_SIZE_BYTES = 3_000_000  # 3 MB


# =========================================================================
# HTML PARSER — extract images, links, text, and metadata
# =========================================================================

class EmailHTMLParser(HTMLParser):
    """Parse email HTML and extract elements relevant to QA."""

    def __init__(self) -> None:
        super().__init__()
        self.images: List[Dict[str, Any]] = []  # {src, alt, line}
        self.links: List[Dict[str, Any]] = []  # {href, text, line}
        self.title: Optional[str] = None
        self._in_title = False
        self._current_link_text = ""
        self._in_link = False
        self._current_link_href = ""
        self._current_line = 1

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_dict = dict(attrs)
        line = self.getpos()[0]

        if tag == "img":
            self.images.append({
                "src": attr_dict.get("src", ""),
                "alt": attr_dict.get("alt"),  # None means missing, "" means empty
                "line": line,
            })

        if tag == "a":
            href = attr_dict.get("href", "")
            self._in_link = True
            self._current_link_href = href
            self._current_link_text = ""

        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self.links.append({
                "href": self._current_link_href,
                "text": self._current_link_text.strip(),
                "line": self.getpos()[0],
            })
            self._in_link = False

        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()
        if self._in_link:
            self._current_link_text += data


def _parse_html(html: str) -> EmailHTMLParser:
    """Parse HTML content and return structured data."""
    parser = EmailHTMLParser()
    parser.feed(html)
    return parser


# =========================================================================
# INDIVIDUAL VALIDATION CHECKS
# =========================================================================

def validate_image_alt_tags(parsed: EmailHTMLParser) -> Tuple[List[str], List[str]]:
    """Check that every <img> has a non-empty alt attribute.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    for img in parsed.images:
        src = img["src"]
        # Truncate long URLs for readability
        src_display = src[:80] + "..." if len(src) > 80 else src

        if img["alt"] is None:
            errors.append(
                f"Image missing alt attribute (line ~{img['line']}): {src_display}"
            )
        elif img["alt"].strip() == "":
            errors.append(
                f"Image has empty alt attribute (line ~{img['line']}): {src_display}"
            )

    return errors, warnings


def validate_unsubscribe_link(
    html: str,
    subscription_group: str = "Marketing",
) -> Tuple[List[str], List[str]]:
    """Check for unsubscribe link in marketing emails.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    if subscription_group != "Marketing":
        return errors, warnings

    for pattern in UNSUBSCRIBE_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            return errors, warnings

    # Also check for a plain-text "unsubscribe" link
    if re.search(r'<a[^>]+>.*?unsubscribe.*?</a>', html, re.IGNORECASE | re.DOTALL):
        return errors, warnings

    errors.append(
        "No unsubscribe link detected in marketing email. "
        "CAN-SPAM requires an unsubscribe mechanism for commercial emails. "
        "Expected: {{${set_user_to_unsubscribed_url}}} or "
        "{{content_blocks.${unsubscribe}...}}"
    )
    return errors, warnings


def validate_brand_domains(
    parsed: EmailHTMLParser,
    brand: str,
) -> Tuple[List[str], List[str]]:
    """Check that all links point to the brand's domain or known-safe domains.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    brand_upper = brand.upper()
    allowed_domains = BRAND_DOMAINS.get(brand_upper, [])
    if not allowed_domains:
        warnings.append(f"Unknown brand '{brand}' — skipping domain validation.")
        return errors, warnings

    for link in parsed.links:
        href = link["href"]

        # Skip Liquid template URLs, mailto, tel, and anchors
        if not href or href.startswith(("{{", "{%", "mailto:", "tel:", "#")):
            continue

        try:
            parsed_url = urlparse(href)
            domain = parsed_url.netloc.lower()
            if not domain:
                continue

            # Strip www.
            bare_domain = domain[4:] if domain.startswith("www.") else domain

            # Check against brand domains
            brand_match = any(
                bare_domain == d.lower() or bare_domain.endswith("." + d.lower())
                for d in allowed_domains
            )

            # Check against allowed external domains
            external_match = any(
                bare_domain == d or bare_domain.endswith("." + d)
                for d in ALLOWED_EXTERNAL_DOMAINS
            )

            # Check against sister brand domains (same parent company)
            sister_match = any(
                bare_domain == d or bare_domain.endswith("." + d)
                for d in SISTER_BRAND_DOMAINS
            )

            if not brand_match and not external_match and not sister_match:
                warnings.append(
                    f"Link to off-brand domain '{domain}' "
                    f"(expected {', '.join(allowed_domains)}): {href[:100]}"
                )
        except Exception:
            continue

    return errors, warnings


def validate_utm_parameters(
    parsed: EmailHTMLParser,
    brand: str,
    channel: str = "email",
) -> Tuple[List[str], List[str]]:
    """Check that links include proper UTM parameters.

    Note: Braze Link Management often adds UTMs after campaign creation,
    so missing UTMs are warnings, not errors.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    brand_upper = brand.upper()
    accepted_sources = BRAND_UTM_SOURCES.get(brand_upper, ())
    expected_source = accepted_sources[0] if accepted_sources else None
    expected_medium = "sms" if channel == "sms" else "email"

    # Collect links that should have UTMs (skip Liquid, mailto, tel, anchors, images)
    brand_domains = BRAND_DOMAINS.get(brand_upper, [])
    checkable_links = []

    for link in parsed.links:
        href = link["href"]
        if not href or href.startswith(("{{", "{%", "mailto:", "tel:", "#")):
            continue

        try:
            parsed_url = urlparse(href)
            domain = parsed_url.netloc.lower()
            bare_domain = domain[4:] if domain.startswith("www.") else domain

            # Only check UTMs on brand-domain links
            is_brand = any(
                bare_domain == d.lower() or bare_domain.endswith("." + d.lower())
                for d in brand_domains
            )
            if is_brand:
                checkable_links.append(link)
        except Exception:
            continue

    if not checkable_links:
        return errors, warnings

    links_missing_utm = 0
    links_wrong_source = 0
    links_wrong_medium = 0

    for link in checkable_links:
        href = link["href"]
        try:
            parsed_url = urlparse(href)
            params = parse_qs(parsed_url.query)

            has_source = "utm_source" in params
            has_medium = "utm_medium" in params
            has_campaign = "utm_campaign" in params

            if not (has_source and has_medium and has_campaign):
                links_missing_utm += 1
                continue

            # Validate values
            if accepted_sources and has_source:
                actual_source = params["utm_source"][0]
                if actual_source not in accepted_sources:
                    links_wrong_source += 1

            if has_medium:
                actual_medium = params["utm_medium"][0]
                if actual_medium != expected_medium:
                    links_wrong_medium += 1

        except Exception:
            continue

    if links_missing_utm > 0:
        warnings.append(
            f"{links_missing_utm} of {len(checkable_links)} brand-domain links "
            f"are missing UTM parameters. Verify that Link Management templates "
            f"are applied in Braze."
        )

    if links_wrong_source > 0:
        warnings.append(
            f"{links_wrong_source} link(s) have utm_source that doesn't match "
            f"expected value '{expected_source}' for {brand_upper}."
        )

    if links_wrong_medium > 0:
        warnings.append(
            f"{links_wrong_medium} link(s) have utm_medium that doesn't match "
            f"expected value '{expected_medium}' for {channel} channel."
        )

    return errors, warnings


def _strip_style_blocks(html: str) -> str:
    """Remove <style>...</style> blocks so CSS braces don't confuse Liquid checks."""
    return re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)


def _strip_mso_conditionals(html: str) -> str:
    """Remove <!--[if mso]>...<![endif]--> blocks."""
    return re.sub(r"<!--\[if[^]]*\]>.*?<!\[endif\]-->", "", html, flags=re.DOTALL)


def validate_liquid_syntax(html: str) -> Tuple[List[str], List[str]]:
    """Check for common Liquid syntax errors.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Strip CSS and MSO blocks so their braces don't cause false positives
    cleaned = _strip_style_blocks(html)
    cleaned = _strip_mso_conditionals(cleaned)

    # Count opening/closing double-brace tags
    open_braces = len(re.findall(r"\{\{", cleaned))
    close_braces = len(re.findall(r"\}\}", cleaned))
    if open_braces != close_braces:
        errors.append(
            f"Mismatched Liquid output tags: {open_braces} opening '{{{{' vs "
            f"{close_braces} closing '}}}}'. Check for unclosed tags."
        )

    # Count opening/closing Liquid block tags
    open_blocks = re.findall(r"\{%\s*(if|unless|for|case)\b", cleaned, re.IGNORECASE)
    close_blocks = re.findall(r"\{%\s*end(if|unless|for|case)\b", cleaned, re.IGNORECASE)
    if len(open_blocks) != len(close_blocks):
        errors.append(
            f"Mismatched Liquid block tags: {len(open_blocks)} opening "
            f"(if/unless/for/case) vs {len(close_blocks)} closing "
            f"(endif/endunless/endfor/endcase)."
        )

    # Check for bare ${...} without outer {{ }}
    # Pattern: ${...} that is NOT preceded by {{ and NOT part of {{...${...}...}}
    bare_vars = re.findall(r"(?<!\{)\$\{[^}]+\}(?!\s*\})", cleaned)
    if bare_vars:
        # Filter out false positives inside {{ }} context
        for var in bare_vars[:3]:
            # Check if it's actually inside {{ }}
            pos = cleaned.find(var)
            if pos >= 0:
                # Look backwards for {{
                preceding = cleaned[max(0, pos - 50):pos]
                if "{{" not in preceding:
                    errors.append(
                        f"Possible bare Liquid variable without {{{{...}}}}: {var}. "
                        f"Should be {{{{${{{var[2:-1]}}}}}}}."
                    )
                    break

    # Check for malformed content_blocks references
    content_block_refs = re.findall(
        r"\{\{content_blocks\.\$\{([^}]*)\}", cleaned
    )
    for ref in content_block_refs:
        # Should have a matching closing }}
        full_pattern = f"{{{{content_blocks.${{{{" + ref + "}}"
        pos = cleaned.find(full_pattern)
        if pos >= 0:
            # Check that there's a closing }} somewhere after
            after = cleaned[pos:pos + len(full_pattern) + 50]
            if "}}" not in after[len(full_pattern):]:
                errors.append(
                    f"Malformed content_blocks reference: content_blocks.${{{ref}}} "
                    f"— missing closing braces."
                )

    return errors, warnings


def validate_title_tag(parsed: EmailHTMLParser) -> Tuple[List[str], List[str]]:
    """Warn if <title> tag is missing or empty.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    if parsed.title is None or parsed.title.strip() == "":
        warnings.append(
            "Email has no <title> tag or it is empty. Some email clients "
            "display the title — consider adding a descriptive title."
        )

    return errors, warnings


# =========================================================================
# NETWORK-DEPENDENT CHECKS (opt-in)
# =========================================================================

async def _check_links_async(
    parsed: EmailHTMLParser,
    check_images: bool = True,
) -> Tuple[List[str], List[str]]:
    """HTTP HEAD check for broken links and oversized images.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    try:
        import aiohttp
    except ImportError:
        warnings.append(
            "aiohttp not installed — skipping link/image checks. "
            "Install with: uv add aiohttp"
        )
        return errors, warnings

    # Collect unique URLs to check
    urls_to_check: Dict[str, str] = {}  # url -> type (link/image)

    for link in parsed.links:
        href = link["href"]
        if href and href.startswith("http"):
            urls_to_check[href] = "link"

    if check_images:
        for img in parsed.images:
            src = img["src"]
            if src and src.startswith("http"):
                urls_to_check[src] = "image"

    if not urls_to_check:
        return errors, warnings

    total_image_size = 0

    async with aiohttp.ClientSession() as session:
        for url, url_type in urls_to_check.items():
            url_display = url[:100] + "..." if len(url) > 100 else url
            try:
                async with session.head(
                    url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True
                ) as resp:
                    if resp.status == 404:
                        warnings.append(f"Broken {url_type} (404): {url_display}")
                    elif resp.status >= 500:
                        warnings.append(
                            f"{url_type.title()} returned server error "
                            f"({resp.status}): {url_display}"
                        )

                    # Check image size
                    if url_type == "image" and resp.status == 200:
                        content_length = resp.headers.get("Content-Length")
                        if content_length:
                            size = int(content_length)
                            total_image_size += size
                            if size > MAX_IMAGE_SIZE_BYTES:
                                size_mb = size / 1_000_000
                                warnings.append(
                                    f"Large image ({size_mb:.1f} MB): {url_display}. "
                                    f"Consider optimizing to under 1 MB."
                                )

            except asyncio.TimeoutError:
                warnings.append(f"Timeout checking {url_type}: {url_display}")
            except Exception as e:
                warnings.append(
                    f"Error checking {url_type} ({type(e).__name__}): {url_display}"
                )

    if total_image_size > MAX_TOTAL_IMAGE_SIZE_BYTES:
        total_mb = total_image_size / 1_000_000
        warnings.append(
            f"Total image weight is {total_mb:.1f} MB (recommended max: 3 MB). "
            f"Consider optimizing images for faster load times."
        )

    return errors, warnings


def check_links_sync(
    parsed: EmailHTMLParser,
    check_images: bool = True,
) -> Tuple[List[str], List[str]]:
    """Synchronous wrapper for async link checking."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an async context — create a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run, _check_links_async(parsed, check_images)
            )
            return future.result()
    else:
        return asyncio.run(_check_links_async(parsed, check_images))


# =========================================================================
# SMS-SPECIFIC VALIDATION
# =========================================================================

def validate_sms_utms(
    sms_body: str,
    brand: str,
    require_bzt: bool = False,
) -> Tuple[List[str], List[str]]:
    """Validate UTM parameters on links in SMS body text.

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    brand_upper = brand.upper()
    accepted_sources = BRAND_UTM_SOURCES.get(brand_upper, ())
    expected_source = accepted_sources[0] if accepted_sources else None

    # Extract URLs from SMS body
    url_pattern = re.compile(r'(https?://[^\s,;)]+)')
    urls = url_pattern.findall(sms_body)

    if not urls:
        warnings.append("No URLs found in SMS body.")
        return errors, warnings

    for url in urls:
        try:
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)

            has_source = "utm_source" in params
            has_medium = "utm_medium" in params

            if not has_source:
                warnings.append(
                    f"SMS link missing utm_source: {url[:80]}"
                )
            elif accepted_sources and params["utm_source"][0] not in accepted_sources:
                warnings.append(
                    f"SMS link has utm_source='{params['utm_source'][0]}', "
                    f"expected '{expected_source}': {url[:80]}"
                )

            if not has_medium:
                warnings.append(f"SMS link missing utm_medium: {url[:80]}")
            elif has_medium and params["utm_medium"][0] != "sms":
                warnings.append(
                    f"SMS link has utm_medium='{params['utm_medium'][0]}', "
                    f"expected 'sms': {url[:80]}"
                )

            if require_bzt and "bzt" not in params:
                errors.append(f"SMS link missing required bzt param: {url[:80]}")

        except Exception:
            continue

    return errors, warnings


# =========================================================================
# MAIN ENTRY POINTS
# =========================================================================

def validate_html(
    html_content: str,
    brand: str,
    channel: str = "email",
    subscription_group: str = "Marketing",
    check_links: bool = False,
) -> Tuple[List[str], List[str]]:
    """Run all HTML validation checks.

    Args:
        html_content: Raw HTML string.
        brand: Brand code (HAV, CZ, ID, BUR, STF, TI).
        channel: "email" or "sms".
        subscription_group: "Marketing" or "Transactional".
        check_links: If True, perform network checks (HTTP HEAD for links/images).

    Returns:
        (errors, warnings) — errors are blocking; warnings are advisory.
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []

    if not html_content or not html_content.strip():
        return ["HTML content is empty"], []

    # Parse HTML
    parsed = _parse_html(html_content)

    # 1. Image alt tags
    errs, warns = validate_image_alt_tags(parsed)
    all_errors.extend(errs)
    all_warnings.extend(warns)

    # 2. Unsubscribe link (marketing emails only)
    if channel == "email":
        errs, warns = validate_unsubscribe_link(html_content, subscription_group)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    # 3. Brand domain validation
    errs, warns = validate_brand_domains(parsed, brand)
    all_errors.extend(errs)
    all_warnings.extend(warns)

    # 4. UTM parameter enforcement
    errs, warns = validate_utm_parameters(parsed, brand, channel)
    all_errors.extend(errs)
    all_warnings.extend(warns)

    # 5. Liquid syntax
    errs, warns = validate_liquid_syntax(html_content)
    all_errors.extend(errs)
    all_warnings.extend(warns)

    # 6. Title tag
    if channel == "email":
        errs, warns = validate_title_tag(parsed)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    # 7. Network checks (opt-in)
    if check_links:
        errs, warns = check_links_sync(parsed, check_images=True)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    return all_errors, all_warnings


def validate_sms(
    sms_body: str,
    brand: str,
    require_bzt: bool = False,
) -> Tuple[List[str], List[str]]:
    """Run SMS-specific validation checks.

    Args:
        sms_body: SMS message text.
        brand: Brand code.
        require_bzt: If True, treat a missing bzt param as an error.

    Returns:
        (errors, warnings)
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []

    if not sms_body or not sms_body.strip():
        return ["SMS body is empty"], []

    errs, warns = validate_sms_utms(sms_body, brand, require_bzt=require_bzt)
    all_errors.extend(errs)
    all_warnings.extend(warns)

    return all_errors, all_warnings
