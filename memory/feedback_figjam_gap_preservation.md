---
name: figjam-gap-preservation
description: "Universal gap-preservation rule for all lifecycle FigJam boards: measure actual visual gap after any frame resize or new card, then restore it to the board's target gap. Applies to BUR, ID, HAV, CZ, and all future brand boards."
metadata:
  node_type: memory
  type: feedback
  originSessionId: f902461a-0790-4266-8f1c-9f471e2c6e63
---

Whenever any frame on a lifecycle FigJam board grows taller — due to adding a content block, importing a new screenshot, adding a new card, or resizing a placeholder — shift every subsequent row to restore the board's target inter-row visual gap.

**Why:** Blindly shifting by the raw height delta preserves whatever gap existed before, which may itself have been wrong (see CZ Cart Abandon incident where a pre-existing 520px gap ballooned to 526px instead of correcting to 126px). Always measure, then fix.

**How to apply — universal procedure:**

1. **Before making changes**, note the current heights of any frames you'll modify.
2. **After resizing**, run a gap measurement script (see below) to get the actual visual gap between the modified row's content bottom and the next row's top.
3. **Compare to the board's target gap** (see per-board tables below).
4. **Shift all subsequent rows** by `(current_gap - target_gap)` in the correct direction — UP if gap is too large, DOWN if too small.
5. **Apply to all `figma.currentPage.children`** with `node.y >= threshold` in one `use_figma` call. Pick threshold safely between the modified row's content and the next row's top.
6. **Verify** by re-running the gap measurement.

**For new boards:** Before making ANY frame changes, run the gap measurement script to establish the baseline target gap. Save it to this memory file.

---

## Two board structure types

### Type A — Title bar spans full row height (HAV, ID)
- Each row has a RECTANGLE named `"Row: X — title bar"` that spans the full row height
- Gap = `next_titleBar.y − (prev_titleBar.y + prev_titleBar.height)`
- When a row's content grows: resize the title bar `height += growth`, shift all subsequent rows down by `growth`

### Type B — Flat layout, screenshots as top-level nodes (CZ, BUR)
- Row headers are short TEXT/RECTANGLE nodes at the top; screenshot frames sit below
- Gap = `next_rowHeader.y − max(screenshot.y + screenshot.height)` for screenshots in the current row
- **CZ** screenshots: RECTANGLE nodes named `ph__*`
- **BUR** screenshots: FRAME nodes named `canvas-*.png`

---

## Per-board target gaps

### HAV — `UHfbjMJfByUpWQAXEw71Qu` (Type A)
**Target gap:** **76px** between each title bar's bottom and the next title bar's top

| Row | Title bar node | y | h |
|---|---|---|---|
| Welcome Stream | `50:2` | 48 | 2691 |
| Design Fee Abandon | `39:2` | 2808 | 1216 |
| Room Profile Complete | `1:2` | 4122 | 1632 |
| Shopping Prompts | `70:2` | 5815 | 1065 |
| Abandon Merch Cart | `82:2` | 6956 | 723 |
| HIP Profile Complete | `91:2` | 7755 | 378 |
| AI Session Welcome | `78:2` | 8209 | 568 |
| AI Session Welcome PU | `86:2` | 8853 | 607 |
| AI Session Free Design | `96:2` | 9536 | 471 |
| Studio 6 Follow Up | `100:2` | 10083 | 830 |

### CZ — `yhfQv32GCWNOfwEerlMORd` (Type B)
**Target gap:** **126px** between tallest `ph__*` bottom and next row title y

| Row | Title text node | y (as of 2026-06-05) |
|---|---|---|
| Welcome Flow | `1:3` | 206 |
| Cart Abandon | `1:43` | 2434 |
| Product Browse | `1:59` | ~3973 |
| Post Purchase | `1:91` | ~5111 |
| Swatch Post Purchase | `1:119` | ~7052 |
| Waitlist Release | `1:155` | ~8997 |
| Waitlist Confirmation | `99:76` | ~9421 |
| SMS Welcome | `102:3` | ~10593 |

**Cart Abandon screenshot heights (as of 2026-06-05):**
- `134:5` ph__Cart Abandon__T3 → h=1311 (tallest; FIT mode, 260×1311)

### BUR — `VxjmwZuwCf3bsWfMGLOlOm` (Type B)
**Target gap:** ~**96px** between tallest `canvas-*.png` FRAME bottom and next row header y

Screenshot FRAMEs sit at y=-628 (Welcome), y=1210 (Post-Order Welcome), y=4294 (Abandon Cart), y=5744 (Swatch Post Purchase). Tallest frames typically ~1634px (email renders). Row header TEXT nodes sit ~96px above the frame starts.

**Measure before modifying** — run the gap measurement script to confirm current gaps before any changes.

### ID — `IHASW2pUj5Zfy4ZKJlTyDR` (Type A)
**Target gap:** varies by row pair (72–117px); see table below.

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

| Row | Node ID | y | h |
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

### Future boards (STF, TI, TE, others)
When creating a new FigJam board for any brand: after adding the first two rows, run the gap measurement script to record the target gap here before making further changes.

---

## Gap measurement script (reusable)

**Type A boards (HAV, ID) — title bars span row height:**
```javascript
const bars = page.children
  .filter(n => n.type === 'RECTANGLE' && n.name.includes('title bar'))
  .sort((a, b) => a.y - b.y);
const gaps = [];
for (let i = 0; i < bars.length - 1; i++) {
  gaps.push({ from: bars[i].name, to: bars[i+1].name,
              gap: bars[i+1].y - (bars[i].y + bars[i].height) });
}
return gaps;
```

**Type B boards (CZ — ph__ rects; BUR — canvas-* frames):**
```javascript
// CZ:
const phs = page.findAll(n => n.type === 'RECTANGLE' && n.name.startsWith('ph__'));
// BUR:
const phs = page.findAll(n => n.type === 'FRAME' && n.name.startsWith('canvas-'));
// Then for each row, find max(ph.y + ph.height) and gap to next row header y
```

---

## ID — additional notes

### welcome_promo — always evergreen branch
When rendering ID Welcome Series emails for the FigJam board, always use the evergreen `{% else %}` branch of `welcome_promo`. The cached version in `data/content_blocks/id.json` contains only the evergreen branch.

### ID content block API key
`BRAZE_USERS_API_KEY_ID` in `.env` (`03177b46-ac76-4b31-bda9-0d82545e76bf`) has content block read permissions.
