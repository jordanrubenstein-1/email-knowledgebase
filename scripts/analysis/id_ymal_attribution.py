"""
ID YMAL Purchase Attribution
=============================
Measures whether users who received the abandon browse YMAL grid
purchased one of the 6 specific products shown to them.

Message extras captured per send (via recs_* content blocks):
  ymal_cat   — product category shown (e.g. "Sofas", "Chairs")
  ymal_s1–s6 — slug of each product shown (e.g. "sloan-sofa")

Data sources:
  Sends  — TIER3 Braze datashare (DATALAKE_SHARING_TIERED)
  Orders — PROD.ID_WAREHOUSE.ORDERS + ORDER_ITEMS + DIM_PRODUCTS

Methodology notes:
  - EXTERNAL_USER_ID format: "interiordefine-{COBAIN_CUSTOMER_ID}"
    → join to ORDERS.CUSTOMER_ID via TRY_CAST(SPLIT_PART(..., '-', 2) AS NUMBER)
  - Slug matching: slug prefix (e.g. "sloan") is extracted with SPLIT_PART(slug, '-', 1)
    and matched against REGEXP_REPLACE(LOWER(SPLIT_PART(DIM_PRODUCTS.COLLECTION, ' ', 1)), '[^a-z]', '')
    e.g. "Ms. Chesterfield" → "ms", matching slug "ms-sofa" → "ms"
  - Do NOT use FACT_SALES_ORDERS / FACT_SALES_ORDER_ITEMS — that table's
    CREATED_AT_WID is a YYYYMMDD string and the data is stale (last updated Jan 2025).
    Use ORDERS + ORDER_ITEMS (ORDER_CREATED_AT TIMESTAMP_NTZ, live data).
  - Do NOT match on raw SKU prefix (e.g. "SLON") — that doesn't align with slug format.
    Always join through DIM_PRODUCTS to get COLLECTION name.

Message extras deployment date: 2026-06-24 ~17:17 UTC
Run this analysis after 2026-07-24 for a full 30-day attribution window.
"""

from scripts.snowflake_client import get_snowflake_client

TIER3_DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"
TIER3_SCHEMA = "DATALAKE_SHARING_TIERED"
ID_APP_GROUP = "6666726b459b5e0059d7d687"

ATTRIBUTION_QUERY = f"""
WITH ymal_sends AS (
  SELECT
    s.USER_ID,
    TRY_CAST(SPLIT_PART(s.EXTERNAL_USER_ID, '-', 2) AS NUMBER) AS cobain_id,
    TO_DATE(TO_TIMESTAMP(s.TIME))                               AS send_date,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_cat"::STRING             AS ymal_cat,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s1"::STRING              AS s1,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s2"::STRING              AS s2,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s3"::STRING              AS s3,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s4"::STRING              AS s4,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s5"::STRING              AS s5,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s6"::STRING              AS s6
  FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
  WHERE s.APP_GROUP_ID = '{ID_APP_GROUP}'
    AND s.CANVAS_ID IS NOT NULL
    AND s.MESSAGE_EXTRAS IS NOT NULL
    AND s.EXTERNAL_USER_ID IS NOT NULL
    AND TO_TIMESTAMP(s.TIME) >= '2026-06-24 17:17:00'
),
purchases AS (
  SELECT
    o.CUSTOMER_ID                                                            AS cobain_id,
    TO_DATE(o.ORDER_CREATED_AT)                                              AS order_date,
    oi.SKU                                                                   AS sku,
    dp.COLLECTION                                                            AS prod_collection,
    REGEXP_REPLACE(LOWER(SPLIT_PART(dp.COLLECTION, ' ', 1)), '[^a-z]', '')  AS collection_prefix,
    oi.GRAND_TOTAL                                                           AS revenue
  FROM PROD.ID_WAREHOUSE.ORDERS o
  JOIN PROD.ID_WAREHOUSE.ORDER_ITEMS oi  ON o.COBAIN_SALES_ORDER_ID = oi.COBAIN_SALES_ORDER_ID
  JOIN PROD.ID_WAREHOUSE.DIM_PRODUCTS dp ON oi.SKU = dp.SKU
  WHERE o.ORDER_CREATED_AT >= '2026-06-24'
),
matched AS (
  SELECT
    y.USER_ID,
    y.ymal_cat,
    y.send_date,
    p.order_date,
    p.prod_collection,
    p.revenue,
    CASE WHEN
      SPLIT_PART(y.s1, '-', 1) = p.collection_prefix OR
      SPLIT_PART(y.s2, '-', 1) = p.collection_prefix OR
      SPLIT_PART(y.s3, '-', 1) = p.collection_prefix OR
      SPLIT_PART(y.s4, '-', 1) = p.collection_prefix OR
      SPLIT_PART(y.s5, '-', 1) = p.collection_prefix OR
      SPLIT_PART(y.s6, '-', 1) = p.collection_prefix
    THEN 1 ELSE 0 END AS purchased_shown_item
  FROM ymal_sends y
  JOIN purchases p
    ON y.cobain_id = p.cobain_id
    AND p.order_date BETWEEN y.send_date AND DATEADD('day', 30, y.send_date)
)
SELECT
  ymal_cat,
  COUNT(DISTINCT USER_ID)                                                        AS users_purchased_anything,
  SUM(purchased_shown_item)                                                      AS orders_of_shown_item,
  ROUND(SUM(revenue), 0)                                                         AS total_revenue,
  ROUND(SUM(CASE WHEN purchased_shown_item = 1 THEN revenue ELSE 0 END), 0)      AS revenue_shown_items,
  ROUND(SUM(purchased_shown_item) / NULLIF(COUNT(DISTINCT USER_ID), 0) * 100, 1) AS pct_bought_shown
FROM matched
GROUP BY 1
ORDER BY users_purchased_anything DESC
"""

ROW_LEVEL_QUERY = f"""
-- Row-level detail: every purchase by a YMAL recipient
WITH ymal_sends AS (
  SELECT
    s.USER_ID,
    TRY_CAST(SPLIT_PART(s.EXTERNAL_USER_ID, '-', 2) AS NUMBER) AS cobain_id,
    TO_DATE(TO_TIMESTAMP(s.TIME))                               AS send_date,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_cat"::STRING             AS ymal_cat,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s1"::STRING              AS s1,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s2"::STRING              AS s2,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s3"::STRING              AS s3,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s4"::STRING              AS s4,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s5"::STRING              AS s5,
    PARSE_JSON(s.MESSAGE_EXTRAS):"ymal_s6"::STRING              AS s6
  FROM {TIER3_DB}.{TIER3_SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
  WHERE s.APP_GROUP_ID = '{ID_APP_GROUP}'
    AND s.CANVAS_ID IS NOT NULL
    AND s.MESSAGE_EXTRAS IS NOT NULL
    AND s.EXTERNAL_USER_ID IS NOT NULL
    AND TO_TIMESTAMP(s.TIME) >= '2026-06-24 17:17:00'
),
purchases AS (
  SELECT
    o.CUSTOMER_ID                                                            AS cobain_id,
    TO_DATE(o.ORDER_CREATED_AT)                                              AS order_date,
    oi.SKU                                                                   AS sku,
    dp.COLLECTION                                                            AS prod_collection,
    REGEXP_REPLACE(LOWER(SPLIT_PART(dp.COLLECTION, ' ', 1)), '[^a-z]', '')  AS collection_prefix,
    oi.GRAND_TOTAL                                                           AS revenue
  FROM PROD.ID_WAREHOUSE.ORDERS o
  JOIN PROD.ID_WAREHOUSE.ORDER_ITEMS oi  ON o.COBAIN_SALES_ORDER_ID = oi.COBAIN_SALES_ORDER_ID
  JOIN PROD.ID_WAREHOUSE.DIM_PRODUCTS dp ON oi.SKU = dp.SKU
  WHERE o.ORDER_CREATED_AT >= '2026-06-24'
)
SELECT
  y.ymal_cat,
  y.USER_ID,
  y.send_date,
  p.order_date,
  DATEDIFF('day', y.send_date, p.order_date) AS days_to_purchase,
  p.sku,
  p.prod_collection,
  p.revenue,
  CASE WHEN
    SPLIT_PART(y.s1, '-', 1) = p.collection_prefix OR
    SPLIT_PART(y.s2, '-', 1) = p.collection_prefix OR
    SPLIT_PART(y.s3, '-', 1) = p.collection_prefix OR
    SPLIT_PART(y.s4, '-', 1) = p.collection_prefix OR
    SPLIT_PART(y.s5, '-', 1) = p.collection_prefix OR
    SPLIT_PART(y.s6, '-', 1) = p.collection_prefix
  THEN 1 ELSE 0 END AS purchased_shown_item,
  y.s1, y.s2, y.s3, y.s4, y.s5, y.s6
FROM ymal_sends y
JOIN purchases p
  ON y.cobain_id = p.cobain_id
  AND p.order_date BETWEEN y.send_date AND DATEADD('day', 30, y.send_date)
ORDER BY y.send_date, p.order_date
"""


def run(row_level: bool = False) -> None:
    client = get_snowflake_client(schema=TIER3_SCHEMA, database=TIER3_DB)
    query = ROW_LEVEL_QUERY if row_level else ATTRIBUTION_QUERY
    rows = client.execute_query(query)

    if not rows:
        print("No data yet — check back after 2026-07-24 for a full 30-day window.")
        return

    if row_level:
        for r in rows:
            flag = "✓ SHOWN" if r["PURCHASED_SHOWN_ITEM"] else "  other"
            print(
                f"{flag}  {r['YMAL_CAT']:<12} {r['SEND_DATE']} → {r['ORDER_DATE']} "
                f"(+{r['DAYS_TO_PURCHASE']}d)  {r['PROD_COLLECTION']:<20} ${r['REVENUE']:,.0f}"
            )
    else:
        print(f"{'Category':<14} {'Purchased':<10} {'Bought Shown':<14} {'Total Rev':>10} {'Shown Rev':>10} {'% Shown':>8}")
        print("-" * 72)
        for r in rows:
            print(
                f"{r['YMAL_CAT']:<14} {r['USERS_PURCHASED_ANYTHING']:<10} "
                f"{r['ORDERS_OF_SHOWN_ITEM']:<14} ${r['TOTAL_REVENUE']:>9,.0f} "
                f"${r['REVENUE_SHOWN_ITEMS']:>9,.0f} {r['PCT_BOUGHT_SHOWN']:>7}%"
            )


if __name__ == "__main__":
    import sys
    run(row_level="--rows" in sys.argv)
