---
name: reference_stf_links
description: STF (St. Frank) link map — context → verified working URL (all channels). Source of truth is data/stf_links.yaml.
metadata: 
  node_type: memory
  type: reference
  originSessionId: d528ecb5-2675-48f0-a728-d6511402b1dd
---

All URLs verified HTTP 200 as of 2026-05-29. Applies to all channels — email briefs and SMS.

**Source of truth:** `data/stf_links.yaml` — edit that file when a URL changes. `build_sms_campaign.py` loads link_paths from it automatically for STF; `create_calendar_tasks.py` `STF_EMAIL_IDEAS` references it via `_STF_LP`.

| Context | URL |
|---------|-----|
| Sale / promo / event | `https://www.stfrank.com/` |
| Best sellers | `https://www.stfrank.com/collections/best-seller` |
| New Arrivals | `https://www.stfrank.com/collections/new-arrivals` |
| Prints / POTM / Print Spotlight | `https://www.stfrank.com/collections/prints` |
| Kuba Cloth | `https://www.stfrank.com/collections/kuba-cloth` |
| Pillows | `https://www.stfrank.com/collections/pillows` |
| Outdoor Pillows | `https://www.stfrank.com/collections/outdoor-pillows` |
| Rugs | `https://www.stfrank.com/collections/rugs` |
| Wallpaper | `https://www.stfrank.com/collections/wallpaper` |
| Curtains / window treatments | `https://www.stfrank.com/collections/window-treatments` |
| Swatches | `https://www.stfrank.com/collections/swatches` |
| Surfboards | `https://www.stfrank.com/collections/surfboards` |
| Fabric by the Yard | `https://www.stfrank.com/collections/fabric-by-the-yard` |
| Outdoor Fabric | `https://www.stfrank.com/collections/outdoor-fabric` |
| Furniture / Studio By STF | `https://www.stfrank.com/collections/furniture` |
| Bedding | `https://www.stfrank.com/collections/bedding` |
| Throws / quilts | `https://www.stfrank.com/collections/quilts-throws` |

**How to apply:** When writing an STF brief (email or SMS), resolve `[link]` using this map. To update a URL, edit `data/stf_links.yaml` — both SMS and email will pick it up automatically.
