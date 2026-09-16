# How to Check GA4 Access

This guide helps you verify if you have the necessary access to set up GA4 API credentials.

## Quick Access Check

### For Each Brand Property (HAV, CZ, ID, BUR, STF, TI):

1. **Go to GA4**: https://analytics.google.com/
2. **Select the property** (e.g., Havenly, The Citizenry, etc.)
3. **Look for the Admin icon** (gear icon ⚙️ in bottom left)
   - ✅ **If you see it**: You have some level of access
   - ❌ **If you don't see it**: You don't have admin access

4. **Click Admin** → **Property Access Management**
   - ✅ **If you can access this page**: You can grant service account access
   - ❌ **If you get "You don't have permission"**: You need higher access

5. **Try to add a user** (you don't need to actually add one, just see if you can):
   - Click **+** → **Add users**
   - ✅ **If you see the form**: You have Editor or Admin role
   - ❌ **If you can't access it**: You only have Viewer role (not enough)

## Required Access Levels

### To Set Up Service Account Access Yourself:

**Minimum:** **Editor** or **Administrator** role on the GA4 property

**What each role can do:**
- **Viewer**: ❌ Cannot grant access to others
- **Analyst**: ❌ Cannot grant access to others  
- **Editor**: ✅ Can grant access (Viewer/Analyst roles)
- **Administrator**: ✅ Full access, can grant any role

### To Just Get Property IDs:

**Minimum:** **Viewer** role (anyone with access can see Property ID)

---

## Step-by-Step Verification

### Check 1: Can You See Admin Settings?

1. Go to https://analytics.google.com/
2. Select a brand property (e.g., Havenly)
3. Look for ⚙️ **Admin** icon in bottom left
4. **Result:**
   - ✅ **Yes** → Continue to Check 2
   - ❌ **No** → You need someone else to set up credentials

### Check 2: Can You Access Property Access Management?

1. Click **Admin** ⚙️
2. Under **Property** column, look for **Property Access Management**
3. Click it
4. **Result:**
   - ✅ **You see a list of users** → Continue to Check 3
   - ❌ **"You don't have permission"** → You need Editor/Admin role

### Check 3: Can You Add Users?

1. On the Property Access Management page
2. Look for **+** button or **Add users** link
3. Click it
4. **Result:**
   - ✅ **You see a form to add users** → You have enough access! ✅
   - ❌ **No button or "permission denied"** → You need Editor/Admin role

### Check 4: Can You See Property ID?

1. Click **Admin** ⚙️
2. Under **Property** column, click **Property Settings**
3. Look for **Property ID** (numeric, e.g., `123456789`)
4. **Result:**
   - ✅ **You can see it** → You can at least get Property IDs
   - ❌ **Can't access Property Settings** → You need Viewer role minimum

---

## Access Summary by Role

| Role | See Property ID? | Grant Access? | Set Up Yourself? |
|------|------------------|---------------|-----------------|
| Viewer | ✅ Yes | ❌ No | ❌ No |
| Analyst | ✅ Yes | ❌ No | ❌ No |
| Editor | ✅ Yes | ✅ Yes (Viewer/Analyst) | ✅ Yes |
| Administrator | ✅ Yes | ✅ Yes (All roles) | ✅ Yes |

---

## What If You Don't Have Enough Access?

**Option 1: Request Access**
- Ask your GA4 Administrator to grant you **Editor** or **Administrator** role
- Or ask them to set up the service account for you (send them `GA4_CREDENTIALS_REQUEST.md`)

**Option 2: Have Someone Else Do It**
- If you only have Viewer/Analyst access, have someone with Editor/Admin access:
  1. Create the service account
  2. Grant it access to all properties
  3. Send you the JSON key file and Property IDs

---

## Quick Test Script

You can also run a Python script to test if you have API access (requires credentials first):

```bash
# After you have credentials set up, test access:
uv run python scripts/test_ga4_access.py --brand HAV
```

This will attempt to query GA4 and show if you have proper access.

