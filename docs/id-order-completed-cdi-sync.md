# ID — `temp_last_order_completed_at` Braze CDI Sync

Temporary suppression backstop for the ID **`Order Completed`** event gap, delivered
via **Braze Cloud Data Ingestion (CDI) SQL Editor** — not a GitLab job.

## Why this exists

ID's `Order Completed` Braze event is **client-side**. Around **2025-09-22** ID cut
the event over from a server-side Segment source (`SEGMENT.INTERIOR_DEFINE_MAGENTO_SERVER`,
which stopped that day) to a client-side one (`INTERIOR_DEFINE_PRODUCTION_FRONTEND`,
which started that day). Since the cutover the event only fires when the customer
completes checkout in their own browser, so it misses orders placed by a DE / sales
rep (no customer browser) and orders lost to ad blockers.

Measured against warehouse orders:

| Order type | Server-side (pre-2025-09-22) | Client-side (now) |
|---|---|---|
| Rep-placed | 85.4% | ~38% |
| Web self-serve | 85.5% | ~91% |
| All (reaching Braze) | ~85% | ~68% |

Several Canvases (e.g. Swatch Post Purchase) use `Order Completed` as **exit criteria**,
so buyers whose event never fired are never exited and keep receiving post-purchase
nurture. This is the CX complaint that triggered the work.

**Permanent fix (eng):** restore a **server-side** Order Completed event feeding Braze.
Retire this sync once that lands.

## What the sync does

Writes the Braze custom attribute **`temp_last_order_completed_at`** (a **Time**
attribute) = the customer's most recent order in the last 6 months, for existing ID
Braze profiles matched by **email**.

- Set for **all** recent buyers, not just the "missed" ones — harmless, because buyers
  whose event fired are already exited by the real event; this only adds the backstop
  for the ones it missed. (Keeping it "missed-only" would require the CDI role to read
  the Braze datashare / `SEGMENT` DB, which it can't — and it changes no suppression
  outcome.)
- Matched by **email** — ID `external_id` is not reliable, so email is the join key.
  CDI updates matched profiles only; unmatched emails are skipped (never creates users).
- The **first sync is the one-off backfill**. Daily runs keep it current.

## CDI SQL

Source: `BRAZE_INTERIOR_DEFINE` (warehouse `ETL_WAREHOUSE`, database `PROD`, schema
`ID_WAREHOUSE`) — the same source as the DE-attributes CDI sync. Sync type: **User
Attributes**, **SQL Editor**.

```sql
SELECT
    LOWER(c.EMAIL)                          AS EMAIL,
    MAX(o.ORDER_CREATED_AT)::TIMESTAMP_NTZ  AS UPDATED_AT,
    MAX(o.ORDER_CREATED_AT)::TIMESTAMP_NTZ  AS temp_last_order_completed_at
FROM PROD.ID_WAREHOUSE.ORDERS o
JOIN PROD.ID_WAREHOUSE.CUSTOMERS c ON o.CUSTOMER_ID = c.CUSTOMER_ID
WHERE o.ORDER_CREATED_AT >= DATEADD('month', -6, CURRENT_TIMESTAMP())
  AND o.SALES_ORDER_ID IS NOT NULL
  AND c.EMAIL IS NOT NULL
GROUP BY LOWER(c.EMAIL)
```

### Column notes (important)

- **`EMAIL`** and **`UPDATED_AT`** are CDI **reserved** columns — the identifier and the
  incremental-sync watermark. They do **not** become profile attributes. Only
  `temp_last_order_completed_at` is created as an attribute.
- Both timestamp columns are cast `::TIMESTAMP_NTZ`:
  - `TIMESTAMP_NTZ` (not `TIMESTAMP_LTZ`) — CDI rejects LTZ (type-7 error).
  - A **timestamp type**, not `TO_CHAR(...)` — this is what makes Braze create
    `temp_last_order_completed_at` as a **Time** attribute rather than a String. In the
    CDI column-mapping step, confirm it is typed **Time**.
- `UPDATED_AT = MAX(ORDER_CREATED_AT)` so the watermark advances when a customer places a
  newer order, re-syncing just that row.

## Schedule

**Recurring, once daily** (if the frequency field takes a minutes interval, use `1440`).
Run **after the warehouse ETL settles** — ~10:00 UTC / 6am ET is safe; avoid 00:00 UTC.
The source refreshes ~daily, so more frequent syncs add cost with no freshness benefit.

## Suppression usage

Build the suppression / exit segment on **`temp_last_order_completed_at` after
{N} days ago** (time-bounded) so stale values self-expire — the sync does not clear old
values, and rows aging out of the 6-month window simply stop updating.

## Related

- Root cause + investigation: memory `reference_id_swatch_flow_trade_exit_gap`
- Order Completed payload structure: memory `reference_id_order_completed_event`
- DE-attributes CDI sync (same source/pattern): memory `reference_id_braze_cdi_de_attributes`
