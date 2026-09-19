# Snowflake Data Audit

**Date**: 2026-02-20
**Purpose**: Inventory of available data in Snowflake across Airbyte and Fivetran pipelines, with focus on GA4 analytics and product inventory for stock-aware email recommendations.

---

## 1. Databases & Access

| Database | Pipeline | Role |
|----------|----------|------|
| `AIRBYTE_DATABASE` | Airbyte | `MCP_READER` |
| `FIVETRAN_DB` | Fivetran | `MCP_READER` |
| `PROD` | Internal | `MCP_READER` |
| `ROCKERBOX_BURROW` | Data Share | `MCP_READER` |
| `ROCKERBOX_CITIZENRY` | Data Share | `MCP_READER` |
| `ROCKERBOX_HAVENLY` | Data Share | `MCP_READER` |
| `ROCKERBOX_INTERIORDEFINE` | Data Share | `MCP_READER` |

---

## 2. GA4 Session Data

GA4 data flows through Airbyte into `AIRBYTE_DATABASE`. Used for attributing sessions, purchases, and revenue to email/SMS campaigns.

### Available Brands

| Brand | Schema | Table | Last Sync | Status |
|-------|--------|-------|-----------|--------|
| Burrow | `LANDING_BURROW_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` | Daily | Active |
| The Citizenry | `LANDING_CITIZENRY_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` | Daily | Active |
| Interior Define | `LANDING_INTERIORDEFINE_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` | Daily | Active |

### Missing Brands (No Airbyte Connector)

| Brand | Expected Schema | Status |
|-------|----------------|--------|
| Havenly | `LANDING_HAVENLY_GA4` | **Not provisioned** |
| St. Frank | `LANDING_STFRANK_GA4` | **Not provisioned** |
| The Inside | `LANDING_THEINSIDE_GA4` | **Not provisioned** |

### GA4 Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `SESSIONCAMPAIGNNAME` | TEXT | Campaign name for matching to Braze |
| `SESSIONPRIMARYCHANNELGROUP` | TEXT | Email / SMS attribution |
| `SESSIONS` | NUMBER | Total sessions |
| `ECOMMERCEPURCHASES` | NUMBER | Purchase count |
| `TOTALREVENUE` | FLOAT | Revenue |
| `DATE` | TEXT | YYYYMMDD format |

Campaign name matching is working at 90-94% across all 3 brands.

---

## 3. Product Inventory Data

### 3a. Burrow — Netsuite via Airbyte

**Database**: `AIRBYTE_DATABASE`

| Table | Schema | Rows | Last Sync |
|-------|--------|------|-----------|
| `INVENTORYITEMLOCATIONS` | `LANDING_BURROW_NETSUITE2` | 69,310 | 2026-02-20 |
| `ITEM` | `LANDING_BURROW_NETSUITE2` | 21,312 | 2026-02-20 |
| `LOCATION` | `LANDING_BURROW_NETSUITE2` | 95 | 2026-02-20 |
| `INVENTORYITEM` | `LANDING_BURROW_NETSUITE` | 2,436 | 2026-01-04 |

**Stock query pattern** (join ITEM for product names):
```sql
SELECT
    i.FULLNAME, i.DISPLAYNAME, i.ITEMID, i.ITEMTYPE,
    i.CUSTITEM_CATEGORY, i.CUSTITEM_SUB_CATEGORY, i.CLASS,
    SUM(l.QUANTITYAVAILABLE::NUMBER) AS total_available,
    SUM(l.QUANTITYONHAND::NUMBER) AS total_on_hand,
    SUM(COALESCE(l.QUANTITYONORDER::NUMBER, 0)) AS total_on_order,
    SUM(COALESCE(l.QUANTITYCOMMITTED::NUMBER, 0)) AS total_committed
FROM AIRBYTE_DATABASE.LANDING_BURROW_NETSUITE2.INVENTORYITEMLOCATIONS l
JOIN AIRBYTE_DATABASE.LANDING_BURROW_NETSUITE2.ITEM i ON l.ITEM = i.ID
WHERE l.QUANTITYAVAILABLE::NUMBER > 0
  AND i.ISINACTIVE = 'F'
GROUP BY 1,2,3,4,5,6,7
ORDER BY total_available DESC
```

**Key columns in INVENTORYITEMLOCATIONS** (Airbyte schema — values are VARCHAR, cast to NUMBER):
- `ITEM` — FK to ITEM.ID
- `LOCATION` — FK to LOCATION.ID
- `QUANTITYAVAILABLE` — Available to sell
- `QUANTITYONHAND` — Physical on hand
- `QUANTITYONORDER` — Purchase orders
- `QUANTITYCOMMITTED` — Allocated to orders
- `QUANTITYBACKORDERED` — Customer backorders
- `LASTQUANTITYAVAILABLECHANGE` — Last stock change timestamp

**Warehouse locations**: Flexport (DFW, EWR, LAX, Returns), Floorfound, Plenish (East Coast, Vancouver), Metro Eastvale, plus Canadian warehouses.

**Scale**: 1,048 active items with stock, ~437K total units available.

---

### 3b. The Citizenry — Netsuite via Fivetran

**Database**: `FIVETRAN_DB`

| Table | Schema | Rows | Last Sync |
|-------|--------|------|-----------|
| `INVENTORYITEMLOCATIONS` | `LANDING_CZ_NETSUITE` | 1,082,080 | 2026-02-20 |
| `ITEM` | `LANDING_CZ_NETSUITE` | 8,634 | 2026-02-20 |
| `LOCATION` | `LANDING_CZ_NETSUITE` | 37 | 2026-02-20 |
| `INVENTORYBALANCE` | `LANDING_CZ_NETSUITE` | 151,489 | 2026-02-20 |

**Stock query pattern** (Fivetran schema — columns are native FLOAT, no casting needed):
```sql
SELECT
    i.FULLNAME, i.DISPLAYNAME, i.ITEMID, i.ITEMTYPE,
    i.CUSTITEM_ITEM_COLLECTION, i.CUSTITEM_ITEM_COLLECTION_SUB,
    SUM(l.QUANTITYAVAILABLE) AS total_available,
    SUM(l.QUANTITYONHAND) AS total_on_hand,
    SUM(COALESCE(l.QUANTITYONORDER, 0)) AS total_on_order,
    SUM(COALESCE(l.QUANTITYCOMMITTED, 0)) AS total_committed
FROM FIVETRAN_DB.LANDING_CZ_NETSUITE.INVENTORYITEMLOCATIONS l
JOIN FIVETRAN_DB.LANDING_CZ_NETSUITE.ITEM i ON l.ITEM = i.ID
WHERE l.QUANTITYAVAILABLE > 0
  AND i.ISINACTIVE = 'No'
  AND (l._FIVETRAN_DELETED IS NULL OR l._FIVETRAN_DELETED = FALSE)
GROUP BY 1,2,3,4,5,6
ORDER BY total_available DESC
```

**Key columns** (same as Burrow but native FLOAT types):
- `ITEM` — FK to ITEM.ID (NUMBER)
- `LOCATION` — FK to LOCATION.ID (NUMBER)
- `QUANTITYAVAILABLE`, `QUANTITYONHAND`, `QUANTITYONORDER`, `QUANTITYCOMMITTED`, `QUANTITYBACKORDERED` — all FLOAT
- `_FIVETRAN_DELETED` — soft-delete flag (filter out TRUE)

---

### 3c. Interior Define — Netsuite via Fivetran

**Database**: `FIVETRAN_DB`

| Table | Schema | Rows | Last Sync |
|-------|--------|------|-----------|
| `INVENTORYITEMLOCATIONS` | `LANDING_NETSUITE_ID` | 10,563,390 | **2025-11-13** |
| `ITEM` | `LANDING_NETSUITE_ID` | 94,292 | Unknown |
| `LOCATION` | `LANDING_NETSUITE_ID` | 61 | Unknown |

**Same schema as CZ** (Fivetran Netsuite connector). Same query pattern.

**STATUS: STALE** — Last synced 2025-11-13. The Fivetran connector may be paused or broken. Needs investigation before using for stock checks.

---

### 3d. St. Frank — Shopify via Fivetran

**Database**: `FIVETRAN_DB`

| Table | Schema | Rows | Last Sync |
|-------|--------|------|-----------|
| `PRODUCT_VARIANT` | `LANDING_STF_SHOPIFY` | 8,951 | 2026-02-20 |
| `PRODUCT` | `LANDING_STF_SHOPIFY` | 6,182 | 2026-02-20 |
| `INVENTORY_QUANTITY` | `LANDING_STF_SHOPIFY` | 97,672 | 2026-02-20 |
| `INVENTORY_LEVEL` | `LANDING_STF_SHOPIFY` | 15,122 | 2026-02-20 |
| `INVENTORY_ITEM` | `LANDING_STF_SHOPIFY` | 9,377 | 2026-02-20 |
| `LOCATION` | `LANDING_STF_SHOPIFY` | 22 | 2026-02-20 |
| `COLLECTION` | `LANDING_STF_SHOPIFY` | 594 | 2026-02-20 |
| `COLLECTION_PRODUCT` | `LANDING_STF_SHOPIFY` | 76,637 | 2026-02-20 |

**Stock query pattern** (Shopify schema):
```sql
SELECT
    p.TITLE AS product_title,
    pv.TITLE AS variant_title,
    pv.SKU,
    pv.INVENTORY_QUANTITY,
    pv.PRICE,
    pv.AVAILABLE_FOR_SALE
FROM FIVETRAN_DB.LANDING_STF_SHOPIFY.PRODUCT_VARIANT pv
JOIN FIVETRAN_DB.LANDING_STF_SHOPIFY.PRODUCT p ON pv.PRODUCT_ID = p.ID
WHERE pv.INVENTORY_QUANTITY > 0
ORDER BY pv.INVENTORY_QUANTITY DESC
```

**Detailed inventory breakdown** (INVENTORY_QUANTITY table):

| Quantity Type | Total |
|--------------|-------|
| on_hand | 5,382,856 |
| available | 5,378,280 |
| committed | 4,574 |
| reserved | 2 |
| damaged | 0 |
| safety_stock | 0 |
| incoming | 0 |

**Key columns in PRODUCT_VARIANT**:
- `PRODUCT_ID` — FK to PRODUCT.ID
- `INVENTORY_ITEM_ID` — FK to INVENTORY_ITEM.ID
- `INVENTORY_QUANTITY` — Total available
- `AVAILABLE_FOR_SALE` — Boolean
- `SKU`, `TITLE`, `PRICE`
- `INVENTORY_POLICY` — DENY (can't oversell) or CONTINUE

**Scale**: 1,721 variants with stock across 6,182 products.

---

### 3e. Havenly — Product Catalog via Airbyte

**Database**: `AIRBYTE_DATABASE`

| Table | Schema | Rows | Last Sync |
|-------|--------|------|-----------|
| `AVAILABILITIES` | `LANDING_HAVENLY_PRODUCTS` | 170,818,544 | 2026-02-20 |
| `VENDOR_VARIANTS` | `LANDING_HAVENLY_PRODUCTS` | 92,331,688 | 2026-02-20 |
| `PRICES` | `LANDING_HAVENLY_PRODUCTS` | 189,685,958 | 2026-02-20 |
| `AVAILABILITY_TYPES` | `LANDING_HAVENLY_PRODUCTS` | 4 | 2026-02-20 |
| `VENDOR_VARIANT_GROUPS` | `LANDING_HAVENLY_PRODUCTS` | 2,302,748 | 2026-02-20 |
| `TAXONOMIES` | `LANDING_HAVENLY_PRODUCTS` | 5,403 | 2026-02-20 |

**Availability query pattern**:
```sql
SELECT
    a.VENDOR_VARIANT_ID,
    a.IS_AVAILABLE,
    at.TITLE AS availability_type,
    a.MODIFIED
FROM AIRBYTE_DATABASE.LANDING_HAVENLY_PRODUCTS.AVAILABILITIES a
JOIN AIRBYTE_DATABASE.LANDING_HAVENLY_PRODUCTS.AVAILABILITY_TYPES at
    ON a.AVAILABILITY_TYPE_ID = at.ID
WHERE a.IS_AVAILABLE = TRUE
```

**Availability types**:

| ID | Type | Description |
|----|------|-------------|
| 1 | `in_stock` | In stock (manual) |
| 2 | `in_stock_api` | In stock (API-fed) |
| 3 | `back_ordered` | Back ordered (manual) |
| 4 | `back_ordered_api` | Back ordered (API-fed) |

**Limitation**: Boolean availability only (IS_AVAILABLE true/false) — no quantity depth. Sufficient to know if a product can be promoted, but not how deep the stock is. 95.7M unique vendor variants tracked.

---

### 3f. The Inside — No Inventory Data Found

No Netsuite, Shopify, or product inventory data found for The Inside in either Airbyte or Fivetran databases. The `FIVETRAN_DB.LANDING_THEINSIDE_THEINSIDE` schema exists but was not explored.

---

## 4. Braze Engagement Data

**Status: Not available in Snowflake.**

No Braze Datashare tables found in any accessible database or schema. The `MCP_READER` role does not have access to Braze event-level data (sends, opens, clicks). This data is currently sourced via the Braze API during campaign import.

---

## 5. Other Data Sources

| Schema | Database | Description |
|--------|----------|-------------|
| `LANDING_HAVENLY_MYSQL` | Airbyte | Havenly app database (designers, rooms, orders) — mostly 0-row tables |
| `LANDING_BURROW_FACEBOOK` | Airbyte | Burrow Facebook ads data |
| `LANDING_GOOGLE_ADS` | Airbyte | Google Ads data |
| `LANDING_GOOGLE_SHEETS` | Airbyte | Google Sheets data |
| `LANDING_HUBSPOT` | Airbyte | HubSpot CRM data |
| `LANDING_BURROW_SHOPIFY` | Fivetran | Burrow Shopify (in addition to Netsuite) |
| `LANDING_CZ_SHOPIFY` | Fivetran | CZ Shopify (in addition to Netsuite) |
| `PROD.ANALYTICS_*` | Internal | Brand-level analytics schemas (Burrow, Citizenry, St. Frank, The Inside) |

---

## 6. Summary: Stock Check Readiness by Brand

| Brand | Source | Quantity Data? | Fresh? | Ready for Stock-Aware Recs? |
|-------|--------|---------------|--------|----------------------------|
| **Burrow** | Netsuite (Airbyte) | Full (available, on hand, on order, committed, backordered) | Daily | **Yes** |
| **The Citizenry** | Netsuite (Fivetran) | Full (same as Burrow) | Daily | **Yes** |
| **Interior Define** | Netsuite (Fivetran) | Full (same schema) | **Nov 2025 — STALE** | **No — fix connector first** |
| **St. Frank** | Shopify (Fivetran) | Full (on hand, available, committed + variant-level qty) | Daily | **Yes** |
| **Havenly** | Products DB (Airbyte) | Boolean only (in_stock / back_ordered) | Daily | **Partial** — no quantity depth |
| **The Inside** | None | None | N/A | **No data** |

---

## 7. Action Items

1. **Fix ID Fivetran connector** — `FIVETRAN_DB.LANDING_NETSUITE_ID` last synced 2025-11-13. Check if paused or broken.
2. **Provision GA4 Airbyte connectors** for HAV, STF, TI — code is ready in `scripts/import_ga4_metrics_snowflake.py` (schemas commented out at line 93-95).
3. **Evaluate Braze Datashare** — Would allow querying send/open/click data from Snowflake instead of Braze API. Requires provisioning by Braze admin.
4. **Explore The Inside data** — Check `FIVETRAN_DB.LANDING_THEINSIDE_THEINSIDE` for any inventory data. If TI uses Shopify, inventory may be there.
5. **Schema differences** — Airbyte (Burrow Netsuite) stores quantities as VARCHAR (need `::NUMBER` cast). Fivetran (CZ, ID Netsuite) uses native FLOAT. Shopify (STF) uses native NUMBER. Any shared utility module needs to handle these differences.

---

## 8. Schema Quick Reference

### Netsuite (Airbyte) — Burrow
```
AIRBYTE_DATABASE.LANDING_BURROW_NETSUITE2.INVENTORYITEMLOCATIONS
  ITEM (VARCHAR) → ITEM.ID
  LOCATION (VARCHAR) → LOCATION.ID
  QUANTITYAVAILABLE (VARCHAR, cast ::NUMBER)
  QUANTITYONHAND, QUANTITYONORDER, QUANTITYCOMMITTED, QUANTITYBACKORDERED
```

### Netsuite (Fivetran) — CZ, ID
```
FIVETRAN_DB.LANDING_CZ_NETSUITE.INVENTORYITEMLOCATIONS
  ITEM (NUMBER) → ITEM.ID
  LOCATION (NUMBER) → LOCATION.ID
  QUANTITYAVAILABLE (FLOAT)
  QUANTITYONHAND, QUANTITYONORDER, QUANTITYCOMMITTED, QUANTITYBACKORDERED
  _FIVETRAN_DELETED (BOOLEAN) — filter out TRUE
```

### Shopify (Fivetran) — STF
```
FIVETRAN_DB.LANDING_STF_SHOPIFY.PRODUCT_VARIANT
  PRODUCT_ID (NUMBER) → PRODUCT.ID
  INVENTORY_ITEM_ID (NUMBER) → INVENTORY_ITEM.ID
  INVENTORY_QUANTITY (NUMBER)
  AVAILABLE_FOR_SALE (BOOLEAN)
  SKU, TITLE, PRICE
```

### Havenly Products (Airbyte)
```
AIRBYTE_DATABASE.LANDING_HAVENLY_PRODUCTS.AVAILABILITIES
  VENDOR_VARIANT_ID (NUMBER) → VENDOR_VARIANTS.ID
  IS_AVAILABLE (BOOLEAN)
  AVAILABILITY_TYPE_ID (NUMBER) → AVAILABILITY_TYPES.ID
```
