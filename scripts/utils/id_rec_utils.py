#!/usr/bin/env python3
"""
Utilities for Interior Define "You May Also Like" recommendation engine.

Provides:
- cylindo_image_url(sku)        — Cylindo CDN image URL for a given base SKU
- magento_image_url(sku)        — Magento CDN image URL (real product colors)
- resolve_all_image_urls(...)   — validate and return best image per SKU
- slugify(name)                 — fallback URL slug from product name
- product_url(sku, name, ...)   — canonical product page URL (event data or slugify)
- display_name(...)             — specific product name (e.g. "Sloan Fabric 2-Seat Sofa")
- URL_RAW_QUERY                 — SQL to build SKU → URL mapping from STG_MAPPED_TRACKS
- PRODUCTS_QUERY                — SQL for top-selling products per MERCH_CLASS
- EXCLUDED_COLLECTIONS          — set of discontinued collections to filter out
- MERCH_CLASS_TO_BLOCK          — MERCH_CLASS → Braze content block name mapping
- CROSS_SELL_MAP                — post-purchase cross-sell category mapping
- build_rec_html(...)           — generate static HTML content block for a list of products
- build_liquid_pool(...)        — assemble 12-product pool (10 primary + 2 cross-sell) for Liquid
- build_rec_html_liquid(...)    — generate Liquid-randomized HTML block (12-pool → 6 per send)
"""

import os
import re
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Image URL
# ---------------------------------------------------------------------------

def _cloudinary_fetch_url(magento_url: str) -> str:
    """Wrap a Magento CDN URL in Cloudinary's fetch transform.

    Cloudinary proxies and re-serves the image through their CDN, which is
    reachable from Braze's rendering servers (unlike www.interiordefine.com
    which returns gzip-encoded images that Braze's preview can't display).

    Requires CLOUDINARY_CLOUD_NAME in the environment. If not set, returns
    the original URL unchanged.
    """
    cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    if not cloud:
        return magento_url
    return f"https://res.cloudinary.com/{cloud}/image/fetch/{magento_url}"

def magento_image_url(sku: str) -> str:
    """Construct Magento CDN image URL for a product SKU.

    Shows the product in its actual hero color/fabric — matches the default
    display on the product page we link to. Works for ALL product types.

    Args:
        sku: Base product SKU from DIM_PRODUCTS (e.g. "SLON.FABRIC.SOFA.STNDRD")
    """
    slug = sku.lower()
    return (
        f"https://www.interiordefine.com/media/catalog/product/"
        f"{slug[0]}/{slug[1]}/{slug}.jpg"
    )


def cylindo_image_url(sku: str) -> str:
    """Construct Cylindo CDN image URL for a product SKU.

    White-background render, default fabric (may appear gray without color params).
    Used as fallback when Magento CDN returns 404.

    Args:
        sku: Base product SKU from DIM_PRODUCTS (e.g. "SLON.FABRIC.SOFA.STNDRD")
    """
    return (
        f"https://content.cylindo.com/api/v2/4472/products/{sku}/frames/1/"
        f"{sku}.JPG?background=FFFFFF"
    )


# ---------------------------------------------------------------------------
# SKU mapping: DIM_PRODUCTS SKU → Magento parent SKU
# ---------------------------------------------------------------------------
# Some product categories use different SKU formats in the ID warehouse vs
# on the Magento website. This map translates the DIM_PRODUCTS base SKU to
# the Magento configurable-product SKU so that GraphQL image/URL lookups work.
#
# Lighting: DIM_PRODUCTS uses COLLECTION.TYPE.FINISH (e.g. GIDA.FLR.GOLD),
#           Magento stores the parent as a 4-char code (GIDA).
# Rugs:     DIM_PRODUCTS uses COLLECTION.SIZE.COLOR (e.g. GLDI.912.IVORY),
#           Magento stores the parent as a 4-char code (GLDI).
SKU_REMAP: Dict[str, str] = {
    # Lighting
    "GIDA.FLR.GOLD":      "GIDA",
    "LEAH.FLR.BRASS":     "LEAH",
    # Rugs
    "GLDI.912.IVORY":     "GLDI",
    "TAYL.810.GRAY-BLACK": "TAYL",
}


def _fetch_graphql_product_data(
    skus: List[str], timeout: int = 12
) -> Dict[str, Dict[str, str]]:
    """Batch-fetch product image + URL from the Magento GraphQL API.

    Applies SKU_REMAP before querying so products whose DIM_PRODUCTS SKU
    differs from the Magento parent SKU are still resolved correctly.

    Returns a dict of original-SKU → {"img": url, "url": product_url}.
    Only returns entries where at least an image was found.
    """
    import json
    import requests

    # Build mapping: magento_sku → original_sku (for remapped entries)
    magento_to_original: Dict[str, str] = {}
    query_skus: List[str] = []
    for sku in skus:
        magento_sku = SKU_REMAP.get(sku, sku)
        query_skus.append(magento_sku)
        if magento_sku != sku:
            magento_to_original[magento_sku] = sku

    result: Dict[str, Dict[str, str]] = {}
    batch_size = 20
    for i in range(0, len(query_skus), batch_size):
        batch = query_skus[i : i + batch_size]
        sku_filter = ", ".join(f'"{s}"' for s in batch)
        query = json.dumps(
            {
                "query": (
                    f"{{ products(filter: {{sku: {{in: [{sku_filter}]}}}}) "
                    f"{{ items {{ sku url_key image {{ url }} }} }} }}"
                )
            }
        )
        try:
            r = requests.post(
                "https://www.interiordefine.com/graphql",
                data=query,
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
                timeout=timeout,
            )
            items = r.json().get("data", {}).get("products", {}).get("items", [])
            for item in items:
                if item.get("image", {}).get("url"):
                    magento_sku = item["sku"]
                    original_sku = magento_to_original.get(magento_sku, magento_sku)
                    url_key = item.get("url_key", "")
                    result[original_sku] = {
                        "img": item["image"]["url"].split("?")[0],
                        "url": f"https://www.interiordefine.com/{url_key}" if url_key else "",
                    }
        except Exception:
            pass
    return result


def _fetch_graphql_images(skus: List[str], timeout: int = 12) -> Dict[str, str]:
    """Return SKU → image URL for the given SKUs (thin wrapper over _fetch_graphql_product_data)."""
    data = _fetch_graphql_product_data(skus, timeout=timeout)
    return {sku: d["img"] for sku, d in data.items() if d.get("img")}


def resolve_graphql_url_overrides(skus: List[str]) -> Dict[str, str]:
    """Return GraphQL-verified product page URLs for non-upholstered SKUs.

    Used to override stale event-data URLs (STG_MAPPED_TRACKS stopped ~Aug 2025)
    with current Magento url_key values for rugs, tables, lighting, art, etc.

    Upholstered products are skipped — their URLs come from MARKETING_PRODUCT_FEED
    (more specific, with variant/color params already applied).

    Args:
        skus: Base SKU list (all MERCH_CLASSes; upholstered ones are filtered out)

    Returns:
        Dict mapping SKU → canonical product page URL from Magento GraphQL
    """
    non_upholstered = [s for s in skus if not _is_upholstered_sku(s)]
    if not non_upholstered:
        return {}
    data = _fetch_graphql_product_data(non_upholstered)
    return {sku: d["url"] for sku, d in data.items() if d.get("url")}


def _is_upholstered_sku(sku: str) -> bool:
    """Return True if this SKU is an upholstered seating product with a Cylindo render.

    Sofas, sectionals, chairs, ottomans, and beds all have Cylindo white-background
    renders — their .FABRIC. / .LEATHR. SKUs resolve correctly.

    Pillows (.PLLW.) use the same .FABRIC./.LEATHR. naming convention but do NOT
    have Cylindo renders; they need Magento GraphQL images instead.
    """
    if ".PLLW." in sku:
        return False
    return ".FABRIC." in sku or ".LEATHR." in sku


def resolve_all_image_urls(
    skus: List[str],
    max_workers: int = 20,
    timeout: int = 6,
) -> Dict[str, str]:
    """Validate image URLs for a list of SKUs and return the best image per SKU.

    Resolution order (per SKU):
      Upholstered (.FABRIC./.LEATHR. in SKU):
        → Cylindo CDN — white-background render, consistent with feed images
          (used even though GraphQL could provide a Magento image, because mixing
          white and gray-background images in one block looks inconsistent)
      Non-upholstered (rugs, tables, lighting, art, pillows):
        1. Magento GraphQL API — returns the real uploaded image path.
           Applies SKU_REMAP for products whose DIM_PRODUCTS SKU differs from
           the Magento parent SKU (e.g. GIDA.FLR.GOLD → GIDA).
        2. Cylindo CDN fallback — base JPG; will 404 for non-upholstered but
           is kept as a final fallback so the HTML is never missing an src.

    Called once at content-block generation time — results are baked into the
    static HTML so there is no per-send overhead.

    Args:
        skus:        List of base SKU strings to validate.
        max_workers: Unused (kept for API compatibility).
        timeout:     Per-request timeout in seconds.

    Returns:
        Dict mapping SKU → best image URL.
    """
    # Split: upholstered (Cylindo) vs non-upholstered (GraphQL → Cylindo fallback)
    cylindo_skus = [s for s in skus if _is_upholstered_sku(s)]
    gql_skus     = [s for s in skus if not _is_upholstered_sku(s)]

    # GraphQL batch lookup for non-upholstered products
    gql_images: Dict[str, str] = {}
    if gql_skus:
        print(f"  Fetching images via GraphQL for {len(gql_skus)} non-upholstered SKUs...")
        gql_images = _fetch_graphql_images(gql_skus, timeout=12)
        print(f"  GraphQL resolved {len(gql_images)}/{len(gql_skus)} SKUs")

    result: Dict[str, str] = {}
    sources: Dict[str, str] = {}

    for sku in skus:
        if _is_upholstered_sku(sku):
            # Upholstered: always Cylindo for white-background consistency
            result[sku] = cylindo_image_url(sku)
            sources[sku] = "cylindo"
        elif sku in gql_images:
            result[sku] = _cloudinary_fetch_url(gql_images[sku])
            sources[sku] = "graphql" if not os.environ.get("CLOUDINARY_CLOUD_NAME") else "cloudinary"
        else:
            # Cylindo fallback (will 404 for non-upholstered, but is a valid HTML src)
            result[sku] = cylindo_image_url(sku)
            sources[sku] = "cylindo-fallback"

    cyl_count   = sum(1 for s in sources.values() if s == "cylindo")
    gql_count   = sum(1 for s in sources.values() if s == "graphql")
    cdn_count   = sum(1 for s in sources.values() if s == "cloudinary")
    miss_count  = sum(1 for s in sources.values() if s == "cylindo-fallback")
    gql_label   = "GraphQL/Magento (⚠ may fail in Braze preview)" if gql_count and not cdn_count else "GraphQL/Cloudinary"
    print(
        f"  Image sources: {cyl_count} Cylindo (upholstered), "
        f"{gql_count or cdn_count} {gql_label}, {miss_count} Cylindo fallback (may 404)"
    )
    return result


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Generate a URL slug from a product name (fallback when no event URL found)."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


# Manually verified product page URLs for products that have no event data
# (i.e. not in STG_MAPPED_TRACKS and not in MARKETING_PRODUCT_FEED).
# All URLs confirmed via Magento GraphQL url_key field.
MANUAL_URL_OVERRIDES: Dict[str, str] = {
    # Lighting — Magento url_key verified
    "GIDA.FLR.GOLD":      "https://www.interiordefine.com/giada-floor-lamp",
    "LEAH.FLR.BRASS":     "https://www.interiordefine.com/leah-floor-lamp",
    # Rugs — DIM_PRODUCTS uses SIZE.COLOR suffix; Magento parent page is collection-level
    "GLDI.912.IVORY":     "https://www.interiordefine.com/goldie-rug-ivory",
    "TAYL.810.GRAY-BLACK": "https://www.interiordefine.com/taylor-rug",
}


def product_url(sku: str, name: str, url_lookup: Dict[str, str]) -> str:
    """Return the product page URL.

    Priority: manual override → event data lookup → slugify fallback.
    """
    if sku in MANUAL_URL_OVERRIDES:
        return MANUAL_URL_OVERRIDES[sku]
    if sku in url_lookup:
        return url_lookup[sku]
    return f"https://www.interiordefine.com/{slugify(name)}"


# ---------------------------------------------------------------------------
# Display name construction
# ---------------------------------------------------------------------------

# Material code (DIM_PRODUCTS.MATERIAL) → display label
_MATERIAL_LABEL: Dict[str, str] = {
    "Fabric":   "Fabric",
    "Leather":  "Leather",
}

# MERCH_SUB_CLASS → concise display label (only values we want to surface)
_SUB_CLASS_LABEL: Dict[str, str] = {
    "2 Seat":        "2-Seat",
    "3 Seat":        "3-Seat",
    "4 Seat":        "4-Seat",
    "Chaise":        "Chaise",
    "Corner":        "Corner",
    "Accent Regular": "Accent",
    "Swivel":        "Swivel",
    # Lighting
    "Floor Lamp":    "Floor Lamp",
    "Table Lamp":    "Table Lamp",
    "Chandelier":    "Chandelier",
    "Pendants":      "Pendant",
    # Tables
    "Coffee":        "Coffee",
    "Side":          "Side",
    "Dining":        "Dining",
}

# MERCH_CLASS → singular type label appended at the end
# Empty string = names are already type-specific, no suffix needed
_MERCH_CLASS_SINGULAR: Dict[str, str] = {
    "Sofas":          "Sofa",
    "Sectionals":     "Sectional",
    "Chairs":         "Chair",
    "Ottomans":       "Ottoman",
    "Dining Seating": "",    # "Hollis Chair", "Dorian Banquette" already specific
    "Dining Tables":  "Dining Table",
    "Beds":           "Bed",
    "Accent Tables":  "Table",
    "Lighting":       "",    # sub_class handles it ("Floor Lamp", "Chandelier")
    "Rugs":           "",    # names already include size
    "Art":            "",    # names already fully descriptive
    "Pillows":        "Pillow",
    "Benches":        "",    # names already include "Bench"
}


def display_name(
    name: str,
    merch_class: str,
    merch_sub_class: str = "",
    material: str = "",
) -> str:
    """Build a specific product display name from DIM_PRODUCTS fields.

    Constructs names like "Sloan Fabric 2-Seat Sofa", "Maxwell Fabric Accent
    Chair", "Giada Floor Lamp" by appending material, sub-class, and product
    type to the bare collection name — but only when they aren't already present.

    Args:
        name:            DIM_PRODUCTS.NAME (e.g. "Sloan")
        merch_class:     DIM_PRODUCTS.MERCH_CLASS (e.g. "Sofas")
        merch_sub_class: DIM_PRODUCTS.MERCH_SUB_CLASS (e.g. "2 Seat")
        material:        DIM_PRODUCTS.MATERIAL (e.g. "Fabric")

    Returns:
        Display name suitable for a product card
    """
    parts = [name]
    name_lower = name.lower()

    # 1. Material (Fabric / Leather) — only for upholstered products
    mat_label = _MATERIAL_LABEL.get(material or "", "")
    if mat_label and mat_label.lower() not in name_lower:
        parts.append(mat_label)

    # 2. Sub-class descriptor (e.g. "2-Seat", "Chaise", "Floor Lamp")
    sub_label = _SUB_CLASS_LABEL.get(merch_sub_class or "", "")
    if sub_label:
        # Don't append if any word from it is already in what we've built so far
        built_lower = " ".join(parts).lower()
        sub_words = {w.lower() for w in sub_label.split()}
        built_words = set(re.sub(r"[^a-z ]", " ", built_lower).split())
        if not (sub_words & built_words):
            parts.append(sub_label)

    # 3. Product type suffix (e.g. "Sofa", "Chair", "Sectional")
    type_label = _MERCH_CLASS_SINGULAR.get(merch_class, "")
    if type_label:
        built_lower = " ".join(parts).lower()
        type_words = {w.lower() for w in type_label.split()}
        built_words = set(re.sub(r"[^a-z ]", " ", built_lower).split())
        if not (type_words & built_words):
            parts.append(type_label)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Snowflake queries
# ---------------------------------------------------------------------------

FEED_METADATA_QUERY = """
-- Fetch all distinct color variants (name, URL, image) from MARKETING_PRODUCT_FEED.
--
-- PROMO_ROW_NUMBER = 1 is a flag meaning "this variant is actively promoted in
-- Google/Facebook ads" — it applies to every promoted color, not a single row.
-- We group by (ITEM_GROUP_ID, color_code) to get one representative row per
-- color, ranked by how frequently that color appears in the feed (a proxy for
-- how prominently it is promoted).
--
-- IMAGE_LINK and LINK are kept from the SAME source row so they always match —
-- clicking the email link opens the product in the exact color shown in the image.
--
-- LINK is used as-is (with variant params) so clicking opens the product pre-
-- configured to the color variant shown in the image.
--
-- " Custom" is stripped from the product name because the website product page
-- titles omit it (e.g. "Sloan 3-Seat Sofa", not "Sloan Custom 3-Seat Sofa").
--
-- Returns multiple rows per ITEM_GROUP_ID (one per color), ordered by frequency
-- DESC so the most-promoted color comes first. Python picks from this list to
-- maximize visual diversity across the recommendation grid.
--
-- Only covers configurable upholstered products. Non-upholstered categories
-- (rugs, tables, art, lighting) are not in this feed.
WITH base AS (
    SELECT
        ITEM_GROUP_ID                                                           AS base_sku,
        REPLACE(SPLIT_PART(TITLE, ' in ', 1), ' Custom', '')                   AS product_name,
        LINK                                                                    AS product_link,
        IMAGE_LINK                                                              AS image_url,
        REGEXP_SUBSTR(IMAGE_LINK, 'feature=COLOR:([^&%]+)', 1, 1, 'e', 1)      AS color_code,
        PRICE                                                                   AS list_price,
        SALE_PRICE                                                              AS sale_price,
        SALE_PRICE_EFFECTIVE_DATE_FROM                                          AS sale_from,
        SALE_PRICE_EFFECTIVE_DATE_TO                                            AS sale_to
    FROM PROD.ID_WAREHOUSE.MARKETING_PRODUCT_FEED
    WHERE STATUS = 'Active'
        AND AVAILABILITY = 'in_stock'
        AND PROMO_ROW_NUMBER = 1
),
color_freq AS (
    SELECT base_sku, color_code, COUNT(*) AS freq
    FROM base
    GROUP BY 1, 2
)
SELECT b.base_sku, b.product_name, b.product_link, b.image_url, b.color_code, cf.freq,
       b.list_price, b.sale_price, b.sale_from, b.sale_to
FROM base b
JOIN color_freq cf ON b.base_sku = cf.base_sku AND b.color_code = cf.color_code
QUALIFY ROW_NUMBER() OVER (
    -- Order by LINK (stable identifier) so IMAGE_LINK and LINK come from the
    -- same row — avoids mismatched image/URL from lexicographic URL sorting
    PARTITION BY b.base_sku, b.color_code
    ORDER BY cf.freq DESC, b.product_link
) = 1
ORDER BY b.base_sku, cf.freq DESC
"""

URL_RAW_QUERY = """
-- Extract (variant_sku, clean_url, received_at) from Product Viewed events.
--
-- No join to DIM_PRODUCTS — that times out on 61M rows with a LIKE predicate.
-- Instead, fetch all distinct pairs and prefix-match in Python (build_url_lookup).
--
-- RECEIVED_AT is returned so build_url_lookup can pick the most recently viewed
-- variant among all variants sharing a base-SKU prefix — avoids stale URLs like
-- /sloan-custom-sofa-1 when /sloan-custom-sofa is more recent.
--
-- No date filter: STG_MAPPED_TRACKS stopped ~Aug 2025 (Fivetran stale).
SELECT
    REGEXP_SUBSTR(URL, '[?&]sku=([^&]+)', 1, 1, 'e', 1) AS variant_sku,
    SPLIT_PART(URL, '?', 1)                               AS clean_url,
    RECEIVED_AT
FROM PROD.ID_WAREHOUSE.STG_MAPPED_TRACKS
WHERE EVENT = 'product_viewed'
    AND URL LIKE '%sku=%'
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY REGEXP_SUBSTR(URL, '[?&]sku=([^&]+)', 1, 1, 'e', 1)
    ORDER BY RECEIVED_AT DESC
) = 1
"""


def build_url_lookup(raw_rows: list, base_skus: list) -> Dict[str, str]:
    """Match variant SKUs (from event URLs) to base SKUs (from DIM_PRODUCTS).

    Scans all variant SKUs sharing a base-SKU prefix and picks the URL from
    the most recently viewed variant. This avoids stale URLs that come from
    alphabetically-first variants that were renamed (e.g. /sloan-custom-sofa-1).

    Args:
        raw_rows:  List of dicts with VARIANT_SKU, CLEAN_URL, RECEIVED_AT keys.
        base_skus: List of base SKU strings from DIM_PRODUCTS.

    Returns:
        Dict mapping base_sku → clean product page URL.
    """
    import bisect

    entries = sorted(
        [
            (row["VARIANT_SKU"], row["CLEAN_URL"], row.get("RECEIVED_AT"))
            for row in raw_rows
            if row.get("VARIANT_SKU") and row.get("CLEAN_URL")
        ],
        key=lambda x: x[0],
    )
    if not entries:
        return {}

    variant_skus = [e[0] for e in entries]
    lookup: Dict[str, str] = {}

    for base_sku in base_skus:
        if not base_sku:
            continue
        idx = bisect.bisect_left(variant_skus, base_sku)
        best_url: Optional[str] = None
        best_at = None
        while idx < len(variant_skus) and variant_skus[idx].startswith(base_sku):
            _, url, at = entries[idx]
            if best_at is None or (at is not None and at > best_at):
                best_url = url
                best_at = at
            idx += 1
        if best_url:
            lookup[base_sku] = best_url

    return lookup


SUBCLASS_PRODUCTS_QUERY = """
-- Top N revenue-weighted products for a specific MERCH_CLASS + MERCH_SUB_CLASS.
-- Used to fetch cross-sell items (e.g. Chairs/Chaise) that don't appear in the
-- main PRODUCTS_QUERY top-16 pool. Same dedup and revenue logic.
-- Replace {merch_class} and {merch_sub_class} before executing.
WITH purchase_stats AS (
    SELECT
        p.NAME, p.SKU, p.COLLECTION, p.MERCH_CLASS, p.MERCH_SUB_CLASS,
        p.MATERIAL, p.PRICE,
        COUNT(soi.PRODUCT_WID)           AS purchase_count,
        COUNT(soi.PRODUCT_WID) * p.PRICE AS revenue_score
    FROM PROD.ID_WAREHOUSE.DIM_PRODUCTS p
    LEFT JOIN PROD.ID_WAREHOUSE.FACT_SALES_ORDER_ITEMS soi ON soi.PRODUCT_WID = p.WID
    WHERE p.STATUS = 1
        AND p.MERCH_CLASS = '{merch_class}'
        AND p.MERCH_SUB_CLASS = '{merch_sub_class}'
        AND p.PRICE > 0
    GROUP BY 1, 2, 3, 4, 5, 6, 7
)
SELECT NAME, SKU, COLLECTION, MERCH_CLASS, MERCH_SUB_CLASS, MATERIAL, PRICE,
       purchase_count, revenue_score
FROM purchase_stats
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COLLECTION, MATERIAL ORDER BY revenue_score DESC
) = 1
ORDER BY revenue_score DESC
LIMIT 20
"""

PRODUCTS_QUERY = """
-- Top 12 revenue-weighted products per MERCH_CLASS from DIM_PRODUCTS.
-- (Fetches 12 so Python can apply preferences and still get 6.)
--
-- Revenue score = purchase_count × catalog price.
-- Collection+material dedup: max 1 SKU per (MERCH_CLASS, COLLECTION, MATERIAL)
-- so that leather and fabric variants of the same design both remain candidates.
-- Joins FACT_SALES_ORDER_ITEMS → DIM_PRODUCTS via PRODUCT_WID = WID.
WITH purchase_stats AS (
    SELECT
        p.NAME,
        p.SKU,
        p.COBAIN_PRODUCT_ID,
        p.WID,
        p.COLLECTION,
        p.MERCH_CLASS,
        p.MERCH_SUB_CLASS,
        p.MATERIAL,
        p.PRICE,
        COUNT(soi.PRODUCT_WID)           AS purchase_count,
        COUNT(soi.PRODUCT_WID) * p.PRICE AS revenue_score
    FROM PROD.ID_WAREHOUSE.DIM_PRODUCTS p
    LEFT JOIN PROD.ID_WAREHOUSE.FACT_SALES_ORDER_ITEMS soi
        ON soi.PRODUCT_WID = p.WID
    WHERE p.STATUS = 1
        AND p.MERCH_CLASS IS NOT NULL
        AND p.PRICE > 0
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
),
one_per_collection_material AS (
    SELECT *,
        ROW_NUMBER() OVER (
            -- Dedup logic: at most one product per (MERCH_CLASS, collection-key,
            -- MATERIAL) in the candidate pool, where collection-key varies by class:
            --
            -- Sofas:      partition by COLLECTION + MATERIAL + seat-size tier so
            --             both a 3-seat and a non-3-seat of the same design can
            --             appear. Python apply_sofa_preferences picks the final 6.
            --
            -- Case Goods: partition by SKU directly (all nightstands share the same
            --             COLLECTION and MERCH_SUB_CLASS, so SKU is the only way to
            --             allow multiple variants from the same collection, e.g.
            --             Leta One Drawer and Leta Two Drawer both appearing).
            --
            -- All others: partition by COLLECTION + MATERIAL (standard dedup).
            PARTITION BY MERCH_CLASS,
                CASE
                    WHEN MERCH_CLASS = 'Case Goods' THEN SKU
                    ELSE COLLECTION
                END,
                MATERIAL,
                CASE WHEN MERCH_SUB_CLASS = '3 Seat' THEN '3seat' ELSE 'other' END
            ORDER BY revenue_score DESC
        ) AS coll_rank
    FROM purchase_stats
)
SELECT NAME, SKU, COBAIN_PRODUCT_ID, COLLECTION, MERCH_CLASS, MERCH_SUB_CLASS,
       MATERIAL, PRICE, purchase_count, revenue_score
FROM one_per_collection_material
WHERE coll_rank = 1
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY MERCH_CLASS ORDER BY revenue_score DESC
) <= 16
ORDER BY MERCH_CLASS, revenue_score DESC
"""


# Collections that are no longer active on interiordefine.com.
# Products from these collections are excluded even if STATUS=1 in DIM_PRODUCTS.
# Add to this set when collections are discontinued.
EXCLUDED_COLLECTIONS: set = {
    "Jason",   # Jason by Jason Wu — discontinued
}

# Individual SKUs to exclude from recommendations regardless of collection.
# Use for accessories/add-ons that rank highly by volume but aren't aspirational,
# or products whose URLs/images can't be resolved (not in Magento catalog).
EXCLUDED_SKUS: set = {
    # Accessories
    "RGPD.810",              # Rug Pad 8x10 — accessory, not a featured product
    "RGPD.912",              # Rug Pad 9x12 — accessory
    "RGPD.57",               # Rug Pad 5x7 — accessory
    # Accent tables — STATUS=1 in DIM_PRODUCTS but not in Magento catalog;
    # URLs from event data are stale and images are unavailable (Cylindo 404)
    "DEV.TBL.COFF.OIL-WAL",  # Devon Coffee Table Oiled Walnut
    "BRO.TBL.COFF.NAT-OAK",  # Brooks Coffee Table Natural Oak
    "LIN.TBL.COFF.OIL-WAL",  # Linden Coffee Table Oiled Walnut
    "GLMR.TBL.COFF.WHITE",   # Gilmore Coffee Table White
    # Side tables not in Magento (verified via GraphQL)
    "REE.TBL.SIDE.BLA-OAK",  # Reese Side Table Black Oak
    "GRE.TBL.SIDE.NAT-OAK",  # Greer Side Table Natural Oak
    "NIC.TBL.SIDE.NAT-OAK",  # Nico Side Table Natural Oak
    "DEV.TBL.SIDE.OIL-WAL",  # Devon Side Table Oiled Walnut
    "FNKI.TBL.SIDE.BLACK",   # Frankie Side Table Black
    "LIN.TBL.SIDE.NAT-OAK",  # Linden Side Table Natural Oak
    "PRES.TBL.SIDE.WHITE",   # Preston Side Table White
    "TYR.TBL.SIDE.GRY",      # Thayer Side Table Gray
    # Lighting — not in Magento catalog, bad link
    "HNNA.CHND.BRASS",       # Hanna Brass Chandelier
    # Pillows — custom-fabric throw pillows not in Magento pillow catalog
    "CHES.FABRIC.PLLW.LARGER",  # Ms. Chesterfield Fabric Pillow
    "CHES.LEATHR.PLLW.LARGER",  # Ms. Chesterfield Leather Pillow
    "MXWL.FABRIC.PLLW.LUMBAR",  # Maxwell Fabric Pillow — not in Magento catalog
    "CAIT.FABRIC.PLLW.LUMBAR",  # Caitlin Fabric Pillow — not in Magento catalog
    "ELLA.FABRIC.PLLW.LUMBAR",  # Ella Fabric Pillow — not in Magento catalog
    "JMES.FABRIC.PLLW.18x18",   # James Throw Pillow — not in Magento catalog
    "POET.THRW.FABRIC.PLLW.22X22.SAND",  # Poeta Sand Pillow — not in Magento
    "LOLA.THRW.FABRIC.PLLW.20X20.ECRU",  # Lola Pillow — not in Magento
    # Rugs — not resolvable via Magento GraphQL (SKU not in catalog)
    "ELOD.7696.LINEN",   # Elodie 7'6" x 9'6" Linen & Coral — not in Magento
    # Dining Seating — Cylindo 404 (stool not in Cylindo CDN)
    "HLIS.LEATHR.DINING.STOOL",  # Hollis Leather Counter Stool — Cylindo 404
}


# ---------------------------------------------------------------------------
# Braze Content Block naming
# ---------------------------------------------------------------------------

MERCH_CLASS_TO_BLOCK: Dict[str, str] = {
    "Sofas":          "recs_sofas",
    "Sectionals":     "recs_sectionals",
    "Chairs":         "recs_chairs",
    "Ottomans":       "recs_ottomans",
    "Rugs":           "recs_rugs",
    "Dining Seating": "recs_dining_seating",
    "Dining Tables":  "recs_dining_tables",
    "Beds":           "recs_beds",
    "Accent Tables":  "recs_accent_tables",
    "Lighting":       "recs_lighting",
    "Art":            "recs_art",
    "Pillows":        "recs_pillows",
    "Benches":        "recs_benches",
    "Case Goods":     "recs_nightstands",
}

# Cross-sell specs: list of (target_class, sub_class_filter, count).
# sub_class_filter=None means any sub_class.
# 2 cross-sell items are mixed into slots 3-6, weighted toward the end.
CROSS_SELL_MAP: Dict[str, List] = {
    "Sofas":          [("Sectionals", None, 3),      ("Sectionals", "Bumper", 3)],
    "Sectionals":     [("Sofas", None, 6)],
    "Chairs":         [("Sofas", None, 3),           ("Rugs", None, 3)],
    "Ottomans":       [("Rugs", None, 6)],
    "Beds":           [("Benches", None, 3),          ("Chairs", "Chaise", 3)],
    "Rugs":           [("Sofas", None, 6)],
    "Dining Tables":  [("Dining Seating", None, 6)],
    "Dining Seating": [("Dining Tables", None, 6)],
    "Accent Tables":  [("Sofas", None, 6)],
    "Lighting":       [("Chairs", None, 6)],
    "Art":            [("Lighting", None, 6, "price")],
    "Pillows":        [("Sofas", None, 6)],
    "Benches":        [("Beds", None, 6)],
    "Case Goods":     [("Beds", None, 6)],
}


def get_cross_sell_products(
    products_by_class: Dict[str, List[Dict]],
    subclass_pool: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, List[Dict]]:
    """Build per-class cross-sell lists from already-fetched product data.

    Uses CROSS_SELL_MAP to pick up to 2 cross-sell candidates per class.
    Deduplicates by SKU both within the cross-sell list and against the
    primary pool so the same product never appears twice in one block.

    Returns:
        Dict mapping primary MERCH_CLASS → list of cross-sell product dicts.
    """
    result: Dict[str, List[Dict]] = {}
    for primary_class, specs in CROSS_SELL_MAP.items():
        primary_skus = {p["SKU"] for p in products_by_class.get(primary_class, [])}
        seen: set = set()
        xs: List[Dict] = []
        for spec in specs:
            target_class, sub_filter, count = spec[0], spec[1], spec[2]
            sort_by = spec[3] if len(spec) > 3 else None
            # For sub-class filtered specs, prefer the dedicated subclass_pool
            # (fetched by a targeted query) over the main pool which may not
            # include low-revenue sub-classes like Chairs/Chaise.
            if sub_filter and subclass_pool:
                pool_key = f"{target_class}/{sub_filter}"
                candidates = subclass_pool.get(pool_key, [])
            else:
                candidates = products_by_class.get(target_class, [])
                if sub_filter:
                    candidates = [
                        p for p in candidates
                        if (p.get("MERCH_SUB_CLASS") or "").strip() == sub_filter
                    ]
            if sort_by == "price":
                candidates = sorted(candidates, key=lambda p: float(p.get("PRICE") or 0), reverse=True)
            added = 0
            for p in candidates:
                if added >= count:
                    break
                sku = p["SKU"]
                if sku not in primary_skus and sku not in seen:
                    seen.add(sku)
                    xs.append(p)
                    added += 1
        result[primary_class] = xs
    return result


def _mix_products(primary: List[Dict], cross_sell: List[Dict]) -> List[Dict]:
    """Mix 4 primary + 2 cross-sell into 6 slots.

    Slots 0, 1 always primary. The remaining 4 slots (2-5) contain 2 primary
    and 2 cross-sell items, with cross-sell weighted toward the end.
    Placement is deterministic (seeded by the first two primary SKUs) so the
    same block always renders identically.

    Cross-sell slot patterns (positions within slots 2-5):
      60%  → [4, 5]  — both cross-sell items in the final two slots
      20%  → [3, 5]  — interleaved: one mid-block, one last
      20%  → [3, 4]  — both in the second half but not the very end
    """
    import hashlib

    result: List[Dict] = [None] * 6  # type: ignore
    result[0] = primary[0]
    result[1] = primary[1]

    seed = (primary[0].get("SKU", "") + primary[1].get("SKU", "")).encode()
    h = int(hashlib.md5(seed).hexdigest(), 16) % 5

    # xs_positions: which of slots 2-5 get cross-sell items
    if h == 0:    # slot 3, slot 6  — one mid, one at end
        xs_positions = {3, 5}
    elif h == 1:  # slot 3, slot 5  — together in back half of row 2
        xs_positions = {3, 4}
    elif h == 2:  # slot 3, slot 4  — one in each row, spread
        xs_positions = {2, 4}
    elif h == 3:  # slot 4, slot 6  — spread, one early row 2
        xs_positions = {2, 5}
    else:         # slot 3, slot 5  — same as h==0
        xs_positions = {3, 5}

    xi = 0
    pi = 2
    for pos in range(2, 6):
        if pos in xs_positions and xi < len(cross_sell):
            result[pos] = cross_sell[xi]
            xi += 1
        else:
            if pi < len(primary):
                result[pos] = primary[pi]
                pi += 1

    return [p for p in result if p is not None]


# ---------------------------------------------------------------------------
# Color diversity helpers
# ---------------------------------------------------------------------------

# Color code prefix → visual family name.
# Codes from MARKETING_PRODUCT_FEED IMAGE_LINK feature=COLOR params.
# Products sharing the same family look visually similar in email thumbnails.
_COLOR_FAMILY: Dict[str, str] = {
    "LNL": "linen",        # Natural Linen (warm tan/cream) — most common neutral
    "CAS": "classic",      # Classic Weave (warm neutral — bisque, cove, truffle)
    "AM":  "loop",         # Loop Weave performance (gray spectrum)
    "ROY": "royal",        # Royal performance (varied — blues, greens, warm tones)
    "SE":  "stain",        # Stain-Ease (varied textures)
    "COV": "cove",         # Cove performance weave
    "MER": "merit",        # Merit/Merit (varied)
    "AK":  "velvet",       # Mod Velvet (bold colors — blue, blush, greige)
    "BI":  "bisque",       # Bisque family
    "PD":  "pattern",      # Patterned
    "GIA": "gia",          # Gia family
    "HRT": "hart",         # Hart family
    "HS":  "heritage",     # Heritage Stitch
    "DC":  "deep",         # Deep Clean
    "LTHR": "leather",     # Leather
}


# Manual color overrides: force a specific color variant for a given base SKU.
# Useful when the auto-selected color is too similar to a neighbor in the block,
# or when a specific color is preferred for brand reasons.
# Format: { base_sku: color_code }
MANUAL_COLOR_OVERRIDES: Dict[str, str] = {
    "ELLA.FABRIC.SOFA.3SEAT":      "ROY-010",  # Celadon — distinct from adjacent ANG/COV
    "CHES.LEATHR.SOFA.STNDRD":    "LTHR-01",  # Cognac Pigment-Dyed Leather
}


# Color families/codes that render as too light (white/cream) or too dark
# (near-black) — deprioritized in favor of bolder, more visually distinct
# options.  Only used as a last resort once all other families are exhausted.
#
# Family names are derived by color_family() (e.g. color_family("8519A") →
# "8519a"), so numeric leather codes are listed in lowercase here.
_PREFER_LAST_FAMILIES: set = {
    # Light / neutral — wash out against white background
    "gia", "linen", "bisque",
    # Near-black leather codes — hard to read at thumbnail size
    "8519a",   # Pecan Pigment-Dyed Leather (very dark brown)
}


def color_family(color_code: str) -> str:
    """Return the visual family for a Cylindo color code (e.g. 'LNL-001' → 'linen').

    Used to detect when multiple products in the same recommendation block share
    a similar-looking color, so we can swap in a visually distinct alternative.
    """
    if not color_code:
        return "unknown"
    prefix = re.split(r"[-_]", color_code)[0].upper()
    return _COLOR_FAMILY.get(prefix, prefix.lower())


# ---------------------------------------------------------------------------
# Sofa-specific selection preferences
# ---------------------------------------------------------------------------

def apply_sofa_preferences(products: List[Dict]) -> List[Dict]:
    """Select 10 sofas: ~7 three-seaters, 2 two-seaters, 1 leather — no duplicate collections.

    Slot allocation (filled greedily, skipping any SKU already used):
      Slots 1-7:  best 3-seat fabric sofas by revenue
      Slots 8-9:  best non-3-seat fabric sofas from new collections
      Slot 10:    best leather sofa (3-seat preferred) from a new collection

    If fewer than 7 three-seat fabric options exist, non-3-seat fabric fills the gap.
    If no leather is available, slot 10 goes to the next best fabric sofa.

    Args:
        products: Candidate pool of up to 16 sofa product dicts from Snowflake.
                  Should include both 3-seat and non-3-seat variants per collection
                  (requires PRODUCTS_QUERY to partition by seat-size tier).

    Returns:
        Up to 10 selected products in display order.
    """
    rev = lambda p: -(p.get("revenue_score") or 0)

    is_leather = lambda p: (p.get("MATERIAL") or "").strip() == "Leather"
    is_3seat   = lambda p: (p.get("MERCH_SUB_CLASS") or "").strip() == "3 Seat"

    three_fabric = sorted([p for p in products if     is_3seat(p) and not is_leather(p)], key=rev)
    other_fabric = sorted([p for p in products if not is_3seat(p) and not is_leather(p)], key=rev)
    leather_3    = sorted([p for p in products if     is_3seat(p) and     is_leather(p)], key=rev)
    leather_2    = sorted([p for p in products if not is_3seat(p) and     is_leather(p)], key=rev)

    result: List[Dict] = []
    seen_skus: set = set()

    def add(p: Dict) -> bool:
        sku = (p.get("SKU") or "").strip()
        if sku not in seen_skus:
            result.append(p)
            seen_skus.add(sku)
            return True
        return False

    # Slots 1-7: three-seat fabric
    for p in three_fabric:
        if len(result) >= 7:
            break
        add(p)

    # Slots 8-9: non-3-seat fabric (two-seaters for variety)
    for p in other_fabric:
        if len(result) >= 9:
            break
        add(p)

    # Fill any remaining fabric slots if we didn't have enough candidates
    for p in three_fabric + other_fabric:
        if len(result) >= 9:
            break
        add(p)

    # Slot 10: leather (3-seat preferred, then 2-seat)
    for p in leather_3 + leather_2:
        if add(p):
            break

    # If no leather available, fill with next best fabric
    if len(result) < 10:
        for p in three_fabric + other_fabric:
            if len(result) >= 10:
                break
            add(p)

    return result[:10]


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _price_html(product: Dict) -> str:
    """Return a price line for a product card, with strikethrough if on sale.

    Uses LIST_PRICE / SALE_PRICE / SALE_FROM / SALE_TO stamped by
    enrich_products_from_feed. Falls back to DIM_PRODUCTS PRICE if no
    feed price is available. Returns empty string if no price data.
    """
    from datetime import datetime, timezone

    list_price = product.get("LIST_PRICE") or product.get("PRICE")
    sale_price = product.get("SALE_PRICE")
    sale_from  = product.get("SALE_FROM")
    sale_to    = product.get("SALE_TO")

    if not list_price or list_price <= 0:
        return ""

    now = datetime.now(timezone.utc)
    # Make sale_from/sale_to timezone-aware if they aren't already
    def _tz(dt):
        if dt is None:
            return None
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    is_on_sale = bool(
        sale_price
        and sale_from
        and sale_to
        and _tz(sale_from) <= now <= _tz(sale_to)
    )

    style = 'font-family:Arial,Helvetica,sans-serif;font-size:11px;margin:2px 0 0;line-height:1.4;'
    if is_on_sale:
        return (
            f'              <p style="{style}">'
            f'<span style="color:#999;text-decoration:line-through;">'
            f'${list_price:,.0f}</span>'
            f'&nbsp;<span style="color:#b8392a;font-weight:700;">'
            f'${sale_price:,.0f}</span></p>\n'
        )
    return (
        f'              <p style="{style}color:#1a1a1a;">'
        f'${list_price:,.0f}</p>\n'
    )


def _card_html(
    product: Dict,
    url_lookup: Dict[str, str],
    resolved_images: Dict[str, str],
) -> str:
    """Generate HTML for a single product card (190px wide).

    Expects dict keys in uppercase (Snowflake DictCursor convention).

    Feed-enriched fields (set by enrich_products_from_feed in the main script):
      DISPLAY_NAME  — full marketing name from MARKETING_PRODUCT_FEED
      PRODUCT_URL   — product page URL with color variant params
      PRODUCT_IMAGE — Cylindo URL with color params (renders in actual color)
      LIST_PRICE    — regular price for this variant
      SALE_PRICE    — sale price (shown with strikethrough if currently active)

    Falls back to display_name() / product_url() / resolved_images / DIM_PRODUCTS
    PRICE for products not in the feed (Rugs, Art, Lighting, etc.).
    """
    sku = product["SKU"]
    raw_name = product["NAME"]
    merch_class = product.get("MERCH_CLASS", "")
    merch_sub_class = product.get("MERCH_SUB_CLASS", "") or ""
    material = product.get("MATERIAL", "") or ""

    # Prefer feed-enriched values; fall back to derived values
    name = (
        product.get("DISPLAY_NAME")
        or display_name(raw_name, merch_class, merch_sub_class, material)
    )
    img_url = (
        product.get("PRODUCT_IMAGE")
        or resolved_images.get(sku)
        or (cylindo_image_url(sku) if _is_upholstered_sku(sku) else magento_image_url(sku))
    )
    # Cylindo feature param names can contain spaces (e.g. "SEAT HEIGHT") which
    # break HTML src attributes. Encode spaces before writing into HTML.
    img_url = img_url.replace(" ", "%20")
    url = product.get("PRODUCT_URL") or product_url(sku, raw_name, url_lookup)
    safe_name = name.replace('"', "&quot;").replace("&", "&amp;")

    return (
        '          <td valign="top" style="padding:6px 5px;width:190px;">\n'
        f'            <a href="{url}" style="text-decoration:none;color:inherit;">\n'
        f'              <img src="{img_url}" alt="{safe_name}" width="190"\n'
        '                   style="display:block;width:190px;height:190px;'
        'object-fit:contain;background:#ffffff;" />\n'
        f'              <p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        f'color:#1a1a1a;margin:8px 0 2px;line-height:1.4;text-align:center;">{name}</p>\n'
        '            </a>\n'
        '          </td>'
    )


def _empty_cell_html() -> str:
    """Invisible spacer cell — pads rows with fewer than 3 products."""
    return '          <td valign="top" style="padding:6px 5px;width:190px;"></td>'


def build_rec_html(
    products: List[Dict],
    url_lookup: Dict[str, str],
    merch_class: str,
    resolved_images: Optional[Dict[str, str]] = None,
    cross_sell_products: Optional[List[Dict]] = None,
) -> str:
    """Build the full 'You May Also Like' HTML content block for a MERCH_CLASS."""
    if not products:
        return ""

    if cross_sell_products and len(products) >= 4 and len(cross_sell_products) >= 2:
        display = _mix_products(products[:4], cross_sell_products[:2])
    else:
        display = products[:6]

    rows = [display[i : i + 3] for i in range(0, len(display), 3)]

    imgs = resolved_images or {}
    rows_html_parts = []
    for row in rows:
        cells = [_card_html(p, url_lookup, imgs) for p in row]
        while len(cells) < 3:
            cells.append(_empty_cell_html())
        rows_html_parts.append(
            "        <tr>\n" + "\n".join(cells) + "\n        </tr>"
        )

    rows_html = "\n".join(rows_html_parts)
    block_slug = merch_class.lower().replace(" ", "_")
    xs_count = len(cross_sell_products or [])

    return f"""<!-- id_recs_{block_slug} — {len(display)} products ({xs_count} cross-sell) — auto-generated by id_recommendation_blocks.py -->
<table width="600" cellpadding="0" cellspacing="0" border="0"
  style="border-collapse:collapse;margin:0 auto;">
  <tr>
    <td align="center" style="padding:28px 0 12px;">
      <p style="font-family:Georgia,Arial,sans-serif;font-size:18px;
                font-weight:400;color:#2e3c47;margin:0;">You May Also Like</p>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding:0 15px 28px;">
      <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
{rows_html}
      </table>
    </td>
  </tr>
</table>"""


_XS_PAIRS    = [(0,1),(2,3),(4,5),(0,2),(1,4),(3,5),(0,3)]
_XS_SLOT_POS = [(2,3),(2,4),(2,5),(3,4),(3,5),(4,5),(2,3)]


def build_slot_arrays_for_n(n_primary: int) -> List[List[int]]:
    """Build dedup-safe 6×7 slot arrays for a pool with n_primary primary items.

    For n_primary >= 10 returns the pre-validated _LIQUID_SLOT_ARRAYS unchanged.
    For smaller pools generates arrays where no window (column) contains
    duplicate indices. XS items occupy indices n_primary..n_primary+5.
    Rows 0 and 1 always reference primary indices.
    """
    if n_primary >= 10:
        return _LIQUID_SLOT_ARRAYS

    xs_base = n_primary
    arrays: List[List[int]] = [[] for _ in range(6)]

    for ts in range(7):
        xa, xb   = _XS_PAIRS[ts]
        xp1, xp2 = _XS_SLOT_POS[ts]
        prim_slots = [s for s in range(6) if s not in (xp1, xp2)]

        # Round-robin primary selection: start shifts by ~4/7 of the pool each window
        start = (ts * n_primary * 4 // 7) % n_primary
        picked: List[int] = []
        for i in range(n_primary + 10):
            p = (start + i) % n_primary
            if p not in picked:
                picked.append(p)
            if len(picked) == len(prim_slots):
                break

        vals: List[Optional[int]] = [None] * 6
        vals[xp1] = xs_base + xa
        vals[xp2] = xs_base + xb
        for i, s in enumerate(prim_slots):
            vals[s] = picked[i]

        for slot in range(6):
            arrays[slot].append(vals[slot])  # type: ignore[arg-type]

    return arrays


def build_liquid_pool(primary: List[Dict], cross_sell: List[Dict]) -> List[Dict]:
    """Assemble pool for Liquid slot-array display.

    Returns primary items followed by cross_sell[0..5]. Use
    build_slot_arrays_for_n(len(primary)) to get matching slot arrays that
    guarantee no duplicate products within any rotation window.

    Args:
        primary:    Primary-class products (ordered by revenue); any length >= 1
        cross_sell: Exactly 6 cross-sell products

    Returns:
        (n_primary + 6)-product list.
    """
    return list(primary) + cross_sell[:6]


# Slot arrays for Liquid randomization.
#
# For 7 timestamp windows (ts = 'now' | date: '%s' | modulo: 7):
# _LIQUID_SLOT_ARRAYS[slot][ts] = product index to display in that slot.
#
# Product index convention (from build_liquid_pool):
#   0-9  → primary products P0-P9
#   10   → XS_A (cross-sell item 1)
#   11   → XS_B (cross-sell item 2)
#
# Every window contains both XS_A (10) and XS_B (11) exactly once.
# XS items appear at different positions across windows so the block
# looks different to recipients who open at different times of the week.
#
# Slot arrays for Liquid randomization.
#
# Product index convention (from build_liquid_pool):
#   0-9   → primary products P0-P9
#   10-15 → cross-sell items XS_0 through XS_5
#
# XS items NEVER appear in slots 0 or 1.
# Each of the 7 windows picks a DIFFERENT pair from {10..15}:
#   ts=0: XS_0(10), XS_1(11) at slots 2,3
#   ts=1: XS_2(12), XS_3(13) at slots 2,4
#   ts=2: XS_4(14), XS_5(15) at slots 2,5
#   ts=3: XS_0(10), XS_2(12) at slots 3,4
#   ts=4: XS_1(11), XS_4(14) at slots 3,5
#   ts=5: XS_3(13), XS_5(15) at slots 4,5
#   ts=6: XS_0(10), XS_3(13) at slots 2,3
_LIQUID_SLOT_ARRAYS = [
    [0,  4,  8,  2,  6,  0,  7 ],  # slot 0 — always primary
    [1,  5,  9,  3,  7,  2,  8 ],  # slot 1 — always primary
    [10, 12, 14, 4,  8,  4,  10],  # slot 2
    [11, 6,  0,  10, 11, 6,  13],  # slot 3
    [2,  13, 1,  12, 9,  13, 9 ],  # slot 4
    [3,  7,  15, 5,  14, 15, 3 ],  # slot 5
]


def build_rec_html_liquid(
    pool: List[Dict],
    url_lookup: Dict[str, str],
    merch_class: str,
    resolved_images: Optional[Dict[str, str]] = None,
) -> str:
    """Build a Liquid-randomized 'You May Also Like' HTML block.

    Encodes a 12-product pool (from build_liquid_pool) as pipe-delimited
    Liquid arrays. At send time Braze picks one of 7 windows via Unix
    timestamp modulo 7. Every window contains both cross-sell items at
    different positions (see _LIQUID_SLOT_ARRAYS).

    Args:
        pool:            12 products: primary[0..9] at indices 0-9,
                         XS_A at index 10, XS_B at index 11
        url_lookup:      base_sku → product page URL
        merch_class:     MERCH_CLASS label for the HTML comment
        resolved_images: SKU → image URL fallback
    """
    import re as _re

    if not pool:
        return ""

    imgs = resolved_images or {}
    items = pool[:16]

    names:       List[str] = []
    im_urls:     List[str] = []
    prod_urls:   List[str] = []

    for product in items:
        sku       = product["SKU"]
        raw_name  = product["NAME"]
        merch_sub = product.get("MERCH_SUB_CLASS", "") or ""
        material  = product.get("MATERIAL", "") or ""
        mc        = product.get("MERCH_CLASS", "") or merch_class

        name = (
            product.get("DISPLAY_NAME")
            or display_name(raw_name, mc, merch_sub, material)
        )
        name = name.replace("|", "-").replace('"', "'")

        img = (
            product.get("PRODUCT_IMAGE")
            or imgs.get(sku)
            or (cylindo_image_url(sku) if _is_upholstered_sku(sku) else magento_image_url(sku))
        )
        # Strip feature params that break Cylindo rendering or cause 404s.
        # Handle both raw spaces and %20-encoded spaces in SEAT HEIGHT.
        img = _re.sub(r'&feature=(?:LENGTH|SEAT(?:%20| )?HEIGHT|PIPING):[^&]*', '', img)
        # Strip .PIPING suffix from Cylindo product path — the variant SKU suffix
        # (e.g. CLIA.FABRIC.BDRM.BED.PIPING) is not a valid Cylindo product ID.
        # Also normalize .LEATHER. → .LEATHR. (feed data inconsistency).
        if 'cylindo.com' in img:
            img = _re.sub(r'\.PIPING\b', '', img)
            img = img.replace('.LEATHER.', '.LEATHR.')
        img = img.replace(" ", "%20").replace("|", "%7C")

        url = product.get("PRODUCT_URL") or product_url(sku, raw_name, url_lookup)
        url = url.replace("|", "%7C")

        names.append(name)
        im_urls.append(img)
        prod_urls.append(url)

    nm_str = "|".join(names)
    im_str = "|".join(im_urls)
    ur_str = "|".join(prod_urls)

    # Slug array (matches utm_content values used in GA4 / add_ymal_utm_content.py)
    _type_kws = {
        "sofa", "sectional", "chair", "bed", "bench", "ottoman",
        "rug", "table", "chaise", "lounge", "cabinet", "dresser",
        "nightstand", "pendant", "sconce", "lamp", "pillow", "art",
        "shelf", "bookcase", "credenza", "console",
    }
    def _make_slug(url: str) -> str:
        path = url.split("?")[0].rstrip("/").split("/")[-1]
        parts = path.split("-")
        name = parts[0]
        type_word = next((p for p in parts[1:] if p in _type_kws), "")
        return f"{name}-{type_word}" if type_word else name
    slugs  = [_make_slug(u) for u in prod_urls]
    sl_str = "|".join(slugs)

    # Slot arrays: 6 strings, each a pipe-delimited list of 7 product indices
    n_primary = len(items) - 6
    slot_strs = [
        "|".join(str(idx) for idx in slot_row)
        for slot_row in build_slot_arrays_for_n(n_primary)
    ]

    block_slug  = merch_class.lower().replace(" ", "_")
    style_name  = "font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#1a1a1a;margin:8px 0 2px;line-height:1.4;text-align:center;"

    def _card(kv: str, slot_num: int) -> str:
        alias = f"recs_{block_slug}_s{slot_num}"
        return (
            f'          <td valign="top" style="padding:6px 5px;width:190px;">\n'
            f'            <a href="{{{{ _ur[{kv}] }}}}&utm_content=ymal_{{{{ _sl[{kv}] }}}}_s{slot_num}" style="text-decoration:none;color:inherit;" data-link-alias="{alias}">\n'
            f'              <img src="{{{{ _im[{kv}] }}}}" alt="{{{{ _nm[{kv}] | escape }}}}" width="190"\n'
            f'                   style="display:block;width:190px;height:190px;object-fit:contain;background:#ffffff;" />\n'
            f'              <p style="{style_name}">{{{{ _nm[{kv}] }}}}</p>\n'
            f'            </a>\n'
            f'          </td>'
        )

    row1 = "        <tr>\n" + "\n".join(_card(v, i + 1) for i, v in enumerate(["_k0", "_k1", "_k2"])) + "\n        </tr>"
    row2 = "        <tr>\n" + "\n".join(_card(v, i + 4) for i, v in enumerate(["_k3", "_k4", "_k5"])) + "\n        </tr>"

    return (
        f"{{% assign _ts = 'now' | date: '%s' | modulo: 7 %}}\n"
        f'{{% assign _nm = "{nm_str}" | split: "|" %}}\n'
        f'{{% assign _im = "{im_str}" | split: "|" %}}\n'
        f'{{% assign _ur = "{ur_str}" | split: "|" %}}\n'
        f'{{% assign _sl = "{sl_str}" | split: "|" %}}\n'
        f'{{% assign _s0 = "{slot_strs[0]}" | split: "|" %}}\n'
        f'{{% assign _s1 = "{slot_strs[1]}" | split: "|" %}}\n'
        f'{{% assign _s2 = "{slot_strs[2]}" | split: "|" %}}\n'
        f'{{% assign _s3 = "{slot_strs[3]}" | split: "|" %}}\n'
        f'{{% assign _s4 = "{slot_strs[4]}" | split: "|" %}}\n'
        f'{{% assign _s5 = "{slot_strs[5]}" | split: "|" %}}\n'
        f"{{% assign _k0 = _s0[_ts] | plus: 0 %}}\n"
        f"{{% assign _k1 = _s1[_ts] | plus: 0 %}}\n"
        f"{{% assign _k2 = _s2[_ts] | plus: 0 %}}\n"
        f"{{% assign _k3 = _s3[_ts] | plus: 0 %}}\n"
        f"{{% assign _k4 = _s4[_ts] | plus: 0 %}}\n"
        f"{{% assign _k5 = _s5[_ts] | plus: 0 %}}\n"
        f"{{% message_extras :key ymal_cat :value {merch_class} %}}\n"
        f"{{% message_extras :key ymal_s1 :value {{{{_sl[_k0]}}}} %}}\n"
        f"{{% message_extras :key ymal_s2 :value {{{{_sl[_k1]}}}} %}}\n"
        f"{{% message_extras :key ymal_s3 :value {{{{_sl[_k2]}}}} %}}\n"
        f"{{% message_extras :key ymal_s4 :value {{{{_sl[_k3]}}}} %}}\n"
        f"{{% message_extras :key ymal_s5 :value {{{{_sl[_k4]}}}} %}}\n"
        f"{{% message_extras :key ymal_s6 :value {{{{_sl[_k5]}}}} %}}\n"
        f"<!-- id_recs_{block_slug} — 16-product pool (6 XS, 2 per window), 7 rotations — auto-generated -->"
        f"""
<table width="600" cellpadding="0" cellspacing="0" border="0"
  style="border-collapse:collapse;margin:0 auto;">
  <tr>
    <td align="center" style="padding:28px 0 12px;">
      <p style="font-family:Georgia,Arial,sans-serif;font-size:18px;
                font-weight:400;color:#2e3c47;margin:0;">You May Also Like</p>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding:0 15px 28px;">
      <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
{row1}
{row2}
      </table>
    </td>
  </tr>
</table>"""
    )
