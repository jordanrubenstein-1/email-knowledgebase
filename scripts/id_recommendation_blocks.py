#!/usr/bin/env python3
"""
Interior Define "You May Also Like" — Content Block Generator

Queries Snowflake for top-selling products per MERCH_CLASS, constructs
Cylindo image URLs + real product page URLs, and creates/updates Braze
Content Blocks via the Braze Content Blocks API.

Usage:
    # Preview HTML without touching Braze (safe to run anytime):
    uv run python scripts/id_recommendation_blocks.py --dry-run

    # Generate and push all content blocks to Braze:
    uv run python scripts/id_recommendation_blocks.py

    # Refresh a single category only:
    uv run python scripts/id_recommendation_blocks.py --category Sofas

    # Preview a single category:
    uv run python scripts/id_recommendation_blocks.py --dry-run --category Rugs

When to refresh:
    Top sellers are stable — refresh when major new collections launch or
    seasonally (quarterly is plenty). No scheduled automation needed.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from snowflake_client import get_snowflake_client
from braze_campaign_api import braze_post_request
from import_braze import init_config, get_api_key, get_base_url
from utils.id_rec_utils import (
    CROSS_SELL_MAP,
    EXCLUDED_COLLECTIONS,
    EXCLUDED_SKUS,
    FEED_METADATA_QUERY,
    MANUAL_COLOR_OVERRIDES,
    MERCH_CLASS_TO_BLOCK,
    PRODUCTS_QUERY,
    SUBCLASS_PRODUCTS_QUERY,
    URL_RAW_QUERY,
    _PREFER_LAST_FAMILIES,
    _is_upholstered_sku,
    apply_sofa_preferences,
    build_liquid_pool,
    build_rec_html,
    build_rec_html_liquid,
    build_slot_arrays_for_n,
    build_url_lookup,
    color_family,
    cylindo_image_url,
    display_name,
    get_cross_sell_products,
    product_url,
    resolve_all_image_urls,
    resolve_graphql_url_overrides,
)


BRAND = "ID"

# Color family prefix → human-readable fabric family name.
# Matches the prefix extracted from swatch SKUs in Braze Liquid (split on "-", take first).
# Leather (LTHR, 2210A) intentionally excluded — gets separate email treatment.
SWATCH_COLOR_FAMILIES: Dict[str, str] = {
    "ROY":  "Performance Plush Velvet",
    "MER":  "Performance Antimicrobial Chenille",
    "SE":   "Performance Velvet",
    "COV":  "Performance Vintage Velvet",
    "AK":   "Mod Velvet",
    "HRT":  "Performance Brushed Knit",
    "LNL":  "Natural Linen",
    "CAS":  "Performance Classic Weave",
    "AM":   "Performance Loop Weave",
    "GIA":  "Performance Linen Weave",
    "PD":   "Performance Down",
    "SMA":  "Performance Smart Weave",
}

# SQL for top sofas/sectionals/chairs in a specific color family.
# {prefix} is replaced at runtime (e.g. "ROY" → FABRIC_SKU LIKE 'ROY%').
# Revenue = purchase_count × catalog_price. One product per COLLECTION+MATERIAL.
_SWATCH_REC_QUERY = """
WITH purchase_stats AS (
    SELECT
        p.SKU, p.NAME, p.MERCH_CLASS, p.COLLECTION, p.MATERIAL, p.PRICE,
        COUNT(soi.PRODUCT_WID)           AS purchase_count,
        COUNT(soi.PRODUCT_WID) * p.PRICE AS revenue_score
    FROM PROD.ID_WAREHOUSE.DIM_PRODUCTS p
    LEFT JOIN PROD.ID_WAREHOUSE.FACT_SALES_ORDER_ITEMS soi ON soi.PRODUCT_WID = p.WID
    WHERE p.STATUS = 1
        AND p.MERCH_CLASS IN ('Sofas', 'Sectionals', 'Chairs')
        AND p.PRICE > 0
    GROUP BY 1, 2, 3, 4, 5, 6
),
deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY COLLECTION, MATERIAL
            ORDER BY revenue_score DESC
        ) AS coll_rank
    FROM purchase_stats
),
color_variants AS (
    SELECT
        ITEM_GROUP_ID                                                               AS base_sku,
        REPLACE(SPLIT_PART(TITLE, ' in ', 1), ' Custom', '')                       AS product_name,
        LINK                                                                        AS product_link,
        IMAGE_LINK                                                                  AS image_url,
        REGEXP_SUBSTR(IMAGE_LINK, 'feature=COLOR:([^&%]+)', 1, 1, 'e', 1)          AS color_code,
        PRICE                                                                       AS list_price,
        SALE_PRICE                                                                  AS sale_price,
        SALE_PRICE_EFFECTIVE_DATE_FROM                                              AS sale_from,
        SALE_PRICE_EFFECTIVE_DATE_TO                                                AS sale_to
    FROM PROD.ID_WAREHOUSE.MARKETING_PRODUCT_FEED
    WHERE FABRIC_SKU LIKE '{prefix}%'
        AND STATUS = 'Active'
        AND AVAILABILITY = 'in_stock'
        AND PROMO_ROW_NUMBER = 1
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ITEM_GROUP_ID ORDER BY LINK) = 1
)
SELECT
    d.SKU, d.NAME, d.MERCH_CLASS, d.COLLECTION, d.PRICE,
    d.purchase_count, d.revenue_score,
    cv.product_name, cv.product_link, cv.image_url, cv.color_code,
    cv.list_price, cv.sale_price, cv.sale_from, cv.sale_to
FROM deduped d
JOIN color_variants cv ON cv.base_sku = d.SKU
WHERE d.coll_rank = 1
ORDER BY d.revenue_score DESC
LIMIT 6
"""

# SQL for the default fallback block — top sofas/sectionals/chairs in any non-leather color.
_SWATCH_DEFAULT_QUERY = """
WITH purchase_stats AS (
    SELECT
        p.SKU, p.NAME, p.MERCH_CLASS, p.COLLECTION, p.MATERIAL, p.PRICE,
        COUNT(soi.PRODUCT_WID)           AS purchase_count,
        COUNT(soi.PRODUCT_WID) * p.PRICE AS revenue_score
    FROM PROD.ID_WAREHOUSE.DIM_PRODUCTS p
    LEFT JOIN PROD.ID_WAREHOUSE.FACT_SALES_ORDER_ITEMS soi ON soi.PRODUCT_WID = p.WID
    WHERE p.STATUS = 1
        AND p.MERCH_CLASS IN ('Sofas', 'Sectionals', 'Chairs')
        AND p.PRICE > 0
    GROUP BY 1, 2, 3, 4, 5, 6
),
deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY COLLECTION, MATERIAL
            ORDER BY revenue_score DESC
        ) AS coll_rank
    FROM purchase_stats
),
color_variants AS (
    SELECT
        ITEM_GROUP_ID                                                               AS base_sku,
        REPLACE(SPLIT_PART(TITLE, ' in ', 1), ' Custom', '')                       AS product_name,
        LINK                                                                        AS product_link,
        IMAGE_LINK                                                                  AS image_url,
        REGEXP_SUBSTR(IMAGE_LINK, 'feature=COLOR:([^&%]+)', 1, 1, 'e', 1)          AS color_code,
        PRICE                                                                       AS list_price,
        SALE_PRICE                                                                  AS sale_price,
        SALE_PRICE_EFFECTIVE_DATE_FROM                                              AS sale_from,
        SALE_PRICE_EFFECTIVE_DATE_TO                                                AS sale_to
    FROM PROD.ID_WAREHOUSE.MARKETING_PRODUCT_FEED
    WHERE STATUS = 'Active'
        AND AVAILABILITY = 'in_stock'
        AND PROMO_ROW_NUMBER = 1
        AND FABRIC_SKU NOT LIKE 'LTHR%'
        AND FABRIC_SKU NOT LIKE '2210A%'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ITEM_GROUP_ID ORDER BY LINK) = 1
)
SELECT
    d.SKU, d.NAME, d.MERCH_CLASS, d.COLLECTION, d.PRICE,
    d.purchase_count, d.revenue_score,
    cv.product_name, cv.product_link, cv.image_url, cv.color_code,
    cv.list_price, cv.sale_price, cv.sale_from, cv.sale_to
FROM deduped d
JOIN color_variants cv ON cv.base_sku = d.SKU
WHERE d.coll_rank = 1
ORDER BY d.revenue_score DESC
LIMIT 6
"""


def _swatch_rows_to_products(rows: List[Dict]) -> List[Dict]:
    """Convert Snowflake result rows to product dicts expected by build_rec_html."""
    import re as _re
    products = []
    for r in rows:
        img = (r.get("IMAGE_URL") or "").strip()
        # Strip Cylindo feature params that cause 404 for some SKUs.
        # Match both raw-space ("SEAT HEIGHT") and percent-encoded ("SEAT%20HEIGHT") forms.
        img = _re.sub(r"&feature=(?:LENGTH|SEAT(?:%20| )HEIGHT|SEATHEIGHT|PIPING):[^&]*", "", img)
        products.append({
            "SKU":          r["SKU"],
            "NAME":         r["NAME"],
            "MERCH_CLASS":  r.get("MERCH_CLASS", ""),
            "COLLECTION":   r.get("COLLECTION", ""),
            "PRICE":        r.get("PRICE"),
            "DISPLAY_NAME": (r.get("PRODUCT_NAME") or "").strip(),
            "PRODUCT_URL":  (r.get("PRODUCT_LINK") or "").strip(),
            "PRODUCT_IMAGE": img,
            "COLOR_CODE":   (r.get("COLOR_CODE") or "").strip(),
            "LIST_PRICE":   r.get("LIST_PRICE"),
            "SALE_PRICE":   r.get("SALE_PRICE"),
            "SALE_FROM":    r.get("SALE_FROM"),
            "SALE_TO":      r.get("SALE_TO"),
        })
    return products


def generate_swatch_color_blocks(
    client,
    existing_blocks: Dict[str, str],
    dry_run: bool = False,
    family_filter: Optional[str] = None,
    save_dir: Optional[str] = None,
) -> tuple:
    """Generate SwatchRec_* content blocks for swatch post-purchase color personalization.

    Generates one Braze Content Block per active color family prefix, plus a
    SwatchRec_Default fallback. Block names match what the T1/T2 Liquid routes to:
      SwatchRec_ROY, SwatchRec_MER, SwatchRec_SE, SwatchRec_COV, SwatchRec_AK,
      SwatchRec_HRT, SwatchRec_LNL, SwatchRec_CAS, SwatchRec_AM, SwatchRec_GIA,
      SwatchRec_PD, SwatchRec_SMA, SwatchRec_Default

    Args:
        client:        Snowflake client (ID_WAREHOUSE)
        existing_blocks: Dict of name → content_block_id (from get_existing_blocks)
        dry_run:       Print HTML without pushing to Braze
        family_filter: If set, only generate block for this prefix (e.g. "ROY")
        save_dir:      If set, save each block's HTML as {save_dir}/{block_name}.html

    Returns:
        (success_count, skip_count, error_count) tuple
    """
    success_count = skip_count = error_count = 0
    families = list(SWATCH_COLOR_FAMILIES.items()) + [("Default", "All fabrics (fallback)")]

    for prefix, family_name in families:
        if family_filter and prefix.upper() != family_filter.upper():
            continue

        block_name = f"SwatchRec_{prefix}"

        if prefix == "Default":
            print(f"\nQuerying top sofas/sectionals/chairs (any color) → {block_name}")
            rows = client.execute_query(_SWATCH_DEFAULT_QUERY)
        else:
            print(f"\nQuerying {family_name} ({prefix}) → {block_name}")
            rows = client.execute_query(_SWATCH_REC_QUERY.replace("{prefix}", prefix))

        if not rows:
            print(f"  No products found — skipping")
            skip_count += 1
            continue

        products = _swatch_rows_to_products(rows)
        print(f"  {len(products)} products:")
        for p in products:
            price_val = p.get("LIST_PRICE") or p.get("PRICE") or 0
            try:
                price_val = float(price_val)
            except (TypeError, ValueError):
                price_val = 0.0
            print(
                f"    {(p['DISPLAY_NAME'] or p['NAME']):<55}"
                f"  ${price_val:>6,.0f}"
                f"  color={p.get('COLOR_CODE', '')}"
            )

        html = build_rec_html(products, {}, family_name)

        if save_dir:
            import os
            os.makedirs(save_dir, exist_ok=True)
            out_path = os.path.join(save_dir, f"{block_name}.html")
            with open(out_path, "w") as _f:
                _f.write(html)

        ok = upsert_content_block(block_name, html, existing_blocks, dry_run=dry_run)
        if ok:
            success_count += 1
        else:
            error_count += 1

    return success_count, skip_count, error_count


# ---------------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------------

def fetch_products(client) -> Dict[str, List[Dict]]:
    """Run PRODUCTS_QUERY and group results by MERCH_CLASS.

    Returns:
        Dict mapping MERCH_CLASS → list of product dicts (ordered revenue DESC)
    """
    print("Querying Snowflake for top products per MERCH_CLASS...")
    rows = client.execute_query(PRODUCTS_QUERY)

    by_class: Dict[str, List[Dict]] = defaultdict(list)
    excluded = 0
    for row in rows:
        mc = (row.get("MERCH_CLASS") or "").strip()
        collection = (row.get("COLLECTION") or "").strip()
        sku = (row.get("SKU") or "").strip()
        if mc:
            if collection in EXCLUDED_COLLECTIONS or sku in EXCLUDED_SKUS:
                excluded += 1
            else:
                by_class[mc].append(row)

    # SQL fetches up to 16 candidates per class; apply preferences then trim to 10
    for mc in by_class:
        if mc == "Sofas":
            by_class[mc] = apply_sofa_preferences(by_class[mc])
        else:
            by_class[mc] = by_class[mc][:10]

    total = sum(len(v) for v in by_class.values())
    print(f"  {total} products across {len(by_class)} MERCH_CLASSes ({excluded} excluded — discontinued collections)")
    return dict(by_class)


def fetch_url_lookup(client, base_skus: List[str]) -> Dict[str, str]:
    """Fetch product URLs from event data and match to base SKUs.

    Two-step process to avoid a slow LIKE join across 61M rows:
      1. SQL: extract distinct (variant_sku, clean_url) pairs from STG_MAPPED_TRACKS
      2. Python: prefix-match variant SKUs to DIM_PRODUCTS base SKUs

    Args:
        client:    Snowflake client
        base_skus: List of base SKUs from DIM_PRODUCTS (used for prefix matching)

    Returns:
        Dict mapping base SKU → clean product page URL (no query params)
    """
    print("Querying Snowflake for product URLs from Product Viewed events...")
    print("  (fetching all distinct variant SKUs — may take ~30s)")
    raw_rows = client.execute_query(URL_RAW_QUERY)
    print(f"  {len(raw_rows)} distinct variant SKU/URL pairs retrieved")

    print("  Matching variant SKUs to base SKUs (prefix match)...")
    lookup = build_url_lookup(raw_rows, base_skus)
    print(f"  {len(lookup)} base SKUs resolved to URLs")
    return lookup


def fetch_feed_metadata(client) -> Dict[str, List[Dict]]:
    """Fetch marketing names, URLs, and ALL color variants from MARKETING_PRODUCT_FEED.

    Returns multiple rows per base_sku (one per distinct color), sorted by
    color_frequency DESC (most-promoted color first). Python then picks colors
    greedily to maximize visual diversity across a recommendation block.

    Non-upholstered categories (Rugs, Art, Lighting, Accent Tables, Dining Tables,
    Pillows, Benches) are not in this feed and will fall back to DIM_PRODUCTS names.

    Returns:
        Dict mapping base_sku → list of variant dicts [{product_name, clean_url,
        image_url, color_code, color_freq}, ...] sorted by color_freq DESC
    """
    print("Querying Snowflake for marketing metadata (names, URLs, images)...")
    rows = client.execute_query(FEED_METADATA_QUERY)
    print(f"  {len(rows)} color variants found in MARKETING_PRODUCT_FEED")

    meta: Dict[str, List[Dict]] = {}
    for row in rows:
        sku = (row.get("BASE_SKU") or "").strip()
        if not sku:
            continue
        variant = {
            "product_name": (row.get("PRODUCT_NAME") or "").strip(),
            "product_link": (row.get("PRODUCT_LINK") or "").strip(),
            "image_url":    (row.get("IMAGE_URL") or "").strip(),
            "color_code":   (row.get("COLOR_CODE") or "").strip(),
            "color_freq":   row.get("FREQ", 0),
            "list_price":   row.get("LIST_PRICE"),
            "sale_price":   row.get("SALE_PRICE"),
            "sale_from":    row.get("SALE_FROM"),
            "sale_to":      row.get("SALE_TO"),
        }
        if sku not in meta:
            meta[sku] = []
        meta[sku].append(variant)
    return meta


def fetch_active_promo(client) -> Optional[Dict]:
    """Return the current sitewide general discount from ACTIVE_PROMOS, or None.

    Looks for an active by_percent promo whose name contains 'General'.
    Returns a dict with keys: discount_pct, sale_from, sale_to.
    """
    rows = client.execute_query("""
        SELECT DISCOUNT_AMOUNT, FROM_TIMESTAMP, TO_TIMESTAMP
        FROM PROD.ID_WAREHOUSE.ACTIVE_PROMOS
        WHERE IS_ACTIVE = 1
          AND SIMPLE_ACTION = 'by_percent'
          AND PROMO_NAME ILIKE '%general%'
          AND FROM_TIMESTAMP <= CURRENT_TIMESTAMP()
          AND TO_TIMESTAMP   >= CURRENT_TIMESTAMP()
        ORDER BY DISCOUNT_AMOUNT DESC
        LIMIT 1
    """)
    if not rows:
        return None
    r = rows[0]
    return {
        "discount_pct": float(r["DISCOUNT_AMOUNT"]),
        "sale_from":    r["FROM_TIMESTAMP"],
        "sale_to":      r["TO_TIMESTAMP"],
    }


def apply_promo_to_unenriched(products_by_class: Dict[str, List[Dict]], promo: Dict) -> int:
    """Stamp SALE_PRICE/SALE_FROM/SALE_TO onto products that have no feed sale price.

    Used for non-upholstered products (dining tables, rugs, accent tables, etc.)
    that aren't in MARKETING_PRODUCT_FEED but are covered by a sitewide promo.
    Returns count of products updated.
    """
    discount = promo["discount_pct"] / 100
    updated = 0
    for products in products_by_class.values():
        for p in products:
            if p.get("SALE_PRICE"):
                continue
            price = p.get("LIST_PRICE") or p.get("PRICE")
            if price and float(price) > 0:
                p["SALE_PRICE"] = round(float(price) * (1 - discount))
                p["SALE_FROM"]  = promo["sale_from"]
                p["SALE_TO"]    = promo["sale_to"]
                updated += 1
    return updated


def enrich_products_from_feed(
    products_by_class: Dict[str, List[Dict]],
    feed_meta: Dict[str, List[Dict]],
) -> None:
    """Stamp DISPLAY_NAME, PRODUCT_URL, PRODUCT_IMAGE onto each product dict.

    For each MERCH_CLASS block, assigns colors greedily to maximize visual
    diversity — if two products would show the same color family (e.g. two
    linen neutrals), the second product gets its next most-promoted color from
    a different family.

    Modifies product dicts in-place. Products not in the feed (Rugs, Art, etc.)
    are untouched — _card_html falls back to display_name() and Magento/Cylindo.

    Args:
        products_by_class: Dict of MERCH_CLASS → [product dicts] (mutated in place)
        feed_meta:         Dict of base_sku → [color variant dicts]
    """
    total = sum(len(v) for v in products_by_class.values())
    enriched = 0
    diverse_swaps = 0

    for merch_class, products in products_by_class.items():
        used_families: List[str] = []  # color families already assigned in this block

        for p in products:
            sku = p.get("SKU", "")
            variants = feed_meta.get(sku)
            if not variants:
                continue

            # Manual override: force a specific color for this SKU if configured
            chosen = None
            forced_code = MANUAL_COLOR_OVERRIDES.get(sku)
            if forced_code:
                for v in variants:
                    if v["color_code"] == forced_code:
                        chosen = v
                        break

            # Pass 1: prefer non-neutral, non-used families (skip linen/gia/bisque)
            if chosen is None:
                for v in variants:
                    fam = color_family(v["color_code"])
                    if fam not in used_families and fam not in _PREFER_LAST_FAMILIES:
                        chosen = v
                        if v is not variants[0]:
                            diverse_swaps += 1
                        break
            # Pass 2: all bold options used — try neutral unused families
            if chosen is None:
                for v in variants:
                    fam = color_family(v["color_code"])
                    if fam not in used_families:
                        chosen = v
                        if v is not variants[0]:
                            diverse_swaps += 1
                        break
            # Pass 3: all families exhausted — fall back to most-promoted color
            if chosen is None:
                chosen = variants[0]

            used_families.append(color_family(chosen["color_code"]))

            if chosen["product_name"]:
                p["DISPLAY_NAME"] = chosen["product_name"]
            if chosen["product_link"]:
                p["PRODUCT_URL"] = chosen["product_link"]
            if chosen["image_url"]:
                # Strip Cylindo features that cause 404s or malformed renders:
                # LENGTH/SEATHEIGHT/PIPING — these add noise or break the CDN URL
                img = chosen["image_url"]
                import re as _re
                img = _re.sub(r'&feature=(?:LENGTH|SEATHEIGHT|SEAT%20HEIGHT|PIPING):[^&]*', '', img)
                p["PRODUCT_IMAGE"] = img
            p["COLOR_CODE"]  = chosen["color_code"]
            p["LIST_PRICE"]  = chosen.get("list_price")
            p["SALE_PRICE"]  = chosen.get("sale_price")
            p["SALE_FROM"]   = chosen.get("sale_from")
            p["SALE_TO"]     = chosen.get("sale_to")
            enriched += 1

    print(f"  Feed enrichment: {enriched}/{total} products matched "
          f"({total - enriched} will use DIM_PRODUCTS fallback); "
          f"{diverse_swaps} color swaps for visual variety")


# ---------------------------------------------------------------------------
# Braze Content Block API
# ---------------------------------------------------------------------------

def _cb_headers() -> Dict[str, str]:
    """Return auth headers for content block API calls.

    Uses BRAZE_CONTENT_BLOCKS_API_KEY_ID if set, otherwise falls back to
    the brand's standard API key. The content blocks key is separate because
    it requires content_blocks.create/update permissions which may not be on
    the main import key.
    """
    import os
    cb_key = os.environ.get("BRAZE_CONTENT_BLOCKS_API_KEY_ID")
    if not cb_key:
        init_config(BRAND)
        cb_key = get_api_key()
    return {"Authorization": f"Bearer {cb_key}", "Content-Type": "application/json"}


def get_existing_blocks() -> Dict[str, str]:
    """Fetch existing Braze Content Block IDs for the ID workspace.

    Returns:
        Dict mapping block name → content_block_id
    """
    init_config(BRAND)
    base_url = get_base_url()

    url = f"{base_url}/content_blocks/list"

    try:
        resp = requests.get(url, headers=_cb_headers(), params={"limit": 1000}, timeout=30)
        resp.raise_for_status()
        blocks = resp.json().get("content_blocks", [])
        return {b["name"]: b["content_block_id"] for b in blocks}
    except Exception as e:
        print(f"  Warning: could not fetch existing content blocks: {e}")
        return {}


def upsert_content_block(
    block_name: str,
    html: str,
    existing_blocks: Dict[str, str],
    dry_run: bool = False,
) -> bool:
    """Create or update a Braze Content Block.

    Uses content_blocks/update if the block already exists (identified by name),
    otherwise calls content_blocks/create.

    Args:
        block_name:      Braze Content Block name (e.g. "recs_sofas")
        html:            HTML body for the content block
        existing_blocks: Dict of name → content_block_id (from get_existing_blocks)
        dry_run:         If True, print HTML instead of calling API

    Returns:
        True on success (or dry-run), False on API error
    """
    if dry_run:
        print(f"\n{'=' * 64}")
        print(f"CONTENT BLOCK: {block_name}")
        print(f"{'=' * 64}")
        # Print a trimmed preview — full HTML goes to Braze, not terminal
        preview = html[:3000] + ("  ...(truncated)" if len(html) > 3000 else "")
        print(preview)
        return True

    init_config(BRAND)
    base_url = get_base_url()

    payload: Dict = {
        "name": block_name,
        "content": html,
        "content_type": "html",
        "state": "active",
    }

    if block_name in existing_blocks:
        payload["content_block_id"] = existing_blocks[block_name]
        endpoint = "content_blocks/update"
        action = "Updating"
    else:
        endpoint = "content_blocks/create"
        action = "Creating"

    print(f"  {action}: {block_name}")
    try:
        resp = requests.post(
            f"{base_url}/{endpoint}",
            headers=_cb_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        print(f"    ERROR: {e}")
        return False

    if "errors" in result:
        print(f"    ERROR: {result['errors']}")
        return False

    block_id = result.get("content_block_id", "unknown")
    print(f"    OK — content_block_id: {block_id}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate ID 'You May Also Like' Braze Content Blocks from Snowflake top sellers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated HTML without pushing to Braze",
    )
    parser.add_argument(
        "--category",
        metavar="MERCH_CLASS",
        help="Only generate block for this MERCH_CLASS (e.g. 'Sofas')",
    )
    parser.add_argument(
        "--save-dir",
        metavar="DIR",
        help="Save each block's HTML to a file in DIR (e.g. /tmp/id_recs_blocks)",
    )
    parser.add_argument(
        "--swatch-color-blocks",
        action="store_true",
        help=(
            "Generate SwatchRec_* color-personalized content blocks "
            "for the swatch post-purchase email (T1/T2)"
        ),
    )
    parser.add_argument(
        "--family",
        metavar="PREFIX",
        help="With --swatch-color-blocks: only generate block for this prefix (e.g. ROY)",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Swatch color blocks mode — separate flow, exits after completion
    # -----------------------------------------------------------------------
    if args.swatch_color_blocks:
        client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")

        existing_blocks: Dict[str, str] = {}
        if not args.dry_run:
            print("Fetching existing Braze content blocks...")
            existing_blocks = get_existing_blocks()
            print(f"  {len(existing_blocks)} existing blocks found")

        mode_label = "Dry run — printing HTML" if args.dry_run else "Generating SwatchRec_* content blocks"
        print(f"\n{mode_label}...")

        success_count, skip_count, error_count = generate_swatch_color_blocks(
            client,
            existing_blocks,
            dry_run=args.dry_run,
            family_filter=args.family,
            save_dir=args.save_dir,
        )

        action_word = "printed" if args.dry_run else "pushed to Braze"
        print(f"\n{'=' * 64}")
        print(
            f"Done. {success_count} SwatchRec blocks {action_word}, "
            f"{skip_count} skipped, {error_count} errors."
        )
        if not args.dry_run and success_count > 0:
            print(
                "\nNext steps:"
                "\n  1. Verify blocks in Braze › Content Blocks (search 'SwatchRec_')"
                "\n  2. Insert the Liquid frequency-counting block into the T1 email in Braze"
                "\n  3. Test in Braze preview with swatches entry property override"
            )
        if error_count > 0:
            sys.exit(1)
        return

    # -----------------------------------------------------------------------
    # 1. Fetch data from Snowflake
    # -----------------------------------------------------------------------
    client = get_snowflake_client(schema="ID_WAREHOUSE", database="PROD")

    products_by_class = fetch_products(client)

    # Collect all base SKUs so the URL lookup can match against them
    all_base_skus = [
        p["SKU"]
        for products in products_by_class.values()
        for p in products
        if p.get("SKU")
    ]
    url_lookup = fetch_url_lookup(client, all_base_skus)

    # URL coverage report (for non-feed products that need event-data URLs)
    total = sum(len(v) for v in products_by_class.values())
    matched = sum(
        1
        for products in products_by_class.values()
        for p in products
        if p.get("SKU") in url_lookup
    )
    pct = matched / max(total, 1) * 100
    print(f"  URL coverage: {matched}/{total} products ({pct:.0f}%) resolved from events")
    if pct < 50:
        print("  NOTE: low URL coverage — slugify fallback active for many products")

    # Enrich upholstered products with marketing names, URLs, and colored images
    print("\nFetching MARKETING_PRODUCT_FEED metadata...")
    feed_meta = fetch_feed_metadata(client)
    enrich_products_from_feed(products_by_class, feed_meta)

    # Fetch any sub-class specific pools needed for cross-sell
    # (e.g. Chairs/Chaise — these don't appear in the main top-16 Chairs pool)
    needed_subclasses = {
        (tc, sf)
        for specs in CROSS_SELL_MAP.values()
        for spec in specs for tc, sf in [(spec[0], spec[1])]
        if sf is not None
    }
    subclass_pool: Dict[str, List[Dict]] = {}
    if needed_subclasses:
        print("\nFetching targeted sub-class pools for cross-sell...")
        for target_class, sub_filter in sorted(needed_subclasses):
            q = SUBCLASS_PRODUCTS_QUERY.replace("{merch_class}", target_class).replace("{merch_sub_class}", sub_filter)
            rows = client.execute_query(q)
            rows = [r for r in rows if (r.get("SKU") or "").strip() not in EXCLUDED_SKUS]
            subclass_pool[f"{target_class}/{sub_filter}"] = rows
            print(f"  {target_class}/{sub_filter}: {len(rows)} products")

    # Build cross-sell lists (uses main pool + subclass overrides)
    cross_sell_by_class = get_cross_sell_products(products_by_class, subclass_pool)

    # Enrich cross-sell items that came from subclass_pool (not yet enriched by feed)
    xs_needing = {
        f"xs_{mc}": [p for p in xs if not p.get("PRODUCT_IMAGE")]
        for mc, xs in cross_sell_by_class.items()
    }
    xs_needing = {k: v for k, v in xs_needing.items() if v}
    if xs_needing:
        print(f"  Enriching {sum(len(v) for v in xs_needing.values())} unenriched cross-sell items from feed...")
        enrich_products_from_feed(xs_needing, feed_meta)

    # Apply active sitewide promo to products not covered by MARKETING_PRODUCT_FEED
    active_promo = fetch_active_promo(client)
    if active_promo:
        n = apply_promo_to_unenriched(products_by_class, active_promo)
        # Also apply to cross-sell items
        n += apply_promo_to_unenriched(
            {k: v for k, v in cross_sell_by_class.items()}, active_promo
        )
        pct = int(active_promo["discount_pct"])
        print(f"  Active promo: {pct}% off (through {active_promo['sale_to'].strftime('%b %d')}) — applied to {n} non-feed products")
    else:
        print("  No active general promo found")

    # -----------------------------------------------------------------------
    # 2. Resolve images + URLs for products NOT covered by MARKETING_PRODUCT_FEED
    #    (Rugs, Art, Lighting, Accent Tables, Dining Tables, Pillows, Benches,
    #     and any upholstered products not in the current feed snapshot)
    # -----------------------------------------------------------------------
    skus_needing_images = [
        p["SKU"]
        for products in products_by_class.values()
        for p in products
        if p.get("SKU") and not p.get("PRODUCT_IMAGE")
    ]
    if skus_needing_images:
        print(f"\nResolving images for {len(skus_needing_images)} non-feed products "
              "(Cylindo for upholstered; Magento GraphQL for everything else)...")
        resolved_images = resolve_all_image_urls(skus_needing_images)

        # Also pull current Magento url_keys for non-upholstered products —
        # event-data URLs (STG_MAPPED_TRACKS, stopped ~Aug 2025) are stale.
        # GraphQL url_key is more reliable and takes priority over event data.
        non_upholstered_needing_urls = [
            s for s in skus_needing_images if not _is_upholstered_sku(s)
        ]
        if non_upholstered_needing_urls:
            print(f"  Fetching GraphQL URLs for {len(non_upholstered_needing_urls)} "
                  "non-upholstered products...")
            graphql_urls = resolve_graphql_url_overrides(non_upholstered_needing_urls)
            overridden = sum(
                1 for sku, url in graphql_urls.items()
                if sku in url_lookup and url_lookup[sku] != url
            )
            new_urls = sum(1 for sku in graphql_urls if sku not in url_lookup)
            url_lookup.update(graphql_urls)
            print(f"  GraphQL URLs: {len(graphql_urls)} resolved "
                  f"({overridden} overriding stale event data, {new_urls} new)")
    else:
        print("\nAll products have feed images — skipping Magento/Cylindo validation.")
        resolved_images = {}

    # -----------------------------------------------------------------------
    # 3. Fetch existing Braze content blocks (skip in dry-run)
    # -----------------------------------------------------------------------
    existing_blocks: Dict[str, str] = {}
    if not args.dry_run:
        print("\nFetching existing Braze content blocks...")
        existing_blocks = get_existing_blocks()
        print(f"  {len(existing_blocks)} existing blocks found")

    # -----------------------------------------------------------------------
    # 4. Generate and push content blocks
    # -----------------------------------------------------------------------
    mode_label = "Dry run — printing HTML" if args.dry_run else "Generating content blocks"
    print(f"\n{mode_label}...")

    # Process known MERCH_CLASSes in defined order; surface any unlisted ones too
    known_classes = list(MERCH_CLASS_TO_BLOCK.keys())
    extra_classes = [c for c in products_by_class if c not in MERCH_CLASS_TO_BLOCK]
    all_classes = known_classes + extra_classes

    success_count = 0
    skip_count = 0
    error_count = 0

    for merch_class in all_classes:
        # Apply --category filter
        if args.category and merch_class.lower() != args.category.lower():
            continue

        products = products_by_class.get(merch_class, [])
        if not products:
            print(f"  Skipping '{merch_class}' — no products in Snowflake data")
            skip_count += 1
            continue

        block_name = MERCH_CLASS_TO_BLOCK.get(
            merch_class,
            f"recs_{merch_class.lower().replace(' ', '_')}",
        )

        # Log product lineup for this class
        print(f"\n{merch_class} ({len(products)} products) → {block_name}")
        for p in products:
            sku = p["SKU"]
            # Use feed-enriched fields when available, fall back to derived values
            dname = p.get("DISPLAY_NAME") or display_name(
                p["NAME"], p.get("MERCH_CLASS", ""),
                p.get("MERCH_SUB_CLASS", "") or "",
                p.get("MATERIAL", "") or "",
            )
            url = p.get("PRODUCT_URL") or product_url(sku, p["NAME"], url_lookup)
            _resolved_img = resolved_images.get(sku)
            img = p.get("PRODUCT_IMAGE") or _resolved_img or cylindo_image_url(sku)
            url_src = "feed " if p.get("PRODUCT_URL") else ("event" if sku in url_lookup else "slug ")
            if p.get("PRODUCT_IMAGE"):
                img_src = "feed "
            elif _resolved_img and "cloudinary.com" in _resolved_img:
                img_src = "cloud"
            elif _resolved_img and "cylindo.com" not in _resolved_img:
                img_src = "gql  "
            elif _resolved_img:
                img_src = "cyl  "
            else:
                img_src = "cdn  "
            color_tag = f"  color={p['COLOR_CODE']}" if p.get("COLOR_CODE") else ""
            price_str = f"${p['PRICE']:,.0f}"
            print(
                f"  [url:{url_src}|img:{img_src}] {dname:<45} {price_str:>8}"
                f"  {p.get('PURCHASE_COUNT', 0):>4} orders{color_tag}"
            )
            print(f"          img: {img}")
            print(f"          url: {url}")

        # Generate HTML
        cross_sell = cross_sell_by_class.get(merch_class, [])
        if cross_sell:
            xs_names = [p.get("DISPLAY_NAME") or p["NAME"] for p in cross_sell]
            print(f"  Cross-sell ({len(cross_sell)}): {', '.join(xs_names)}")

        # Use Liquid randomization if we have a full 10+6 pool; fall back to static otherwise
        if len(products) >= 1 and len(cross_sell) >= 6:
            pool = build_liquid_pool(products[:10], cross_sell[:6])
            html = build_rec_html_liquid(pool, url_lookup, merch_class, resolved_images)
            n_primary = len(pool) - 6
            print(f"  → Liquid block ({n_primary} primary + 6 XS, 7 rotation windows)")
            # Static ts=0 preview: resolve slot indices for ts=0
            slot_arrays = build_slot_arrays_for_n(n_primary)
            ts0_items = [pool[slot_arrays[s][0]] for s in range(6)]
            preview_html = build_rec_html(ts0_items, url_lookup, merch_class, resolved_images)
        else:
            pool = products
            html = build_rec_html(products, url_lookup, merch_class, resolved_images, cross_sell or None)
            preview_html = html
            print(f"  → Static block (fewer than 10+2 products available)")

        # Save HTML to file if --save-dir specified
        if args.save_dir:
            import os
            os.makedirs(args.save_dir, exist_ok=True)
            out_path = os.path.join(args.save_dir, f"{block_name}.html")
            with open(out_path, "w") as _f:
                _f.write(html)
            # Save ts=0 preview alongside the Liquid block
            preview_path = os.path.join(args.save_dir, f"{block_name}_preview_ts0.html")
            with open(preview_path, "w") as _f:
                _f.write(preview_html)

        # Push to Braze (or print in dry-run)
        ok = upsert_content_block(block_name, html, existing_blocks, dry_run=args.dry_run)
        if ok:
            success_count += 1
        else:
            error_count += 1

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    action_word = "printed" if args.dry_run else "pushed to Braze"
    print(f"\n{'=' * 64}")
    print(
        f"Done. {success_count} blocks {action_word}, "
        f"{skip_count} skipped, {error_count} errors."
    )

    if not args.dry_run and success_count > 0:
        print(
            "\nNext steps:"
            "\n  1. Verify blocks in Braze › Content Blocks (search 'recs_')"
            "\n  2. Open 3-5 Cylindo image URLs in browser to confirm they render"
            "\n  3. Add the cart_abandon_module.liquid to the Cart Abandon canvas email step"
        )

    if error_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
