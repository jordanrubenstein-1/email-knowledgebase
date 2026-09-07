---
name: cz-builder-reinject-lessons
description: "Lessons from debugging build_cz_designed_email.py re-injection in edit mode — Monaco targeting, portal scoping, layout parsing, link href parsing"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 054ed132-8b18-4710-8192-2571b82ead02
---

## Monaco editor must be scoped to the portal in edit mode

In edit mode (editing an existing campaign), the compose step page has subject/preheader Monaco editors in the DOM BEFORE the `#email-message-composer-portal` div. `page.locator(".monaco-editor").first` resolves to the subject editor, not the HTML body editor. This causes clipboard paste to overwrite the subject with the HTML body.

**Fix:** Always scope to `page.locator("#email-message-composer-portal .monaco-editor")` when editing an existing campaign. The portal is only present in edit mode; for new campaign builds the page-wide selector is fine.

**Why:** The email-message-composer-portal is a React portal appended to `<body>` — it comes AFTER the compose step's Sending Info section in DOM order, so `.monaco-editor.first` finds the subject editor first.

**How to apply:** Implemented in `_inject_html()` — checks `#email-message-composer-portal` count; if > 0, scopes Monaco locator to portal.

## Edit-existing-campaign navigation flow

When navigating to an existing campaign URL (`/engagement/campaigns/{id}/{workspace}`), Braze lands on the overview page, not the compose step. The correct flow is:

1. Navigate to campaign URL (with `?page=3` to land on compose step)
2. Click "Compose Messages" (wizard step button) — NOT "Edit message" directly
3. Scroll down, click "Edit message" to open the HTML editor portal

The portal selector for tab navigation is `#email-message-composer-portal` — sidebar buttons like "Content" (aria-label="Content") belong to the Braze sidebar navigation, not the modal tabs. The modal tabs inside the portal are labeled "HTML", "Classic", "Plaintext", "AMP" (not "Content"/"Sending Settings").

## Sending info (subject/preheader) fix flow

Subject/preheader are NOT inside the `#email-message-composer-portal`. They live in the "Sending Info" section of the compose step page, accessible via the "Edit sending info" button.

To fix a corrupted subject/preheader in edit mode:
1. Navigate to compose step (`?page=3`)
2. Click "Compose Messages"
3. Scroll to "Sending Info" section, click "Edit sending info"
4. Find Monaco editors: `subject` editor has `id` containing `sending-info-subject-input`, preheader has `sending-info-preheader-input`
5. Click the Monaco editor's `.view-lines` at `(rect.x + rect.w/2, min(rect.y + 20, 900))` to focus it
6. `Meta+A` → clipboard paste new value
7. Close panel via "Save" button
8. Save as draft

Do NOT use `locator.fill()` on Monaco editors — it doesn't properly update their React state. Always use click + `Meta+A` + clipboard paste.

## Brief-specified layouts override pixel widths

When an Asana brief uses "50/50 left" / "50/50 right" in slice header names, use those layout hints directly in `discover_image_configs()` instead of inferring from pixel widths. The `_parse_slice_layouts()` function parses these hints; `discover_image_configs(layouts=...)` accepts them as an override.

This matters when designers deliver images at different widths than the target layout (e.g., all images at 900px but some are intended to be 50/50).

## Link href vs anchor text in _parse_slice_links

Asana html_notes sometimes use `<a href="REAL_URL">display-text</a>` where the display text differs from the href. Stripping HTML and reading the text returns the wrong URL.

**Fix:** Search for `href=` attribute in the raw HTML block first; fall back to plain-text URL only when no anchor tag is present.

**When to apply:** `_parse_slice_links()` in `build_cz_designed_email.py` — now implemented.

## En-dash in slice header split regex

Asana sometimes uses en-dash (–, U+2013) in slice names like "Slice 2 – DEK". The original split regex `[—\-]` only handled em-dash and hyphen. Added en-dash: `[—–\-]`. Missing this causes the DEK slice to be merged into the hero block, shifting all link/alt/layout assignments by one.
