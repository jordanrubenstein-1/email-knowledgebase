---
name: HAV Color Block PT Template
description: When user asks for "color block" or "colorblock" HAV email, use components/hav_colorblock_pt_template.html — do not re-fetch from Braze
type: reference
originSessionId: 8dec6358-065c-4829-a86b-d60a0d64d507
---
When the user says "color block" or "colorblock" for a HAV email template, use the saved component at `components/hav_colorblock_pt_template.html`.

**Structure:** 600px wide, 3-column table (35px coral `#ed6b4d` left bar | 530px white content | 35px gold `#e59400` right bar), spans 3 rows via `rowspan="3"`.

| Row | Element | Key styles |
|-----|---------|-----------|
| 1 | Header | `#c2b04a` bg, Havenly wordmark (white, 120px wide) |
| 2 | Body | `#FFFFFF` bg, `padding: 24px 20px 36px 20px`, Helvetica 14px `#101b24` |
| 3 | Footer bar | `#304561` (navy) bg, H icon 40px right-aligned |
| Below | Unsubscribe | `{{content_blocks.${unsubscribe} | id: 'cb1'}}` centered |

**Button style:** `#CD8F52` bg, white text, `border-radius: 50px`, uppercase, 18px, `padding: 14px 32px` — use a nested `<table>` with `text-align: center` for the button row.

**Image URLs (already on Braze CDN):**
- Wordmark: `https://braze-images.com/appboy/communication/assets/image_assets/images/697a85e045042100652b5d66/original.png?1769637344`
- H icon: `https://braze-images.com/appboy/communication/assets/image_assets/images/697a85e4b446f100635ef81c/original.png?1769637348`

**Source campaign:** `P_2026_04_10_HAV_PC_PT_AI_Free_Package` (Braze campaign ID `f3e57de6-9735-41bb-8cad-3bcf99a76baf`)

**First use as Email Template:** `P_2026_04_30_HAV_CONV_PT_MDS_Refer_A_Friend` (template ID `b70efe14-aada-489e-9fae-04d6d2c99fa5`)
