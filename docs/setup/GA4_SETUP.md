# GA4 Integration Setup Guide

This guide explains how to set up GA4 Data API access for importing conversion metrics (sessions, purchases, revenue) into campaign YAML files.

## Option A: Have Someone Else Create the Credentials (Recommended)

If you have a colleague or team member with Google Cloud/GA4 admin access, they can create the service account and send you the credentials. **This is often easier!**

**What you need from them:**
1. A JSON key file (service account credentials)
2. GA4 Property IDs for each brand (6 numbers)

**Send them this document:** `GA4_CREDENTIALS_REQUEST.md` (see below)

Once you receive the JSON key file and property IDs, skip to **Step 5: Configure .env File** below.

---

## Option B: Create Credentials Yourself

If you have access to Google Cloud Console and GA4 Admin, follow these steps:

## Prerequisites

1. Access to Google Cloud Console
2. Admin access to GA4 properties for each brand
3. Python environment with `uv` package manager

## Step 1: Create Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project (or create a new one)
3. Navigate to **IAM & Admin** → **Service Accounts**
4. Click **Create Service Account**
5. Name it (e.g., "ga4-email-analytics")
6. Click **Create and Continue**
7. Skip role assignment for now, click **Done**

## Step 2: Create and Download JSON Key

1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON** format
5. Click **Create** - the JSON file will download automatically
6. Save this file securely (e.g., `~/ga4-service-account-key.json`)

## Step 3: Grant GA4 Property Access

For each brand's GA4 property:

1. Go to [GA4 Admin](https://analytics.google.com/)
2. Select the property (HAV, CZ, ID, BUR, or STF)
3. Click **Admin** (gear icon) → **Property Access Management**
4. Click **+** → **Add users**
5. Enter the service account email (found in the JSON key file, `client_email` field)
6. Select role: **Viewer**
7. Click **Add**

Repeat for all 6 brand properties (HAV, CZ, ID, BUR, STF, TI).

## Step 4: Get GA4 Property IDs

For each brand:

1. In GA4, go to **Admin** → **Property Settings**
2. Find the **Property ID** (numeric, e.g., `123456789`)
3. Note it down for each brand

## Step 5: Configure .env File

**If someone else created the credentials for you:**
1. Save the JSON key file they sent you to a secure location (e.g., `~/ga4-service-account-key.json`)
2. Use an **absolute path** to the file

**If you created it yourself:**
- Use the path where you saved the downloaded JSON file

Add these lines to your `.env` file:

```bash
# GA4 Service Account JSON (path to the downloaded key file)
# Use absolute path, e.g., /Users/yourname/ga4-service-account-key.json
GA4_SERVICE_ACCOUNT_PATH=/path/to/your-service-account-key.json

# GA4 Property IDs (one per brand)
# Get these from the person who set up credentials, or from GA4 Admin → Property Settings
GA4_PROPERTY_ID_HAV=123456789
GA4_PROPERTY_ID_CZ=987654321
GA4_PROPERTY_ID_ID=111222333
GA4_PROPERTY_ID_BUR=444555666
GA4_PROPERTY_ID_STF=777888999
GA4_PROPERTY_ID_TI=555444333
```

Replace:
- `GA4_SERVICE_ACCOUNT_PATH` with the **absolute path** to your JSON key file
- Property IDs with the actual values you received

## Step 6: Install Dependencies

```bash
uv sync
```

This will install `google-analytics-data` package.

## Step 7: Test the Integration

Run a dry-run to test:

```bash
uv run python scripts/import_ga4_metrics.py --brand HAV --dry-run
```

This will:
- Load campaigns for HAV brand
- Query GA4 for each campaign
- Show what metrics would be imported
- **Not modify any files** (dry-run mode)

## Step 8: Import GA4 Metrics

Once you've verified the dry-run looks correct:

```bash
# Single brand
uv run python scripts/import_ga4_metrics.py --brand HAV

# All brands with 14-day attribution window
uv run python scripts/import_ga4_metrics.py --all --attribution-days 14

# Only recent campaigns (last 30 days)
uv run python scripts/import_ga4_metrics.py --brand HAV --days 30
```

## How Campaign Matching Works

The script matches campaigns to GA4 data using:

1. **UTM Parameters**: Matches `utm_campaign` parameter in GA4 to campaign names/Braze IDs
2. **Date Range**: Queries GA4 for the attribution window (default 7 days) after `first_sent` date
3. **Email Traffic**: Filters for `sessionSourceMedium` containing "email"

### Matching Logic

- Exact name match
- Substring match (campaign name in GA4 or vice versa)
- Braze ID match (if Braze ID appears in GA4 campaign name)
- Keyword matching (extracts meaningful keywords from campaign names)

## Attribution Windows

Default: **7 days** (standard e-commerce)

Configurable per campaign type:
- **Batch campaigns**: 7 days
- **Canvas/triggered campaigns**: 14 days (longer consideration period)
- **Sale campaigns**: 7 days (can be customized)

## Troubleshooting

### "GA4_SERVICE_ACCOUNT_PATH not set"
- Make sure you've added the path to your JSON key file in `.env`
- Use absolute path (e.g., `/Users/yourname/ga4-key.json`)

### "GA4_PROPERTY_ID_{BRAND} not set"
- Add the property ID for that brand to `.env`
- Find it in GA4 Admin → Property Settings

### "Error initializing GA4 client"
- Check that the JSON key file exists at the specified path
- Verify the service account has Viewer access to the GA4 property
- Make sure the JSON file is valid (not corrupted)

### "No GA4 data returned" for campaigns
- Campaign might not have UTM parameters set up in Braze
- Check GA4 to see what campaign names are actually being tracked
- UTM campaign parameter might not match campaign name format
- Try adjusting the matching logic in `normalize_campaign_name_for_ga4()`

### Rate Limiting
- GA4 allows 10 requests/second
- Script automatically spaces requests (~6-7/sec) to stay under limit
- If you hit limits, reduce `--workers` (default: 5)

## Data Structure

After import, campaign YAML files will have:

```yaml
performance_summary:
  # ... existing Braze metrics ...
  ga4:
    sessions: 1234
    purchases: 45
    revenue: 12345.67
    attribution_window_days: 7
    last_synced: "2025-01-15T10:30:00"
```

## Next Steps

1. Compare GA4 revenue to Braze revenue (if available) to validate attribution
2. Analyze campaigns with high click rates but low GA4 conversions
3. Build reports showing campaign ROI (GA4 revenue / send count)
4. Identify which campaign types drive the most revenue

