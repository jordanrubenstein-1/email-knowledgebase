# Email Knowledgebase — Session Memory

## Lifecycle Canvas FigJam Board URLs
- [Burrow](https://www.figma.com/board/VxjmwZuwCf3bsWfMGLOlOm)
- [Interior Define](https://www.figma.com/board/IHASW2pUj5Zfy4ZKJlTyDR)
- [Havenly](https://www.figma.com/board/UHfbjMJfByUpWQAXEw71Qu/HAV-%E2%80%94-Lifecycle-Canvas-Map)
- [The Citizenry](https://www.figma.com/board/yhfQv32GCWNOfwEerlMORd/The-Citizenry-%E2%80%94-Lifecycle-Canvas-Map)
- [St. Frank](https://www.figma.com/board/sGQ2oaV3pGupwGr5u8lwaJ/STF-%E2%80%94-Lifecycle-Canvas-Map)
- [The Inside](https://www.figma.com/board/UHfbjMJfByUpWQAXEw71Qu/HAV-%E2%80%94-Lifecycle-Canvas-Map?node-id=277-2) *(page 2 of HAV board)*
- Local dashboard: `http://localhost:8507` — start with `bash scripts/start_dashboards.sh`

## Braze Raw Events Datashare (confirmed access 2026-02-27; TIER3 added 2026-05-28)

### Primary Datashare (BUR, HAV, CZ)
- **Database:** `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206`
- **Schema:** `DATALAKE_SHARING` (224 VIEWs)
- **Brands:** BUR (`67093a1f24ebbe0065cb9c77`), HAV (`664223fb71bcf3005760dfc2`), CZ (`666672a4d8965b005ac6c1bd`)
- **Date range:** Jul 2024 – real-time

### TIER3 Datashare (ID, STF)
- **Database:** `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF`
- **Schema:** `DATALAKE_SHARING_TIERED`
- **Brands:** ID (`6666726b459b5e0059d7d687`), STF (`666716b3858150005b566956`)
- **Date range:** Jul 2024 – real-time

### Shared Notes (both datashares)
- Key notes: `MACHINE_OPEN` is a STRING column (`'true'`/NULL, no `'false'` values) — use `MACHINE_OPEN IS NULL OR MACHINE_OPEN = 'false'` for human opens; `IS_SUSPECTED_BOT_CLICK` is all NULL — use `IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false'` for non-bot clicks
- `SNAPSHOTS_CANVAS_STEP_SHARED` — columns `API_ID`, `NAME` — maps CANVAS_STEP_API_ID to step name. Use `QUALIFY ROW_NUMBER() OVER (PARTITION BY API_ID ORDER BY TIME DESC) = 1` to deduplicate
- Canvas step names in GA4 follow `TRG_EM_*` pattern; batch email in GA4 follow `P_EM_*` pattern
- DISPATCH_ID is shared across ALL users in a batch send — never do multi-table fan-out JOIN on DISPATCH_ID; use CTE to pre-aggregate dispatches first
- `SMS_SHORTLINKCLICK_SHARED` has no `DISPATCH_ID` — join on `CAMPAIGN_API_ID`/`CANVAS_API_ID` directly
- Warehouse: `SNOWFLAKE_WAREHOUSE=COMPUTE_WH` is needed (was previously empty, causing hangs)
- Join to campaign names via `CHANGELOGS_CAMPAIGN_SHARED` on `CAMPAIGN_API_ID = API_ID`
- Full docs in CLAUDE.md § "Braze Raw Events Datashare"

## Snowflake Connection
- `scripts/snowflake_client.py` — `get_snowflake_client(schema=..., database=...)`
- Role: `MCP_READER`
- For Braze datashare queries, pass `database=DB, schema='DATALAKE_SHARING'` and use fully-qualified table names in SQL

## BW Lifecycle Report (generate_lifecycle_report.py)
- `scripts/generate_lifecycle_report.py` — generates 9-tab Excel for a given month
- Run: `uv run python scripts/generate_lifecycle_report.py --month February --year 2026`
- Output: `reports/BW_Lifecycle_Report_{Month}_{Year}.xlsx`
- GA4 revenue: filter by `SESSIONPRIMARYCHANNELGROUP = 'Email'` for email, `'SMS'` for SMS
- Canvas step names from `SNAPSHOTS_CANVAS_STEP_SHARED` — not from YAML lookup
- Long Tail in B&B: GA4-only campaigns that don't start with `TRG_` or `OT_EM_`
- Validated Feb 2026: total orders=70 ✓, total revenue=$103K vs ref $102K (1% variance), SMS exact match

## ngrok + Asana Webhook Service
- See `project_ngrok_webhook.md` for full steps
- Triggered by: "restart ngrok", "get ngrok running", etc.
- ngrok binary: `/opt/homebrew/bin/ngrok` (not on PATH); port: 8765
- Webhook server: `uv run uvicorn scripts.braze_automation.webhook_server:app --host 0.0.0.0 --port 8765`
- After starting, check registration: `uv run python scripts/braze_automation/register_webhook.py list`
- ngrok URL appears stable (`deafly-nondemocratical-theresa.ngrok-free.dev`) — re-registration usually not needed

## Rockerbox Datashares (also visible in Snowflake)
- `ROCKERBOX_BURROW`, `ROCKERBOX_CITIZENRY`, `ROCKERBOX_HAVENLY`, `ROCKERBOX_INTERIORDEFINE`
- Not yet explored

## Klaviyo Integration (added 2026-03-11, flows fixed 2026-03-11)
- `scripts/utils/klaviyo_client.py` — API wrapper for Klaviyo v2024-10-15; `KlaviyoClient(api_key, brand)`
- `scripts/import_klaviyo.py` — mirrors import_braze.py; supports `--brand TI|TE --skip-existing --skip-analytics --dry-run --flows-only`
- `scripts/backfill_klaviyo_analytics.py` — fills analytics for Klaviyo YAMLs; `--mode timeframe` (default, 4 API calls total for both brands) or `--mode batch` (100 IDs/call); supports `--days N`, `--force`
- Brands: TI (The Inside), TE (The Expert) — separate Klaviyo accounts, keys: `KLAVIYO_API_KEY_TI` / `KLAVIYO_API_KEY_TE`
- **ALWAYS use `--skip-analytics`** for imports; analytics endpoint (`campaign-values-reports`) has strict daily quota (~225 calls/day, was ~20 before batching)
- **Analytics backfill**: run both brands in parallel after quota resets (~20h): `uv run python scripts/backfill_klaviyo_analytics.py --brand TI --mode timeframe & uv run python scripts/backfill_klaviyo_analytics.py --brand TE --mode timeframe & wait`
- Timeframe mode uses `get_all_campaign_analytics()` — no campaign_id filter, Klaviyo returns all campaigns in window. API uses `groupings` field (not `grouping_keys`) for this query pattern. 1-year max per request; auto-splits into 364-day windows.
- Analytics coverage as of 2026-03-13: TI 589/2180 campaigns (27%), TE 805/1663 (48%) — remaining zeros are pre-July 2024 (TI has been on Klaviyo since 2018)
- HTML in campaign-messages is NOT inline — requires `?include=template`; HTML injected as `msg["_html"]` by `get_campaign_messages()`
- Flow messages: `include=template` NOT supported for `/flow-actions/{id}/flow-messages/` — use `get_template(template_id)` separately
- Flow action_type is `SEND_EMAIL` (uppercase) — filter uses `.upper() == "SEND_EMAIL"`
- Flow subject/preheader in `msg_attrs["content"]` dict (not top-level `msg_attrs`)
- Flow YAML filenames: `klv-flow-{flow_slug[:30]}-t{seq:02d}-{msg_id[:8]}.yaml` (not `klv-canvas-`)
- HTML filenames: `klv-flow-{flow_slug[:30]}-t{seq:02d}-{msg_id[:8]}.html`
- `write_flow_record` also uses `klv-flow-` prefix and zero-padded seq (`t01`, `t02`, etc.)
- YAML has `klaviyo_campaign_id` + `klaviyo_message_id` + `klaviyo_type: campaign|flow`
- TE campaign names DON'T follow naming convention (e.g., `03-10-26 | New Arrivals | Shopping`)
- `backfill_html_screenshots.py` fixed: wraps `init_config()` in try/except for Klaviyo-only brands; TE added to `--all` list
- TI: 2,180 campaign YAMLs + 351 flow step YAMLs; TE: 1,663 campaign YAMLs + 111 flow step YAMLs
- Total knowledgebase: ~9,900+ files as of 2026-03-11

## CZ Swatch Campaign Link
- See `feedback_cz_swatch_link.md`
- Any CZ campaign mentioning swatches must link to `https://www.the-citizenry.com/collections/swatches-bedding` — not the homepage

## HAV Color Block PT Template
- See [HAV Color Block PT Template](reference_hav_colorblock_template.md) — use `components/hav_colorblock_pt_template.html` whenever user asks for "color block" or "colorblock" HAV email

## ID Figma Templates
- See [ID Figma Templates](reference_id_figma_templates.md) — full catalog of Interior Define email templates (Core Designs A–BNDL, Swatch Talk, In Stock, Retail, Guides, Sale-specific), with node IDs and use cases. File key: `oFsPeUJ1s8oK5s6mbLl376`

## TI Figma Templates
- See [TI Figma Templates](reference_ti_figma_templates.md) — full catalog of The Inside email templates across 4 sections (Print/Swatch Callouts, Product Features, Edits & Destination, UGC) + add-on components. File key: `B2DuEEQLOCrQNhY3iKTkhi`. Also in CLAUDE.md § "TI (The Inside) Email Figma Templates".

## CZ Slice Consolidation Rule (effective 2026-06-05)
- See [CZ Slice Consolidation](feedback_cz_template_d_slice_structure.md) — Logo+Hero always merge; any additional slices sharing the same destination link also fold into one combined slice. Confirmed for Templates D, F, H. Single `Link:` at bottom of combined slice. Do NOT apply retroactively before 6/5.

## ID Analytics — Trade Exclusion Rule
- See [ID Trade Exclusion](feedback_id_trade_exclusion.md) — always exclude campaigns with "TRADE" in the name (case-insensitive) from all ID email analytics

## SMS Campaign Name — Strip "SMS" and Parenthesized Content
- See [SMS Campaign Name Cleanup](feedback_sms_campaign_name_cleanup.md) — strip "SMS" anywhere in description (P_SMS_ already encodes channel); strip entire `(...)` groups including content (parens content is scheduling metadata)

## Campaign Name Auto-Build — Strip "If Needed" and "Engaged"
- See [Campaign Name If Needed](feedback_campaign_name_if_needed.md) — when auto-building from a task with "If Needed" in the name, strip it from the Braze campaign name
- See [Engaged Strip](feedback_engaged_strip.md) — "Engaged" in a task name is an audience indicator (Engaged segment); strip it from the campaign name. Implemented in `_format_description()` in `scripts/utils/campaign_name.py`

## CZ Designed Email HTML/CSS Auto-Build (added 2026-05-23)
- **Reference script:** `scripts/braze_automation/build_cz_archive_sale_html_20260530.py` — canonical example for CZ designed emails (send date 2026-06-09+)
- **Method:** Create new campaign via "Create campaign → Email → HTML/CSS code editor" — do NOT duplicate an existing DnD campaign. Duplicating a DnD campaign produces another DnD (BEE editor); HTML/CSS campaigns require a fresh creation.
- **Flow:** `navigate_to_campaigns` → `start_campaign_creation` → set name → `select_html_editor` → `fill_sending_settings` (subject/preheader in Sending Settings tab) → `fill_html_content` (HTML in Content tab) → `_configure_link_templates` → Done → `configure_target_audience` → `configure_delivery_designed` → `configure_conversions_designed` → `save_as_draft` → Asana writeback
- **Use `configure_target_audience`** (from `build_pt_campaign.py`) — NOT `configure_audience_designed` — because it calls `_set_variant1_to_100()` after segment selection. `configure_audience_designed` does NOT include this call.
- **Re-injection script:** `scripts/braze_automation/reinject_html_cz_archive_sale.py` — navigate directly to campaign ID URL → Compose Messages → Edit message → verify Monaco (not BEE) → `fill_html_content` → `_configure_link_templates` → Done → `save_as_draft`

## UTM Re-injection Limitation (added 2026-05-23)
- `_configure_link_templates` selector: `.bcl-select__control` filtered by `has_text="link templates"` does NOT match when a template is already selected (dropdown shows "1 item selected" not the placeholder text)
- During re-injection this causes a 30s timeout — but is **benign**: Braze maintains UTM template coverage across HTML re-injections; all links keep their blue checkmarks
- Fix needed: also detect the "N item(s) selected" state (e.g. check `.bcl-select__value-container` or skip if value already set) so re-injection doesn't waste 30s timing out

## Braze Campaign Archive API (added 2026-05-23)
- `POST /campaigns/archive` with `{"campaign_ids": [api_id]}` returns `{"message":"Invalid URL"}` — endpoint is incorrect or unsupported
- Must archive campaigns manually in the Braze UI; log a warning and continue in scripts

## ID PT Template — Body + Signoff in Same Block
- See [ID PT Signoff](feedback_id_pt_template_signoff.md) — body and signoff must be in the same `block-2` div; separate block-3 table creates a large visual gap between body and sign-off

## Auto-Build HTML Source Rule
- See [Auto-Build HTML Source](feedback_auto_build_html_source.md) — NEVER use old campaign HTML files as a template. Always use the Asana brief (Body Copy) + designer assets from Google Drive.

## HAV MP/DPS → CONV/PC Mapping (added 2026-06-05)
- See [HAV MP/CONV Mapping](feedback_hav_mp_conv_mapping.md) — `MP:` task prefix = Converted audience → use `CONV` in campaign name; `DPS:` or no prefix = PC. Builder was only checking for `CONV` in name and defaulting to PC, causing wrong audience/name for MP tasks.

## PT Email Auto-Build Parsing Rules (added 2026-06-05)
- See [PT Email Parsing Rules](feedback_pt_email_parsing_rules.md) — 5 rules: (1) `SL:`/`PH:` lines set campaign fields, never go in body; (2) body starts at "Hi there," — nothing above it, never duplicated; (3) `[CTA: Text]` renders as HTML button, never literal text; (4) `[Name]` in signoff → brand signoff (`Lisa from Havenly` for HAV PT); (5) `Happy Shopping,` marks the signoff block — strip everything after the name.

## SMS Copy — First Paragraph Only
- See [SMS First Paragraph](feedback_sms_first_paragraph_only.md) — `build_sms_campaign.py` must use only the first paragraph of task notes; content after the first blank line is copywriter metadata/notes, not SMS copy.

## CZ/STF/BUR Product Inventory Check — Mandatory
- See [Product Inventory Check](feedback_cz_product_inventory_check.md) — run `inventory_checker.py --brand [CZ|STF|BUR] --search "[product]"` before including ANY product in a CZ, STF, or BUR brief; no exceptions. ID/TI have no inventory data — note unverified stock in brief.

## ID Link Map (all channels)
- See [ID Links](reference_id_sms_links.md) — context → verified URL map for ID briefs (email + SMS + push). Covers sale/EA, swatches, new arrivals, sofas/sectionals/chairs/beds, dining, rugs, leather, locations.

## BW (Burrow) Link Map (all channels)
- See [BW Links](reference_bw_sms_links.md) — context → verified URL map for BUR briefs (email + SMS + push). Note: several old brand_config.yaml paths were 404 — corrected in both config and this map (pet-friendly → /pet-friendly-furniture, dining → /dining, outdoor → /outdoor, storage → /storage).

## TI (The Inside) Link Map (all channels)
- See [TI Links](reference_ti_links.md) — context → verified URL map for TI briefs (email + SMS). Key gotcha: `/collections/best-sellers` (hyphen) redirects to beds page — always use `/collections/bestsellers`. For destination/print/edit URLs use `data/ti_links.yaml`.

## STF (St. Frank) Link Map (all channels)
- See [STF Links](reference_stf_links.md) — context → verified URL map for STF briefs (email + SMS). Source of truth is `data/stf_links.yaml` — edit there; SMS + email pick it up automatically. Covers prints, curtains, wallpaper, swatches, surfboards, furniture (/collections/decor-furniture), FBTY, outdoor fabric, and more.

## FigJam Lifecycle Board Standards — Email + SMS + Real Timing
- See [FigJam Lifecycle Board Standards](feedback_figjam_lifecycle_board_standards.md) — always show both email AND SMS touchpoints; look up real timing from Braze datashare (CANVAS_NAME ILIKE, trace a late-stage user's full journey with DATEDIFF/LAG). Never guess timing.

## FigJam Lifecycle Board — Gap-Preserving Layout Updates
- See [FigJam Gap Preservation](feedback_figjam_gap_preservation.md) — whenever an email frame grows (new content block, new screenshot, re-render), shift all subsequent rows to preserve exact inter-row gaps. Includes shift formula, row title bar node IDs, and gap table for the ID board. Full procedure in `docs/lifecycle-figjam-board-setup.md` § "Gap-Preserving Layout Updates".

## CZ Builder Re-injection Lessons (added 2026-06-02)
- See [CZ Builder Re-injection](feedback_cz_builder_reinject.md) — 5 bugs fixed: Monaco portal scoping, edit-mode navigation, brief-specified 50/50 layouts, link href vs anchor text, en-dash in slice split regex.

## Drip Banner Content Blocks — All Brands (CZ, ID, BW, HAV, STF)
- See [Drip Banner Content Blocks](reference_drip_banner_content_blocks.md) — full catalog with Braze IDs, automation script, and multi-sale design. Script: `update_sale_banner.py --sale-name "[Brand] Sale Name"`. Key auto-derived from name (`srfs`, `j4s`, `mds`); appends new sales, updates existing by key. **CZ/BUR: API**. **ID: Playwright** (`--interactive`, BEE frame `app.getbee.io`, CM6 `locator.fill()`, 1440×900 viewport). BW uses 05:00 UTC (midnight ET). Tracker: [Sale Drip Content Blocks](https://docs.google.com/spreadsheets/d/14gp2nTFXlr9tmhPnzyUPICvp4Q7DzOaOiqHq_0xRzps).

## ID Order Completed Event — Confirmed Payload Structure (added 2026-06-11)
- See [ID Order Completed Event](reference_id_order_completed_event.md) — fires once per order, products is a JSON array. SKU = `COLLECTION.MATERIAL.CATEGORY.SUBTYPE` (split by `.`). Color/leg extracted from Cylindo `image_url` params (`COLOR:`, `FINISH:`). Key edge cases: select-fabric-later (static image_url, no Cylindo params → fallback email), warranty items (`mulberry-warranty-*`), multi-item orders (SOFA not always at index 0). Full Liquid patterns for User Update steps included.


## ID Braze CDI SQL Editor — Design Expert Attributes (added 2026-06-11)
- See [ID CDI DE Attributes](reference_id_braze_cdi_de_attributes.md) — CDI SQL Editor (beta) setup for swatch post-purchase canvas personalization. Reuse existing source `BRAZE_INTERIOR_DEFINE`. Data from `STG_CONTACTS.OWNER_EMAIL` (96.7% coverage). First name via `INITCAP(SPLIT_PART(OWNER_EMAIL, '.', 1))`. Filter `it@interiordefine.com`. Braze swatch trigger event: `"Swatch Order"` (not "Swatch Order Completed"). First sync: 428.3K rows, 48 errors (0.01%).
## CZ Archive Sale Campaign (added 2026-05-23)
- Campaign ID: `6a121a092e845c0081cb8707`, workspace: `666672a4d8965b005ac6c1bd`
- Asana GID: `1213928748054248`, send date: 2026-05-30
- HTML file: `campaigns/html/p_em_2026_05_30_cz_d_memorial_day_archive_sale.html`
- Contains `row-3b` (moodboard collage inserted between photo grid and CTA button): CDN URL `https://braze-images.com/appboy/communication/assets/image_assets/images/6a121c58a5ec86007f52af8b/original.png?1779571799`, links to `https://www.the-citizenry.com/collections/archive-sale`, alt "The Archive Sale"
- Old (incorrectly DnD-duplicated) campaign `6a1215efb7c1340083bd6611` needs manual archiving in Braze UI
