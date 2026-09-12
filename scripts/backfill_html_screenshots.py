#!/usr/bin/env python3
"""
Backfill HTML content and screenshots for email campaigns.

Fetches campaign HTML from Braze, saves it, and captures screenshots.

Usage:
    uv run python scripts/backfill_html_screenshots.py --brand HAV
    uv run python scripts/backfill_html_screenshots.py --all --workers 5
    uv run python scripts/backfill_html_screenshots.py --all --limit 100
"""

import argparse
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import yaml

from import_braze import (
    init_config,
    get_campaign_details,
    slugify,
)


def extract_image_urls(html):
    """Extract image URLs from HTML content."""
    if not html:
        return []

    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    urls = re.findall(img_pattern, html, re.IGNORECASE)

    bg_pattern = r'background-image:\s*url\(["\']?([^"\')\s]+)["\']?\)'
    urls.extend(re.findall(bg_pattern, html, re.IGNORECASE))

    filtered = []
    for url in urls:
        if url.startswith('data:'):
            continue
        if '{{' in url:
            continue
        if url.strip():
            filtered.append(url)

    return list(set(filtered))


def capture_screenshot(html_content, output_path, browser, width=600):
    """Render HTML and capture screenshot using provided browser."""
    try:
        context = browser.new_context(
            viewport={"width": width, "height": 800},
            device_scale_factor=2,
        )
        page = context.new_page()

        # Set content and wait for images to load
        page.set_content(html_content, wait_until="networkidle")

        # Get full page height
        height = page.evaluate("document.body.scrollHeight")

        # Resize viewport to full height (capped at 5000px)
        page.set_viewport_size({"width": width, "height": min(height, 5000)})

        # Take screenshot
        page.screenshot(path=str(output_path), full_page=True)

        context.close()
        return True
    except Exception as e:
        print(f"Screenshot error: {e}")
        return False


def load_campaigns_missing_screenshots(campaigns_dir, screenshots_dir, brand=None, html_dir=None, html_only=False):
    """Load email campaigns that don't have screenshots (or HTML, in html_only mode)."""
    campaigns = []

    for f in campaigns_dir.glob("*.yaml"):
        if f.name.startswith("_"):
            continue

        with open(f) as file:
            data = yaml.safe_load(file)
            if not data:
                continue

        if brand and data.get("brand") != brand:
            continue

        # Skip canvas-level records and canvas steps — not fetchable via campaign details API
        braze_type = data.get("braze_type", "")
        if braze_type in ("canvas", "canvas_step"):
            continue

        # Check if any send is an email with subject
        has_email = False
        for send in data.get("sends", []):
            if send.get("channel") == "email" and send.get("subject"):
                has_email = True
                break

        if not has_email:
            continue

        braze_id = data.get("braze_id") or data.get("id")
        if not braze_id:
            continue

        # Skip Klaviyo campaigns — IDs are not valid Braze campaign identifiers
        if str(braze_id).startswith("klaviyo-") or not re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            str(braze_id),
            re.IGNORECASE,
        ):
            continue

        slug = slugify(data.get("name", ""))

        # In html_only mode, skip if HTML already exists
        if html_only and html_dir:
            html_file = html_dir / f"{slug}.html"
            if html_file.exists():
                continue
        else:
            # Normal mode: skip if screenshot already exists
            screenshot_file = screenshots_dir / f"{slug}.png"
            if screenshot_file.exists():
                continue

        campaigns.append({
            "file": f,
            "data": data,
            "braze_id": braze_id,
            "slug": slug,
        })

    return campaigns


def fetch_html(campaign_info, html_dir):
    """Fetch campaign HTML from Braze (can be parallelized)."""
    braze_id = campaign_info["braze_id"]
    slug = campaign_info["slug"]

    html_file = html_dir / f"{slug}.html"

    # Check if we already have HTML
    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read(), None

    # Fetch from Braze
    details = get_campaign_details(braze_id)

    if not details or "messages" not in details:
        return None, "No message details returned"

    for msg_key, msg_data in details.get("messages", {}).items():
        body = msg_data.get("body", "")
        if body and msg_data.get("channel") == "email":
            # Save HTML
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(body)
            return body, None

    return None, "No HTML body in campaign"


def process_screenshot(campaign_info, html_content, html_dir, screenshots_dir, browser):
    """Capture screenshot and update YAML (must be sequential due to Playwright)."""
    data = campaign_info["data"]
    filepath = campaign_info["file"]
    slug = campaign_info["slug"]

    screenshot_file = screenshots_dir / f"{slug}.png"

    success = capture_screenshot(html_content, screenshot_file, browser)
    if not success:
        return None, "Screenshot capture failed"

    # Update campaign YAML with references
    image_urls = extract_image_urls(html_content)
    for send in data.get("sends", []):
        if send.get("channel") == "email":
            send["html_file"] = f"html/{slug}.html"
            send["screenshot"] = f"screenshots/{slug}.png"
            if image_urls:
                send["image_urls"] = image_urls[:10]
            break

    with open(filepath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return {
        "html_size": len(html_content),
        "image_count": len(image_urls),
    }, None


def main():
    parser = argparse.ArgumentParser(description="Backfill HTML and screenshots for emails")
    parser.add_argument("--brand", type=str, help="Brand to backfill (HAV, CZ, etc.)")
    parser.add_argument("--all", action="store_true", help="Backfill all brands")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    parser.add_argument("--workers", type=int, default=10, help="Parallel workers for API calls (default: 10)")
    parser.add_argument("--limit", type=int, help="Limit number of campaigns")
    parser.add_argument("--skip-screenshots", action="store_true", help="Fetch HTML only; skip Playwright screenshot rendering")
    args = parser.parse_args()

    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return

    script_dir = Path(__file__).parent
    campaigns_dir = script_dir.parent / "campaigns"
    html_dir = campaigns_dir / "html"
    screenshots_dir = campaigns_dir / "screenshots"

    html_dir.mkdir(exist_ok=True)
    screenshots_dir.mkdir(exist_ok=True)

    if args.all:
        brands = ["HAV", "CZ", "STF", "BUR", "ID", "TI", "TE"]
    else:
        brands = [args.brand.upper()]

    total_updated = 0
    total_skipped = 0

    # Initialize Playwright browser once (must be in main thread) — skipped when --skip-screenshots
    playwright = None
    browser = None
    if not args.skip_screenshots:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch()

    try:
        for brand in brands:
            print(f"\n{'='*60}")
            print(f"Processing {brand}")
            print(f"{'='*60}")

            try:
                init_config(brand)
            except SystemExit:
                # Klaviyo-only brand — no Braze API key needed; HTML is read from disk
                print(f"  Note: No Braze API key for {brand} (Klaviyo brand) — HTML read from disk only")

            campaigns = load_campaigns_missing_screenshots(
                campaigns_dir, screenshots_dir, brand,
                html_dir=html_dir, html_only=args.skip_screenshots,
            )
            print(f"Found {len(campaigns)} email campaigns missing screenshots")

            if not campaigns:
                continue

            if args.limit:
                campaigns = campaigns[:args.limit]
                print(f"Limited to {args.limit} campaigns")

            # Phase 1: Fetch HTML in parallel
            print(f"\nPhase 1: Fetching HTML ({args.workers} workers)...")
            html_results = {}
            fetch_errors = {}

            def fetch_worker(campaign_info):
                html, error = fetch_html(campaign_info, html_dir)
                return campaign_info["slug"], html, error

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(fetch_worker, c) for c in campaigns]
                for i, future in enumerate(as_completed(futures), 1):
                    slug, html, error = future.result()
                    if html:
                        html_results[slug] = html
                    else:
                        fetch_errors[slug] = error
                    print(f"\r  Fetched {i}/{len(campaigns)} HTML files...", end="", flush=True)

            print(f"\n  Got {len(html_results)} HTML files, {len(fetch_errors)} errors")

            if args.dry_run:
                print(f"\n{brand}: Would save {len(html_results)} HTML files (dry-run)")
                total_updated += len(html_results)
                total_skipped += len(fetch_errors)
                continue

            if args.skip_screenshots:
                print(f"\n{brand}: Saved {len(html_results)} HTML files (screenshots skipped)")
                total_updated += len(html_results)
                total_skipped += len(fetch_errors)
                continue

            # Phase 2: Capture screenshots sequentially (Playwright limitation)
            print(f"\nPhase 2: Capturing screenshots...")
            updated_count = 0
            skipped_count = len(fetch_errors)

            for i, campaign_info in enumerate(campaigns, 1):
                slug = campaign_info["slug"]

                if slug not in html_results:
                    continue

                html_content = html_results[slug]
                result, error = process_screenshot(
                    campaign_info, html_content, html_dir, screenshots_dir, browser
                )

                name = campaign_info["data"].get("name", "")[:40]
                if result:
                    updated_count += 1
                    size_kb = result["html_size"] / 1024
                    print(f"[{updated_count}/{len(html_results)}] {name}... {size_kb:.1f}KB")
                else:
                    skipped_count += 1
                    print(f"[SKIP] {name}: {error}")

            print(f"\n{brand}: Saved {updated_count}, Skipped {skipped_count}")
            total_updated += updated_count
            total_skipped += skipped_count

    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()

    print(f"\n{'='*60}")
    print(f"TOTAL: Saved {total_updated} screenshots, Skipped {total_skipped}")
    print(f"HTML: {html_dir}")
    print(f"Screenshots: {screenshots_dir}")


if __name__ == "__main__":
    main()
