#!/usr/bin/env python3
"""
Inventory checker — query Snowflake for in-stock products by brand.

Supports:
  - BUR, CZ, STF via Shopify (FIVETRAN_DB)
  - HAV via Havenly Products catalog (AIRBYTE_DATABASE)

ID and TI are excluded (stale/no data).

Usage:
    from scripts.utils.inventory_checker import (
        get_top_stocked_products,
        check_product_availability,
        get_product_categories,
        format_inventory_for_prompt,
        close_all_clients,
        SUPPORTED_BRANDS,
    )

    products = get_top_stocked_products("BUR", limit=15)
    print(format_inventory_for_prompt(products))
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Add scripts dir to path for snowflake_client import
sys.path.insert(0, str(Path(__file__).parent.parent))
from snowflake_client import get_snowflake_client, SnowflakeClient


# ---------------------------------------------------------------------------
# Brand → data-source configuration
# ---------------------------------------------------------------------------

SHOPIFY_BRANDS = {
    "BUR": {
        "database": "FIVETRAN_DB",
        "schema": "LANDING_BURROW_SHOPIFY",
        "domain": "burrow.com",
    },
    "CZ": {
        "database": "FIVETRAN_DB",
        "schema": "LANDING_CZ_SHOPIFY",
        "domain": "www.the-citizenry.com",
    },
    "STF": {
        "database": "FIVETRAN_DB",
        "schema": "LANDING_STF_SHOPIFY",
        "domain": "www.stfrank.com",
    },
}

HAVENLY_CONFIG = {
    "database": "AIRBYTE_DATABASE",
    "schema": "LANDING_HAVENLY_PRODUCTS",
}

SUPPORTED_BRANDS = set(SHOPIFY_BRANDS.keys()) | {"HAV"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProductStock:
    """Normalized product stock record across all data sources."""
    brand: str
    product_title: str
    variant_count: int
    quantity_available: Optional[int]  # None for HAV (boolean availability only)
    is_available: bool
    min_price: Optional[float]
    max_price: Optional[float]
    product_type: Optional[str]
    source: str  # "shopify" or "havenly_products"


# ---------------------------------------------------------------------------
# Connection cache (one per brand, reused within a script run)
# ---------------------------------------------------------------------------

_client_cache: Dict[str, SnowflakeClient] = {}


def _get_client(brand: str) -> SnowflakeClient:
    """Get or create a cached Snowflake client for a brand."""
    if brand in _client_cache:
        return _client_cache[brand]

    if brand in SHOPIFY_BRANDS:
        cfg = SHOPIFY_BRANDS[brand]
    elif brand == "HAV":
        cfg = HAVENLY_CONFIG
    else:
        raise ValueError(f"Unsupported brand: {brand}. Supported: {', '.join(sorted(SUPPORTED_BRANDS))}")

    client = get_snowflake_client(schema=cfg["schema"], database=cfg["database"])
    _client_cache[brand] = client
    return client


def close_all_clients():
    """Close all cached Snowflake connections."""
    for client in _client_cache.values():
        try:
            client.close()
        except Exception:
            pass
    _client_cache.clear()


# ---------------------------------------------------------------------------
# Result cache (inventory changes daily, no need to re-query within a run)
# ---------------------------------------------------------------------------

_results_cache: Dict[str, List[ProductStock]] = {}


def _cache_key(brand: str, category: Optional[str], limit: int) -> str:
    return f"{brand}|{category or ''}|{limit}"


# ---------------------------------------------------------------------------
# Shopify queries (BUR, CZ, STF)
# ---------------------------------------------------------------------------

# Product types to exclude from top-stocked queries (spare parts, samples, etc.)
_EXCLUDED_PRODUCT_TYPES = ("Components", "Swatch", "Accessories")

def _shopify_top_products(
    brand: str, category: Optional[str] = None, limit: int = 20,
) -> List[ProductStock]:
    """Query Shopify for top-stocked products, aggregated by product title.

    Excludes spare parts, swatches, and low-value accessories by default
    to surface only promotable products.
    """
    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    # AVAILABLE_FOR_SALE is the storefront-level signal — a variant can have
    # INVENTORY_QUANTITY > 0 but still be unpurchasable on the website (e.g. the
    # product is unlisted from a sales channel). Always filter on AVAILABLE_FOR_SALE.
    where_clause = "WHERE pv.AVAILABLE_FOR_SALE = TRUE AND p.STATUS = 'ACTIVE' AND p._FIVETRAN_DELETED = FALSE"
    if category:
        where_clause += f" AND LOWER(p.PRODUCT_TYPE) = LOWER('{category}')"
    else:
        # Exclude non-promotable product types and very cheap items (spare parts)
        excluded = ", ".join(f"'{t}'" for t in _EXCLUDED_PRODUCT_TYPES)
        where_clause += f" AND (p.PRODUCT_TYPE IS NULL OR p.PRODUCT_TYPE NOT IN ({excluded}))"
        where_clause += " AND pv.PRICE > 50"

    query = f"""
    SELECT
        p.TITLE AS product_title,
        p.PRODUCT_TYPE AS product_type,
        COUNT(pv.ID) AS variant_count,
        SUM(pv.INVENTORY_QUANTITY) AS total_stock,
        MIN(pv.PRICE) AS min_price,
        MAX(pv.PRICE) AS max_price
    FROM {fqn}.PRODUCT_VARIANT pv
    JOIN {fqn}.PRODUCT p ON pv.PRODUCT_ID = p.ID
    {where_clause}
    GROUP BY p.TITLE, p.PRODUCT_TYPE
    ORDER BY total_stock DESC
    LIMIT {limit}
    """

    client = _get_client(brand)
    rows = client.execute_query(query)

    results = []
    for row in rows:
        results.append(ProductStock(
            brand=brand,
            product_title=row["PRODUCT_TITLE"],
            variant_count=int(row["VARIANT_COUNT"]),
            quantity_available=int(row["TOTAL_STOCK"]),
            is_available=True,
            min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
            max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
            product_type=row.get("PRODUCT_TYPE"),
            source="shopify",
        ))
    return results


def _shopify_check_product(brand: str, product_name: str) -> Optional[ProductStock]:
    """Fuzzy search for a specific product in Shopify."""
    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT
        p.TITLE AS product_title,
        p.PRODUCT_TYPE AS product_type,
        COUNT(pv.ID) AS variant_count,
        SUM(CASE WHEN pv.AVAILABLE_FOR_SALE = TRUE THEN pv.INVENTORY_QUANTITY ELSE 0 END) AS total_stock,
        MIN(pv.PRICE) AS min_price,
        MAX(pv.PRICE) AS max_price
    FROM {fqn}.PRODUCT_VARIANT pv
    JOIN {fqn}.PRODUCT p ON pv.PRODUCT_ID = p.ID
    WHERE LOWER(p.TITLE) ILIKE '%{product_name.lower().replace("'", "''")}%'
      AND p.STATUS = 'ACTIVE'
      AND p._FIVETRAN_DELETED = FALSE
    GROUP BY p.TITLE, p.PRODUCT_TYPE
    ORDER BY total_stock DESC
    LIMIT 1
    """

    client = _get_client(brand)
    rows = client.execute_query(query)
    if not rows:
        return None

    row = rows[0]
    stock = int(row["TOTAL_STOCK"])
    return ProductStock(
        brand=brand,
        product_title=row["PRODUCT_TITLE"],
        variant_count=int(row["VARIANT_COUNT"]),
        quantity_available=stock,
        is_available=stock > 0,
        min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
        max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
        product_type=row.get("PRODUCT_TYPE"),
        source="shopify",
    )


def _shopify_categories(brand: str) -> List[str]:
    """Get distinct product types from Shopify."""
    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT DISTINCT p.PRODUCT_TYPE
    FROM {fqn}.PRODUCT p
    JOIN {fqn}.PRODUCT_VARIANT pv ON pv.PRODUCT_ID = p.ID
    WHERE pv.INVENTORY_QUANTITY > 0
      AND p.PRODUCT_TYPE IS NOT NULL
      AND p.PRODUCT_TYPE != ''
    ORDER BY p.PRODUCT_TYPE
    """

    client = _get_client(brand)
    rows = client.execute_query(query)
    return [row["PRODUCT_TYPE"] for row in rows if row.get("PRODUCT_TYPE")]


def _shopify_collection_products(
    brand: str, collection_name: str, limit: int = 20,
) -> List[ProductStock]:
    """Get in-stock products from a named Shopify collection."""
    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT
        p.TITLE AS product_title,
        p.PRODUCT_TYPE AS product_type,
        COUNT(pv.ID) AS variant_count,
        SUM(pv.INVENTORY_QUANTITY) AS total_stock,
        MIN(pv.PRICE) AS min_price,
        MAX(pv.PRICE) AS max_price
    FROM {fqn}.COLLECTION_PRODUCT cp
    JOIN {fqn}.COLLECTION c ON cp.COLLECTION_ID = c.ID
    JOIN {fqn}.PRODUCT p ON cp.PRODUCT_ID = p.ID
    JOIN {fqn}.PRODUCT_VARIANT pv ON pv.PRODUCT_ID = p.ID
    WHERE LOWER(c.TITLE) ILIKE '%{collection_name.lower().replace("'", "''")}%'
      AND pv.INVENTORY_QUANTITY > 0
    GROUP BY p.TITLE, p.PRODUCT_TYPE
    ORDER BY total_stock DESC
    LIMIT {limit}
    """

    client = _get_client(brand)
    rows = client.execute_query(query)

    results = []
    for row in rows:
        results.append(ProductStock(
            brand=brand,
            product_title=row["PRODUCT_TITLE"],
            variant_count=int(row["VARIANT_COUNT"]),
            quantity_available=int(row["TOTAL_STOCK"]),
            is_available=True,
            min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
            max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
            product_type=row.get("PRODUCT_TYPE"),
            source="shopify",
        ))
    return results


# ---------------------------------------------------------------------------
# Havenly queries (HAV)
# ---------------------------------------------------------------------------

def _havenly_top_products(
    category: Optional[str] = None, limit: int = 20,
) -> List[ProductStock]:
    """Query Havenly products catalog for available products.

    Uses AVAILABILITIES + VENDOR_VARIANTS + VENDOR_VARIANT_GROUPS.
    Only includes truly in-stock items (AVAILABILITY_TYPE_ID IN (1, 2)),
    excluding back-ordered (3, 4).

    Schema notes:
      - VENDOR_VARIANT_GROUPS.VENDOR_GROUP (not NAME) = product group name
      - VENDOR_VARIANTS.TAXONOMY_ID links to TAXONOMIES.ID
      - TAXONOMIES.TITLE (not NAME) = category name
      - Prices are in separate PRICES table joined by VENDOR_VARIANT_ID
    """
    cfg = HAVENLY_CONFIG
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    # Category filter via taxonomy on VENDOR_VARIANTS
    category_join = ""
    category_where = ""
    if category:
        category_join = f"""
        JOIN {fqn}.TAXONOMIES t ON vv.TAXONOMY_ID = t.ID
        """
        category_where = f"AND LOWER(t.TITLE) = LOWER('{category.replace(chr(39), chr(39)+chr(39))}')"

    query = f"""
    SELECT
        ANY_VALUE(vv.TITLE) AS product_title,
        COUNT(DISTINCT vv.ID) AS variant_count,
        MIN(pr.PRICE) AS min_price,
        MAX(pr.PRICE) AS max_price
    FROM {fqn}.AVAILABILITIES a
    JOIN {fqn}.VENDOR_VARIANTS vv ON a.VENDOR_VARIANT_ID = vv.ID
    JOIN {fqn}.VENDOR_VARIANT_GROUPS vvg ON vv.VENDOR_VARIANT_GROUP_ID = vvg.ID
    LEFT JOIN {fqn}.PRICES pr ON pr.VENDOR_VARIANT_ID = vv.ID
        AND pr.PRICE_TYPE_ID = 1
        AND (pr.END_DATE IS NULL OR pr.END_DATE > CURRENT_TIMESTAMP())
    {category_join}
    WHERE a.IS_AVAILABLE = TRUE
      AND a.AVAILABILITY_TYPE_ID IN (1, 2)
      AND a.MODIFIED >= DATEADD('day', -7, CURRENT_TIMESTAMP())
      {category_where}
    GROUP BY vvg.ID
    ORDER BY variant_count DESC
    LIMIT {limit}
    """

    client = _get_client("HAV")
    rows = client.execute_query(query)

    results = []
    for row in rows:
        results.append(ProductStock(
            brand="HAV",
            product_title=row["PRODUCT_TITLE"],
            variant_count=int(row["VARIANT_COUNT"]),
            quantity_available=None,  # HAV has boolean availability, not quantity
            is_available=True,
            min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
            max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
            product_type=None,  # Set via separate taxonomy query if needed
            source="havenly_products",
        ))
    return results


def _havenly_check_product(product_name: str) -> Optional[ProductStock]:
    """Fuzzy search for a specific product in Havenly catalog."""
    cfg = HAVENLY_CONFIG
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT
        ANY_VALUE(vv.TITLE) AS product_title,
        COUNT(DISTINCT vv.ID) AS variant_count,
        MIN(pr.PRICE) AS min_price,
        MAX(pr.PRICE) AS max_price,
        MAX(CASE WHEN a.AVAILABILITY_TYPE_ID IN (1, 2) AND a.IS_AVAILABLE = TRUE
            THEN 1 ELSE 0 END) AS any_in_stock
    FROM {fqn}.AVAILABILITIES a
    JOIN {fqn}.VENDOR_VARIANTS vv ON a.VENDOR_VARIANT_ID = vv.ID
    JOIN {fqn}.VENDOR_VARIANT_GROUPS vvg ON vv.VENDOR_VARIANT_GROUP_ID = vvg.ID
    LEFT JOIN {fqn}.PRICES pr ON pr.VENDOR_VARIANT_ID = vv.ID
        AND pr.PRICE_TYPE_ID = 1
        AND (pr.END_DATE IS NULL OR pr.END_DATE > CURRENT_TIMESTAMP())
    WHERE LOWER(vv.TITLE) ILIKE '%{product_name.lower().replace("'", "''")}%'
      AND a.MODIFIED >= DATEADD('day', -7, CURRENT_TIMESTAMP())
    GROUP BY vvg.ID
    ORDER BY variant_count DESC
    LIMIT 1
    """

    client = _get_client("HAV")
    rows = client.execute_query(query)
    if not rows:
        return None

    row = rows[0]
    in_stock = int(row.get("ANY_IN_STOCK", 0)) > 0
    return ProductStock(
        brand="HAV",
        product_title=row["PRODUCT_TITLE"],
        variant_count=int(row["VARIANT_COUNT"]),
        quantity_available=None,
        is_available=in_stock,
        min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
        max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
        product_type=None,
        source="havenly_products",
    )


def _havenly_categories() -> List[str]:
    """Get distinct taxonomy categories from Havenly products.

    Uses TAXONOMIES.TITLE (not NAME) joined through VENDOR_VARIANTS.TAXONOMY_ID.
    """
    cfg = HAVENLY_CONFIG
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT DISTINCT t.TITLE
    FROM {fqn}.TAXONOMIES t
    WHERE t.TITLE IS NOT NULL
      AND t.TITLE != ''
      AND t.PARENT_ID IS NOT NULL
    ORDER BY t.TITLE
    LIMIT 50
    """

    client = _get_client("HAV")
    rows = client.execute_query(query)
    return [row["TITLE"] for row in rows if row.get("TITLE")]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_top_stocked_products(
    brand: str, category: Optional[str] = None, limit: int = 20,
) -> List[ProductStock]:
    """Get top in-stock products for a brand, ordered by stock depth.

    Args:
        brand: Brand code (BUR, CZ, STF, HAV)
        category: Optional product type/category filter
        limit: Max products to return

    Returns:
        List of ProductStock, sorted by stock depth (Shopify) or variant count (HAV)
    """
    if brand not in SUPPORTED_BRANDS:
        return []

    key = _cache_key(brand, category, limit)
    if key in _results_cache:
        return _results_cache[key]

    if brand in SHOPIFY_BRANDS:
        results = _shopify_top_products(brand, category, limit)
    else:
        results = _havenly_top_products(category, limit)

    _results_cache[key] = results
    return results


def check_product_availability(brand: str, product_name: str) -> Optional[ProductStock]:
    """Check if a specific product is available for a brand.

    Args:
        brand: Brand code (BUR, CZ, STF, HAV)
        product_name: Product name to search for (fuzzy match)

    Returns:
        ProductStock if found, None otherwise
    """
    if brand not in SUPPORTED_BRANDS:
        return None

    if brand in SHOPIFY_BRANDS:
        return _shopify_check_product(brand, product_name)
    else:
        return _havenly_check_product(product_name)


def get_product_categories(brand: str) -> List[str]:
    """Get distinct product categories for a brand.

    Args:
        brand: Brand code (BUR, CZ, STF, HAV)

    Returns:
        List of category/product-type names
    """
    if brand not in SUPPORTED_BRANDS:
        return []

    if brand in SHOPIFY_BRANDS:
        return _shopify_categories(brand)
    else:
        return _havenly_categories()


def get_archive_sale_product_handles(brand: str) -> set:
    """Return the set of product handles that belong to any Archive Sale collection.

    Used to filter archive-sale items out of non-archive-sale email briefs.
    Only supported for Shopify brands (BUR, CZ, STF).
    """
    if brand not in SHOPIFY_BRANDS:
        return set()

    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT DISTINCT p.HANDLE AS handle
    FROM {fqn}.COLLECTION_PRODUCT cp
    JOIN {fqn}.COLLECTION c ON cp.COLLECTION_ID = c.ID
    JOIN {fqn}.PRODUCT p ON cp.PRODUCT_ID = p.ID
    WHERE LOWER(c.TITLE) ILIKE '%archive%'
    """

    client = _get_client(brand)
    rows = client.execute_query(query)
    return {row["HANDLE"] for row in rows if row.get("HANDLE")}


_collection_titles_cache: Dict[str, List[str]] = {}


def list_collection_titles(brand: str) -> List[str]:
    """Return every real, distinct Shopify collection TITLE for a brand (BUR/CZ/STF),
    live from Snowflake.

    Lets a caller match a brief's free-text topic against REAL collection names
    without hand-maintaining a static per-brand list - the BUR briefing flow used a
    hardcoded `_BUR_KNOWN_COLLECTIONS` list and it drifted out of sync with the real
    catalog more than once (e.g. a bogus "Haiku Alto" entry that matched zero rows,
    confirmed 2026-08-02). Cached per-brand for the life of the process since
    collection names change rarely within a single briefing session.
    """
    if brand not in SHOPIFY_BRANDS:
        return []
    if brand in _collection_titles_cache:
        return _collection_titles_cache[brand]

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    client = _get_client(brand)
    rows = client.execute_query(f"""
        SELECT DISTINCT TITLE FROM {fqn}.COLLECTION
        WHERE TITLE IS NOT NULL AND TITLE != ''
    """)
    titles = [r["TITLE"].strip() for r in rows if r.get("TITLE") and r["TITLE"].strip()]
    _collection_titles_cache[brand] = titles
    return titles


def get_ready_to_ship_variants(brand: str, timeout: int = 15) -> Optional[Dict[str, set]]:
    """Fetch the ACTUAL burrow.com/ready-to-ship collection page and return, per product
    handle, the set of specific colorway/finish combinations (as sorted tuples of
    (query-param, value) pairs, ORIGINAL casing preserved for display - use
    `_normalize_product_link_signature()`/lowercase both sides to compare) that page shows
    as ready-to-ship - the authoritative, curated ground truth for what's currently
    promoted as Quick Ship.

    Confirmed 2026-08-02 that Quick Ship status is genuinely COLORWAY-specific, not just
    product-level: the /ready-to-ship page links to
    `/products/nomad-plus-sofa?Fabric=Sienna+-+Performance+Brushed+Chenille&Leg+Finish=...`
    - only that one fabric/leg-finish/arm-style combination is ready-to-ship for Nomad
    Sofa, not the product generally. Neither Shopify collection membership (product-level)
    nor Snowflake PRODUCT_VARIANT inventory/AVAILABLE_FOR_SALE predicts this: Nomad
    Loveseat's "Crushed Gravel" colorway has healthy live inventory in Snowflake but does
    NOT appear on this page at all (only a different colorway does, for a different but
    same-family product), and Span Storage Chaise has 70-100+ units available across every
    colorway yet its product page quotes an 8-10 week lead time - raw stock counts do not
    drive Burrow's displayed ready-to-ship/lead-time estimate. The live page is the only
    reliable signal.

    A handle appearing with an EMPTY signature (no query string at all, e.g. `benji-rocker`,
    `chorus-bed`) means that listing has no colorway variants to distinguish - any link to
    that bare product page counts as a match. A handle appearing only with non-empty
    signatures (e.g. `nomad-plus-sofa`) means ONLY those specific colorway combinations are
    ready-to-ship; a bare link to that product (no colorway specified) cannot be confirmed
    and should not pass.

    Burrow's storefront (Remix/Hydrogen) server-renders this page's full product grid, so a
    plain, unauthenticated GET returns every handle+colorway with no JS execution or
    Playwright needed - confirmed by comparing this function's output against a JS-rendered
    browser fetch of the same page: identical results.

    Returns None (not an empty dict) on any fetch failure so callers can distinguish
    "couldn't check" from "checked, found nothing". Only supported for BUR - the only
    brand with a Quick Ship collection page today.
    """
    if brand != "BUR":
        return None
    domain = SHOPIFY_BRANDS.get(brand, {}).get("domain", "burrow.com")
    try:
        import requests as _requests
        r = _requests.get(f"https://{domain}/ready-to-ship", timeout=timeout)
        r.raise_for_status()
    except Exception:
        return None

    import re as _re
    from html import unescape as _unescape
    from urllib.parse import parse_qsl as _parse_qsl

    href_re = _re.compile(r'/products/([a-z0-9\-]+)(\?[^"\'<>\s]*)?')
    variants: Dict[str, set] = {}
    for handle, qs in href_re.findall(r.text):
        qs = _unescape(qs).lstrip("?")
        signature = tuple(sorted(
            (k.strip(), v.strip()) for k, v in _parse_qsl(qs)
        )) if qs else ()
        variants.setdefault(handle, set()).add(signature)
    return variants


def _normalized_signature(signature: tuple) -> tuple:
    """Lowercase a (param, value) signature tuple for case-insensitive comparison, without
    losing the original-cased version needed for display."""
    return tuple(sorted((k.lower(), v.lower()) for k, v in signature))


def _normalize_product_link_signature(url: str) -> tuple:
    """Extract a product URL's query string into the same (param, value)-tuple signature
    `get_ready_to_ship_variants()` uses (then run through `_normalized_signature()` at
    comparison time), so a brief's resolved Link can be compared against the live
    ready-to-ship page's colorway signatures. Handles both "+"- and "%20"-encoded spaces.
    """
    from urllib.parse import urlsplit, parse_qsl
    qs = urlsplit(url).query
    return tuple(sorted(
        (k.strip(), v.strip()) for k, v in parse_qsl(qs)
    )) if qs else ()


def get_quick_ship_product_handles(brand: str) -> set:
    """Return the flat set of product handles that appear ANYWHERE on the live Ready to
    Ship page, regardless of colorway. Coarser than `get_ready_to_ship_variants()` (which
    is colorway-aware) - kept for callers that only need a quick "is this product in the
    Quick Ship lineup at all" check, and as the fallback path when the live page can't be
    reached (falls back to the less precise, product-level Snowflake COLLECTION_PRODUCT
    membership query in that case - still better than no check at all).

    Confirmed gap 2026-08-02: a BUR "Quick Ship — Designed" brief (qs_v2) featured Nomad
    Loveseat ("Ships in 3-5 days", made-to-order) and Span Storage Chaise ("Ships in 8-10
    weeks") alongside genuine ready-to-ship items, because no inventory grounding or
    validation distinguished Quick Ship stock from the general top-stocked fallback.
    """
    if brand not in SHOPIFY_BRANDS:
        return set()

    live = get_ready_to_ship_variants(brand)
    if live is not None:
        return set(live.keys())

    cfg = SHOPIFY_BRANDS[brand]
    db = cfg["database"]
    schema = cfg["schema"]
    fqn = f"{db}.{schema}"

    query = f"""
    SELECT DISTINCT p.HANDLE AS handle
    FROM {fqn}.COLLECTION_PRODUCT cp
    JOIN {fqn}.COLLECTION c ON cp.COLLECTION_ID = c.ID
    JOIN {fqn}.PRODUCT p ON cp.PRODUCT_ID = p.ID
    JOIN {fqn}.PRODUCT_VARIANT pv ON pv.PRODUCT_ID = p.ID
    WHERE (LOWER(c.TITLE) ILIKE '%ready to ship%' OR LOWER(c.TITLE) ILIKE '%quick ship%')
      AND pv.INVENTORY_QUANTITY > 0
    """

    client = _get_client(brand)
    rows = client.execute_query(query)
    return {row["HANDLE"] for row in rows if row.get("HANDLE")}


def get_products_by_handles(brand: str, handles: set, limit: int = 30) -> List[ProductStock]:
    """Look up title/price/stock for a specific, known set of product handles - used to
    turn `get_quick_ship_product_handles()`'s live-verified handle set into readable
    product names for prompt grounding (the live page gives handles, not titles/prices;
    Snowflake has those, keyed by the same handle).
    """
    if brand not in SHOPIFY_BRANDS or not handles:
        return []

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    safe_handles = ", ".join(f"'{h}'" for h in handles if h)
    if not safe_handles:
        return []

    query = f"""
    SELECT
        p.TITLE AS product_title,
        p.PRODUCT_TYPE AS product_type,
        COUNT(pv.ID) AS variant_count,
        SUM(pv.INVENTORY_QUANTITY) AS total_stock,
        MIN(pv.PRICE) AS min_price,
        MAX(pv.PRICE) AS max_price
    FROM {fqn}.PRODUCT p
    JOIN {fqn}.PRODUCT_VARIANT pv ON pv.PRODUCT_ID = p.ID
    WHERE p.HANDLE IN ({safe_handles})
    GROUP BY p.TITLE, p.PRODUCT_TYPE
    ORDER BY total_stock DESC
    LIMIT {limit}
    """

    client = _get_client(brand)
    rows = client.execute_query(query)

    return [
        ProductStock(
            brand=brand,
            product_title=row["PRODUCT_TITLE"],
            variant_count=int(row["VARIANT_COUNT"]),
            quantity_available=int(row["TOTAL_STOCK"]) if row.get("TOTAL_STOCK") is not None else None,
            is_available=True,
            min_price=float(row["MIN_PRICE"]) if row.get("MIN_PRICE") else None,
            max_price=float(row["MAX_PRICE"]) if row.get("MAX_PRICE") else None,
            product_type=row.get("PRODUCT_TYPE"),
            source="shopify",
        )
        for row in rows
    ]


def get_titles_by_handles(brand: str, handles: set) -> Dict[str, str]:
    """Return a plain handle -> product TITLE map for a known set of handles - no
    aggregation, unlike `get_products_by_handles()`, so it stays 1:1 with the handle-level
    colorway data `get_ready_to_ship_variants()` returns."""
    if brand not in SHOPIFY_BRANDS or not handles:
        return {}

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    safe_handles = ", ".join(f"'{h}'" for h in handles if h)
    if not safe_handles:
        return {}

    client = _get_client(brand)
    rows = client.execute_query(f"""
        SELECT HANDLE, TITLE FROM {fqn}.PRODUCT WHERE HANDLE IN ({safe_handles})
    """)
    return {row["HANDLE"]: row["TITLE"] for row in rows if row.get("HANDLE")}


# Query params that represent a colorway/finish choice on a Burrow product page (as
# opposed to e.g. a size or leg-style param) - used to pick which value to surface as
# "the" ready-to-ship colorway when formatting prompt grounding text.
_COLORWAY_PARAM_PRIORITY = ("fabric", "wood finish", "leather", "color")


def format_ready_to_ship_prompt_context(brand: str, limit: int = 30) -> Optional[str]:
    """Build prompt-ready text listing each Ready to Ship product together with the EXACT
    colorway(s) that are actually ready-to-ship for it - not just any live/in-stock
    colorway. Grounding for Quick Ship briefs so an AI can only ever name a real,
    genuinely-ready-to-ship colorway (never an arbitrary in-stock one that happens to be
    made-to-order for that specific fabric/finish).

    Example output:
        - Nomad Sofa: ready-to-ship colorway is Sienna - Performance Brushed Chenille
          (do not use any other colorway for this product in a Quick Ship email)
        - Opera Media Console: ready-to-ship in any of these finishes: Oak - Wood,
          Walnut - Wood, Blackened Oak - Wood
        - Benji Rocker: ready-to-ship, no colorway to specify

    Returns None if the live ready-to-ship page can't be reached or no products resolve
    (callers should fall back to a stricter "don't invent a colorway at all" instruction
    rather than silently proceeding as if grounding data was available). Only supported
    for BUR - the only brand with a Quick Ship collection page today.
    """
    variants = get_ready_to_ship_variants(brand)
    if not variants:
        return None

    titles = get_titles_by_handles(brand, set(variants.keys()))
    if not titles:
        return None

    lines = []
    for handle, signatures in variants.items():
        title = titles.get(handle)
        if not title:
            continue
        if () in signatures and len(signatures) == 1:
            lines.append(f"- {title}: ready-to-ship, no colorway to specify")
            continue
        real_signatures = [s for s in signatures if s]
        colorway_values = []
        for sig in real_signatures:
            by_param = {k.lower(): v for k, v in sig}
            for param in _COLORWAY_PARAM_PRIORITY:
                if param in by_param:
                    colorway_values.append(by_param[param])
                    break
            else:
                if sig:
                    colorway_values.append(sig[0][1])
        colorway_values = sorted(set(colorway_values))
        if not colorway_values:
            continue
        if len(colorway_values) == 1:
            lines.append(
                f"- {title}: ready-to-ship colorway is {colorway_values[0]} "
                f"(do not use any other colorway for this product in a Quick Ship email)"
            )
        else:
            lines.append(
                f"- {title}: ready-to-ship in any of these finishes: "
                + ", ".join(colorway_values)
            )

    if not lines:
        return None
    return "\n".join(sorted(lines)[:limit])


def get_collection_products(
    brand: str, collection_name: str, limit: int = 20,
) -> List[ProductStock]:
    """Get in-stock products from a named collection (Shopify brands only).

    Args:
        brand: Brand code (BUR, CZ, STF)
        collection_name: Collection name to search for (fuzzy match)
        limit: Max products to return

    Returns:
        List of ProductStock from the collection
    """
    if brand not in SHOPIFY_BRANDS:
        return []

    return _shopify_collection_products(brand, collection_name, limit)


def resolve_product_link(
    brand: str, product_title: str, colorway: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """Resolve a real product title (optionally with a specific Fabric/finish colorway)
    to a verified, LIVE product-page URL - never guess handles or invent Fabric query
    values by hand.

    Handles a real gotcha confirmed 2026-07-31 while fixing BUR briefs: the same
    product TITLE can have multiple Shopify listings (e.g. a base listing and a
    "Plus"-prefixed variant with a different price/fabric range), and the
    older/canonical listing is sometimes discontinued (404 on the live site) even
    though Snowflake still shows it STATUS = 'ACTIVE'. This function:

    1. Finds every ACTIVE product record with this exact title.
    2. Live-checks each candidate handle over HTTP (only a 200 counts).
    3. If a colorway is given, prefers a live handle where that exact fabric is an
       available variant; if none match, falls back to a real fabric that IS live on
       the first live handle and reports the substitution via "substituted": True -
       always surface that to a human before treating the brief as final, the same as
       an unverified product name.
    4. Builds the final URL with %20-encoded spaces, not "+": "+" is only guaranteed to
       decode as a space inside application/x-www-form-urlencoded content, and every
       link here passes through Braze's click-tracking redirect wrapper (and
       potentially further email-client "safe link" rewriting) before reaching the
       destination - %20 is unambiguous in every URL context, "+" is not.

    Domain is read from SHOPIFY_BRANDS[brand]["domain"] (burrow.com / www.the-citizenry.com /
    www.stfrank.com) - confirmed 2026-07-31 that this was hardcoded to burrow.com in the
    live-check and URL-building steps regardless of `brand`, silently breaking every CZ/STF
    call (always returned None, even for real, live, ACTIVE products - see git history for
    the fix). Only supports Shopify brands (BUR/CZ/STF) - the ones with a Snowflake PRODUCT/
    PRODUCT_VARIANT table this can query. Returns None if no live handle exists for
    this title at all (e.g. the whole product got sunset). Returns a dict:
        {"url": ..., "handle": ..., "colorway": ..., "substituted": bool}
    """
    if brand not in SHOPIFY_BRANDS:
        return None

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    client = _get_client(brand)

    safe_title = product_title.replace("'", "''")
    candidates = client.execute_query(f"""
        SELECT ID, HANDLE FROM {fqn}.PRODUCT
        WHERE TITLE = '{safe_title}' AND STATUS = 'ACTIVE'
        ORDER BY ID
    """)
    if not candidates:
        return None

    import requests as _requests
    from urllib.parse import quote as _quote

    domain = cfg["domain"]

    def _is_live(handle: str) -> bool:
        try:
            r = _requests.get(f"https://{domain}/products/{handle}", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def _primary_option_name(pid) -> str:
        """Return the product's REAL first-position option name (e.g. "Fabric", "Size",
        "Color", "Wood Finish") from PRODUCT_OPTION, for use as the URL query parameter
        key. Confirmed bug 2026-08-02: this used to be hardcoded as "Fabric" for every
        brand/product, which is correct for BUR items like Range Pro (option IS named
        "Fabric") but silently wrong for e.g. STF pillows (option is named "Size" -
        confirmed via PRODUCT_OPTION: "Sage Ribbon Suzani Outdoor Pillow" has one option,
        NAME="Size"). A URL built as "?Fabric=18%22 W x 18%22 H" would not correctly
        preselect anything on the live site, since the product's actual Shopify option
        key is "Size", not "Fabric". Falls back to "Fabric" only if no option row exists
        at all (shouldn't happen for a product with real variants).
        """
        rows = client.execute_query(f"""
            SELECT NAME FROM {fqn}.PRODUCT_OPTION WHERE PRODUCT_ID = {pid}
            ORDER BY POSITION LIMIT 1
        """)
        if rows and rows[0].get("NAME"):
            return rows[0]["NAME"]
        return "Fabric"

    def _matching_live_fabric(pid, fabric: str) -> Optional[str]:
        """Return the REAL, full variant title matching `fabric` (prefix match, case-
        insensitive), or None. Confirmed bug 2026-08-02: this used to return a bare bool,
        and the caller built the URL from the model's raw (possibly shorthand) input
        string - e.g. a brief saying "navy" would prefix-match the real variant "Navy
        Blue - Performance Flatweave" and report substituted=False, but the URL was built
        as "?Fabric=navy", not the full real title. Shopify's variant selector needs an
        exact string match to auto-select the swatch, so a shorthand match that "passes"
        validation could still land on the wrong (or no) preselected variant on the live
        site. Always use the actual matched TITLE in the URL, never the caller's input.
        """
        safe_fabric = fabric.replace("'", "''")
        rows = client.execute_query(f"""
            SELECT pv.TITLE FROM {fqn}.PRODUCT_VARIANT pv
            WHERE pv.PRODUCT_ID = {pid} AND pv.AVAILABLE_FOR_SALE = TRUE
              AND pv.TITLE ILIKE '{safe_fabric}%'
            LIMIT 1
        """)
        if not rows:
            return None
        title = (rows[0]["TITLE"] or "").split(" / ")[0].strip()
        return title or None

    def _first_live_fabric(pid) -> Optional[str]:
        """Return the first real, live variant value to suggest as a substitute.
        Confirmed gap 2026-08-02: this used to require " - " in the title (matching
        BUR's "Name - Description" convention, e.g. "Moss Green - Performance
        Flatweave"), which silently excluded valid values with a different shape (STF
        pillow sizes like '18" W x 18" H' have no dash) - meaning STF products would
        report substituted=True with NO suggested colorway even when real, live size
        values existed. Now accepts any real value, only excluding Shopify's own
        "Default Title" placeholder (used for products with no real options at all).
        """
        rows = client.execute_query(f"""
            SELECT DISTINCT pv.TITLE FROM {fqn}.PRODUCT_VARIANT pv
            WHERE pv.PRODUCT_ID = {pid} AND pv.AVAILABLE_FOR_SALE = TRUE LIMIT 10
        """)
        for r in rows:
            first = (r["TITLE"] or "").split(" / ")[0].strip()
            if first and first.lower() != "default title":
                return first
        return None

    live = [(r["ID"], r["HANDLE"]) for r in candidates if _is_live(r["HANDLE"])]
    if not live:
        return None

    if colorway is None:
        pid, handle = live[0]
        return {"url": f"https://{domain}/products/{handle}", "handle": handle,
                "colorway": None, "substituted": False}

    for pid, handle in live:
        matched_title = _matching_live_fabric(pid, colorway)
        if matched_title:
            option_name = _primary_option_name(pid)
            url = (
                f"https://{domain}/products/{handle}"
                f"?{_quote(option_name, safe='')}={_quote(matched_title, safe='')}"
            )
            return {"url": url, "handle": handle, "colorway": matched_title, "substituted": False}

    pid, handle = live[0]
    fallback = _first_live_fabric(pid)
    if not fallback:
        return {"url": f"https://{domain}/products/{handle}", "handle": handle,
                "colorway": None, "substituted": True}
    option_name = _primary_option_name(pid)
    url = (
        f"https://{domain}/products/{handle}"
        f"?{_quote(option_name, safe='')}={_quote(fallback, safe='')}"
    )
    return {"url": url, "handle": handle, "colorway": fallback, "substituted": True}


def get_product_variants(brand: str, product_title: str) -> List[str]:
    """Return the real, live, available-for-sale variant titles (colorways/finishes) for
    an exact, ACTIVE product title - e.g. ["Moss Green - Performance Flatweave",
    "Georgia Clay - Performance Chenille", "Camel - Top Grain Leather"]. Empty list if the
    product isn't found, isn't ACTIVE, or has no live handle.

    Used to ground brief generation in real colorway options BEFORE the copy is written,
    so a brief never names a color/finish that doesn't exist for that product - the root
    cause behind BUR "Range Pro Highlight" (2026-08-02), where the brief described
    "oatmeal"/"charcoal"/"warm gray" Range Pro fabrics that were never real; the actual
    options are the three listed above. Only supports Shopify brands (BUR/CZ/STF).
    """
    if brand not in SHOPIFY_BRANDS:
        return []

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    client = _get_client(brand)

    safe_title = product_title.replace("'", "''")
    products = client.execute_query(f"""
        SELECT ID FROM {fqn}.PRODUCT WHERE TITLE = '{safe_title}' AND STATUS = 'ACTIVE'
    """)
    if not products:
        return []

    variants: List[str] = []
    seen = set()
    for p in products:
        rows = client.execute_query(f"""
            SELECT DISTINCT pv.TITLE FROM {fqn}.PRODUCT_VARIANT pv
            WHERE pv.PRODUCT_ID = {p['ID']} AND pv.AVAILABLE_FOR_SALE = TRUE
        """)
        for r in rows:
            title = (r["TITLE"] or "").split(" / ")[0].strip()
            if title and title not in seen:
                seen.add(title)
                variants.append(title)
    return variants


def get_product_option_name(brand: str, product_title: str) -> Optional[str]:
    """Return the real, first-position Shopify option NAME for an exact, ACTIVE product
    title - e.g. "Fabric" (BUR Range Pro), "Size" (STF pillows), "Color". None if the
    product isn't found or has no option rows.

    This is NOT always "colorway"/"finish" - confirmed 2026-08-02 while wiring real
    inventory grounding for STF: "Sage Ribbon Suzani Outdoor Pillow" varies by Size, not
    color (the print/color is already baked into the product name). Used to label
    get_product_variants() output accurately in prompt grounding text instead of
    unconditionally calling every variant axis a "colorway" - describing a pillow's
    size options as "colorways" would itself invite the AI to write nonsensical copy
    like "in the 18x18 colorway."
    """
    if brand not in SHOPIFY_BRANDS:
        return None

    cfg = SHOPIFY_BRANDS[brand]
    fqn = f"{cfg['database']}.{cfg['schema']}"
    client = _get_client(brand)

    safe_title = product_title.replace("'", "''")
    products = client.execute_query(f"""
        SELECT ID FROM {fqn}.PRODUCT WHERE TITLE = '{safe_title}' AND STATUS = 'ACTIVE' LIMIT 1
    """)
    if not products:
        return None

    rows = client.execute_query(f"""
        SELECT NAME FROM {fqn}.PRODUCT_OPTION WHERE PRODUCT_ID = {products[0]['ID']}
        ORDER BY POSITION LIMIT 1
    """)
    if rows and rows[0].get("NAME"):
        return rows[0]["NAME"]
    return None


def format_inventory_for_prompt(
    products: List[ProductStock], max_items: int = 15, include_variants: bool = False,
) -> str:
    """Format product list as compact text for Claude prompt injection.

    Example output:
        - Range Sofa $1,895 (68,738 units) [Sofas]
        - Nomad Loveseat $1,295 (5,681 units) [Loveseats]

    With include_variants=True, appends each product's real, live colorway/finish
    options so a prompt can ground copy generation in what actually exists, e.g.:
        - Range Pro 76" 2-Seat Sofa $2,299-$3,249 (62 units) [Seating]
          colorways: Moss Green - Performance Flatweave, Georgia Clay - Performance
          Chenille, Camel - Top Grain Leather

    This is what makes a "never invent a colorway" prompt instruction actually
    enforceable instead of a hopeful ask with nothing behind it - confirmed gap
    2026-08-02 (BUR "Range Pro Highlight" briefed with 3 non-existent fabric colors).
    One extra Snowflake query per product - only enable for brands/flows that already
    pay for a small, curated product list (e.g. per-story BUR inventory context), not a
    large max_items sweep.
    """
    if not products:
        return "(No inventory data available)"

    lines = []
    for p in products[:max_items]:
        # Price display
        if p.min_price and p.max_price and p.min_price != p.max_price:
            price = f"${p.min_price:,.0f}-${p.max_price:,.0f}"
        elif p.min_price:
            price = f"${p.min_price:,.0f}"
        else:
            price = ""

        # Stock display
        if p.quantity_available is not None:
            stock = f"({p.quantity_available:,} units)"
        else:
            stock = f"({p.variant_count} variants available)"

        # Category
        cat = f" [{p.product_type}]" if p.product_type else ""

        line = f"- {p.product_title}"
        if price:
            line += f" {price}"
        line += f" {stock}{cat}"
        lines.append(line)

        if include_variants:
            try:
                variants = get_product_variants(p.brand, p.product_title)
                option_name = get_product_option_name(p.brand, p.product_title)
            except Exception:
                variants = []
                option_name = None
            if variants:
                # Label reflects the REAL Shopify option name (e.g. "Size" for STF
                # pillows, "Fabric" for BUR seating) - not a blanket "colorways/finishes"
                # for every product. Confirmed 2026-08-02: STF pillow variants are sizes
                # ('18" W x 18" H'), and calling that a "colorway" would itself invite the
                # AI to write nonsensical copy like "in the 18x18 colorway."
                label = f"{option_name} options" if option_name else "colorways/finishes"
                lines.append(f"  {label}: {', '.join(variants)}")

    return "\n".join(lines)


def get_inventory_summary(brand: str) -> Optional[Dict]:
    """Get a brief inventory summary for a brand (for gap analysis).

    Returns dict with 'top_categories' and 'total_products' or None on failure.
    """
    if brand not in SUPPORTED_BRANDS:
        return None

    try:
        categories = get_product_categories(brand)
        products = get_top_stocked_products(brand, limit=5)
        return {
            "top_categories": categories[:10],
            "top_products": [p.product_title for p in products[:5]],
            "total_products": len(products),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test inventory checker")
    parser.add_argument("--brand", type=str, default="BUR",
                        help="Brand code (BUR, CZ, STF, HAV)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max products to show")
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by product category")
    parser.add_argument("--search", type=str, default=None,
                        help="Search for a specific product")
    parser.add_argument("--categories", action="store_true",
                        help="List available categories")
    args = parser.parse_args()

    brand = args.brand.upper()

    if brand not in SUPPORTED_BRANDS:
        print(f"Error: Brand '{brand}' not supported.")
        print(f"Supported brands: {', '.join(sorted(SUPPORTED_BRANDS))}")
        sys.exit(1)

    try:
        if args.categories:
            print(f"\nProduct categories for {brand}:")
            for cat in get_product_categories(brand):
                print(f"  - {cat}")

        elif args.search:
            print(f"\nSearching {brand} for '{args.search}'...")
            result = check_product_availability(brand, args.search)
            if result:
                print(f"  Found: {result.product_title}")
                print(f"  Available: {result.is_available}")
                if result.quantity_available is not None:
                    print(f"  Stock: {result.quantity_available:,} units")
                print(f"  Variants: {result.variant_count}")
                if result.min_price:
                    print(f"  Price: ${result.min_price:,.0f}" +
                          (f" - ${result.max_price:,.0f}" if result.max_price != result.min_price else ""))
            else:
                print("  Not found.")

        else:
            print(f"\nTop {args.limit} in-stock products for {brand}:")
            products = get_top_stocked_products(brand, category=args.category, limit=args.limit)
            if products:
                print(format_inventory_for_prompt(products, max_items=args.limit))
            else:
                print("  No products found.")

    finally:
        close_all_clients()
