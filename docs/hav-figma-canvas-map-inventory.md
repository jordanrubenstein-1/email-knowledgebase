# HAV Figma Canvas Map — Row Inventory

Reference inventory of cards on the [Havenly Lifecycle Canvas Map](https://www.figma.com/board/UHfbjMJfByUpWQAXEw71Qu/HAV-%E2%80%94-Lifecycle-Canvas-Map) (Figma board). This board is the source of truth for what's displayed; this doc is a point-in-time mirror for anyone working from the repo who can't open Figma. Update it whenever a card is added/changed on the board — it will drift otherwise.

Note: this board is tracked separately from the locally hosted dashboard (`scripts/lifecycle_canvas_map_dashboard.py` / `http://localhost:8507`) — the two are not guaranteed to be in sync card-for-card. See CLAUDE.md's "FigJam ↔ Dashboard sync rule" for canvases that are meant to be kept in sync; this row (API-Triggered Transactional, one-off Braze *campaigns* rather than canvases) is not currently wired into the local dashboard config.

## API-Triggered Transactional

Row node: `169:2` (title `169:3`, subtitle `169:4`) on the board's single implicit page.

21 emails · API-triggered by order + account events

| Card | Trigger (timing label) | Subject | Note |
|---|---|---|---|
| Order placed | API · Order placed | Your order has been confirmed! - Order # | Transactional — no preheader |
| Partial order confirmed | API · Partial order confirmed | Part of your order has been confirmed! - Order #[#] | Transactional — no preheader |
| Quote requested | API · Quote requested | Expect your order quote soon - Order #[#] | Transactional — no preheader |
| Quote ready for approval | API · Quote ready for approval | Please approve your order quote - Order #[#] | Transactional — no preheader |
| Quote cancelled | API · Quote cancelled | Your order quote has been cancelled - Order #[#] | Transactional — no preheader |
| Order cancelled | API · Order cancelled | Your order has been cancelled - Order #[#] | Transactional — no preheader |
| Order ETA updated | API · Order ETA updated | We have an update on your order - Order #[#] | Transactional — no preheader |
| Return/cancel requested | API · Return/cancel requested | We received your return/cancellation request - Order #[#] | Transactional — no preheader |
| Project start date set | API · Project start date set | Complete room profile, check! | Transactional — no preheader |
| Schedule design review | API · Schedule design review | Schedule your design review | Transactional — no preheader |
| Concept ready | API · Concept ready | Your design concept is ready to review | Transactional · HTML not available |
| Final concept ready | API · Final concept ready | Your Final Concept is ready! | Transactional · HTML not available |
| Design review followup | API · Design review followup | Review your design in 3D with your designer | Transactional — no preheader |
| Cart from quote | API · Cart from quote | Your Havenly Quote | Transactional — no preheader |
| Package upgraded | API · Package upgraded | Design Package Change Confirmation | Transactional — no preheader |
| Payment declined | API · Payment declined | Action Needed: Payment Method Declined | Transactional — no preheader |
| Gift card en route | API · Gift card en route | Your Havenly gift card is en route! | Transactional — no preheader |
| Gift card order confirmed | API · Gift card order confirmed | Thank you for your gift card purchase | Transactional — no preheader |
| Gift card received (PC) | API · Gift card received (PC) | Someone Special Sent You A Gift! | Transactional — no preheader |
| **Designer tip submitted** *(added 2026-08-14)* | API · Designer tip submitted | You received a tip from a client | Transactional — no preheader |

### Designer tip submitted — detail

- **Braze campaign:** `OT_EM_2026_08_HAV_CONV_H_Designer_Tip_Details` (`campaigns/ot_em_2026_08_hav_conv_h_designer_tip_details.yaml`)
- **Braze campaign ID:** `6a7393c83a3d6900864a8c18`
- **Trigger:** client submits a tip for their designer
- **`trigger_properties` payload:** `clientFirstName`, `clientLastName`, `projectName`, `roomId`, `tipAmount`, `tipUrl`, `payoutMonth`
- **Audience:** designer (recipient is the designer being tipped, not the client)
- **Screenshot:** `campaigns/screenshots/rendered/canvas-api-triggered-designer-tip-details-3d6dbe48.png` (sample data substituted for the Liquid placeholders)
