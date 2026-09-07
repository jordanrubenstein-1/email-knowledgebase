---
name: reference-id-braze-cdi-de-attributes
description: Braze CDI SQL Editor setup for ID — syncing design expert first name + email as user attributes for swatch post-purchase canvas personalization
metadata: 
  node_type: memory
  type: reference
  originSessionId: 342140cb-48b5-4bf5-82e9-03b24e33294f
---

# ID — Braze CDI SQL Editor: Design Expert Attributes

## Overview

Braze CDI SQL Editor (beta, 2026) lets you write a `SELECT` query instead of pointing at a pre-built table with a `PAYLOAD` column. **User Attributes only** (beta limitation). Syncs against the existing source — no new credentials needed.

**Use case:** Swatch post-purchase canvas — personalize `from_name` and `reply_to` with the customer's assigned Interior Define design expert (DE).

**Braze trigger event name:** `"Swatch Order"` — NOT "Swatch Order Completed" (confirmed against TIER3 datashare; "Swatch Order Completed" returns 0 rows).

## CDI Source Reuse

Braze CDI separates Sources (credentials) from Syncs (queries). SQL Editor is a new Sync type that uses the **existing source** `BRAZE_INTERIOR_DEFINE` (warehouse `ETL_WAREHOUSE`, database `PROD`, schema `ID_WAREHOUSE`). No new Snowflake credentials needed.

To create: Data Settings → Cloud Data Ingestion → Syncs → Create New Sync → User Attributes → select existing source → SQL Editor.

## Data Source: `PROD.ID_WAREHOUSE.STG_CONTACTS`

HubSpot CRM staging table. The authoritative source for DE-to-customer assignment.

**Key columns:**
- `CONTACT_EMAIL` — customer email (join/identifier)
- `OWNER_EMAIL` — assigned DE in HubSpot (format `firstname.lastname@interiordefine.com`)
- `MAGENTO_CUSTOMER_ID`, `PRIMARY_HUBSPOT_ID` — alternative identifiers

**Why not `SWATCH_ORDERS.SALES_REP`?** That column is `system.admin` for 99% of swatch orders (162,621 of ~164,000 rows). DEs are assigned in HubSpot after the fact, not at order creation.

**Why not a DE name lookup table?** None exists in ID_WAREHOUSE — no `STG_OWNERS`, no first-name column anywhere. `INITCAP(SPLIT_PART(OWNER_EMAIL, '.', 1))` is the only option (e.g. `jessica.smith@interiordefine.com` → `Jessica`). Edge case: `jenée.satterwhite` would yield `Jenee` — acceptable tradeoff.

**Coverage (last 12 months, 126,849 unique swatch customers):**
- Matched to STG_CONTACTS: 97.5%
- Has a real DE (not IT account): 96.7% (~122,603 customers)
- Needs Liquid fallback: ~3.3% (~4,246 customers)
- Filter required: `OWNER_EMAIL != 'it@interiordefine.com'` (19K rows owned by IT account)

## CDI SQL Query

```sql
SELECT
    CONTACT_EMAIL                                        AS EMAIL,
    CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP)::TIMESTAMP_NTZ AS UPDATED_AT,
    OWNER_EMAIL                                          AS de_email,
    INITCAP(SPLIT_PART(OWNER_EMAIL, '.', 1))             AS de_first_name
FROM PROD.ID_WAREHOUSE.STG_CONTACTS
WHERE CONTACT_EMAIL IS NOT NULL
  AND OWNER_EMAIL IS NOT NULL
  AND OWNER_EMAIL != 'it@interiordefine.com'
  AND OWNER_EMAIL ILIKE '%@interiordefine.com'
```

**Required CDI column names (case-sensitive, uppercase):**
- `EMAIL` — Braze user identifier (matches by email if external_id not configured)
- `UPDATED_AT` — must be uppercase; controls incremental sync watermark
- Remaining columns become Braze custom attribute names: `de_email`, `de_first_name`

**First sync result (2026-06-11):** 428.3K records synced, 48 errors (0.01%). Braze shows "Partial success" for any run with ≥1 error. 48 errors = likely unmatched email addresses. Acceptable.

## Liquid Personalization in Canvas

```liquid
{{custom_attribute.${de_first_name} | default: 'the Interior Define Team'}}
{{custom_attribute.${de_email} | default: 'support@23765919.hubspot-inbox.com'}}
```

**`from_name`:** `Lisa from {{custom_attribute.${de_first_name} | default: 'the Interior Define Team'}}`
**`reply_to`:** `{{custom_attribute.${de_email} | default: 'support@23765919.hubspot-inbox.com'}}`

Recommended sync schedule: **Daily** (DE assignments change infrequently).
