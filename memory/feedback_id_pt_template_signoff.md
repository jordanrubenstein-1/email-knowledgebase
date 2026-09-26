---
name: feedback-id-pt-template-signoff
description: ID PT email template — body and signoff must be in the same div block to avoid large visual gap
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 132d8067-b209-438e-a88f-3bf3e641d5e3
---

Body content and signoff must live inside the **same `block-2` div** in `components/id_pt_template.html` — do NOT use a separate `block-3` table for the signoff.

**Why:** Separate table blocks produce an oversized line gap between the body copy and the sign-off in rendered email clients.

**How to apply:** The `<!-- BODY_CONTENT -->` and `<!-- SIGNOFF -->` placeholders are both inside the single `block-2` `<div>` in the template. When injecting, the signoff paragraph (`<p style="margin:0 0 14px 0;">Talk soon,<br>Lisa<br>Interior Define Team</p>`) should follow immediately after the last body paragraph — no additional padding or table row between them.
