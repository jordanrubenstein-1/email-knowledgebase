# GA4 API Credentials Request

**Purpose:** Set up GA4 Data API access to import conversion metrics (sessions, purchases, revenue) for email marketing campaigns.

**What needs to be created:** A Google Cloud service account with access to GA4 properties.

**Note:** The Inside (TI) currently uses Klaviyo for email campaigns (not Braze), but GA4 access is needed now for future integration of Klaviyo campaign data with GA4 conversion metrics.

---

## What I Need From You

1. **Service Account JSON Key File** - A downloaded JSON file containing the credentials
2. **GA4 Property IDs** - One numeric ID for each brand property (6 total)

---

## Step-by-Step Instructions for Setup

### Step 1: Create Service Account in Google Cloud

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select the appropriate project (or create a new one if needed)
3. Navigate to **IAM & Admin** → **Service Accounts**
4. Click **Create Service Account**
5. Name it something descriptive like:
   - `ga4-email-analytics`
   - `email-campaign-analytics`
   - `marketing-analytics-api`
6. Click **Create and Continue**
7. **Skip role assignment** (we'll grant access in GA4 directly)
8. Click **Done**

### Step 2: Create and Download JSON Key

1. Click on the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON** format
5. Click **Create**
   - The JSON file will download automatically
   - **Important:** This file contains sensitive credentials - handle securely!

### Step 3: Grant GA4 Property Access

For **each** of the 6 brand GA4 properties (HAV, CZ, ID, BUR, STF, TI):

1. Go to [GA4 Admin](https://analytics.google.com/)
2. Select the property (e.g., Havenly, The Citizenry, etc.)
3. Click **Admin** (gear icon in bottom left)
4. Under **Property**, click **Property Access Management**
5. Click **+** → **Add users**
6. Enter the **service account email address**
   - You can find this in the JSON key file you downloaded
   - Look for the `client_email` field (looks like: `ga4-email-analytics@project-name.iam.gserviceaccount.com`)
7. Select role: **Viewer** (read-only access)
8. Click **Add**

**Repeat this for all 6 brand properties:**
- Havenly (HAV)
- The Citizenry (CZ)
- Interior Define (ID)
- Burrow (BUR)
- St. Frank (STF)
- The Inside (TI) - *Note: Currently uses Klaviyo for emails, but GA4 access needed for future integration*

### Step 4: Get GA4 Property IDs

For **each** brand property:

1. In GA4, go to **Admin** → **Property Settings**
2. Find the **Property ID** (it's a numeric value, e.g., `123456789`)
3. Note it down with the brand code:
   - HAV: `[property-id]`
   - CZ: `[property-id]`
   - ID: `[property-id]`
   - BUR: `[property-id]`
   - STF: `[property-id]`
   - TI: `[property-id]`

---

## What to Send Me

Please send:

1. **The JSON key file** (the downloaded `.json` file)
   - Can be sent via secure file sharing (password-protected zip, secure link, etc.)
   - Or via secure messaging/email

2. **The 6 Property IDs** in this format:
   ```
   GA4_PROPERTY_ID_HAV=123456789
   GA4_PROPERTY_ID_CZ=987654321
   GA4_PROPERTY_ID_ID=111222333
   GA4_PROPERTY_ID_BUR=444555666
   GA4_PROPERTY_ID_STF=777888999
   GA4_PROPERTY_ID_TI=555444333
   ```

---

## Security Notes

- The JSON key file provides **read-only** access to GA4 data (Viewer role)
- It cannot modify any GA4 settings or data
- Store it securely and don't commit it to version control
- If the key is ever compromised, you can delete it in Google Cloud Console and create a new one

---

## Questions?

If you need clarification on any step, please ask! The key things are:
- Service account created
- JSON key downloaded
- Service account email granted "Viewer" access to all 6 GA4 properties
- Property IDs collected (6 total)

Thank you!

