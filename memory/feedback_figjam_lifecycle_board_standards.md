---
name: figjam-lifecycle-board-standards
description: Standing rules for building lifecycle canvas FigJam boards across brands — always include SMS touchpoints and look up real timing from Braze datashare
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8290b35e-f5ec-4b4b-bd3c-c3f73d35693b
---

Always incorporate both email AND SMS touchpoints when building or updating lifecycle FigJam boards for any brand. Do not show only email steps even if the knowledgebase YAMLs only capture email channels.

**Why:** The Braze canvases often have SMS steps embedded alongside emails. Showing email-only misrepresents the actual flow cadence and makes it harder for the team to reason about multi-channel timing.

**How to apply:**
1. Call `braze_get_canvas` to inspect the full canvas structure — not just the YAML knowledgebase — and identify every message step by channel (email or SMS).
2. For each SMS step, create an SMS-style card (dark header bar with gold timing + white label, light purple body card with actual SMS copy from the canvas response).
3. Insert SMS cards at their correct sequence position, shifting any existing email cards right to make room. Update all T-number labels accordingly.
4. Update the flow count label (e.g. "4 emails" → "4 emails + 1 SMS").

**Footer content blocks — always look them up from the canvas HTML; never invent block names:**
- Every email HTML in `campaigns/html/` includes the actual Braze content block tags the canvas step uses. Grep the file for `content_blocks.${` to find the correct footer block name before rendering.
- Full per-brand footer block map is in `docs/lifecycle-figjam-board-setup.md § Step 3b`.
- CZ footers change seasonally (`CZ_Main_Footer_Spring_2025`, `_Summer_2025`, `_Fall_2025`, `_Holiday_2025`, etc.) — always check the specific canvas file; do not assume.
- CZ designed emails always include `Havenly_Footer_1`, `Havenly_Footer_2`, `Havenly_Footer_3` alongside the `CZ_Main_Footer` variant.

**Timing — always look it up from the datashare; never guess:**
- Use the method in `docs/lifecycle-figjam-board-setup.md § Step 5b`.
- Find a user who received a late-stage step in the canvas via `CANVAS_NAME ILIKE`.
- Pull their full journey (email + SMS) with `DATEDIFF('minute', LAG(...), ...)` to get real delays.
- Convert minutes to cumulative days/hours from T1 for the timing label (e.g. `T2 · Day 0 · 2 hrs`).
- Use `CANVAS_NAME ILIKE` rather than `CANVAS_ID` — the raw events views use the Braze BSON canvas ID which may not match the UUID in the YAML.
- Datashare by brand: BUR/HAV/CZ → primary datashare `DATALAKE_SHARING`; ID/STF → TIER3 `DATALAKE_SHARING_TIERED`.
