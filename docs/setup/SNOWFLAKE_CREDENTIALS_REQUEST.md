# Snowflake Access Request for GA4 Campaign Data

**Purpose:** Access GA4 data stored in Snowflake to import conversion metrics (sessions, purchases, revenue) for email marketing campaigns.

**Context:** Instead of accessing GA4 via API, we want to query GA4 data that's already loaded into Snowflake for better performance and scalability.

---

## What I Need

1. **Snowflake account access** with read permissions
2. **Database/Schema information** where GA4 data is stored
3. **Table/view names** containing GA4 data
4. **Schema documentation** (columns, data types, how campaigns are identified)

---

## Access Details Needed

### 1. Connection Information

- **Account identifier**: `?` (e.g., `xy12345.us-east-1`)
- **Username**: `?` (or service account username)
- **Authentication method**: Password? Key pair? SSO?
- **Warehouse name**: `?` (for compute)
- **Database name**: `?` (where GA4 data lives)
- **Schema name**: `?` (within that database)

### 2. Permissions/Role

- **Role needed**: `?` (e.g., `ANALYST`, `READ_ONLY`, custom role)
- **Permissions**: `USAGE` and `SELECT` on database/schema/tables

### 3. Data Structure Questions

**Where is GA4 data stored?**
- Database: `?`
- Schema: `?`
- Tables/Views: `?`

**How are campaigns identified?**
- UTM parameters? (`utm_source`, `utm_medium`, `utm_campaign`)
- Custom dimensions?
- Event parameters?
- Separate columns?

**What metrics are available?**
- Sessions?
- Purchases/transactions?
- Revenue?
- Event counts?

**What's the data granularity?**
- Daily aggregates?
- Event-level?
- Session-level?

**How are brands identified?**
- Brand dimension/column?
- Separate tables per brand?
- Property ID in the data?

**Date handling:**
- How are dates stored? (DATE? TIMESTAMP? String?)
- What timezone?
- Date column name?

---

## Use Case

I need to:
1. Query GA4 data for email campaigns sent via Braze (5 brands: HAV, CZ, ID, BUR, STF)
2. Match campaigns using UTM parameters or campaign identifiers
3. Aggregate metrics (sessions, purchases, revenue) by campaign and date range
4. Import this data into campaign YAML files for analysis

**Date ranges:** Campaigns from July 2024 to present, with attribution windows (typically 7-14 days after send date)

**Brands:** Havenly (HAV), The Citizenry (CZ), Interior Define (ID), Burrow (BUR), St. Frank (STF), The Inside (TI)

---

## Questions

1. Is GA4 data already in Snowflake? If so, where?
2. What's the best way to query campaign-level metrics?
3. Are there any existing views/aggregations I should use?
4. How do I match email campaigns (from Braze) to GA4 data?
5. Can you share example queries or schema documentation?

---

## Alternative: If GA4 Data Isn't in Snowflake Yet

If GA4 data isn't currently in Snowflake:
- We could set up GA4 → Snowflake data pipeline
- Or proceed with GA4 API access (see `GA4_CREDENTIALS_REQUEST.md`)

Let me know which approach makes more sense!

Thank you!







