---
name: feedback_pt_email_parsing_rules
description: "Rules for parsing Asana task descriptions when auto-building PT emails — SL/PH handling, CTA formatting, signoff, body start detection"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 237e4d9c-81ed-4e07-9710-ae8b798563b2
---

## Rule 1: SL/PH lines set campaign fields — never go in the body

When an Asana task description starts with `SL: ...` and/or `PH: ...` lines, those values set the **subject line** and **preheader** of the campaign. They must NOT appear in the email body.

**Why:** The auto-builder incorrectly included `SL: LAST CHANCE: Summer Ready Flash Sale` as the first line of the email body (task GID 1215400596416918).

**How to apply:** Strip any leading `SL:` / `PH:` lines before extracting body copy. Pass the stripped values to the campaign's subject and preheader fields.

---

## Rule 2: Body starts at "Hi there," — nothing above it

When the Asana description contains `Hi there,` (or a Liquid first-name greeting), that marks the start of the email body. The auto-builder must:
- Treat everything from `Hi there,` onward as body copy
- Never prepend any other text above the greeting (no SL line, no duplicated greeting)
- Never emit the greeting twice

**Why:** The auto-built email had `Hi there,` then `SL: LAST CHANCE: Summer Ready Flash Sale` then `Hi there,` again.

**How to apply:** Find the first greeting line in the task notes and use that as the body start. Everything above it (SL/PH lines, brief metadata) is stripped from the body.

---

## Rule 3: `[CTA: Copy Text]` → HTML anchor/button — never literal text

When the task description contains a pattern like `[CTA: Some Text]` or `CTA: Some Text`, it means **link that text** — render it as a clickable element. Do NOT include the brackets or the word "CTA" in the email output.

**For HAV PT emails**, render as a styled HTML button:
```html
<a href="[URL]" style="display:inline-block;background-color:#101b24;color:#ffffff;font-family:'Open Sans',Arial,Sans-serif;font-size:14px;font-weight:700;text-decoration:none;padding:12px 24px;border-radius:4px;">[CTA Text]</a>
```

**Why:** The auto-builder copied `[CTA: Shop the Summer Ready Flash Sale]` literally into the email body.

**How to apply:** Use a regex like `\[CTA:\s*(.+?)\]` to extract the CTA text, then render as an anchor. URL comes from the LP field in the task or the Asana brief. See also the `cta_links` field in campaign config dicts.

---

## Rule 4: `[Name]` in signoff → brand-specific signoff name

When the task description ends with a signoff like `Happy Shopping,\n[Name]`, the `[Name]` placeholder must be replaced with the brand's standard signoff name. Never output literal `[Name]` in the email body.

**HAV signoff names by audience:**
- PT `from_name`: `Lisa from Havenly` (used as the signoff name in body)
- Configured in `data/brand_braze_config.yaml` under `HAV_PC` and `HAV_CONV`

**Why:** The auto-built email kept `[Name]` literally in the body.

**How to apply:** Replace `[Name]` (case-insensitive, with brackets) with the appropriate signoff for the brand/channel being built. For HAV PT, use `Lisa from Havenly`.

---

## Rule 5: `Happy Shopping,` is the line before the signoff name

`Happy Shopping,` (and similar closings like `Warm regards,`, `The Burrow Team`, etc.) signals the final signoff block. The line immediately following it is the signoff name (or `[Name]` placeholder per Rule 4 above). Everything after the signoff name is briefing metadata to be stripped.
