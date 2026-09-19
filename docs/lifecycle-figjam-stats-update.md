# Lifecycle FigJam Stats — Manual Refresh Runbook

Refresh the rolling **12-week weekly averages** on the Burrow and Interior Define
lifecycle FigJam boards. This is normally done by the `update-lifecycle-figjam`
GitLab job every Monday (9am ET), but that job calls the `claude` CLI with an
**Anthropic Console API key** — when its prepaid credit balance runs out the job
fails with `Credit balance is too low`, and the boards must be refreshed manually
through a Claude session (which uses the subscription, not API credits).

**Trigger phrase:** "update the lifecycle figjam stats" / "refresh the lifecycle
FigJam boards".

Boards:
- **Burrow** — `VxjmwZuwCf3bsWfMGLOlOm` — https://www.figma.com/board/VxjmwZuwCf3bsWfMGLOlOm
- **Interior Define** — `IHASW2pUj5Zfy4ZKJlTyDR` — https://www.figma.com/board/IHASW2pUj5Zfy4ZKJlTyDR

Each row's stats live in a TEXT node named `lifecycle-stats::{brand}::{canvas-slug}`
(e.g. `lifecycle-stats::bur::abandon-cart`). Node **names are stable** — always
find nodes by name, not by node ID.

---

## Prerequisites

- Snowflake access (`.env`, `scripts/snowflake_client.py`) — Braze raw-events
  datashare + GA4 tables.
- Figma MCP write access. **Load the `figma-use` skill before any `use_figma`
  call** and pass `skillNames: "figma-use"`.
- These are FigJam boards (`/board/` URLs) — text nodes edit via `characters`
  after a font load.

---

## Steps

### 1. Compute the payloads

```bash
uv run python scripts/update_lifecycle_stats.py
```

The script queries Snowflake and prints a JSON block after the
`===PAYLOADS_JSON===` marker:

```json
{ "boards": {...}, "updates": { "<board_key>": { "<node_name>": "<text>", ... } } }
```

It **cannot** write to Figma itself — it only produces the text. Do not skip the
script and hand-write numbers; it encodes all the query logic and edge cases
below.

### 2. Apply each board's payloads via the Figma MCP

For **each board** (run the two boards as parallel `use_figma` calls — one sets
`currentPage` at most once), find each TEXT node by name and set its characters.
Load the node's current font first (all are `Inter / Medium`, but load from the
node to be safe):

```js
// fileKey = the board_key from the payload; updates = that board's {node_name: text}
const updates = /* paste the board's object here */;
const done = [], missing = [];
await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
for (const [name, text] of Object.entries(updates)) {
  const node = figma.currentPage.findAll(
    n => n.type === 'TEXT' && n.name === name
  )[0];
  if (!node) { missing.push(name); continue; }
  node.characters = text;
  done.push(node.id);
}
return { mutatedNodeIds: done, missing };
```

### 3. Verify

Read the nodes back and confirm the numbers landed:

```js
return figma.currentPage
  .findAll(n => n.type === 'TEXT' && n.name.startsWith('lifecycle-stats::'))
  .map(n => n.name + ' => ' + n.characters.split('\n')[1]); // the Sends/wk line
```

Report the refreshed values to the user (a small table per board is ideal).

---

## What the script computes (edge cases already handled)

All averages are **12-week totals ÷ 12**, rounded. Config lives at the top of
`scripts/update_lifecycle_stats.py`.

### Standard nodes (email)
`T1 Sends/wk · Sends/wk · Unique Opens/wk · UOR · Sessions/wk · Rev/wk · Rev/M`.
Sends/opens from the Braze datashare (opens include machine opens to match the
Braze dashboard); sessions/revenue from GA4 last-click by `SESSIONCAMPAIGNNAME`
pattern (`GA4_PATTERNS`).

### SMS-only nodes (`SMS_ONLY`)
`bur::sms-welcome`, `id::sms-welcome` — `T1 Sends/wk · Sends/wk · Sessions/wk ·
Rev/wk` (no Opens/UOR/Rev-M; sends from the SMS datashare).

### Combined email + SMS nodes (`SMS_SUBSECTION`)
`bur::abandon-browse-multi`, `bur::abandon-browse-product-viewed`,
`bur::abandon-cart`, `id::cart-abandon` get a `── SMS ──` sub-section
(`Sends/wk · Sessions/wk · Rev/wk`) below the email block.
- **SMS sends** come from `USERS_MESSAGES_SMS_SEND_SHARED` per `CANVAS_ID` — always
  reliable and per-canvas.
- **SMS sessions/revenue** come from GA4 (SMS channel). **Caveat:** the two BUR
  *browse* canvases share identical SMS campaign names
  (`TRG_SMS_..._BW_Abandon_Browse_T2/T5_V1`), so GA4 can't attribute
  sessions/revenue to one vs. the other — the script sets those to `—`
  (`sms_ga4_pattern: None`). The cart canvases have unique SMS names and
  attribute cleanly.

### Swatch-order nodes (`SWATCH_CANVASES`)
`id::swatch-cart-abandon` appends `Swatch Orders/wk`, from GA4
`KEYEVENTS:GENERATE_LEAD_SWATCH` (EMAIL channel, last-click — same basis as
revenue; the column exists only in the ID GA4 table).

---

## Adding / changing a row

- **New canvas row:** add its hex `CANVAS_ID`(s) to `CANVAS_IDS` and a GA4 pattern
  to `GA4_PATTERNS`, then create the matching `lifecycle-stats::{brand}::{slug}`
  TEXT node on the board.
- **New SMS sub-section:** add the slug to `SMS_SUBSECTION` (with `sms_ga4_pattern`
  or `None`).
- **New swatch line:** add the slug to `SWATCH_CANVASES` with its GA4 pattern
  (e.g. to also track swatch orders on `id::swatch-post-purchase`).
- Get real canvas hex IDs / campaign patterns from the datashare — never guess
  (`CANVAS_NAME ILIKE '%...%'` to find, then read `CANVAS_ID` / `CANVAS_STEP_NAME`).

---

## Gotchas

- **Font load is mandatory** before setting `characters`, or FigJam throws
  `Cannot write to node with unloaded font`.
- **`use_figma` is atomic** — a failed script makes no changes; fix and retry.
- The stats strings contain `—` (em-dash) and `──` (box-drawing) — the script
  prints them with `ensure_ascii=False`; keep them intact when applying.
- The underlying weekly job stays broken until the **Anthropic Console credit
  balance** behind its `ANTHROPIC_API_KEY` (GitLab → Settings → CI/CD →
  Variables) is topped up. Manual refreshes are the stopgap; enabling
  auto-reload in the Console fixes it permanently.
- Per the **FigJam ↔ Dashboard sync rule**, if any board structure changes
  (rows added/removed), mirror it in `scripts/canvas_map_dashboard.py`.
