# Lifecycle Canvas Map — Setup & Maintenance Guide

This guide covers the full lifecycle canvas map system — what it is, how to view it, and how to keep it current.

---

## What is the lifecycle canvas map?

A visual reference showing every active lifecycle canvas for each brand, with:
- Email creative thumbnails for each step
- Subject lines and timing labels
- Performance stats (Sends/wk, Opens/wk, UOR, Sessions/wk, Revenue/wk, Rev/M)
- SMS step copy

It exists in three forms:

| Format | Where | Best for |
|--------|--------|----------|
| **Streamlit dashboard** | `http://localhost:8507` — run `bash scripts/start_dashboards.sh` | Daily use, live Snowflake stats, brand tab switching |
| **Static HTML** | `reports/lifecycle-canvas-map.html` — open in browser or share as file | Sharing with people who don't have the repo set up |
| **FigJam boards** | Links below | Workshopping, annotations, presenting to stakeholders |

**Existing FigJam boards:**
- Burrow: https://www.figma.com/board/VxjmwZuwCf3bsWfMGLOlOm
- Interior Define: https://www.figma.com/board/IHASW2pUj5Zfy4ZKJlTyDR

**Brands covered:** Burrow · Interior Define · Havenly · The Citizenry · St. Frank

---

## Viewing the dashboard

```bash
# Pull latest
git pull

# Start all lifecycle dashboards (canvas map is on port 8507)
bash scripts/start_dashboards.sh

# Open in browser
open http://localhost:8507
```

Use the brand tabs at the top to switch brands. Stats load from Snowflake on first view and cache for the session. Click **Refresh** to pull updated numbers.

The static HTML version is always available at `reports/lifecycle-canvas-map.html` — open it directly in a browser. It's regenerated automatically every Monday by the CI pipeline and committed to the repo, so `git pull` + open is enough.

---

---

## Prerequisites

### 1. Braze API key with Canvas permissions
The key needs both **Canvas** and **Campaigns** permissions enabled. Check in Braze:
> Settings → API Keys → [key] → Permissions → Canvas (Export, Details, Trigger, Schedule)

Add to `.env`:
```
BRAZE_API_KEY_[BRAND]=your-key-here
BRAZE_BASE_URL_[BRAND]=https://rest.iad-07.braze.com
```

### 2. Figma access
You need edit access to the Havenly Figma workspace. The Figma API token is already configured in `.env` (`FIGMA_TOKEN`).

### 3. Python environment
All scripts use `uv`. From the repo root: `uv run python scripts/...`

---

## Step 1 — Import canvases into the knowledgebase

```bash
# Import all campaigns and canvases for the brand
uv run python scripts/import_braze.py --brand [BRAND] --skip-existing

# Flatten canvas steps into individual YAML records
uv run python scripts/flatten_canvases.py --brand [BRAND]
```

This creates YAML files at `campaigns/canvas-[slug]-t[n]-[hash].yaml` for each active step.

---

## Step 2 — Identify active canvases and steps

Query the knowledgebase to find the active steps for each canvas you want to include. For canvases with multiple variants at the same `sequence_position`, use the one with the most recent `dates.first_sent`.

```bash
python3 - << 'EOF'
import yaml, glob

TARGET_CANVASES = [
    "Your Canvas Name Here",
    # add more...
]

results = {}
for f in glob.glob("campaigns/canvas-*.yaml"):
    data = yaml.safe_load(open(f))
    if data.get('brand') != '[BRAND]': continue
    cn = data.get('canvas_name', '')
    for t in TARGET_CANVASES:
        if t.lower() in cn.lower():
            pos = data.get('sequence_position', 0)
            sent = (data.get('dates') or {}).get('first_sent', '') or ''
            subj = (data.get('subject') or '')[:60]
            html = (data.get('sends') or [{}])[0].get('html_file', '')
            results.setdefault(cn, []).append({'pos':pos,'sent':sent,'subj':subj,'html':html,'file':f})
            break

for cn in sorted(results):
    steps = sorted(results[cn], key=lambda x: x['pos'])
    print(f"\n{cn}")
    for s in steps:
        exists = "✓" if s['html'] and glob.glob(f"campaigns/{s['html']}") else "✗"
        print(f"  T{s['pos']} {exists} {s['subj']}")
        print(f"       {s['file'].split('/')[-1]}")
EOF
```

---

## Step 3 — Render email screenshots

The render script preprocesses Braze Liquid templates with mock data and produces PNG screenshots.

```bash
# Render a single file
uv run python scripts/render_liquid_preview.py --file canvas-[slug]-t[n]-[hash].html

# Render multiple in parallel (run as background jobs)
for f in file1.html file2.html file3.html; do
  uv run python scripts/render_liquid_preview.py --file "$f" &
done
wait
```

Rendered PNGs land in `campaigns/screenshots/rendered/`.

**Watch out for:**
- **Very tall emails** (>10,000px): crop to a reasonable height before uploading to Figma. Figma can't render files that large.
  ```python
  from PIL import Image
  img = Image.open("path/to/email.png")
  cropped = img.crop((0, 0, img.width, 4923))  # ≈ 2000px at FigJam scale
  cropped.save("path/to/email-cropped.png")
  ```
- **Liquid code showing**: if raw Liquid code is visible in the rendered output, check `scripts/render_liquid_preview.py` — the `preprocess_html()` function may need a new pattern added for that canvas's template type.

### Calculate FigJam frame heights

FigJam frames are 260px wide. Scale height proportionally:
```python
from PIL import Image
img = Image.open("rendered/your-email.png")
scale = 260 / img.width
figjam_h = round(img.height * scale)
print(f"FigJam height: {figjam_h}px")
```

Cap very tall frames at **2000px** to keep the board navigable.

---

## Step 4 — Create the FigJam board

Use Claude Code (in the email-knowledgebase project) with the Figma MCP connected:

1. **Create a new FigJam file:**
   Ask Claude: *"Create a new FigJam board called '[Brand] — Lifecycle Canvas Map' in the Havenly Figma workspace."*

2. **Build the board structure and upload images:**
   Share the canvas list (name, steps, subjects, timing, file slugs) with Claude and ask it to replicate the format from the Burrow or Interior Define board.

   Claude will:
   - Create the title column, entry text, label bars (dark background with gold timing + white subject), and email frame placeholders for each row
   - Upload all rendered PNGs and apply them to the placeholder frames
   - Add grey/purple placeholder rectangles for SMS-only steps

### Board layout reference (matches existing boards)

| Element | Position | Style |
|---|---|---|
| Title column bar | x=500, y=**ROW_Y − 44** | 8px wide, dark (#1A1A1A) — starts at same y as title text |
| Title text | x=520, y=**ROW_Y − 44** | 18px, Semi Bold, dark — floats **above** the label bars, no width constraint, `textAutoResize='WIDTH_AND_HEIGHT'` (default) |
| Subtitle (e.g. "4 emails") | x=520, y=**ROW_Y − 22** | 13px, Regular, grey — same, no width constraint |
| Entry text | x= after last step + gap | 13px, grey — "Canvas Name · Entry: trigger description" |
| Label bar (per step) | y=**ROW_Y**, h=100 | Dark rect (#1A1A1A), 260px wide — first content element; ROW_Y is where step content starts |
| Timing label | inside label bar, top (+10) | 12px, Semi Bold, gold (rgb 217,166,51) — e.g. "T1 · Day 0" |
| Subject line | inside label bar (+34) | 10px, white — `textAutoResize='HEIGHT'`, `resize(240, h)` so full SL always shows |
| Preheader line | inside label bar (+54) | 9px, grey — italic "No preheader (plain-text)" for PT emails |
| Email frame | y=ROW_Y + 100 | 260px wide, height = scaled PNG height (max 2000px), scaleMode=FIT |
| SMS placeholder | same y as email frame | Purple-tinted rect (#DBD1FA), 200px wide |
| Row gap | between rows | 120px after tallest frame |
| **Title placement rule** | — | Title and subtitle float **above** the label bars at ROW_Y−44 and ROW_Y−22. They are NOT placed to the left of the emails. No width constraint needed since they are above the content area. Title bar y also starts at ROW_Y−44 so it aligns with the title text. |

---

## Step 5 — Add timing

Get exact timing from Braze canvas details (requires canvas API permission):

```bash
source .env
curl -s "https://rest.iad-07.braze.com/canvas/details?canvas_id=[CANVAS_ID]" \
  -H "Authorization: Bearer $BRAZE_API_KEY_[BRAND]" | python3 -c "
import sys, json
data = json.load(sys.stdin)
steps = data.get('canvas', data).get('steps', [])
for s in steps:
    if s.get('type') in ('delay', 'message'):
        print(f\"  [{s['type']:10}] {s['name']} | {json.dumps(s.get('delay',{}))}\")
"
```

If the canvas API is blocked (403), ask the canvas owner for the delay schedule and update labels manually. Timing labels can be updated in Claude Code:

*"Update the Swatch Post Purchase timing labels to: T1 Day 6, T2 Day 9, T3 Day 13..."*

---

## Step 6 — Handle missing canvases

If a canvas isn't in the knowledgebase (no YAML files match), add a grey placeholder row on the board noting it's pending import. Once the Braze API key has canvas permissions:

```bash
uv run python scripts/flatten_canvases.py --brand [BRAND]
uv run python scripts/backfill_html_screenshots.py --brand [BRAND]
```

Then render the new HTML files and add frames to the existing board.

---

## Step 5b — Get real delay timing from Snowflake

The Braze canvas details API returns empty delay objects — it does not expose actual delay amounts for any canvas type (email or SMS). The most reliable way to get real timing is to trace a real user's journey in the Braze raw events datashare.

**Which view to query:** use whichever channel the canvas sends. For a mixed email+SMS canvas, either view works — pick the one with the most steps. Both views share the same `USER_ID`, `CANVAS_NAME`, `CANVAS_STEP_NAME`, and `TIME` columns.

| Channel | View |
|---|---|
| Email | `USERS_MESSAGES_EMAIL_SEND_SHARED` |
| SMS | `USERS_MESSAGES_SMS_SEND_SHARED` |

**Which datashare to use:**

| Brand | Database | Schema |
|---|---|---|
| BUR, HAV, CZ | `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206` | `DATALAKE_SHARING` |
| ID, STF | `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF` | `DATALAKE_SHARING_TIERED` |

**Step 1 — Find a user who received the last step in the flow:**

```sql
SELECT USER_ID
FROM {DB}.{SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
  AND CANVAS_NAME = '{Canvas Name}'
  AND CANVAS_STEP_NAME ILIKE '%T8%'   -- or whatever the last step is
ORDER BY TIME DESC
LIMIT 1
```

Use `CANVAS_NAME ILIKE` if you don't know the BSON CANVAS_ID. A user who received the last step necessarily received all prior steps.

**Step 2 — Pull all sends for that user from the same canvas, with time deltas:**

```sql
WITH last_step_user AS (
  SELECT USER_ID
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED
  WHERE APP_GROUP_ID = '{APP_GROUP_ID}'
    AND CANVAS_NAME = '{Canvas Name}'
    AND CANVAS_STEP_NAME ILIKE '%T8%'
  ORDER BY TIME DESC
  LIMIT 1
)
SELECT
  s.CANVAS_STEP_NAME,
  TO_TIMESTAMP(s.TIME)                                       AS sent_at,
  DATEDIFF('minute',
    LAG(TO_TIMESTAMP(s.TIME)) OVER (ORDER BY s.TIME),
    TO_TIMESTAMP(s.TIME))                                    AS minutes_since_prev
FROM {DB}.{SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED s
JOIN last_step_user u ON s.USER_ID = u.USER_ID
WHERE s.APP_GROUP_ID = '{APP_GROUP_ID}'
  AND s.CANVAS_NAME = '{Canvas Name}'
ORDER BY s.TIME ASC
```

**Step 3 — Convert minutes to cumulative days:**

Add up the `minutes_since_prev` column and divide by 1440 to get days from T1. Round to the nearest whole day for the label.

Example (ID SMS Welcome):

| Step | Minutes since prev | Cumulative day |
|---|---|---|
| T1 | — | Day 0 |
| T2 | 120 (2 hrs) | Day 0 |
| T3 | 1,320 (22 hrs) | Day 1 |
| T4 | 2,881 (~2 days) | Day 3 |
| T5 | 4,321 (~3 days) | Day 6 |
| T6 | 4,320 (~3 days) | Day 9 |
| T7 | 4,321 (~3 days) | Day 12 |
| T8 | 5,760 (~4 days) | Day 16 |

**Notes:**
- Sale and non-sale variants share the same canvas-level delays — timing is identical regardless of which copy variant fires.
- Use the Havenly Analytics MCP (`mcp__claude_ai_Havenly_Brands_Analytics_MCP__execute_query`) to run these queries without needing a separate Snowflake connection.
- If no user has received the last step yet (new canvas), check the canvas setup in Braze UI — delay steps will show the configured wait time in the step editor.

---

## Step 3b — Find the correct footer content blocks per brand

Email HTML files use Liquid content block tags (`{{content_blocks.${Block_Name}}}`) for footers. These render as blank or raw Liquid in previews unless substituted. Before rendering, identify which footer block each canvas step uses so you can inject the right HTML.

**How to find the footer block for any canvas:**

```bash
# Grep a specific HTML file
grep -o 'content_blocks\.\${[^}]*}' campaigns/html/your-canvas-file.html

# Or grep all HTML files for a brand's canvas steps at once
grep -roh 'content_blocks\.\${[^}]*}' campaigns/html/ | grep -i footer | sort | uniq -c | sort -rn
```

Then cross-reference with the brand map below to know which block name(s) to substitute in `render_liquid_preview.py`.

**Per-brand footer content blocks**

| Brand | Footer content block(s) | Notes |
|-------|------------------------|-------|
| **CZ** | `CZ_Main_Footer` (or seasonal variant) + `Havenly_Footer_1`, `Havenly_Footer_2`, `Havenly_Footer_3` | Seasonal variants: `CZ_Main_Footer_Spring_2025`, `CZ_Main_Footer_Summer_2025`, `CZ_Main_Footer_Fall_2025`, `CZ_Main_Footer_Holiday_2025`. Check the specific canvas HTML file to see which variant it uses — do not assume. `CZ_Main_Footer_Without_Categories` appears on some B2C sends. `Havenly_Footer_1/2/3` always appear alongside the CZ footer in designed emails. |
| **BUR** | `footer_us` (non-sale) or `sale_footer_us` (during sale) | PT emails use `PT_sale_footer_unsubscribe` instead. |
| **HAV** | `pre_converted_footer` (DPS/PC) or `converted_footer_2` (MP/CONV) | Lifecycle canvases also use `All_Brands_Footer`, `All_Brands_Footer2`, `All_Brands_Footer3` for the Havenly network block at the bottom. |
| **ID** | `b2c_footer` (standard) or `b2c_footer_no_geo` | `B2C_Footer_Unsub` is a minimal variant. Trade uses `trade_unsubscribe`. |
| **STF** | `footer` | `Unsub` is used in some older STF emails as a standalone unsubscribe block. |
| **TI / TE** | Klaviyo — no Braze content blocks. Footer is hardcoded in each template's HTML. | |

**Important:** Footer block names change seasonally for CZ (and possibly other brands in future). Always grep the actual canvas HTML file rather than assuming the block name. The knowledgebase HTML files in `campaigns/html/` reflect what was live when the campaign was sent — they are the source of truth for which block a given step uses.

---

## Content Block Rendering Rules

### welcome_promo — always use the evergreen branch

`welcome_promo` is a date-conditional block at the top of ID Welcome Series emails (T1–T5). It shows different promotional banners during active sale phases, and a permanent evergreen offer outside of sales.

**Rule:** When rendering any Welcome Series screenshot for the FigJam board, always use the **evergreen ({% else %}) branch** — even if a sale is currently active. The board shows the canonical non-sale state of each email.

**Implementation:** The cached version in `data/content_blocks/id.json` contains only the evergreen branch (currently: "15% Off Your Next Order — WELCOME15"). If `welcome_promo` is updated in Braze (e.g. new promo code or creative), re-fetch from the ID workspace using `BRAZE_USERS_API_KEY_ID` and cache the `{% else %}` branch only.

```python
# Fetch current welcome_promo content
import urllib.request, json, os
key = os.getenv('BRAZE_USERS_API_KEY_ID')
req = urllib.request.Request(
    'https://rest.iad-07.braze.com/content_blocks/info?content_block_id=4de56627-db9d-4fef-834d-d5edd8338f6b&include_inclusion_data=false',
    headers={'Authorization': f'Bearer {key}'}
)
with urllib.request.urlopen(req) as r:
    d = json.loads(r.read())
# Extract and cache only the {% else %} branch (block-10 in current structure)
```

---

## Gap-Preserving Layout Updates

**Trigger:** Any time an email frame on the board gets taller — due to adding a content block (e.g. chat_kicker), importing a new email screenshot, or re-rendering an existing email.

When a frame grows, it may push into the gap between its row and the next. Always preserve the original inter-row gaps by shifting subsequent rows down.

### Procedure

**1. Determine which rows grew**

**Only shift if the row's tallest frame changed.** A row's height is the height of its tallest frame. If an email grew but is still shorter than other emails in the same row, the row's bottom didn't move — do nothing.

```
row_growth = max(new frame heights in row) − max(old frame heights in row)
```

If `row_growth == 0`, skip — no shift for anything below that row.

*Example:* Welcome T5 grew 1406→1818px, but T2/T3/T4 in the same row are 2000px (still tallest). `row_growth = 0`. Nothing below Welcome shifted.

**2. Identify shift boundaries**

Each row's "bottom" is the y-position of its tallest frame's lower edge (`frame.y + frame.height`). All elements with an original y **greater than** that bottom need to shift down by `row_growth`. Shifts accumulate across multiple rows.

```javascript
function yShift(origY) {
  let shift = 0;
  if (origY > row_A_bottom) shift += row_A_growth;  // original boundary
  if (origY > row_B_bottom) shift += row_B_growth;
  // ... for each row below that grew, in top-to-bottom order
  return shift;
}
```

Always use **original** y positions (before any shift), not shifted positions. Process all nodes in a single `use_figma` call.

**3. Resize the row title bar**

Each row has an 8px-wide vertical rectangle on the left whose height spans the whole row. Increase its height by `row_growth`. Its y position changes only if it's below a different row that also grew.

**4. Apply in one `use_figma` call**

```javascript
for (const node of figma.currentPage.children) {
  const origY = node.y;
  const shift = yShift(origY);

  if (node is a resized frame) {
    node.resize(node.width, newH);   // set new height
    if (shift > 0) node.y = origY + shift;  // also shift y
  } else if (node is a row title bar being extended) {
    node.resize(node.width, originalH + row_growth);
    if (shift > 0) node.y = origY + shift;
  } else {
    if (shift > 0) node.y = origY + shift;
  }
}
```

**5. Verify gaps**

After the update, confirm each inter-row gap is unchanged:
- Read the updated `get_figjam` node tree
- For each adjacent row pair: `next_row_bar.y − (prev_row_bar.y + prev_row_bar.height)` should equal the original gap

### ID FigJam board — inter-row gaps (as of 2026-06-04)

These are gaps between the bottom of each row's title bar and the top of the next row's title bar. They must be preserved exactly on every update.

| Row pair | Gap |
|---|---|
| Cart Abandon → SMS Welcome | 94px |
| SMS Welcome → Welcome Series | 85px |
| Welcome Series → Collection Browse Abandon | 72px |
| Collection Browse Abandon → Category Browse Abandon | 96px |
| Category Browse Abandon → Swatch Post Purchase | 96px |
| Swatch Post Purchase → Browse Abandon Multi Product | 117px |
| Browse Abandon Multi Product → Swatch Cart Abandon | 91px |
| Swatch Cart Abandon → Post Purchase | 99px |

### ID FigJam board — row title bar node IDs (as of 2026-06-04)

| Row | Node ID | Current y | Current h |
|---|---|---|---|
| Cart Abandon | `1:7` | 382 | 1555 |
| SMS Welcome | `89:5` | 2031 | 267 |
| Welcome Series | `1:31` | 2383 | 2489 |
| Collection Browse Abandon | `1:55` | 4944 | 2132 |
| Category Browse Abandon | `1:67` | 7172 | 2132 |
| Swatch Post Purchase | `1:79` | 9400 | 2553 |
| Browse Abandon Multi Product | `1:131` | 12070 | 1367 |
| Swatch Cart Abandon | `1:151` | 13528 | 695 |
| Post Purchase | `1:163` | 14322 | 4258 |

---

## Tips

- **Only include `status: active` canvases** — archived or draft canvases create noise
- **For canvases with A/B variants** at the same step position, use the most recently sent variant (`dates.first_sent`)
- **Dynamic subject lines** (Liquid-generated) — label them as `[Personalized: variable_name]` in the timing bar
- **SMS steps** — show as purple placeholder rectangles, not email frames; include the SMS copy in the label if available
- **Board order** — match the order the brand team requested, or use trigger timing (subscription → browse → cart → post-purchase)
- **Re-rendering** — if email creative changes, re-run `render_liquid_preview.py` for that file and re-upload to Figma using `nodeId`

---

## Maintaining the canvas map (ongoing)

This section covers what to do when a new canvas launches, creative changes, or timing needs updating. The system is designed so any team member can keep it current.

---

### Adding a new canvas

When a new lifecycle canvas goes live, add it to both the **Streamlit dashboard** and the **FigJam board** for that brand.

**Step 1 — Wait for first sends**

The canvas needs at least a few sends in the Braze datashare before you can get step names and timing. Once it's live and sending:

```bash
# Check it's showing up
uv run python - << 'EOF2'
from scripts.snowflake_client import get_snowflake_client
# query CHANGELOGS_CANVAS_SHARED for the brand's APP_GROUP_ID to confirm hex ID
EOF2
```

Or just ask Claude: *"Find the hex canvas ID for [Canvas Name] for [Brand] in the datashare."*

**Step 2 — Get step structure and timing**

Use `braze_get_canvas` (requires canvas API permissions on the brand's key) or trace a real user journey from the datashare:

```sql
-- Trace timing from a real user
SELECT channel, CANVAS_STEP_NAME, TO_TIMESTAMP(TIME) AS sent_at,
  DATEDIFF('hour', MIN(TO_TIMESTAMP(TIME)) OVER (), TO_TIMESTAMP(TIME)) AS hours_from_t1
FROM (
  SELECT 'email' AS channel, CANVAS_STEP_NAME, TIME
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED WHERE USER_ID = :user AND CANVAS_ID = :hex_id
  UNION ALL
  SELECT 'sms', CANVAS_STEP_NAME, TIME
  FROM {DB}.{SCHEMA}.USERS_MESSAGES_SMS_SEND_SHARED WHERE USER_ID = :user AND CANVAS_ID = :hex_id
)
ORDER BY TIME ASC
```

**Step 3 — Render the email screenshots**

```bash
# Find the HTML file (imported by the daily CI job)
ls campaigns/html/ | grep [canvas-slug]

# Render it
uv run python scripts/render_liquid_preview.py --file canvas-[slug]-t[n]-[hash].html
```

**Step 4 — Add to the dashboard script**

Edit `scripts/lifecycle_canvas_map_dashboard.py` and add a new entry to the brand's `"rows"` list:

```python
{
    "name": "Canvas Display Name",
    "entry": "Entry trigger description",
    "stats_node": "lifecycle-stats::[brand]::[canvas-slug]",
    "canvas_ids": ["hex_canvas_id_from_datashare"],
    "ga4_pattern": "TRG_EM%Canvas_Name_Pattern%",
    "ga4_channel": "EMAIL",  # or "SMS"
    "steps": [
        {"t": "T1 · Day 0",  "s": "Subject line here", "f": "canvas-[slug]-t1-[hash].png"},
        {"t": "T2 · Day 3",  "s": "Subject line here", "f": "canvas-[slug]-t2-[hash].png"},
        # SMS steps: add channel="sms", body="...", no "f" field
    ],
},
```

Then regenerate:

```bash
uv run python scripts/lifecycle_canvas_map_dashboard.py
```

**Step 5 — Add to the FigJam board**

Tell Claude: *"Add [Canvas Name] to the [Brand] FigJam board"* — it will place the row, upload screenshots, add label bars, and wire up the stats node.

The `stats_node` name you set in Step 4 must match exactly — this is how the Monday CI job finds and updates that canvas's stats automatically.

---

### Updating timing labels

If a canvas delay schedule changes, update the `"t"` field on each step in `lifecycle_canvas_map_dashboard.py` and also update the label bars in FigJam. Tell Claude: *"Update [Canvas Name] timing for [Brand] to: T1 Day 0, T2 Day 3..."*

Always get real timing from the datashare (see Step 5b in the setup guide) — don't guess.

---

### Updating email creative

When a canvas step gets new creative:

```bash
# Re-render the updated HTML
uv run python scripts/render_liquid_preview.py --file canvas-[slug]-t[n]-[hash].html

# Then tell Claude: "Update the [Canvas Name] T[n] screenshot on the [Brand] FigJam board"
# Claude will upload the new PNG and apply it to the existing frame node
```

The dashboard HTML regenerates automatically on Mondays via CI, so no manual step needed there.

---

### Monday auto-refresh (stats only)

A GitLab CI scheduled pipeline runs every Monday at 9am ET under `PIPELINE_TYPE=figjam_stats_update`. It:
- Queries Snowflake for rolling 12-week weekly averages (Sends, Opens, UOR, Sessions, Revenue, Rev/M)
- Updates the `lifecycle-stats::` text nodes on the BUR and ID FigJam boards
- Regenerates `reports/lifecycle-canvas-map.html` and commits it

No action needed — it runs automatically. If it fails, check GitLab CI/CD → Pipelines for the error.

To trigger it manually: GitLab → CI/CD → Pipelines → Run pipeline → set `PIPELINE_TYPE = figjam_stats_update`.

---

### Adding a new brand

To add a new brand (e.g., TI, TE) to the canvas map:

1. Follow the full setup guide (Steps 1–6) to build the FigJam board
2. Add the brand's canvas definitions to `CANVASES` in `lifecycle_canvas_map_dashboard.py`
3. Add the brand's Snowflake config to `BRAND_SNOWFLAKE`
4. Add the brand's canvas hex IDs to the weekly CI query in `.gitlab-ci.yml`
5. Add `"[brand]"` to the `--brand` choices in `argparse` and the `brand_tabs` list in `canvas_map_dashboard.py`

Then tell Claude: *"Add [Brand] to the lifecycle canvas map dashboard."*

---

### Quick reference — existing boards and scripts

| What | Where |
|---|---|
| Burrow FigJam board | https://www.figma.com/board/VxjmwZuwCf3bsWfMGLOlOm |
| Interior Define FigJam board | https://www.figma.com/board/IHASW2pUj5Zfy4ZKJlTyDR |
| Dashboard generator (HTML + Streamlit data) | `scripts/lifecycle_canvas_map_dashboard.py` |
| Streamlit app | `scripts/canvas_map_dashboard.py` — run on port 8507 |
| Start all dashboards | `bash scripts/start_dashboards.sh` |
| Static HTML export | `reports/lifecycle-canvas-map.html` |
| Weekly CI job | `.gitlab-ci.yml` → `update-lifecycle-canvas-map` + `update-lifecycle-figjam` |
| Render email screenshots | `scripts/render_liquid_preview.py` |
