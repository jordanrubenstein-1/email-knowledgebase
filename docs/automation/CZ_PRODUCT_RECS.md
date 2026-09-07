# CZ Product Recommendations — Braze + Shopify System

AI-powered product recs for The Citizenry (CZ) emails, built entirely in Braze without engineering support. Uses Shopify's native recommendations API seeded with each user's last interaction anchor.

---

## How It Works (Non-Technical Summary)

Every time a CZ customer carts a product, purchases, or views a product page, Braze quietly stores a "recommendation anchor" on their profile — the best product from that interaction. When we send them an email, the email automatically calls Shopify's recommendation engine using that anchor and renders a personalized grid of 3–6 related products.

The system gracefully hides itself if there's no data (new users), if Shopify returns fewer than 3 in-stock products, or if the API fails.

---

## Architecture

### Three "Tracking" Canvases (write user attributes)

| Canvas | Trigger | What it does |
|---|---|---|
| `CZ - Track Cart Updated` | `ecommerce.cart_updated` | Stores the most expensive item's product ID as the anchor |
| `CZ - Track Order Placed` | `ecommerce.order_placed` | Same logic; purchase anchors take highest priority |
| `CZ - Track Product Viewed` | `custom_product_view` | Always writes `last_viewed_*`; only updates anchor if no fresh cart/purchase anchor |

### Priority Logic

**purchase > cart > view**

- `last_viewed_product_id` / `last_viewed_at` — written on every product view, no conditions
- `rec_anchor_product_id` — the anchor used at send time; only overwritten by a view if:
  - No cart or purchase anchor exists, OR
  - The existing cart/purchase anchor is more than 30 days old

**Swatch filter (cart + purchase):** The cart/purchase Canvases find the most expensive item in the `products` array. Since swatches cost ~$3.75 and furniture costs $300–$2,000+, swatches never win — no extra filtering needed.

### Nine Custom User Attributes

| Attribute | Type | Purpose |
|---|---|---|
| `last_viewed_product_id` | String | Shopify product ID of last viewed item |
| `last_viewed_at` | Time | Timestamp of last view |
| `last_carted_product_id` | String | Most expensive item's product ID from last cart |
| `last_carted_at` | Time | Timestamp of last cart update |
| `last_purchased_product_id` | String | Most expensive item's product ID from last order |
| `last_purchased_at` | Time | Timestamp of last purchase |
| `rec_anchor_product_id` | String | **The key** — used in the Shopify API call at send time |
| `rec_anchor_source` | String | `"view"`, `"cart"`, or `"purchase"` |
| `rec_anchor_at` | Time | Timestamp of when the anchor was set |

> `last_carted_at` and `last_purchased_at` are Time type so Braze's "more than X days ago" segment filter works on them.

### Two Browse-Window Attributes (added April 2026)

Written by "CZ - Track Browse Products" canvas (Webhook step, fires on `custom_product_view`, immediate re-entry). Runs in parallel with the nine attributes above.

| Attribute | Braze Type | Max Size | Purpose |
|---|---|---|---|
| `recently_browsed_products` | Array of Objects | **8** | Rolling window of up to 8 unique in-stock products viewed; deduplicated by `shopify_product_id` (newest variant wins); oldest dropped when full |
| `browse_affinity_categories` | Array of Strings | **8** | `product_type` values from the current 8-item window, sorted by view frequency descending; e.g. `["Bedding", "Rugs", "Accents"]` |

**Object schema for `recently_browsed_products`:**

| Field | Source | Notes |
|---|---|---|
| `product_id` | Catalog (`shopify_product_id`) | Dedupe key |
| `product_title` | Event (`product_title`) | Display name |
| `image_url` | Event (`image_url`), fallback catalog (`variant_image_url`) | CDN URL |
| `url` | Event (`variant_url`) | Full variant URL incl. `?v=` param — links back to exact variant viewed |
| `product_type` | Event (`product_type`) | e.g. "Accents", "Bedding", "Rugs" |
| `quantity_available` | Event (`quantity_available`) | At time of view; OOS products (qty=0) are never stored |
| `last_viewed_at` | Webhook compute time | ISO 8601 string |

**Abort conditions (in webhook Liquid):** SKU not in `the-citizenry_shopify_catalog` OR `quantity_available == 0`.

**Read by:** "CZ - Browse Abandon" canvas T1 email — `components/cz_browse_products_grid.liquid` (browsed products grid) + `components/cz_shopify_recs_browse_abandon.liquid` (recommendations).

**Purchase attribution:** The grid component sets `MESSAGE_EXTRAS.browsed_product_ids` (comma-separated `shopify_product_ids`) on every send, captured in `USERS_MESSAGES_EMAIL_SEND_SHARED.MESSAGE_EXTRAS` (Snowflake, CZ APP_GROUP_ID: `666672a4d8965b005ac6c1bd`). Join to `USERS_BEHAVIORS_PURCHASE_SHARED` on `USER_ID` within a 7-day window to attribute purchases to browsed products.

### Connected Content Blocks (render in emails)

Five blocks in `components/` — all share the same card rendering logic, different anchor sources:

| File | Use In | Anchor Source |
|---|---|---|
| `cz_shopify_recs_batch.liquid` | Batch / broadcast emails | `rec_anchor_product_id` user attribute |
| `cz_shopify_recs_cart_abandon.liquid` | Cart Abandon Canvas | Most expensive item in `canvas_entry_properties.products` |
| `cz_shopify_recs_browse_abandon.liquid` | Browse Abandon Canvas | `canvas_entry_properties.sku` → catalog lookup → Shopify product ID |
| `cz_shopify_recs_post_purchase.liquid` | Post-Purchase Canvas | Most expensive item in `canvas_entry_properties.products` |
| `cz_browse_products_grid.liquid` | Browse Abandon Canvas | `recently_browsed_products` user attribute (Array of Objects) — shows actual browsed products, not recommendations |

**Usage:** Paste the block at the top of the email template, then place `{{ rec_block }}` where the card grid should appear. `cz_browse_products_grid.liquid` is self-contained (no `{{ rec_block }}` needed — paste as an HTML block in drag-and-drop editor).

---

## Card Grid Behavior

| Condition | Result |
|---|---|
| No anchor set (new user) | Section hidden |
| Shopify API error / timeout | `:retry` once, then hidden |
| < 3 in-stock products returned | Hidden (prevents orphaned 1–2 card rows) |
| 3–5 in-stock products | 1 row of 3 cards |
| 6 in-stock products | 2 rows of 3 cards (max) |
| Duplicate product IDs in API response | Deduplicated |
| Product on sale | Original price with strikethrough; sale price in CZ rust (#b84a31) |
| No sale | Regular price in gray (#666666) |

**Card dimensions:** 190px × 190px, 3 per row, totaling 570px + 30px padding = 600px email width.

**Image optimization:** Images requested at `&width=380` (2× retina) from Shopify CDN — reduces image weight ~80–90% vs full-size originals.

**API caching:** `:cache_max_age 1800` — each unique anchor product ID cached 30 minutes. Prevents hammering Shopify's API on large sends.

---

## Shopify API

**Endpoint:** `https://www.the-citizenry.com/recommendations/products.json?product_id={ID}&limit=10`

**Test URL** (paste in browser while logged out):
```
https://www.the-citizenry.com/recommendations/products.json?product_id=7870675714235&limit=10
```

Shopify returns at most 10 products regardless of `limit`. Blocks filter down to 6 max (in-stock, deduplicated). Prices are returned in cents (e.g., `32700` = $327.00).

---

## Catalog

**Catalog name:** `the-citizenry_shopify_catalog`

Used by the Browse Abandon block and the Product Viewed Canvas to translate SKU → Shopify product ID (the `custom_product_view` event carries `sku` but not `product_id`).

Liquid lookup pattern:
```liquid
{% catalog_items the-citizenry_shopify_catalog {{canvas_entry_properties.sku}} %}
{% assign anchor_id = items[0].shopify_product_id %}
```

---

## UTM Attribution (GA4)

Each block uses a distinct `utm_campaign` value for GA4 tracking:

| Block | utm_campaign |
|---|---|
| Batch | `rec_block` |
| Cart Abandon | `cart_abandon_rec` |
| Browse Abandon | `browse_abandon_rec` |
| Post-Purchase | `post_purchase_rec` |

`utm_content` is set to the anchor product ID on all blocks.

---

## Implementation Notes

**Braze Webhook syntax:**
- `canvas_entry_properties.products` — no `${...}` brackets in Liquid logic tags
- `{% assign arr = canvas_entry_properties.products %}` then `{% for item in arr %}`
- Authorization header: `Bearer YOUR_API_KEY_HERE` (include "Bearer " prefix)
- `{{ braze_id }}` in webhook body (not `{{${braze_id}}}`)

**Time attributes:** ISO 8601 string written as `{{ 'now' | date: '%Y-%m-%dT%H:%M:%SZ' }}` — Braze parses it automatically for Time-type attributes.

**Canvas step for loops:** `{% for %}` loops only work in Webhook steps, not User Update steps. All multi-item iteration (cart + order events) uses Webhook steps calling Braze's `/users/track` endpoint.
