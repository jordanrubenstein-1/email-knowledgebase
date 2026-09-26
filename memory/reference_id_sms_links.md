---
name: reference_id_sms_links
description: ID (Interior Define) link map — context → verified working URL (all channels)
metadata: 
  node_type: memory
  type: reference
  originSessionId: d528ecb5-2675-48f0-a728-d6511402b1dd
---

All URLs verified HTTP 200 as of 2026-05-29. Applies to all channels — email briefs, SMS, push.

| Context | URL |
|---------|-----|
| Sale launch / reminder / EA (any "X% off sitewide") | `https://www.interiordefine.com/` |
| Swatch Talk / "request free swatches" | `https://swatches.interiordefine.com/` |
| New Arrivals | `https://www.interiordefine.com/new-arrivals` |
| Quick Ship | `https://www.interiordefine.com/quick-ship` |
| Named collection mentioned (Sloan, James, Tatum, etc.) | `https://www.interiordefine.com/{collection-name}` |
| Sofas (general, no named collection) | `https://www.interiordefine.com/living/all-custom-sofas` |
| Sectionals | `https://www.interiordefine.com/living/all-custom-sectionals` |
| Chairs | `https://www.interiordefine.com/living/all-custom-chairs` |
| Beds | `https://www.interiordefine.com/bedroom/all-beds` |
| Dining | `https://www.interiordefine.com/dining` |
| Rugs | `https://www.interiordefine.com/rugs` |
| Leather | `https://www.interiordefine.com/collections/leather` |
| Store callout / studio visit | `https://www.interiordefine.com/locations` |

**How to apply:** When writing an ID brief (email or SMS), resolve `[link]` using this map based on the copy's content. Always re-verify with curl if uncertain whether a new collection URL exists.
