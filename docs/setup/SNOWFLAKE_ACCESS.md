# Snowflake Access Requirements for GA4 Data

## Overview

Instead of accessing GA4 directly via API, you can query GA4 data that's already loaded into Snowflake. This is often more efficient and scalable for analytics workloads.

## What Snowflake Access You Need

### 1. Database/Schema Access

You need **read access** to:
- The **database** where GA4 data is stored
- The **schema** within that database containing GA4 tables/views
- Specific **tables or views** with GA4 data

**What to ask for:**
- Database name (e.g., `ANALYTICS`, `MARKETING_DATA`, `GA4_DATA`)
- Schema name (e.g., `GA4`, `ANALYTICS`, `WEB_ANALYTICS`)
- Table/view names (e.g., `ga4_sessions`, `ga4_events`, `ga4_daily_summary`)

### 2. Required Permissions

**Minimum:** `USAGE` and `SELECT` privileges on:
- The database
- The schema
- The relevant tables/views

**Roles typically needed:**
- `ANALYST` role (read-only access)
- `READ_ONLY` role
- Custom role with SELECT permissions

### 3. Connection Information

You'll need:
- **Account identifier** (e.g., `xy12345.us-east-1`)
- **Username** (or service account username)
- **Password** (or key pair authentication)
- **Warehouse name** (for compute resources)
- **Database name**
- **Schema name**

### 4. Data Structure Understanding

You need to know:
- **How campaigns are identified** in the data
  - UTM parameters? (`utm_source`, `utm_medium`, `utm_campaign`)
  - Custom dimensions?
  - Event parameters?
- **What metrics are available**
  - Sessions?
  - Purchases/transactions?
  - Revenue?
  - Event counts?
- **Data granularity**
  - Daily aggregates?
  - Event-level?
  - Session-level?
- **Date fields**
  - How dates are stored
  - Timezone considerations

## Questions to Ask Your Data Team

1. **Where is GA4 data stored?**
   - Database name: `?`
   - Schema name: `?`
   - Table/view names: `?`

2. **What's the data structure?**
   - How are campaigns identified? (UTM parameters? Custom dimensions?)
   - What metrics are available? (sessions, purchases, revenue?)
   - What's the granularity? (daily? event-level? session-level?)

3. **How do I access it?**
   - What role/permissions do I need?
   - Do I need a service account or can I use my user account?
   - What's the account identifier?

4. **What's the schema?**
   - Can you share the table structure/columns?
   - Are there any views that aggregate the data?
   - How are dates stored?

5. **Brand segmentation:**
   - How are different brands (HAV, CZ, ID, BUR, STF, TI) identified in the data?
   - Is there a brand dimension/column?
   - Or are they in separate tables/schemas?

## Example Snowflake Query Structure

Once you have access, queries might look like:

```sql
-- Example: Get sessions and revenue by campaign
SELECT 
    DATE_TRUNC('day', event_date) as date,
    (SELECT value.string_value 
     FROM UNNEST(event_params) 
     WHERE key = 'utm_campaign') as campaign_name,
    (SELECT value.string_value 
     FROM UNNEST(event_params) 
     WHERE key = 'utm_source') as source,
    COUNT(DISTINCT user_pseudo_id || '-' || session_id) as sessions,
    COUNTIF(event_name = 'purchase') as purchases,
    SUM((SELECT value.double_value 
         FROM UNNEST(event_params) 
         WHERE key = 'value')) as revenue
FROM `your-database.your-schema.ga4_events_*`
WHERE 
    _TABLE_SUFFIX BETWEEN '20240101' AND '20240131'
    AND (SELECT value.string_value 
         FROM UNNEST(event_params) 
         WHERE key = 'utm_source') = 'email'
GROUP BY 1, 2, 3
```

*(Note: Actual query structure depends on how data is stored in your Snowflake instance)*

## Advantages of Using Snowflake

1. **Performance**: Pre-aggregated data, faster queries
2. **Cost**: No API rate limits, no API costs
3. **Historical Data**: Access to full historical data (not limited by GA4 API retention)
4. **Flexibility**: Can join with other data sources (Braze, Klaviyo, etc.)
5. **Scalability**: Handle large date ranges efficiently

## Implementation Approach

If using Snowflake instead of GA4 API:

1. **Update import script** to query Snowflake instead of GA4 API
2. **Match campaigns** using UTM parameters or campaign identifiers
3. **Aggregate metrics** (sessions, purchases, revenue) by campaign and date range
4. **Update campaign YAML files** with Snowflake-sourced metrics

## Next Steps

1. **Get Snowflake access** (ask your data team using questions above)
2. **Explore the data structure** (understand schema, tables, columns)
3. **Test queries** to verify you can match campaigns correctly
4. **Update import script** to use Snowflake instead of GA4 API

## Alternative: Hybrid Approach

You could also:
- Use **Snowflake for historical data** (more efficient)
- Use **GA4 API for recent data** (real-time, last 30 days)
- Combine both in the import script







