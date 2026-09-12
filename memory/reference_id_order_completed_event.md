---
name: reference-id-order-completed-event
description: "Interior Define Order Completed Braze custom event — confirmed payload structure, product array schema, and Liquid extraction patterns"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2a863e31-55c7-49f5-97a7-902ef7367849
---

## Event basics

- **Event name**: `Order Completed`
- **Fires**: Once per order (not per item) — products is a JSON array
- **Volume**: ~7,500 events/90 days
- **Source**: TIER3 datashare — `DATALAKE_SHARING_TIERED.USERS_BEHAVIORS_CUSTOMEVENT_SHARED`

## Top-level properties

| Property | Type | Example |
|---|---|---|
| `order_id` | string | `"1100242886"` |
| `checkout_id` | string | `"776290"` |
| `total` | string (decimal) | `"3359.7000"` |
| `revenue` | string | `"2467.4500"` |
| `shipping` | string | `"299.0000"` |
| `discount` | string | `"-637.5000"` (negative) |
| `coupon` | string | `"CX25APPL13EKV"` (optional) |
| `currency` | string | `"USD"` |
| `affiliation` | string | `"Interior Define"` |
| `email` | string | customer email |
| `external_id` | string | `"interiordefine-507074"` |
| `content_names` | array | `["Sloan", "Sloan"]` — collection name per item |
| `content_ids` | array | `["13", "5210"]` — product IDs |
| `content_brand` | string | `"Interior Define"` |
| `contents` | array | flat summary: `[{id, item_name, item_brand, item_price}]` |
| `products` | array | full product details — see below |

**Note**: `content_names` contains the collection display name (e.g. "Sloan", "Maxwell"), not product name. Useful for canvas entry filters.

## `products` array — per-item schema

```json
{
  "product_id": "13",
  "hashed_id": "d67c789eda16ce388c7dee48b080df1c",
  "sku": "SLON.FABRIC.SOFA.STNDRD",
  "variant": "SLON.FABRIC.SOFA.STNDRD-SE-173-DEPTH-36-Leg001-1-LENGTH-83-CUSHION-2-DAR-10",
  "name": "Sloan Fabric 2-Seat Sofa",
  "price": "2280.0000",
  "url": "https://www.interiordefine.com/checkoutsuccess/...",
  "image_url": "https://content.cylindo.com/api/v2/4472/products/SLON.FABRIC.SOFA.STNDRD/frames/1/?background=FFFFFF&feature=COLOR:SE-173&feature=FINISH:LEG001-1&feature=CUSHIONS:CUSHION-2&feature=DEPTH:DEPTH-36"
}
```

## SKU structure

`COLLECTION.MATERIAL.CATEGORY.SUBTYPE` — split by `.`

| Index | Field | Example values |
|---|---|---|
| `[0]` | Collection code | SLON, MXWL, JMES, ALXR, ROWN, DAPH, MRSH, CLIA, etc. |
| `[1]` | Material | FABRIC, LEATHR, ART |
| `[2]` | Category | SOFA, CHAR, OTTO, BDRM, DINING, BENCH, STOOL |
| `[3]` | Subtype | STNDRD, SLEEPR, SSTWIN, DAYBED, SLPCOV, ACCENT, SWIVEL, etc. |

Collection codes for post-purchase canvas: `SLON`, `MXWL`, `JMES`
Sleeper subtypes: `SLEEPR` (sleeper sofa), `SSTWIN` (twin sleeper) — `TWNSLEPR` does NOT exist in real event data
Material types: `FABRIC`, `LEATHR`, `SLPCOV` (slipcover); also `INV.` prefix for quick-ship inventory variants (e.g. `INV.SLON.FABRIC.SOFA.SLEEPR`)

**CDI SQL pattern for Sloan sleeper suppression:**
```sql
WHERE (oi.SKU LIKE '%SLON%.SOFA.SLEEPR%' OR oi.SKU LIKE '%SLON%.SOFA.SSTWIN%')
```
Cast `UPDATED_AT` as `::TIMESTAMP_NTZ` — Braze CDI rejects `TIMESTAMP_LTZ` (type code 7).

## Cylindo `image_url` — color and leg extraction

When fabric is selected at order time, `image_url` is a Cylindo URL:
```
https://content.cylindo.com/api/v2/4472/products/SLON.FABRIC.SOFA.STNDRD/frames/1/
  ?background=FFFFFF
  &feature=COLOR:SE-173       ← fabric/color code
  &feature=FINISH:LEG001-1    ← leg finish code
  &feature=CUSHIONS:CUSHION-2 ← cushion style (not needed for cross-sell Liquid)
  &feature=DEPTH:DEPTH-36     ← depth (not needed for cross-sell Liquid)
```

**Extract in Liquid:**
```liquid
{% assign color = product.image_url | split: 'COLOR:' | last | split: '&' | first %}
{% assign leg = product.image_url | split: 'FINISH:' | last | split: '&' | first %}
```

## Edge cases

### 1. Select-fabric-later orders
Some customers order without choosing fabric. In these cases:
- `variant` contains `select-fabric-later` instead of a color code
- `image_url` falls back to a static interiordefine.com catalog image (NOT Cylindo)
  ```
  https://www.interiordefine.com/media/catalog/product/s/l/slon.fabric.sofa.stndrd_6.jpg
  ```
- Color and leg cannot be extracted — `image_url` does not contain `COLOR:` or `FINISH:`
- **Action**: the brief's existing fallback (`{% if color != blank and legs != blank %}`) handles this correctly — static fallback email renders

**Guard in Liquid:**
```liquid
{% if product.image_url contains 'cylindo.com' %}
  {% assign color = product.image_url | split: 'COLOR:' | last | split: '&' | first %}
  {% assign leg = product.image_url | split: 'FINISH:' | last | split: '&' | first %}
{% endif %}
```

### 2. Warranty/add-on items
Mulberry warranty items appear in the products array:
- `sku`: `mulberry-warranty-60-months`, `mulberry-warranty-24-months`
- `image_url`: static interiordefine.com image (not Cylindo)
- **Action**: `sku_parts[2] == 'SOFA'` check skips these automatically

### 3. Multi-item orders
Confirmed: customers regularly order sofa + ottoman + warranty + other items in one order. Examples seen:
- Sloan sofa + Sloan ottoman + 2x warranty
- Celia bed + Sloan sofa
- Rose chair + Maxwell ottoman

**Action**: Liquid `for` loop must filter to `SOFA` category and qualifying collection — do not assume `products[0]` is the sofa.

### 4. Non-Cylindo products
Art pieces (e.g. `PORT.ART.2432.FGRT.NATURAL`) use a standard product image URL. The SKU structure breaks the 4-segment pattern. The SOFA check handles this.

## Liquid patterns for User Update steps

### Collection code
```liquid
{% assign col = '' %}
{% for product in canvas_entry_properties.${products} %}
  {% assign sku_parts = product.sku | split: '.' %}
  {% if sku_parts[2] == 'SOFA' %}
    {% if sku_parts[0] == 'SLON' or sku_parts[0] == 'MXWL' or sku_parts[0] == 'JMES' %}
      {% assign col = sku_parts[0] %}
    {% endif %}
  {% endif %}
{% endfor %}
{{col | strip}}
```

### Color code
```liquid
{% assign color = '' %}
{% for product in canvas_entry_properties.${products} %}
  {% assign sku_parts = product.sku | split: '.' %}
  {% if sku_parts[2] == 'SOFA' %}
    {% if sku_parts[0] == 'SLON' or sku_parts[0] == 'MXWL' or sku_parts[0] == 'JMES' %}
      {% if product.image_url contains 'cylindo.com' %}
        {% assign color = product.image_url | split: 'COLOR:' | last | split: '&' | first %}
      {% endif %}
    {% endif %}
  {% endif %}
{% endfor %}
{{color | strip}}
```

### Leg code
```liquid
{% assign leg = '' %}
{% for product in canvas_entry_properties.${products} %}
  {% assign sku_parts = product.sku | split: '.' %}
  {% if sku_parts[2] == 'SOFA' %}
    {% if sku_parts[0] == 'SLON' or sku_parts[0] == 'MXWL' or sku_parts[0] == 'JMES' %}
      {% if product.image_url contains 'cylindo.com' %}
        {% assign leg = product.image_url | split: 'FINISH:' | last | split: '&' | first %}
      {% endif %}
    {% endif %}
  {% endif %}
{% endfor %}
{{leg | strip}}
```

## Canvas entry filter recommendation

For the attribute-writing canvas, filter entry on `content_names` contains "Sloan" OR "Maxwell" OR "James" — this is a top-level array property and easier to filter on than nested `products.sku`. The Liquid for loop inside the User Update step provides the fine-grained SOFA-category guard.

For the Sloan Sleeper flag: use CDI SQL (not canvas entry filter) — Braze cannot filter on nested array-of-objects properties. CDI query uses `LIKE '%SLON%.SOFA.SLEEPR%' OR LIKE '%SLON%.SOFA.SSTWIN%'` against `PROD.ID_WAREHOUSE.ORDER_ITEMS.SKU`.
