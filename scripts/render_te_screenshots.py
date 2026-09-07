"""Render screenshots for TE Klaviyo flow emails using Playwright."""
import os, glob
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent.parent
HTML_DIR = BASE / "campaigns" / "html"
SS_DIR   = BASE / "campaigns" / "screenshots"
SS_DIR.mkdir(exist_ok=True)

# Find all TE flow HTML files
patterns = [
    "klv-flow-flow-welcome-series-*.html",
    "klv-flow-trade_program-welcome-june2026-*.html",
    "klv-flow-trade_program-welcome-july2025-*.html",
    "klv-flow-flow-sr_post-purchase_trade-*.html",
    "klv-flow-flow-sh_abandoned-browse2-*.html",
    "klv-flow-flow-co_create-account-*.html",
    "klv-flow-flow-sh_abandoned-cart2-*.html",
    "klv-flow-flow-co_post-consultation_ecom-xo-*.html",
]

html_files = []
for pat in patterns:
    html_files.extend(sorted(HTML_DIR.glob(pat)))

# Deduplicate and filter to TE-only (skip TI armadillo/welcome-series etc.)
seen = set()
to_render = []
for f in html_files:
    if f.name not in seen:
        seen.add(f.name)
        to_render.append(f)

print(f"Rendering {len(to_render)} TE flow screenshots...")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 600, "height": 800})

    for i, html_path in enumerate(to_render, 1):
        slug = html_path.stem
        out = SS_DIR / f"{slug}.png"
        if out.exists():
            print(f"  [{i}/{len(to_render)}] SKIP (exists): {slug}")
            continue
        try:
            page.goto(f"file:///{html_path.as_posix()}", wait_until="networkidle")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out), full_page=True)
            print(f"  [{i}/{len(to_render)}] OK: {slug}")
        except Exception as e:
            print(f"  [{i}/{len(to_render)}] ERROR {slug}: {e}")

    browser.close()

print("Done.")
