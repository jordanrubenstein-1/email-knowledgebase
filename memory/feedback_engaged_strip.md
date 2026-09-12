---
name: ""
metadata: 
  node_type: memory
  originSessionId: e7fece86-935c-442c-b879-d8b7222dc29a
---

When an Asana task title contains "Engaged" (e.g., "Summer Sale Reminder Engaged" or "Summer Sale Reminder — Engaged"), it signals that the campaign should be sent to the Engaged segment. It must NOT appear in the Braze campaign name.

**Why:** "Engaged" is audience metadata, not campaign content. Including it in the campaign name violates the naming convention.

**How to apply:** Already implemented — `_format_description()` in `scripts/utils/campaign_name.py` strips `\bengaged\b` (word boundary, case-insensitive) immediately after stripping "If Needed". Both `build_pt_campaign.py` and `build_designed_campaign.py` flow through this function. No additional handling needed.

Related: [[feedback-campaign-name-if-needed]]
