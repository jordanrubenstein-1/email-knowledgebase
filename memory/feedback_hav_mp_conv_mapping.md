---
name: feedback_hav_mp_conv_mapping
description: HAV task name prefixes MP and DPS map to CONV and PC in Braze campaign names and audience settings
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 237e4d9c-81ed-4e07-9710-ae8b798563b2
---

## Rule: MP → CONV, DPS → PC in HAV campaign naming and audience selection

For Havenly email tasks, the Asana task name prefix determines the audience segment. **These prefixes must be stripped from the description** — they are never included in the Braze campaign name.

| Task name prefix | Audience | Campaign name segment |
|---|---|---|
| `MP:` or `MKPL:` | Converted (Marketplace) | `CONV` |
| `DPS:` | Pre-Converted (Design Service) | `PC` |
| `DPS and MP:` | Both (combined) | no audience code |
| No prefix | Default to PC | `PC` |

**Correct campaign name order:** `HAV_PC_PT` / `HAV_CONV_PT` — audience code (`PC`/`CONV`) comes **before** design type (`PT`/`D`). Confirmed from real sends (Apr–May 2026): `P_2026_04_10_HAV_PC_PT_AI_Free_Package`, `P_2026_04_30_HAV_CONV_PT_MDS_Refer_A_Friend`.

**Why:** The auto-builder defaulted to PC when a task named `MP: Summer Ready Flash Sale Last Chance` was processed — because it looked for `CONV` in the name. The `MP:` prefix was not recognized as a signal for CONV, resulting in:
- Campaign named `_PT_PC_MP_` instead of `_PT_CONV_`  
- PC audience segment selected instead of CONV
- PC conversion events configured instead of CONV
- Cascading QA false positives (sender check used PC config)

**How to apply:** In `build_pt_campaign.py`'s HAV variant detection and anywhere else HAV audience is inferred from task name:
1. Check for `MP:` prefix first → `hav_variant = "CONV"`
2. Then check for `CONV` in name → `hav_variant = "CONV"`
3. Otherwise → `hav_variant = "PC"`

Fix is in `build_pt_campaign.py` `build_campaign_config()` at the HAV variant detection block.
