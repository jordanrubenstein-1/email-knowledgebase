# Braze Campaign Creation - API Limitation

## Finding

**Braze REST API does not support creating campaigns programmatically.**

The Braze REST API does not have a `/campaigns/create` endpoint. Campaigns must be created through the Braze Dashboard UI.

## What Works via API

✅ **Content Blocks** - Can be created via API (this worked!)
- Endpoint: `POST /content_blocks/create`
- Content Block ID created: `26e8992b-b8e2-4534-b64d-60eccad158f2`

✅ **Campaign Operations** - Can be done via API:
- List campaigns: `GET /campaigns/list`
- Get campaign details: `GET /campaigns/details`
- Schedule campaigns: `POST /campaigns/trigger/schedule/create`
- Send/trigger campaigns: `POST /campaigns/trigger/send`

❌ **Campaign Creation** - Must be done in UI:
- Campaigns cannot be created via REST API
- Must use Braze Dashboard to create campaigns

## Workaround: Manual Campaign Creation

Since the content block was successfully created, you can:

1. **Go to Braze Dashboard** → Campaigns → Create Campaign
2. **Select Email Campaign** → Plain Text
3. **Use the Content Block**:
   - Content Block ID: `26e8992b-b8e2-4534-b64d-60eccad158f2`
   - Name: `P_2026_01_25_PT_BUR_Winter_Refresh_Sale_Reminder_PM_ContentBlock`
4. **Configure the campaign**:
   - Subject: "Your chance to save up to 35% off"
   - Preheader: "Winter Refresh Sale ends Tuesday"
   - Audience: Segment ID `4c0994bb-b4e3-44df-9b0c-d62fa2d5a19f` (All Users)
   - Schedule: Sunday, January 25, 2026 at 4:00 PM Eastern
5. **Review and schedule** (campaign will NOT send automatically)

## Alternative: Use Braze Templates API

If you want more automation, you could:
1. Create email templates via API (`POST /templates/email/create`)
2. Then create campaigns in UI that use those templates
3. Schedule via API once created

This is still a hybrid approach but reduces manual work.
