---
name: reference_ti_links
description: TI (The Inside) link map — context → verified working URL (all channels)
metadata: 
  node_type: memory
  type: reference
  originSessionId: d528ecb5-2675-48f0-a728-d6511402b1dd
---

All URLs verified HTTP 200 as of 2026-05-29. Applies to all channels — email briefs and SMS.

**Important:** Never use `/collections/sale` as a default for TI SMS — always use the homepage. `/collections/best-sellers` (hyphenated) redirects to the beds page — use `/collections/bestsellers` (no hyphen).

For editorial, destination, and print-specific send URLs, refer to `data/ti_links.yaml` (full catalog).

| Context | URL |
|---------|-----|
| Sale / promo / event | `https://www.theinside.com/` |
| New Arrivals | `https://www.theinside.com/collections/new-arrivals` |
| Best Sellers | `https://www.theinside.com/collections/bestsellers` |
| Beds / bedroom | `https://www.theinside.com/c/bedroom-furniture/beds` |
| Sofas | `https://www.theinside.com/c/living-room-furniture/sofas` |
| Accent chairs | `https://www.theinside.com/c/living-room-furniture/chairs` |
| Ottomans | `https://www.theinside.com/c/living-room-furniture/ottomans` |
| Curtains / drapes | `https://www.theinside.com/c/home-decor/curtains` |
| Throw pillows | `https://www.theinside.com/c/home-decor/throw-pillows` |
| Dining chairs | `https://www.theinside.com/c/dining-room/dining-chairs` |
| Wallpaper | `https://www.theinside.com/c/home-decor/wallpaper` |
| Bedding / sheets | `https://www.theinside.com/collections/all-bedding` |
| Outdoor | `https://www.theinside.com/collections/outdoorliving` |
| All furniture | `https://www.theinside.com/collections/furniture` |
| Fabric swatches | `https://www.theinside.com/fabric-swatches` |
| Trade program | `https://www.theinside.com/design-trade-services` |

**How to apply:** When writing a TI brief (email or SMS), resolve `[link]` using this map. For named print or destination collections (Bloomsbury, Ireland, etc.), look up the exact URL in `data/ti_links.yaml` — don't guess.
