# TI (& TE) Lifecycle FigJam Board — Build Instructions

How to build or rebuild the [The Inside Lifecycle Canvas Map](https://www.figma.com/board/0GfQj3VJtQCSEslCo1SPjm/The-Inside-%E2%80%94-Lifecycle-Canvas-Map) (standalone board, fileKey `0GfQj3VJtQCSEslCo1SPjm`, single page id `0:1`), and how to port it to The Expert (TE).

**Note (corrected 2026-07-12):** this doc previously pointed at a stale copy embedded on page 2 (`277:2`) of the HAV board file (`UHfbjMJfByUpWQAXEw71Qu`) — that copy is not the live board and edits there don't show up for users. Always target `0GfQj3VJtQCSEslCo1SPjm` directly.

The board is built programmatically via the Figma Plugin API (`use_figma` MCP tool) — no drag-and-drop.

---

## Step 1 — Audit live flows and steps

**Do this before every build.** Only live flows with at least one live email step appear on the board. Klaviyo has separate statuses for the flow and each action — a flow can be live while individual steps are draft.

```python
import requests, os

API_KEY = os.getenv('KLAVIYO_API_KEY_TI')  # swap _TE for The Expert
headers = {'Authorization': f'Klaviyo-API-Key {API_KEY}', 'revision': '2024-10-15'}

# Paginate all flows (Klaviyo caps at 50/page — TI has 75+)
flows, url = [], 'https://a.klaviyo.com/api/flows/?page[size]=50'
while url:
    r = requests.get(url, headers=headers).json()
    flows.extend(r['data'])
    url = r.get('links', {}).get('next')
live_flows = [f for f in flows if f['attributes']['status'] == 'live']

# For each live flow, get live email actions only
for flow in live_flows:
    r = requests.get(
        f"https://a.klaviyo.com/api/flows/{flow['id']}/flow-actions/?page[size]=50",
        headers=headers
    ).json()
    live_email_actions = [
        a for a in r['data']
        if a['attributes']['status'] == 'live'
        and a['attributes']['action_type'].upper() == 'SEND_EMAIL'
    ]
    # Only include flows with at least one live email action

    # Get subject/preheader for each live action
    for action in live_email_actions:
        r2 = requests.get(
            f"https://a.klaviyo.com/api/flow-actions/{action['id']}/flow-messages/?include=template",
            headers=headers
        ).json()
        for msg in r2['data']:
            msg_id   = msg['id']   # key for IH and FH dicts
            subject  = msg['attributes']['content']['subject']
            preheader = msg['attributes']['content'].get('preview_text', '')
```

**Known TI draft steps (as of 2026-06-19) — re-audit on rebuild:**

| Flow | Draft step IDs (excluded from board) |
|------|--------------------------------------|
| Swatch Shipped | T3 — TZawGc |
| Order Delivered | T2 — XfZkTK, T4 — XD2npG |
| Delayed Order | T2, T3 (only T1/Ygma3w is live) |
| Shipped NS | T1a (UBPHGC, no sofa) and T1b (TzrDey, sofa) are the only two live actions |

---

## Step 2 — Crop screenshots

Source PNGs live in `campaigns/screenshots/` (`klv-flow-*.png`, 600px wide). Auto-crop whitespace before uploading:

```python
from PIL import Image

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
```

Display height formula: `FH = round(cropped_height × 260 / cropped_width)`

---

## Step 3 — Upload images to Figma

Use `mcp__figma__upload_assets` with `count: N` → POST each cropped PNG to its `submitUrl` → capture the returned `imageHash`. Hashes are board-specific and persist; re-upload if building in a new file.

---

## Step 4 — Build the board

Run the following via `mcp__figma__use_figma` targeting the board file.

### Layout constants & colors

```js
const SX=100, LW=140, SW=260, SG=40, LH=120, RG=120;
// SX = left margin · LW = label col width · SW = step card width
// SG = gap between cards · LH = label bar height · RG = row gap

const DARK ={r:0.11,g:0.13,b:0.17}; // navy — title bars, label bars
const GOLD ={r:0.98,g:0.75,b:0.27}; // gold — timing text
const WHITE={r:1,  g:1,  b:1  };    // white — subject line
const GREY ={r:0.6,g:0.6,b:0.6};    // grey — preheader + trigger
const PGREY={r:0.93,g:0.93,b:0.93}; // pale grey — screenshot background
const BLACK={r:0.05,g:0.05,b:0.05}; // black — flow name
const LPUR ={r:0.88,g:0.85,b:0.95}; // light purple — SMS body card
```

### Helper functions

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
```

### Email row builder

```js
function buildRow(rowY, flow) {
  const maxFH = Math.max(...flow.steps.map(s => FH[s.id] || 400));
  mkR(SX, rowY-44, 8, 44+LH+maxFH, DARK);                          // left accent bar
  mkT(SX+20, rowY-40, flow.name,    14, 'Semi Bold', BLACK);        // flow name
  mkT(SX+20, rowY-22, flow.trigger, 10, 'Regular',   GREY);         // trigger condition
  for (let i=0; i<flow.steps.length; i++) {
    const s=flow.steps[i], sx=SX+LW+i*(SW+SG), fh=FH[s.id]||400;
    mkR(sx, rowY,    SW, LH, DARK);                                  // label bar
    mkT(sx+10, rowY+ 8, s.t,    11, 'Semi Bold', GOLD,  SW-20);     // timing
    mkT(sx+10, rowY+26, s.subj, 10, 'Semi Bold', WHITE, SW-20);     // subject
    if(s.ph) mkT(sx+10, rowY+58, s.ph, 9, 'Regular', GREY, SW-20); // preheader
    const fr = mkR(sx, rowY+LH, SW, fh, PGREY);                     // screenshot rect
    if(IH[s.id]) fr.fills=[{type:'IMAGE',scaleMode:'FIT',imageHash:IH[s.id]}];
  }
  return rowY + LH + maxFH + RG;
}
```

### SMS row builder (no screenshot — text card)

```js
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
    mkR(sx, rowY+LH, SW, SMS_FH, LPUR);                             // light purple card
    mkT(sx+12, rowY+LH+14, s.body, 10, 'Regular', DARK, SW-24);    // SMS copy
  }
  return rowY + LH + SMS_FH + RG;
}
```

### Header + entry point

```js
await figma.loadFontAsync({family:"Inter",style:"Regular"});
await figma.loadFontAsync({family:"Inter",style:"Semi Bold"});
const page = figma.root.children.find(p=>p.id==='0:1');
await figma.setCurrentPageAsync(page);
for(const n of [...page.children]) n.remove(); // clear existing

mkT(SX, 20, 'The Inside — Lifecycle Canvas Map', 20, 'Semi Bold', DARK);

let rowY = 100;
for (const flow of FLOWS) {
  rowY = flow.type==='sms' ? buildSmsRow(rowY, flow) : buildRow(rowY, flow);
}
```

---

## TI Flow Definitions (live flows, live steps only — as of 2026-06-19)

```js
const FLOWS = [
  {type:'email', name:'Welcome Series', trigger:'Trigger: New subscriber', steps:[
    {id:'V885ai', t:'T1 · Immediately', subj:'Welcome to your design era 💫', ph:''},
    {id:'Sh4mfk', t:'T2 · +1 day',     subj:"Let's have a little fun", ph:''},
    {id:'WvLaRG', t:'T3 · +3 days',    subj:'Design it your way (because why settle?)', ph:''},
    {id:'Wmkqcc', t:'T4 · +4 days',    subj:'The best part? Making it yours.', ph:''},
    {id:'VQnBYB', t:'T5 · +6 days',    subj:'Final Call on 15% Off', ph:''},
    // Note: T5 SL is temporarily "25% Off" during 4th of July sale — revert after
  ]},
  {type:'sms', name:'SMS Welcome Series', trigger:'Trigger: New SMS subscriber', steps:[
    {t:'T1 · Immediately', label:'SMS',
     body:'Welcome to The Inside! Use code WELCOME15 for 15% off your first order. theinside.com'},
  ]},
  // Confirmed via Klaviyo flow-actions API 2026-07-12: TIME_DELAY 1800s (30 min) before T1, TIME_DELAY 345600s (4 days) before T2
  {type:'email', name:'Cart Abandon', trigger:'Trigger: Cart abandoned', steps:[
    {id:'RNrZz8', t:'T1 · Day 0 · 30 min', subj:'You left something behind…', ph:'We saved your order at The Inside.'},
    {id:'VRTBkb', t:'T2 · Day 4',          subj:'Did you forget something?',  ph:'We saved your order at The Inside.'},
  ]},
  // Flow VMTjse "Abandon: Browse Abandon new drip NONSWATCH" (live, created 2026-07-14). Trigger metric
  // ProductViewed (MtS3mW) filtered is_swatch=0. Confirmed via flow-actions API 2026-07-17: TIME_DELAY
  // 3600s (1 hr) before T1, TIME_DELAY 345600s (4 days) before T2. T2 reuses the same creative as T1
  // (only SL/PH differ), so both message IDs share one image hash (identical rendered bytes). Placed
  // directly under Cart Abandon (below the Cart Abandon SMS row on the live board).
  {type:'email', name:'Abandon Browse', trigger:'Trigger: Product viewed, no cart, no purchase', steps:[
    {id:'Tnspj8', t:'T1 · Day 0 · 1 hr', subj:'Still thinking about it?', ph:'We saved your picks at The Inside.'},
    {id:'YebFkR', t:'T2 · Day 4',        subj:'Your next move?',         ph:"Take another look before they're gone."},
  ]},
  {type:'email', name:'Order Placed', trigger:'Trigger: Order placed', steps:[
    {id:'UyMKn4', t:'T1 · Immediately', subj:'Your order is confirmed!', ph:"See what's coming..."},
  ]},
  // Both steps are T1 variants — branched by whether the order contains a sofa
  {type:'email', name:'Shipped (Non-Swatch)', trigger:'Trigger: Order shipped', steps:[
    {id:'UBPHGC', t:'T1a · Immediately · No sofa', subj:'Great news! Your items shipped.', ph:'Track your items here.'},
    {id:'TzrDey', t:'T1b · Immediately · Sofa',    subj:'Great news! Your items shipped.', ph:'Track your items here.'},
  ]},
  {type:'email', name:'Swatch Order Placed', trigger:'Trigger: Swatch order placed', steps:[
    {id:'NH95MZ', t:'T1 · Immediately', subj:'Your swatch order is confirmed', ph:'Heading your way soon'},
  ]},
  // T3 (TZawGc) and T5 (XhRQPu) are draft — numbering jumps T1, T2, T4, T6
  // T2 fires immediately after T1 via AB_TEST (no delay). Delays: T2→T4 = 5+1+2d = Day 8; T4→T6 = +2d = Day 10
  {type:'email', name:'Swatch Shipped', trigger:'Trigger: Swatch order shipped', steps:[
    {id:'XT9zCb', t:'T1 · Day 0',  subj:'Your next step ✨',          ph:'Bring your swatches to life'},
    {id:'YfhAvK', t:'T2 · Day 0',  subj:'Great news! Items shipped.', ph:'Up next: swatching.'},
    {id:'RUmmW8', t:'T4 · Day 8',  subj:'Best for a reason',          ph:'Shop furniture favorites'},
    {id:'WnyYhx', t:'T6 · Day 10', subj:'The reviews are in',         ph:'Spoiler: designers love The Inside'},
  ]},
  // T2 (XfZkTK) and T4 (XD2npG) are draft — shows T1 + T3
  {type:'email', name:'Order Delivered (Non-Swatch)', trigger:'Trigger: Order delivered', steps:[
    {id:'SRFgxb', t:'T1 · Immediately', subj:'Your order from The Inside has arrived!', ph:'Thank you!'},
    {id:'VNVeN8', t:'T3 · +14 days',    subj:'Complete your look.', ph:''},
  ]},
  // Only T1 is live
  {type:'email', name:'Delayed Order', trigger:'Trigger: Order delay detected', steps:[
    {id:'Ygma3w', t:'T1 · Immediately', subj:'We are still working on your order.', ph:''},
  ]},
  {type:'email', name:'Trade Swatch Shipped', trigger:'Trigger: Trade swatch order shipped', steps:[
    {id:'H9erkq', t:'T1 · Immediately',           subj:'Your free swatches have arrived.',  ph:'Questions? Let us help!'},
    {id:'YqFv7g', t:'T2 · +3 days',               subj:'The reviews are in.',               ph:'Spoiler: designers love The Inside'},
    {id:'XmFUDm', t:'T3 · +7 days',               subj:'Best for a reason',                 ph:'Shop furniture favorites'},
    {id:'YwCfuj', t:'T4 · +14 days',              subj:'Need More Swatches?',               ph:"Order more — they're free!"},
    {id:'WCfdCZ', t:'T5 · Immediately (shipped)', subj:'Your free swatches have shipped!',  ph:"Here's your tracking."},
  ]},
  {type:'email', name:'Waitlist — Added', trigger:'Trigger: Added to waitlist', steps:[
    {id:'VS5C9c', t:'T1 · Immediately', subj:'Thanks for joining the waitlist.', ph:''},
  ]},
  {type:'email', name:'Waitlist — Back in Stock', trigger:'Trigger: Item back in stock', steps:[
    {id:'YrTLY6', t:'T1 · Immediately', subj:'Great news! Your waitlisted product is back in stock.', ph:'Shop The Inside now.'},
  ]},
  {type:'email', name:'[TRADE] Swatch Order Placed', trigger:'Entry: Swatch order placed (trade account)', steps:[
    {id:'MZafkb', t:'T1 · Immediate', subj:'Your swatch order is confirmed', ph:'Heading your way soon'},
  ]},
  {type:'email', name:'Rapid Repeat: Rug Pad', trigger:'Entry: Fulfilled order — bed purchased, no rug pad', steps:[
    {id:'TEbeRS', t:'T1 · +7 days', subj:"Don't forget your Rug Pad!", ph:''},
  ]},
  // T2 and T3 are A/B variants (Variation A / Variation B) of the same step
  {type:'email', name:'Bed Foundation Rapid Repeat', trigger:'Entry: Fulfilled order — bed purchased, no foundation', steps:[
    {id:'TTT4YG', t:'T1', subj:"Don't forget your Bed Foundation!", ph:''},
    {id:'TdX6hj', t:'T2a · Variant A', subj:"Don't forget your Bed Foundation!", ph:''},
    {id:'RkTWrs', t:'T2b · Variant B', subj:'Your perfect Bed Foundation.', ph:''},
  ]},
  // 7 variants — one per bed style; label = bed style name, not T1/T2
  {type:'email', name:'Assembly Instructions', trigger:'Entry: Order fulfilled — bed style match (7 variants)', steps:[
    {id:'MD4L36', t:'Modern Platform',     subj:'Assembly instructions for your bed.', ph:''},
    {id:'QzTNpV', t:'Square Back',         subj:'Assembly instructions for your bed.', ph:''},
    {id:'SxDZVW', t:'Art Deco',            subj:'Assembly instructions for your bed.', ph:''},
    {id:'HPT9VG', t:'Tailored Platform',   subj:'Assembly instructions for your bed.', ph:''},
    {id:'TdKnCT', t:'Mid-Century Platform',subj:'Assembly instructions for your bed.', ph:''},
    {id:'RZuhVt', t:'Classic Wingback',    subj:'Assembly instructions for your bed.', ph:''},
    {id:'XJWHQx', t:'Regency',             subj:'Assembly instructions for your bed.', ph:''},
  ]},
  // Grouped into one row (like HAV transactionals)
  {type:'email', name:'Transactionals', trigger:'Forgot Password · Order Canceled · Order Refunded', steps:[
    {id:'PFrNZQ', t:'Forgot Password', subj:'Reset your password', ph:'Click here to reset your password.'},
    {id:'HcYF9F', t:'Order Canceled',  subj:'Your order has been canceled', ph:'Thank you for shopping at The Inside.'},
    {id:'QcUG4j', t:'Order Refunded',  subj:'Your refund is being processed.', ph:'Thank you for shopping at The Inside.'},
  ]},
];
```

---

## TI Image Hashes & Display Heights

Image hashes are board-specific — valid for fileKey `0GfQj3VJtQCSEslCo1SPjm` (standalone TI board). Re-upload if rebuilding in a different file.

| Message ID | Image Hash | FH (px) |
|-----------|-----------|---------|
| V885ai | 98d9d88491d8c5f1c15e15c9b3ea41c8826808d3 | 1635 |
| Sh4mfk | a78e292617d08acb6d1a1059baeb840ecbf59a62 | 1248 |
| WvLaRG | 6f6d7006ec00585fedcf9c444c5f380928fb984c | 1702 |
| Wmkqcc | 8ef3e1184bdf433e86067af36015dc6fe0602209 | 1909 |
| VQnBYB | b73edbda5185cbb9e0725d9ccc953bbdd896f66c | 1459 |
| RNrZz8 | 641772b595496ca86f57823d26b0b7d5fd33cf2e | 927 |
| VRTBkb | ef9455c58e9195c935f9059e2c03ac504e8a0815 | 891 |
| UyMKn4 | d6069d4e30057f514f8e975fce46364b706f487d | 1441 |
| UBPHGC | 9dfd69f153ae63a943d6c546894597649718d895 | 839 |
| TzrDey | 280a24a6e58c64f8f5e07fc2b8ffad6d03798670 | 715 |
| NH95MZ | bfd19d6db99bb83f05ff18070b7db2c23d67adbb | 1362 |
| XT9zCb | 5950d2576ace6944516545f9e1fd49a53a5cf4d1 | 1382 |
| YfhAvK | e056a1baf9adb85f995498fb82e81dbce74ce58e | 1203 |
| RUmmW8 | e6f18a3b31ba1811be1036637dd4b9f451511841 | 938 |
| XhRQPu | 14546e09240423f6aefaabc57b40ed0fdf3cee7d | 729 |
| WnyYhx | 325d4c780ce34f1d3bfbd6b7282e14a137e319d0 | 1000 |
| SRFgxb | 9344156009f2aacfb16ec04205bd871530b02cb5 | 826 |
| VNVeN8 | 3592b7d18e9c69ecc620f01ce30a68074c80b52e | 697 |
| Ygma3w | 9529592fd40aa34844afdd9d6e9ade6466eb27cf | 342 |
| H9erkq | 56e5e452d59a40429f95ee18dc25fe54124a858e | 819 |
| YqFv7g | d041c3396969e69746b04226e46564d801314ef0 | 1163 |
| XmFUDm | c3b0048ea3416a959e98bb0d31f7cad2ce1df1d6 | 1076 |
| YwCfuj | becef66064c2128851c6889687d2849fe6848c0a | 596 |
| WCfdCZ | 456f6d6480091f7b156b5eefd017c7c046dddbf4 | 1215 |
| VS5C9c | e3b19a0c6973eef06d56f6b7e1672f95117fc16a | 497 |
| YrTLY6 | 75d231a4b24c40a99af98242bb7cb50d7f0d06c8 | 556 |
| MZafkb | e69c435401ffd44f394fbc281f80d134585d7c50 | 1428 |
| TEbeRS | f731b756ec7b40daf4cdb928b7511492fd148653 | 619 |
| TTT4YG | 9cbd548b4bf96b18549b73476b219ea2afb143ac | 572 |
| TdX6hj | 2b11cb6614246f05c87f528e34d9908cd4e2dda8 | 641 |
| RkTWrs | 2b11cb6614246f05c87f528e34d9908cd4e2dda8 | 641 |
| MD4L36 | d36c1e90da929a5c18a2e654cbdd3c13a6cf5b3e | 143 |
| QzTNpV | 0412f04677959baa1463eaa6c02a59c86cb2b99c | 136 |
| SxDZVW | e073f1d82ce175bb987e7e8b2400c61ab5a85d3b | 136 |
| HPT9VG | 3d6aa002f3d419be47d95cb05e43f76106213698 | 136 |
| TdKnCT | a5b6d1ea5138bcd79413a8bf65a51341f2da11ab | 144 |
| RZuhVt | e29ac7e41bd7e09e5bd05806927e97aae540eed3 | 136 |
| XJWHQx | b74509eb320ac797b941bbfb12b1f11f9b1ca720 | 136 |
| PFrNZQ | 62799d3434dbeda06025abb4a3ee10aacd911be6 | 384 |
| HcYF9F | 018b823c19d8bfde42de2ab1ba074bc9c906416a | 548 |
| QcUG4j | 87739c75cfcf4e69b77709d7b75e2e05e98f3577 | 542 |
| Tnspj8 (Abandon Browse T1) | 81652c4bb7546ad0ed05476e28b48f0815ba6b42 | 883 |
| YebFkR (Abandon Browse T2) | 81652c4bb7546ad0ed05476e28b48f0815ba6b42 | 883 |

---

## Porting to The Expert (TE)

Same layout, colors, and builder functions — only the data changes.

1. Run the live flow audit above with `KLAVIYO_API_KEY_TE`
2. Screenshots: `campaigns/screenshots/klv-flow-te-*.png` — backfill if missing:
   ```bash
   uv run python scripts/backfill_html_screenshots.py --brand TE
   ```
3. Crop + upload PNGs to get new `IH` and `FH` values
4. Create or target an existing TE FigJam board; update the page node ID
5. Build using the same `buildRow` / `buildSmsRow` functions with TE `FLOWS` data

TE flow types to expect: Welcome, New Arrivals, Home Tour, Showroom, Best of Month, New Dates, Trade variants.
