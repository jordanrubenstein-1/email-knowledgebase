---
name: reference_drip_banner_content_blocks
description: "All brand drip banner content blocks — Braze IDs, Liquid date structure, non-sale fallbacks, update process, and automated script for CZ (API) and ID (Playwright/BEE)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: ddf5e3d4-9443-407a-a43e-8f93365dec62
---

# Drip Banner Content Blocks — All Brands

These content blocks inject sale banners into triggered/drip emails. `| date: "%s"` converts timestamps to Unix seconds for numeric comparison.

**Source of truth for sale dates:** [Asana Promo Tracking Board](https://app.asana.com/1/5257710284167/project/1213996005172086/)
**Tracker spreadsheet:** [Sale Drip Content Blocks](https://docs.google.com/spreadsheets/d/14gp2nTFXlr9tmhPnzyUPICvp4Q7DzOaOiqHq_0xRzps)

---

## Automation Script

**`scripts/braze_automation/update_sale_banner.py`** — updates content blocks for a new sale. **Multi-sale aware** — adds new sales alongside existing ones; updates in-place when key matches.

```bash
# CZ — API update (instant, no browser)
uv run python scripts/braze_automation/update_sale_banner.py \
  --brand CZ \
  --sale-name "[The Citizenry] Summer Retreat Sale" \
  --reg-start "2026-06-05 07:00:00" --sale-end "2026-06-09 07:00:00" \
  --reg-image "https://braze-images.com/.../original.png" \
  --reg-link  "https://www.the-citizenry.com/" \
  --reg-alt   "Summer Retreat Sale" \
  [--dry-run]

# BUR — API update (same as CZ)
uv run python scripts/braze_automation/update_sale_banner.py \
  --brand BUR \
  --sale-name "[Burrow] Summer Ready Flash Sale" \
  --reg-start "2026-06-05 05:00:00" --sale-end "2026-06-09 05:00:00" \
  --reg-image "..." --reg-link "https://burrow.com" --reg-alt "..."

# ID — Playwright (DnD blocks can't be updated via API)
uv run python scripts/braze_automation/update_sale_banner.py \
  --brand ID \
  --sale-name "[Interior Define] Weekender Sale" \
  --reg-start "2026-06-05 07:00:00" --sale-end "2026-06-09 07:00:00" \
  --reg-image "..." --reg-link "https://www.interiordefine.com/" --reg-alt "..." \
  --interactive \
  [--block sale_b2c_banner]   # optional: one block at a time
  [--diagnose]                # screenshot only, no changes

# Full 3-phase sale (EA + main + extension)
  --ea-start "..."  --ea-image "..." --ea-link "..." --ea-alt "..."
  --ext-start "..." --ext-image "..." --ext-link "..." --ext-alt "..."

# Override auto-derived key
  --sale-key mykey
```

**Script support status:**
- **CZ, BUR, STF** — HTML/CSS blocks, API update (instant, no browser) ← STF not yet wired in script
- **ID, HAV** — DnD blocks, Playwright required (`--interactive`) ← HAV not yet wired in script
- HAV workspace ID: `664223fb71bcf3005760dfc2`; `trig_banner_dps_final` dashboard edit ID: `66ce98bcb6a2690063284681`
- STF workspace ID: `666716b3858150005b566956`; STF blocks accumulate historical sale history (additive pattern)

### Multi-sale behavior
- `--sale-name` is required — used to auto-derive a short key (e.g. `[Burrow] Summer Ready Flash Sale` → `srfs`, `July 4th Sale` → `j4s`)
- Key strips `[Brand]` prefix, takes first letter of text words and leading digits of number tokens
- Block stores hidden `SALE_SECTION:{...}` JSON comments as machine-readable metadata
- **New sale**: key not found → appends new `{% elsif %}` branch, sorted by date
- **Date change**: key matches → replaces that section's variables/image in-place
- `--sale-key` overrides auto-derivation (use if two sales generate the same key)

---

## How CZ Blocks Work (plain HTML/Liquid)

CZ blocks are clean HTML/Liquid — no DnD wrapper. Updated directly via `POST /content_blocks/update` API (immediate, no browser needed).

**API key:** `BRAZE_API_KEY_CZ`

## How ID Blocks Work (DnD — Playwright required)

Braze API returns `"DND Content blocks are not allowed to be updated from the API."` for DnD blocks. Must use Playwright to automate the Braze UI.

**API key for listing/fetching:** `BRAZE_CONTENT_BLOCKS_API_KEY_ID`

### Playwright automation flow for ID:
1. Navigate to content block list → find block by name → click it
2. Click "Edit Content Block body"
3. Wait for BEE editor (`app.getbee.io` iframe, `1440×900` viewport)
4. Hover over html_block at **(570, 190)** → reveals inline toolbar
5. Click "HTML" toolbar button at **(770, 246)** → opens HTML PROPERTIES right panel
6. Use `bee_frame.locator(".cm-content").first.fill(liquid_body)` — **CodeMirror v6 contenteditable**
7. Click Done → Click "Launch Content Block"

### Key technical facts:
- The editor is in `app.getbee.io` iframe — NOT `us07.bz-rndr.com` (which is a preload frame)
- The BEE iframe: x=1, y=165, width=1918, height=914 in page coords
- HTML PROPERTIES panel in BEE frame: x=1507-1918, y=50-914 (BEE coords)
- The code editor is **CodeMirror v6** (`.cm-content.cm-lineWrapping`, contenteditable)
- **Viewport must be 1440×900** — at 1920×1080, the HTML PROPERTIES panel is off-screen on most laptops
- `locator.fill()` on `.cm-content` reliably replaces all content and triggers CM6 state update
- After `fill()`, click **Done** (top bar, in main page frame) then **"Launch Content Block"** to publish
- A single click at (570, 190) selects the html_block; a second click at the same spot deselects it

---

## Standardized Variable Names (all brands, all future sales)

```liquid
{% assign sale_ea_start        = "YYYY-MM-DD HH:MM:SS" | date: "%s" %}
{% assign sale_reg_start       = "YYYY-MM-DD HH:MM:SS" | date: "%s" %}
{% assign sale_extension_start = "YYYY-MM-DD HH:MM:SS" | date: "%s" %}
{% assign sale_end             = "YYYY-MM-DD HH:MM:SS" | date: "%s" %}
```

- No EA → set `sale_ea_start = sale_reg_start` (EA window = 0)
- No extension → set `sale_extension_start = sale_end` (extension window = 0)
- All times in **UTC**. CZ/ID/HAV/STF use `07:00:00` (midnight MT). **BW uses `05:00:00`** (midnight ET — intentional).

---

## Block Catalog

| Brand | Block | Braze ID | Non-sale fallback | API key env | Structure |
|-------|-------|----------|-------------------|-------------|-----------|
| CZ | `sale_b2c_banner` | `a71504fd-ec1f-4c01-b143-03fc277d26ab` | Blank | `BRAZE_API_KEY_CZ` | HTML/CSS — API |
| CZ | `Welcome_Promo_Banner` | `a9ff9798-f4b0-4489-a0b5-d48d1c9f072e` | CRAFTED20 20% off | `BRAZE_API_KEY_CZ` | HTML/CSS — API |
| ID | `sale_b2c_banner` | `e5978bcf-a82a-4ac4-ae24-2451908fe189` | Blank | `BRAZE_CONTENT_BLOCKS_API_KEY_ID` | DnD — Playwright |
| ID | `welcome_promo` | `4de56627-db9d-4fef-834d-d5edd8338f6b` | WELCOME15 15% off | `BRAZE_CONTENT_BLOCKS_API_KEY_ID` | DnD — Playwright |
| BW | `2025Q3_Abandon_Banner` | `b04c8f92-ac84-4e1e-9bb8-a0f7868a12f6` | Blank | `BRAZE_API_KEY_BUR` | HTML/CSS — API |
| HAV | `trig_banner_dps_final` | `a2142cc5-d22d-498e-88f9-3f2918e47c2e` | Blank | `BRAZE_API_KEY_HAV` | DnD — Playwright |
| STF | `2025Q3_Welcome_Banner_2` | `69291094-e703-45c6-adac-0f380ec8327d` | STFRANK20 20% off | `BRAZE_API_KEY_STF` | HTML/CSS — API |
| STF | `2025Q3_Welcome_Banner_2_FreeShipping` | `8f3b7492-89d1-46b2-b7ae-9465223ef6ee` | Free shipping $150+ | `BRAZE_API_KEY_STF` | HTML/CSS — API |

**ID `welcome_promo` evergreen (hardcoded in script):**
`15% Off Your Next Order. Use Code: WELCOME15-A6J8D3.` — CDN: `68efaf4f053179006334c3b0/original.png`, LID: `j7wmgwh38ndf`

**CZ `Welcome_Promo_Banner` evergreen:**
`Claim 20% Off Your First Order. Use Code: CRAFTED20-ETWC26` — CDN: `69f226fb55f47c009abac172/original.png`, LID: `bruyy7cx2x0v`

---

## HAV known bug (as of 2026-06)
`trig_banner_dps_final` has an unreachable extension branch — `sale_extension_end` (5/20) is before `sale_reg_end` (5/27). Fix when updating for next sale.

## STF pattern
STF appends new sale phases at the top of a growing `if/elsif` chain — old sale windows stay (they never match since dates are past). Commented-out vars (`{%- comment -%}`) reference old sales. This is intentional.

## BW/HAV/ID `sale_b2c_banner` — no fallback
These go BLANK outside the sale window. `welcome_promo` (ID) and `Welcome_Promo_Banner` (CZ) have evergreen fallbacks; `sale_b2c_banner` blocks do not.
