-- Braze CDI SQL Syncs — Sloan / Maxwell / James cross-sell canvas
-- Source: PROD.ID_WAREHOUSE (Snowflake)
-- CDI source: BRAZE_INTERIOR_DEFINE (existing source, add new Syncs under it)
-- Braze requires UPDATED_AT as TIMESTAMP_NTZ — cast ::TIMESTAMP_NTZ to avoid type code 7 rejection

-- ============================================================
-- SYNC 1: purchased_sloan_sleeper (boolean)
-- Purpose: suppress sleeper buyers from the cross-sell canvas entirely
-- Confirmed working: 1,725 profiles synced
-- Covers: Sloan sleeper sofa (SLEEPR), Sloan twin sleeper (SSTWIN),
--         Sloan sectional sleepers (SECT.SS* — SSLEFT, SSRGHT, etc.)
-- Note: leather sleeper sofas also excluded here
-- ============================================================

SELECT
  'interiordefine-' || c.CUSTOMER_ID::VARCHAR        AS EXTERNAL_ID,
  MAX(o.UPDATED_AT)::TIMESTAMP_NTZ                   AS UPDATED_AT,
  TRUE                                               AS purchased_sloan_sleeper
FROM PROD.ID_WAREHOUSE.ORDER_ITEMS oi
JOIN PROD.ID_WAREHOUSE.ORDERS o    ON oi.SALES_ORDER_ID = o.SALES_ORDER_ID
JOIN PROD.ID_WAREHOUSE.CUSTOMERS c ON o.CUSTOMER_ID    = c.CUSTOMER_ID
WHERE (oi.SKU LIKE '%SLON%.SOFA.SLEEPR%'
    OR oi.SKU LIKE '%SLON%.SOFA.SSTWIN%'
    OR oi.SKU LIKE '%SLON%.SECT.SS%')
GROUP BY c.CUSTOMER_ID;


-- ============================================================
-- SYNC 2: six personalization attributes for Cylindo image rendering
-- Purpose: power dynamic cross-sell email (Email 1 + Email 2) in the canvas
-- Writes: first_order_cylindo_collection_code, first_order_cylindo_color_code,
--         first_order_cylindo_leg_code, first_order_cylindo_material,
--         first_order_has_piping, first_order_cylindo_piping_color_code
--
-- Canvas audience path logic (set in Braze audience paths):
--   first_order_cylindo_material != LEATHR AND first_order_has_piping = false → Email 1 + Email 2
--   first_order_cylindo_material  = LEATHR                                    → Email 2 only
--   first_order_has_piping = true                                              → hold; attributes set for future piping path
--
-- Legacy fabric codes (OTE-*, AK-618-*, 8519A, 2210A) affect ~7 customers per 90 days.
-- These are stored as-is; Liquid in email uses fallback to MER-002 if Cylindo render fails.
--
-- Select-fabric-later orders: COLOR_SKU is null at order time; COALESCE applies MER-002
-- placeholder so the user still enters the canvas. When the buyer selects fabric, ORDERS.UPDATED_AT
-- bumps within seconds → CDI re-syncs automatically, replacing the placeholder with the real code.
--
-- James sofas have no legs (LEGS_SKU always null) → first_order_cylindo_leg_code set to NULL for JMES.
-- ============================================================

SELECT
  'interiordefine-' || c.CUSTOMER_ID::VARCHAR         AS EXTERNAL_ID,
  o.UPDATED_AT::TIMESTAMP_NTZ                         AS UPDATED_AT,
  SPLIT_PART(oi.SKU, '.', 1)                          AS first_order_cylindo_collection_code,
  COALESCE(oi.COLOR_SKU, 'MER-002')                   AS first_order_cylindo_color_code,
  CASE
    WHEN SPLIT_PART(oi.SKU, '.', 1) = 'JMES' THEN NULL
    ELSE COALESCE(oi.LEGS_SKU, 'Leg001-1')
  END                                                  AS first_order_cylindo_leg_code,
  SPLIT_PART(oi.SKU, '.', 2)                          AS first_order_cylindo_material,
  CASE WHEN oi.SKU LIKE '%.PIPING' THEN TRUE ELSE FALSE END
                                                       AS first_order_has_piping,
  CASE
    WHEN oi.SKU LIKE '%.PIPING'
     AND oi.COLOR_SKU IS NOT NULL
     AND oi.COLOR_SKU != 'select-fabric-later'
    THEN REGEXP_SUBSTR(oi.ITEM_SKU, oi.COLOR_SKU || '-([A-Z]+-[0-9]+)', 1, 1, 'e', 1)
    ELSE NULL
  END                                                  AS first_order_cylindo_piping_color_code
FROM PROD.ID_WAREHOUSE.ORDER_ITEMS oi
JOIN PROD.ID_WAREHOUSE.ORDERS o    ON oi.SALES_ORDER_ID = o.SALES_ORDER_ID
JOIN PROD.ID_WAREHOUSE.CUSTOMERS c ON o.CUSTOMER_ID     = c.CUSTOMER_ID
WHERE oi.SKU IN (
  -- Sloan fabric + slipcover (Email 1 + 2)
  'SLON.FABRIC.SOFA.STNDRD', 'SLON.FABRIC.SOFA.3SEAT',
  'SLON.SLPCOV.SOFA.STNDRD', 'SLON.SLPCOV.SOFA.3SEAT',
  -- Sloan leather (Email 2 only — filtered in canvas via first_order_cylindo_material)
  'SLON.LEATHR.SOFA.STNDRD', 'SLON.LEATHR.SOFA.3SEAT',
  -- Maxwell fabric: STNDRD=2-seat, APRTMT=apartment sofa+loveseat (LENGTH-74), 3SEAT (Email 1 + 2)
  -- Excluded: TALL variants (we feature Maxwell Tall in email), slipcover, piping
  'MXWL.FABRIC.SOFA.STNDRD', 'MXWL.FABRIC.SOFA.3SEAT', 'MXWL.FABRIC.SOFA.APRTMT',
  -- Maxwell leather (Email 2 only)
  'MXWL.LEATHR.SOFA.STNDRD', 'MXWL.LEATHR.SOFA.3SEAT', 'MXWL.LEATHR.SOFA.APRTMT',
  -- James fabric non-piping (Email 1 + 2)
  'JMES.FABRIC.SOFA.2SEAT', 'JMES.FABRIC.SOFA.3SEAT', 'JMES.FABRIC.SOFA.LOVESEAT',
  -- James piping (attributes set; held from email via first_order_has_piping = TRUE; future piping path)
  'JMES.FABRIC.SOFA.2SEAT.PIPING', 'JMES.FABRIC.SOFA.3SEAT.PIPING',
  'JMES.FABRIC.SOFA.LOVESEAT.PIPING',
  -- James leather (Email 2 only)
  'JMES.LEATHR.SOFA.2SEAT', 'JMES.LEATHR.SOFA.3SEAT', 'JMES.LEATHR.SOFA.LOVESEAT'
)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY c.CUSTOMER_ID
  ORDER BY o.ORDER_CREATED_AT ASC,
           oi.COBAIN_SALES_ORDER_ITEM_ID ASC
) = 1;
