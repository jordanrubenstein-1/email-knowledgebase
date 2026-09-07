---
name: feedback_sms_campaign_name_cleanup
description: "Two rules for SMS campaign name generation — strip \"SMS\" anywhere in description; strip content inside parentheses entirely"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 849171fd-b6e4-442e-833d-127257b36d1e
---

Two confirmed rules for `generate_sms_campaign_name` in `scripts/braze_automation/build_sms_campaign.py` and `_format_description` in `scripts/utils/campaign_name.py`:

**Rule 1 — Strip channel words (SMS, Push, Email) from the description entirely.**
The channel is already encoded in `P_SMS_` / `P_PUSH_` / `P_EM_`. Any of these words appearing anywhere in the Asana task name are redundant and must be removed.
In `build_sms_campaign.py`: `re.sub(r'\b(?:SMS|Push|Email)\b\s*[:\-]?\s*', '', description, flags=re.IGNORECASE)`.
In `_format_description` (campaign_name.py): same regex, applied as a general safety net before punctuation stripping.

**Why:** "Swatch Talk SMS (May 29)" → `..._Swatch_Talk_SMS_May_29`; "Mid-Sale Push" SMS task → `..._Mid-Sale_Push`. Channel words were only stripped at start/end, not mid-string.

**Rule 2 — Strip parenthesized content entirely from campaign names.**
Content inside `(...)` in an Asana task name is scheduling/context metadata (e.g. "(May 29)", "(If Needed)") and must be excluded from the campaign name. Strip the entire group including its content: `re.sub(r'\s*\([^)]*\)', '', desc)` — applied in `_format_description` before the punctuation-character strip.

**Why:** The old code stripped `(` and `)` as punctuation characters but left the content inside, turning "(May 29)" into "May_29" in the campaign name.

**How to apply:** Both fixes are implemented. Any time a task name contains `(...)` or embedded "SMS", the generated name should exclude both.
