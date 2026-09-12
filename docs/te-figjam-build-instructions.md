# TE (The Expert) Lifecycle FigJam Board — Build Instructions

**Trigger phrase:** "generate the figjam report for TE at this url: [URL]"

Parse the FigJam URL for the `fileKey` (the ID after `/board/`) and, if present, a `node-id` query param identifying the target page. If no page is specified, create a new page named "TE — Lifecycle Canvas Map".

---

## Prerequisites — Screenshots

TE email screenshots live at `campaigns/screenshots/klv-flow-te-*.png`. Before building the board, verify they exist:

```bash
ls campaigns/screenshots/klv-flow-te-*.png | wc -l
```

If the count is 0 or significantly less than the number of live flow steps (expect ~15–30 live steps):

```bash
uv run python scripts/backfill_html_screenshots.py --brand TE
```

This can take several minutes. Once screenshots exist, proceed to Step 1.

---

## Step 1 — Audit live TE flows and steps

**Always run this fresh — never use hardcoded flow data.** Only include:
- Flows with `status == 'live'`
- Actions with `status == 'live'` AND `action_type == 'SEND_EMAIL'`

```python
import requests, os

API_KEY = os.getenv('KLAVIYO_API_KEY_TE')
headers = {'Authorization': f'Klaviyo-API-Key {API_KEY}', 'revision': '2024-10-15'}

# Paginate all flows
flows, url = [], 'https://a.klaviyo.com/api/flows/?page[size]=50'
while url:
    r = requests.get(url, headers=headers).json()
    flows.extend(r['data'])
    url = r.get('links', {}).get('next')

live_flows = [f for f in flows if f['attributes']['status'] == 'live']
print(f"{len(live_flows)} live flows found")

# For each live flow, collect live email actions + subject/preheader
flow_data = []
for flow in live_flows:
    fid = flow['id']
    fname = flow['attributes']['name']
    trigger = flow['attributes'].get('trigger_type', '')

    # Get all flow actions (paginate)
    actions, aurl = [], f'https://a.klaviyo.com/api/flows/{fid}/flow-actions/?page[size]=50'
    while aurl:
        r = requests.get(aurl, headers=headers).json()
        actions.extend(r['data'])
        aurl = r.get('links', {}).get('next')

    live_email_actions = [
        a for a in actions
        if a['attributes']['status'] == 'live'
        and a['attributes']['action_type'].upper() == 'SEND_EMAIL'
    ]
    if not live_email_actions:
        continue  # Skip flows with no live email steps

    steps = []
    for action in live_email_actions:
        aid = action['id']
        seq = action['attributes'].get('order', 0)

        # Get message content (subject/preheader)
        r2 = requests.get(
            f'https://a.klaviyo.com/api/flow-actions/{aid}/flow-messages/?include=template',
            headers=headers
        ).json()
        for msg in r2['data']:
            content = msg['attributes'].get('content', {})
            steps.append({
                'action_id': aid,
                'msg_id': msg['id'],
                'seq': seq,
                'subject': content.get('subject', ''),
                'preheader': content.get('preview_text', ''),
            })

    flow_data.append({'id': fid, 'name': fname, 'trigger': trigger, 'steps': steps})
```

---

## Step 2 — Get real timing from the flow-actions API

**Never guess or invent timing. Always derive from the API.**

For each live flow, fetch all actions (including TIME_DELAY, AB_TEST, BOOLEAN_BRANCH) and trace the main path:

```python
def get_flow_timing(flow_id, headers):
    """Returns dict of {action_id: cumulative_days} for the main path through the flow."""
    actions, url = [], f'https://a.klaviyo.com/api/flows/{flow_id}/flow-actions/?page[size]=50'
    while url:
        r = requests.get(url, headers=headers).json()
        actions.extend(r['data'])
        url = r.get('links', {}).get('next')

    # Sort by sequence order
    actions.sort(key=lambda a: a['attributes'].get('order', 0))

    cumulative_seconds = 0
    action_times = {}  # action_id → cumulative_days (float)

    for action in actions:
        attrs = action['attributes']
        atype = attrs.get('action_type', '').upper()

        if atype == 'TIME_DELAY':
            delay_s = attrs.get('settings', {}).get('delay_seconds', 0) or 0
            cumulative_seconds += delay_s

        elif atype == 'SEND_EMAIL':
            action_times[action['id']] = cumulative_seconds / 86400  # seconds → days

        # AB_TEST and BOOLEAN_BRANCH: treat as 0 delay (main path)

    return action_times
```

**Timing label rules:**
- `0 days` → `"Immediately"`
- `< 1 day` but `> 0` → `"~X hr"` (e.g., `"~1 hr"`, `"~30 min"`)
- `N days` (integer) → `"Day N"`
- For AB/branch variants that fire at the same time as another step → same timing label as the step they branch from, plus `"· Variant A"` / `"· Variant B"` if needed

**For branching flows:** The flat action list accumulates delays from ALL branches, not just the main path. For flows with BOOLEAN_BRANCH or AB_TEST before a TIME_DELAY, the TIME_DELAY may only apply to one branch. When in doubt, look at the sequence: if two SEND_EMAIL actions surround a TIME_DELAY with no branching between them, the delay is cumulative. If a TIME_DELAY falls inside a branch (i.e., between BOOLEAN_BRANCH and the next merge), it applies only to that path — use the shorter path for the main-path label.

---

## Step 3 — Match screenshots to flow steps

For each live step's `msg_id`, find the matching screenshot file:

```python
import glob, os

screenshot_dir = 'campaigns/screenshots'

def find_screenshot(msg_id):
    """Find screenshot by msg_id embedded in filename."""
    pattern = os.path.join(screenshot_dir, f'klv-flow-*{msg_id[:8]}*.png')
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    # Fallback: check YAML for html_file, then look for matching screenshot
    return None
```

If a screenshot is missing for a step, use a grey placeholder (the `PGREY` rectangle) and note it in the board title for that step.

---

## Step 4 — Crop, measure, and upload screenshots

This step builds the two dicts the board builder needs:
- `IH` — `{msg_id: imageHash}` — the Figma image hash after upload
- `FH` — `{msg_id: display_height_px}` — the card height at 260px card width

**Why autocrop matters for sizing:** Raw screenshots are 600px wide and may have large whitespace footers. Autocrop removes blank rows/columns before calculating height, so each card is sized to the actual email content — not padded whitespace. The display height is then scaled proportionally to the 260px card width.

```python
import os, glob, tempfile, requests
from PIL import Image

CARD_WIDTH = 260  # SW constant from layout

def autocrop(src, dst, pad=2):
    img = Image.open(src).convert('RGBA')
    bg = img.getpixel((0, 0))
    pixels = img.load()
    w, h = img.size
    top    = next((y for y in range(h)         for x in range(w) if pixels[x,y][:3] != bg[:3]), 0)
    bottom = next((y for y in range(h-1,-1,-1) for x in range(w) if pixels[x,y][:3] != bg[:3]), h)
    left   = next((x for x in range(w)         for y in range(h) if pixels[x,y][:3] != bg[:3]), 0)
    right  = next((x for x in range(w-1,-1,-1) for y in range(h) if pixels[x,y][:3] != bg[:3]), w)
    img.crop((max(0,left-pad), max(0,top-pad), min(w,right+pad), min(h,bottom+pad))).save(dst)

def display_height(cropped_path):
    img = Image.open(cropped_path)
    cw, ch = img.size
    return round(ch * CARD_WIDTH / cw)

# 1. Collect all steps that have a screenshot
to_upload = []  # list of {msg_id, src_path, cropped_path}
FH = {}

tmpdir = tempfile.mkdtemp()
for msg_id, src_path in screenshot_paths.items():  # from Step 3
    if src_path is None:
        FH[msg_id] = 400  # fallback height for missing screenshots
        continue
    cropped_path = os.path.join(tmpdir, f'{msg_id}.png')
    autocrop(src_path, cropped_path)
    FH[msg_id] = display_height(cropped_path)
    to_upload.append({'msg_id': msg_id, 'path': cropped_path})

print(f"Uploading {len(to_upload)} screenshots. Heights: {FH}")

# 2. Upload via mcp__figma__upload_assets (count = len(to_upload))
# POST each file to its submitUrl, capture imageHash per msg_id
# IH dict is built from the upload responses:
IH = {}
# (upload_assets returns a list of {imageHash} in the same order as submitted)
# After upload: IH[msg_id] = returned_image_hash
```

**Verify before building:** Print `FH` and confirm no value is 400 (the missing-screenshot fallback) unless expected. Card heights that look wrong (e.g. an email at 120px when others are 800px+) likely mean the screenshot has a large uniform-color section that autocrop treated as background — inspect the source PNG manually.

---

## Step 5 — Build the board

### Layout constants and colors (identical to TI board)

```js
const SX=100, LW=140, SW=260, SG=40, LH=120, RG=120;
const DARK ={r:0.11,g:0.13,b:0.17};
const GOLD ={r:0.98,g:0.75,b:0.27};
const WHITE={r:1,  g:1,  b:1  };
const GREY ={r:0.6,g:0.6,b:0.6};
const PGREY={r:0.93,g:0.93,b:0.93};
const BLACK={r:0.05,g:0.05,b:0.05};
const LPUR ={r:0.88,g:0.85,b:0.95};  // SMS cards
```

### Helper functions (identical to TI board)

```js
function mkR(x,y,w,h,color){
  const r=figma.createRectangle();r.x=x;r.y=y;r.resize(w,h);
  r.fills=[{type:'SOLID',color}];page.appendChild(r);return r;
}
function mkT(x,y,txt,sz,style,color,maxW){
  const t=figma.createText();t.fontName={family:"Inter",style};
  t.characters=String(txt);t.fontSize=sz;t.fills=[{type:'SOLID',color}];
  if(maxW){t.textAutoResize='HEIGHT';t.resize(maxW,50);}
  t.x=x;t.y=y;page.appendChild(t);return t;
}
function buildRow(rowY, flow) {
  const maxFH = Math.max(...flow.steps.map(s => FH[s.id] || 400));
  mkR(SX, rowY-44, 8, 44+LH+maxFH, DARK);
  mkT(SX+20, rowY-40, flow.name,    14, 'Semi Bold', BLACK);
  mkT(SX+20, rowY-22, flow.trigger, 10, 'Regular',   GREY);
  for (let i=0; i<flow.steps.length; i++) {
    const s=flow.steps[i], sx=SX+LW+i*(SW+SG), fh=FH[s.id]||400;
    mkR(sx, rowY,    SW, LH, DARK);
    mkT(sx+10, rowY+ 8, s.t,    11, 'Semi Bold', GOLD,  SW-20);
    mkT(sx+10, rowY+26, s.subj, 10, 'Semi Bold', WHITE, SW-20);
    if(s.ph) mkT(sx+10, rowY+58, s.ph, 9, 'Regular', GREY, SW-20);
    const fr = mkR(sx, rowY+LH, SW, fh, PGREY);
    if(IH[s.id]) fr.fills=[{type:'IMAGE',scaleMode:'FIT',imageHash:IH[s.id]}];
  }
  return rowY + LH + maxFH + RG;
}
function buildSmsRow(rowY, flow) {
  const SMS_FH = 160;
  mkR(SX, rowY-44, 8, 44+LH+SMS_FH, DARK);
  mkT(SX+20, rowY-40, flow.name,    14, 'Semi Bold', BLACK);
  mkT(SX+20, rowY-22, flow.trigger, 10, 'Regular',   GREY);
  for (let i=0; i<flow.steps.length; i++) {
    const s=flow.steps[i], sx=SX+LW+i*(SW+SG);
    mkR(sx, rowY,       SW, LH,     DARK);
    mkT(sx+10, rowY+ 8, s.t,     11, 'Semi Bold', GOLD,  SW-20);
    mkT(sx+10, rowY+26, s.label, 10, 'Semi Bold', WHITE, SW-20);
    mkR(sx, rowY+LH, SW, SMS_FH, LPUR);
    mkT(sx+12, rowY+LH+14, s.body, 10, 'Regular', DARK, SW-24);
  }
  return rowY + LH + SMS_FH + RG;
}
```

### Entry point

```js
await figma.loadFontAsync({family:"Inter",style:"Regular"});
await figma.loadFontAsync({family:"Inter",style:"Semi Bold"});

// Target page — use the node ID from the URL if given, otherwise create a new page
// NOTE: FigJam doesn't support figma.createPage() — target an existing page or
// ask the user to create a blank page and provide its node ID.
const page = figma.root.children.find(p => p.id === 'TARGET_PAGE_NODE_ID');
await figma.setCurrentPageAsync(page);
for (const n of [...page.children]) n.remove(); // clear existing

mkT(SX, 20, 'The Expert — Lifecycle Canvas Map', 20, 'Semi Bold', DARK);

let rowY = 100;
for (const flow of FLOWS) {
  rowY = flow.type === 'sms' ? buildSmsRow(rowY, flow) : buildRow(rowY, flow);
}
```

---

## Step 6 — Expected TE flow types

Based on TE's weekly content calendar, expect flows in approximately this order. Confirm against the live audit — do not hardcode this list:

| Flow name (approximate) | Type | Notes |
|-------------------------|------|-------|
| Welcome Series | email | May have End Consumer + Trade variants as separate flows |
| New Arrivals | email | Only if a live flow exists — TE only sends if new arrivals confirmed |
| Home Tour / Spotted | email | — |
| Showroom | email | May have consumer + trade variants |
| Best of Month | email | End of month digest |
| New Dates | email | New designer availability — End Consumer only |
| Browse Abandonment | email | Check if live |
| Cart Abandon | email | Check if live |
| Transactionals | email | Booking confirmation, password reset, etc. |

**TE has no SMS flows** (as of 2026-06). If any appear in the audit, build them with `buildSmsRow`.

---

## Important notes for timing labels

These lessons came from the TI board — apply the same rules to TE:

1. **Use "Day X" format** — cumulative from the trigger event, not relative to previous step. "Day 0" = fires immediately; "Day 7" = 7 days after trigger.
2. **Get timing from `settings.delay_seconds`** in the flow-actions API, NOT from `delay_type`/`delay_amount` (those fields don't exist).
3. **For AB/branch variants** that fire at the same time as the preceding step, label them with the same Day and append `"· Variant A"` / `"· Variant B"`.
4. **For flows where the flat action list accumulates delays from all branches**, trace the main path manually by looking at which TIME_DELAY nodes sit between SEND_EMAIL nodes vs inside branch segments.
5. **Draft steps are excluded** — only steps with `status == 'live'` appear. Note any draft steps in a comment for future reference.

---

## Step 7 — Add TE tab to the canvas map dashboard

The dashboard at `http://localhost:8507` (`scripts/canvas_map_dashboard.py`) shows lifecycle flows for all brands. TE needs to be wired in after the board is built.

### 7a — Add TE to `BRAND_LABELS` in `canvas_map_dashboard.py`

```python
# Around line 215 — add "te" after "ti":
BRAND_LABELS = {
    "bur": "🛋 Burrow",
    "id":  "🪑 Interior Define",
    "hav": "🏠 Havenly",
    "cz":  "🌍 The Citizenry",
    "stf": "🎨 St. Frank",
    "ti":  "🏡 The Inside",
    "te":  "✏️ The Expert",   # add this line
}
```

### 7b — Add TE to `BRAND_SNOWFLAKE` in `lifecycle_canvas_map_dashboard.py`

TE has no Braze datashare and no GA4 (uses Stripe/HubSpot — Snowflake has no TE revenue data). Set both to None:

```python
# After the "ti" entry in BRAND_SNOWFLAKE:
"te": {"app_group_id": None, "db": None, "schema": None, "ga4": None},
```

Also add a guard in `fetch_klaviyo_stats_batch` so it doesn't crash when `ga4` is None:

```python
def fetch_klaviyo_stats_batch(brand: str, rows: list, client) -> dict:
    cfg = BRAND_SNOWFLAKE[brand]
    ga4 = cfg["ga4"]
    campaign_data: dict = {}
    if ga4:   # ← add this guard (TE has no GA4)
        try:
            results = client.execute_query(...)
            ...
        except Exception as e:
            print(f"  ⚠ batch GA4 query failed for {brand}: {e}")
    ...
```

### 7c — Add TE to `CANVASES` in `lifecycle_canvas_map_dashboard.py`

Build the `CANVASES["te"]` entry from the live flow data collected in Step 1. Use the same structure as TI. The `f` field is the screenshot filename from `campaigns/screenshots/` (the same `klv-flow-te-*` files — no path prefix needed, just the filename). The `canvas_ids` field holds the Klaviyo flow ID (e.g. `"SmPgUp"` for TI Welcome). `ga4_pattern` can be omitted or set to `None` since TE has no GA4.

```python
"te": {
    "label": "The Expert",
    "color": "#1a1a1a",
    "rows": [
        # Welcome Series splits into 3 rows by shopping_for branch
        {
            "name": "Welcome — Shopping for Clients",
            "entry": "New subscriber · shopping_for = clients",
            "canvas_ids": [],
            "ga4_pattern": None,
            "steps": [
                {"t": "T1 · Immediately", "s": "Welcome to The Expert",        "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                {"t": "T2 · Day 1",       "s": "Join The Expert Trade Program", "f": "klv-flow-flow-welcome-series-t07-VcTHRZ.png",    "f_dir": "ss"},
            ],
        },
        {
            "name": "Welcome — Shopping for Consultation",
            "entry": "New subscriber · shopping_for = consultation",
            "canvas_ids": [],
            "ga4_pattern": None,
            "steps": [
                {"t": "T1 · Immediately", "s": "Welcome to The Expert",                               "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                {"t": "T2 · Day 1",       "s": "Questions about consultations?",                      "f": "klv-flow-flow-welcome-series-t02-VmM9pi.png",    "f_dir": "ss"},
                {"t": "T3 · Day 1",       "s": "Our Experts' shopping secrets, revealed.",            "f": "klv-flow-flow-welcome-series-t03-U7K4a4.png",    "f_dir": "ss"},
                {"t": "T4 · Day 4",       "s": "A before & after signed Jake Arnold",                 "f": "klv-flow-flow-welcome-series-t04-YeYBsf.png",    "f_dir": "ss"},
                {"t": "T5 · Day 7",       "s": "Bring Miles Redd's iconic style home",               "f": "klv-flow-flow-welcome-series-t05-Yamm6R.png",    "f_dir": "ss"},
                {"t": "T6 · Day 10",      "s": "This tangerine-hued pantry borrows from the Brits",  "f": "klv-flow-flow-welcome-series-t06-YjHZ4R.png",    "f_dir": "ss"},
                {"t": "T7 · Day 13",      "s": "Caitlin Flemming's go-to wallpaper",                 "f": "klv-flow-flow-welcome-series-t13-QZBWMT.png",    "f_dir": "ss"},
            ],
        },
        {
            "name": "Welcome — Shopping for Myself",
            "entry": "New subscriber · shopping_for = myself (or other)",
            "canvas_ids": [],
            "ga4_pattern": None,
            "steps": [
                {"t": "T1 · Immediately", "s": "Welcome to The Expert",                               "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                {"t": "T2 · Day 2",       "s": "Our Experts' shopping secrets, revealed.",            "f": "klv-flow-flow-welcome-series-t08-SGJpcT.png",    "f_dir": "ss"},
                {"t": "T3 · Day 2",       "s": "Bring Miles Redd's iconic style home",               "f": "klv-flow-flow-welcome-series-t09-S3GkrK.png",    "f_dir": "ss"},
                {"t": "T4 · Day 7",       "s": "This tangerine-hued pantry borrows from the Brits",  "f": "klv-flow-flow-welcome-series-t10-Rwv4fe.png",    "f_dir": "ss"},
                {"t": "T5 · Day 10",      "s": "A before & after signed Jake Arnold",                "f": "klv-flow-flow-welcome-series-t11-TgTVBc.png",    "f_dir": "ss"},
                {"t": "T6 · Day 10",      "s": "Questions about consultations?",                     "f": "klv-flow-flow-welcome-series-t12-VJX7Vb.png",    "f_dir": "ss"},
                {"t": "T7 · Day 13",      "s": "Caitlin Flemming's go-to wallpaper",                 "f": "klv-flow-flow-welcome-series-t14-Y4jugu.png",    "f_dir": "ss"},
            ],
        },
        # ... one entry per live flow from Step 1
    ],
},
```

Screenshot `f` filename format: `klv-flow-{flow_slug[:30]}-t{seq:02d}-{msg_id[:8]}.png` — match the actual files in `campaigns/screenshots/` using `ls campaigns/screenshots/klv-flow-te-*.png`.

### 7d — Restart the dashboard

```bash
bash scripts/start_dashboards.sh
```

Then open `http://localhost:8507` and confirm the TE tab renders with the correct flows and step thumbnails.

---

## After building

1. Take a screenshot of the completed FigJam board (`mcp__figma__get_screenshot`) and share with Jordan
2. Update `docs/te-figjam-build-instructions.md` with:
   - The actual live flow definitions (names, step IDs, timing, subjects) found during the audit
   - The image hashes and FH values for each step (so the board can be rebuilt without re-uploading)
   - Any draft steps found during the audit (to track for future activation)
3. Add the TE board URL to MEMORY.md under "Lifecycle Canvas FigJam Board URLs"

---

## Pre-researched Flow: TE Trade Welcome Series

Already placed on the **Trade — Lifecycle Canvas Map** board (`5f6dP8IdpUYefFtskp1FeC`) as a second section below the HAV Trade Welcome Series (2026-06-22). Reuse this data when building the full TE board — do not re-audit this flow from scratch.

**Klaviyo flow:** `trade_program-welcome-June2026` · **Flow ID:** `Xzc85N` · **Trigger:** Added to List (trade approved)

### Step sequence

All delays are business-day-gated (Mon–Fri). Day numbers = minimum calendar days from list addition.

| Step | Timing | YAML seq | Subject | Preheader | Screenshot | Scaled height (260px) |
|---|---|---|---|---|---|---|
| T1 | Day 1 | t01-Tmjisd | Welcome to The Expert! | Shop faster. Save more. Stress Less. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t01-Tmjisd.png` | 1,603px |
| T2 | Day 3 | t02-SDEZuc | Better trade discounts are here! | 200+ brands. One unbeatable promise. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t02-SDEZuc.png` | 1,085px |
| T3 | Day 5 | t05-RW2Gwb | Excited to work with you! | *(none — plain text)* | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t05-RW2Gwb.png` | 347px |
| T4 | Day 7 | t06-RiZDTy | Everything you'd travel to find, just a click away | A curated world of design at your fingertips. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t06-RiZDTy.png` | 1,907px |
| T5 | Day 10 | t07-Renpya | Ready to declutter your inbox? | 100s of brands, 1 contact. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t07-Renpya.png` | 1,683px |
| T6 | Day 13 | t08-VmBWQm | We rep hundreds of brands. Let us help you source! | *(none — plain text)* | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t08-VmBWQm.png` | 347px |
| T7 | Day 16 | t09-Wx2MJd | You're in good company | Join designers who've found their sourcing home. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t09-Wx2MJd.png` | 1,940px |
| T8 | Day 19 | t10-UDXDSk | Loved by the trade. Exclusively ours. | Stop giving your clients déjà vu… | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t10-UDXDSk.png` | 2,400px |
| T9 | Day 22 | t11-XBNngF | We want to be your growth partner | Think of us as an extension of your team. | `campaigns/screenshots/klv-flow-trade_program-welcome-june2026-t11-XBNngF.png` | 1,458px |

### Delay structure (from Klaviyo API)

```
Entry → 1 biz day → T1
T1    → 2 biz days → T2 (A/B container, variant A only)
T2    → 2 biz days → T3
T3    → 2 biz days → T4
T4    → 3 biz days → T5
T5    → 3 biz days → T6
T6    → 3 biz days → T7
T7    → 3 biz days → T8
T8    → 3 biz days → T9
```

### T2 A/B test — treat as single step

T2 is wrapped in a Klaviyo AB_TEST container (action `109658149`) with 3 variants (t02/t03/t04). The API returns all as "live" but does not expose winner status. Jordan confirmed only **Variant A is sending**. Always use t02-SDEZuc for the screenshot. Do not label T2 with "· A/B" on any board.

### FigJam node IDs (Trade board, already placed)

| Element | Node ID |
|---|---|
| Divider line | 17:2 |
| Section title | 17:3 |
| Section subtitle | 17:4 |
| T1 card / screenshot | 17:5 / 17:9 |
| T2 card / screenshot | 17:10 / 17:14 |
| T3 card / screenshot | 17:15 / 17:18 |
| T4 card / screenshot | 17:19 / 17:23 |
| T5 card / screenshot | 17:24 / 17:28 |
| T6 card / screenshot | 17:29 / 17:32 |
| T7 card / screenshot | 17:33 / 17:37 |
| T8 card / screenshot | 17:38 / 17:42 |
| T9 card / screenshot | 17:43 / 17:47 |

### Regenerating screenshots

Screenshots were rendered via Playwright from local HTML files (YAMLs lack a `screenshot` field so `backfill_html_screenshots.py` skips them). To regenerate:

```python
from playwright.async_api import async_playwright

STEPS = [
    ("T1", "klv-flow-trade_program-welcome-june2026-t01-Tmjisd"),
    ("T2", "klv-flow-trade_program-welcome-june2026-t02-SDEZuc"),
    ("T3", "klv-flow-trade_program-welcome-june2026-t05-RW2Gwb"),
    ("T4", "klv-flow-trade_program-welcome-june2026-t06-RiZDTy"),
    ("T5", "klv-flow-trade_program-welcome-june2026-t07-Renpya"),
    ("T6", "klv-flow-trade_program-welcome-june2026-t08-VmBWQm"),
    ("T7", "klv-flow-trade_program-welcome-june2026-t09-Wx2MJd"),
    ("T8", "klv-flow-trade_program-welcome-june2026-t10-UDXDSk"),
    ("T9", "klv-flow-trade_program-welcome-june2026-t11-XBNngF"),
]
# viewport width=600, full_page=True, wait 1500ms
# Skip t03 and t04 (A/B variants)
```
