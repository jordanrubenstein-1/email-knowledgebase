# ID Warehouse Sale × Swatch-Match Email — Feasibility Memo

**Date:** 2026-07-04
**Question:** Can we email recent Interior Define swatch purchasers whose swatch fabric matches a warehouse-sale item currently in stock — e.g. *"A Celia Bed is available in the Spa Velvet from your recent swatch order"* — with a link to that item's product page?

**Verdict: Yes.** All three data requirements are met, verified live on 2026-07-04. A Celia Bed in ROY-008 "Spa" (Performance Velvet) was on the warehouse floor at the time of this check — the exact example above is buildable today.

---

## Requirement 1 — Live warehouse-sale inventory with product URLs ✅

**Source: Interior Define's public Magento GraphQL API** (`https://www.interiordefine.com/graphql`, no auth required). The `/warehouse` page is a JS single-page app, so the rendered page can't be scraped directly — but the GraphQL backend that powers it is openly queryable:

1. `urlResolver(url:"/warehouse")` → category id **660**
2. `products(filter:{category_id:{eq:"660"}}, pageSize:200, currentPage:N)` → **516 units** (as of 2026-07-04) with `sku`, `name`, `url_key`, sale/regular prices, and `stock_status`

**Inventory signal:** sold-out units are **not removed** from the category — they remain listed with `stock_status: OUT_OF_STOCK` (504 of 516 were `IN_STOCK`, 12 `OUT_OF_STOCK` at time of check). No numeric quantity is exposed via GraphQL, but each unit is one-of-one, so the binary flag is the complete inventory picture. The pipeline must filter to `stock_status = IN_STOCK`.

Each unit is a one-of-one item (SKU prefix `CAN.` + a unit serial like `EV0227471HV`). The PDP URL is simply `https://www.interiordefine.com/{url_key}`:

| Item | url_key (→ PDP URL) | Verified |
|---|---|---|
| Celia Bed (Spa) | `warehouse/qs-clia-fabric-bdrm-bed-ev0227471hv-1782944871` | HTTP 200, resolves to PRODUCT |
| Winslow Sectional (Spa) | `warehouse/qs-wins-fabric-sect-bumprght-3seat-sa0231844hv-1782944891` | resolves to PRODUCT |
| Nina Coffee Table | `warehouse/qs-nina-tbl-coff-sc0212363hv-1783007640` | resolves to PRODUCT |

**Why not Snowflake:** `PROD.ID_WAREHOUSE.INVENTORY_SNAPSHOT` is stale (last update 2025-01-09, rugs/lighting/accessories only) and `PRODUCTS` carries only ~30 live `INV.*` parent listings without per-unit fabric. **GraphQL is the only live source** for the warehouse floor; the pull must run same-day as any send.

## Requirement 2 — Fabric of each warehouse item ✅

The fabric color code is embedded in each unit's config SKU:

```
CAN.EV0227471HV.CLIA.FABRIC.BDRM.BED-ROY-008-Leg008-3-KING-...
                └─ Celia Bed          └─ ROY-008 = "Spa"
```

- **457 of 516 units** carry a fabric code validated against the 300-row fabric catalog `PROD.ID_WAREHOUSE.SWATCHES` (`COLOR_SKU`, `COLOR_NAME`, `FABRIC_MATERIAL`, `FABRIC_FAMILY`) — which also supplies the display name for copy ("Spa" + "Velvet" / "Performance Velvet").
- **93 distinct fabrics** are on the warehouse floor. Top: SE-172 Fawn (37 items), ROY-005 Mink (21), **ROY-008 Spa (16, incl. Celia Bed)**, SE-170 Marigold (15), ROY-006 Camel (14).
- The ~59 units without a fabric code are tables and some leather units — excluded from matching (or matched by leather code where present, e.g. `2210A` Palomino, which is also in the swatch catalog).

**Extraction caveats:** SKUs can carry two fabric codes (body + piping — the first is primary), and naive regex false-positives on tokens like `LENGTH-124` / `STORAGE-8519A`. Every extracted token must be validated against `SWATCHES.COLOR_SKU`.

## Requirement 3 — Match fabric to swatch orders ✅

`PROD.ID_WAREHOUSE.SWATCH_ORDER_ITEMS.SKU` **is the fabric color SKU** (`SE-172`, `ROY-008`, …) — the same code space as the warehouse SKUs. Join to `SWATCH_ORDERS` on `SWATCH_ORDER_ID` for `EMAIL`, `CREATED_AT`, `SALES_CHANNEL`, `IS_CONVERTED`. Data is near-real-time (fresher than the Braze datashare).

**Audience sizing** (self-serve `SALES_CHANNEL='Website'` swatchers whose swatch fabric matches ≥1 live warehouse item):

| Lookback | Matched emails |
|---|---|
| 30 days | ~9,200 |
| 60 days | ~20,100 |
| 90 days | ~30,000 (~27,700 excluding already-converted swatchers) |

**Braze matching:** join by **EMAIL** (warehouse `CUSTOMER_ID` ≠ Braze external_id). Swatchers since 2026-07-03 ~2:50pm ET are auto-subscribed at checkout; earlier swatchers are only emailable if they opted in.

**Qualified audience with subscription filter (verified 2026-07-04):** of the 27,729 matched 90-day emails (Website, not converted, in-stock fabric match), **20,535 (74%) are Subscribed or Opted In** in Braze — 6,327 unsubscribed, 867 with no Braze profile. Method: email → `USER_DEFAULT_ATTRIBUTES_VIEW_SHARED` → latest `USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED` row (ID TIER3 datashare; ~30-min lag; global state — subscription-group filters would trim slightly at send).

---

## Hero-match ranking (when a user matches multiple items)

Use the swatch checkout survey: `SWATCH_ORDERS.SWATCH_QUESTIONNAIRE` is a JSON string — `PARSE_JSON(...):type` = shopping-for. Verified values: `Sectionals`, `Sofas`, `Sleeper Sofas`, `Chairs/Chaises`, `Ottomans`, `Other` (comma-separated when multi-select; null when unanswered). It also carries `trade` (Yes/No).

1. **Selected categories win.** Any fabric-matching item in a shopping-for category outranks any item outside it. SKU segment map: Sectionals→`SECT` (non-sleeper) · Sofas→`SOFA` (non-sleeper) · Sleeper Sofas→`SOFA.SLEEPR`/`SSTWIN`/`SECT.SS*` · Chairs/Chaises→`CHAR` · Ottomans→`OTTO`.
2. **Within a tier, rank by price (highest first).** Worked example (user selected Bed + Ottoman): matching bed + ottoman + sofa available → **bed** (in shopping_for, more expensive than the ottoman); only ottoman + sofa available → **ottoman** (in shopping_for beats the pricier-or-not sofa); only sofa available → **sofa** (no shopping_for match, fall through to price ranking of what's left).
3. **Survey blank or `Other`** → rank purely by price (highest first). Beds are not a survey option, so pieces like the Celia Bed surface via price ranking.
4. Use the survey from the user's **most recent** qualifying swatch order.
5. **No fabric match at all → not in the audience.** The segment is only users with ≥1 in-stock warehouse item matching a swatch fabric; there is no generic-fallback send.

Email features **1 hero match** plus a "and N more pieces in fabrics from your swatch order" line linking to the `/warehouse` LP.

## Suppressions & hygiene

- **Already purchased:** exclude `SWATCH_ORDERS.IS_CONVERTED = TRUE` (drops ~2.3K of the 90-day pool).
- **No Trade suppression** for this send (per Jordan). The survey's `trade` field and `CUSTOMERS.CUSTOMER_GROUP_NAME` exist if that ever changes.
- **Subscription:** rely on Braze's send-time subscription filter; optionally pre-check via `POST /users/export/ids` by email.
- **Inventory volatility:** units are one-of-one and the June warehouse sale is actively selling (7 `INV.*`/warehouse orders since 6/16 in `ORDER_ITEMS`, which conveniently carries `COLOR`, `COLOR_SKU`, `FABRIC_MATERIAL` per purchase). **Pull inventory the same day as the send** and re-verify hero items just before launch; a sold hero falls back to the next-ranked match.

## Recommended build (not yet started)

1. **Matching script** (`scripts/analysis/` or `scripts/utils/`): GraphQL pull of category 660 filtered to `stock_status = IN_STOCK` → fabric-code extraction validated against `SWATCHES` → Snowflake swatch match (90-day, Website, suppressions above) → survey-driven ranking → output CSV: `email, hero_product_name, hero_fabric_display, hero_price, hero_url, other_match_count`.
2. **Braze sync:** resolve external_ids via `users/export/ids` (loop, one email per request), write per-user attributes via `users/track` (e.g. `wh_match_product`, `wh_match_fabric`, `wh_match_url`, `wh_match_count`).
3. **Campaign:** plain-text, `Lisa from the Interior Define Team` / HubSpot reply-to, Liquid personalization; abort-if-blank Liquid guard on the match attributes (the audience is only matched users, so a blank attribute means a sync failure — abort that send rather than fall back to generic copy); copy written via the Interior Define copywriter skill; naming per convention (no "Shop" in the name).
4. **Timing:** the warehouse sale has run since 6/17 ("up to 60% off"); this send works as a high-relevance mid/late-sale touch and is re-runnable for future warehouse drops.

**Effort estimate:** ~1 day — half for the matching script + dry-run review CSV, half for Braze attribute sync + campaign build/QA.

---

*Verified queries and the 516-unit inventory snapshot from this analysis are reproducible: GraphQL calls above, plus `SWATCH_ORDER_ITEMS`/`SWATCH_ORDERS`/`SWATCHES` joins in `PROD.ID_WAREHOUSE`.*
