---
name: feedback-campaign-name-if-needed
description: "When auto-building a campaign from a task that contains \"If Needed\" in the task name, strip \"If Needed\" from the generated Braze campaign name"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e57363a1-e1de-4588-9d14-c70324b49d47
---

When a task is auto-built and the task name contains "If Needed" (or "if needed"), do NOT include that phrase in the generated Braze campaign name.

**Why:** "If Needed" is a scheduling qualifier in the Asana task name, not part of the campaign's actual content description. Including it in the campaign name pollutes the naming convention and makes the Braze campaign history harder to read.

**How to apply:** In `generate_campaign_name()` and any auto-build script that derives the campaign description from the Asana task name, strip "If Needed" (case-insensitive) from the task name before constructing the campaign name segment.
