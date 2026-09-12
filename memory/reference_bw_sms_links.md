---
name: reference_bw_sms_links
description: BUR (Burrow) link map — context → verified working URL (all channels)
metadata: 
  node_type: memory
  type: reference
  originSessionId: d528ecb5-2675-48f0-a728-d6511402b1dd
---

All URLs verified HTTP 200 as of 2026-05-29. Applies to all channels — email briefs, SMS, push.

Note: several `data/brand_config.yaml` paths were 404 and have been corrected here and in the config.

| Context | URL |
|---------|-----|
| Sale launch / reminder / EA / final hours | `https://burrow.com/` |
| Pet-friendly / performance fabric | `https://burrow.com/pet-friendly-furniture` |
| Nomad collection | `https://burrow.com/collections/nomad` |
| Range collection | `https://burrow.com/collections/range` |
| Shift collection | `https://burrow.com/collections/shift` |
| Union collection | `https://burrow.com/collections/union` |
| Sleeper sofas | `https://burrow.com/collections/sleeper-sofas` |
| Sofas / sectionals (general, no named collection) | `https://burrow.com/collections/shop-all-sofas` |
| Bedroom | `https://burrow.com/bedroom` |
| Seating (general category page) | `https://burrow.com/seating` |
| Dining / tables / dining chairs | `https://burrow.com/dining` |
| Rugs | `https://burrow.com/collections/rugs` |
| Outdoor | `https://burrow.com/outdoor` |
| Storage / shelves / media console | `https://burrow.com/storage` |
| Accent chairs | `https://burrow.com/collections/accent-chairs` |
| Quick Ship / ready to ship | `https://burrow.com/ready-to-ship` |
| Clearance | `https://burrow.com/collections/clearance` |
| Best sellers | `https://burrow.com/collections/best-sellers` |
| Swatches | `https://burrow.com/swatches` |
| Leather (no collection page) | `https://burrow.com/` |

**How to apply:** When writing a BUR brief (email or SMS), resolve `[link]` using this map based on the copy's content. If the copy mentions a named collection (Nomad, Range, Shift, Union), use that collection's URL. Always re-verify with curl if using a new or unfamiliar URL before including it in a brief.
