# HAV Pre-Converted Email Engagement Analysis

**Generated:** April 22, 2026  
**Source file:** `Daily_Send_List_-_Pre_Converted_export 2.csv` (283,739 users in CSV)  
**Snowflake cohort:** 305,498 users emailed in last 90d, no design_fee, not unsubscribed  
**Engagement window:** July 26, 2025 – October 24, 2025 (90 days)  
**Conversion tracking:** October 24, 2025 – April 22, 2026 (6 months forward)  

---

## 1. Send List Composition

Breakdown of the current pre-converted send list by lifecycle sub-stage.
(Merch purchases without a design fee purchase means they bought shop items directly.)

| SUB_STAGE                     | USERS  | PCT  |
| ----------------------------- | ------ | ---- |
| Pre-conv — account, no merch  | 184160 | 60.3 |
| Email-only (no account)       | 118463 | 38.8 |
| Pre-conv — has merch purchase | 2875   | 0.9  |


---

## 2. Current Email Engagement vs. Merch Purchase Rate

Users classified by email engagement in the **trailing 90 days** (Jan 22 – Apr 22, 2026).  
Merch rate = users who have ANY `merch_order_completed_fe` event (ever, not just recent).

| ENGAGEMENT_TIER             | USERS  | PCT_OF_LIST | MERCH_BUYERS | MERCH_RATE_PCT | AVG_SENDS_90D | AVG_OPEN_RATE_PCT |
| --------------------------- | ------ | ----------- | ------------ | -------------- | ------------- | ----------------- |
| Active — Clicked            | 20846  | 6.8         | 532          | 2.55           | 61.3          | 16.3              |
| Active — Opened only        | 91410  | 29.9        | 916          | 1.00           | 55.2          | 11.7              |
| Dormant — Received, no open | 193242 | 63.3        | 1427         | 0.74           | 47.9          | 0.0               |


---

## 3. Email Touch Before a Merch Purchase

For pre-converted merch buyers on this list: what was their email engagement
in the **90 days before their first merch purchase**?

| EMAIL_ENGAGEMENT_TIER             | BUYERS | PCT_OF_BUYERS | AVG_SENDS | AVG_OPENS | AVG_CLICKS |
| --------------------------------- | ------ | ------------- | --------- | --------- | ---------- |
| 3 — Clicked email before purchase | 1048   | 36.5          | 54.8      | 16.6      | 5.9        |
| 2 — Opened email (no click)       | 172    | 6.0           | 28.3      | 9.1       | 0.0        |
| 1 — Received email (no open)      | 465    | 16.2          | 7.6       | 0.0       | 0.0        |
| 0 — No email touch in prior 90d   | 1190   | 41.4          | 0.0       | 0.0       | 0.0        |


---

## 4. Last-Click Campaign Type Attribution (30-day window)

For merch buyers, the campaign type of their last email click before purchase.

| CAMPAIGN_TYPE                   | BUYERS | PCT  |
| ------------------------------- | ------ | ---- |
| Other                           | 5875   | 88.7 |
| Converted audience campaign     | 604    | 9.1  |
| Pre-converted audience campaign | 123    | 1.9  |
| No attributed campaign          | 22     | 0.3  |


---

## 5. Design Package Conversion by Email Engagement Tier (Cohort Analysis)

**Cohort:** HAV pre-converted users who received at least one email between  
July 26, 2025 and October 24, 2025 and had NOT yet purchased a design package.  

**Outcome:** Who subsequently paid the design fee within the following 6 months?

| ENGAGEMENT_TIER      | COHORT_USERS | PCT_OF_COHORT | CONVERTED | CONVERSION_RATE_PCT | MERCH_BUYERS_POST | MERCH_RATE_POST_PCT | AVG_SENDS | AVG_OPENS | AVG_CLICKS |
| -------------------- | ------------ | ------------- | --------- | ------------------- | ----------------- | ------------------- | --------- | --------- | ---------- |
| Dormant — No opens   | 187636       | 62.1          | 783       | 0.42                | 119               | 0.06                | 56.2      | 0.0       | 0.0        |
| Active — Opened only | 73482        | 24.3          | 450       | 0.61                | 86                | 0.12                | 57.8      | 9.3       | 0.0        |
| Active — Clicked     | 40818        | 13.5          | 945       | 2.32                | 191               | 0.47                | 46.4      | 10.5      | 3.0        |


### Key Question: Does volume of sends to dormant users predict conversion?

Among the dormant (no-open) cohort, broken down by how many emails they received:

| SEND_BUCKET | USERS  | CONVERTED | CONVERSION_RATE_PCT |
| ----------- | ------ | --------- | ------------------- |
| 01-04 sends | 6707   | 76        | 1.13                |
| 05-08 sends | 3292   | 38        | 1.15                |
| 09-12 sends | 6345   | 25        | 0.39                |
| 13+ sends   | 185833 | 929       | 0.50                |


---

## Methodology Notes

- **Dormant** = received ≥1 email in the window but zero human opens (machine opens excluded)
- **Merch purchase** = `merch_order_completed_fe` custom event in Braze, without a prior `design_fee` event
- **Design conversion** = `design_fee` or `design_fee_fe` event (paying for a design package)
- Machine opens filtered via `MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false'`
- Data source: Braze Raw Events Datashare (HAV workspace `664223fb71bcf3005760dfc2`)