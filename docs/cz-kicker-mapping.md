# CZ Kicker Module Mapping

Which kicker modules go with each CZ Figma template (A–O).

---

## Kicker Module Reference

| Module | Description |
|--------|-------------|
| **YMAL** | Personalized product recs. Content block: `{{content_blocks.${product_recs}}}`. Hides itself if no anchor exists — always safe to include. Place *above* the link farm. |
| **Text link farm** | All-category text links (Rugs, Bedding, Bath, Furniture, Pillows & Throws, etc.) |
| **Image link farm** | Same categories, image-block version |
| **Swatches** | "Order your free swatch samples" CTA — MTO furniture content only |
| **Back in Stock** | Restocked product spotlight CTA |
| **Archive Sale** | Archive sale CTA block |
| **New Arrivals** | "See what's new" CTA |
| **Fair Trade Guaranteed** | Brand values / mission block |

**Cycling rule:** For templates that rotate between kicker options, avoid using the same named kicker more than 2 days in a row. Link farms (text or image) are exempt from this rule and can appear on back-to-back days.

---

## Template Mapping

### A. Multi-Hero
*MTO furniture, specific product feature, product launch, artisan story*
*Length: Long (3 hero sections)*

No link farm — too long. Choose one short kicker based on the email topic, then cycle to avoid repeats:

| Email topic | Kicker |
|-------------|--------|
| MTO / furniture | **Swatches** |
| Product launch | **New Arrivals** |
| Artisan story | **Fair Trade Guaranteed** |

---

### B. Product Feature Full Bleed
*Sale last chance/reminder, gift guides, single strong product feature*
*Length: Medium — has built-in Kicker HED/DEK/CTA slot*

Uses the built-in kicker slot. Cycle (avoiding repeats):
- Archive Sale
- New Arrivals
- Back in Stock
- Fair Trade Guaranteed

No additional modules appended below.

---

### C. Destination
*Destination editorial, travel and culture storytelling*
*Length: Medium — has built-in Kicker CTA slot*

Built-in kicker slot (primary: **Fair Trade Guaranteed**; alt: **New Arrivals**) + **text link farm** appended below.

---

### D. Get the Look
*Shop the look, styled room, bedding layers, pillow pairings, rugs*
*Length: Medium-long (hero + 4 product image blocks)*

**YMAL** above + **text link farm** below. Skip link farm if the email runs long.

---

### E. Color Edit
*Color palette editorial, seasonal color story*
*Length: Medium — has built-in Kicker HED/DEK/CTA slot*

Uses the built-in kicker slot. Cycle (avoiding repeats):
- **Back in Stock** (primary — confirmed on Color Edit Desert Clay)
- New Arrivals
- Swatches (for bedding or fabric color stories)

No additional modules appended.

---

### F. Archive Sale
*Archive sale, clearance, end-of-season sale*
*Length: Long — body already has New Arrivals + Back in Stock shop blocks*

**No kicker appended.** The template body IS the New Arrivals + Back in Stock 50/50 structure. No YMAL either (recs pull from the full catalog, not archive-specific inventory).

---

### G. Furniture by Room
*Furniture by room, shop by room, MTO furniture*
*Length: Very long (4 room sections)*

No kicker by default. Add **Swatches** only if the email has an explicit MTO ordering CTA.

---

### H. Shop by Category
*Sale launch, early access, sale reminder, last chance, bedding sale*
*Length: Medium (hero + 6 category image blocks)*

**YMAL** above + **image link farm** below. Image link farm preferred over text for sale emails.

---

### I. Rugs
*Rugs feature, rug sale, rug-focused editorial*
*Length: Short-medium*

**YMAL** above + **text link farm** below. If the angle is restocked rugs specifically, consider swapping to a **Back in Stock** kicker instead.

---

### J. Hero Only
*Spring preview, collection launch, specific product feature, Meadow Press*
*Length: Short (hero only)*

**YMAL** above + **text link farm** (standard). For sale or event heroes: use **image link farm** instead of text.

---

### K. Back in Stock
*Back in stock announcement, restocked products*
*Length: Short (hero only)*

**YMAL** above + **text link farm** below. No Back in Stock kicker — the email is already a BIS email.

---

### L. Monthly Edit
*Monthly edit, trend forecast, newsletter, seasonal recap*
*Length: Long — has Kicker 1 and Kicker 3 built-in slots*

Uses both built-in kicker slots. Cycle pairs from the pool, picking two different options and avoiding repeats vs. adjacent emails:

- Archive Sale
- Fair Trade Guaranteed
- New Arrivals
- Back in Stock
- Swatches

Example (May 2026): Kicker 1 = Archive Sale, Kicker 3 = Fair Trade Guaranteed.

No additional modules appended.

---

### M. General Edit
*The Spa Edit, bedding guide, bath essentials, shop by category editorial*
*Length: Medium (hero + 4 category blocks)*

**YMAL** above + **text link farm** below. Text preferred over image link farm for spa/bath editorial feel.

---

### N. UGC
*UGC campaign, community showcase, customer-styled photos*
*Length: Medium (5 UGC sections)*

**YMAL** above + **text link farm** below.

---

### O. Meet the Makers
*Artisan story, maker spotlight, destination with craft narrative*
*Length: Short*

**Fair Trade Guaranteed** kicker (primary — reinforces brand mission after artisan story) + **text link farm** below. If Fair Trade Guaranteed was used in an adjacent email, swap to **YMAL** instead.

---

## Quick Reference Table

| Template | Task description output |
|----------|------------------------|
| **A** Multi-Hero | `Kicker modules:` · one of: Swatches / New Arrivals / Fair Trade Guaranteed *(cycled)* |
| **B** Product Feature Full Bleed | `Kicker modules:` · one of: Archive Sale / New Arrivals / Back in Stock / Fair Trade Guaranteed *(cycled)* |
| **C** Destination | `Kicker modules:` · one of: Fair Trade Guaranteed / New Arrivals *(cycled)* · Text link farm |
| **D** Get the Look | `Kicker modules:` · YMAL · Text link farm |
| **E** Color Edit | `Kicker modules:` · one of: Back in Stock / New Arrivals / Swatches *(cycled)* |
| **F** Archive Sale | `Kicker modules:` · New Arrivals image block · Back in Stock image block |
| **G** Furniture by Room | `Kicker: None` |
| **H** Shop by Category | `Kicker modules:` · YMAL · Image link farm |
| **I** Rugs | `Kicker modules:` · YMAL · Text link farm |
| **J** Hero Only | `Kicker modules:` · YMAL · Text link farm |
| **K** Back in Stock | `Kicker modules:` · YMAL · Text link farm |
| **L** Monthly Edit | `Kicker modules:` · two of: Archive Sale / Fair Trade Guaranteed / New Arrivals / Back in Stock / Swatches *(cycled pair)* |
| **M** General Edit | `Kicker modules:` · YMAL · Text link farm |
| **N** UGC | `Kicker modules:` · YMAL · Text link farm |
| **O** Meet the Makers | `Kicker modules:` · one of: Fair Trade Guaranteed / YMAL *(cycled)* · Text link farm |
