#!/usr/bin/env python3
"""
Fetch and cache content block HTML for blocks referenced in canvas HTML files.

Only fetches blocks that are actually used — much faster than fetching all blocks.
Saves raw (Liquid) HTML to data/content_blocks/{brand}/{name}.html.

Usage:
    uv run python scripts/fetch_content_blocks.py              # all brands
    uv run python scripts/fetch_content_blocks.py --brand BUR  # one brand
    uv run python scripts/fetch_content_blocks.py --force      # re-fetch all
"""

import argparse
import os
import re
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

BRANDS = ["BUR", "HAV", "CZ", "ID", "STF"]  # TI uses Klaviyo, no Braze content blocks

# Blocks that require live user/session data — not worth fetching
PERSONALIZATION_BLOCKS = {
    "browse_product_recs", "browse_product_recs_ab", "browsed_products",
    "cart_product_recs", "purchase_product_recs", "shopping_cart_items",
    "shopping_cart_items_2", "shopping_cart_items_DM",
    "shopping_cart_items_cart_viewed", "swatch_shopping_cart",
    "recs_sofas", "recs_sectionals", "recs_chairs", "recs_ottomans",
    "recs_beds", "recs_nightstands", "recs_rugs", "recs_pillows",
    "recs_dining_tables", "recs_dining_seating", "recs_lighting",
    "recs_art", "recs_accent_tables", "recs_benches",
}


def get_canvas_html_files_for_brand(brand: str) -> list[Path]:
    """Return canvas HTML files belonging to the given brand."""
    html_dir = ROOT / "campaigns" / "html"
    yaml_dir = ROOT / "campaigns"
    result = []
    for html_path in html_dir.glob("canvas-*.html"):
        slug = html_path.stem
        yaml_path = yaml_dir / f"{slug}.yaml"
        if not yaml_path.exists():
            continue
        try:
            data = yaml.safe_load(yaml_path.read_text())
            if data.get("brand") == brand:
                result.append(html_path)
        except Exception:
            continue
    return result


def get_needed_block_names(brand: str) -> set[str]:
    """Extract unique content block names used in canvas HTML files for a brand."""
    needed = set()
    for html_path in get_canvas_html_files_for_brand(brand):
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        names = re.findall(r'content_blocks\.\$\{([^}]+)\}', html)
        needed.update(names)
    return needed - PERSONALIZATION_BLOCKS


def fetch_content_blocks_for_brand(brand: str, force: bool = False) -> int:
    from import_braze import init_config, braze_request

    needed = get_needed_block_names(brand)
    if not needed:
        print(f"  {brand}: no content blocks needed")
        return 0

    out_dir = ROOT / "data" / "content_blocks" / brand
    out_dir.mkdir(parents=True, exist_ok=True)

    # Skip already-cached blocks unless --force
    if not force:
        needed = {n for n in needed if not (out_dir / f"{n}.html").exists()}
    if not needed:
        print(f"  {brand}: all blocks already cached")
        return 0

    print(f"  {brand}: fetching {len(needed)} blocks: {', '.join(sorted(needed))}")
    try:
        init_config(brand)
        # ID has a dedicated content blocks API key with the right permissions
        if brand == "ID":
            import import_braze as _ib
            cb_key = os.environ.get("BRAZE_CONTENT_BLOCKS_API_KEY_ID")
            if cb_key:
                _ib.CONFIG["api_key"] = cb_key
    except Exception as e:
        print(f"  {brand}: init failed — {e}")
        return 0

    # Build name→id map by paging through the list
    name_to_id = {}
    page = 0
    while True:
        resp = braze_request("content_blocks/list", params={"page": page, "limit": 100})
        if resp is None:
            print(f"  {brand}: API returned None — check API key permissions")
            return 0
        blocks = resp.get("content_blocks", [])
        if not blocks:
            break
        for b in blocks:
            if b.get("name") in needed:
                name_to_id[b["name"]] = b["content_block_id"]
        page += 1
        if len(blocks) < 100:
            break

    saved = 0
    for name in sorted(needed):
        cb_id = name_to_id.get(name)
        if not cb_id:
            print(f"    {name}: not found in Braze")
            continue
        info = braze_request("content_blocks/info", params={"content_block_id": cb_id})
        body = info.get("content", "")
        if body:
            (out_dir / f"{name}.html").write_text(body, encoding="utf-8")
            saved += 1
            print(f"    ✓ {name}")
        else:
            print(f"    ✗ {name}: empty body")

    print(f"  {brand}: {saved}/{len(needed)} saved")
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", choices=BRANDS, help="Single brand to fetch")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    args = parser.parse_args()

    brands = [args.brand] if args.brand else BRANDS
    for brand in brands:
        print(f"\n{brand}:")
        try:
            fetch_content_blocks_for_brand(brand, force=args.force)
        except Exception as e:
            print(f"  ERROR — {e}")


if __name__ == "__main__":
    main()
