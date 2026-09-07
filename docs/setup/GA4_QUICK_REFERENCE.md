# GA4 API Credentials - Quick Reference

## What You Need (If Someone Else Is Setting It Up)

**Send them:** `GA4_CREDENTIALS_REQUEST.md`

**You need from them:**
1. ✅ **One JSON key file** (service account credentials)
2. ✅ **Six Property IDs** (one number per brand)

---

## What Gets Created

### 1. Service Account (in Google Cloud)
- **What it is:** A special account that can access GA4 data via API
- **Permissions needed:** Google Cloud Console access
- **What it does:** Provides read-only access to GA4 data
- **Output:** A JSON key file (contains credentials)

### 2. GA4 Property Access (in GA4)
- **What it is:** Granting the service account permission to read each brand's GA4 data
- **Permissions needed:** GA4 Admin access for each property
- **What to grant:** "Viewer" role (read-only)
- **Properties needed:** 6 total (HAV, CZ, ID, BUR, STF, TI)

### 3. Property IDs (from GA4)
- **What it is:** A unique number that identifies each GA4 property
- **Where to find:** GA4 Admin → Property Settings
- **Format:** Numeric (e.g., `123456789`)
- **How many:** 5 (one per brand)

---

## Summary: What API Keys/Credentials Are Needed

**Answer:** Just **one service account JSON key file** that has access to all 6 GA4 properties.

**Not needed:**
- ❌ OAuth client IDs/secrets
- ❌ API keys (different from service accounts)
- ❌ Multiple credential files (one JSON file works for all properties)

**The JSON key file contains:**
- Service account email
- Private key for authentication
- Project information

**Security:**
- Read-only access (Viewer role)
- Can be revoked/deleted anytime
- No ability to modify GA4 settings or data

---

## Quick Setup Checklist (For Person Creating Credentials)

- [ ] Create service account in Google Cloud
- [ ] Download JSON key file
- [ ] Grant service account "Viewer" access to HAV GA4 property
- [ ] Grant service account "Viewer" access to CZ GA4 property
- [ ] Grant service account "Viewer" access to ID GA4 property
- [ ] Grant service account "Viewer" access to BUR GA4 property
- [ ] Grant service account "Viewer" access to STF GA4 property
- [ ] Grant service account "Viewer" access to TI GA4 property
- [ ] Get Property ID from HAV GA4 property
- [ ] Get Property ID from CZ GA4 property
- [ ] Get Property ID from ID GA4 property
- [ ] Get Property ID from BUR GA4 property
- [ ] Get Property ID from STF GA4 property
- [ ] Get Property ID from TI GA4 property
- [ ] Send JSON key file + 6 Property IDs securely

---

## What You Do After Receiving Credentials

1. Save JSON key file securely (e.g., `~/ga4-key.json`)
2. Add to `.env`:
   ```bash
   GA4_SERVICE_ACCOUNT_PATH=/absolute/path/to/ga4-key.json
   GA4_PROPERTY_ID_HAV=123456789
   GA4_PROPERTY_ID_CZ=987654321
   GA4_PROPERTY_ID_ID=111222333
   GA4_PROPERTY_ID_BUR=444555666
   GA4_PROPERTY_ID_STF=777888999
   GA4_PROPERTY_ID_TI=555444333
   ```
3. Run: `uv run python scripts/import_ga4_metrics.py --brand HAV --dry-run`

Done! 🎉

