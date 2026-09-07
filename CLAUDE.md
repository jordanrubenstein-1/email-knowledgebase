# Email Knowledgebase

AI-queryable archive of email marketing campaigns across 7 brands (Braze + Klaviyo).

## Workflow

**Work directly on `main` — do not create branches.** Commit straight to `main`, even when the user asks you to commit or push. This **overrides** any default behavior to "branch first when on the default branch" — that habit does not apply in this repo. Do not create feature branches, topic branches, or fix branches for any reason.

**Do not use git worktrees.** Do not invoke `superpowers:using-git-worktrees` or create worktrees at any point. If an executing-plans skill or similar workflow requires a branch or worktree, skip that step and work directly in the `main` checkout instead.

## Team Pronouns

When referring to the following people in any generated text (Slack messages, Asana comments/tasks, emails, summaries, briefs) — regardless of who is nominally "speaking" in the drafted text — use these pronouns:

- **Jordan Rubenstein** — they/them
- **Emmy** — he/him

## Skills

When writing, drafting, or refining **any copy** for a brand — including subject lines (SL), preheaders (PH), plain-text email body copy, SMS, push notifications, or creative direction — always invoke that brand's copywriter skill **before** generating content.

### HAV — Havenly Copywriter
Invoke `anthropic-skills:havenly-copywriter` for all Havenly copy (SL/PH, PT email body, push).

### CZ — The Citizenry Copywriter
Invoke `anthropic-skills:citizenry-brand-voice` for all Citizenry copy (SL/PH, PT email body, SMS).

### ID — Interior Define Copywriter
Invoke `anthropic-skills:interior-define-copywriter` for all Interior Define copy (SL/PH, PT email body, SMS, push).

### BUR — Burrow Copywriter
Invoke `anthropic-skills:burrow-copywriter` for all Burrow copy (SL/PH, PT email body, SMS).

### STF — St. Frank Copywriter
Invoke `anthropic-skills:st-frank-copywriter` for all St. Frank copy (SL/PH, PT email body, SMS).

### TI — The Inside Copywriter
Invoke `anthropic-skills:the-inside-copywriter` for all The Inside copy (SL/PH, PT email body, SMS).

### Trade Emails
- **Single-brand Trade email** (e.g. ID Trade, CZ Trade) — invoke that brand's copywriter skill.
- **Cross-brand / general Trade email** — invoke `anthropic-skills:havenly-copywriter`.

## Brands
| Code | Brand (Asana) | Notes |
|------|---------------|-------|
| **HAV** | Havenly | Best opens (52.5%), editorial content works |
| **CZ** | The Citizenry | Personalization is key lever |
| **ID** | Interior Define | List quality issue (improving mid-2025) |
| **BUR** | Burrow | Content problem — text-only emails work best |
| **STF** | St. Frank | Highest clicks (1.48%), product-focused |
| **TI** | The Inside | Klaviyo (+ 9 legacy Braze campaigns) |
| **TE** | The Expert | Klaviyo only (new brand) |
| **X-Brand** | X-Brand | Cross-brand campaigns |

When searching Asana: task names use **codes** (e.g., "HAV"), but the Brand custom field uses **full names** (e.g., "Havenly").

## Brand Resources

**Havenly Brands Overview Deck** — primary brand voice reference for all 6 brands (HAV, CZ, ID, BUR, TI, STF). Fetch with WebFetch before writing copy for any brand.
URL: https://docs.google.com/presentation/d/1rs-nMnC9FAO3RXi84iWSX2PCDta2Sg29_t1852x9Fbw/edit?usp=sharing

### Campaign URLs & Discounts
- **CZ Back in Stock LP**: `https://www.the-citizenry.com/collections/all-back-in-stock`
- **CZ Meadow Press Collection**: `https://www.the-citizenry.com/pages/the-meadow-press-collection`
- **CZ Rugs LP** (CTA "Shop Rugs"): `https://www.the-citizenry.com/collections/shop-all-rugs-1` — NOT `/collections/rugs` or `/collections/fall-2025-rugs` (seasonal collection, wrong link)
- **CZ Archive Sale discount**: Up to 70% off
- **CZ — never suggest `https://www.the-citizenry.com/collections/shop` as a link in any brief/description.** Banned outright, not just deprioritized — do not fall back to it even when no better single-collection match exists for a cross-category email (e.g. a Color Edit). Use the homepage (`https://www.the-citizenry.com/`) or a specific product/category link instead.
- **STF Swatches LP**: `https://www.stfrank.com/collections/swatches`

## Key Files
```
email-knowledgebase/
├── campaigns/                    # ~9,200 campaign YAML files (Braze + Klaviyo)
│   ├── *.yaml                   # One per campaign/canvas step
│   ├── html/                    # Email HTML bodies
│   └── screenshots/             # Rendered email screenshots (12GB, gitignored)
├── scripts/
│   ├── import_braze.py          # Main import (campaigns + canvases) — HAV, CZ, ID, BUR, STF
│   ├── import_klaviyo.py        # Klaviyo import (campaigns + flows) — TI, TE
│   ├── import_sale_schedules.py # Sync sale schedules from Asana Promo Tracking Board (--source asana)
│   ├── flatten_canvases.py      # Convert canvas steps to campaign records
│   ├── backfill_analytics.py    # Repair analytics for old campaigns
│   ├── backfill_send_dates.py   # Add send_date to all YAMLs from campaign name (no API calls)
│   ├── backfill_scheduling_metadata.py  # Add local_time_send/sto/scheduled_time via Braze API re-fetch
│   ├── backfill_html_screenshots.py
│   ├── analysis/                # One-off analysis scripts
│   └── utils/                   # Utility modules (sale_matcher, inventory_checker, klaviyo_client, etc.)
├── data/
│   ├── sale_schedules.yaml      # Imported sale/promo schedules
│   ├── lifecycle_guidelines.yaml # Brand send cadence, segments, send times
│   └── calendar_task_mapping.yaml # Dedup tracking for calendar→Asana import
├── docs/
│   ├── setup/                   # GA4, Snowflake setup guides
│   ├── automation/              # Braze automation docs
│   └── legacy/                  # ANALYSIS.md
├── reports/                     # Analysis outputs (MD + PDF)
├── exports/                     # CSV data exports
├── components/                  # Email component library
└── .env                         # API keys (gitignored)
```

## Campaign YAML Schema
```yaml
id: uuid
name: P_EM_2025_07_20_HAV_PC_Summer_Sale_Reminder_PT
brand: HAV
channel: email                   # email, sms, or multi
category: sale_promo             # sale_promo, editorial, product_launch, reminder, other
type: announcement
braze_type: campaign             # campaign or canvas_step
campaign_type: One-Time Send     # One-Time Send, Triggered Journey, etc.

dates:
  created: "2025-07-15"
  send_date: "2025-07-20"           # PRIMARY analysis date — parsed from campaign name; use this for "when was it sent?"
  inferred_send_type: scheduled     # Best-guess delivery mode from first_sent/last_sent spread:
                                    #   scheduled  = spread < 15h (fixed UTC time + queue delays)
                                    #   local_time = spread 15-30h (rolling window across time zones)
                                    #   sto        = spread > 30h (Intelligent Timing / STO)
  first_sent: "2025-07-20T14:15:00+00:00"  # First email actually delivered (UTC)
  last_sent: "2025-07-20T17:15:00+00:00"   # Last email actually delivered (UTC)

schedule_type: time_based           # Braze campaign schedule type: time_based | action_based | api_triggered
                                    # NOTE: Braze returns time_based for ALL batch sends — it does not distinguish
                                    # local-time delivery from STO from fixed-UTC in this field for sent campaigns.

sends:                           # Message variants
  - id: uuid
    channel: email
    name: Variant 1
    subject: "Subject line here"
    preheader: "Preview text"
    html_file: html/slug.html
    screenshot: screenshots/slug.png
    image_urls: [...]

performance_summary:
  total_sends: 229606
  total_delivered: 226072
  total_opens: 97419             # Unique opens (not total)
  total_clicks: 370              # Unique clicks (not total)
  open_rate: 0.4243              # unique_opens / total_sends
  click_rate: 0.0016             # unique_clicks / total_sends
  total_unsubscribes: 540

# Canvas-specific fields (for braze_type: canvas_step)
canvas_id: uuid
canvas_name: "Cart Abandonment Flow"
flow_type: cart_abandonment      # cart_abandonment, browse_abandonment, welcome_series, etc.
sequence_position: 1             # T1, T2, T3...

# Asana metadata (optional)
asana:
  gid: "1234567890"
  name: "Task name in Asana"
  matched_by: "date+kw_0d_80%"

structure:                       # Email structure analysis
  image_count: 5
  link_count: 12
  has_gif: false
  layout_type: product_grid      # text_only, hero_only, product_grid, editorial
```

## Campaign Naming Convention

All Braze campaigns **must** follow the naming convention documented in `.cursor/rules/campaign-naming-convention.mdc`.

**Pattern:** `[TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_[DESIGN]_[HAV_AUDIENCE?]_[CONTENT_TYPE?]_Description[_SUFFIX?]`

**Quick reference:**
- **Types**: P (Promotional), OT (Transactional), CX, WTL (Waitlist), SEG (Segmented)
- **Channels**: EM, SMS, PUSH
- **Brands**: HAV, CZ, SF, ID, TI, BW (Burrow), TRADE
- **Design**: D (Designed), H (HTML), PT (Plain-Text) — required for email, omit for SMS
- **HAV Audience** (HAV only): PC (Pre-Converted), CONV (Converted)
- **Content Types** (optional): BIS, CLR, CS, GTL, PF, RTS, UGC, At_Risk, Cart_Abandon, etc.
- **PR is deprecated** — sale context comes from `data/sale_schedules.yaml`, not campaign names

**Examples:**
```
P_EM_2026_02_10_HAV_D_PC_PF_Summer_Sale_Reminder
P_EM_2026_01_29_CZ_D_Winter_Retreat_Sale_Last_Chance
P_SMS_2026_01_29_BW_Sale_Final_Hours
OT_EM_2026_02_01_ID_D_Order_Confirmation
```

**Punctuation rule:** Campaign names must never contain colons, commas, em dashes, or any other punctuation. Use only alphanumeric characters, underscores, and spaces (per the convention above). This applies to auto-built names in `generate_campaign_name()` and any script that constructs a Braze campaign name string.

**"Shop" rule:** Never include the word "Shop" (any case) in a Braze campaign name, canvas step name, or Asana task title. GA4 misclassifies sessions from campaigns containing "Shop" as Organic Shopping instead of Email, breaking attribution in marketing dashboards. Rephrase: "Shop by Category" → "Browse by Category", "Shop the Edit" → "The Edit", "Shop the Sale" → "Explore the Sale", etc. If you encounter an existing campaign or step with "Shop" in the name while working on it, rename it. This applies to names only — "shop" in email body copy is fine.

**Utility module:** `scripts/utils/campaign_name.py` — `generate_campaign_name()`, `validate_campaign_name()`, `parse_campaign_name()`

**Reference:** [Braze Campaign Name Conventions (Google Sheet)](https://docs.google.com/spreadsheets/d/10GQdM8YUfQQuCOvgk7fvzHvyswdrxM5e6j0Qii8g4Lk)

## Plain-Text Emails

### Greeting (all brands)

Every Braze plain-text email across every brand must use the Liquid first-name greeting:

```
Hi {{${first_name} | default: 'there'}},
```

Never hardcode `Hi there,` or any other static greeting.

### Link placement rules

Every PT email body must contain **at least 1 link**. Use this priority order to determine what to link:

1. **Explicit links in the Asana description** — if the description contains hyperlinked text (e.g., "The James Collection" links to a URL), use those links and that anchor text.
2. **"LINK" placeholder in copy** — if the description has a pattern like `Shop early access: LINK`, the text *before* "LINK" is the anchor; do not make "LINK" itself a hyperlink. Apply formatting rules below.
3. **"here" language** — phrasing like "Shop the sale here." signals a link; link the surrounding text (not just "here"), typically the full phrase or sentence.
4. **Bold text in description** — if none of the above apply, bold text signals the link anchor. Keep the text bold AND make it a link.
5. **No signal at all** — pick a logical place (e.g., a CTA phrase or collection name) and add an Asana comment: *"I wasn't sure where to link, please verify that the email link(s) are correct."* Place it after the auto-build line, before the STO line and campaign link.

**Formatting the anchor when using the "LINK" placeholder pattern:**

| Anchor word count | Format |
|---|---|
| ≤ 3 words | Drop the colon, add an arrow: `Shop early access → URL` |
| 4–6 words | Drop the colon, add a period, link the full phrase: `Shop early access.` (linked) |
| > 6 words | Link a shorter sub-phrase only (e.g., just "Shop" or just "Memorial Day Sale") |

### CTA links must be HTML anchors

Plain-text email bodies need CTA links formatted as HTML anchors — not bare URLs. This applies to both **campaigns** and **Email Templates**. Use the `cta_links` field in the campaign config dict:

```python
campaign_config = {
    "name": "...",
    "email": {
        "subject": "...",
        "body": "...\n\nhttps://burrow.com/refer\n\n...",
        "cta_links": [
            {"text": "https://burrow.com/refer", "url": "https://burrow.com/refer", "priority": 1},
        ],
    },
}
```

Both `create_email_template` (`braze_template_api.py`) and `create_braze_campaign` (`braze_campaign_api.py`) process `cta_links`, replacing each matching text occurrence with:
```html
<a href="URL" style="color: #0000EE; text-decoration: underline;">link text</a>
```

The link text in `body` and the `text` field in `cta_links` must match exactly.

### CZ PT sender

CZ PT emails send from **`Lisa at The Citizenry`** (`info@mail.the-citizenry.com`), not `The Citizenry` — that display name is the designed-email sender. Both share one address, so if the "Lisa at The Citizenry" option is ever missing from Braze's From dropdown the builder's fallback silently selects the other sender with the same address and the send goes out under the wrong name (confirmed 2026-07-27 on [Summer Sale Reminder](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1216732556019966)). `_fill_sending_info()` now logs a warning when the exact display name isn't in the dropdown — if that appears, add the sender in Braze (Settings > Email Preferences) rather than accepting the fallback. Configured in `data/brand_config.yaml` under `CZ.sender_info.pt`.

### CZ PT sale disclaimer

CZ PT emails sent during an active sale must include a disclaimer in the Row 6 (disclaimer) section of `components/cz_pt_template.html`. Look up the current discount % and end date from the [Asana Promo Tracking Board](https://app.asana.com/1/5257710284167/project/1213996005172086/) and pass via the `disclaimer` field:

```
For a limited time, receive {DISCOUNT}% off sitewide. Sale ends {END_DATE} at midnight EST. These products are not eligible for additional discounts. Not valid on previous purchases or gift cards. Please refer to individual product details for returns and exchange information. Select styles are final sale.
```

The disclaimer renders in small gray italic text below the signoff. If it's not a sale send, omit the disclaimer entirely (Row 6 is removed from template).

### HAV PT sale disclaimer

Havenly PT emails sent during an active sale (look up `data/sale_schedules.yaml`, matched by brand and `havenly_audience` for PC/CONV per the Promo Lookup rule) must include a disclaimer at the very bottom of the email body, after the signoff:

```
Offer applies to select items only. Prices as marked. Total discount reflected at checkout. See complete Terms & Conditions.
```

Use **"Offers apply"** (plural) instead of "Offer applies" when the active promo has multiple discount rules/tiers (e.g. a Buy More Save More tiered offer with separate $-threshold tiers); use the singular "Offer applies" for a single flat discount. "Terms & Conditions" links to `https://havenly.com/current-promotions` (see Terms & Conditions link rule below). If it's not a sale send, omit the disclaimer entirely.

**Implemented in `build_pt_campaign.py`:** `_get_sale_disclaimer()` handles HAV as a special case (fixed text, not templated from discount %/end date) — matches `sale_schedules.yaml` by `havenly_audience`, and picks `_HAV_SALE_DISCLAIMER_SINGULAR`/`_PLURAL` via `_hav_discount_has_multiple_rules()` (counts `\d+%` occurrences in the sale's discount string — more than one means plural). Rendered into `components/hav_pt_template.html`'s Row 2 (`<!-- BEGIN_DISCLAIMER_ROW -->`/`<!-- END_DISCLAIMER_ROW -->`, between the body-content row and the logo footer row), the same marker pattern used by the BUR/CZ/STF PT templates. Row is stripped entirely outside an active sale.

### HAV Terms & Conditions link (all channels, all sends)

Every Havenly send — designed email, plain-text email, SMS, push — must link to the complete promo terms page: `https://havenly.com/current-promotions`. For PT emails this is folded into the sale disclaimer above (the "Terms & Conditions" anchor). For designed emails, SMS, and push, add the same link (e.g. as a footer/terms line or linked disclaimer) whenever the send is tied to an active sale — this is not yet wired into `build_designed_campaign.py` or the SMS/push builders; do that when next touching those paths.

### Brand-specific PT standards

**PT email closings and signoff names** — source of truth is `data/brand_config.yaml` under `pt_email_styles` (each brand's `default_signoff` and `default_signoff_name`). Do not duplicate those values here.

**HAV (both PC and CONV)**
- PT `from_name`: `Lisa from Havenly` | `from_email`: `hello@mail.havenly.com` | `reply_to`: `hello@havenly.com`
- Designed `from_name`: `Havenly`
- Configured in `data/brand_config.yaml` under `HAV_PC` and `HAV_CONV`

**BUR (Burrow)**
- PT `from_name`: `Lisa at Burrow` | `from_email`: `friends@em.burrow.com` | `reply_to`: `friends@burrow.com`
- Designed `from_name`: `Burrow`
- Footer: use content block `{{content_blocks.${PT_sale_footer_unsubscribe}}}` — not a manual unsubscribe link
- Bold text: use `<b>...</b>` tags
- API brand key: pass `"BUR"` (not `"BW"`) to `create_email_template` and other Braze API wrappers; `.env` key is `BRAZE_API_KEY_BUR`

**ID (Interior Define)**
- `from_name`: `Lisa from the Interior Define Team` (set at campaign/canvas message step level)
- `reply_to`: `support@23765919.hubspot-inbox.com` (set at campaign/canvas message step level)
- Footer (9px): Copyright © [year], Interior Define, 3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209; unsubscribe link via `{{${set_user_to_unsubscribed_url}}}`
- HTML structure: 600px wide table, `font-family:Arial,sans-serif;font-size:14px;color:#101b24;line-height:150%`; body paragraphs `<p style="margin:0 0 14px 0;">`; links `color:#1871D8;text-decoration:underline`
- The CZ PT header logo intentionally carries **no alt text** — Braze falls back to the first text in the email when no preheader is set, so alt text on the logo gets pulled into the preheader ahead of the body copy. The auto-QA alt-tag check exempts the **first** image in a PT email for this reason (`_alt_exempt_images()` in `qa_designed_email.py`); every other image in a PT email, and every image in a designed email, still needs alt.
- Unsubscribe may come from either `{{${set_user_to_unsubscribed_url}}}` or a shared content block such as `{{content_blocks.${PT_sale_footer_unsubscribe} | id: 'cb2'}}` (the `id:` value varies per campaign and is not meaningful). The auto-QA unsubscribe check (`_html_has_unsubscribe()` in `qa_designed_email.py`) accepts **any brand's** content block whose name contains "unsub", so a block shared across brands no longer reads as a missing footer; only blocks whose name doesn't say "unsub" (BUR `footer_us`/`sale_footer_us`, STF `footer`) stay brand-scoped in `_UNSUB_CONTENT_BLOCKS`.

### ID Product Facts (all copy, all channels)

- **Leather is top-grain only — never "full-grain."** Interior Define's leather product line is top-grain leather; ID does not offer full-grain leather. Any ID copy that references a leather grade (email SL/PH/body, SMS, push) must say "top-grain leather," not "full-grain leather." Vague references ("premium leather," "quality leather") are fine — only a spelled-out grade claim needs to say top-grain. (Confirmed 2026-08-05 after the PT email "Leather that lives up to the hype" described ID leather in a way that implied full-grain.)

## SMS

### Link formatting (all brands)

The sentence immediately before the link must end with a **colon**, not a period:

- **Correct:** `25% off sitewide: LINK`
- **Wrong:** `25% off sitewide. LINK`

**Exception:** If that sentence already contains a colon, keep a period to avoid double-colons.

## Auto-Build Rule: HTML Source

**Never use old campaign HTML files** from `campaigns/html/` as a source or template when auto-building a designed email. Old files contain expired Braze CDN image URLs and last year's assets.

The correct sources for the email body are:
1. **Asana task brief** — the Body Copy section defines slice structure, links, and alt text
2. **Designer's image assets** — the Google Drive folder in the Email Slices/Banners/Blocks Details field

Use `scripts/build_cz_designed_email.py` (brand-parameterized via `brand=` — serves CZ and STF) which handles the full pipeline: Drive download → Braze CDN upload → HTML assembly → campaign creation. Do not copy or adapt any existing HTML file.

### `build_cz_designed_email.py` — confirmed behavioral rules

Seven rules confirmed for `scripts/build_cz_designed_email.py` and its `edit_existing_campaign` path:

1. **Monaco editor must be scoped to the portal in edit mode** — The compose step page has subject/preheader Monaco editors in the DOM *before* the `#email-message-composer-portal` div. `page.locator(".monaco-editor").first` resolves to the subject editor, not the HTML body editor. In edit mode this causes clipboard paste to overwrite the subject line with the full HTML body. Fix: always scope to `portal.locator(".monaco-editor")` when `#email-message-composer-portal` is present.

2. **Edit-mode navigation: compose step → Edit message** — Navigating to the campaign URL lands on the overview page (or already on the compose step via `?page=3`). Click "Compose Messages" wizard step first, then scroll and click "Edit message" to open the HTML editor portal. The portal's internal tabs are "HTML / Classic / Plaintext / AMP" — the sidebar "Content" button (behind the portal) is a different element entirely and must not be clicked.

3. **Fixing subject/preheader: use "Edit sending info"** — Subject and preheader are NOT inside the HTML editor portal. To fix them in edit mode: navigate to compose step → click "Edit sending info" → find Monaco editors by `id` containing `sending-info-subject-input` or `sending-info-preheader-input` → click the `.view-lines` area at `(rect.x + rect.w/2, min(rect.y + 20, 900))` → `Meta+A` → clipboard paste. Do NOT use `locator.fill()` on Monaco editors; it does not properly update their React state.

4. **Brief-specified 50/50 layouts override pixel-width detection** — `_parse_slice_layouts()` reads "50/50 left" / "50/50 right" hints from slice header lines in `html_notes`. `discover_image_configs(layouts=...)` accepts these as an override of the pixel-width inference. Use brief labels when the designer specifies them; fall back to pixel widths only when no hints are found.

5. **Link href takes priority over anchor text in `_parse_slice_links`** — When a `Link:` field uses `<a href="REAL_URL">display-text</a>` where text ≠ href (e.g. `<a href="/collections/custom-furniture">https://www.the-citizenry.com</a>`), reading plain text gives the wrong URL. `_parse_slice_links` now searches for the `href` attribute first in the raw HTML, falling back to plain-text parsing only when no anchor tag is present.

6. **Blank Asana Segment field must default to Full File, not Engaged — confirmed 2026-09-04.** Two spots both defaulted the wrong way: `build_campaign_config()`'s `segment_name = _get_cf_enum_name(task, FIELD_SEGMENT) or "Engaged File"`, and `build_campaign_playwright()`'s `_segment_map.get(segment_name, "engaged")` fallback for an unrecognized value. This contradicted CLAUDE.md's documented default for all three brands this builder serves — CZ ("default Full File; 1–2 sends/week use Engaged"), STF ("always Full File"), and BUR ("default Full File; 2–3 sends/week use Engaged") — so any CZ/STF/BUR designed email built with a blank Segment field silently under-targeted to Engaged instead of Full File. The older Braze DnD builder (`build_designed_campaign.py`, via `resolve_segment_type_for_task()`) already defaulted correctly to `full_file`; only this newer HTML/CSS builder had drifted. Both defaults now resolve to `"Full File"`/`"full_file"`; an explicit "Engaged File"/"Engaged Audience" selection on the task is unaffected.

7. **Campaign naming must go through the shared prefix-stripping helper — confirmed gap 2026-09-05.** This builder called `generate_campaign_name()` directly with the raw Asana task name, skipping the prefix-stripping regex both the Braze DnD builder and the Klaviyo designed-email builder apply via `_derive_campaign_name()` (`build_designed_campaign.py`). That regex strips more than just HAV's `MP:`/`DPS:`/`MP/DPS:` audience tokens (which don't apply to CZ/STF/BUR anyway) — it also strips a stray `SMS:` prefix and the task's own brand code (e.g. `CZ:`, `STF:`, `BUR:`), both of which are brand-agnostic and did apply here. A CZ task literally named "CZ: Color Edit" kept the redundant prefix baked into the generated campaign name, where the other two designed-email builders would have stripped it. Now calls the shared `_derive_campaign_name("", task_name, due_on, brand)` — empty `ref_name` since this from-scratch builder has no ref campaign, matching the Klaviyo designed-email builder's own call.

**Bonus:** Slice-split regex uses `[—–\-]` (em-dash, en-dash, hyphen). Asana sometimes writes "Slice 2 – DEK" with an en-dash — the original `[—\-]` missed this, merging the DEK block into the hero block and shifting all link/alt/layout assignments by one.

---

## HTML/CSS Brand Migration

Brands on the from-scratch HTML/CSS designed-email builder: **CZ** (cutoff 2026-05-30), **STF** (cutoff 2026-07-20), **TI** (cutoff 2026-07-21, Klaviyo), and **BUR** (cutoff 2026-08-18). Same detection (Drive URL + due-date cutoff) drives all four; the **builder differs by platform**:
- **Braze brands (CZ, STF, BUR)** → `scripts/build_cz_designed_email.py` (Playwright, Braze campaign + Braze CDN), brand-parameterized (`brand=` arg). Footer, Braze API key, homepage fallback, sale lookup resolved from the `brand` code inside it. BUR's footer is content-block based (`footer_us` / `sale_footer_us`), same pattern as CZ — not STF's inline HTML.
- **Klaviyo brands (TI)** → `scripts/braze_automation/build_klaviyo_designed_email.py` (API-based, Klaviyo campaign + Klaviyo CDN). Both builders share `scripts/braze_automation/designed_email_core.py` for Drive listing/download, layout classification, image caching, and HTML assembly, so the assembled markup is identical across platforms.

**Alt-text fallback added to the Klaviyo path — confirmed gap 2026-09-05.** The Braze CZ/STF/BUR builder (`build_cz_designed_email.py`, does **not** actually import `designed_email_core.py` — it has its own independent parsing) has always had a rich per-slice alt-text chain (`_parse_slice_alts()`: CTA → HED → Name → logo detection → prettified filename). `designed_email_core.py`'s `download_and_upload_slices()` — the shared core the Klaviyo builder does use — had no equivalent at all: every slice's alt text was just the raw Drive filename stem (e.g. "Slice 3"), regardless of brief content. Ported the same priority logic into `parse_brief_slices()` (only CTA is length-gated; HED/Name/Product tag/Eyebrow are used verbatim, matching Braze's own asymmetry) via two new helpers, `_parse_slice_fields()` and `_derive_slice_alt()`, and a matching `_prettify_filename_alt()` last-resort fallback. `build_klaviyo_designed_email.py` threads the result through as `sf["_alt_override"]`, alongside the existing `_link_override`.

The builder split lives in `_dispatch_htmlcss_designed_build` (webhook) / the `_KLAVIYO_HTMLCSS_BRANDS` branch (poller): brand in `_KLAVIYO_DESIGNED_BRANDS` (`{TI, TE}`) → Klaviyo builder, else the Braze builder.

When adding a brand, the routing in **two files must stay in lockstep**. Missing one causes DnD builds to continue silently through the other path. (This happened with CZ on 2026-06-02 when `poll_ready_tasks.py` was missed.)

### Files to update

| File | What to change |
|------|---------------|
| `scripts/braze_automation/webhook_server.py` | Add `"{BRAND}": "{cutoff}"` to the `HTMLCSS_DESIGNED_CUTOFFS` map. The generic detection (`is_htmlcss_designed`) needs no change. Dispatch (`_dispatch_htmlcss_designed_build`) already branches Klaviyo vs Braze off `_KLAVIYO_DESIGNED_BRANDS` — no change unless the new brand is on a third platform. |
| `scripts/braze_automation/poll_ready_tasks.py` | Add the same `"{BRAND}": "{cutoff}"` entry to its `HTMLCSS_DESIGNED_CUTOFFS` map. For a Klaviyo brand, also add it to `_KLAVIYO_HTMLCSS_BRANDS`. |
| `scripts/build_cz_designed_email.py` | **Braze brands only.** If the brand's footer differs — add a brand branch in `_footer_html()` (CZ = content blocks, STF = inline). Add the brand's homepage to `_BRAND_FALLBACK_LINK`. |

**Env / config checklist:**
- **Braze brand:** confirm `BRAZE_API_KEY_{BRAND}` **and** `BRAZE_API_KEY_MEDIA_{BRAND}` in `.env`, plus a `brand_config.yaml` entry with `audiences` + `conversion_events`.
- **Klaviyo brand (TI):** confirm `KLAVIYO_API_KEY_{BRAND}` in `.env` (no Braze/media keys needed — uploads go to Klaviyo's CDN), plus a `brands.{BRAND}.designed_email` section in `brand_config.yaml` (`homepage` + `footer`).

**Poller safety-net — Drive-URL-only tasks:** `fetch_ready_to_code_designed_tasks(brand_filter=None, htmlcss_cutoffs=None)` returns Ref-Braze-Campaign tasks by default (needed by the DnD duplicator + Klaviyo ref-campaign clone). When the poller passes its `HTMLCSS_DESIGNED_CUTOFFS` as `htmlcss_cutoffs`, the fetch **also** returns tasks with a Drive URL but **no** Ref Braze Campaign that qualify as an HTML/CSS build (`_qualifies_htmlcss_task` — same brand/type/cutoff/Drive gate as `is_htmlcss_designed`, so an admitted no-ref task always hits the HTML/CSS branch, never the DnD path). This closes the gap where a Drive-only TI/CZ/STF task briefed without a ref campaign was built only by the webhook and was invisible to the 15-min poller. A new HTML/CSS brand added to `HTMLCSS_DESIGNED_CUTOFFS` is covered automatically; no fetch change needed.

**Klaviyo ref-campaign clone naming was broken — confirmed 2026-09-04, never actually run to completion.** `build_klaviyo_designed_campaign.py` (the ref-campaign-clone path for a Drive-URL task with no HTML/CSS Drive assets yet, or pre-cutoff) called `_derive_campaign_name(ref_campaign, task_name, send_date)` — the shared helper imported from `build_designed_campaign.py`, which requires a 4th `brand` argument to strip the brand-code task-name prefix and resolve the HAV PC/CONV audience token. The 3-arg call raised `TypeError` unconditionally, so every real (non-dry-run) invocation of this builder would have crashed before creating anything. Fixed by passing the `brand` parameter already in scope (`_derive_campaign_name(ref_campaign, task_name, send_date, brand)`), matching the correct 4-arg call in `build_klaviyo_designed_email.py` and the original in `build_designed_campaign.py`.

### Routing conditions (must match in both files)

A task qualifies for HTML/CSS if ALL of:
- Brand is a key in `HTMLCSS_DESIGNED_CUTOFFS`
- Type ≠ Plain-Text
- `due_on >= HTMLCSS_DESIGNED_CUTOFFS[brand]`
- `Email Slices/Banners/Blocks Details` field contains a `drive.google.com` URL

The Drive-URL check runs **before** the Ref Braze Campaign check, so a qualifying task routes to HTML/CSS even if a Ref Braze Campaign is also populated. Tasks that don't qualify (no Drive URL, pre-cutoff date) fall through to the DnD duplicator as before — intentional for historical/in-flight tasks.

### Cutoff date

Set the brand's cutoff to the first send date where the new pipeline should be used. All tasks with `due_on` before the cutoff continue to use DnD (preserving backward compatibility for in-flight work). Tasks on or after the cutoff with a Drive URL automatically use HTML/CSS.

### After deploying

Restart the webhook server so it picks up the new code. The LaunchAgent (`com.havenly.poll-ready-tasks`, runs every 15 min) picks up the change automatically on its next run — no restart needed.

### Restarting the webhook server (launchd-managed)

The webhook server runs as a **launchd service** `com.havenly.webhook-server` (alongside `com.havenly.ngrok-webhook`, `com.havenly.poll-ready-tasks`, `com.havenly.braze-session-refresh`, `com.havenly.webhook-ensure-registered`, `com.havenly.notify-lee-completions`). After merging any `scripts/braze_automation/` change to `main`, restart it via `launchctl` so the running process picks up the new code:

1. **Drain the queue first** — never kill an in-flight campaign build:
   ```bash
   curl -sf http://localhost:8765/health   # queue_depth must be 0
   ```
2. **Restart the service:**
   ```bash
   launchctl kickstart -k "gui/$(id -u)/com.havenly.webhook-server"
   ```
3. **Verify** — the health endpoint responds within a few seconds and the PID changed:
   ```bash
   launchctl list | grep webhook-server && curl -sf http://localhost:8765/health
   ```

Do **not** use `scripts/braze_automation/restart_webhook_server.sh` for the launchd-managed deployment — it does a manual `nohup uvicorn` start that fights launchd's respawn and can collide on port 8765. (That script is for non-launchd setups / the `.git/hooks/post-commit` path.) The `com.havenly.poll-ready-tasks` LaunchAgent still picks up code changes automatically on its next run — no restart needed for the poller.

---

## Building Braze Email Templates

Use `scripts/braze_template_api.py` (`create_email_template`) to create templates programmatically. See `scripts/create_template_and_guide.py` for the full workflow, or write a one-off script that calls `create_email_template` directly with a `campaign_config` dict.

### Template naming conventions

Template names must match how the template will be used — check the Asana task's **Type** and **Audience** fields:

| Asana signal | Naming convention to use | Example |
|---|---|---|
| Type = "Triggered Journey" OR Audience = "Triggered" | Canvas step (drip) convention | `TRG_EM_2026_04_BW_PT_Post_Delivery_Friendbuy_T1_V1` |
| Batch and blast | Batch/blast campaign convention | `P_EM_2026_04_25_BW_PT_Sale_Reminder_PM` |

### PT auto-build rules (`build_pt_campaign.py`)

Seven behavioral rules confirmed for `scripts/braze_automation/build_pt_campaign.py`:

1. **Variant 1 must always be 100%** — After removing the control group, Braze leaves Variant 1 at 80%. Call `_set_variant1_to_100()` at the END of `configure_target_audience()`, after segment selection (not inside `_remove_control_group()`), because segment picker interactions trigger React re-renders that revert earlier DOM changes. Use `fill("100")` + Tab.

2. **Intelligent Timing fallback must be a specific time** — Always select "a specific custom fallback time" (not "most popular time"). Default fallback is `07:00` local time (or the parsed send time from the Asana field). `build_designed_campaign.py` has the same `_set_intelligent_timing_fallback()` and requires the same fix (minutes `0` and `5` are single-digit in Braze's picker, not zero-padded).

3. **Bold and italic formatting from Asana must be preserved** — Fetch `html_notes` from the Asana API (not plain `notes`). `_html_notes_to_rich_text()` strips all HTML except `<strong>`/`<em>` (and normalizes `<b>`→`<strong>`, `<i>`→`<em>`). `convert_pt_body_to_html()` uses token-swap to preserve both through HTML escaping. **Confirmed bug 2026-09-05:** both functions' docstrings/comments already claimed `<em>` was preserved, but only `<strong>` actually had stash-and-restore tokens — `<em>` was silently stripped by the generic tag-strip in the first function, and HTML-escaped into visible `&lt;em&gt;` text in the second (for any `<em>` that happened to survive some other way). Every italic phrase from an Asana brief was silently lost. Fixed by adding the matching `__ITALIC__`/`\x00ITALIC\x00` stash-and-restore pair alongside the existing bold ones in both functions.

4. **Strip notes after the signoff** — Text after the sign-off/attribution line followed by 3+ blank lines is copywriter briefing notes — strip it from the body. `_is_signoff_attribution()` detects sign-off lines; `_strip_signoff()` removes the attribution line itself.

5. **Intelligent Timing needs real lead time** — `resolve_send_time()` used to default to Intelligent Timing for *any* send with no explicit Asana Send time, no PM marker, and no sale-announcement keyword — regardless of how close the send date was. A last-minute send cannot absorb STO's rolling per-user delivery window, so those campaigns must get a specific local time instead. Priority 5 is now gated on `business_days_until(task["due_on"]) >= STO_MIN_BUSINESS_DAYS` (5, shared constant in `build_pt_campaign.py`); below the threshold it returns a specific time — the parsed Asana time, else `07:15` (the brand AM default, matching Priority 3 and `resolve_send_time_designed()`). The designed builder's `_business_days_until()` and the QA delivery check now call the same `business_days_until()` helper, so all three agree on when STO is appropriate — they previously used three different rules (PT: always STO · designed: ≥5 business days · QA: ≥3 calendar days), which made QA flag correctly-built campaigns and miss wrongly-built ones. Confirmed 2026-08-22 on [ID Warehouse Sale PT Email](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1217700462638088), built 8/20 for an 8/22 send and given STO.

6. **Start Time must be filled even under Intelligent Timing** — `_set_entry_frequency()` only filled Braze's Start Time input when `send_time_config["time"]` was set, which is `None` for Intelligent Timing. That field is the campaign's *entry* time (not the per-user send time) and Braze pre-populates it, so skipping it left an arbitrary default standing — the ID Warehouse Sale campaign above went out with a 02:00 start rather than the intended morning. It now falls back to `fallback_time` when `time` is absent, so an IT campaign still enters at the intended hour. The fallback-time picker is still set *after* entry frequency (unchanged ordering — see rule 2).

7. **A missing subject line must be flagged, not shipped silently — confirmed gap 2026-09-05.** `parse_asana_task()` has always logged only a warning when no subject was found anywhere (description or the Subject Line field) — nothing visible to a human, and the campaign built with a blank subject. The Klaviyo PT builder (`create_klaviyo_email.py`) has posted a "⚠️ subject line is missing" Asana comment for this since it existed. `build_single_campaign()` now checks `config.get("subject")` right after building the config and, if empty, appends a warning to the same `result["warnings"]` list the HTML-QA check populates — so it rides the same @-mention comment as QA warnings (`build_warnings` in the post-build comment block), rather than needing a second comment path. The QA-warnings assignment (`result["warnings"] = qa_warnings`) was changed to `.extend()` so it no longer overwrites this missing-subject warning when both fire.

### Braze Canvas Webhook Liquid syntax

Confirmed working patterns for Canvas Webhook steps (Action-Based Canvases):

```liquid
{{!-- canvas_entry_properties: NO ${} in logic tags --}}
{% assign products_arr = canvas_entry_properties.products %}
{% for item in products_arr %}

{{!-- Timestamps in JSON: single-quoted 'now' --}}
"timestamp": "{{ 'now' | date: '%Y-%m-%dT%H:%M:%SZ' }}"

{{!-- braze_id in webhook body --}}
"braze_id": "{{ braze_id }}"
```

- `${...}` syntax is only for Braze personalization variables like `{{${external_user_id}}}` — not for canvas property access
- Cannot use `{{ }}` output syntax inside `{% %}` logic tags
- Authorization header value: `Bearer YOUR_KEY_HERE` (include "Bearer " prefix with space)
- `canvas_entry_properties` for Action-Based entry events; `canvas_event_properties` for events fired within Canvas via Action Paths steps
- If Canvas only has a Webhook step, Braze may block publishing with "Unavailable event properties" — add a User Update step first

## Klaviyo Integration (TI + TE)

Two brands use Klaviyo instead of Braze: **TI** (The Inside) and **TE** (The Expert), each on a separate Klaviyo account. TI also has 9 legacy Braze campaign YAMLs (from before the migration).

Klaviyo YAMLs follow the **same schema** as Braze campaigns with extra fields at the bottom:
- `klaviyo_type: campaign | flow` — one-time send vs triggered journey
- `klaviyo_campaign_id: {id}` — Klaviyo campaign ID (for analytics re-fetch)
- `klaviyo_message_id: {id}` — Klaviyo message variant ID

Field mappings: Klaviyo Campaign → `braze_type: campaign`; Klaviyo Flow → `braze_type: canvas_step`; Klaviyo Flow Action → `sequence_position`. Analytics via `POST /api/campaign-values-reports/`.

**Note:** TE campaign names don't follow the standard naming convention (e.g., `03-10-26 | New Arrivals | Shopping`). Filter on `brand: TE` rather than name patterns.

### Import Klaviyo campaigns

```bash
# Campaigns only (fast — skips analytics to avoid strict rate limit)
uv run python scripts/import_klaviyo.py --brand TI --skip-analytics
uv run python scripts/import_klaviyo.py --brand TE --skip-existing --skip-analytics

# With analytics (slow — 1 API call per campaign, quota exhausts quickly)
uv run python scripts/import_klaviyo.py --brand TI

# Campaigns + flows (triggered journeys)
uv run python scripts/import_klaviyo.py --brand TI --include-flows --skip-analytics

# Then generate screenshots
uv run python scripts/backfill_html_screenshots.py --brand TI
uv run python scripts/backfill_html_screenshots.py --brand TE
```

### Analytics backfill (run after ~20h quota reset)

The `campaign-values-reports` endpoint has a strict daily quota. After the quota resets, run the backfill script slowly:

```bash
# Fills in performance_summary for campaigns with total_sends: 0
# Default 3s delay between calls; ~2 hours for ~2000 campaigns
uv run python scripts/backfill_klaviyo_analytics.py --brand TI
uv run python scripts/backfill_klaviyo_analytics.py --brand TE

# Test first (dry-run)
uv run python scripts/backfill_klaviyo_analytics.py --brand TI --limit 10 --dry-run
```

### API key setup

Get private API keys from each Klaviyo account: Settings > API Keys > Create Private API Key (full access scopes for future automation). Add to `.env`:

```
KLAVIYO_API_KEY_TI=pk_...
KLAVIYO_API_KEY_TE=pk_...
```

### TI domain and link rules

- Always use `https://www.theinside.com/` — never `the-insideshop.com` or any other variant
- Links must come from existing links found in knowledgebase campaign files (don't guess URLs)
- SMS copy: use a colon before the link, not an arrow (`Shop new arrivals: https://www.theinside.com/collections/new-arrivals`)

### Klaviyo SMS auto-builder (`create_klaviyo_sms.py`)

Seven confirmed rules for TI/TE SMS:

1. **`add_org_prefix: False`** — Klaviyo accounts already prepend "The Inside: " / "The Expert: " at the carrier level; setting True duplicates the prefix.
2. **Campaign links** — pass the edit URL (`/text-message/campaign/{id}/edit`) to the Asana comment; pass the overview URL (`/campaign/{id}/overview`) to the Asana campaign field.
3. **TI default link** — never use `/collections/sale` as a default. The TI SMS fallback link is `https://www.theinside.com/` (homepage).
4. **Link must be appended even with no placeholder in the brief copy** — `resolve_link()` always resolves *some* URL (falls through to the homepage), but the old code only ever substituted it into an existing `LINK`/`[link]`/`<link>`/arrow placeholder via `apply_link()`. When the brief copy had no placeholder at all and no bare URL, the resolved link was silently discarded — the campaign built with no link anywhere in the body. Confirmed 2026-09-04 on the [Labor Day Event Last Chance](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1217247785391698) SMS (9/8 send), whose brief copy ("LAST CHANCE. The Inside's Labor Day Event ends tonight at midnight. Shop 25% off sitewide before it's gone.") had no link signal at all. Fixed via `has_link_placeholder()` + `append_link()`: when the body has no placeholder and no existing `http(s)://` URL, the resolved link is now appended to the end, following the same colon/period punctuation rule as the SMS Link Formatting rule above (colon before the link, unless the copy already contains a colon elsewhere, in which case a period is used to avoid a double colon). This mirrors behavior the Braze SMS builder (`build_sms_campaign.py`'s `extract_sms_copy()`) already had — this was a TI/Klaviyo-only gap, not a cross-brand one.
5. **Grammar/copy-quality check added — confirmed gap 2026-09-04.** The Braze SMS builder has had `check_copy_grammar()` (space-before-punctuation, double spaces, `":."` sequences) since before this file existed; `create_klaviyo_sms.py` had no equivalent at all. Both builders now share the checks from `scripts/utils/sms_grammar.py` (`check_copy_grammar()` + `SMS_URL_STRIP_RE`, the latter stripping the link out of the copy first so its own formatting can't produce a false positive) — `build_sms_campaign.py` was updated to import from there instead of defining it locally, so the two can no longer drift. Same non-blocking behavior as Braze: warnings print to console and post as a separate Asana comment after a successful build; they never block the campaign from being created.
6. **Live URL validation added — confirmed gap 2026-09-05.** The Braze SMS builder has always HTTP-checked a resolved landing URL via `validate_url()` (detects a redirect-to-homepage on what should be a specific page, and HTTP 4xx/5xx) before using it; `create_klaviyo_sms.py` trusted its resolved link blindly. Both builders now share the check from `scripts/utils/url_validation.py` — `build_sms_campaign.py` wraps it to keep routing messages through its own `logger` (same output format as before); `create_klaviyo_sms.py` calls it directly with print-based reporters. Same non-blocking behavior as Braze: a broken/redirecting URL only prints a warning, the link is still used — this check has never hard-blocked a build on either platform.
7. **Campaign-naming fallback added — confirmed gap 2026-09-05.** `generate_sms_campaign_name()` in `build_sms_campaign.py` (Braze) has always wrapped `generate_campaign_name()` in try/except, falling back to a manually-built name (`P_SMS_{date}_{brand}_{description}`) on `ValueError` (e.g. an unrecognized brand code or malformed date); `create_klaviyo_sms.py`'s `_generate_campaign_name()` called it unguarded, so the same class of edge case would crash the whole build. Now wrapped with the equivalent fallback.

### Klaviyo email campaign API — body/template workflow

Unlike SMS, Klaviyo email campaign-message `content` does **not** accept a `body` field. HTML body must go through a template:

1. `POST /api/templates/` with `{"data": {"type": "template", "attributes": {"name": "...", "html": "...", "editor_type": "CODE"}}}` → returns `template_id`
2. `POST /api/campaign-message-assign-template/` linking `message_id` → `template_id` (Klaviyo clones the template)

**Valid `content` PATCH fields** (`PATCH /api/campaign-messages/{id}/`):
- `subject` ✓, `preview_text` ✓, `from_email` ✓, `from_label` ✓ (NOT `from_name`), `reply_to_email` ✓
- ~~`body`~~ ✗ — use template workflow instead
- ~~`from_name`~~ ✗ — use `from_label`

**`KlaviyoClient` methods** (`scripts/utils/klaviyo_client.py`): `create_email_template(name, html)`, `assign_template_to_campaign_message(message_id, template_id)`, `update_campaign_message_content(message_id, content_dict)`

**Script:** `scripts/create_klaviyo_email.py` — auto-builds TI PT email from Asana task GID. Usage: `uv run python scripts/create_klaviyo_email.py --brand TI --asana-gid GID [--dry-run]`

**Link must be appended even with no link signal in the brief copy — confirmed 2026-09-04.** Same bug class as the TI SMS builder fix above: `resolve_link()` always resolves *some* URL (falls through to the homepage), but `body_to_html()`'s link pass (`_apply_link_rules_paragraph()`) only ever *substitutes* that URL into an existing signal — an explicit `<a href>`, a bracketed URL hint, a `LINK`/`[link]` placeholder, "here" language, a bare URL, or (as a last resort) a bold phrase. When a brief has none of those signals at all, the resolved link was silently dropped — the campaign built with no link anywhere in the body, mirroring the exact TI SMS bug fixed the same day. Fixed via a Rule 5 fallback in `body_to_html()`: when the paragraph-by-paragraph link pass and the bold-phrase fallback both leave `any_linked` False, the resolved link is appended as its own paragraph (`<a href="{link}">{link}</a>`) — matching the Braze PT builder's own Rule 5 fallback in `_apply_link_rules()` (`build_pt_campaign.py`: `body_copy.rstrip() + f"\n\n{homepage}"`).

**Campaign-naming fallback added — confirmed gap 2026-09-05.** `_derive_campaign_name()` in `build_pt_campaign.py` (the Braze PT builder) has always caught a `ValueError` from `generate_campaign_name()` and fallen back to the raw Asana task name; `create_klaviyo_email.py`'s own `_generate_campaign_name()` called it unguarded, so the same class of edge case (unrecognized brand code, malformed date) would crash the whole build. Now wrapped with the same fallback — returns the raw task name with a printed warning instead of crashing.

### TI filename collision handling

If a Braze YAML and a Klaviyo YAML have the same campaign name slug, the Klaviyo file gets a `klv-` prefix (e.g., `klv-p-em-2025-09-10-ti-cafe-curtains.yaml`). Both records are preserved.

### TI Figma Template Selection

When creating TI email Asana tasks, include the Figma template in the **Figma** field of the html_notes (standard 5-field format). Use the content → template match below. These are the **only** 9 available templates (from the "TI Templates Update" page, node `174:2`). Slice-by-slice brief instructions in `docs/figma-templates.md#ti-the-inside-email-figma-templates`.

| Figma section | Key | Node ID | Content type |
|---|---|---|---|
| POTM | `potm` | `174:32` | Print of the Month |
| Swatch edit | `swatch_story` | `174:76` | Swatch / trend print story (multi-swatch grid) |
| Swatch edit | `swatch_party` | `174:3` | Swatch edit (simple / short — "Swatch Party") |
| product multi category | `product_multi` | `174:202` | Multi-category product feature (beds, soft goods, outdoor) |
| product category | `product_single` | `174:351` | Product category (short) |
| product category | `seating` | `174:144` | Seating / chairs (numbered products) |
| color edit | `color_edit` | `175:607` | Color edit |
| destination edit | `destination` | `175:501` | Travel / destination editorial |
| category edit | `dining` | `175:562` | Dining / hosting / entertaining |

---

## The Expert (TE) Brand

TE uses Klaviyo (separate account). Campaign names use `MM-DD-YY | Topic | Audience` format — filter on `brand: TE`, not name patterns.

### Asana

TE tasks live in **Master CRM (Email & SMS)** (`1207522423363072`) — no dedicated section. Filter by Brand = The Expert (GID: `1213380147938608`).

| Field | Field GID | Value | Option GID |
|-------|-----------|-------|------------|
| Brand | `1207522425689880` | The Expert | `1213380147938608` |
| Channel | `1207562370794988` | Email | `1207562370794989` |
| Type | `1207522425689987` | Batch & Blast | `1209982215610998` |
| Category | `1207522425689885` | Editorial/Content | `1207522425689887` |
| Category | `1207522425689885` | New/Product Launch | `1207522425689888` |
| Audience | `1207522425689896` | Trade | `1207522425689962` |

### Send Cadence

- **3 emails/week** baseline
- **2 of 3** are paired sends: same content, different header/tone, different segment (End Consumer + Trade variant)
- **1 of 3** goes to End Consumer OR Trade only

### Weekly Content Calendar

| Day | Content |
|-----|---------|
| Mon / Tue | New Arrivals *(only if confirmed new arrivals exist)* or Home Tour / Spotted |
| Wed / Thu | Showroom Launch or Trade-specific content |
| End of month | "Best of Month" recap (last few days, prefer weekend) |
| Start of month | "New Dates" — End Consumer only, no Trade variant (first 1–2 days) |

Never assume New Arrivals exists — only schedule if confirmed.

### Paired Send Rules

- Trade variant task name = main name + " — Trade" suffix (e.g. "New Arrivals — Trade")
- **Trade tasks**: Audience = Trade — leave Segment blank
- **End Consumer tasks**: leave Audience blank — set Segment = Full File or Engaged
  - Always Full File: Best of Month, sale emails, product launches, big-name designers
  - Default to Engaged for all other emails

### Send Times

| Audience | Send Time |
|----------|-----------|
| End Consumer | 9:00 AM |
| Trade | 8:30 AM |

### Figma Templates

File key: `dzffPJHnElmsKrFu7Uw9D8` — [Expert Lifecycle Email Templates](https://www.figma.com/design/dzffPJHnElmsKrFu7Uw9D8/Expert-Lifecycle-Email-Templates)
URL format: `?node-id=[NODE_ID_HYPHENATED]` (hyphens, e.g. `2-36`)

| Template | Section Node | Best For |
|----------|-------------|----------|
| Home Tour / Studio Tour | `2:36` | Editorial home tour, designer profile, "Get the Look" product grid |
| New Dates | `2:234` | Designer availability drop, new consultation dates |
| New Arrivals | `9:277` | New product arrivals with editorial intro + product grid |
| Best of Month | `9:361` | Monthly digest — home tours, articles, editor's picks |
| Showroom | `9:490` | Showroom launch; End Consumer assembled comp `9:708`, Trade `9:782` |
| Book Club | `14:5` | Book recommendation + home tour story + product picks |

**Content → template quick match:**
- Home Tour / Spotted → Home Tour (`2:36`)
- New Arrivals → New Arrivals (`9:277`)
- New Dates → New Dates (`2:234`)
- Showroom (consumer) → Showroom End Consumer (`9:708`)
- Showroom (trade) → Showroom Trade (`9:782`)
- Best of Month → Best of Month (`9:361`)

### Subject Line Patterns

- **Sweet spot:** 30–70 characters (80.5% OR); avoid over 70 chars
- **Best formats:** Name-drop (designer/expert) → 77.8% OR; Number-led ("5 ways…") → 77.0%
- **Avoid:** Vague open-loops ("Something big is coming") → 37.7% OR; all-caps; clever-but-vague
- **Top words:** off, new, spotted, vintage, last, expert, love, your, how, now
- **Preheader:** no preheader → 86% OR vs with preheader → 74% (transactional/gratitude drives gap); still use preheaders for editorial/shopping sends

**Templates that work:** "[Expert name]'s [specific thing]" · "Spotted: [specific product]" · "[Number] [category] our Experts love" · "Last [day/chance]: [specific offer]"

### Content Performance Notes

- **Trade + Vendors** are highest-engagement segments (107% / 4.3% CTR and 143% / 13.7% CTR) — always create Trade variants
- **Hero-only layout** dramatically outperforms product grids (126% OR / 10% CTR vs 74.5% / 2.8%) — currently underused
- **Keep link count ~12** — 22+ links suppresses clicks on shopping sends
- **Vintage content** (only 4–5/year) → 14–17% CTR consistently — expand to 8–10 per year
- **Showroom audience** underperforms at 63% OR — needs redesign

---

## CZ Designed Email Task Creation

**Standing rules (create AND update):**
- Always suggest the appropriate Figma template — in the notes field, never as a comment
- Do NOT populate the **Template inspiration (with reasoning)** custom field for CZ tasks — leave it blank
- Do NOT populate: Top KPI/Objective, Banners/Blocks, or Specific Callouts fields

When creating a CZ designed email Asana task during a briefing, follow this sequence:

1. Determine the Figma template and fill "Template inspiration (with reasoning)" on the task
2. Run the ref campaign finder to get the best reference campaign:
   ```bash
   uv run python scripts/utils/ref_campaign_finder.py --task-name "<task description>" [--template "<letter>"]
   ```
   - `--template` is the Figma template letter just selected (e.g. `A` from "A. Multi-Hero …")
   - Add `--top 3` to see ranked alternatives
3. Populate the **"Ref Braze Campaign"** Asana field (GID: `1214484659930023`) with the returned campaign name

The finder uses hierarchical matching: descriptive keywords (Rug, Archive, Bedding) first, generic keywords (Sale, Reminder) as fallback, then most-recent if no match. Template letter boosts ranking within each tier when `template_inspiration` is populated in the YAML.

### CZ Figma Template Catalog

File key: `K043FA15z83zW2fhOkTH7J` — [2026 CZ Editorials](https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS)
URL format: `?node-id=[NODE_ID_HYPHENATED]` (hyphens, e.g. `789-178`)

**Do not default to A. Multi-Hero** — it is for a narrow use case (MTO furniture, artisan story, product deep-dive with craft narrative).

#### Template Selection Guidance

| Content type | Template |
|---|---|
| Sale launch / multi-category sale | H. Shop by Category |
| Sale reminder / last chance | H. Shop by Category or J. Hero Only |
| Single-product feature or materiality story | B. Product Feature Full Bleed |
| Multi-product guide, spa/bath/lifestyle edit | M. General Edit |
| Single product deep-dive with craft narrative | A. Multi-Hero |
| Color/mood-driven editorial | E. Color Edit |
| Styled room + shoppable grid | D. Get the Look |
| Back in stock | K. Back in Stock |
| Archive/clearance sale | F. Archive Sale |
| Rugs focus | I. Rugs |
| Room-by-room browse | G. Furniture by Room |
| Simple announcement / one hero image | J. Hero Only |
| Artisan story, maker spotlight | O. Meet the Makers |

#### Template Catalog

| Letter | Template | Node ID | Use Cases |
|---|---|---|---|
| A | Multi-Hero | 789:178 | MTO furniture, specific product feature, product launch, artisan story |
| B | Product Feature Full Bleed | 832:988 | Sale last chance/reminder, gift guides, single strong product feature |
| C | Destination | 789:240 | Destination editorial, travel & culture storytelling |
| D | Get the Look | 789:412 | Shop the look, styled room, bedding layers, pillow pairings, UGC, rugs |
| E | Color Edit | 789:445 | Color palette editorial, seasonal color story |
| F | Archive Sale | 789:527 | Archive sale, clearance, end-of-season |
| G | Furniture by Room | 789:579 | Furniture by room, shop by room, UGC, MTO furniture |
| H | Shop by Category | 811:737 | Sale launch, early access, reminder, last chance, bedding sale |
| I | Rugs | 811:800 | Rugs feature or rug sale |
| J | Hero Only | 824:975 | Spring preview, collection launch, specific product, Meadow Press |
| K | Back in Stock | 876:1171 | Back in stock announcement |
| L | Monthly Edit | 1363:434 | Monthly edit, trend forecast, newsletter, seasonal recap |
| M | General Edit | 1382:566 | Spa Edit, bedding guide, bath essentials, shop by category |
| N | UGC | 1672:446 | UGC, community showcase, customer-styled photos |
| O | Meet the Makers | 1735:760 | Artisan story, maker spotlight, destination with craft narrative |

Body copy fields per template are encoded in `CZ_FIGMA_TEMPLATES` in `scripts/create_calendar_tasks.py` and generated automatically by `generate_cz_email_brief()`.

### CZ Email Slice Structure (effective 2026-06-05)

> **Source of truth:** the auto-builder reads `CZ_FIGMA_TEMPLATES` in `scripts/create_calendar_tasks.py`, which was reconciled to the per-template "confirmed" structures below on 2026-07-20 (logos merged, counts aligned). A read-only mechanical mirror is generated into [docs/figma-templates.md → Auto-Briefed Slice Structures → The Citizenry (CZ)](docs/figma-templates.md) by `scripts/generate_figma_templates_doc.py`. The per-template sections here remain the home for the with-/without-sale-banner variants and historical caveats; keep the dict and these sections in sync.

For all CZ designed email tasks with send date **2026-06-05 and after**, apply these slice consolidation rules when writing the Body Copy section of the Asana brief:

1. **Logo bar + Hero always merge into one slice.** No separate "Logo link:" or "Hero link:" — just a single `Link:` at the bottom.
2. **Additional adjacent slices merge into that same slice if they share the same destination link.** Only slices with a *different* link (e.g., a sale banner pointing to the homepage) stay separate.

Do NOT apply retroactively to tasks before 6/5.

#### Link Farm / Kicker Rules (effective 2026-06-09)

- **No link farm kickers** — the text link farm is permanently in the email footer; do not specify it as a kicker module in any template.
- **Sale emails: Sale link farm header** — for emails sent during an active sale, the last delivered slice is a "Sale link farm header" [IMAGE], provided by the designer. It sits just above the footer and contains the sale name + discount (e.g., "Memorial Day Sale / 25% OFF SITEWIDE"), linking to the homepage. The auto-builder populates this from sale_schedules.
- **Optional kickers** — content kickers (YMAL, swatches, Fair Trade Guaranteed, etc.) can still appear above the sale link farm header when appropriate and email length warrants it.

Do NOT apply retroactively to tasks before 6/9.

#### Template A (Multi-Hero) — confirmed

Logo bar + Hero + Sections 1–3 all share the main LP → one combined slice.

**With sale banner (3 slices to deliver, 3 entries):**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo, hero, and sections
  - Visual / HED / Hero CTA
  - Section 1 Visual / Section 1 DEK
  - Section 2 Visual / Section 2 DEK
  - Section 3 Visual / Section 3 DEK / Section 3 CTA *(if present)*
  - Link: [main LP]
- Slice 3 — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

**Without sale banner (1 slice to deliver, 1 entry):**
- Slice 1 — Logo, hero, and sections (same fields as above)

#### Template B (Product Feature Full Bleed) — confirmed

Logo bar, optional sale terms bar, eyebrow, and HED are all in Slice 1. Slices 2–5 each link independently to their category LP. Kicker defaults to Archive Sale block but rotates per kicker rules. (Confirmed against the live Figma frame 2026-08-01 — the "Sale terms bar" field was documented here but missing from `CZ_FIGMA_TEMPLATES["B"]`'s actual field list in code; added to match.)

**Without sale banner (6–7 entries):**
- Slice 1 — Logo bar, eyebrow, and HED · Sale terms bar (optional) / Eyebrow / HED / Visual (full-bleed background) / Link: [hero/sale LP]
- Slice 2 — Full-width image · CTA: [Category] → / Link: [category LP]
- Slice 3 — 50/50 left · CTA: [Category] → / Link: [category LP]
- Slice 4 — 50/50 right · CTA: [Category] → / Link: [category LP]
- Slice 5 — Full-width image · CTA: [Category] → / Link: [category LP]
- Slice 6 — CTA over background image · CTA: [e.g. "Shop Up to 25% Off"] / Link: [hero/sale LP]
- *(optional)* Slice 7 — Kicker [content block - no slice needed] (Archive Sale by default)

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar, eyebrow, and HED · (same fields as above) / Link: [hero/sale LP]
- Slices 3–6 — Full-width and 50/50 category images (each with their own link)
- Slice 7 — CTA over background image · Link: [hero/sale LP]
- *(optional)* Slice 8 — Kicker [content block - no slice needed]
- Slice 8 (or 9) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template C (Destination) — confirmed

Logo bar + hero merge into one slice using the destination capsule LP. The "Meet Us in [Destination]" section and the dark full-bleed bottom banner ("The [Destination] Capsule >") are delivered together as one asset (Slice 2).

**Without sale banner (2 entries):**
- Slice 1 — Logo bar and hero · Eyebrow / HED: "[Destination], [Country]" / Visual / CTA: "Explore the Capsule" / Link: [destination capsule LP]
- Slice 2 — Meet Us in [Destination] · HED / Collage / DEK / CTA 1: "Explore the Capsule" / CTA 2: "The [Destination] Capsule >" / Link: [destination capsule LP]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · Link: [destination capsule LP]
- Slice 3 — Meet Us in [Destination] · Link: [destination capsule LP]
- *(optional)* Slice 4 — Kicker [content block - no slice needed]
- Slice 4 (or 5) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template D (Get the Look) — confirmed

Logo bar + Hero + Body copy all share the main LP → one combined slice. Product 50/50 slices each link independently and stay separate.

**With sale banner (7 delivered slices, sale banner + 6 content slices + optional kicker + sale link farm header):**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo, hero, and body copy · Visual / HED / Hero CTA / DEK / Link: [hero LP]
- Slices 3–6 — Product Image 1–4 (50/50 left/right alternating)
- Slice 7 — CTA button
- *(optional)* Slice 8 — Kicker [content block - no slice needed]
- Slice 8 (or 9) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

**Without sale banner (6 delivered slices):**
- Slice 1 — Logo, hero, and body copy
- Slices 2–5 — Product Images
- Slice 6 — CTA button
- *(optional)* Slice 7 — Kicker [content block - no slice needed]

#### Template E (Color Edit) — confirmed

Logo bar + hero merge into one slice. Both slices link to the same color edit LP. Kicker follows standard kicker rules — not tied to any specific kicker in the Figma.

**Without sale banner (2–3 entries):**
- Slice 1 — Logo bar and hero · Eyebrow / HED: [Color name] / Visual / CTA: "Shop the Edit" / Link: [color edit LP]
- Slice 2 — Color swatches + mosaic · Color palette swatches row / Mosaic collage / CTA: "Shop the Edit" / Link: [color edit LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · Link: [color edit LP]
- Slice 3 — Color swatches + mosaic · Link: [color edit LP]
- *(optional)* Slice 4 — Kicker [content block - no slice needed]
- Slice 4 (or 5) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template F (Archive Sale) — confirmed

Logo bar + Hero + Body copy + Photo grid + CTA button all share the archive sale LP → one combined slice. **Corrected 2026-08-01:** the code previously special-cased F to skip the code-injected Slice 1 sale banner entirely, on the assumption its own Figma frame baked one in — confirmed false via screenshot + metadata of node `789:527` (no banner element anywhere, hidden or otherwise; goes straight from the logo into the Archive Sale hero). `CZ_FIGMA_TEMPLATES["F"]["slices"]` also used to list "Sale banner" as its own first base slice, which told the AI to write one itself — removed, since the banner is now purely code-injected for F exactly like every other template. This prose was already correct; only the code and its own catalog entry had drifted from it.

**With sale banner (3 slices to deliver, 4 entries):**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo, hero, body copy, photo grid, and CTA
  - Logo background / Visual / Eyebrow / HED / Hero CTA / DEK / Body CTA / Photo grid / CTA button
  - Link: [archive sale LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]
- Slice 3 (or 4) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template G (Furniture by Room) — confirmed

Logo bar + hero + intro copy row merge into one slice. The 4 category images each link independently. Used for Furniture by Room, UGC, Rugs, and MTO Furniture — Slice 1 HED is whatever the email's headline is, not fixed.

**Without sale banner (6 entries):**
- Slice 1 — Logo bar, hero, and intro copy · HED / CTA on hero / DEK (intro copy row) / Link: [hero LP]
- Slice 2 — [Category 1] · HED / Body / CTA: "Shop Now >" / Link: [category 1 LP]
- Slice 3 — [Category 2] · HED / Body / CTA: "Shop Now >" / Link: [category 2 LP]
- Slice 4 — [Category 3] · HED / Body / CTA: "Shop Now >" / Link: [category 3 LP]
- Slice 5 — [Category 4] · HED / Body / CTA: "Shop Now >" / Link: [category 4 LP]
- Slice 6 — CTA button · Link: [hero LP]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar, hero, and intro copy · Link: [hero LP]
- Slices 3–6 — [Category 1–4] (each with HED / Body / CTA / Link)
- Slice 7 — CTA button · Link: [hero LP]
- *(optional)* Slice 8 — Kicker [content block - no slice needed]
- Slice 8 (or 9) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template H (Shop by Category) — confirmed

Logo bar + Hero merge; Category Blocks each link independently and stay separate. All Category Blocks are full-width — there are no 50/50 modules in this template.

**With sale banner (N+2 entries where N = number of category blocks):**
- Slice 1 — Sale banner · Link: homepage *(if present)*
- Slice 2 — Logo and hero · Visual / HED / CTA / Link: [hero LP]
- Slices 3–N+1 — Category Block 1–N (each with Eyebrow / HED / Link)
- Slice N+2 — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

**Without sale banner:** Slice 1 = Logo and hero; category blocks follow.

#### Template I (Rugs) — confirmed

All content (logo bar + hero + product grid) merges into one slice, linking to the rugs LP. Note: 6/16 Washable Rugs was built before this rule was established — do not retroactively change it.

**Without sale banner (1–2 entries):**
- Slice 1 — Logo bar, hero, and all content · Link: [rugs LP]
- *(optional)* Slice 2 — Kicker [content block - no slice needed]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar, hero, and all content · Link: [rugs LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]
- Slice 3 (or 4) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template K (Back in Stock) — confirmed

**Single slice only — logo + hero + HED + DEK + CTA, no separate product image slices.**
The Figma reference (node `876:1171`) is one hero graphic (logo, "Back In Stock" HED,
DEK, one CTA button, linking to the BIS collection page) — restocked products aren't
individually featured in the email; the hero CTA links straight to the collection
showing all of them. Corrected 2026-08-01: `CZ_FIGMA_TEMPLATES["K"]` previously also
listed "Product Image 1/2/3" slices that don't exist in the Figma frame at all — a
catalog-vs-Figma drift that went undetected because nothing validated the catalog
against the live design, only the AI's output against the (wrong) catalog. Confirmed via
screenshot before correcting. Note: 6/23 Back in Stock was already in progress before
this correction — do not retroactively change it.

**Without sale banner:**
- Slice 1 — Logo bar and hero · HED / DEK / Hero CTA / Link: [hero LP / BIS LP]
- *(optional)* Slice 2 — Kicker [content block - no slice needed] (cycled — YMAL / Archive Sale / Fair Trade Guaranteed)

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · HED / DEK / Hero CTA / Link: [hero LP / BIS LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]
- Slice 3 (or 4) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template L (Monthly Edit) — confirmed

Logo bar + hero merge into one slice. Slices 2–4 each link independently to their own LP. Kicker options for this template: Archive Sale block or Fair Trade Guaranteed block.

**Without sale banner (4–5 entries):**
- Slice 1 — Logo bar and hero · Eyebrow / HED / DEK / CTA (ghost button) / Link: [hero LP]
- Slice 2 — [Section name] · Eyebrow / HED / Collage (2×2 image grid) / Body / CTA / Link: [section LP]
- Slice 3 — [Section name] · Eyebrow / HED / Image / Body / CTA / Link: [section LP]
- Slice 4 — [Section name] · Eyebrow / HED / Image / Body / CTA / Link: [section LP]
- *(optional)* Slice 5 — Kicker [content block - no slice needed] (Archive Sale or Fair Trade Guaranteed)

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · Link: [hero LP]
- Slice 3 — [Section name] · Collage / Link: [section LP]
- Slice 4 — [Section name] · Image / Link: [section LP]
- Slice 5 — [Section name] · Image / Link: [section LP]
- *(optional)* Slice 6 — Kicker [content block - no slice needed]
- Slice 6 (or 7) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template J (Hero Only) — confirmed

Logo bar + hero merge into one slice using the hero LP link. Note: 6/15, 6/18, 6/21, and 6/27 sends were already in progress before this rule was established — do not retroactively change them.

**Without sale banner (1–2 entries):**
- Slice 1 — Logo bar and hero · Link: [hero LP]
- *(optional)* Slice 2 — Kicker [content block - no slice needed]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · Link: [hero LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]
- Slice 3 (or 4) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template M (General Edit) — confirmed

Logo bar + hero merge into one slice using the hero link. Category blocks each link independently.

**Without sale banner:**
- Slice 1 — Logo bar and hero · Visual / Eyebrow / HED / DEK / CTA / Link: [hero LP]
- Slices 2–N — Category blocks (each with their own link)
- *(optional)* Slice N+1 — Kicker [content block - no slice needed]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero · Visual / Eyebrow / HED / DEK / CTA / Link: [hero LP]
- Slices 3–N+1 — Category blocks (each with their own link)
- *(optional)* Slice N+2 — Kicker [content block - no slice needed]
- Slice N+2 (or N+3) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template N (UGC) — confirmed

Logo bar is part of Slice 1 (overlaid on the first UGC photo). Always 3 UGC photos total. Slices 2–3 each link to their featured product. Slices 1 and 4 link to the hero LP.

**Without sale banner (4 entries):**
- Slice 1 — Logo bar and hero (UGC photo 1) · HED / DEK / CTA: "Shop Now" (ghost button) / Product tag: [PRODUCT NAME] / Handle: @[instagram_handle] / Link: [hero LP]
- Slice 2 — UGC photo 2 · Product tag: [PRODUCT NAME] / Handle: @[instagram_handle] / Link: [product LP]
- Slice 3 — UGC photo 3 · Product tag: [PRODUCT NAME] / Handle: @[instagram_handle] / Link: [product LP]
- Slice 4 — CTA button · CTA: "Shop Now" / Link: [hero LP]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar and hero (UGC photo 1) · HED / DEK / CTA / Product tag / Handle / Link: [hero LP]
- Slice 3 — UGC photo 2 · Product tag / Handle / Link: [product LP]
- Slice 4 — UGC photo 3 · Product tag / Handle / Link: [product LP]
- Slice 5 — CTA button · Link: [hero LP]
- *(optional)* Slice 6 — Kicker [content block - no slice needed]
- Slice 6 (or 7) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

#### Template O (Meet the Makers) — confirmed

Entire email is one slice — logo is embedded in the top of the slice, no separate logo bar.

**Without sale banner (1 entry):**
- Slice 1 — Logo bar, hero, and maker story · Eyebrow: "Meet the Makers" / HED: [Artisan / Studio Name] / Visual: [Maker portrait] / DEK: [Artisan story copy] / CTA: "Meet the Maker >" / Link: [artisan LP]

**With sale banner:**
- Slice 1 — Sale banner · Link: homepage
- Slice 2 — Logo bar, hero, and maker story · (same fields as above) / Link: [artisan LP]
- *(optional)* Slice 3 — Kicker [content block - no slice needed]
- Slice 3 (or 4) — Sale link farm header [IMAGE] · [sale name / discount] · Link: homepage

---

## Link Sourcing Rule (all brands, all tasks)

**Never guess or invent landing page URLs.** This applies everywhere — briefs, PT emails, designed emails, SMS, QA. Guessed Shopify URL patterns are frequently wrong (e.g., CZ Rugs is `/collections/shop-all-rugs-1`, not `/collections/rugs`).

**Priority order:**
1. **Asana brief** — check the LP field and any hyperlinks in the brief notes first
2. **Brand link-catalog yaml, if one exists** — CZ (`data/cz_links.yaml`), BUR (`data/bur_links.yaml`), STF (`data/stf_links.yaml`), TI (`data/ti_links.yaml`) each have a maintained, HTTP-verified catalog that's also the live source for SMS keyword resolution (see each brand's Link Map section below) — check this before falling back to grepping campaign HTML.
3. **Knowledgebase campaign HTMLs** — every real URL ever used by a brand lives in `campaigns/html/*.html`. Query:
   ```bash
   grep -roh 'https://www[.]the-citizenry[.]com/collections/[^"&[:space:]>]*' campaigns/html/ | \
     sed 's|.*\.com||' | sort | uniq -c | sort -rn | head -30
   ```
   Swap in the brand's domain (`burrow\.com`, `stfrank\.com`, etc.).
4. **CLAUDE.md explicit URLs** — e.g., `CZ Back in Stock LP`, `STF Swatches LP`, `CZ Meadow Press Collection`

The TI-specific version of this rule ("Links must come from existing links found in knowledgebase campaign files") is a special case of the same principle.

---

## Designed Email QA — Links and Alt Text from Figma

For designed emails that are already coded, or to QA an auto-built email, use the Figma reference to read each slice and map it to the correct link and alt text:

1. **Get the Figma node** from the task's "Ref Image/Slide deck link" field (or the Figma field in the brief)
2. **Screenshot it** using `mcp__figma__get_screenshot` — extract `fileKey` and `nodeId` from the URL:
   - Example URL: `https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/...?node-id=3127-2540`
   - `fileKey` = `K043FA15z83zW2fhOkTH7J`, `nodeId` = `3127:2540`
   - Use `maxDimension: 2000` for full-height emails so all slices are readable
3. **Read the text** on each slice — category labels, CTAs, headline copy, discount callouts
4. **Match each slice to a collection URL** using the knowledgebase (Link Sourcing Rule above)
5. **Write alt text** from the text visible in the image (e.g., `Shop Rugs`, `Memorial Day Sale — Final Hours — 25% off sitewide`)

**When to use this method:**
- **Auto-built emails (send date 2026-05-30 and after):** the auto-builder populates links and alt text from the Asana brief. Use this Figma method as a **QA check** — verify the built email matches the design intent.
- **Manually built / older emails / non-auto-builder brands:** use this as the primary method to determine links and alt text.

---

## Common Tasks

**`uv` path:** `uv` is symlinked to `/usr/local/bin/uv` — use `uv run python` directly (no full path needed).

### Query campaigns
Load `campaigns/*.yaml` with PyYAML. Filter on `brand`, `channel`, `performance_summary.click_rate`, etc.

For row-level event data (individual sends, opens, clicks, bounces, unsubscribes), use the **Braze Raw Events Datashare in Snowflake** — see the "Braze Raw Events Datashare (Snowflake)" section below. BUR, HAV, and CZ are in the primary datashare; ID and STF are in a separate TIER3 datashare. TI is not available.

### Import new campaigns
```bash
# Import all brands
uv run python scripts/import_braze.py

# Single brand, skip existing
uv run python scripts/import_braze.py --brand HAV --skip-existing

# Flatten canvas steps into individual records
uv run python scripts/flatten_canvases.py --brand HAV
```

## Sale Schedule Integration

**Source of truth for upcoming promo terms, dates, and discounts:** the [Asana Promo Tracking Board](https://app.asana.com/1/5257710284167/project/1213996005172086/list/1213996041392096). Each task has the discount percent and promo terms in its description, and a Brand field indicating which brand the promo applies to.

Sale/promo schedules can be imported and used to analyze campaign performance during sale periods vs non-sale periods.

### Sync Sale Schedules

Sale schedules are stored in `data/sale_schedules.yaml` and sync automatically daily from the [Asana Promo Tracking Board](https://app.asana.com/1/5257710284167/project/1213996005172086/list/1213996041392096) via GitLab CI. To sync manually:

```bash
uv run python scripts/import_sale_schedules.py --source asana

# Preview without writing
uv run python scripts/import_sale_schedules.py --source asana --dry-run
```

**How sync works:**
- Reads `ASANA_ACCESS_TOKEN` from `.env`
- Fetches all tasks from the Asana Promo Tracking project (GID `1213996005172086`)
- Parses task name, notes (`PROMO - B2C:` line for discount, `SALE NAME:` line for name), start/due dates, and Brand custom field
- Merges with existing historical data — historical entries are preserved, current/future entries are replaced with fresh data

**Havenly DPS vs Marketplace:** The Asana board has separate tasks for Havenly DPS and Havenly Marketplace with different sale dates and offers. The sync preserves this distinction via the `havenly_audience` field on sale records:
- **Havenly DPS** → `brand: HAV`, `havenly_audience: PC` (pre-converted)
- **Havenly Marketplace** → `brand: HAV`, `havenly_audience: CONV` (converted)

The `sale_matcher` automatically extracts PC/CONV from campaign names (e.g., `_PC_` or `_CONV_` in `P_EM_2026_02_10_HAV_D_PC_...`) and matches only the appropriate promo. Sales without `havenly_audience` match any HAV campaign (backward-compatible).

**CI/CD variables required** (GitLab Settings > CI/CD > Variables):
- `ASANA_ACCESS_TOKEN` (masked)
- `CI_PUSH_TOKEN` — a project or group access token with `write_repository` scope

### Using Sale Schedules in Analysis

Sale schedules are integrated into `scripts/analysis/analyze_engagement.py`, `analyze_send_times.py`, and `analyze_sale_performance.py`. In custom scripts, use `scripts/utils/sale_matcher.py`: `load_sale_schedules()`, `tag_campaigns_with_sales()`, `filter_campaigns_by_sale(during_sale=True/False)`, `get_sale_context()`. Tagged campaigns include a `_sale_context` key.

### Sale Performance Analysis

Generate dedicated sale performance reports:

```bash
uv run python scripts/analysis/analyze_sale_performance.py
```

Outputs: `reports/sale-performance-analysis.md` with:
- Overall sale vs non-sale performance comparison
- Performance by brand during sales
- Performance by sale type
- Timing analysis (days from sale start)
- Sale overlap analysis (single vs multiple concurrent sales)

## Lifecycle Guidelines

Brand-level send cadence, segments, and send times are in `data/lifecycle_guidelines.yaml`. Key cadences: HAV 4–5/wk, ID/BUR/CZ 6–9/wk, TI 3–6/wk, STF 3 email + 1–2 SMS/wk, Trade 1–3/wk. HAV DPS (Pre-Conv) and MP (Converted) are separate audiences with separate weekly counts.

See **Copy Standards** section below for per-brand SL/PH lengths, emoji policy, and SMS rules.

## Lifecycle Canvas FigJam Boards

Full setup guide: `docs/lifecycle-figjam-board-setup.md`. Existing boards: [Burrow](https://www.figma.com/board/VxjmwZuwCf3bsWfMGLOlOm) · [Interior Define](https://www.figma.com/board/IHASW2pUj5Zfy4ZKJlTyDR) · [Havenly](https://www.figma.com/board/UHfbjMJfByUpWQAXEw71Qu/HAV-%E2%80%94-Lifecycle-Canvas-Map) · [The Citizenry](https://www.figma.com/board/yhfQv32GCWNOfwEerlMORd/The-Citizenry-%E2%80%94-Lifecycle-Canvas-Map) · [St. Frank](https://www.figma.com/board/sGQ2oaV3pGupwGr5u8lwaJ/STF-%E2%80%94-Lifecycle-Canvas-Map) · [The Inside](https://www.figma.com/board/0GfQj3VJtQCSEslCo1SPjm/The-Inside-%E2%80%94-Lifecycle-Canvas-Map) · [The Expert](https://www.figma.com/board/dtgM4oqjnYueUniBESjCHJ/The-Expert-%E2%80%94-Lifecycle-Canvas-Map)

### Weekly stats refresh (rolling 12-week averages) — BUR + ID

The `lifecycle-stats::{brand}::{canvas-slug}` TEXT nodes on the Burrow and Interior Define boards show rolling 12-week weekly averages. They're refreshed automatically by the `update-lifecycle-figjam` GitLab job (Mondays 9am ET), which calls the `claude` CLI via an **Anthropic Console API key** — when that prepaid balance is empty the job fails (`Credit balance is too low`) and the boards must be refreshed manually through a Claude session.

**To refresh manually** (trigger: "update the lifecycle figjam stats"): follow **[`docs/lifecycle-figjam-stats-update.md`](docs/lifecycle-figjam-stats-update.md)** — run `uv run python scripts/update_lifecycle_stats.py` to compute the JSON payloads, then apply each `lifecycle-stats::…` node by name via the Figma MCP (load `figma-use` skill + `Inter/Medium` font first). The script already encodes every edge case: SMS sub-sections for combined email+SMS canvases (with `—` where the two BUR browse canvases share SMS campaign names), and `Swatch Orders/wk` for ID swatch canvases (GA4 `generate_lead_swatch`, EMAIL last-click). Do **not** hand-write numbers or skip the script.

### FigJam ↔ Dashboard sync rule

**The FigJam boards and the dashboard must always stay in sync.** Any change made to one must also be applied to the other in the same session — including timing updates, adding or removing a step, subject line edits, and structural changes. Never close out a task after updating only one.

### Dashboard screenshot update rule

**Always restart the dashboard immediately after writing any new file to `campaigns/screenshots/rendered/`.** Do not report the task as complete until the restart is done.

`load_thumb` in `scripts/canvas_map_dashboard.py` is decorated with `@st.cache_data` (no TTL). Once a thumbnail is loaded, the running process never re-reads it from disk — the old image stays cached for the lifetime of the process. Restart command:

```bash
bash scripts/stop_dashboards.sh && bash scripts/start_dashboards.sh
```

### Multi-channel rule (all brands, all flows)

Every flow on the FigJam board must show **both email and SMS touchpoints** — not email only. Many canvases have SMS steps embedded alongside emails that are not captured in the YAML knowledgebase (which only imports email steps).

**Process for each canvas:**
1. Call `braze_get_canvas` to inspect the full canvas structure and identify every message step by channel
2. For each SMS step, create an SMS-style card: dark header bar (gold timing text + white label), light purple body rectangle with the actual SMS copy from the canvas API response
3. Insert SMS cards at their correct sequence position; shift any existing email cards right; update all T-number labels and the step count (e.g. "4 emails" → "4 emails + 1 SMS")

### Timing rule — always look up from the datashare

Never guess or invent delay timing. Always trace a real user's journey from the Braze raw events datashare:

1. Find a user who received a late-stage step using `CANVAS_NAME ILIKE '%Canvas Name%'` (not `CANVAS_ID` — the UUID in YAMLs does not match the raw events views)
2. Pull all email + SMS sends for that user from the same canvas and compute delays:
   ```sql
   SELECT channel, CANVAS_STEP_NAME, TO_TIMESTAMP(TIME) AS sent_at,
     DATEDIFF('minute', LAG(TO_TIMESTAMP(TIME)) OVER (ORDER BY TIME), TO_TIMESTAMP(TIME)) AS minutes_since_prev
   FROM (
     SELECT 'email' AS channel, CANVAS_STEP_NAME, TIME FROM USERS_MESSAGES_EMAIL_SEND_SHARED WHERE USER_ID = :user
     UNION ALL
     SELECT 'sms', CANVAS_STEP_NAME, TIME FROM USERS_MESSAGES_SMS_SEND_SHARED WHERE USER_ID = :user
   )
   ORDER BY TIME ASC
   ```
3. Convert cumulative minutes to days/hours from T1 for the label (e.g. `T2 · Day 0 · 2 hrs`, `T3 · Day 2`)

Datashare by brand: BUR/HAV/CZ → `DATALAKE_SHARING`; ID/STF → `DATALAKE_SHARING_TIERED` (TIER3 database).

### Gap-preserving layout rule (all boards, all brands)

Whenever a screenshot frame grows taller — by adding a card, resizing a placeholder, embedding a new screenshot, or adding a content block — **do not blindly shift subsequent rows by the height delta**. Instead:

1. After resizing, measure the actual visual gap (screenshot bottom → next row title y).
2. Compare to the board's target gap (HAV: 76px · CZ: 126px · BUR: ~96px · ID: 72–117px).
3. Shift all subsequent rows by `current_gap − target_gap` to restore the correct spacing.

Per-board target gaps, node IDs, and measurement scripts are in `memory/feedback_figjam_gap_preservation.md`. For **new boards**, run the measurement script after adding the first two rows to establish the target gap before making further changes.

### Title line-break rule (all boards, all brands)

Card/step title text sits inside a fixed-width label bar (~260px on most boards). Before finalizing any title — including auto-generated ones (e.g. cross-brand or cross-sell step names) — check whether its rendered width fits inside the bar. If it doesn't, insert a manual line break at a natural point (typically right before or after a `·` separator) rather than letting the text overflow past the box edge. Confirmed needed on the ID board's "Sofa/Sectional Post Purchase · 8 weeks post order" title (2026-07-26), which overflowed ~30px past its 260px card until broken into two lines.

## HAV Email Content Ideas

### Evergreen Interactive/Editorial Formats
- **This or That** — Collection of photos; subscribers click to vote on which they prefer. High-engagement interactive format.
- **Before and After** — Room transformation using Havenly. Works for DPS (designer-led) and MP.
- **Why Havenly** — Brand value prop email. Good for DPS (why work with a designer) or MP (why shop Havenly).

### During-Sale Fillers
- **Plain-Text email** — Breaks up designed content during heavy sale periods. Use a PT task (Type = Plain-Text) with a simple sale message. Good when volume is needed but the designed template cadence needs a rest.

### Recurring Major-Sale Send — Items In Your Design Are On Sale (MP only)
- **"Items In Your Design Are On Sale"** — MP/CONV-only send that reminds recipients the products already sitting in their saved design are now on sale (cart-callout angle, e.g. `P_EM_2026_07_04_HAV_CONV_D_Items_In_Your_Design_Are_On_Sale`). This should be included in the plan for every **major** HAV sale window (flagship multi-week events — Summer Sale, Memorial Day Event, Fourth of July Event, Labor Day Event, Black Friday Event, End of Year Sale, etc.) — not short Flash Sales, EA-only windows, or most Extensions, which historically never got this send. Typically lands mid-to-late in the sale window.
- Confirmed gap (2026-08-26): this ran regularly through 2026-07-04, then silently stopped for three subsequent major sale windows (Summer Sale, Flash Sale, Labor Day Event) with nothing catching it. `validate_hav_items_in_design_coverage()` in `scripts/create_calendar_tasks.py` is the automated safety net for this — see the weekend-coverage-check step in the Calendar Task Creation Workflow below for how it's wired in.

## Copy Standards

### Email Subject Line & Preheader (all brands)

| Format | Length | Case | End punctuation |
|--------|--------|------|----------------|
| Designed SL | <40 chars | Sentence case | No period |
| Designed PH | <90 chars | Sentence case | With punctuation |
| Plain-Text SL | <40 chars | Sentence case | No punctuation |
| Plain-Text PH | N/A — omit | — | — |
| Sale names | Title case (all brands) | — | — |

### Urgency in SL/PH — no literal dates or countdowns (all brands)

Never mention sale end dates, day counts, or expiry callouts in SL or PH copy. Urgency should come from tone and word choice, not specific dates or timers.

- **Wrong:** "Up to 20% off through July 13. Shop before it ends." / "3 days left to save up to 20%"
- **Right:** "The Fourth of July Event ends soon" / "LAST CHANCE: 50% off design" / "Bold living just got 20% off"

This applies to all brands, all channels (email, SMS, push).

### Banned words — no "genuine" / "genuinely" (all brands, all channels)

Never use "genuine" or "genuinely" (any form) in copy — it reads as an AI-writing tell. This applies to all brands, all channels (email, SMS, push), subject lines, preheaders, and body copy.

- **Wrong:** "the pieces that are left are genuinely some of our favorites"
- **Right:** "the pieces that are left are some of our favorites" (just cut it, or replace with a more specific claim)

### "Introducing" a collection/product line is launch-only (all brands, all templates)

When "Introducing" (or equivalent brand-new-debut framing, e.g. "New Collection," "Just Launched") is applied to a **named collection or product line** — e.g. an Eyebrow/HED on a collection-spotlight template — only use it when that collection/product line is an **actual new launch**, confirmed by one of:
- The Master Marketing Calendar Google Sheet row explicitly flags it as a launch (new collection debut, first send for a newly released collection/product), or
- The Claude session briefing the task explicitly states it's a launch send.

A spotlight, category feature, or reminder send on an **existing/evergreen collection** is not a launch — use a descriptive, content-specific label instead (e.g. the collection name, a benefit callout, a section label).

- **Wrong:** ID Category/Collection spotlight on an established collection (e.g. Tatum) with `Eyebrow: INTRODUCING` while the Creative Direction itself says "non-sale, evergreen collection content"
- **Right:** `Eyebrow: THE TATUM COLLECTION` or another descriptive label; reserve "Introducing" for a brief that actually says this collection/product is new

**Not covered by this rule — "Introducing" a themed edit, color story, or sale/event is fine**, since that instance of the content genuinely is new even when the format/series recurs (e.g. `SL: Introducing: Harvest Hues` for a new seasonal color edit, or `SL: Introducing: the serene retreat` for a new styled-room edit). The distinction is collection/product line (must be a real new launch) vs. a themed content instance within a recurring editorial series (always fine to call new, since each theme/edit is itself new).

Confirmed 2026-08-06 after [Kenzie flagged](https://app.asana.com/1/5257710284167/project/1207353785125835/task/1216322104720564) that ID category-spotlight sends were repeatedly getting an "Introducing" eyebrow despite not being new-collection sends. `docs/figma-templates.md`'s ID Template C field reference (`Eyebrow ("INTRODUCING")`) is an illustrative example for genuine launches, not a fixed default — check whether the send is actually a launch before using it, for every brand/template, not just ID.

**Same rule applies to individual products, not just named collections — and to any new-arrival phrasing, not just the literal word "Introducing."** A roundup/spotlight brief must not claim individual featured products are new (e.g. "Just dropped," "New [Category], Now on Sale," "Fresh pieces just landed," "New tables, new chairs") unless the brief has explicit confirmation that those specific products are a new launch. Without that confirmation, default to a plain roundup/collection framing (e.g. task name "[Category] Roundup," hero copy describing the products by benefit/quality rather than novelty).

- **Wrong:** BUR "New in Dining — Roundup" task briefed with SL "Just dropped: dining that does it all," hero HED "New Dining, Now on Sale," DEK "Fresh dining pieces just landed" — for Serif Extendable Dining Table, Alto Dining Chairs, Haiku Counter Stools, and Dram Bar Cart, all of which launched the prior year
- **Right:** Task renamed "Dining Roundup"; SL "Dining that does it all, up to 35% off"; hero HED "Dining Essentials, Now on Sale"; DEK "Dining pieces built to last, and the Labor Day Event makes them..."

Confirmed 2026-08-14 on [Dining Roundup](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1217034167476255) (BUR) after [Gillian flagged](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1217034167476255?focus=true) that the featured products "launched last year" despite the brief's new-arrival framing. When auto-briefing a roundup/multi-product spotlight with no signal that the products are new, do not invent that signal — write it as a roundup by default.

### Emoji Policy by Brand

| Brand | Rule |
|-------|------|
| HAV (PC + Conv) | Allowed strategically at end of SL or PH — limit 1-2/month |
| ID | Allowed strategically at end of SL — limit 1-2/month |
| TI | Allowed strategically at end of SL — limit 1-4/month |
| BUR, CZ, STF, Trade | No emojis |

### SMS Standards

All SMS: <130 characters. Include brand name at the beginning **OR** incorporated into body copy — not both.

| Brand | Prefix |
|-------|--------|
| ID | "Interior Define:" |
| BUR | "Burrow:" |
| CZ | "The Citizenry:" |
| TI | "The Inside:" |
| STF | "St. Frank:" |

### Push Standards (HAV only)
- Title: <30–40 characters
- Body copy: <150–170 characters

### Trade Program
- Must include brand name in SL or PH
- No SMS channel

### Content Planning Rules
- **No sale teasers** — do not suggest "starts tomorrow / something special is coming" style sends
- **No unconfirmed new arrivals** — only schedule New Arrivals content if confirmed in the master marketing calendar or explicitly specified

## Analysis Continuation

When continuing analysis work:

1. **Data is in YAMLs** — Query `campaigns/*.yaml` for any analysis
2. **Screenshots exist** — `campaigns/screenshots/` (12GB, gitignored, regenerate with `backfill_html_screenshots.py`)
3. **Metrics use unique counts** — `open_rate` and `click_rate` are based on unique opens/clicks, not totals
4. **Channel/category fields** — Filter on `channel: email` to exclude SMS; use `category` for campaign type analysis
5. **Canvas vs batch** — `braze_type: canvas_step` for triggered, `campaign` for batch
6. **Use `send_date` as the primary analysis date** — `dates.send_date` is the canonical "when was this campaign sent?" field, parsed from the campaign name (e.g. `_2026_04_27_` → `2026-04-27`). Do not use `first_sent` or `last_sent` for this purpose: local-time sends and STO campaigns spread both values over 20–48h, and `first_sent` often lands a day before the intended send date. Fall back to parsing the date from `name` directly, then `first_sent`, only when `send_date` is absent. The `schedule_type` field (top-level, not under `dates`) indicates batch vs triggered vs API-triggered, but does NOT distinguish local-time from STO from fixed-UTC — Braze does not expose that granularity for already-sent campaigns.
7. **Discount language detection — scan full text** — When classifying subject lines or preheaders as discount-led, scan the entire string, not just the first N characters. Emoji, mid-sentence discount mentions, and trailing "save" language are all meaningful signal.

## ID-Specific Analysis Rules

- **Always exclude Trade campaigns** — filter out any ID campaign with "TRADE" in the campaign name (case-insensitive) before computing any metrics. Trade sends go to a separate trade audience and are not representative of consumer program performance.
- **Order/revenue analysis — see [Order Data Hygiene (all brands)](#order-data-hygiene-all-brands)** for two confirmed data-quality risks that apply to ID specifically and to every other brand checked: an internal ops account (`orders@havenly.com`, `CUSTOMER_ID` 20 in `ID_WAREHOUSE`, ~1,000 orders / ~$3M trailing 6mo, sitting in `Tax Exempt` not Trade/B2B) that must be excluded explicitly, and a Braze `EXTERNAL_USER_ID` → `ID_WAREHOUSE.CUSTOMER_ID` numeric join that looks valid but silently resolves to the wrong person — join on lowercased email instead.

## Data Coverage
- **Campaigns**: ~9,200 total (4,536 Braze + ~2,200 TI Klaviyo + ~1,663 TE Klaviyo)
- **Date range**: July 2024 – present
- **Screenshots**: 3,299+ rendered (email only; TI+TE rendering in progress)
- **Asana metadata**: ~83% matched (Braze brands only)
- **Analytics**: Klaviyo campaigns have `total_sends: 0` (analytics rate-limited); run `backfill_klaviyo_analytics.py` after 20h quota reset

## Asana Integration
- **Workspace**: havenly.com (`5257710284167`)
- **Project**: Master CRM (Email & SMS) (`1207522423363072`)
- **Team**: E-Comm

**Important**: Always use a **sub-agent** (Task tool) for Asana MCP queries to avoid filling conversation context with large responses. Example:
```
Task: "Search Asana for HAV tasks due this week and summarize"
```
The agent handles MCP calls in its own context and returns only the summary.

**Date filtering**: When queries involve dates, instruct the agent to filter at the API level:
```
"Use due_on_after=2026-01-20 and due_on_before=2026-01-26 parameters
in the asana_search_tasks call to filter at the API level"
```
This reduces data transfer vs fetching all tasks and filtering locally.

## Calendar Task Creation Workflow

Pull email sends from the **Master Marketing Calendar Google Sheet** and create Asana tasks multi-homed to two projects.

**Sheet ID:** `1S3YEx-f7aOTrqZgD4VUbQ7-XKunMIyUYkWJ2d1CGR4o`

> **Do NOT use `scripts/create_calendar_tasks.py`** — it only adds to Master CRM and parses duplicate sheet sections. Use Asana MCP directly via sub-agent.

**This disallows running the script's own sheet-to-Asana driver — it does NOT mean reimplementing brief content by hand.** For **CZ, STF, TI, BUR, and HAV** (the five slice-by-slice brands), the Body Copy content must still go through that brand's template catalog and slice-format rules from `scripts/create_calendar_tasks.py` — never freehand-composed from the prose in `docs/figma-templates.md`. The HTML/CSS auto-builder (`build_cz_designed_email.py`) parses `html_notes` with regex expecting the exact `Slice N — [name]` / field-label format these functions emit, and drifted phrasing can silently break link/alt-text extraction at build time.

**Preferred method — self-generate, no API key needed:** each brand has a `build_xxx_prompt()` / `parse_xxx_response()` pair (`build_cz_prompt`/`parse_cz_response`, `build_stf_prompt`/`parse_stf_response`, `build_ti_prompt`/`parse_ti_response`, `build_bw_prompt`/`parse_bw_response`, `build_hav_prompt`/`parse_hav_response`) that split the old `generate_xxx_email_brief()` into a pure prompt-builder and a pure response-parser — neither makes an API call. **Whichever Claude Code session is doing the briefing should generate the completion itself** (following the prompt's instructions verbatim, real copy — no placeholders like "TBD"), then parse its own output with `parse_xxx_response()`. This is the standard method for Nicole, Mina, Jordan, or any future session running this workflow — not a one-off workaround. Example:
```python
import sys; sys.path.insert(0, "scripts")
from create_calendar_tasks import build_bw_prompt, parse_bw_response
prompt = build_bw_prompt({"story": "...", "date": "2026-08-20", "landing_page": "", "notes": "", "promo": ""}, during_sale=False)
# Generate the completion yourself (as the acting Claude session) following `prompt`'s
# instructions exactly, then:
brief = parse_bw_response(completion_text)
# brief["body_copy"] is the exact Slice-N text to feed into html_notes
```

**If `parse_xxx_response()` (or `build_html_notes()`, once you get to it) raises `SliceBriefValidationError`:** this means your generated body copy has a duplicate product/category slot, or a slice count that doesn't match the selected template's own structure (a merged-vs-split section, an extra/missing product slot). **Do not catch this exception, fall back to a generic version, or create/update the Asana task anyway.** Read the message — it names the exact slices involved — regenerate the completion fixing that specific issue, and re-parse. This is the enforcement mechanism for "the slice-by-slice brief must actually match the Figma template it claims to use," added 2026-08-01 after a batch of CZ tasks shipped with mismatches that only produced an easy-to-miss `[WARN]` print. See [Slice-count validation](#slice-count-validation-all-copy-first-brands-as-of-2026-08-01) below for the full mechanics.

**Fallback — `generate_xxx_email_brief()` (calls the Anthropic API directly):** still exists as a thin wrapper around the same build/parse pair, but depends on `ANTHROPIC_API_KEY` and a shared prepaid Console credit balance that periodically runs dry (same account used by the `update-lifecycle-figjam` GitLab job — see "Weekly stats refresh" below). It **fails completely silently** (returns `None`, no error surfaced) when the key is missing or the balance is empty, which is exactly what happened to a batch of ~44 BW tasks briefed 2026-07-30: the brief silently fell back to a generic placeholder ("template TBD by design", no Body Copy section) instead of surfacing the failure. Only use this fallback if there's a genuine reason not to self-generate.

### PT (Plain-Text) briefs — AI-drafted body copy (as of 2026-07-30)

PT email tasks for the five copy-first brands now get an AI-drafted **full body draft** in the brief, not just Creative Direction + SL suggestion — same self-generate pattern as the designed-email slice builders above, via `build_pt_prompt(brand, record, during_sale=False)` / `parse_pt_response(text)` in `scripts/create_calendar_tasks.py`. Unlike the slice builders, this is a single shared pair parameterized by `brand` (`"HAV"`, `"CZ"`, `"STF"`, `"BUR"`, `"TI"`) rather than 5 near-duplicate functions, since a PT prompt only needs signoff/link-catalog/sale-instruction swapped per brand, not a template catalog.

**Before generating the completion, invoke that brand's copywriter skill** (see Skills section at the top of this file) — `build_pt_prompt()` only encodes mechanics (greeting, link rules, signoff), not voice; the skill is what makes the draft sound like the brand. (All six brand copywriter skills named above were confirmed present and loading 2026-08-18, closing a gap open since 2026-07-30 when they were missing from the available-skills list. If a session ever lacks them again, fall back to the brand's documented voice notes in this file and past-campaign tone rather than skipping voice entirely.)

```python
import sys; sys.path.insert(0, "scripts")
from create_calendar_tasks import build_pt_prompt, parse_pt_response, build_html_notes
prompt = build_pt_prompt("BUR", {"story": "...", "landing_page": "https://burrow.com/", "notes": "", "promo": "..."}, during_sale=True)
# Generate the completion yourself (brand copywriter skill loaded), matching the
# Return format in the prompt exactly (DIRECTION: / SL: / CTA: / CTA_URL:), then:
brief = parse_pt_response(completion_text)
html = build_html_notes(record, sl_ph_text=f"SL: {brief['sl']}", direction_text=brief['direction'],
                        during_sale=True, sale_name=..., sale_discount=..., pt_brief=brief)
```

**CTA must never appear as a bare URL in the body — confirmed bug 2026-07-30.** The prompt requires the model to end the body with a `CTA:` line (2-4 words, ending in `→`, e.g. "Shop the Sale →") followed by a `CTA_URL:` line, never an inline "text: URL" sentence. `parse_pt_response()` extracts both into `cta_text`/`cta_url` and collapses the two lines into a single sentinel inside `brief['body']`. Two renderers reassemble it:
- `render_pt_body_html(brief, esc_fn)` — for `html_notes`, substitutes the sentinel with a real `<a href="{cta_url}">{cta_text}</a>` anchor. This is what makes `build_pt_campaign.py`'s `_apply_link_rules()` Rule 1 (explicit Asana `<a href>` link — highest priority) fire correctly; a bare "text: URL" line matches none of that function's rules and was left sitting as literal visible text in the sent email — exactly the bug that prompted this fix.
- `render_pt_body_plain(brief)` — for the plain-text `notes` field, substitutes the sentinel with `"{cta_text} {cta_url}"`.

Never call `esc()`/`highlight_copy_value()` directly on a raw `pt_brief['body']` string — always go through one of the two renderers above, or the CTA sentinel (or a leaked `<a>` tag) will render literally.

**Hard validation against a leaked `<a>` tag — confirmed bug 2026-08-05, fixed same day.** An ID PT send (`Warehouse Sale Reminder - PT`) shipped with the CTA written as a literal inline `<a href="...">Shop the Warehouse Sale.</a>` anchor instead of the `CTA:`/`CTA_URL:` line pair — `parse_pt_response()` had no check for this, so the raw tag survived into `brief['body']` with `cta_url` empty, and `render_pt_body_html()`'s no-sentinel fallback (`esc_fn(body)`) just escaped it into visible `&lt;a href=...&gt;` text in `html_notes` (the live Braze send itself was fixed by hand directly in Braze before it went out, which is why the Asana record and the sent email diverged). `parse_pt_response()` now raises `SliceBriefValidationError` if the parsed body or `cta_text` contains any raw HTML tag other than `<strong>`/`</strong>` — same mechanism as the CZ/STF/BW slice-count and duplicate-product checks, and (unlike those) `parse_pt_response()` previously had no `except SliceBriefValidationError: raise` guard ahead of its catch-all `except Exception: return None`, so this class of error would have silently become a `None` return instead of surfacing — that guard was added in the same fix. Regenerate the completion with a plain `CTA: ...` / `CTA_URL: ...` pair and re-parse; do not catch this exception and fall back to creating/updating the task anyway.

`build_html_notes()`/`build_description()` take a `pt_brief` dict (not a plain string) for this reason. It's rendered under a `<strong>Proposed Body Copy (AI generated):</strong>` header (own line) followed by the highlighted draft — same yellow-`<mark>` convention as every other AI-generated field, with the CTA anchor nested inside. The header text is load-bearing: `scripts/braze_automation/build_pt_campaign.py`'s `_BODY_COPY_HEADER` regex slices everything after it in as the real email body at build time (updated to tolerate the `(AI generated)` suffix). Do not rename the header without updating that regex.

Do **not** write the sale disclaimer (CZ/HAV) into the AI-drafted body — `build_pt_campaign.py` appends it automatically from `sale_schedules.yaml` at build time; the brief only needs the Promo line.

### Trigger Phrases
"Add [BRAND] [MONTH] to the all brands marketing calendar" / "Do the calendar tasks for [BRAND] [MONTH]"

### Step-by-Step

Follow all field requirements from **Asana Briefing Standards** (required fields, Task Status on Creation, html_notes format, SL/PH format, etc.) — the steps below cover calendar-specific mechanics only.

1. Fetch sheet rows for brand/month using Sheets API with `includeGridData=true` to capture embedded hyperlinks
2. Parse all rows with a story in the story column; skip rows with no story
2b. **HAV only — weekend coverage check, before creating any tasks.** Confirmed root cause (2026-07-31): a month+ of HAV briefing shipped with zero Saturday/Sunday sends because the sheet itself had no weekend rows filled in that month — nothing in the pipeline has weekday awareness, so the gap passed through silently until Mina caught it and fixed it by hand afterward. Each audience (DPS and MP) needs at least one weekend send per week; it's fine for a week to be missing Saturday OR Sunday, never both, and never for an entire audience. Run the check against the parsed records before creating tasks:
   ```python
   import sys; sys.path.insert(0, "scripts")
   from create_calendar_tasks import validate_hav_weekend_coverage
   warnings = validate_hav_weekend_coverage(hav_records)  # list of parsed row dicts for this batch
   ```
   If it returns any warnings, do not silently proceed — surface them and confirm with the sheet owner (Mina) whether weekend rows need to be added before briefing continues. This is advisory, not a hard block (a partial-month pull legitimately won't cover its first/last week), so use judgment for edge weeks at the start/end of the requested range.
2c. **HAV only — major-sale "Items In Your Design Are On Sale" coverage check, same step as 2b.** This recurring MP/CONV send (see [Recurring Major-Sale Send](#recurring-major-sale-send--items-in-your-design-are-on-sale-mp-only) above) should appear in the plan for every major HAV sale window in the batch's date range; it silently stopped being briefed after 2026-07-04 and nothing caught the gap for a month and a half. Run alongside the weekend check, against the same parsed records:
   ```python
   from create_calendar_tasks import validate_hav_items_in_design_coverage
   warnings = validate_hav_items_in_design_coverage(hav_records)
   ```
   If it returns any warnings, do not silently proceed — either add an "Items In Your Design Are On Sale" MP row for that sale window to the plan (confirming with the sheet owner if the sheet itself needs the row), or confirm with them that it's intentionally being skipped this cycle. Same advisory caveat as 2b — a partial-month pull that only grazes the edge of a sale window may not need one.
3. Check for embedded links in hyperlink and textFormatRuns fields — include in notes as LP or reference
4. For each task, **sequentially** (not parallel — avoids rate limits):
   a. `create_task` with all custom fields (see Task Parameters; required fields per Asana Briefing Standards)
   b. Immediately `asana_update_task` with `html_notes` **and** Task Status = Awaiting Creative (`1209982215610994`) if the brief is fully populated — CZ tasks go to Awaiting Copy (`1213916481930051`) instead, see Task Status on Creation — do NOT batch all creates first and then all updates; complete both calls for one task before moving to the next
   c. `add_task_to_section` for both sections
   d. If Channel = SMS or Push, or Brand is a copy-first brand (CZ, STF, TI, BUR, HAV), and status was set to Awaiting Creative/Awaiting Copy, run `uv run python scripts/braze_automation/copy_subtask.py --task-gid <GID>` per the **SMS/Push (+ CZ/STF/TI/BUR/HAV) Awaiting Creative — Lacy Notification Rule** (safety-net create of Lacy's copy subtask + comment; idempotent)
5. After all tasks are created, **verify completion**: query each created task and confirm all required fields (Brand, Channel, Category, Type, Task Status, Audience, Segment where applicable) and html_notes are set. Report any tasks that are missing fields so they can be fixed immediately.
6. Update `data/calendar_task_mapping.yaml` with new GIDs

### Destination Projects

| Project | GID | Section |
|---------|-----|---------|
| All Brands Marketing Calendar | `1207353785125835` | Month section (see below) |
| Master CRM (Email & SMS) | `1207522423363072` | Planning/Briefing = `1207522423363074` |

**All Brands Marketing Calendar — Month Section GIDs**

| Month | Section GID |
|-------|------------|
| May 2026 | `1209112504768866` |
| June 2026 | `1211777222165884` |
| July 2026 | `1212203864377114` |
| August 2026 | `1212203864377115` |
| September 2026 | `1212203864377116` |
| October 2026 | `1212203864377117` |
| November 2026 | `1212203864377118` |
| December 2026 | `1212203864377119` |

### Task Parameters

- `projects`: `["1207353785125835", "1207522423363072"]`
- `due_on`: send date
- `custom_fields`:
  - Brand: `1207522425689880` → see Brand Option GIDs in memory
  - Task Status: `1209982215610993` = `1210229585661743` (Waiting on Brief to Be Filled Out) — set in `create_task`; immediately update to Awaiting Creative (`1209982215610994`) in the `asana_update_task` call that sets `html_notes`, if the brief is fully populated
  - Assets Due Date: set automatically by Asana automation — do **not** pass this in `create_task` custom_fields (causes Bad Request)
- After create: `add_task_to_section` for **both** sections

### Sheet Tab Layouts (columns are 0-indexed)

**HAV** (tab: `HAV`): col 1=Date, 2=Day, 4=Promo, 6=Story, 7=Banners, 8=SL, 9=PH
**CZ** (tab: `CZ`): col 1=Date, 2=Day, 3=Content Pillar, 4=Content Type, 5=Format, 6=Story, 7=LP, 9=Notes
**ID + BUR** (tab: `ID + BUR`): shared Date/Day cols 1-2; ID: Story=8, LP=9, Notes=11; BUR: Story=17, LP=18, Notes=20
**TI + SF** (tab: `TI + SF`): shared Date/Day cols 1-2; TI: Story=8, LP=9, Assets=10, Notes=11; STF: Story=17, LP=18, Notes=20
**TRADE** (tab: `TRADE`): col 1=Date, 2=Day, 3=Brand, 9=Story, 10=LP, 12=Notes

### Notes Template
```
Date: [M/D (Day)]
Content Pillar: [or blank]
Content Type: [or blank]
Format: [or blank]
LP: [URL if found in sheet, or blank]
Assets: 
Notes: [notes from sheet, or blank]
```
Milled reference links embedded on story names → put in Notes as "Reference email: [URL]"

### Fetching with Hyperlinks
```bash
curl -s "https://sheets.googleapis.com/v4/spreadsheets/1S3YEx-f7aOTrqZgD4VUbQ7-XKunMIyUYkWJ2d1CGR4o?key=$GOOGLE_SHEETS_API_KEY&ranges=[TAB]!A[START]:Z[END]&includeGridData=true&fields=sheets.data.rowData.values.hyperlink,sheets.data.rowData.values.formattedValue,sheets.data.rowData.values.textFormatRuns"
```

## Asana Briefing Standards

Standards for all task creation and campaign briefing across all brands.

### Resend / Re-Run Sends (all brands, all channels)

A calendar row flagged as a resend ("resend", "re-run", Content Type = "Refresh/Resend", "pull resend from 2024", etc.) is a **re-run of a past campaign with fresh creative**, sent to the previous campaign's **full audience — openers and non-openers alike**. It is *not* a literal re-fire of an already-coded email, and *not* a non-opener-only send.

Two things are required on every auto-briefed resend task:

**1. Creative Direction must say so.** Open with the exact prefix `Re-run of past campaign with fresh creative — `, then the creative angle. Never write "Resend to non-openers" or any non-opener audience claim — it reads as an exact resend and misstates the audience.

- **Wrong:** `Creative Direction: Resend to non-openers — pair bedding essentials with our best-selling beds.`
- **Right:** `Creative Direction: Re-run of past campaign with fresh creative — pair bedding essentials with our best-selling beds.`

**2. The brief must link the source send.** Add a `Resend of:` line directly under Creative Direction with the source campaign name + send date + SL, **the Asana ticket of the original, and its Braze or Klaviyo campaign link**:

```
Resend of: P_EM_2025_08_23_TI_D_PF_Perfect_Pairs_Resend (sent 2025-08-23, SL "You + Sale = A Perfect Match") · [Asana ticket] · [Klaviyo campaign]
```

Resolve the source with:

```bash
uv run python scripts/utils/resend_source.py --brand TI --task-name "Perfect Pairs Resend" --before 2026-08-22 --top 3
```

It returns the matching past campaign's name, send date, subject, performance, platform, and campaign link. **Never invent a source** — if nothing matches, say so and confirm with the calendar owner (Mina/Nicole) what the row re-runs rather than guessing.

**Two links have to be fetched separately, by design:**
- **Asana ticket of the original** — campaign YAMLs carry no `asana:` block (verified 2026-08-19: zero files have one), so search Asana for the `asana_search_name` the resolver returns (the task name with `SMS:`/`Resend`/`Promo:` noise stripped) and use that task's permalink.
- **Platform campaign link** — Klaviyo is synthesized automatically from `klaviyo_campaign_id` (`https://www.klaviyo.com/campaign/{id}/overview`). **Braze cannot be**: the YAML `id` is the campaign *API* ID (UUID), not the 24-hex internal ID dashboard URLs use. Grab the Braze link from the source task's own **Braze Campaign Link** field (GID `1210710306792280`) when you have it.

**When no clickable campaign link is available, include a date + title reference instead of dropping the field** — never leave the coder with nothing to search on:

```
Resend of: P_EM_2025_11_26_BW_D_Leather_Highlight (sent 2025-11-26, SL "Looking good in leather") · [Asana ticket] · (Braze Campaign: 11/26/25 Leather Highlight)
```

`format_campaign_reference()` builds that parenthetical automatically — `{Braze|Klaviyo} Campaign: M/D/YY {Title}`. The title comes from `campaign_display_title()`, which strips the structural scaffolding (type code, channel, date, brand, design type, HAV audience, and the `PF`/`PR` file markers) and keeps content codes that carry meaning to a human (BIS, CLR, GTL, UGC, RTS, CS, EA, BNDL, POTM). It handles all three naming eras — current convention (`P_EM_2025_08_20_BUR_D_Pillow_Pairings` → `Pillow Pairings`), pre-convention names with no channel segment (`P_2025_05_08_D_TI_Pattern_Pairings` → `Pattern Pairings`), and legacy/TE names (`Perfect Match - 2/14/23` → `Perfect Match`; `03-10-26 | New Arrivals | Shopping` → `New Arrivals — Shopping`). Note `parse_campaign_name()` in `campaign_name.py` is **not** used for this: it leaves the brand and design code sitting in `description` whenever the brand isn't in its own code table (real names use `BUR` where the convention says `BW`), and bails entirely on pre-convention names.

The resolver also skips retired duplicates and internal test sends (`[delete]P_EM_…`, `…_Test_Send`, `do not use`) — real records that would otherwise get offered as a source.

**Implemented, not just documented** — `scripts/utils/resend_source.py` (`detect_resend()`, `normalize_resend_direction()`, `find_resend_source()`) plus three seams in `scripts/create_calendar_tasks.py`:
- `resend_prompt_instruction(record)` is appended to all 6 brief prompts (`build_cz_prompt`, `build_stf_prompt`, `build_bw_prompt`, `build_ti_prompt`, `build_hav_prompt`, `build_pt_prompt`) so the model writes the right DIRECTION; it returns `""` for non-resend rows, leaving those prompts byte-identical.
- `apply_resend_direction()` runs as a **single post-processing pass** over the assembled `parts` list in both `build_html_notes()` and `build_description()` — it rewrites the direction and inserts the `Resend of:` line. Deliberately not per-brand: all 5 brand branches in `build_html_notes` emit their own `<strong>Creative Direction:</strong>` line, and per-branch edits are exactly how the slice rules drifted out of sync before.
- Pass `resend_source=` (from `resolve_resend_source()`) and `resend_asana_url=` plus `task_name=` when calling either renderer. If a row is detected as a resend and no source was passed, the build prints a `[WARN]` naming the task — don't ship the brief without chasing it down.

Normalization is defensive, not just prefix-prepending: it strips the wrong leading clause (`Resend to non-openers — `, `Resend of the X email to non-openers - `, bare `Resend — `), deletes mid-sentence non-opener audience claims, lowercases the handoff word so it reads as one sentence, and warns if "non-opener" survives anywhere.

A re-run still needs **slices delivered** — designers have asked whether a "resend" means no new assets ([Anya on Perfect Pairs Resend, 2026-08-18](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1217247860374284)). The prompt block states this explicitly so the brief never implies otherwise.

### Promo Lookup (all channels, all brands)

When creating **any** Asana task — email, SMS, or push — check `data/sale_schedules.yaml` for an active sale on the send date for that brand. Load the file with PyYAML and match on `brand` and date range (`start_date` ≤ send date ≤ `end_date`). For HAV, also match `havenly_audience` (PC for DPS tasks, CONV for MP tasks).

If an active sale is found, include the promo details in the task description:
- **Email html_notes:** add `<strong>Promo:</strong> {sale_name} — {sale_discount}` after the Creative Direction field
- **SMS notes:** add a line `Promo: {sale_name} — {sale_discount}` after the proposed copy block
- **Push notes:** add `Promo: {sale_name} — {sale_discount}` after the proposed copy block

If `discount` in the YAML is a placeholder (`PERIOD:`, `(PROPOSED)`, `DETERMINED`, `(TBD)`), show only the sale name and omit the discount. If no active sale exists, omit the field entirely.

### Sale Banner & Popup Creative Request Tickets

Ahead of every sale, create Asana tickets asking Creative for the **email-drip promo banners** (and, for Havenly, **popups**). Trigger: *"create the banner/popup creative tickets for the [sale] sale."* These are creative-request tickets, **not** campaign sends — do not multi-home to the marketing calendar.

**Which brands get tickets:**
- **Most sales:** HAV (DPS **and** MP/merch), ID, BW, CZ.
- **Tentpole sales only** (e.g. Labor Day): additionally SF and TI.

**How many graphics — one per sale phase.** Look up the sale's phases on the [Asana Promo Tracking Board](https://app.asana.com/1/5257710284167/project/1213996005172086/) / `data/sale_schedules.yaml` (match `brand`, and `havenly_audience` for HAV). One event → 1 graphic; Early Access + main + extension → 3 graphics. Only request phases that actually exist on the board for that brand (e.g. if a brand shows only a main event, request 1 — do not assume EA/extension).

**Havenly specifics:**
- **MP/merch does NOT use promo banners — popups only.** DPS uses **both** banners and popups.
- Put HAV banners + popups in the **same** ticket **when DPS and MP are on the same sale**. When DPS and MP are on **different** sales (different names/dates), split into **two** tickets, one per audience/sale.
- **Put MP / DPS in the HAV task name** (e.g. "MP Flash Sale Popup", "DPS Labor Day Event Banners + Popups") so audiences stay distinguishable.

**Ticket fields (all brands):**
- Project: Master CRM `1207522423363072`, section `1207614167824712` (the creative-requests section). Tasks default into "Planning/Briefing" on create — move them with `asana_add_task_to_section`.
- **Type = Banner/Module** — field `1207522425689987`, option `1209982215611001`.
- **Task Status = Awaiting Creative** — field `1209982215610993`, option `1209982215610994` (set at creation; assignment happens automatically off brand + Awaiting Creative, so leave assignee unset). Leave the QA-checklist field unset.
- **No Lacy copy subtask.** Because Type = Banner/Module, these are excluded from the Lacy copy-subtask flow even for CZ/STF/TI/BUR/HAV (see the Banner/Module exception under the Lacy Notification Rule) — they must not create a copy subtask assigned to Lacy or @-mention her.
- `due_on` = **~1.5 weeks (10–11 days) before the sale's earliest phase start** (EA date if there is one, else the main-event start). Pick a weekday.
- Brand field `1207522425689880`: Havenly `1207522425689881` · Interior Define `1207522425689882` · The Citizenry `1207553690167887` · Burrow `1208572919795447` · The Inside `1207522425689883` · St. Frank `1207881071843537`.

**Task names** — pull the exact sale name from the Promo Board:
- Non-HAV, 1 phase: `{Sale Name} Banner` · multi-phase: `{Sale Name} Banners`
- HAV MP: `MP {Sale Name} Popup(s)` · HAV DPS: `DPS {Sale Name} Banners + Popups`

**Descriptions (plain English, plain `notes` field — no html_notes needed).** Brand codes: ID, CZ, BW (Burrow), SF (St. Frank), TI; Havenly spelled out with MP/DPS.
- 1 banner: `Looking for a promo banner for email drips for the {CODE} {Sale Name}.`
- Multi banner: `Looking for promo banners for email drips for the {CODE} {Sale Name}. We'll need banners for Early Access, the main event, and the extension.` (list only the phases that exist)
- HAV MP popups: `Looking for popup creative for the Havenly MP {Sale Name}, including the early access, main sale, and extension versions.` (list only the phases that exist)
- HAV DPS combined: `Looking for banner and popup creative for the Havenly DPS {Sale Name}, including both the main sale and the extension versions of each.` (adjust to the actual phases)

Reference examples: [Summer Sale Banner (ID)](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1215969944736526) · [Summer Sale Banners + Popups (HAV)](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1215970066270330) · [Memorial Day multi-banner (CZ)](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1214073359829967).

### Custom Field GIDs

`html_notes` is NOT supported on `create_task` — use plain `notes` on create, then immediately update with `asana_update_task` using `html_notes`.

| Field | Field GID (key) | Common Option GIDs |
|-------|----------------|-------------------|
| Brand | `1207522425689880` | Havenly=`1207522425689881`, ID=`1207522425689882`, CZ=`1207553690167887`, BUR=`1208572919795447`, TI=`1207522425689883`, STF=`1207881071843537` |
| Channel | `1207562370794988` | Email=`1207562370794989`, SMS=`1207562370794990`, Push=`1207562370794991` |
| Task Status | `1209982215610993` | Awaiting Copy=`1213916481930051`, Awaiting Creative=`1209982215610994`, Awaiting Approval=`1209995669275787`, Ready to Code=`1209995669275789`, Waiting on Brief=`1210229585661743` |
| Category | `1207522425689885` | Sale=`1207522425689886`, Editorial=`1207522425689887`, Product Launch=`1207522425689888`, Product/Category=`1207522425689889`, DPS=`1207522425689891` |
| Audience | `1207522425689896` | Pre-converted=`1207522425689897`, Customers=`1207522425689898`, Crossbrand=`1207584209488088` |
| Segment | `1211927654349290` | Full File=`1211927654349291`, Engaged=`1211927654349292`, Geo=`1211927654349293` — **no longer set for ID or TI** (see Segment (Text) below); still used as-is for all other brands |
| Segment (Text) | `1216855544683297` | Text field — **ID + TI**, replaces the enum Segment field for these two brands going forward (see "ID Segment (Text) field" and "TI Segment (Text) field" below) |
| Type | `1207522425689987` | Plain-Text=`1207522425689988`, Batch & Blast=`1209982215610998` |
| Trade Brand | `1210233166197147` | Interior Define=`1210233166197148` — set whenever Brand=Trade |
| Template inspiration (with reasoning) | `1209982221146588` | Text field — populate for STF email tasks |

**Required fields when creating tasks:** Brand, Channel, Task Status, Category, Type (email only), Audience (where applicable), and Segment (where applicable) — see rules below for Audience and Segment.
- Trade tasks: also set Trade Brand = Interior Define
- Designed email → Batch & Blast; Plain-text email → Plain-Text
- Push → no Type, no Segment; Send Time = always 3 PM

**Segment Rules by Brand** — only set Segment when logic is defined below; omit for brands without logic. **These rules apply to email tasks only.** SMS (and push) always send to a single list regardless of engagement — never set the Segment field on an SMS or push task, for any brand, even during a brand's "N sends per week use Engaged" window. (Confirmed gap 2026-08-05: 22 BW SMS tasks going back to Oct 2025, including 18 from the 2026-07-30 Labor Day batch, had Segment set because the brand bullets below didn't say "email" explicitly — only HAV's did.)

**HAV** (always populate Segment for HAV email tasks):
- **Full File** — sale emails of any type (launch, reminder, early access, last chance, final hours, PT sale); combined DPS + MP sends; big-name designer features; Before & After
- **Engaged** — single-audience (DPS-only or MP-only) non-sale editorial content
- Push → no Segment (omit entirely)

**CZ** — default Full File; 1–2 sends per week use Engaged — pick the sends least likely to perform well (e.g. lower-interest editorial, repeat reminders, secondary content); sale announcements and last day/final hours emails always Full File

**ID** — default Full File; **2–3 sends per week use Engaged**. Pick the sends least likely to perform well, applying this priority (evaluate per calendar week, Mon–Sun; exclude Trade sends):

- **Always Full File (never Engaged):**
  - First-day (sale launch / early access) and last-day (last chance) sale sends — the week's top performers
  - Revenue-driving mid-sale category features and collection spotlights (e.g. Sofas/Sectionals, Dining, and named-collection sale spotlights)
  - **New-collection** sends (launches and their follow-ups) — new collections need full reach
- **Good Engaged candidates (pick 2–3/week from these):**
  - Established/older collection spotlights (not new collections)
  - Editorial/content sends (buying guides, etc.)
  - Repeat/mid-sale reminders and secondary "follow-up" sends that aren't for a new collection
  - **PM double sends** (e.g. a "Final Hours PM" send on the same day as a Full File last-chance send) — the double send can be Engaged
  - **Swatch Talk** sends — most are Engaged-eligible, **but ensure at least some Swatch Talks each month still go Full File**, and lean **Full File for Swatch Talks near the beginning of a sale** (subscribers order swatches early so they can purchase pieces before the sale ends)

  Never drop below the "always Full File" anchors to hit the 2–3 target — if a week doesn't have 2–3 safe Engaged candidates, send fewer to Engaged rather than downgrading a high performer.

**ID Segment (Text) field — segmentation redo (2026-07-24, 7 segments wired 2026-07-31):** Per [Update Interior Define Segmentation](https://app.asana.com/1/5257710284167/project/1208217080803312/task/1214216873746059), ID email tasks — **both PT and designed** — use the **Segment (Text)** custom field (`1216855544683297`, plain text) instead of the enum Segment field above when briefing. Write one of these values:
- `Full File` (also accepts `All / Full File` or `All`)
- `Engaged`
- `Highly Engaged`
- `Swatch Purchasers`
- `Swatch Non-Purchasers` (also accepts `Swatch non purchasers` / `Swatch nonpurchasers`)
- `Geo Segment - Engaged`
- `Geo Segment - Unengaged`

Matching is case-insensitive and tolerant of dash style (`-`/`–`/`—`) and spacing — `_normalize_segment_key()` in `build_pt_campaign.py` collapses a value to lowercase-alphanumeric-only before comparing, so `"highly engaged"`, `"HIGHLY ENGAGED"`, and `"Highly-Engaged"` all resolve the same way. Still write the values above verbatim in Asana for consistency; the tolerance is a safety net for human variation, not an invitation to freelance new phrasings.

The Full File vs Engaged decision logic above (2–3 Engaged sends/week, priority lists, etc.) still governs which of those two values to write for standard batch sends. Highly Engaged, Swatch Purchasers/Non-Purchasers, and the two Geo values are not yet auto-selected by any rule — only set them when a specific send type calls for that audience (e.g. Swatch Talk → Swatch Non-Purchasers).

**Braze audience mapping — effective 2026-08-18 (all 7 segments live):** For ID, `resolve_segment_type_for_task()` (in `build_pt_campaign.py`, shared by `build_designed_campaign.py`) reads `Segment (Text)` first, then routes through `_resolve_id_segment_type()`, which is **date-gated** on the campaign's own send date via `_ID_SEGMENTATION_V2_CUTOFF = "2026-08-18"`:
- **Send date ≥ 2026-08-18** — all 7 values route to their own dedicated Braze segment (`data/brand_config.yaml` ID audience keys `full_file_v2`, `engaged_v2`, `highly_engaged`, `swatch_purchasers`, `swatch_non_purchasers`, `geo_engaged`, `geo_unengaged`). An unrecognized value logs a warning and defaults to `full_file_v2`.
- **Send date < 2026-08-18** — unchanged legacy interim mapping: blank/`Full File` → `full_file` (Braze segment `Main Email Send List`); `Engaged`/`Highly Engaged` → `engaged` (Braze segment `AM VIP B2C Segment`); anything else defaults to `full_file` with a warning. This protects already-scheduled near-term tasks from being silently retargeted by the cutover.

**If `Segment (Text)` itself is blank on the task, it falls back to reading the legacy enum Segment field** — this keeps older/in-flight ID tasks (briefed before the new field existed) working during the transition; if that's also blank, it defaults to Full File (the pre- or post-cutoff one, per the send date).

**Companion fix — exact-match segment selection:** `_select_segment()` in `build_pt_campaign.py` used to find the Braze dropdown option to click via a `:has-text()` substring match + `.first`. With `Engaged`, `Highly Engaged`, `Geo Segment - Engaged`, and `Geo Segment - Unengaged` all live in the same segment picker, a substring match on `"Engaged"` would match all four and could silently click the wrong one. Fixed 2026-07-31 to compare each rendered option's exact trimmed text before clicking, retrying (and ultimately failing loudly) if no exact match is found — this fix is load-bearing for the 7-segment rollout, not optional polish.

**BUR** — default Full File; **2–3 sends per week use Engaged**. Favor sends you expect to drive revenue → Full File; route the sends least likely to drive revenue → Engaged. Evaluate per calendar week (Mon–Sun):

- **Always Full File (never Engaged):**
  - First-day (sale launch / early access) and last-day (last chance / final hours) sale sends — **exception:** on a **double-send day** (e.g. "Final Hours — Morning" designed + "Final Hours — Evening" PT on the same last day), keep the primary/morning send Full File and the second/evening send can go Engaged
  - High-revenue category sends: Sofas/Sectionals, Bestsellers, Storage, Quick Ship (in-stock conversion driver), and named-collection launches
- **Good Engaged candidates (pick 2–3/week from these):**
  - Editorial/content sends (social proof, "picks" roundups, lifestyle/seasonal editorial)
  - Lower-ticket / narrow category features (Accent Chairs, Dining Chairs, single-SKU features like Media Console)
  - Swatch / lead-gen sends (Free Swatches) — lower direct revenue
  - Seasonally-declining categories (e.g. Outdoor in late summer)
  - The **evening/PM half of a double send** (per the exception above)

  Same guardrail as ID: never downgrade a likely high-revenue send just to hit the 2–3 count — send fewer to Engaged that week instead.

**STF** — always Full File

**TE** — Always Full File: Best of Month, sale emails, product launches, big-name designers; default Engaged for all other

**TI** — default **Engaged** (opposite default from every other brand above — Engaged is TI's baseline, gets every regular send: new arrivals, editorial, sale launches/reminders, early access, POTM/print drops, referral/bonus sends). **Full File** is the restricted tier (1–2 sends/week) — always use it for sale launches, early access launches, and last-chance/final-day-of-sale sends; skip it for everyday editorial/content-only sends. **Swatch Purchasers** / **Swatch Non-Purchasers** are targeting overlays, not frequency tiers — use only for dedicated swatch-focused content (e.g. a "Swatchee" sale nudge → Swatch Purchasers; a swatch-program explainer/UGC send → Swatch Non-Purchasers), never for standard cadence sends. See "TI Segment (Text) field" below.

**TI Segment (Text) field — segmentation redo (2026-08-06):** Per [Update Segmentation](https://app.asana.com/1/5257710284167/project/1208217080803312/task/1216770925418815), TI email tasks — **both PT and designed** — use the **Segment (Text)** custom field (`1216855544683297`, plain text) instead of the enum Segment field above when briefing. Write one of these 4 values:
- `Full File`
- `Engaged`
- `Swatch Purchasers`
- `Swatch Non-Purchasers`

Matching is case-insensitive and dash/spacing-tolerant (`resolve_ti_segment_key()` in `scripts/utils/segment_text.py` normalizes the same way ID's `_normalize_segment_key()` does) — still write the values above verbatim in Asana for consistency.

**If `Segment (Text)` is blank, the build falls back to the legacy enum Segment field, then defaults to `Engaged`** — note this default is the *opposite* of ID's (Full File). This keeps older/in-flight TI tasks working during the transition.

**Klaviyo audience mapping:** `Full File` → the Klaviyo segment named exactly `"Full File"`, `Engaged` → `"Engaged"` (`data/brand_config.yaml` TI audience keys `full_file`/`engaged`) — both created 2026-08-03 to match the ticket's precise criteria (90-day activity floor for Engaged; 12-month suppression baked into Full File), superseding the old "May 2024 Full List"/"AM List VIP" mapping. **`Swatch Purchasers` → `"Swatch purchasers"`, `Swatch Non-Purchasers` → `"Swatch non-purchasers"`** — created in Klaviyo 2026-08-11 (`data/brand_config.yaml` TI audience keys `swatch_purchasers`/`swatch_non_purchasers`; segment-name matching is case-insensitive, so the title-case strings in config resolve fine against Klaviyo's lowercase names).

**Swatch segmentation cutover — effective 2026-08-18:** the two swatch segments only take effect for sends **on or after 2026-08-18** — `TI_SWATCH_SEGMENTATION_CUTOFF` in `resolve_ti_segment_key()` (`scripts/utils/segment_text.py`), which now takes an optional `send_date` (Asana `due_on`, threaded through all 3 email builders — `create_klaviyo_email.py`, `build_klaviyo_designed_campaign.py`, `build_klaviyo_designed_email.py`). For a send date before the cutoff (or when the date is unknown), `Swatch Purchasers`/`Swatch Non-Purchasers` fall back to `Engaged` instead of hard-failing — same rationale as ID's `_ID_SEGMENTATION_V2_CUTOFF`: protects tasks briefed before the segments existed from being silently redirected to them once they went live. This is **email-only** — TI SMS continues sending to `Master SMS Segment` via its own separate, unaffected path in `create_klaviyo_sms.py`, which never reads Segment (Text) or `resolve_ti_segment_key()`.

**Exclusion applies to all 4 lists:** `"Trade Members (All)"` (plus `"Apple emails - unengaged"`) is a brand-level exclusion (`brands.TI.klaviyo.audiences.excluded` in `data/brand_config.yaml`) read unconditionally regardless of which of the 4 segment keys resolved — no per-segment config needed.

**HAV DPS vs MP Audience:**
- DPS only → Audience = Pre-converted (`1207522425689897`)
- MP only → Audience = Customers (`1207522425689898`)
- DPS + MP combined → leave Audience blank

### Task Naming

Task names must be **short and human-readable** — never the Braze campaign name. Strip type prefix, channel, date, brand, and design codes.

- `P_SMS_2026_04_16_CZ_Sleep_Well_Sale_Launch` → **"Sleep Well Sale Launch"**
- `P_EM_2026_04_23_CZ_D_Sleep_Well_Sale_Reminder` → **"Sleep Well Sale Reminder"**

**Prefixes by channel/audience:**
- SMS tasks: always `SMS:` prefix (e.g. "SMS: Memorial Day Event Launch")
- HAV DPS-only push: `DPS:` · HAV MP-only push: `MP:` · Combined: `DPS and MP:`

**Sale task names must use the exact sale name from the Asana Promo Tracking Board** (`https://app.asana.com/1/5257710284167/project/1213996005172086/`), not an invented/generic name. Look up the promo covering the send's date range and pull its exact name (e.g. `Summer Sale`, `Archive Sale`, `Flash Sale`, `Labor Day Event EA`, `Labor Day Event`, `Labor Day Event Ext`), then append the send's role: `{Sale Name} Launch` / `{Sale Name} Reminder` / `{Sale Name} Last Chance`. Do not build names like "Early August Sale Launch" or "August Sale Reminder" by guessing from the calendar month — always confirm against the Promo Board first. If a window's offer/name is still unconfirmed on the Promo Board (e.g. discount TBD), leave the task named generically (e.g. "Sale Launch (Offer TBD)") rather than inventing a name, and revisit once the Board is updated.

### Task Status on Creation

- **Awaiting Creative** — when brief is fully populated (LP, products, SL/PH, Figma all filled in). Set this in the `asana_update_task` call alongside `html_notes` — not in `create_task`, since `html_notes` requires a separate update anyway. Always set both in the same call.
  - **CZ, STF, TI, BUR, and HAV exception:** for CZ, STF, TI, BUR, and HAV tasks, once the brief is fully populated, set Task Status = **Awaiting Copy** (`1213916481930051`) instead of Awaiting Creative — so Lacy writes/reviews the copy before it moves further (the copy-first process). This applies to these five brands only — all other brands still go to Awaiting Creative. Setting these brands to Awaiting Copy is what triggers the native Asana "Lacy Notification Rule" to create Lacy's copy subtask. **HAV is briefing-only** — its auto-build still uses the existing DnD-duplicator path (`HTMLCSS_DESIGNED_CUTOFFS` in `webhook_server.py`/`poll_ready_tasks.py` does NOT include HAV; see [HTML/CSS Brand Migration](#htmlcss-brand-migration)) — this switch changes only how HAV designed emails get briefed, not how they get built.
- **Waiting on Brief** — for empty placeholder tasks that still need the brief written. Leave as-is; do not update status.

### Task Status Update — Check Before Setting

Before updating any task's `Task Status` field, fetch the task's current status and skip the update if it's already set to the target value. This prevents re-triggering Asana automation rules that fire on field saves (not just transitions).

```python
task = asana_get_task(gid, opt_fields=["custom_fields"])
current_status = next(
    (f["enum_value"]["gid"] for f in task["custom_fields"] if f["gid"] == "1209982215610993"),
    None
)
if current_status != target_status_gid:
    asana_update_task(gid, custom_fields={"1209982215610993": target_status_gid})
```

Apply this check for all status transitions, including Waiting on Brief → Awaiting Creative, Awaiting Creative → Ready to Code, etc.

### Same-Day Send Rule (all brands, all channels)

When two email tasks are created for the same brand and date, one must be AM and one must be PM:

- Set the PM task's **Send time** field to `4:00 PM`.
- **PT gets PM**: if one task is Plain-Text and one is designed (Batch & Blast), the PT task gets PM.
- **Default**: if both tasks are the same type (or neither is PT), the second task created gets PM.
- **HAV exception**: one DPS send + one MP send on the same day may both be AM — different audiences, not a conflict. Two DPS sends or two MP sends on the same day still require one PM.

A second send must **never** be added for the same brand+date without the Send time field filled out on the appropriate task.

`create_calendar_tasks.py` enforces this automatically via `_assign_same_day_send_times()`. For manual/MCP task creation, apply the same rule explicitly.

#### PM-in-name → 4:00 PM send time (auto-builders, all brands/channels)

When an Asana task has **no explicit Send time** but its task name signals an afternoon send (a standalone `PM` token — e.g. "4th of July Sale Final Hours - PM" — or "afternoon"), the auto-builder schedules it for **4:00 PM local** (`email_pm` in `data/lifecycle_guidelines.yaml`, the lifecycle common data set column M — 4:00 PM across all brands).

Resolution order (both plain-text and designed email builders):
1. **Explicit Send time field wins** — if set, honor it as-is.
2. **PM in name (field empty)** → 4:00 PM local, ahead of any sale/last-chance or HAV-CONV AM default.
3. Otherwise fall through to the existing sale-announcement / Intelligent-Timing / business-days logic.

Implemented via the shared `is_pm_send(task_name)` helper and `PM_SEND_TIME` constant in `build_pt_campaign.py`, consumed by both `resolve_send_time()` (PT) and `resolve_send_time_designed()` (designed, `build_designed_campaign.py`). Detection is token-based, so an explicit time like `3pm` written into the name is not mistaken for the PM slot. SMS and Push keep their own 3:00 PM defaults and are unaffected.

### SMS/Push (+ CZ/STF/TI/BUR/HAV) Awaiting Creative — Lacy Notification Rule

A task gets a copy subtask assigned to Lacy Morris + a notification comment whenever it is at Task Status = **Awaiting Creative or Awaiting Copy** and it is either **SMS or Push** (any brand) **OR** a **copy-first brand — CZ, STF, TI, BUR, or HAV** (any channel). The copy-first brands run this process: task set to **Awaiting Copy** → Lacy is tagged in and inputs copy directly on the task → Lacy flips the status to Awaiting Creative herself once done.

**Exception — Type = Banner/Module tasks never get a Lacy copy subtask.** Banner/popup creative-request tickets (see [Sale Banner & Popup Creative Request Tickets](#sale-banner--popup-creative-request-tickets)) carry no copy, so they are excluded even when they're a copy-first brand (CZ/STF/TI/BUR/HAV) at Awaiting Creative. `ensure_copy_subtask()` in `copy_subtask.py` returns early on `Type == Banner/Module` (option `1209982215611001`), which covers both the synchronous briefing call and the 15-min safety-net poller. The native Asana rule does not fire on these anyway (they're Awaiting Creative, not Awaiting Copy, and have no Channel), so the poller was the only path that created them.

**Exception — footer refresh tasks never get a Lacy copy subtask.** Quarterly footer-imagery-refresh tasks (e.g. "Fall Email Footer Refresh") are an imagery swap, not a copy request — set Task Status straight to Awaiting Creative when briefing these (skip Awaiting Copy), and `ensure_copy_subtask()` in `copy_subtask.py` excludes them outright via a case-insensitive title match on "email footer" or "footer refresh" (`_is_footer_refresh_title()`), regardless of brand/channel. Since these go to Awaiting Creative rather than Awaiting Copy, the native Asana rule (which fires copy-first brands on Awaiting Copy) doesn't create one either — same shape as the Banner/Module exception above. Confirmed friction on [Fall Email Footer Refresh](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1213317185744565) (CZ, GID `1213317185744565`), where Lacy was tagged in with nothing to write.

**Creation is owned by the native Asana "Lacy Notification Rule"** — it fires on brand ∈ {CZ, TI, SF, BUR} + Awaiting Copy, and on SMS/Push tasks, and creates the subtask + comment on its own. BUR was added to the native rule's brand condition in Asana's rule builder as of 2026-07-30 (previously only `copy_subtask.py`'s `_COPY_FIRST_BRANDS` list included it, added 2026-07-29, with the poller acting as the sole safety net until the native rule caught up). `copy_subtask.py`'s `_COPY_FIRST_BRANDS` was also extended to include HAV (2026-07-29, briefing-only — see the Task Status on Creation note above) — **the native Asana rule's own brand condition still needs HAV added manually in Asana's rule builder** (Workflow > Rules) for the primary/instant trigger to fire; until that manual step is done, HAV's copy subtasks are created only by the 15-min poller safety net, not instantly. `copy_subtask.py` is therefore a **safety net + due-date manager, not the primary creator** (do not assume the Asana rule is paused — confirmed still firing, see `memory/project_lacy_notification_rule_still_active.md`).

**Caution when bulk-flipping many tasks to Awaiting Copy at once (any brand in the native rule's condition):** because the native rule has no idempotency check of its own, flipping status on a task that already has a poller-created copy subtask (e.g. from a prior Awaiting-Creative safety-net run) WILL create a second, duplicate subtask + comment. Before a bulk status flip, check each task for an existing incomplete copy subtask; if the native rule is about to fire for brands newly added to its condition, consider temporarily pausing the rule for the duration of the bulk update, or de-duplicating subtasks afterward. Confirmed necessary 2026-07-30 when fixing ~44 BW tasks that had already picked up poller-created subtasks while stuck at Awaiting Creative.

**Do not hand-create the comment/subtask via the MCP.** Run the shared helper — it is idempotent and is the single source of truth for the subtask fields and due-date math:

```bash
uv run python scripts/braze_automation/copy_subtask.py --task-gid <PARENT_GID>
```

Run this immediately after setting the task to Awaiting Creative or Awaiting Copy during briefing. **If task creation/status-setting is delegated to a sub-agent**, the sub-agent does not inherit these instructions — so the parent session must run this command itself after the sub-agent returns. Add the parent GID for each SMS/Push task, or CZ/STF/TI/BUR/HAV task of any channel, set to Awaiting Creative/Awaiting Copy.

What the helper does (`scripts/braze_automation/copy_subtask.py`):
- **Idempotent, never duplicates.** If a copy subtask already exists (created by this script or the Asana rule) it does not create a second one. A **completed** copy subtask is treated as "copy cycle done" and is never recreated or touched — this prevents re-@mentioning Lacy for already-approved copy (the bug that spammed CZ email tasks on 2026-07-17).
- **Safety-net create only for genuine recent misses.** When creating (no subtask exists), it skips (a) tasks whose send date has already passed, and (b) backlog tasks created more than `_SAFETY_NET_CREATE_MAX_AGE_DAYS` (4) days ago — so it never mass-creates for an existing backlog and tags Lacy on dozens of tasks at once.
- **Due-date rule (spreads Lacy's load).** The Asana rule stamps every subtask at *fire + 2 working days*, so a month briefed at once all lands the same day — and a flat "N weeks out" tier system still bunches every far-out send onto one date (confirmed 2026-07-22: a whole Labor Day Event's worth of sends all landed on the same day). The poller re-stamps **far-out sends only, and only going forward** (subtasks created on/after `_RESTAMP_CREATED_ON_OR_AFTER`) to exactly **4 weeks before the parent send date** (changed from 2 weeks on 2026-07-22 per team request), pulled back to the preceding Friday if that lands on a weekend (never pushed forward). If 4-weeks-before would be earlier than the rule's own fire+2 near-term date, there's no real runway to give, so that near-term date is left standing instead — this can leave a whole early stretch of a freshly-briefed batch all sitting near-term at once (a whole month briefed in one sitting will have its first 1-2 weeks of sends all fall into this bucket); spreading those across a few near-term days is a one-time manual call, not something the formula does automatically. The existing backlog's dates are never mass-shifted.
- **Subtask/comment:** name `[task name] Copy`, assignee Lacy Morris (`1212463876283471`), Brand copied from parent; comment `Hi @Lacy Morris, the brief for [task name] is ready for you!`.
- **Brand field is re-synced from the parent on every poll, not just at creation** (as of 2026-08-11) — including clearing it if the parent has no Brand set. This closed a root-cause bug: the native Asana rule's "set Brand" action can only write a fixed value, and it was authored for CZ then never updated when the rule's trigger condition was broadened to TI/STF/BUR/HAV — so every new copy subtask got stamped with a fixed brand (The Citizenry) regardless of the parent's real brand. Confirmed 117+ mislabeled subtasks (should have been The Inside/Burrow/St. Frank) across the "All Brand Copy Requests" list before this fix — see [[project_cz_ti_bur_brand_mislabel]]. Because of this poller-side sync, the fixed-value "set Brand" action can be removed from the native Asana rule entirely; the poller now owns Brand correctness going forward.

**The rule occasionally produces an unparented copy task — `parent` is null and it is NOT a subtask at all.** Confirmed 2026-08-16: of 100 copy tasks created in All Brand Copy Requests since 2026-07-01, **95 were real subtasks and 5 were orphans** (3 with `created_by_rule` but no subtask link — a rule misfire; 2 hand-created with no `created_by_rule` at all). Their only link back to the send is the **Parent Task Due Date** custom field.

**Do not read an orphan as evidence its parent was deleted.** Asana trashes subtasks along with their parent, so a surviving copy task proves the link never existed. Diagnose from the story stream, not the `parent` field:

```
GET /tasks/{gid}/stories?opt_fields=created_at,created_by.name,resource_subtype,text
```

A real copy subtask has an `added_to_task` story (*"added this task as a subtask of X"*, attributed to the rule owner even when `created_by_rule` is also present). An orphan has **neither** `added_to_task` **nor** any detach/`removed_from_task` event. Note `created_by_rule`'s text *"Asana created this task from a private task"* means the trigger task is inaccessible **or** deleted — it proves neither on its own.

**Why this matters:** `ensure_copy_subtask()` checks for an existing copy subtask *under the parent*, so orphans are invisible to its idempotency guard. If an orphan's real parent still exists, the poller will create a second, properly-parented copy subtask and re-tag Lacy. When cleaning these up, search Master CRM by name **and** by the Parent Task Due Date value before assuming the parent is gone.

**Safety net:** `poll_ready_tasks.py` (LaunchAgent `com.havenly.poll-ready-tasks`, every 15 min) also runs `poll_awaiting_creative_copy_subtasks()`, which scans all SMS/Push and CZ/STF/TI/BUR/HAV Awaiting Creative/Awaiting Copy tasks and ensures/manages the subtask per the rules above. Because both paths call the same idempotent `ensure_copy_subtask()`, running both never produces duplicates. Backfill/scan manually with `--poll` (add `--dry-run` to preview). **Note:** this LaunchAgent runs from the repo working directory, so it executes whatever code is checked out — never leave risky mid-edit changes to `copy_subtask.py` in the working tree uncommitted, or the next poll (≤15 min) runs them live.

### STF LP Domain

St. Frank's correct domain is `stfrank.com` — no hyphen. `https://www.stfrank.com/` — not `st-frank.com`.

**STF LP fallback:** When no specific collection LP exists for the email's content (e.g., no color- or category-filtered collection page that's a genuine match), default to the homepage `https://www.stfrank.com/` — not `/collections/full-collection`.

### Recovering an overwritten brief

Asana keeps the **full previous and new description text** on every description-edit story, so a brief that was overwritten (e.g. a task rewritten to drop sale language that wiped the slice-by-slice Body Copy along with it) is recoverable — do not regenerate it from scratch.

```
GET /tasks/{gid}/stories?opt_fields=created_at,created_by.name,resource_subtype,old_value,new_value
# filter resource_subtype == "notes_changed"; old_value = the description BEFORE that edit
```

Used 2026-08-16 to restore slice-by-slice Body Copy to 4 BUR tasks (Bestsellers Roundup, Russet Collection Highlight, Sectional Highlight, Storage Highlight) after an 8/6 non-sale rewrite dropped it. **Cross-check a recovered version before trusting it:** its template name and slice count should match the template's own entry in `BW_FIGMA_TEMPLATES` / the relevant brand catalog (these matched exactly — bs_v1/5, cs_v5/6, mcs_v2/10, cs_v2/9), which distinguishes a real validated brief from a partial draft.

**Reading the recovered plain text:** Asana's plain-text rendering joins the *first* nested `<li>` onto the preceding line, so `Slice 1 — Logo & hero        Layout: Full width` is a slice header plus its first nested field, not one line. Same for `SL/PH (AI generated):    SL: ...`. Split on that when rebuilding the body-copy line list.

**Re-rendering the restore:** `esc()`, `href()`, `is_copy_field()`, `highlight_copy_value()`, and `render_body_copy_nested()` are nested *inside* `build_html_notes()` in `scripts/create_calendar_tasks.py` and cannot be imported. Replicate them and import only the module-level constants (`_COPY_FIELD_LABELS`, `_COPY_HIGHLIGHT_OPEN`/`_CLOSE`, `_numbered_section_copy_re`, `_category_block_cta_re`) so the markup matches what the real briefing path emits. Note `Value prop`, `Visual`, `Colorway`, and `Callout labels` are **not** in `_COPY_FIELD_LABELS` and so render unhighlighted — that is the code's actual behavior, not a bug to "fix" in a one-off restore.

Write back with `PUT /tasks/{gid}` and `data.html_notes`. **Leave Task Status untouched** — writing it re-triggers the native rule and can create duplicate Lacy copy subtasks (see the bulk-flip caution above).

### html_notes Format

Asana's `html_notes` rejects `<p>` and `<br>` tags (Bad Request) — but a literal newline between top-level fields works fine and is what production tasks actually use. Confirmed against a real Launched task ([CZ Pillow Pairings](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1213983392124795) — the reference "goal state" for what Claude successfully builds):

- **Header fields (Creative Direction / Promo / LP / Figma / SL/PH label) are bare `<strong>Label:</strong> value` lines directly under `<body>`, separated by real newlines — NOT wrapped in `<ul><li>`.** These structural labels stay bold; they are scaffolding, not AI-generated copy.
- **SL/PH values ARE wrapped in a `<ul><li>` pair**, with the AI-generated copy value highlighted (not bolded) using a yellow `<mark>` span — see "Highlight markup reference" below. The same highlight treatment applies to every other AI-generated copy field value in the brief (Body Copy HED/DEK/CTA/Eyebrow/etc., Kicker fields) — across every brand, including the standard 5-field format (BUR/ID/HAV/Trade). Only the field's *value* is highlighted; the `Label:` prefix stays plain, unbolded.
- **The Body Copy section is a nested `<ul>` of sibling blocks** — one `<li>Slice N — [name]</li>` immediately followed by its own `<ul><li>field: value</li>...</ul>` (siblings within the outer `<ul>`, not a child of the `<li>`). This is what actually renders as indented sub-bullets in Asana; cramming all of a slice's fields into one `<li>` with line breaks does not.
- **LP** gets wrapped in an `<a href="...">` anchor even though it's just the bare URL as link text (matches the Figma anchor pattern).
- **This highlight convention applies going forward only** — do not retrofit or manually re-highlight already-created/Launched tasks.

**Highlight markup reference:** every AI-generated copy value is wrapped in this exact `<mark>` span (matches Asana's native yellow highlighter, so auto-generated briefs render identically to a human manually highlighting text in Asana's UI). In the examples below, `<mark>...</mark>` is shorthand for this full wrapper:
```html
<mark data-highlight-color="yellow" style="background-color: #feedd9; background-color: var(--color-richtext-highlight-background, #feedd9)">...</mark>
```
Source of truth in code: `_COPY_HIGHLIGHT_OPEN`/`_COPY_HIGHLIGHT_CLOSE` and `highlight_copy_value()` in `scripts/create_calendar_tasks.py`.

**HAV designed email format — copy-first, slice-by-slice (as of 2026-07-29):** HAV joined CZ/STF/TI/BUR as a copy-first brand — `generate_hav_email_brief()` in `scripts/create_calendar_tasks.py` selects the Figma template, writes the creative direction, and generates numbered Slice N Body Copy, same convention as the other four brands (see [HAV (Havenly) Email Figma Templates](#hav-havenly-email-figma-templates) for the per-template field breakdown). This is a **briefing-only** switch — HAV designed emails still auto-build via the existing DnD-duplicator path at Ready to Code, not the HTML/CSS builder (HAV is not in `HTMLCSS_DESIGNED_CUTOFFS`; see [HTML/CSS Brand Migration](#htmlcss-brand-migration)).

**HAV sale banner rule (as of 2026-07-30):** unlike the original assumption that HAV designed emails fold sale messaging into the Hero copy, a HAV send during an active sale **does** get a dedicated Sale Banner slice — always exactly one slice position (`Slice 1`), never two stacked banner slices, even for a combined send:
- DPS-only send → `Slice 1 — Sale banner` → `https://havenly.com/#packages-section`
- MP-only send → `Slice 1 — Sale banner` → `https://havenly.com/shop/collection/sale`
- Combined "DPS and MP" send → still just `Slice 1 — Sale banner`, but audience-conditional: it lists both destinations as alternate versions of that one slot (`DPS: ... — Link: .../#packages-section` and `MP: ... — Link: .../shop/collection/sale`) — Braze/Liquid renders whichever matches the recipient's segment, since the send goes to one combined list, not two separate emails

The banner slice is prepended by code, not by the AI — `_hav_sale_banner_body_lines()` in `scripts/create_calendar_tasks.py` resolves the audience-appropriate link(s) from the task's `DPS:`/`MP:`/`DPS and MP:` name prefix, and `build_html_notes()`'s HAV branch renumbers the AI-generated Hero/Section slices by exactly 1 and bumps `Slices to deliver` by 1. `generate_hav_email_brief()`'s sale instruction no longer tells the AI to fold the sale into Hero copy — it only needs to know a banner will be added ahead of it.
```html
<body><strong>Creative Direction:</strong> One-line description of the email and offer.
<strong>Promo:</strong> [Sale name] — [discount] (omit entire line if no active sale)
<strong>LP:</strong> <a href="https://...">https://...</a>
<strong>Figma:</strong> <a href="[FIGMA_NODE_URL]">Template name</a>
<strong>SL/PH (AI generated):</strong>
<ul><li>SL: <mark>Subject line here</mark></li><li>PH: <mark>Preheader here</mark></li></ul>
<strong>Body Copy ([Template Name]):</strong>
<ul><li>Slices to deliver: N</li><li>Slice 1 — Hero</li><ul><li>HED: <mark>...</mark></li><li>DEK: <mark>...</mark></li><li>CTA: <mark>...</mark></li></ul><li>Slice 2 — Section 1</li><ul><li>HED: <mark>...</mark></li><li>DEK: <mark>...</mark></li></ul></ul>
<strong>Kicker:</strong> <a href="[FIGMA_NODE_URL]">Kicker name</a>
</body>
```
HAV emails have no Products field (design service, not shoppable) and no per-slice Link field — all sections point at the single top-level LP, except This or That, which always links to `https://havenly.com/exp/interior-design-ideas`. Slice count varies per template (fixed at 1 for Gif + Body / Why Havenly / AI; variable for Theme 01 / Style Feature / This or That — see the per-template field reference). The Kicker line only appears when a kicker is auto-attached (currently only the AI template, which always pairs with one) — kicker copy itself is static template chrome or a real testimonial a human sources, never AI-generated, so no kicker body copy is rendered. For PT emails (no Figma template — still the plain single-hero-block format, not yet migrated), omit the `PH:` line entirely per the SL/PH rules below.

**Standard 5-field format (all other email tasks):**
```html
<body><strong>Creative Direction:</strong> One-line creative direction here.
<strong>LP:</strong> <a href="https://...">https://...</a>
<strong>Figma:</strong> <a href="[FIGMA_NODE_URL]">Template name</a>
<strong>SL/PH (AI generated):</strong>
<ul><li>SL: <mark>Subject line here</mark></li><li>PH: <mark>Preheader here</mark></li></ul>
<strong>Body Copy ([Template Name]):</strong>
<ul><li>Slices to deliver: N</li><li>Slice 1 — [slice name]</li><ul><li>Field: <mark>value</mark></li><li>Link: https://...</li></ul><li>Slice 2 — [slice name]</li><ul><li>Field: <mark>value</mark></li><li>Link: https://...</li></ul></ul>
</body>
```
`Field:` is only highlighted when it's one of the copy-field labels (`_COPY_FIELD_LABELS` in `scripts/create_calendar_tasks.py` — HED, DEK, CTA, Eyebrow, Name, **Body**, etc.) or matches the numbered-field pattern (`_numbered_section_copy_re` — `Section N`/`Room N`/`Row N` followed by DEK/CTA/HED/Eyebrow/**Body**); structural fields like `Link:`, `Layout:`, and slice headers are never highlighted. **`Body` is copy needing review, same as HED/CTA** — confirmed 2026-07-30 (a prior gap left `Row N Body`/bare `Body` fields unhighlighted on ~20 of the BW Labor Day batch's 44 tasks; fixed in both label sets).

Do NOT include: Date, Content Pillar, Content Type, Format, Assets, Notes, or any other fields.

### SMS Brief Format

SMS task descriptions use the plain-text `notes` field (not `html_notes`) so that real line breaks work naturally. Always start with `[AI Brief]` on its own line — this is the truncation marker for the SMS builder and makes clear the content is AI-generated. Follow with `Direction` and `Proposed Copy (AI generated):` as sub-sections:

```
[AI Brief]
Direction: [one-line brief describing the send — angle, content, tone]

Proposed Copy (AI generated):
[Brand]: [copy text]:
[link]
```

**`Proposed Copy (AI generated):` is mandatory** — never use bare `Copy:` or `SMS Copy:`. The label must match exactly so it's clear the copy is AI-generated and not copywriter-approved.

If a note is needed (e.g. PROPOSED discount), add it after the proposed copy block:

```
[AI Brief]
Direction: [one-line brief]

Proposed Copy (AI generated):
[Brand]: [copy text]:
[link]

Discount is PROPOSED — confirm final offer before sending.
```

When calling `asana_update_task`, set the `notes` field (not `html_notes`) with actual newline characters.

### SMS Link Selection

Always resolve `[link]` to an actual URL in the proposed copy — never leave it as a placeholder. Rules:

1. **Verify the link returns HTTP 200** before including (use `curl -s -o /dev/null -w "%{http_code}" -L URL`).
2. **Pick from confirmed working links used in past campaigns** (grepped from `campaigns/html/`).
3. **Match the link to the copy context** — see per-brand maps below.

#### HAV (Havenly) Link Map

Default link differs by audience. When no specific link is provided in the brief, use:

| Audience | Default URL |
|----------|-------------|
| DPS / Pre-converted (PC) | `https://havenly.com/#packages-section` |
| Marketplace / Converted (CONV) | `https://havenly.com/shop` |

This is enforced automatically by `build_pt_campaign.py` via `_BRAND_BASE_URLS["HAV_PC"]` / `["HAV_CONV"]`.

#### ID (Interior Define) Link Map

These apply to all channels (email briefs, SMS, push). Use the most specific match; default to homepage for general sale sends.

| Context | URL |
|---------|-----|
| Sale launch / reminder / EA (any "X% off sitewide") | `https://www.interiordefine.com/` |
| Warehouse Sale (limited-stock/clearance warehouse markdowns) | `https://www.interiordefine.com/warehouse` |
| Swatch Talk / "request free swatches" | `https://swatches.interiordefine.com/` |
| New Arrivals | `https://www.interiordefine.com/new-arrivals` |
| Quick Ship | `https://www.interiordefine.com/quick-ship` |
| Named collection mentioned (Sloan, Ella, Alexander, James, Tatum, etc.) | `https://www.interiordefine.com/{collection-name}-collection?page=1` (e.g. `/sloan-collection?page=1`) — NOT `/{collection-name}`, which is a different page. Verify against `campaigns/html/` per the Link Sourcing Rule. |
| Sofas (general, no named collection) | `https://www.interiordefine.com/living/all-custom-sofas` |
| Sectionals | `https://www.interiordefine.com/living/all-custom-sectionals` |
| Chairs | `https://www.interiordefine.com/living/all-custom-chairs` |
| Beds | `https://www.interiordefine.com/bedroom/all-beds` |
| Dining | `https://www.interiordefine.com/dining` |
| Rugs | `https://www.interiordefine.com/rugs` |
| Leather | `https://www.interiordefine.com/collections/leather` |
| Store callout / studio visit | `https://www.interiordefine.com/locations` |

#### BUR (Burrow) Link Map

These apply to all channels (email briefs, SMS, push). Use the most specific match; default to homepage for general sale sends. Source of truth: `data/bur_links.yaml` — edit that file, not this table (both SMS via `build_sms_campaign.py` and email/PT briefing via `create_calendar_tasks.py` read from it at runtime; this table is a mirror for human reference).

| Context | URL |
|---------|-----|
| Sale launch / reminder / EA / final hours | `https://burrow.com/` |
| Pet-friendly / performance fabric | `https://burrow.com/pet-friendly-furniture` |
| Nomad collection | `https://burrow.com/collections/nomad` |
| Range collection | `https://burrow.com/collections/range` |
| Shift collection | `https://burrow.com/collections/shift` |
| Union collection | `https://burrow.com/collections/union` |
| Sleeper sofas | `https://burrow.com/collections/sleeper-sofas` |
| Sofas (general, no named collection) | `https://burrow.com/collections/shop-all-sofas` |
| Sectionals | `https://burrow.com/collections/sectionals` |
| Loveseats | `https://burrow.com/collections/loveseats` |
| Modular furniture | `https://burrow.com/collections/modular-furniture` |
| Seating (general category page) | `https://burrow.com/seating` |
| Chairs & Ottomans | `https://burrow.com/collections/chairs-ottomans` |
| Leather accent seating | `https://burrow.com/collections/leather-accent-seating` |
| Accent chairs | `https://burrow.com/collections/accent-chairs` |
| Coffee & side tables | `https://burrow.com/collections/coffee-side-tables` |
| Bookcases | `https://burrow.com/collections/bookcases` |
| Bedroom (general, no named product) | `https://burrow.com/bedroom` |
| Beds / bed frames | `https://burrow.com/collections/beds` |
| Dressers | `https://burrow.com/collections/dressers` |
| Nightstands | `https://burrow.com/collections/nightstands` |
| Mattresses | `https://burrow.com/collections/mattresses` |
| Desks | `https://burrow.com/collections/desks` |
| Dining (general room, no named product) | `https://burrow.com/dining` |
| Dining tables | `https://burrow.com/collections/dining-tables` |
| Dining chairs | `https://burrow.com/collections/dining-chairs` |
| Dining stools / counter stools / bar stools | `https://burrow.com/collections/dining-stools` |
| Bar carts / credenzas (dining context) | `https://burrow.com/collections/bar-carts-credenzas` |
| Ready to ship dining furniture | `https://burrow.com/collections/ready-to-ship-dining` |
| Rugs | `https://burrow.com/collections/rugs` |
| Outdoor | `https://burrow.com/outdoor` |
| Storage (general, no named product) | `https://burrow.com/storage` |
| Storage benches | `https://burrow.com/collections/storage-benches` |
| Credenzas & media storage (media consoles, entryway consoles) | `https://burrow.com/collections/credenzas-media-storage` |
| Wall shelves / storage cubes | `https://burrow.com/collections/wall-shelves` |
| Ready to ship storage | `https://burrow.com/collections/ready-to-ship-storage-shelving` |
| Quick Ship / ready to ship (general) | `https://burrow.com/ready-to-ship` |
| Warehouse / clearance (general) | `https://burrow.com/collections/clearance` |
| Clearance seating | `https://burrow.com/collections/clearance-seating` |
| Clearance outdoor | `https://burrow.com/collections/clearance-outdoor` |
| Clearance dining | `https://burrow.com/collections/clearance-dining` |
| Clearance storage | `https://burrow.com/collections/clearance-storage` |
| Clearance rugs | `https://burrow.com/collections/clearance-rugs` |
| Clearance pillows | `https://burrow.com/collections/clearance-pillows` |
| Best sellers | `https://burrow.com/collections/best-sellers` |
| Swatches | `https://burrow.com/swatches` |
| Leather seating (general, no dedicated collection page) | `https://burrow.com/seating` |
| Leather (no collection page, non-seating context) | `https://burrow.com/` |

**Confirmed broken — never suggest:** `https://burrow.com/living-room/seating/leather` returns 404. This URL is not a valid Burrow page under any circumstance. (Unrelated to the real `leather-accent-seating` collection above.)

#### TI (The Inside) Link Map

These apply to all channels (email briefs, SMS). Use the most specific match; default to homepage for general sale sends — **never** use `/collections/sale` as default for TI. Source of truth: `data/ti_links.yaml`'s `categories` + `product_categories` sections — edit that file, not this table. Unlike the other Klaviyo/Braze brands, TI SMS does **not** go through `build_sms_campaign.py`; its own builder (`scripts/create_klaviyo_sms.py`) has a separate loader (`_ti_default_links_from_yaml()`) that reads the same yaml and matches keywords against the campaign name (not the SMS copy), first-match-wins, sorted by keyword length so specific phrases are checked before generic ones. `destinations`/`edits`/`prints` (also in `data/ti_links.yaml`) are one-off seasonal editorial collections looked up by label, not keyword-matched — see that file for the full catalog.

| Context | URL |
|---------|-----|
| Sale / promo / event | `https://www.theinside.com/` |
| New Arrivals | `https://www.theinside.com/collections/new-arrivals` |
| Best Sellers | `https://www.theinside.com/collections/bestsellers` |
| Beds / bedroom | `https://www.theinside.com/c/bedroom-furniture/beds` |
| Headboards | `https://www.theinside.com/c/bedroom-furniture/headboards` |
| Bedroom benches | `https://www.theinside.com/c/bedroom-furniture/benches` |
| Sofas | `https://www.theinside.com/c/living-room-furniture/sofas` |
| Accent chairs | `https://www.theinside.com/c/living-room-furniture/chairs` |
| Ottomans | `https://www.theinside.com/c/living-room-furniture/ottomans` |
| Benches (living room) | `https://www.theinside.com/c/living-room-furniture/benches` |
| Curtains / drapes | `https://www.theinside.com/c/home-decor/curtains` |
| Throw pillows | `https://www.theinside.com/c/home-decor/throw-pillows` |
| Table linens | `https://www.theinside.com/c/home-decor/table-linens` |
| Dining chairs | `https://www.theinside.com/c/dining-room/dining-chairs` |
| Wallpaper | `https://www.theinside.com/c/home-decor/wallpaper` |
| Room dividers | `https://www.theinside.com/c/home-decor/room-dividers` |
| Outdoor furniture | `https://www.theinside.com/c/outdoor-furniture/outdoor` |
| Outdoor pillows | `https://www.theinside.com/c/outdoor-furniture/outdoor-pillows` |
| Cabana chairs | `https://www.theinside.com/c/outdoor-furniture/cabana-chairs` |
| Fabric by the yard | `https://www.theinside.com/c/fabric-by-the-yard/fabric-by-the-yard` |
| Bar & counter stools | `https://www.theinside.com/c/categories/bar-and-counter-stools` |
| Rugs | `https://www.theinside.com/collections/rugs` |
| Bedding / sheets | `https://www.theinside.com/collections/all-bedding` |
| Outdoor (general) | `https://www.theinside.com/collections/outdoorliving` |
| All furniture | `https://www.theinside.com/collections/furniture` |
| Fabric swatches | `https://www.theinside.com/fabric-swatches` |
| Trade program | `https://www.theinside.com/design-trade-services` |

#### STF (St. Frank) Link Map

These apply to all channels (email briefs, SMS). Source of truth: `data/stf_links.yaml` — edit that file, not this table. SMS link_paths are loaded from it automatically; email `STF_EMAIL_IDEAS` LPs reference it via `_STF_LP`.

**Bedding is banned as an auto-briefing topic — stock issue (flagged 2026-08-31).** STF has ongoing bedding stock issues. When generating/suggesting new STF content (calendar auto-briefing, self-generated slice-by-slice briefs, SL/PH ideation, etc.), never choose bedding as the topic, never feature Bedding as a category/product callout, and never default/fall back to the bedding link — including as a secondary mention inside a multi-category send (e.g. a General Edit or category grid). **This does not apply to a send a human has already manually briefed as bedding** — if an Asana task explicitly specifies bedding content, still resolve and use the correct `/collections/bedding` link when auto-building it; the `data/stf_links.yaml` entry is kept for exactly this case. This applies until the stock issue is confirmed resolved; revisit at that point rather than assuming it still applies indefinitely.

| Context | URL |
|---------|-----|
| Sale / promo / event | `https://www.stfrank.com/` |
| Best sellers | `https://www.stfrank.com/collections/best-seller` |
| New Arrivals | `https://www.stfrank.com/collections/new-arrivals` |
| Suzani / POTM / Print Spotlight | `https://www.stfrank.com/collections/suzani` |
| Kuba Cloth | `https://www.stfrank.com/collections/kuba-cloth` |
| Pillows | `https://www.stfrank.com/collections/pillows` |
| Outdoor Pillows | `https://www.stfrank.com/collections/outdoor-pillows` |
| Rugs | `https://www.stfrank.com/collections/rugs` |
| Wallpaper | `https://www.stfrank.com/collections/wallpaper` |
| Curtains / window treatments | `https://www.stfrank.com/collections/window-treatments` |
| Swatches | `https://www.stfrank.com/collections/swatches` |
| Surfboards | `https://www.stfrank.com/collections/surfboards` |
| Fabric by the Yard | `https://www.stfrank.com/collections/fabric-by-the-yard` |
| Outdoor Fabric | `https://www.stfrank.com/collections/outdoor-fabric` |
| Furniture / Studio By STF | `https://www.stfrank.com/collections/furniture` |
| Bedding | `https://www.stfrank.com/collections/bedding` — **do not auto-suggest this topic/link (stock issue, see note above); only use when a task is already manually briefed for bedding.** |
| Throws / quilts | `https://www.stfrank.com/collections/quilts-throws` |

### AI Brief Separator

All Asana task notes follow a two-section structure:
- **Top section** — copywriter-written content (SL, PH, body copy, signoff)
- **Bottom section** — AI-generated briefing instructions (creative direction, SL/PH suggestions, format notes, etc.)

Always separate these sections with `[AI Brief]` on its own line:

```
The Burrow Team


[AI Brief]
Format: Plain Text (PM send — conditional...)
SL/PH Suggestions (AI generated):
SL: ends in a few hours
PH: Last call on up to 50% off. Shop now.
Creative Direction: ...
```

This applies to **all brands and channels** (email PT, email designed, SMS, push). The `[AI Brief]` line serves as a hard boundary — the PT email builder uses it as a truncation marker so briefing metadata is never accidentally included in the email body.

For tasks that have no copywriter copy yet (empty brief), `[AI Brief]` still appears first, followed by the briefing instructions.

### SL/PH Suggestions Format

Always write exactly **1** paired SL + PH — not 2 options. Header must be:

```
SL/PH Suggestions (AI generated):
SL: [subject line]
PH: [preheader]
```

**Never use bare `Subject:` / `Preheader:` labels** for AI-generated suggestions — they look identical to copywriter-entered copy and create confusion during QA. The `(AI generated)` label is mandatory for every brand, every channel, every context. This includes manually-created task briefs, webhook-generated notes, and any other path where Claude writes SL/PH into an Asana task.

For **plain-text emails**, omit the `PH:` line entirely — PT emails have no preheader:

```
SL/PH Suggestions (AI generated):
SL: [subject line]
```

Run a compliance check before saving — verify character counts and case rules per brand (see Copy Standards).

### Product Links in Task Descriptions

Always include a direct product URL for every product recommended in any Asana task (all brands). Query the brand's Shopify PRODUCT table for the HANDLE column: `https://www.[brand-domain]/products/[handle]`.

- When multiple records exist for the same product, prefer the lower/older product ID (canonical listing) — **but verify it's actually live first.** Confirmed 2026-07-31: the canonical/oldest handle is sometimes 404 on the live site even though Snowflake still shows it `STATUS = 'ACTIVE'` (e.g. `nomad-sofa` is dead; only the newer `nomad-plus-sofa` listing is live). Always HTTP-check the candidate handle before using it — don't assume "oldest ID" alone means "live."
- **BUR "Product N" slices that show ONE specific product with a colorway/finish must link to that product's own page, with a `Fabric=`/`Wood Finish=` query param matching the exact colorway shown — never the generic `/collections/...` page.** Use `resolve_product_link(brand, product_title, colorway)` (`scripts/utils/inventory_checker.py`) to get this right — do not hand-build the URL or guess the handle/query value. It resolves every ACTIVE Shopify listing for that title, live-checks each handle over HTTP, and picks whichever live listing actually carries the requested colorway as a variant; if none do, it substitutes a real colorway that IS live and flags `"substituted": True` in its return dict — always surface that to a human before finalizing, the same way an unverified product name would be. Confirmed 2026-07-31 while fixing the BW Labor Day batch: several "Product N" slices linked to a generic collection page even though they named one specific product+colorway, and some of those colorways only existed on a *different* Shopify listing (a "Plus"-prefixed duplicate) than the one initially assumed. Encode the query value with `%20` for spaces, not `+` — the link passes through Braze's click-tracking redirect wrapper (and potentially further email-client link rewriting) before reaching the destination, and `+` is only guaranteed to decode as a space inside `application/x-www-form-urlencoded` content, not universally. This is a **post-generation step**, not something to bake into the AI-generation prompt itself — the prompt can't run Snowflake queries or live HTTP checks, so have the AI write the safe generic collection link as usual, then run `resolve_product_link()` afterward to upgrade it.
- **This rule applies to every single-product slice regardless of the template's name for it, not just slices literally named "Product N."** Confirmed bug 2026-07-30, BW "Last Chance — up to 35% off" (Multi Collection Spotlight V9, `mcs_v9`): all 4 "Product feature N" slices — Nomad Sofa, Range 3-Piece Sectional Lounger, Range Ottoman, and a nonexistent "Union Sleeper Sofa" (Union has no sleeper variant; swapped for the real "Span Sleeper Sofa") — linked to generic `/collections/...` pages instead of each product's own `/products/...` page, and one (Range Ottoman) linked to a completely mismatched collection (`/collections/shift`). The earlier "Product N" instruction in `build_bw_prompt()` never matched this naming, and `build_bw_prompt()`'s own Link-rules section told the model to "pick the best-matching product-category URL" for *all* category/product slices — actively causing the bug. Fixed in `build_bw_prompt()` (`scripts/create_calendar_tasks.py`): the product-slice instruction is now schema-driven off `Link: [product page]` in the template's own field list (matches "Product N", "Product feature N", "Spotlight N", any naming), and the model is told to write a literal `[NEEDS PRODUCT PAGE — resolve via resolve_product_link()]` placeholder rather than any collection URL, forcing the `resolve_product_link()` post-generation step. A new mechanical backstop, `_warn_generic_link_for_product_slice()`, is wired into `parse_bw_response()` right after `_warn_duplicate_products()`: it raises `SliceBriefValidationError` on any single-product slice (schema-detected, same mechanism as `_warn_duplicate_products()`) whose Link isn't a `/products/...` URL, so an un-resolved placeholder or a leftover collection link can no longer silently become an Asana task.
- **Same bug confirmed in `build_stf_prompt()` too (2026-08-01)** — identical "Product N"-only instruction plus an identical "Category / product slices: pick the best-matching product-category URL" Link-rules bullet, both fixed the same way (schema-driven placeholder instruction; STF's own `resolve_product_link("STF", ...)` post-generation step). `_warn_generic_link_for_product_slice()` is now also wired into `parse_stf_response()`, and `parse_cz_response()` was given the same backstop even though `build_cz_prompt()`'s Link rules were already structurally sound (it already prioritizes a real per-product URL catalog in `data/cz_links.yaml`, with collection fallback only when no product match exists) — defense-in-depth in case the model ignores that instruction. **`build_ti_prompt()` was checked and is a different, pre-existing situation, not the same bug**: several TI templates (`product_multi`, `product_single`) explicitly allow a "[product or collection LP]" either/or link by design, and TI has no Snowflake-backed product catalog or `resolve_product_link()` equivalent at all (Klaviyo brand, no inventory data — see "ID and TI briefs — inventory data unavailable" above), so TI genuinely cannot resolve a live per-product URL the way BUR/CZ/STF can; this is a standing limitation to revisit if TI ever gets its own inventory/product-URL source, not something to patch the same way.
- **Detection itself had a gap independent of the prompt bug**: the schema-driven single-product check only matched the literal substring `"product page"` in a slice's field text, silently missing other real phrasings already used in this file — `"product LP"` (STF Template 4/6) and `"product 1 page"`/`"product 2 page"` (BW `mcs_v2` and sibling paired-product templates). A slice using either phrasing was invisible to both `_warn_duplicate_products()` and `_warn_generic_link_for_product_slice()`, regardless of brand. Fixed via a shared `_is_strict_product_link_field(field_text)` helper: true when the field text mentions "product" and either "page" or "lp", and does **not** also mention "collection" (which excludes the intentional `"product/collection LP"` fallback field) — verified against every distinct `Link: [...]` field string in this file with no false positives/negatives. Both validators now call this helper instead of the narrow substring check.
- HAV uses Airbyte inventory (boolean availability, no handles) — product links not available via this method
- **Brand domains:** STF=`stfrank.com` · CZ=`the-citizenry.com` · BUR=`burrow.com`
- **Always verify stock before suggesting a product** — a handle lookup alone does not include inventory levels. Run `inventory_checker.py --brand [BRAND] --search "[product name]"` to confirm the product is available before including it in a brief. Do not suggest low- or zero-stock products.
- **CZ, STF, and BUR briefs — inventory check is mandatory, no exceptions.** Before including any product in a CZ, STF, or BUR Asana brief (auto-generated or manual), run `uv run python scripts/utils/inventory_checker.py --brand [CZ|STF|BUR] --search "[product name]"`. This applies even when the Asana task already specifies a product. Do not use Looker — use the Snowflake-backed inventory checker only.
  - **BUR: this is now automatic, not just a reminder.** `build_bw_prompt()` (`scripts/create_calendar_tasks.py`) calls `_get_bur_inventory_context()` by default whenever `inventory_context` isn't explicitly passed — it scans the record's story/notes for known collection names (`_BUR_KNOWN_COLLECTIONS`: Nomad, Range, Shift, Union, Field, Pro & Plus, Chorus, Gallery, Listo, Sonnet, Haiku Alto, Opera, Index, Dining Tables, Dining Chairs, Dining Stools) and pulls real in-stock products for any match via `get_collection_products()`, falling back to `get_top_stocked_products()` generally if nothing matches. This closes a real gap found 2026-07-31: the batch-generated briefs for ~44 BW Labor Day tasks invented plausible but nonexistent product model variants and finishes/colorways (e.g. "Shift Loveseat" — Shift is really just one Sleeper Sofa SKU; a 4th "Charcoal" finish for Opera Media Console, which only ships in Oak/Walnut/Blackened Oak) because no inventory was ever passed to the prompt. If Snowflake access fails, the prompt's "never invent products" instruction is strengthened instead of silently proceeding with no data (see `_get_bur_inventory_context()`'s docstring). CZ/STF's builders don't yet have this automatic behavior — they still rely on the caller remembering to pass `inventory_context` (or, for CZ, the create_asana_task()-level auto-injection that only fires through that specific — now legacy — code path). Worth porting the same auto-fetch pattern to `build_cz_prompt()`/`build_stf_prompt()` next time either is touched.
  - **Topic-word expansion for stories that don't name a collection verbatim.** `_BUR_TOPIC_EXPANSIONS` (`create_calendar_tasks.py`) maps a broad topic word (currently just `"dining"`) to its full set of real sub-collections, so a story like "dining and hosting essentials" still triggers a fetch of Dining Tables/Chairs/Stools inventory even though it never says "dining tables" verbatim. Without this, `_BUR_KNOWN_COLLECTIONS`'s substring match finds nothing and falls through to the generic top-stocked fallback — which is unit-volume-sorted and dominated by Nomad seating, so it will never surface a lower-stock category like dining tables (133 units) at all. Confirmed bug 2026-07-31 on "Hosting Highlight" (mcs_v5): with no real dining products in context, the AI followed the "use a general category name" fallback instruction literally and wrote the same "Dining Tables" category name + the same `/collections/dining-tables` link into all 4 of what should have been distinct "Product N" slices.
  - **"Product N" slices must never share a duplicated category name/link.** `build_bw_prompt()` now includes an explicit rule (right after the Product rules block) that any slice literally named "Product N" in a template — as opposed to a "Category feature"/"Category CTA" slice, which is genuinely allowed to be generic — must be a distinct, specific product with its own product-page link; if there aren't enough real products to fill every slot, the model should say so rather than repeat a placeholder across the remaining slices. This is the direct fix for the "Hosting Highlight" bug above, and is a companion to [[feedback_5050_pairing_rule]]'s `_enforce_5050_pairing()` — that catches an unpaired slice count, this catches a paired-but-duplicated grid where every slot technically exists but several are identical.
- **ID and TI briefs — inventory data unavailable.** ID Fivetran data is stale since Nov 2025; TI has no inventory data. When suggesting products for these brands, note in the brief: *"Inventory not verified — please confirm stock before send."*
- **No prices in briefs.** List products by name and URL only — do not include price or price range in product callouts (email briefs, SMS, slice-by-slice body copy, etc.), even when the inventory check surfaces one.

### Same-Day Email + SMS Consistency

When fixing or updating a link, sale name, or offer in any task, always pull same-brand same-date tasks and verify they match before closing out. Email and SMS on the same day are part of the same send moment.

### HAV Push Task Rules

| Scenario | Task name prefix | Notes |
|----------|-----------------|-------|
| Combined DPS + MP | "DPS and MP: [description]" | Category = Product/Category (look up GID on existing push task) |
| DPS only | "DPS: [description]" | Same |
| MP only | "MP: [description]" | Same |

Description format: start with "Proposed Copy (AI Generated):" followed by Title and Body. No Creative Direction field.

---

## SMS Campaign Build Rules

When building a Braze SMS campaign from an Asana task:

1. **Body copy** — always use the copy at the **top of the task description** (not Option 1/2 alternatives further down — those are reference drafts)
2. **Send time** — always use the **Send time custom field** (not any time mentioned in the notes body)
3. **`[link]` placeholder** — replace with the actual URL inline; do not leave as literal `[link]` in the sent message
4. **Strip campaign name line** — the notes often include the Braze campaign name (e.g. `P_SMS_2026_03_13_CZ_Bedding`) as a second paragraph for reference; strip it before sending
5. **First paragraph only** — only use copy from the first paragraph of the task notes (lines before the first blank line). Content separated by a blank line (e.g. a discount callout or writer's note on its own line below) is copywriter metadata, not part of the intended SMS copy.

In `build_sms_campaign.py`: (a) replace `[link]` with the resolved URL, (b) drop any trailing paragraph matching the campaign name pattern (`P_SMS_YYYY_MM_DD_...`), (c) only use the first paragraph from notes — content after the first blank line is copywriter notes/metadata and must be excluded.

## Product Inventory Data

Real-time product inventory is available for **BUR, CZ, STF, and HAV** via Snowflake. When anyone asks about product inventory, in-stock products, best sellers, or product availability — use this data directly.

**Not supported**: ID (Fivetran data stale since Nov 2025), TI (no data)

### Data Sources

| Brand | Source | Snowflake Location | Data Type |
|-------|--------|--------------------|-----------|
| **BUR** | Shopify via Fivetran | `FIVETRAN_DB.LANDING_BURROW_SHOPIFY` | Quantity (units) |
| **CZ** | Shopify via Fivetran | `FIVETRAN_DB.LANDING_CZ_SHOPIFY` | Quantity (units) |
| **STF** | Shopify via Fivetran | `FIVETRAN_DB.LANDING_STF_SHOPIFY` | Quantity (units) |
| **HAV** | Havenly Products via Airbyte | `AIRBYTE_DATABASE.LANDING_HAVENLY_PRODUCTS` | Boolean availability |

### How to Query Inventory

Use the CLI directly via Bash:

```bash
# Top in-stock products for a brand
uv run python scripts/utils/inventory_checker.py --brand BUR --limit 15

# Filter by category
uv run python scripts/utils/inventory_checker.py --brand CZ --category Pillows

# Check a specific product
uv run python scripts/utils/inventory_checker.py --brand BUR --search "Range Sofa"

# List all product categories
uv run python scripts/utils/inventory_checker.py --brand HAV --categories
```

Or use the Python API in scripts:

```python
from scripts.utils.inventory_checker import (
    get_top_stocked_products,
    check_product_availability,
    get_product_categories,
    format_inventory_for_prompt,
    SUPPORTED_BRANDS,  # {"BUR", "CZ", "STF", "HAV"}
)

products = get_top_stocked_products("BUR", limit=15)
print(format_inventory_for_prompt(products))

# Check specific product
result = check_product_availability("BUR", "Range Sofa")
# result.is_available, result.quantity_available, result.min_price, result.max_price

# Get categories
cats = get_product_categories("CZ")
```

### Data Notes
- Shopify data syncs daily; HAV availability syncs daily (modified within last 7 days)
- Shopify excludes spare parts, swatches, and items under $50 from top-stocked results
- HAV returns boolean availability (no unit count), grouped by product variant group
- Fivetran is being migrated to Airbyte — when complete, update database/schema in `inventory_checker.py`

## Revenue Attribution

**Source of truth: GA4 last-click** (`TRAFFIC_SESSION_PERFORMANCE_DAILY`, filtered by `SESSIONPRIMARYCHANNELGROUP` and `SESSIONCAMPAIGNNAME`). Do NOT use Braze `USERS_BEHAVIORS_PURCHASE_SHARED` with a time-window join — that over-attributes purchases to email and is not how the team measures revenue.

Pull `ECOMMERCEPURCHASES` and `TOTALREVENUE` from the appropriate GA4 table. For product-level breakdowns: `TRAFFIC_SESSION_PERFORMANCE_DAILY` is session-level only — no item-level GA4 table exists in any brand's schema.

**GA4 revenue availability by brand:**
- BUR, CZ, ID, HAV, STF, TI — GA4 available (see schemas below)
- **TE** — no GA4 revenue data (uses Stripe/HubSpot); note the gap explicitly when reporting TE performance

## Order Data Hygiene (all brands)

Two data-quality risks confirmed across multiple brands (2026-08-28) that will silently distort any order/revenue analysis — check for both before computing per-customer or per-order metrics (AOV, orders/user, revenue/user, A/B test guardrails, etc.), not just for ID.

**1. Internal/ops accounts inflate order & revenue totals — for per-customer analysis, not for aggregate reporting.** A shared Havenly Brands operations account (`orders@havenly.com`) is the single top-order-count "customer" in **every brand's order data checked** (2026-08-28): BUR (294 orders / $402,865, trailing 6mo), CZ (480 / $320,850), STF (52 / $22,930), ID (1,054 / ~$2.98M — sitting in ID's `Tax Exempt` customer group, not Trade/B2B, so the standard Trade/B2B filter doesn't catch it), and TI (670 / $365,432). HAV has its own set of internal accounts in the same class: `influencerorders@havenly.com` (32 orders / $50,992 — influencer seeding), `creativeteam@havenly.com` (18 / $109,383 — internal samples), and several individual `@havenly.com` employee addresses with $0 net revenue. Other brands' order data also carries `orders@<partner-domain>` addresses (`orders@minoanexperience.com`, `orders@the-citizenry.com`, `orders@interiordefine.com`, `orders@ashnyc.com`, `orders@violetmarsh.com`, `orders@theexpert.com`, `orders@platthome.us`) — wholesale/dropship/partner-fulfillment integrations, not consumers. Not yet checked: TE (no comparable Snowflake orders table — revenue lives in Stripe/HubSpot).

This is real revenue and real order volume — **do not strip it out of total company revenue, total order counts, or Trade-specific revenue rollups**, where it belongs. The risk is specific to **per-customer or per-user metrics** (AOV, orders/user, revenue/user, A/B test guardrails like the one in this section's example) — there, a single account can swing the whole comparison, and it should typically be excluded. **Before that kind of analysis, check the top 10–15 emails/accounts by order count for role-based or internal-looking addresses (`orders@`, `support@`, `wholesale@`, `customercare@`, an employee's own `@brand.com` address, etc.)** — don't assume a `CUSTOMER_GROUP`/`SALES_CHANNEL` filter alone catches them, since they can sit in an unexpected group (as with ID's `Tax Exempt` case).

**2. Don't assume you know whether a brand's Braze/Klaviyo user ID lines up with its warehouse customer ID — check it, because the answer differs by brand.** Spot-checked 2026-08-28, and the pattern is genuinely inconsistent across the portfolio:

| Brand | `EXTERNAL_USER_ID` format | Matches warehouse `CUSTOMER_ID` directly? |
|---|---|---|
| ID | `interiordefine-<n>` (looks numeric) | **No — silently wrong.** Spot-checked 5/5: same number, different person on each side (compared real emails). This is the dangerous case — it looks like it works. |
| BUR | UUID | No numeric join possible at all. |
| CZ | Long hex hash | No numeric join possible at all. |
| STF | Plain large integer | **Yes.** Tested at scale, not just a small sample: 5,000 random Braze users, 100% resolved to a real Shopify `CUSTOMER.ID`, 99.6% exact email match. The 0.4% that didn't match are explainable (email changed on one side after the fact, or a typo fixed later), not identity errors. `EXTERNAL_USER_ID` literally *is* the Shopify `CUSTOMER.ID` here. |
| HAV | Plain integer | **Yes.** Same 5,000-user test against `PROD.ANALYTICS.USERS_CLEAN.ID`: 100% coverage, 99.1% exact match. The disagreements are a HAV-specific artifact, not a join problem: the warehouse anonymizes deleted accounts to `<id>-deleted-customer@havenly.com`, so a since-deleted customer's Braze record (which still has their real email) will look like a "mismatch" against that placeholder — worth knowing if you ever use email agreement as a data-quality check here. |
| TI | Klaviyo profile ID (alphanumeric, not sequential) | Not empirically spot-checked, but structurally in the same category as BUR/CZ — no numeric join possible. |
| TE | Klaviyo profile ID | Not checked — no comparable warehouse table available. |

So the safe universal fallback is still **join on `LOWER(email)`** (verified working directly: ID ~89% match, CZ 5/5, BUR 7/8 ~88% — tested from real recent purchasers, not random subscribers, since most subscribers never purchase and would falsely look like non-matches). But for STF and HAV specifically, the numeric ID is *not* a trap — it's the correct, more precise join key (no casing/typo risk), verified at n=5,000 rather than a handful of spot-checks, and email can be used as a cross-check rather than the only option. **The general rule: verify per brand before trusting either a numeric-ID join or an email join — this portfolio has both a brand where the "obvious" numeric join is actively wrong (ID) and two where it's correct at scale (STF, HAV), so neither assumption is safe by default.** One casing note either way: HAV's warehouse email came back as `GOBUCKY@OUTLOOK.COM` (uppercase) against Braze's lowercase `gobucky@outlook.com` for the same person — always `LOWER()` both sides of an email join, never compare raw case.

## Snowflake GA4 Data

GA4 session/traffic data is available via the Snowflake MCP server. Connection uses key-pair auth configured in `.env`.

### GA4 Tables by Brand

| Brand | Schema | Table |
|-------|--------|-------|
| **BUR** | `LANDING_BURROW_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |
| **CZ** | `LANDING_CITIZENRY_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |
| **ID** | `LANDING_INTERIORDEFINE_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |
| **HAV** | `LANDING_HAVENLY_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |
| **STF** | `LANDING_ST_FRANK_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |
| **TI** | `LANDING_THE_INSIDE_GA4` | `TRAFFIC_SESSION_PERFORMANCE_DAILY` |

**Note**: Schema naming varies by brand (e.g., `LANDING_BURROW_GA4`, `LANDING_ST_FRANK_GA4`, `LANDING_THE_INSIDE_GA4`). All six use the same table format and core columns. Database is `AIRBYTE_DATABASE` (set via `SNOWFLAKE_DATABASE` env var). HAV, STF, and TI schemas were added 2026-04-16.

### Common Columns (all brands)
| Column | Type | Description |
|--------|------|-------------|
| `DATE` | TEXT | Date in **YYYYMMDD format** (e.g., `'20250115'`) — no dashes |
| `SESSIONS` | NUMBER | Total sessions |
| `ENGAGEDSESSIONS` | NUMBER | Engaged sessions |
| `ACTIVEUSERS` | NUMBER | Active users |
| `ECOMMERCEPURCHASES` | NUMBER | Purchase count |
| `ADDTOCARTS` | NUMBER | Add to cart events |
| `ITEMLISTVIEWEVENTS` | NUMBER | Item list views |
| `ITEMVIEWEVENTS` | NUMBER | Item detail views |
| `SESSIONSOURCEMEDIUM` | TEXT | Source/medium (e.g., "google / cpc") |
| `SESSIONCAMPAIGNNAME` | TEXT | Campaign name — used for email/SMS attribution matching |
| `SESSIONPRIMARYCHANNELGROUP` | TEXT | Channel group (e.g., "Email", "SMS") — matches GA4 UI |
| `TOTALREVENUE` | FLOAT | Total revenue |
| `USERENGAGEMENTDURATION` | FLOAT | Engagement duration |
| `STARTDATE`, `ENDDATE` | TEXT | Date range for the report |
| `PROPERTY_ID` | TEXT | GA4 property ID |

### Per-brand column notes
- `BOUNCERATE` (FLOAT) — present for BUR, CZ, ID, STF, TI; **not present for HAV**
- `KEYEVENTS:GENERATE_LEAD_SWATCH` (NUMBER) — present for **ID only**; channel-attributed swatch orders; added 2026-06-25. Note: GA4 connector has a 10-metric limit — this replaced `ITEMLISTVIEWEVENTS` in the ID report config.

**CZ GA4 channel grouping gap:** The CZ table only exports `SESSIONPRIMARYCHANNELGROUP` (GA4's default grouping). CZ's GA4 UI uses a custom channel grouping (slot 02) that classifies some sessions differently, causing a ~10% undercount in Snowflake vs GA4 Explorer (e.g. Mar 2–8: Snowflake 4,950 sessions / $10,868 vs GA4 Explorer 5,489 / $12,411). Use GA4 Explorer numbers as ground truth for the CZ weekly report and note the discrepancy. Fix: add `sessionCustomChannelGroupingSlot02` dimension to the Airbyte connector config for CZ GA4.

Connection configured in `.env` with key-pair auth (`SNOWFLAKE_PRIVATE_KEY_FILE`).

## Havenly Brands Analytics MCP

The `mcp__havenly-analytics__*` tools connect directly to Snowflake (PROD database). Use proactively for any data question — do not ask the user to pull numbers from Looker.

### Semantic Layer Brands (use `get_brand_catalog` / `suggest_query`)

- **burrow** → `PROD.ANALYTICS_BURROW` — orders, order_items, customers, products, inventory, item_availability, swatch_orders, quotes, retail_stores
- **citizenry** → `PROD.ANALYTICS_CITIZENRY` — orders, inventory, campaign_traffic, netsuite_catalog, swatch_orders
- **all_brands** → `PROD.ANALYTICS_ALL_BRANDS` — orders, customers, catalog_data, retail_calendar

### Raw SQL Brands (use `execute_query` directly)

- **STF** → `PROD.ANALYTICS_ST_FRANK` — orders (102K), order_items, products (8.9K), swatch_orders (18K), forecast_input_data
- **TI** → `PROD.ANALYTICS_THE_INSIDE` — orders (101K), products (130K), swatch_orders (40K), accounting
- **ID** → `PROD.ID_WAREHOUSE` — full DIM/FACT star schema: orders, order_items, customers, products, sessions (18M), web_pages (68M), HubSpot CRM (stg_deal, stg_contacts), swatch_order_items (8.2M)

### HAV → `PROD.ANALYTICS` (289-table platform schema)

No Looker connection exists — query `PROD.ANALYTICS` directly.

Key email tables: `EMAIL_EVENTS` (1.66B rows), `EMAIL_CAMPAIGN_STATUS` (1.03B), `BRAZE_EMAIL_EVENTS` (530M), `BRAZE_MASTER_CAMPAIGNS` (2,888 rows)
Key revenue tables: `TRANSACTIONS` (779K), `ORDER_SUMMARY` (345K), `MONTHLY_ACCOUNTING`
Key session tables: `SESSION_FACTS`, `MERCH_ORDER_SESSIONS`, `DESIGN_FEE_SESSIONS`

## Braze Raw Events Datashare (Snowflake)

Real-time, row-level Braze event data is available via Snowflake data shares. This is the most granular engagement data source — individual send/open/click events per user.

### Primary Datashare (BUR, HAV, CZ)

**Database:** `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206`
**Schema:** `DATALAKE_SHARING`
**Objects:** 224 VIEWs (not tables)
**Brands covered:** BUR, HAV, CZ
**Date range:** ~Jul 2024 – real-time (live data)

### TIER3 Datashare (ID, STF)

**Database:** `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF`
**Schema:** `DATALAKE_SHARING_TIERED`
**Brands covered:** ID, STF
**Date range:** ~Jul 2024 – real-time (live data)

### Brand → APP_GROUP_ID Mapping

| Brand | APP_GROUP_ID | APP_GROUP_API_ID | FROM_DOMAIN | Datashare |
|-------|-------------|-----------------|-------------|-----------|
| **BUR** | `67093a1f24ebbe0065cb9c77` | `8d95a484-0b57-4100-b44c-10303e1851ce` | em.burrow.com | Primary |
| **HAV** | `664223fb71bcf3005760dfc2` | `a9a8da97-4b45-460e-badd-d4a5e34d1329` | mail.havenly.com | Primary |
| **CZ** | `666672a4d8965b005ac6c1bd` | `115eea94-7fc7-455f-8dd0-694410625047` | mail.the-citizenry.com | Primary |
| **ID** | `6666726b459b5e0059d7d687` | — | — | TIER3 |
| **STF** | `666716b3858150005b566956` | — | — | TIER3 |

### Key Views

**View naming pattern:** `USERS_MESSAGES_[CHANNEL]_[EVENT]_SHARED`
The `_ALL` suffix variant includes all workspace data (use `_SHARED` to filter to your workspace via `APP_GROUP_ID`).

#### Email Events
| View | Key Extra Columns |
|------|-------------------|
| `USERS_MESSAGES_EMAIL_SEND_SHARED` | `ESP`, `FROM_DOMAIN`, `IP_POOL`, `MESSAGE_EXTRAS` |
| `USERS_MESSAGES_EMAIL_OPEN_SHARED` | `MACHINE_OPEN` (bool), `USER_AGENT`, `IS_AMP` |
| `USERS_MESSAGES_EMAIL_CLICK_SHARED` | `URL`, `LINK_ID`, `LINK_ALIAS`, `IS_SUSPECTED_BOT_CLICK`, `SUSPECTED_BOT_CLICK_REASON` |
| `USERS_MESSAGES_EMAIL_DELIVERY_SHARED` | `ESP`, `FROM_DOMAIN` |
| `USERS_MESSAGES_EMAIL_BOUNCE_SHARED` | `ESP`, `FROM_DOMAIN`, `SENDING_IP` |
| `USERS_MESSAGES_EMAIL_SOFTBOUNCE_SHARED` | `ESP`, `FROM_DOMAIN` |
| `USERS_MESSAGES_EMAIL_UNSUBSCRIBE_SHARED` | `ESP`, `FROM_DOMAIN` |
| `USERS_MESSAGES_EMAIL_MARKASSPAM_SHARED` | `ESP`, `FROM_DOMAIN` |

#### SMS Events
| View | Notes |
|------|-------|
| `USERS_MESSAGES_SMS_SEND_SHARED` | BUR + CZ only (HAV no SMS) |
| `USERS_MESSAGES_SMS_DELIVERY_SHARED` | — |
| `USERS_MESSAGES_SMS_SHORTLINKCLICK_SHARED` | — |

#### Behavior Events
| View | Notes |
|------|-------|
| `USERS_BEHAVIORS_PURCHASE_SHARED` | PRODUCT_ID, PRICE, CURRENCY — no direct CAMPAIGN_ID |
| `USERS_BEHAVIORS_CUSTOMEVENT_SHARED` | Custom event tracking |
| `USERS_BEHAVIORS_SUBSCRIPTIONGROUP_STATECHANGE_SHARED` | Sub/unsub group changes |

#### Reference/Lookup Views
| View | Purpose |
|------|---------|
| `CHANGELOGS_CAMPAIGN_SHARED` | Campaign name lookup: `NAME` (e.g. `P_EM_2026_02_27_HAV_PC_D_Web_AI`), `API_ID` (= `CAMPAIGN_API_ID` in event views), `CONVERSION_BEHAVIORS`, `ACTIONS` (message variation IDs). **⚠ Multiple rows per campaign** — each rename/save creates a new row. Always deduplicate to the most recent name: `QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1`. Without this, campaigns that were duplicated (Braze prefixes them "Copy of…") and later renamed will show the old "Copy_" name, and fan-out joins can silently double-count rows. |
| `CHANGELOGS_CANVAS_SHARED` | Canvas name lookup |
| `SNAPSHOTS_CAMPAIGN_MESSAGE_VARIATION_SHARED` | Message variation names |
| `USER_CUSTOM_ATTRIBUTES_VIEW_SHARED` | Current user attribute state |
| `USER_DEFAULT_ATTRIBUTES_VIEW_SHARED` | Current user default attributes |

### Common Columns (all email event views)
| Column | Type | Notes |
|--------|------|-------|
| `ID` | VARCHAR | Row UUID |
| `USER_ID` | VARCHAR | Braze internal user ID |
| `EXTERNAL_USER_ID` | VARCHAR | Your system's user ID |
| `APP_GROUP_ID` | VARCHAR | Workspace ID — use to filter by brand |
| `TIME` | NUMBER | Unix timestamp — use `TO_TIMESTAMP(TIME)` |
| `CAMPAIGN_ID` | VARCHAR | Braze internal campaign ID |
| `CAMPAIGN_API_ID` | VARCHAR | UUID — matches `CHANGELOGS_CAMPAIGN_SHARED.API_ID` |
| `CANVAS_ID` | VARCHAR | Braze internal canvas ID — set when event is from a Canvas, null for batch |
| `CANVAS_API_ID` | VARCHAR | UUID — matches `CHANGELOGS_CANVAS_SHARED.API_ID` and the Braze API's canvas `id`. Same internal-vs-API split as `CAMPAIGN_ID`/`CAMPAIGN_API_ID` above — **filter canvas queries on `CANVAS_API_ID`, not `CANVAS_ID`**, when starting from a canvas ID fetched via the Braze REST API (confirmed 2026-07-08: filtering on `CANVAS_ID` with an API-fetched UUID silently returns zero rows). `CANVAS_STEP_NAME` is available directly on send/event rows, no join needed. |
| `SF_CREATED_AT` | TIMESTAMP_LTZ | When event landed in Snowflake |

### Example Queries

```python
from scripts.snowflake_client import get_snowflake_client

DB = 'BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206'
SCHEMA = 'DATALAKE_SHARING'

# Get a client (schema required by SnowflakeClient, but queries use fully-qualified names)
client = get_snowflake_client(schema='DATALAKE_SHARING', database=DB)

# Sends + opens for BUR last 30 days
results = client.execute_query(f"""
    SELECT
        TO_DATE(TO_TIMESTAMP(s.TIME)) as send_date,
        c.NAME as campaign_name,
        COUNT(DISTINCT s.ID) as sends,
        COUNT(DISTINCT o.ID) as opens,
        COUNT(DISTINCT o.ID) / NULLIF(COUNT(DISTINCT s.ID), 0) as open_rate
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED s
    LEFT JOIN {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_OPEN_SHARED o
        ON s.DISPATCH_ID = o.DISPATCH_ID AND o.MACHINE_OPEN IS NOT TRUE
    LEFT JOIN {DB}.{SCHEMA}.CHANGELOGS_CAMPAIGN_SHARED c
        ON s.CAMPAIGN_API_ID = c.API_ID
    WHERE s.APP_GROUP_ID = '67093a1f24ebbe0065cb9c77'  -- BUR
      AND TO_TIMESTAMP(s.TIME) >= DATEADD('day', -30, CURRENT_TIMESTAMP())
    GROUP BY 1, 2
    ORDER BY 1 DESC
""")
```

### Important Notes
- Filter **machine opens** with `MACHINE_OPEN IS NOT TRUE` — the column is `NULL` for human opens, `TRUE` for machine opens (not `FALSE`)
- Filter **bot clicks** with `(IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = FALSE)` — the column is `NULL` for non-bot clicks in this datashare; `IS NOT TRUE` syntax is not supported by Snowflake
- `CAMPAIGN_API_ID` links events to campaign names via `CHANGELOGS_CAMPAIGN_SHARED` — always use a `QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1` subquery; a bare join returns multiple rows per campaign (one per save/rename) and will produce "Copy_…" names for campaigns that were duplicated then renamed
- `USERS_BEHAVIORS_PURCHASE_SHARED` has no `CAMPAIGN_ID` — attribute revenue by joining on `USER_ID + TIME` window
- The `_ALL` views skip the workspace filter (returns all brands together)
- **HAV does not use `USERS_BEHAVIORS_PURCHASE_SHARED`** — HAV is a design services platform; conversions are tracked as custom events (`product_list_viewed`, `Deep Link Opened`, `download_prop`, `Application Opened`) in `USERS_BEHAVIORS_CUSTOMEVENT_SHARED`. Use custom events for HAV conversion attribution.
- **Push views exist**: `USERS_MESSAGES_PUSHNOTIFICATION_SEND_SHARED`, `_OPEN_SHARED`, `_INFLUENCEDOPEN_SHARED`, `_BOUNCE_SHARED`, `_ABORT_SHARED`, `_IOSFOREGROUND_SHARED` (plus `_ALL` variants). HAV uses push; push opens bypass GA4 (app deep link).
- **Lifecycle canvas attribution**: To measure lifecycle performance including push → app paths (where click tracking is lost), join lifecycle send USER_IDs to `USERS_BEHAVIORS_CUSTOMEVENT_SHARED` within a time window. `CANVAS_ID IS NOT NULL` identifies lifecycle (triggered) sends vs batch.

## Braze Event & Canvas Anomaly Alerts

Slack alert (`#team-lifecycle`, same webhook as the Lee-completion alert below) when a watched Braze custom event or lifecycle canvas's first-email-step volume silently drops or stops firing — e.g. the ID `Order Completed` event not firing for Trade orders (see `reference_id_order_completed_event.md`).

**Script:** `scripts/braze_automation/monitor_braze_anomalies.py` · **Config:** `data/braze_anomaly_config.yaml` (per-brand watch-lists — see file header for schema) · **State:** `data/braze_anomaly_state.yaml` (dedup, one alert per key per calendar day)

```bash
uv run python scripts/braze_automation/monitor_braze_anomalies.py [--dry-run] [--brand ID]
```

**How it avoids false alarms:**
- **Datashare lag** — before evaluating anything, checks `MAX(SF_CREATED_AT)` on the relevant view. Data younger than 36h evaluates normally; 36–72h old is ordinary daily lag and is silently skipped (not reported as an anomaly); beyond 72h posts a distinct "datashare may be stale" warning instead of a volume-drop alert.
- **Partial "today"** — `get_daily_counts` in `scripts/utils/anomaly_detector.py` always excludes the current UTC calendar day from the series. Confirmed bug (2026-07-08): including it made every single check look like a ~70% volume drop regardless of brand/event, since "today" is necessarily a partial count (whatever fraction of the day has landed so far) compared against full historical days — the recent-window average was being computed against an in-progress day, not a real trailing window.
- **Sale ebb and flow** — the 4-week trailing baseline excludes any day matched by `sale_matcher.is_during_sale()`. A hard-zero check (nothing fired at all) is always active regardless of sale status; the percentage-drop-vs-baseline check is skipped when the recent window overlaps an active sale, since elevated (not depressed) variance is the expected sale effect.
- **Canvas step renames** — the "first email step" of a canvas (which may be T1, T2, etc. depending on whether SMS/push precedes it) is resolved dynamically every run via the Braze API (`resolve_first_email_step` in `scripts/utils/anomaly_detector.py`), never hardcoded — so step renames/reordering self-correct without a config update. `canvas/details`' `steps` array is NOT reliably in flow order for branched canvases (confirmed on a real ID canvas with `audience_paths`/`experiment_paths`), so resolution parses the org's `_T<n>_` sequence-number naming convention rather than trusting array order; falls back to array order only when no step carries a T-number. An optional `first_email_step_override` config field exists for canvases where even that picks the wrong step. Query the send view on `CANVAS_API_ID` (the UUID), not `CANVAS_ID` (Braze's internal ID) — see the datashare column notes above.

**Scheduling:** runs once daily via GitLab CI scheduled pipeline (`monitor-braze-anomalies` job in `.gitlab-ci.yml`, `PIPELINE_TYPE = braze_anomaly_alerts`, 1pm UTC), not a local LaunchAgent — chosen so the alert still fires when nobody's laptop happens to be on. The job commits the updated `data/braze_anomaly_state.yaml` back to `main` after each run so dedup persists across pipeline runs (fresh clone each time). Can also be run locally any time for testing: `uv run python scripts/braze_automation/monitor_braze_anomalies.py --dry-run`.

## Klaviyo Event/Metric Anomaly Alerts

Klaviyo counterpart to the Braze anomaly alerts above — same Slack channel, same underlying detection logic (`scripts/utils/anomaly_detector.py`'s `evaluate_series()`, unchanged), but for **TI and TE** (the two Klaviyo-only brands) instead of the 5 Braze brands.

**Script:** `scripts/monitor_klaviyo_anomalies.py` · **Config:** `data/klaviyo_anomaly_config.yaml` · **State:** `data/klaviyo_anomaly_state.yaml`

```bash
uv run python scripts/monitor_klaviyo_anomalies.py [--dry-run] [--brand TI]
```

**Key differences from the Braze version:**
- **No datashare, no freshness gate** — volume comes from Klaviyo's **Query Metric Aggregates API** (`POST /api/metric-aggregates`, `interval: "day"`, `measurements: ["count"]`), which is real-time, not a once-daily batch feed with lag. `KlaviyoClient.get_daily_counts()` (`scripts/utils/klaviyo_client.py`) wraps this — same `{"day": date, "cnt": int}` shape `get_daily_counts()` returns for Braze, so `evaluate_series()` needed zero changes.
- **Same "partial today" exclusion applies** — confirmed live (2026-07-09): a same-day bucket read mid-day showed roughly 1/3 of a normal day's volume purely because the day wasn't over yet. `get_daily_counts()` always excludes the current UTC day, same fix as the Braze version.
- **Metric-name landscape is messier than Braze's** — both TI and TE have multiple near-duplicate-sounding metrics from parallel/legacy integrations (e.g. TE has both `ADD_TO_CART_SHOWROOM` (235/30d) and `Showroom Add to Cart` (1,065/30d) live simultaneously; TI has a dead `Viewed Product` (0 events) alongside the real `ProductViewed`). Always verify a metric's actual 30-day volume before adding it to config — a name existing doesn't mean it's the live one.
- **TE has zero sale-schedule records** in `data/sale_schedules.yaml` — the sale-exclusion baseline logic is a silent no-op for TE until TE gets sale records added. The hard-zero tier still protects it regardless.
- **Swatch purchases aren't trackable here** — neither TI nor TE has a Klaviyo metric for swatch orders. TI's swatch order data lives only in `PROD.ANALYTICS_THE_INSIDE.swatch_orders` (Snowflake), not as a Klaviyo event.
- Rate limit for this specific endpoint is 60/min steady, 3/s burst — a separate bucket from the strict quota `campaign-values-reports` already fights over elsewhere in this repo, so no conflict with existing Klaviyo analytics jobs.

**Scheduling:** GitLab CI (`monitor-klaviyo-anomalies` job, `PIPELINE_TYPE = klaviyo_anomaly_alerts`, 1:15pm UTC — offset 15 min from the Braze job so the two don't race on the `git push` back to `main`).

## Monday Weekly Channel Report

**Trigger:** User asks for the weekly report / Monday report for any brand.

**Report:** Email + SMS combined performance for the **prior full week (Mon–Sun)**, with a 4-week trend and variance.

### Date Logic
- Report week = last Mon–Sun (e.g., run Mon 3/2 → report week is 2/23–3/1)
- 4W trend = rolling 4 weeks ending with the last day of the report week (3 prior weeks + current week), averaged per week
- Variance = `(current - trend) / trend × 100`, shown as +/- % relative — not percentage points

### Brands & Data Sources

| Brand | Data Source | Snowflake Table | Notes |
|-------|-------------|-----------------|-------|
| CZ | Snowflake GA4 | `LANDING_CITIZENRY_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` | Use GA4 Explorer as ground truth (see CZ gap note) |
| ID | Snowflake GA4 | `LANDING_INTERIORDEFINE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` | Includes Swatches row — use GA4 Explorer as ground truth for swatches (see ID gap note) |
| HAV | `PROD.ANALYTICS` | `SESSION_FACTS`, `MERCH_ORDER_SESSIONS`, `ORDER_SUMMARY`, `DESIGN_FEE_SESSIONS` | Email-only (no SMS) — see HAV query logic below |
| BUR | Snowflake GA4 | `LANDING_BURROW_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` | |
| TI | Snowflake GA4 | `LANDING_THE_INSIDE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` | Revenue tracking unreliable via GA4 (Klaviyo UTM attribution gap) |
| STF | Snowflake GA4 | `LANDING_ST_FRANK_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` | Revenue tracking unreliable via GA4 |

Channel filter for GA4 brands: `UPPER(SESSIONPRIMARYCHANNELGROUP) IN ('EMAIL', 'SMS')` · Date format: `YYYYMMDD`

### Brand Order

Always deliver brands in this sequence: **CZ → ID → HAV → BUR → TI → STF**

### Output Format

Share reports directly in the chat as markdown — do NOT create an Artifact.

**Standard row order (all GA4 brands):**

| Metric | [Week dates] | 4W Trend (avg/wk) | Variance to Trend |
|--------|--------------|-------------------|-------------------|
| Sessions | n | n | +/-% |
| % of Sessions | n% | n% | +/-% |
| Revenue | $n | $n | +/-% |
| % of Ecomm Revenue | n% | n% | +/-% |

**ID row order** (Swatches between % Sessions and Revenue):

| Metric | [Week dates] | 4W Trend (avg/wk) | Variance to Trend |
|--------|--------------|-------------------|-------------------|
| Sessions | n | n | +/-% |
| % of Sessions | n% | n% | +/-% |
| Swatches | n | n | +/-% |
| % of Site Swatches | n% | n% | +/-% |
| Revenue | $n | $n | +/-% |
| % of Ecomm Revenue | n% | n% | +/-% |

**HAV row order** (DPS Rooms before Revenue — primary conversion metric):

| Metric | [Week dates] | 4W Trend (avg/wk) | Variance to Trend |
|--------|--------------|-------------------|-------------------|
| Sessions | n | n | +/-% |
| % of Sessions | n% | n% | +/-% |
| DPS Rooms | n | n | +/-% |
| % of DPS Rooms | n% | n% | +/-% |
| Revenue | $n | $n | +/-% |
| % of Ecomm Revenue | n% | n% | +/-% |

Do NOT include the 4W weekly breakdown table — just the summary table and observations.

**ID-specific — Swatches:**
- Use `KEYEVENTS:GENERATE_LEAD_SWATCH` column from `LANDING_INTERIORDEFINE_GA4.TRAFFIC_SESSION_PERFORMANCE_DAILY` — channel-attributed email swatch counts
- Query: `SUM("KEYEVENTS:GENERATE_LEAD_SWATCH")` filtered to `UPPER(SESSIONPRIMARYCHANNELGROUP) = 'EMAIL'` for email swatches; omit filter for site-wide total
- **Snowflake undercounts vs GA4 Explorer** (confirmed 2026-06-29: Snowflake 61 vs GA4 72 for same Jun 22–28 window). Use GA4 Explorer as ground truth for the current-week figure. The 4W Snowflake trend is also understated — note the gap rather than treating it as reliable.
- For site-wide totals without channel breakdown, `LANDING_INTERIORDEFINE_GA4.CONVERSIONS_REPORT` also works (`EVENTNAME = 'generate_lead_swatch'`, use `TOTALUSERS`)

### Team Summary Message

After the table and observations, add a short team-facing summary:

> Sessions were [up/down X%] to the 4W trend — the [M/D Campaign Name] [email/SMS] drove the highest engagement for the week with [N] sessions.
> Revenue was [up/down X%] to the 4W trend — the [M/D Campaign Name] [email/SMS] drove the most revenue for the week with [$N].

To generate callouts: query `TRAFFIC_SESSION_PERFORMANCE_DAILY` (or `SESSION_FACTS` for HAV) grouped by campaign name for the report week, filtered to Email+SMS, sorted by sessions DESC and revenue DESC.

**Formatting campaign names for the summary:** strip type prefix, channel, date, brand, design codes — replace underscores with spaces, prepend M/D date.
Example: `P_EM_2026_02_16_ID_D_Presidents_Day_Sale_Sweetener_Reminder` → `2/16 Presidents Day Sale Sweetener Reminder email`

## HAV Monday Weekly Report — Query Logic

HAV weekly report uses **`PROD.ANALYTICS`** (not GA4 — no HAV GA4 schema in AIRBYTE_DATABASE). See MEMORY.md for the full report output format and 4W trend structure.

### Tables

| Metric | Table | Key Filter |
|--------|-------|-----------|
| Sessions | `SESSION_FACTS` | `TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')` |
| Revenue | `MERCH_ORDER_SESSIONS` → `ORDER_SUMMARY` | `TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')` on MOS |
| DPS Rooms | `DESIGN_FEE_SESSIONS` → `SESSION_FACTS` | `TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')` on DFS |

### Critical Filters

- **Email traffic source was renamed `Havenly Emails` → `Owned Email` on 2026-07-10** — always match **both** names with `TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')`, on all three tables (`SESSION_FACTS`, `MERCH_ORDER_SESSIONS`, `DESIGN_FEE_SESSIONS` — the rename propagated to all of them). The cutover was clean and same-day: Jul 9 = 717 sessions on the old name / 2 on the new; Jul 10 = 0 / 482. Filtering on `'Havenly Emails'` alone returns **zero** email sessions, revenue, and DPS rooms for any week after Jul 9 — silently, with no error. Matching both names is required for historical weeks and for any 4W trend spanning the boundary. `Partner Emails` was NOT renamed and remains a separate source — do not fold it into the email filter.
- **Bot filter**: `(DEVICE != 'bot' OR DEVICE IS NULL)` — NOT just `DEVICE != 'bot'`. SQL excludes NULLs with `!=`; Looker's "device is not bot" keeps NULL rows (~8-9K sessions/week). This filter is load-bearing: HAV was hit by sustained bot attacks on **Jul 15–28** and **Aug 9–16+, 2026** (peaks ~39K bot sessions/day vs a ~100–300/day baseline, all attributed to `Direct`). The bots were correctly classified `DEVICE = 'bot'`, so this filter already excludes them and no past report needs restating — but any query that omits it will show a 2–4× session spike on those dates.
- **Revenue**: use `ORDER_SUMMARY.NET_ORDER_REVENUE` via `MERCH_ORDER_SESSIONS` — NOT `ORDER_PRODUCT_ATTRIBUTIONS` (OPA sums per product line, not per order)
- **Timezone**: `SESSION_START` is UTC; Looker uses Mountain Time (UTC-7). Mon 00:00 MT = Mon 07:00 UTC. Use `>= '[monday] 07:00:00' AND < '[next_monday] 07:00:00'`
- **4W grouping**: `DATE_TRUNC('week', DATEADD('hour', -7, SESSION_START))`
- **HAV has no SMS** — email-only report

### Revenue Join Pattern
```sql
FROM PROD.ANALYTICS.MERCH_ORDER_SESSIONS mos
JOIN PROD.ANALYTICS.SESSION_FACTS sf ON mos.SESSION_ID = sf.SESSION_ID
JOIN PROD.ANALYTICS.ORDER_SUMMARY os ON mos.ORDER_ID = os.ORDER_ID
WHERE mos.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
  AND (sf.DEVICE != 'bot' OR sf.DEVICE IS NULL)
  AND sf.SESSION_START >= '[monday] 07:00:00' AND sf.SESSION_START < '[next_monday] 07:00:00'
```

### DPS Join Pattern
```sql
FROM PROD.ANALYTICS.DESIGN_FEE_SESSIONS dfs
JOIN PROD.ANALYTICS.SESSION_FACTS sf ON dfs.SESSION_ID = sf.SESSION_ID
WHERE dfs.TRAFFIC_SOURCE IN ('Havenly Emails', 'Owned Email')
  AND (sf.DEVICE != 'bot' OR sf.DEVICE IS NULL)
-- Use COUNT(DISTINCT dfs.ROOM_ID) for room count
```

The evergreen `OT_EM_2024_08_HAV_CONV_New_Messages_Notification` typically tops the session list — flag it as automated; highlight the top one-time batch send separately in observations.

---

## HAV (Havenly) Email Figma Templates

File key: `CgGj7mTdp9SSj975u2mP4F` — [Havenly Lifecycle Templates](https://www.figma.com/design/CgGj7mTdp9SSj975u2mP4F/Havenly-Lifecycle-Templates)
URL format: `?node-id=[NODE_ID_HYPHENATED]&m=dev` — templates auto-selected by `generate_hav_email_brief()` (non-Trade HAV email tasks), same copy-first pattern as CZ/STF/TI/BUR.

**Sections to use for Asana briefing:** Core Designs + Kickers & Footers only.
**Ignore:** Color & Font, Buttons and Icons, Trade sections.
**Blog Feature template is excluded** — Havenly is moving away from Hideaway branding.

### Core Designs

| Key | Template | Node ID | Use Cases |
|-----|----------|---------|-----------|
| `theme_01` | Theme 01 | 12:312 | Editorial, newsletter, blog post, seasonal, trend roundup, general |
| `gif_body` | Gif + Body | 7:36 | Before & After, blog editorial, GIF animation, room transformation |
| `style_feature` | Style Feature | 12:920 | Style feature, moodboard, curated look, earth tones, product spotlight |
| `this_or_that` | This or That | 14:76 | Interactive voting format — subscribers choose between two styles |
| `why_havenly` | Why Havenly | 15:211 | Why Havenly / How It Works, brand value prop — especially DPS |
| `ai` | AI | 44:55 | Havenly AI feature emails; also hero-only sends with kicker attached |

### Kickers & Footers (optional add-ons)

| Key | Kicker | Node ID | Best For | Audiences |
|-----|--------|---------|----------|-----------|
| `5_stars` | 5 Stars 01 | 15:212 | Testimonials, social proof | DPS + MP |
| `categories` | Categories | 17:384 | Shop-by-category grid, sale emails | MP |
| `b_partners` | B. Partners | 17:402 | Brand partners block | MP |
| `dps_kicker` | DPS Kicker | 9:240 | Design service CTA footer | DPS |
| `mp_kicker` | MP Kicker | 9:244 | Marketplace browse CTA footer | MP |
| `havenly_ai` | Havenly AI | 18:688 | Cross-promote AI feature | DPS + MP |
| `value_prop_dps` | HAV Value Prop DPS | 20:1037 | DPS value prop / onboarding | DPS |
| `5_stars_02` | 5 Stars 02 | 15:233 | Testimonials, social proof (alt layout) | DPS + MP |
| `value_prop_mp` | HAV Value Prop MP | 18:565 | MP value prop — price match, single checkout | MP |
| `havenly_ai_b` | B. Havenly AI | 7:55 | Cross-promote AI feature (alt layout, Free Download CTA) | DPS + MP |
| `a_partners` | A. Partners | 20:1118 | Cross-brand partner product callouts w/ pricing | MP |
| `c_partners` | C. Partners | 21:10 | Brand partners block (alt grid layout) | MP |
| `design_package_b` | B. Design Package | 16:255 | Single design-package CTA | DPS |
| `design_packages_a` | A. Design Packages | 22:135 | Online vs. In-Person pricing comparison | DPS |
| `tier_sale` | Tier Sale | 171:9 | Tiered discount callout (spend-more-save-more sales) | DPS + MP |

### Template Selection Guidance

| Email type | Template |
|-----------|---------|
| Editorial / newsletter / blog post | Theme 01 |
| Before & After / room transformation | Gif + Body |
| Style guide / moodboard / earth tones | Style Feature |
| This or That interactive | This or That |
| Why Havenly / How It Works | Why Havenly |
| Havenly AI feature | AI |
| Hero-only announcement / launch | AI (+ kicker) |

**Kicker pairing rules:**
- Most emails stand alone — do not add a kicker by default
- `ai` template (hero-only) → **always** attach a kicker; use `dps_kicker` for DPS, `5_stars` for MP or combined
- Other kickers are optional add-ons for specific scenarios (e.g. `categories` on a sale email, `havenly_ai` to cross-promote the feature, `5_stars` to add social proof)
- `why_havenly` already has a value-prop grid and a 5-star testimonial baked into the template itself (same content as `value_prop_dps` + `5_stars`) — do **not** additionally attach either of those two kickers to a `why_havenly` send, it would be a duplicate

### Template & Kicker Field Reference (confirmed with Mina, 2026-07-13; wired into code 2026-07-29)

Field-by-field breakdown per template/kicker, for writing the "Body Copy" section of a HAV brief. Use the **same "Slices to deliver: N" + numbered "Slice N — [name]" convention as CZ/STF** (see html_notes Format above) — HAV templates are single hero/editorial blocks rather than shoppable product grids, but the brief structure stays consistent across brands. Every template's Hero slice includes Logo as a field (not called out per-template below since it's constant).

**Source of truth is now `HAV_FIGMA_TEMPLATES` in `scripts/create_calendar_tasks.py`** (`slices` + `repeatable_section` keys per template, ported from this section) — `generate_hav_email_brief()` reads it to select the template, write a 1-sentence direction, and generate the numbered slice body copy; edit the dict, not just this prose, when the structure changes. `HAV_FIGMA_KICKERS` was NOT given slice/field data — kickers stay reference-only for content (HED/CTA values are static template chrome, or a real testimonial a human sources, never AI-generated); only the mandatory AI-template kicker pairing (`dps_kicker` / `5_stars`) is auto-attached (name + Figma link only, no body copy), and every other kicker is a manual/designer add-on, same as CZ/STF/BUR's optional kickers.

**Theme 01** (`12:312`) — editorial/newsletter. Slice count varies per email — however many sections the designer/brief calls for:
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA
- Slice 2+ — Section N (full width): HED, DEK — repeat per section, one slice each

**Gif + Body** (`7:36`) — Before & After / room transformation. Always 1 slice:
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA

**Style Feature** (`12:920`) — style guide/moodboard. Slice count varies per email — however many sections the designer/brief calls for:
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA
- Slice 2+ — Section N (full width): HED, CTA — repeat per section, one slice each (no DEK on sections, unlike Theme 01)

**This or That** (`14:76`) — interactive voting. Slice count varies per email — however many sections/rounds the designer/brief calls for; each section = **2 slices** (50/50 pair, not one slice):
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA
- Each section gets its own group label line — `Section N — [category]` (e.g. "Section 1 — Accent Walls") — sitting above its pair of slices, same pattern as STF Template 6's "Section N" headers
- Slice 2 — Section 1, Option A (50/50 left): HED (category, e.g. "Accent Walls"), Visual (image description), Label (text pill, e.g. "Muted Walls")
- Slice 3 — Section 1, Option B (50/50 right): Visual, Label — no HED (already stated on the left slice)
- Repeat per additional section (its own "Section N — [category]" label + 2 more slices) — e.g. 3 sections = 7 slices total (1 hero + 3×2 option slices); 4 sections = 9 slices
- Both options in every section share the same Link — per the standing This or That LP rule, always `https://havenly.com/exp/interior-design-ideas`

**Why Havenly** (`15:211`) — brand value prop / DPS education. Always 1 slice — the Value Prop grid and testimonial below the hero are static template chrome, not brief-driven content, and do NOT get their own slice entries:
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA

**AI / Hero Only** (`44:55`) — hero-only announcement. Always 1 slice:
- Slice 1 — Hero (full width): Logo, HED, DEK, CTA. Background/phone-mockup imagery is illustrative only, not a required field — Visual can be whatever the brief calls for.
- Always pair with a kicker (`dps_kicker` for DPS, `5_stars` for MP/combined) per the pairing rule above

**Kickers:**

| Kicker | Fields |
|---|---|
| `5_stars` / `5_stars_02` | HED ("Over 200,000 Happy Clients Can't Be Wrong"), 5-star testimonial quote + customer name |
| `categories` | HED ("Shop the sale by category"), 4x category button (label is swappable per send, e.g. Dining Room / Living Room / Bedroom / Decor) |
| `b_partners` | HED ("Shop more deals from our partner brands"), 5x partner brand photo tile (Interior Define, The Citizenry, Burrow, The Inside, St. Frank) |
| `dps_kicker` | HED ("Design Your Dream Home"), CTA ("Work With a Designer") |
| `mp_kicker` | HED ("Find the Perfect Piece"), CTA ("Shop Now") |
| `havenly_ai` | HED ("Havenly AI"), DEK, CTA ("Get Started for Free"), phone mockup image |
| `value_prop_dps` | HED ("The #1 Interior Design Service"), 4x icon + short text value props, underlined CTA link, "Get Started" button |
| `value_prop_mp` | HED ("It Pays to Shop with Havenly"), 4x icon + short text value props (Get the best deal / Save time / Avoid hassle / Support your designer) — no CTA button |
| `havenly_ai_b` | HED (2-line, e.g. "The Best AI for Interior Design..."), CTA ("Free Download"), 2-column feature block — each column: sub-HED, DEK, phone screenshot, design caption |
| `a_partners` | HED ("Our Partner Brands"), sub-HED ("Bestsellers"), 5x partner product tile: brand logo, product name, price (struck-through + sale), CTA ("Shop Now") — one named product per brand (Interior Define, The Citizenry, Burrow, The Inside, St. Frank) |
| `c_partners` | HED ("Shop more deals from our partners"), 6x brand photo tile with brand-name overlay (Interior Define, St. Frank, The Inside, Burrow, The Citizenry, Havenly) — no per-tile CTA |
| `design_package_b` | HED ("Design Services Starting at $99"), DEK, CTA ("Buy Now") |
| `design_packages_a` | 2 side-by-side pricing cards — "Online Design" ($199→$99.50) and "In-Person Design" ($699→$349.50), each with DEK + CTA ("Buy Now") |
| `tier_sale` | HED ("Buy More Save More"), 3x tiered discount line (e.g. 15% Off $2500+ / 10% Off $1250+ / 5% Off $750+), bonus line (e.g. "+ Extra 5% Off Only at Havenly"), CTA ("Shop Now"), fine print ("Some exclusions apply") |

---

## Burrow (BW) Email Figma Templates

File key: `iOd6uooBKdfJGHboJ8wLvJ` — [Burrow Email CRM Templates](https://www.figma.com/design/iOd6uooBKdfJGHboJ8wLvJ/Burrow-Email-CRM-Templates)
URL format: `?node-id=[NODE_ID_HYPHENATED]` — templates auto-selected by `generate_bw_email_brief()` (non-Trade BUR email tasks) via Claude Haiku, same pattern as CZ/STF/TI. `pick_bw_template()` remains as a template-pick-only fallback, no longer used in the main BUR briefing path.

Full catalog (Collection Spotlight V1–V7, Multi Collection V1–V14, Other families): `docs/figma-templates.md#burrow-bw-email-figma-templates`

All named BW email templates — Collection Spotlight V1–V7, Multi Collection Spotlight V1–V14, Fabric / Multi Fabric Spotlight, Quick Ship, Best Sellers, and Retail Event — have structured `slices` in `BW_FIGMA_TEMPLATES` (`scripts/create_calendar_tasks.py`), ported from the slice-by-slice brief structures documented at `docs/figma-templates.md` and wired into `generate_bw_email_brief()` as of 2026-07-29 — BW briefs now emit numbered slice-by-slice Body Copy, same as CZ/STF/TI. Unlike CZ/STF, Burrow has **no separate sale-banner slice** — sale messaging is baked inline into hero/kicker copy per Burrow's existing convention, so `generate_bw_email_brief()` never prepends or renumbers a banner slice. The 3 reusable kicker modules (BUR Partner Blocks, Category Lifestyle Block, Category Footer Block) remain **reference only** in `BW_KICKERS` — not auto-cycled into briefs, same as STF's `STF_KICKERS`.

---

## STF Consumer Email Figma Templates 2026

File key: `Bnne2c9xMqh3fiUp3VfLIM` — [St. Frank Templates 2026 — Templates Updated page](https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2&p=f&m=dev)
URL format: `?node-id=[NODE_ID_HYPHENATED]&m=dev` (always include `&m=dev`)

**Always use the "Templates Updated" page (node `252:2`). Do NOT use the old "Templates" page — it is outdated.**

### Templates

| Section | Template | Node ID | When to Use |
|---------|----------|---------|-------------|
| **Studio By STF** | Template 1 | 252:96 | Long editorial: hero + copy + photo collage grid + Shop More Styles kicker |
| | Template 2 | 252:164 | Shorter: hero + Explore Swatches callout + Shop More Styles kicker |
| **Print/Pattern Edits** | Template 3 | 252:854 | Color edit — palette swatches + product grid |
| | Template 4 | 252:1038 | Print of the Month — featured print hero + product variants |
| | Template 5 | 252:1229 | Pattern Drenching — full-bleed bold pattern image |
| **Moodboards, Lookbooks, Mosaics** | Template 11 | 252:1439 | Seasonal moodboard — big typographic name + lifestyle collage grid + category links |
| | Template 12 | 252:1611 | Lookbook / seasonal launch — hero image + date callout |
| **Product Features and Design Edits** | Template 6 | 252:2035 | Outdoor/lifestyle feature — hero + product grid (pillows + fabric) + kicker |
| | Template 7 | 252:2283 | Sale hero / last chance — single hero image + CTA only |
| | Template 8 | 252:2386 | Trends / seasonal edit — 3 named trends each with photo + copy + CTA, plus category grid |
| **UGC** | Template 9 | 252:427 | "Styled By You" — hero + UGC photo grid with Instagram handles |
| **Destinations** | Template 10 | 252:2654 | Destination editorial — multi-section journey (Lake Como) with product category links |
| **Back in Stock** | Template 13 | 252:2783 | Hero-only back in stock announcement |

### Kickers and Category Blocks (optional add-ons)

| Block | Node ID | When to Use |
|-------|---------|-------------|
| Swatch Kicker 1 | 252:2473 | Any email with swatch callout — "Explore Swatches" minimal |
| Category Block 1 | 252:2484 | Any email, especially shorter sends — "Shop More Styles" stacked text links |
| Category Block 2 | 252:2514 | Sale emails only — "X% Off Sitewide" 6-cell product category grid |
| Category Block 3 | 252:2552 | Any email, especially shorter or single-category sends — "Shop More Styles" 2×2 photo grid |
| Swatch Kicker 2 | 252:2571 | Any email featuring swatches — "Explore Swatches" with lifestyle image |
| Edit Kicker 1 | 252:2594 | Holiday/seasonal emails — "Tis the Season" edit kicker |
| Category Block 4 | 252:2603 | Sale reminders — "Up to X% Off" 6-photo category mosaic |
| Category Block 5 | 252:2620 | Seasonal/holiday emails — alternative 'Tis the Season kicker |

### STF Email Slice Structure — confirmed field-by-field

**Now auto-emitted (as of 2026-07-20).** STF designed-email Asana briefs are generated slice-by-slice automatically, exactly like CZ and TI: the 13 templates are encoded with structured `slices` (name/type/`layout`/fields) in `STF_FIGMA_TEMPLATES` (`scripts/create_calendar_tasks.py`), and `generate_stf_email_brief()` selects the template, writes the direction, and emits a numbered "Body Copy" section via the shared `render_body_copy_nested()` renderer. Every slice carries a canonical `Layout:` line (`Full width` / `50/50 left` / `50/50 right`) enforced deterministically by `_stf_inject_layouts()` — not left to the model. **A `50/50 left` slice must always have a matching `50/50 right`** — `_enforce_5050_pairing()` (called right after `_stf_inject_layouts()` in both `parse_stf_response()` and `parse_bw_response()`) checks the left/right count after parsing and, if unequal, drops the last slice on the majority side, renumbers subsequent slices, and prints a warning. This is a mechanical safety net only — when it fires, manually confirm the right item was dropped (e.g. against real sales/inventory data) rather than trusting the auto-drop blindly.

**This same pairing check also runs for CZ** — `parse_cz_response()` calls `_enforce_5050_pairing()` too (as of 2026-07-31, per "the 50/50 pairing enforcement should apply across all brands with designed emails that get auto-built"). CZ has no dedicated `Layout:` field line the way STF/BW do — its 50/50 status is a suffix on the slice name itself (e.g. `Slice 2 — Product Image 1 — 50/50 left [IMAGE]`, per `CZ_FIGMA_TEMPLATES`' naming convention), so `_enforce_5050_pairing()` also checks the slice header text for a `— 50/50 left`/`— 50/50 right` suffix (`_5050_header_suffix_re`) and uses that as the layout value when present. This value is authoritative and is never overwritten by a subsequent `Layout:` line — CZ's own field instructions ask for an additional, wordier `Layout: 50/50 (paired with Product Image 2 in the same row)` line alongside the header suffix, which doesn't match either literal "50/50 left"/"50/50 right" string; letting it override the header-detected value would silently break the check for CZ. STF/BW headers never carry a suffix, so their existing behavior (Layout: line is the only source) is unchanged.

**Not yet extended to HAV — scoped deliberately, not an oversight:** HAV designed emails are briefing-only (see [HAV Copy-First Switch](#hav-copy-first-switch) below) — they still route through the DnD-duplicator path in Braze, built by a human from the Asana brief, not assembled by code the way CZ/STF/BUR (HTML/CSS builder) or TI (Klaviyo builder) are. "Designed emails that get auto-built" therefore doesn't include HAV under the current pipeline; revisit if HAV ever moves onto a code-driven builder.

**Every single-item slice in a repeatable grid must also be distinct — this is a hard failure, not a warning (as of 2026-08-01).** `_warn_duplicate_products()` (called right after `_enforce_5050_pairing()` in `parse_stf_response()`, `parse_bw_response()`, and `parse_cz_response()`) raises `SliceBriefValidationError` if two single-item slices in the same body copy share an identical Name or Link (e.g. two slots both named "Field Ottoman," or several distinct products/categories all pointing at the same `/collections/...` URL instead of their own page). There's still no safe mechanical *fix* (picking a genuinely different real product needs live inventory data this function doesn't have) — but "can't auto-fix" is not the same as "must only warn": every violation is printed as `[ERROR]`, then raised, so the brief cannot silently become an Asana task. **Do not catch `SliceBriefValidationError` and fall back to creating/updating the task anyway** — regenerate the completion addressing the message and re-parse. Both prompts (`build_bw_prompt()`, `build_stf_prompt()`) also carry an explicit instruction against this pattern to reduce how often the error fires at all.

**Detection is schema-driven, not name-pattern-driven, and covers both products and categories (as of 2026-08-01)** — `_warn_duplicate_products()` takes the resolved template's `slices` list and treats ANY slice whose field list declares a `Link:` field mentioning "product page" or "category" as a single-item slot, regardless of what the slice is named. This replaced an earlier version that only matched slice names literally starting with `Product ` (or `Section N Product N`), which silently missed BUR "Leather Highlight"'s `fab_v4` (Multi Fabric Spotlight V1) template — its slices are named `Spotlight 1/2/3`, and despite the schema already saying `Link: [product page]` for each, all 3 shared one broken hero link because the old name-only check never even looked at them. (A `template_slices=None` fallback still matches the old `Product N` name pattern, for any caller without template context.) The "or category" half of the match closes a real gap found 2026-08-01: CZ's Task 9 "Flash Sale Last Chance" (Product Feature Full Bleed) had a "Rugs" category slice whose CTA text and Link both duplicated the preceding "Furniture" slice verbatim — "product page" alone doesn't match category slices' "[category page URL]"/"[category N LP]" wording. Confirmed by inspection that every CZ/BW/STF field mentioning "product page" or "category" is a genuine distinct-item Link placeholder, never a shared/merged-slice field like "[hero LP]" or "[main LP]", so this broadening carries no false-positive risk across any of the 15 CZ + 13 STF + 35 BW templates (verified by generating a clean, template-correct brief for every one and confirming none raise).

**`_warn_duplicate_products()` extended to CZ (as of 2026-08-01)** — the match is on the substring "product page" rather than the exact bracketed "[product page]" text, because CZ's own field wording is "[product page URL]" (BW/STF use "[product page]"). `parse_cz_response()` now calls it right after `_enforce_5050_pairing()`, same as STF/BW. During an active STF sale a **Slice 1 — Sale banner** (Full width, `Link: https://www.stfrank.com/`) is prepended and all other slices renumber +1, **except** the dedicated sale hero (Template 7, `is_sale_hero`), where the hero already carries the sale message. STF does **not** auto-cycle kickers or append a CZ-style "sale link farm header" — standalone kickers/category blocks are catalogued in `STF_KICKERS` for manual/designer use only. The node IDs, use cases, and per-template slice cuts below are the source of the encoded data; keep them in sync with `STF_FIGMA_TEMPLATES` when either changes.

**Extended to TI (as of 2026-08-01)**, via a TI-specific parser rather than reusing `_warn_duplicate_products()` directly — TI's body copy is one line per slice (`Slice 2 — [name] · [fields]`, dot-separated), not the multi-line `Slice N — [name] [IMAGE]\n  Field: value` block format STF/BW/CZ share, so `_stf_slice_header_re`'s block parser can't read it. `_warn_duplicate_products_ti()` (`scripts/create_calendar_tasks.py`) parses both `TI_FIGMA_TEMPLATES[key]["slices_text"]` (to determine which slice names are single-item, schema-driven the same way — any slice whose Link field mentions "product" or "category") and the AI's actual `body_copy_lines`, then raises `SliceBriefValidationError` on the same duplicate Name/Link check. Wired into `parse_ti_response()`.

### Slice-count validation (all copy-first brands, as of 2026-08-01) — hard failure, not a warning

Confirmed real bug, 2026-07-15 CZ batch: several tasks (e.g. "Monthly Edit," "MTO Sofas: Artisan Story," "Flash Sale Last Chance") had a declared "Slices to deliver: N" that didn't match the number of slices actually enumerated underneath it — in one case (Multi-Hero during an active sale) declaring 3 but delivering 6. Root cause was architectural, not an AI-counting mistake: CZ's "Slices to deliver" line was computed from `CZ_FIGMA_TEMPLATES[letter]["slices"]`'s own base count (plus a manually-tallied +1 per sale banner / +1 per sale link-farm header) **before** the AI's actual generated content was known — and in CZ's case, before a kicker slice was even appended after that line was already written — so it silently drifted whenever the AI's delivered slice count diverged from the template (extra/missing product slot, a merged-vs-split section) or whenever a kicker got auto-attached. The mismatch only ever produced a `[WARN]` print that went unnoticed during a multi-task briefing session — the task got created anyway.

The fix, in `build_html_notes()` (`scripts/create_calendar_tasks.py`), applies to CZ, STF, and BUR: assemble the **full** final slice list first — sale banner, AI content, kicker, sale link-farm header, all of which sit outside the template's own base `slices` catalog entry — then compute "Slices to deliver" as a straight count of the "Slice N —" headers actually present via `_warn_slice_count_mismatch()`. On a match, that actual count (never a pre-computed guess) becomes the "Slices to deliver" line. **On a mismatch, the function raises `SliceBriefValidationError` instead of returning anything** — there's no safe way to know WHICH slice is wrong (merged content that should've stayed split, an extra product slot, etc. all look identical from the count alone), so `build_html_notes()` aborts before producing any html_notes at all, and the task cannot be created or updated with that brief. A companion `_renumber_slices_sequentially()` closes numbering gaps that the kicker/link-farm position math can leave behind when a template's *optional* slice goes unused (e.g. Slice 4 followed by Slice 6, skipping 5) — count-correct but not sequential otherwise; this one still auto-fixes, since renumbering sequentially has no judgment call attached to it (unlike picking which slice is wrong).

TI and HAV already computed the deliverable count correctly by counting actual "Slice" lines (no fix needed there) — TI's `parse_ti_response()` additionally now runs the same `_warn_slice_count_mismatch()` as a hard sanity check against `TI_FIGMA_TEMPLATES[key]["slices_text"]`'s own base count (+1 when `during_sale`, since TI's sale banner is AI-inserted via prompt instruction, not code-injected).

**Also fixed in the same pass:** CZ's sale-banner slice was previously rendered as the bare string `"Sale Banner"` — no "Slice 1 —" header, no Copy/Link fields — so it never matched the "Slice N —" pattern any counting or rendering logic looks for. It now renders as a real `Slice 1 — Sale banner` entry with `Sale copy:`/`Link:` fields, matching the sale-link-farm header's own format. Since the CZ sale banner is now fully code-injected (not dependent on the AI writing one), the specific "missing sale banner during an active sale" failure mode from the 2026-07-15 batch is structurally eliminated for CZ, contingent on the caller passing the correct `during_sale` flag.

**`SliceBriefValidationError` (`scripts/create_calendar_tasks.py`) is the shared exception both checks raise.** It is intentionally NOT caught by any `parse_xxx_response()`'s own `except Exception: return None` (each one has an explicit `except SliceBriefValidationError: raise` ahead of that catch-all) — a bare `None` return has an established, different meaning in this codebase ("couldn't parse the response at all," e.g. an unrecognized template letter) and is already documented elsewhere as something callers can silently fall through past (see the BW ~44-task incident under "Calendar Task Creation Workflow" below) — collapsing a structural content defect into that same `None` path would make the exact failure mode this fix targets worse, not better. Whoever is briefing (per the self-generate workflow — almost always a live Claude Code session) must let this exception surface and regenerate the completion addressing the message, not suppress it.

The field lists below are the *fields per template*. When editing or QAing a brief manually, follow the same mandatory format the auto-builder emits (below). For sale sends, let the auto-prepended banner carry the discount — do not also add a Promo/discount line into a hero Eyebrow/HED (except Template 7, where the hero is the sale).

**Mandatory brief format (matches CZ — do not group by "Section"):** The "Body Copy" section of every STF Asana brief must number every individual delivered slice sequentially starting at Slice 1 (not by Figma's internal node numbering, and not grouped under "Section 1 / Section 2" headers). Each slice entry must state:
1. **Layout** — `Full width`, `50/50 left`, or `50/50 right` (pull this from the actual Figma frame geometry — `get_metadata` on the template node shows each `<slice>` element's `x`/`width`; a slice at `x=0` spanning the full canvas width is Full width, one at `x=0` spanning half the canvas is `50/50 left`, one at `x=[half]` is `50/50 right`).
2. **Fields** — HED / DEK / CTA / Eyebrow / Name, whichever apply to that slice.
3. **Link** — the actual resolved URL for that slice specifically, not a generic "Products" list at the top of the brief and not a `→ Link: product page` placeholder.

Lead the Body Copy section with `Slices to deliver: N`. For Template 6, the 12 confirmed slices are: Slice 1 Hero (Full width) → Slice 2 Section 1 header (Full width) → Slices 3–6 Section 1 products (50/50, alternating left/right) → Slice 7 Section 2 header (Full width) → Slices 8–11 Section 2 products (50/50, alternating) → Slice 12 kicker/CTA closer (Full width). For Template 7 + Category Block 2, it's Slice 1 hero (Full width) + 6 category slices (50/50 pairs). For Template 7 + Category Block 4, it's Slice 1 hero (Full width) + 4 category slices, each Full width (image occupies half the row, copy the other half, but it's one slice per category, not paired 50/50 with a different category). See the [Surfboards: Art You Can Ride](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1216400751177127) task for a fully worked example, and the CZ [Pillow Pairings](https://app.asana.com/1/5257710284167/project/1207522423363072/task/1213983392124795) task for the reference goal-state format this mirrors.

**Sale banner rule (content emails during an active sale):** If a non-sale-hero send (e.g. a Category Feature on Template 6, or any Template 1/2/3/8/9/10/11/12/13 send) lands on a date with an active sale per `data/sale_schedules.yaml`, prepend a **Slice 1 — Sale banner — Full width** (sale name + discount, Link: homepage) ahead of the rest of the content, renumbering every subsequent slice by +1 — same convention as CZ's sale banner slice. When the banner is added, drop any redundant "X% Off" Eyebrow text from the send's own hero/header slices — the banner alone carries the sale message so the rest of the email stays focused on the content. This does **not** apply to the dedicated sale-hero sends (Template 7 + Category Block 2/4) — there, the entire hero slice already **is** the sale message.

**Note:** "Category Block 3" as referenced inside Template 2 and Template 8 is a 5-cell block ("Shop More Styles" / "New Releases" / "Pillows" / "Fabric By The Yard" / "Bedding") — this differs from the "Category Block 3" 2×2 photo-grid description in the Kickers table above. Confirm which asset is meant per-brief until this is reconciled.

**Per-template field lists → generated reference.** The field/slice breakdown for all 13 STF templates is generated from `STF_FIGMA_TEMPLATES` in `scripts/create_calendar_tasks.py` (the source of truth the auto-builder reads) into [docs/figma-templates.md → Auto-Briefed Slice Structures → St. Frank (STF)](docs/figma-templates.md). Edit the dict, then re-run `uv run python scripts/generate_figma_templates_doc.py`. Do not hand-maintain slice lists here.

---

## Interior Define Email Figma Templates

File key: `oFsPeUJ1s8oK5s6mbLl376` — [Lifecycle: Email Template Library](https://www.figma.com/design/oFsPeUJ1s8oK5s6mbLl376/Lifecycle--Email-Template-Library)
URL format: `?node-id=[NODE_ID_HYPHENATED]` — templates auto-selected by `pick_id_template()`.

Full catalog (Core Designs A–P, Specialty, Sale-Specific, Body Copy Fields): `docs/figma-templates.md#interior-define-id-email-figma-templates`

---

## Trade Email Figma Templates

File key: `e7qLewGYDpx18n5dqxV0sa` — [HAVENLY BRANDS TRADE](https://www.figma.com/design/e7qLewGYDpx18n5dqxV0sa/HAVENLY-BRANDS-TRADE)
URL format: `?node-id=[NODE_ID_HYPHENATED]` — templates auto-selected by `pick_trade_template()`.
Always include template in task **notes field** (not comment).

Full catalog (HAV, ID, CZ, TI, STF Trade templates): `docs/figma-templates.md#trade-email-figma-templates`

---

## TI (The Inside) Email Figma Templates

File key: `B2DuEEQLOCrQNhY3iKTkhi` — [TI Templates](https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates) — use the **"TI Templates Update"** page (node `174:2`).
URL format: `?node-id=[NODE_ID_HYPHENATED]` — templates auto-selected by `pick_ti_template()`.

Full catalog, slice-by-slice brief instructions, add-on kickers, and archive: `docs/figma-templates.md#ti-the-inside-email-figma-templates`

---

## Lifecycle Canvas FigJam Board — Build Spec (TI & TE)

Full instructions for building/rebuilding the [The Inside Lifecycle Canvas Map](https://www.figma.com/board/0GfQj3VJtQCSEslCo1SPjm/The-Inside-%E2%80%94-Lifecycle-Canvas-Map): **[`docs/ti-figjam-build-instructions.md`](docs/ti-figjam-build-instructions.md)**

Covers: live flow audit (paginate Klaviyo, check action status), layout constants, row builders, all 12 TI flows with correct timing/subjects, image hashes, display heights, screenshot crop script.

**To build the TE board** — trigger phrase: *"generate the figjam report for TE at this url: [URL]"*
Full instructions: **[`docs/te-figjam-build-instructions.md`](docs/te-figjam-build-instructions.md)**

Covers: prerequisites (screenshots), live flow audit with `KLAVIYO_API_KEY_TE`, real timing from `settings.delay_seconds`, screenshot crop + upload, board builder (same layout as TI), timing label rules (Day X format, branch handling), expected TE flow types, and adding a TE tab to the canvas map dashboard at `http://localhost:8507`.

