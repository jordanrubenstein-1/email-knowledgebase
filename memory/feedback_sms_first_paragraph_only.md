---
name: feedback-sms-first-paragraph-only
description: "SMS auto-builder must use only the first paragraph of task notes; content after the first blank line is copywriter metadata, not copy"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8ca93c02-c2ff-407c-be58-d758ac9b1a87
---

Only use the first paragraph from Asana task notes when extracting SMS copy. Content separated by a blank line below the main copy is copywriter notes/metadata (e.g. a discount callout the writer left as a reminder) — it must not be included in the built SMS body.

**Why:** A STF task had "20% off sitewide." on a separate line below the actual copy, separated by a blank line. It was a writer's note, not intended copy. The auto-builder included it, duplicating information already in the copy.

**How to apply:** In `build_sms_campaign.py` `extract_sms_copy()`, stop collecting lines when a blank line is encountered after content has started (same approach used in `create_klaviyo_sms.py` `extract_sms_body()`). The LP: line scan still reads all lines since it's a separate pre-pass.
