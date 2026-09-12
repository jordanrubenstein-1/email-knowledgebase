# Figma Template Catalogs

Full node-ID reference for brands whose templates are auto-selected by `create_calendar_tasks.py`. Claude uses these for manual lookups; the script calls `pick_*_template()` automatically during calendar task creation.

---

## Burrow (BW) Email Figma Templates

File key: `iOd6uooBKdfJGHboJ8wLvJ` — [Burrow Email CRM Templates](https://www.figma.com/design/iOd6uooBKdfJGHboJ8wLvJ/Burrow-Email-CRM-Templates)
URL format: `?node-id=[NODE_ID_HYPHENATED]`

### Collection Spotlight (single product or collection)

| Template | Node ID | Best For |
|----------|---------|----------|
| Collection Spotlight V1 | 5:30 | Single chair or accent piece — hero + feature + 2 lifestyle + small product row |
| Collection Spotlight V2 | 5:67 | Shelving/storage with many SKUs — hero + lifestyle + 2×3 grid |
| Collection Spotlight V3 | 5:143 | Sofa/sleeper launch with feature callouts — dark hero + icons + lifestyle + 2×2 grid |
| Collection Spotlight V4 | 5:226 | Named sofa collection with multiple configs — lifestyle hero + icon row + collection rows |
| Collection Spotlight V5 | 5:404 | Editorial/brand story — 5 stacked full-bleed lifestyle images with text overlays |
| Collection Spotlight V6 | 5:469 | Media console / entertainment furniture — hero + specs + lifestyle + 2×2 grid |
| Collection Spotlight V7 | 5:533 | Flagship sofa families with many configs — lifestyle hero + icons + sofa browsing + grid |

### Multi Collection Spotlight (3+ products or multiple categories)

| Template | Node ID | Best For |
|----------|---------|----------|
| Multi Collection Spotlight V1 | 7:1094 | Outdoor / 2-category — hero + 2 collection sections each with lifestyle + products |
| Multi Collection Spotlight V2 | 7:1138 | Large sofa or sectional collection — hero + 3–4 sections |
| Multi Collection Spotlight V3 | 7:1223 | Curated edit / bestsellers (3 items) — dark banner + 3 products alternating |
| Multi Collection Spotlight V4 | 7:1248 | Outdoor / 3 categories — full-bleed hero + alternating left/right layout |
| Multi Collection Spotlight V5 | 7:1281 | Dining multi-category — dark hero + 3 category sections (chairs/tables/stools) |
| Multi Collection Spotlight V6 | 7:1337 | Gift guide / whole-home — hero + 3+ room sections |
| Multi Collection Spotlight V7 | 7:1396 | Storage/organization — dark tagline hero + 3 storage product sections |
| Multi Collection Spotlight V8 | 7:1444 | Modern dining (4 products) — hero + 4 alternating layout |
| Multi Collection Spotlight V9 | 7:1811 | Sale with seating — 4 products with pricing/sale tags |
| Multi Collection Spotlight V10 | 7:1494 | New colorways / fabric launch — hero + 3 products alternating by color |
| Multi Collection Spotlight V11 | 7:1556 | Small space / apartment — hero + 3 sections (seating/sleeping/storage) |
| Multi Collection Spotlight V12 | 7:1689 | Bedroom collection — hero + 3 bedroom sections |
| Multi Collection Spotlight V13 | 7:1752 | Dining tables (3 options) — hero + 3 table spotlights with variants |
| Multi Collection Spotlight V14 | 7:1632 | Whole-home / new arrivals — hero + 3–4 room sections |

### Other Template Families

| Template | Node ID | Best For |
|----------|---------|----------|
| Retail Event V1 | 2:30 | Compact event announcement — sofa hero with event overlay |
| Retail Event V2 | 2:74 | Detailed retail event invite with when/where + venue photos |
| Retail Event V3 | 2:136 | Compact retail event + product showcase |
| Fabric Spotlight V1 | 2:275 | Single fabric launch — close-up hero + story + lifestyle + product grid |
| Multi Fabric Spotlight V1 | 3:230 | Leather / premium material spotlight — hero + 3 product spotlights |
| Fabric Spotlight V2 | 3:154 | Feature-forward single fabric — dark hero + icon callouts + product grid |
| Multi Fabric Spotlight V2 | 3:30 | Full fabric collection overview — hero + 3 fabric-type sections |
| Quick Ship V1 | 7:2 | Standard quick-ship — lifestyle hero + 2×2 grid |
| Quick Ship V2 | 7:336 | Quick-ship + sale promotion — promo % off hero + product grid |
| Quick Ship V3 | 7:447 | Editorial quick-ship — full-bleed hero + 4 alternating products |
| Best Sellers V1 | 6:558 | Flagship bestsellers — hero + 3–4 stacked products with lifestyle |
| Best Sellers V2 | 6:763 | Gift guide / wishlist — full-bleed hero + lifestyle spotlights |
| Best Sellers V3 | 6:700 | Sale across multiple collections — collection-by-collection with products |
| Best Sellers V4 | 7:382 | Seating bestsellers with promotional angle — hero + 4 alternating |

### Collection Spotlight — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29.** These slice structures are encoded in `BW_FIGMA_TEMPLATES` (`scripts/create_calendar_tasks.py`) and consumed by `generate_bw_email_brief()`, which emits a numbered slice-by-slice Body Copy section for every non-Trade BUR email brief — same pattern as CZ/STF/TI. This section remains the source of truth for the slice content; keep the dict and this doc in sync if either changes.

Use these slice structures when populating the Body Copy section of a BW Asana task by hand. **Bold fields** are copy fields requiring copy editor review; structural fields (links, layout, visual notes) are plain.

**Shared conventions for this family:**
- **Sale messaging is baked into the hero eyebrow / CTA (and closing kicker), NOT a separate sale-banner slice.** When a sale is active (per `data/sale_schedules.yaml`, brand `BUR`), populate the hero **Eyebrow** (V1), the hero **CTA** (V4 card), and the **closing kicker** (V4) with the sale name/discount. When not on sale, omit the eyebrow and use non-sale CTA copy. There is no "with/without sale banner" variant.
- **Product-grid slices — prices only when on sale.** Each product slice lists the **product name** + **product URL**. Prices show in the images **only when the send is on sale** — then the design shows **regular price + strikethrough sale price** (values pulled from the live PDP). **When not on sale, leave prices out of the images entirely** (no regular price, no strikethrough). Per the "No prices in briefs" rule (CLAUDE.md), the brief never contains hardcoded price numbers regardless.
- **Link Sourcing Rule applies** — never guess LPs; use the brief, then `campaigns/html/*.html`, then the BUR link map in CLAUDE.md.
- **"50/50" means two separate half-width slices — never use it for a single full-width feature.** Only label a slice `50/50` when it is genuinely one of a *pair* of half-width slices sitting side by side, each linking to its own destination (two product cards, two category tiles). A single **full-width** slice that internally places an image on one side and copy on the other (a feature/collage row, often alternating sides down the email) is **one full-width slice** — describe it as "full-width; image one side / copy other (alternating)" and do **not** write "50/50", or the auto-builder will build it at half width.

#### A1 — Collection Spotlight V1 (node `5:30`)

**Slices to deliver: 3**
- Slice 1 — Logo & hero [card over full-bleed background image] · Logo / **Eyebrow**: [only if on sale, e.g. sale name / discount] / **HED**: [product or collection title] / Visual: [product image, inside the card] / **DEK**: [body copy] / **CTA**: [e.g. "Shop Now →"] / Link: [product/collection LP]
- Slice 2 — Feature collage [2 rows, alternating sides, each row has a line-art icon] · Row 1: Image left / **HED** / **Body** / **CTA**: [e.g. "Shop Now"] right · Row 2: **HED** / **Body** / **CTA** left / Image right / Link: [LP]
- Slice 3 — Kicker [background image] · **HED** / **Body** / **CTA** / Link: [category LP]

#### B1 — Collection Spotlight V2 (node `5:67`)

**Slices to deliver: 9**
- Slice 1 — Logo & hero [over full-bleed background image] · Logo / **HED** / **DEK**: [body copy] / **CTA**: [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Feature collage · Image left / **HED** / **Body** / **CTA** right → full-width image beneath [with callout labels] → Image right / **HED** / **Body** / **CTA** left / Link: [LP]
- Slice 3 — Product-grid header · **HED**: [e.g. "Shop more with [Title]"]
- Slices 4–9 — Product 1–6 [50/50, alternating left/right] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]

#### C1 — Collection Spotlight V3 (node `5:143`)

**Slices to deliver: 8**
- Slice 1 — Logo & hero · Logo / **HED**: [frames the inset image top & bottom, e.g. "SHIFT" / "SLEEPER"] / Visual: [inset image on a solid background color] / **DEK**: [body copy] / **CTA**: [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Feature callouts · **HED** / image with **feature callout text** [e.g. "Deep, plush cushions" / "Maximum comfort"] / icon row [e.g. Quick conversion / Queen size / Durable fabric]
- Slice 3 — Full-width image
- Slice 4 — Product-grid header · **HED** / **Body**: [optional]
- Slices 5–8 — Product 1–4 [50/50] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]

#### D1 — Collection Spotlight V4 (node `5:226`)

**Slices to deliver: 12**
- Slice 1 — Logo & hero [card over full-bleed background image] · Logo / **HED**: [collection title] / Visual: [same image as the background behind the card] / **CTA**: [button, e.g. "Make It Yours at 25% Off →" — sale wording when on sale] / Link: [collection LP]
- Slice 2 — Intro + icons · **HED** / **DEK**: [description] / **CTA**: [button, e.g. "Shop Now"] / icon row [e.g. Easy assembly / Extreme comfort / Fast shipping] / Link: [LP]
- Slice 3 — Full-width image
- Slice 4 — Editorial grid · Row 1: Image left / icon + **HED** / **Body** / **CTA**: [e.g. "Shop Now →"] right · Row 2: icon + **HED** / **Body** / **CTA** left / Image right → full-width image beneath / Link: [LP per row]
- Slice 5 — Product-grid header · **HED**: [e.g. "Explore all [Collection] now 25% off"]
- Slices 6–11 — Product 1–6 [50/50, alternating left/right] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]
- Slice 12 — Kicker [background image] · **HED** / **Body** / **CTA** / Link: [category/collection LP]

#### E1 — Collection Spotlight V5 (node `5:404`)

Editorial / brand-story layout — value props as full-bleed images, no product grid.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [over full-bleed background image] · Logo / **Eyebrow**: [short, e.g. "The All New"] / **HED**: [short & large, e.g. collection name] / **CTA**: [near the bottom, e.g. "Shop Russet →"] / Link: [collection LP]
- Slices 2–5 — Value prop [full-bleed background image; large all-lowercase white copy] · **Value prop**: [~2 words, e.g. "cloudlike comfort"] / Link: [collection LP]
- Slice 6 — CTA image [full-width background image, CTA button overlaid] · **CTA**: [~2 words, e.g. "Shop Russet →"] / Link: [collection LP]

#### F1 — Collection Spotlight V6 (node `5:469`)

**Slices to deliver: 7**
- Slice 1 — Logo & hero [over background image] · Logo / **HED** / **DEK**: [body copy] / **CTA**: [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Feature collage · Image left / **HED** / **Body** / **CTA**: [e.g. "Shop Now"] right → full-width feature image beneath [with callout labels] → **HED** / **Body** / **CTA** left / Image right / Link: [LP]
- Slice 3 — Product-grid header · **HED**: [copy over the grid]
- Slices 4–7 — Product 1–4 [50/50, alternating left/right] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]

#### G1 — Collection Spotlight V7 (node `5:533`)

Note: V7 product cards show the **product title only** (no price), unlike V2/V3/V4/V6.

**Slices to deliver: 9**
- Slice 1 — Logo & hero [over full-bleed background image] · Logo / **HED** / **Body**: [near the bottom] / **CTA**: [button, e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Feature block [white background] · **HED** / **Body** / **CTA**: [e.g. "Shop Now"] → icon row [3 icons, e.g. Durable upholstery / Hardwood frame / Built-in charger] → 2 side-by-side images → 1 wider image beneath / Link: [LP]
- Slice 3 — Product-grid header · **HED** / **Body** / **CTA**: [e.g. "Shop Now"]
- Slices 4–5 — Product [50/50; product image + **product title** over tan background] · Link: [product page]
- Slice 6 — Product [full-width; product image + **product title** over tan background] · Link: [product page]
- Slices 7–8 — Product [50/50; product image + **product title** over tan background] · Link: [product page]
- Slice 9 — Kicker [background image] · **HED** / **Body**: [short] / **CTA**: [e.g. "Shop Seating" — replace with the kicker topic, e.g. Shop Seating / Shop Outdoor] / Link: [category LP]

### Multi Collection Spotlight — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29** (same status as the Collection Spotlight section above).

Same shared conventions as the Collection Spotlight slice section above: **sale is inline** (hero DEK / badge overlaid on lifestyle images, no separate banner slice); **product images show reg + strikethrough prices only when on sale — omit all prices when not on sale**, and never a price value in the brief; **Link Sourcing Rule** applies. Product pairs are always **2 separate slices** — each product links to its own PDP.

#### MCS V1 — Two-Category Lifestyle (node `7:1094`)

Lifestyle-led, 2 category sections, **no product grid**. Sale shows as a badge overlaid on the lifestyle images (e.g. "30% Off") plus the sale name in the hero DEK.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [over full-bleed lifestyle image] · Logo / **HED** / **DEK** [body; include sale name when on sale] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 header · **HED** [collection name] / **Body** / **CTA** [e.g. "Shop Now"] / icon row [3 icons, e.g. Quick-drying foam / FSC-certified teak / All-weather fabric]
- Slice 3 — Section 1 lifestyle image [full-width; sale badge overlaid when on sale] · Link: [section 1 LP]
- Slice 4 — Section 2 header · **HED** / **Body** / **CTA** / icon row [3 icons]
- Slice 5 — Section 2 lifestyle image [full-width; sale badge when on sale] · Link: [section 2 LP]
- Slice 6 — Kicker [background image] · **HED** / **Body** / **CTA** [e.g. "Shop Outdoor" — swap topic] / Link: [category LP]

#### MCS V2 — Multi-Section Collection (node `7:1138`)

Hero is full-bleed; from slice 2 down, everything sits on a **white background with side padding** (not full-width). 3 collection sections, each = a combined slice (padded lifestyle image + collage header, image/copy alternating sides) followed by a 2-product 50/50 row.

**Slices to deliver: 10**
- Slice 1 — Logo & hero [full-bleed background image] · Logo / **HED** / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 lifestyle image + collage header [padded, on white bg; collage image left / copy right; add a "New In" badge on the lifestyle image ONLY when the brief specifies a collection launch] · **HED** [collection name] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [collection 1 LP]
- Slice 3 — Section 1 Product 1 [50/50 left] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 1 page]
- Slice 4 — Section 1 Product 2 [50/50 right] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 2 page]
- Slice 5 — Section 2 lifestyle image + collage header [padded, on white bg; collage copy left / image right] · **HED** [collection name] / **Body** / **CTA** / Link: [collection 2 LP]
- Slice 6 — Section 2 Product 1 [50/50 left] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 1 page]
- Slice 7 — Section 2 Product 2 [50/50 right] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 2 page]
- Slice 8 — Section 3 lifestyle image + collage header [padded, on white bg; collage image left / copy right] · **HED** [collection name] / **Body** / **CTA** / Link: [collection 3 LP]
- Slice 9 — Section 3 Product 1 [50/50 left] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 1 page]
- Slice 10 — Section 3 Product 2 [50/50 right] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product 2 page]

#### MCS V3 — Curated Bestsellers Edit (node `7:1223`)

Dark hero with a product collage + 3 alternating product features. Lifestyle images are **padded, over alternating cream/white backgrounds** (not full-width). No prices (editorial bestsellers).

**Slices to deliver: 4**
- Slice 1 — Logo & hero [dark background] · Logo / **HED** [e.g. "More to Love"] / product collage [with product-label callout, e.g. "Span Sleeper Sofa"] / **Body** / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slices 2–4 — Product feature 1–3 [alternating sides, over alternating cream/white bg with side padding; each = padded lifestyle image + caption block: **HED** (product name) / **Body** / **CTA** ("Shop Now") + a small secondary detail image] · Link: [product page]

#### MCS V4 — Three-Category Feature (node `7:1248`)

Full-bleed hero + 3 category sections, each combined into one slice (lifestyle image + a row of 3 product thumbnails + copy). The thumbnail row is a single link to the category LP. Section backgrounds alternate: full-width lifestyle image / cream bg with padded image / full-width lifestyle image.

**Slices to deliver: 4**
- Slice 1 — Logo & hero [full-bleed background image with a card overlaid on top; the card contains its own image] · Logo / **HED** / **DEK** [body; sale name when on sale] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 [full-width lifestyle image + 3-thumbnail product row + copy] · **HED** [category] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [category 1 LP — the whole thumbnail row shares this one link]
- Slice 3 — Section 2 [over cream background; padded lifestyle image (not full-width) + 3-thumbnail product row + copy] · **HED** [category] / **Body** / **CTA** / Link: [category 2 LP]
- Slice 4 — Section 3 [same pattern as Slice 2 — full-width lifestyle image + 3-thumbnail product row + copy] · **HED** [category] / **Body** / **CTA** / Link: [category 3 LP]

#### MCS V5 — Dining Multi-Category (node `7:1281`)

Hero + 3 category sections. Sections 1 & 3 are lifestyle category features; section 2 is a 2×2 product grid.

**Slices to deliver: 9**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Category 1 feature [e.g. Dining Chairs] · **HED** / lifestyle image / **Body** / **CTA** button [e.g. "Shop Now →"] / Link: [category 1 LP]
- Slice 3 — Category 2 product-grid header [e.g. Dining Tables] · **HED**
- Slices 4–7 — Product 1–4 [50/50, 2×2] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / optional "Best Seller" badge [include when the products are best sellers] / Link: [product page]
- Slice 8 — Category 2 CTA button · **CTA** [e.g. "Shop Now →"] / Link: [category 2 LP]
- Slice 9 — Category 3 feature [e.g. Counter Stools] · **HED** / lifestyle image / **Body** / **CTA** button / Link: [category 3 LP]

#### MCS V6 — Whole-Home / Gift Guide (node `7:1337`)

Hero + 3 room sections. Each room = a lifestyle image with the section header/copy **overlaid on it**, then a product group of 3 (1 wider single card + 2 50/50). Product cards are **name-only (no price)**. The product group sits on a **white background with side padding** — the single card is not truly full-width.

**Slices to deliver: 13**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Home for the Holidays"] / **DEK** [body] / **CTA** button [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Room 1 lifestyle image [header/copy overlaid] · **HED** [e.g. "Seating"] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [category LP]
- Slice 3 — Room 1 Product 1 [wider single card; padded on white bg] · Product image / **product name** (+ "New In" badge if launch) / Link: [product page]
- Slices 4–5 — Room 1 Product 2–3 [50/50; on white bg with padding] · Product image / **product name** / Link: [product page]
- Slice 6 — Room 2 lifestyle image [header/copy overlaid] · **HED** [e.g. "Dining"] / **Body** / **CTA** / Link: [category LP]
- Slice 7 — Room 2 Product 1 [wider single card; padded on white bg] · Product image / **product name** / Link: [product page]
- Slices 8–9 — Room 2 Product 2–3 [50/50; on white bg with padding] · Product image / **product name** / Link: [product page]
- Slice 10 — Room 3 lifestyle image [header/copy overlaid] · **HED** [e.g. "Storage"] / **Body** / **CTA** / Link: [category LP]
- Slice 11 — Room 3 Product 1 [wider single card; padded on white bg] · Product image / **product name** / Link: [product page]
- Slices 12–13 — Room 3 Product 2–3 [50/50; on white bg with padding] · Product image / **product name** / Link: [product page]

#### MCS V7 — Storage / Organization (node `7:1396`)

Dark hero + 2 product sections (each = a combined header + lifestyle-image-with-callouts slice, then 2 products), with a **feature interstitial** between them (a lifestyle image with overlaid copy + callouts, **no products**). Products are name-only (no price).

**Slices to deliver: 8**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Clutter? Conquered."] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 [header + lifestyle image with feature callouts] · **HED** [e.g. Title Shelves] / **Body** / **CTA** [e.g. "Shop Now"] / feature callouts [e.g. Built-in Desk / Expandable Design / Scratch-resistant] / Link: [collection LP]
- Slices 3–4 — Section 1 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 5 — Feature interstitial [e.g. Index Wall Shelves; lifestyle image with header/copy overlaid + feature callouts, no products] · **HED** / **Body** / **CTA** / Link: [collection LP]
- Slice 6 — Section 2 [header + lifestyle image with feature callouts] · **HED** [e.g. Opera Console] / **Body** / **CTA** / feature callouts / Link: [collection LP]
- Slices 7–8 — Section 2 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]

#### MCS V8 — Modern Dining, 4 Products (node `7:1444`)

Hero + 4 alternating product features + kicker. "Table" features are a lifestyle image with copy overlaid; "chair" features are a split (copy + product cutout on one side, lifestyle image on the other). Name-only, no price.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Product feature 1 [lifestyle image w/ overlaid copy; "New In" badge if launch] · **HED** [product name] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [product page]
- Slice 3 — Product feature 2 [full-width; copy + product cutout image one side, lifestyle image other] · **HED** [product name] / **Body** / **CTA** / Link: [product page]
- Slice 4 — Product feature 3 [lifestyle image w/ overlaid copy] · **HED** [product name] / **Body** / **CTA** / Link: [product page]
- Slice 5 — Product feature 4 [full-width; lifestyle image one side, copy + product cutout other — mirrored from feature 2] · **HED** [product name] / **Body** / **CTA** / Link: [product page]
- Slice 6 — Kicker [background image] · **HED** / **Body** / **CTA** [e.g. "Shop All Dining"] / Link: [category LP]

#### MCS V9 — Sale Seating, 4 Products (node `7:1811`)

Sale template. Hero (sale name/discount in DEK) + 4 alternating product features + kicker. Features 1 & 3 are full-width on a cream background; features 2 & 4 are cream boxes with the info over a white background, product alternating sides. Each feature has a **"% Off" sale badge** (no price value; shown only when on sale) and feature callouts. Name-only.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Take a Seat"] / **DEK** [body; include sale name/discount] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Product feature 1 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** [e.g. "Shop Now"] / sale badge ["% Off", no price value, only when on sale] / Link: [product page]
- Slice 3 — Product feature 2 [cream box with info, over white background; product on one side] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 4 — Product feature 3 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 5 — Product feature 4 [cream box with info, over white background; product on the opposite side from feature 2] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 6 — Kicker [background image] · **HED** [e.g. "Get it by Thanksgiving"] / **Body** [may include a shipping-deadline date] / **CTA** [e.g. "Shop Now →"] / Link: [category LP]

#### MCS V10 — New Colorways / Color Story (node `7:1494`)

Hero (with eyebrow) + 3 product features + kicker. Features alternate between centered copy + an image collage, and copy overlaid on a lifestyle image. Product names include the **colorway** (kept in the HED). No price.

**Slices to deliver: 5**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **Eyebrow** [e.g. "Our Take on Cloud Dancer"] / **HED** / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Product feature 1 [centered copy + image collage] · **HED** [product name + colorway] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [product page]
- Slice 3 — Product feature 2 [copy overlaid on lifestyle image] · **HED** [product name + colorway] / **Body** / **CTA** / Link: [product page]
- Slice 4 — Product feature 3 [centered copy + image collage] · **HED** [product name + colorway] / **Body** / **CTA** / Link: [product page]
- Slice 5 — Kicker [background image] · **HED** [e.g. "Need It Fast?"] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [category LP, e.g. ready-to-ship]

#### MCS V11 — Small Space / Apartment (node `7:1556`)

Hero + 3 room sections. Sections 1 & 3 = combined lifestyle image + centered header, then a 2×2 grid (4 products); section 2 = lifestyle image w/ overlaid header, then 2 products. Section headers have HED + Body but not all have a CTA — match the Figma per send.

**Slices to deliver: 14**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Small Space. Big Thinking."] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 [lifestyle image + centered header] · **HED** [e.g. "Compact, Configured"] / **Body** / **CTA** [if present in the Figma] / Link: [category LP]
- Slices 3–6 — Section 1 Product 1–4 [50/50, 2×2] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]
- Slice 7 — Section 2 [lifestyle image w/ overlaid header] · **HED** [e.g. "One Sofa, Real Sleep"] / **Body** / **CTA** [if present] / Link: [category LP]
- Slices 8–9 — Section 2 Product 1–2 [50/50] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]
- Slice 10 — Section 3 [lifestyle image + centered header] · **HED** [e.g. "One System, Smart Storage"] / **Body** / **CTA** [if present] / Link: [category LP]
- Slices 11–14 — Section 3 Product 1–4 [50/50, 2×2] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]

#### MCS V12 — Bedroom Collection (node `7:1689`)

Hero + 3 sections, each = a combined centered header + lifestyle image with feature callouts, then 2 products. Section headers are **HED + feature callouts only** (no body/CTA). Products are name-only (no price).

**Slices to deliver: 10**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Lose an Hour. Gain the Glow."] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Section 1 [centered header + lifestyle image with feature callouts] · **HED** [e.g. "The Foundation of a Good Night"] / feature callouts [e.g. Attached headboard / Corner-secured joinery] / Link: [category LP]
- Slices 3–4 — Section 1 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 5 — Section 2 [centered header + lifestyle image with feature callouts] · **HED** [e.g. "Everything Within Reach"] / feature callouts / Link: [category LP]
- Slices 6–7 — Section 2 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 8 — Section 3 [centered header + lifestyle image with feature callouts] · **HED** [e.g. "Streamlined Storage"] / feature callouts / Link: [category LP]
- Slices 9–10 — Section 3 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]

#### MCS V13 — Dining Tables, 3 Spotlights (node `7:1752`)

Hero + 3 table spotlights (no kicker). Each spotlight is one combined slice: centered header + lifestyle image + a single product card (one table in a specific finish) + a Shop Now button. Name-only (finish on the product-name line), no price.

**Slices to deliver: 4**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Built to Gather"] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Spotlight 1 [centered header + lifestyle image + single product card + Shop Now button] · **HED** [table name] / **Body** / product card: **product name incl. finish** [e.g. "Serif Extendable Dining Table in Oak"] / **CTA** button [e.g. "Shop Now →"] / Link: [product page]
- Slice 3 — Spotlight 2 [same pattern] · **HED** / **Body** / product card: **product name incl. finish** / **CTA** button / Link: [product page]
- Slice 4 — Spotlight 3 [same pattern] · **HED** / **Body** / product card: **product name incl. finish** / **CTA** button / Link: [product page]

#### MCS V14 — Whole-Home / New Year (node `7:1632`)

Hero + 3 room sections + kicker. Each room = a combined centered header + lifestyle image, then 2 products (50/50). Name-only, no price.

**Slices to deliver: 11**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "New Year, New Style"] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Room 1 [centered header + lifestyle image] · **HED** [e.g. "For the Living Room"] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [category LP]
- Slices 3–4 — Room 1 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 5 — Room 2 [centered header + lifestyle image] · **HED** [e.g. "For the Dining Room"] / **Body** / **CTA** / Link: [category LP]
- Slices 6–7 — Room 2 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 8 — Room 3 [centered header + lifestyle image] · **HED** [e.g. "For the Den"] / **Body** / **CTA** / Link: [category LP]
- Slices 9–10 — Room 3 Product 1–2 [50/50; name-only] · Product image / **product name** / Link: [product page]
- Slice 11 — Kicker [background image] · **HED** [e.g. "Take a Seat"] / **Body** / **CTA** [e.g. "Shop All Seating"] / Link: [category LP]

### Fabric & Multi Fabric Spotlight — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29** (same status as the sections above).

Same shared conventions as the Collection Spotlight slice section above (inline sale; product images show reg + strikethrough only when on sale — omit all prices otherwise, never a price value in the brief; Link Sourcing Rule; product pairs are separate slices). These are swatch-forward templates — hero CTAs and kickers default to the **swatches LP** (`https://burrow.com/swatches`); product cards link to their PDP. **Colorway is its own field** on fabric product grids (e.g. "in Sage Performance Chenille").

#### Fabric Spotlight V1 — Single Fabric Launch (node `2:275`)

Full-bleed fabric close-up hero + a story slice (with swatch thumbnails) + a 4-product grid + a swatch signup kicker.

**Slices to deliver: 7**
- Slice 1 — Logo & hero [full-bleed fabric close-up image] · Logo / **Eyebrow** [e.g. "Fabric Spotlight"] / **HED** [fabric name] / **DEK** [body] / **CTA** [e.g. "Order 5 Free Swatches →"] / Link: [swatches LP]
- Slice 2 — Fabric story [centered header + product image + swatch thumbnail row] · **HED** / **Body** / **CTA** [e.g. "Shop Now"] / [3 swatch thumbnails] / Link: [collection LP]
- Slices 3–6 — Product 1–4 [50/50, 2×2] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]
- Slice 7 — Swatch kicker [background image] · **HED** [e.g. "Order 5 Free Swatches"] / **Body** / **CTA** [e.g. "Shop Swatches"] / Link: [swatches LP]

#### Fabric Spotlight V2 — Feature-Forward Single Fabric (node `3:154`)

Card-over-dark-background hero + a 2-row feature-callout collage + product grid + swatch kicker.

**Slices to deliver: 10**
- Slice 1 — Logo & hero [card over full-bleed dark textured background; card contains a product image] · Logo / **Eyebrow** [e.g. "Just Dropped"] / **HED** [fabric name] / **DEK** [body] / **CTA** [e.g. "Order 5 Free Swatches →"] / Link: [swatches LP]
- Slice 2 — Feature callouts [2 rows, alternating; each = icon + copy + "Order Free Swatches" link + lifestyle image] · Row 1: icon / **HED** / **Body** / **CTA**; Row 2: icon / **HED** / **Body** / **CTA** / Link: [swatches LP]
- Slice 3 — Product-grid header · **HED** [e.g. "Shop performance flatweave on our bestselling sofas"]
- Slices 4–9 — Product 1–6 [50/50, 2×3] · Product image / **product name** / **colorway** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]
- Slice 10 — Swatch kicker [background image] · **HED** [e.g. "The First Step to the Perfect Piece"] / **CTA** [e.g. "Order 5 Free Swatches →"] / Link: [swatches LP]

#### Multi Fabric Spotlight V1 — Leather / Material Spotlight (node `3:230`)

Same spotlight pattern as MCS V13. Hero (sale in DEK when on sale) + 3 product spotlights, each one combined slice (centered header + lifestyle image + single product card + Shop Now button). Name + material, no price.

**Slices to deliver: 4**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **Eyebrow** [e.g. "Sink Into"] / **HED** [e.g. "Laid-back Leather"] / **DEK** [body; include sale name/discount when on sale] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Spotlight 1 [centered header + lifestyle image + single product card + Shop Now button] · **HED** [product name] / **Body** / product card: **product name incl. material** [e.g. "Range Pro 3-Seat Sofa in Camel Leather"] / **CTA** button [e.g. "Shop Now →"] / Link: [product page]
- Slice 3 — Spotlight 2 [same pattern] · **HED** / **Body** / product card: **product name incl. material** / **CTA** button / Link: [product page]
- Slice 4 — Spotlight 3 [same pattern] · **HED** / **Body** / product card: **product name incl. material** / **CTA** button / Link: [product page]

#### Multi Fabric Spotlight V2 — Fabric Collection Overview (node `3:30`)

Hero (with icon row) + 3 fabric-type sections + swatch kicker. Each section = a combined lifestyle image + a row of 3 product-in-colorway thumbnails + copy (the whole thumbnail row is one link to the fabric LP). No prices (overview).

**Slices to deliver: 5**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **Eyebrow** [e.g. "Order 5 Free Swatches"] / **HED** [e.g. "Performance Fabrics"] / **DEK** [body] / icon row [3 icons, e.g. Free of harmful toxins / Ultra-tight weave / Stain & liquid resistant] / **CTA** [e.g. "Shop Now →"] / Link: [hero LP]
- Slice 2 — Fabric section 1 [lifestyle image + 3-thumbnail colorway row + copy; white background] · **HED** [fabric name] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [fabric LP]
- Slice 3 — Fabric section 2 [same pattern; **cream background**] · **HED** / **Body** / **CTA** / Link: [fabric LP]
- Slice 4 — Fabric section 3 [same pattern; white background] · **HED** / **Body** / **CTA** / Link: [fabric LP]
- Slice 5 — Swatch kicker [background image] · **HED** [e.g. "Order 5 Free Swatches"] / **Body** / **CTA** [e.g. "Shop Swatches"] / Link: [swatches LP]

### Quick Ship — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29** (same status as the sections above).

Same shared conventions as the Collection Spotlight slice section above (inline sale; product images show reg + strikethrough only when on sale — omit all prices otherwise, never a price value in the brief; Link Sourcing Rule; product pairs are separate slices). Hero / story / kicker links default to the **quick-ship LP** (`https://burrow.com/ready-to-ship`); product tiles link to their PDP.

#### Quick Ship V1 — Standard Quick-Ship (node `7:2`)

Lifestyle hero + story header + a 5-product grid (2 + 1 full-width + 2). Grid tiles are **image-only** (product cutouts on gray tiles — no name, no price).

**Slices to deliver: 7**
- Slice 1 — Logo & hero [full-bleed lifestyle image] · Logo / **HED** [e.g. "Quick-Ship Steals"] / **DEK** [body; sale name/discount when on sale] / **CTA** [e.g. "Shop Now →"] / Link: [quick-ship LP]
- Slice 2 — Story header · **HED** [e.g. "Ready to go, and 25% off"] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [quick-ship LP]
- Slices 3–4 — Product 1–2 [50/50; image-only] · Product image / Link: [product page]
- Slice 5 — Product 3 [full-width; image-only] · Product image / Link: [product page]
- Slices 6–7 — Product 4–5 [50/50; image-only] · Product image / Link: [product page]

#### Quick Ship V2 — Quick-Ship + Sale (node `7:336`)

Sale promo hero + story header + a 6-product grid with reg/strikethrough prices.

**Slices to deliver: 8**
- Slice 1 — Logo & hero [full-bleed lifestyle image] · Logo / **HED** [e.g. "Up to 35% Off"] / **DEK** [body; include sale name/discount] / **CTA** [e.g. "Shop Now →"] / Link: [quick-ship LP]
- Slice 2 — Story header · **HED** [e.g. "Designs ready when you are"] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [quick-ship LP]
- Slices 3–8 — Product 1–6 [50/50, 2×3] · Product image / **product name** / prices: reg + strikethrough (only when on sale; omit all prices otherwise; no price value in brief) / Link: [product page]

#### Quick Ship V3 — Editorial Quick-Ship (node `7:447`)

**Same layout as MCS V9.** Full-bleed hero (sale in DEK) + 4 alternating product features (1 & 3 full-width on cream; 2 & 4 cream boxes over white, product alternating sides) each with feature callouts + a "% Off" badge + kicker. Name-only.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Take a Seat"] / **DEK** [body; include sale name/discount] / **CTA** [e.g. "Shop Now →"] / Link: [quick-ship LP]
- Slice 2 — Product feature 1 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** [e.g. "Shop Now"] / sale badge ["% Off", no price value, only when on sale] / Link: [product page]
- Slice 3 — Product feature 2 [cream box with info, over white background; product on one side] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 4 — Product feature 3 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 5 — Product feature 4 [cream box with info, over white background; product on opposite side from feature 2] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 6 — Kicker [background image] · **HED** [e.g. "Get it by Thanksgiving"] / **Body** [may include a shipping-deadline date] / **CTA** [e.g. "Shop Now →"] / Link: [category LP]

### Best Sellers — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29** (same status as the sections above).

Same shared conventions as the Collection Spotlight slice section above (inline sale; product images show reg + strikethrough only when on sale — omit all prices otherwise, never a price value in the brief; the "50/50 means two separate half-width slices" rule; Link Sourcing Rule). Generic hero / kicker links default to the **best-sellers LP** (`https://burrow.com/collections/best-sellers`); category/collection tiles link to their specific LP; product cards link to their PDP.

#### Best Sellers V1 — Flagship Bestsellers (node `6:558`)

Hero + 4 product features. Each feature is one **full-width slice** with an image on one side and copy on the other, alternating sides down the email (NOT a 50/50). Name-only, no price, no kicker. "New" badge on a feature when it's a launch.

**Slices to deliver: 5**
- Slice 1 — Logo & hero [full-bleed lifestyle image] · Logo / **HED** [e.g. "Comfort, Built In"] / **DEK** [body] / **CTA** [e.g. "Shop Now →"] / Link: [best-sellers LP]
- Slices 2–5 — Product feature 1–4 [full-width slice; lifestyle image one side / copy other, alternating sides; "New" badge if launch] · **HED** [product name] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [product page]

#### Best Sellers V2 — Gift Guide / Wishlist (node `6:763`)

Hero + category lifestyle tiles (2 + 1 full-width + 2), each a lifestyle image with a "Shop [category] →" link. No product names/prices — category tiles.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [full-bleed lifestyle image] · Logo / **HED** [e.g. "The Styles on Everyone's Wishlist"] / **DEK** [body; sale name/discount when on sale] / **CTA** [e.g. "Shop Now →"] / Link: [best-sellers LP]
- Slices 2–3 — Category tile 1–2 [50/50; lifestyle image] · **CTA** [e.g. "Shop Modular Seating →"] / Link: [category LP]
- Slice 4 — Category tile 3 [full-width; lifestyle image] · **CTA** [e.g. "Shop Sleeper Sofas →"] / Link: [category LP]
- Slices 5–6 — Category tile 4–5 [50/50; lifestyle image] · **CTA** [e.g. "Shop Storage →"] / Link: [category LP]

#### Best Sellers V3 — Sale Across Collections (node `6:700`)

Hero (sale in HED) + 5 collection features + kicker. Each feature is one **full-width slice** with a product image on one side and copy on the other, alternating sides (NOT a 50/50). Name-only, no price.

**Slices to deliver: 7**
- Slice 1 — Logo & hero [full-bleed lifestyle image] · Logo / **Eyebrow** [e.g. "Up To"] / **HED** [e.g. "30% Off Seating"] / **DEK** [body, if present] / **CTA** [e.g. "Shop Now →"] / Link: [best-sellers LP]
- Slices 2–6 — Collection feature 1–5 [full-width slice; product image one side / copy other, alternating sides] · **HED** [collection name] / **Body** / **CTA** [e.g. "Shop Now"] / Link: [collection LP]
- Slice 7 — Kicker [background image] · **HED** [e.g. "The best seat in the house"] / **Body** / **CTA** [e.g. "Shop Seating"] / Link: [category LP]

#### Best Sellers V4 — Seating Bestsellers, Promotional (node `7:382`)

**Same layout as MCS V9 / Quick Ship V3.** Full-bleed hero (sale in DEK) + 4 alternating product features (1 & 3 full-width on cream; 2 & 4 cream boxes over white, product alternating sides) each with feature callouts + a "% Off" badge + kicker. Name-only.

**Slices to deliver: 6**
- Slice 1 — Logo & hero [full-bleed image] · Logo / **HED** [e.g. "Take a Seat"] / **DEK** [body; include sale name/discount] / **CTA** [e.g. "Shop Now →"] / Link: [best-sellers LP]
- Slice 2 — Product feature 1 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** [e.g. "Shop Now"] / sale badge ["% Off", no price value, only when on sale] / Link: [product page]
- Slice 3 — Product feature 2 [cream box with info, over white background; product on one side] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 4 — Product feature 3 [full-width, on cream background] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 5 — Product feature 4 [cream box with info, over white background; product on opposite side from feature 2] · product image with feature callouts / **HED** [product name] / **CTA** / sale badge / Link: [product page]
- Slice 6 — Kicker [background image] · **HED** [e.g. "Get it by Thanksgiving"] / **Body** / **CTA** [e.g. "Shop Now →"] / Link: [category LP]

### Retail Event — Slice-by-Slice Brief Instructions

> **Wired into BW auto-briefs as of 2026-07-29** (same status as the sections above).

Event-invite / in-store templates, not product-grid. Same shared conventions as above where applicable (Link Sourcing Rule). **Store locator link:** the "Find My Store" CTA always links to `https://burrow.com/showrooms`. Whether the hero bakes in the full date/hours/location block (V1, V3) or keeps the hero short and moves that detail to a separate slice (V2) **varies by send/design** — it is not a fixed rule to apply, just note the pattern actually used in the Figma comp for that send.

#### Retail Event V1 — Compact Event Announcement (node `2:30`)

Hero carries all event info baked into one image/text block. Slice 2 is a secondary clearance/promo banner — **always included**.

**Slices to deliver: 2**
- Slice 1 — Logo & hero [full-bleed background image; event info overlaid in one block] · Logo / **Eyebrow** [event name, e.g. "The Sip & Sit Event"] / **HED** [tagline, e.g. "Best Weekend Ever"] / **DEK** [offer + invite copy] / Event dates [e.g. "February 14th & February 15th"] / Event hours [e.g. "Open to Close"] / Location ["Your Local Burrow Studio"] / **CTA** [e.g. "Find My Store →"] / Link: https://burrow.com/showrooms
- Slice 2 — Secondary promo banner [full-width; copy one side on solid background, image other; always included] · **Eyebrow** [e.g. "Last Chance"] / **HED** [e.g. "Up to 70% Off Clearance Styles"] / **CTA** [e.g. "Shop Now"] / Link: [category/clearance LP]

#### Retail Event V2 — Detailed Retail Event Invite (node `2:74`)

Hero carries invite copy + CTA only (no dates baked in). A combined second slice holds the storefront photo + When/Where details, plus a design-consult feature and fine-print terms line.

**Slices to deliver: 2**
- Slice 1 — Logo & hero [full-bleed background image] · Logo / **Eyebrow** [e.g. "You're Invited To"] / **HED** [event name, e.g. "Sip & Sit"] / **DEK** [offer + invite copy] / **CTA** [e.g. "Find My Store →"] / Link: https://burrow.com/showrooms
- Slice 2 — When & Where + design consult [combined: storefront photo + When/Where info, then a design-consult feature with lifestyle image + fine print] · **When** [event date(s) + hours, e.g. "Saturday, 02/07, open to close" / "Sunday, 02/08, open to close"] / **Where** ["Your local Burrow Studio"] / **HED** [e.g. "Make It Yours"] / **Body** [e.g. design-consult pitch] / **CTA** [e.g. "Find My Store"] / Fine print [e.g. "Terms apply. Select studios only."] / Link: https://burrow.com/showrooms

#### Retail Event V3 — Compact Retail Event + Product Showcase (node `2:136`)

Hero image extends down through a lifestyle scene, with event info overlaid at the top — there is no separate lifestyle-image slice. Then a cross-promo banner.

**Slices to deliver: 2**
- Slice 1 — Logo & hero [full-bleed background image, extends down through a lifestyle scene; event info overlaid at top] · Logo / **Eyebrow** [e.g. "You're Invited"] / **HED** [event name, e.g. "Sip & Sit"] / **DEK** [offer + invite copy] / Event dates [e.g. "November 22nd & November 23rd"] / Event hours [e.g. "Open to Close"] / Location ["Your Local Burrow Studio"] / **CTA** [e.g. "Find My Store →"] / Link: https://burrow.com/showrooms
- Slice 2 — Cross-promo banner [solid color background] · **HED** [e.g. "Trending styles for every corner"] / **Body** [e.g. bestsellers pitch] / **CTA** [e.g. "Shop Best Sellers"] / Link: [best-sellers LP]

### Link Farms — Reusable Kicker Modules

> **Reference only — not yet wired into BW auto-briefs.** These are kicker/footer modules appended to other templates, not standalone emails, and there is currently no rule for when to attach one. **Do not add these to BW briefs during auto-briefing until formalized.** If a kicker is added manually (or Claude is prompted to add one during briefing), fold its slices into the brief's total slice count and description rather than appending it separately.

#### BUR Partner Blocks — Cross-Brand Partner Kicker (node `1:97`)

Confirmed in real BW sends Nov 2024–Sept 2025 (e.g. `campaigns/html/20241113_bfcm-phase-2-launch.html`, `campaigns/html/2025_03_13_bw_spring_event_sale_launch.html`) — each brand tile is a **lifestyle photo with the brand name overlaid in white text** (not a flat logo). Referenced in Asana briefs as "partner blocks" or "partner banners." **Note:** as of the 2026-02-14 Bestsellers send, this kicker was requested in the brief but not built — confirm with whoever builds the email before assuming it will be included automatically.

**Slices to deliver: 6**
- Slice 1 — Header [solid background] · **HED** [e.g. "Shop more deals from our partner brands"]
- Slice 2 — Havenly tile [50/50; lifestyle photo with "HAVENLY" overlaid in white text] · Link: https://havenly.com/
- Slice 3 — The Citizenry tile [50/50; lifestyle photo with "THE CITIZENRY" overlaid in white text] · Link: https://www.the-citizenry.com/
- Slice 4 — The Inside tile [50/50; lifestyle photo with "THE INSIDE" overlaid in white text] · Link: https://www.theinside.com/
- Slice 5 — Interior Define tile [50/50; lifestyle photo with "INTERIOR DEFINE" overlaid in white text] · Link: https://www.interiordefine.com/
- Slice 6 — St. Frank tile [50/50; lifestyle photo with "ST FRANK" overlaid in white text] · Link: https://www.stfrank.com/

#### Category Lifestyle Block / Category Footer Block — Category Link Farm Kicker (nodes `7:1870` / `7:1912`)

Two visual variants of the **same category-link-farm concept** — Category Lifestyle Block uses lifestyle photo tiles, Category Footer Block uses solid-color text buttons. Documented here as the **fixed, maximal Figma structure**; real BW sends typically use a subset of categories (e.g. 2–5 of the available categories, sometimes swapping in others like Rugs) rather than the full set — treat the category list as flexible per send even though the structure below is fixed.

**Category Lifestyle Block — Slices to deliver: 7**
- Slice 1 — Header · **Body** [intro copy] / Link: [homepage]
- Slice 2 — Seating [full-width; lifestyle image, category name overlaid] · Link: [seating category LP]
- Slice 3 — Dining [50/50 left; lifestyle image, category name overlaid] · Link: [dining category LP]
- Slice 4 — Bedroom [50/50 right; lifestyle image, category name overlaid] · Link: [bedroom category LP]
- Slice 5 — Sleeper Sofas [full-width; lifestyle image, category name overlaid] · Link: [sleeper sofas category LP]
- Slice 6 — Storage [50/50 left; lifestyle image, category name overlaid] · Link: [storage category LP]
- Slice 7 — Outdoor [50/50 right; lifestyle image, category name overlaid] · Link: [outdoor category LP]

**Category Footer Block — Slices to deliver: 7**
- Slice 1 — Header · **Eyebrow** / **HED** [e.g. "Up To xx% Off [Category]"] / Link: [homepage]
- Slice 2 — Sofas [50/50 left; solid-color button] · Link: [sofas category LP]
- Slice 3 — Sectionals [50/50 right; solid-color button] · Link: [sectionals category LP]
- Slice 4 — Dining [50/50 left; solid-color button] · Link: [dining category LP]
- Slice 5 — Bedroom [50/50 right; solid-color button] · Link: [bedroom category LP]
- Slice 6 — Sleeper Sofas [50/50 left; solid-color button] · Link: [sleeper sofas category LP]
- Slice 7 — Storage [50/50 right; solid-color button] · Link: [storage category LP]

*Collection Spotlight V1–V7, Multi Collection Spotlight V1–V14, and the Fabric / Multi Fabric Spotlight, Quick Ship, Best Sellers, and Retail Event families are fully documented at slice level — all named BW email templates are now covered, along with all 3 Link Farm / kicker modules (BUR Partner Blocks, Category Lifestyle Block, Category Footer Block).*

---

## Interior Define (ID) Email Figma Templates

File key: `oFsPeUJ1s8oK5s6mbLl376` — [Lifecycle: Email Template Library](https://www.figma.com/design/oFsPeUJ1s8oK5s6mbLl376/Lifecycle--Email-Template-Library)
URL format: `?node-id=[NODE_ID_HYPHENATED]`

Each Core Design template has a v1 (primary) and v2 (alternate) variant. Node IDs below are v1.

### Core Designs (section `2:2192`)

| Letter | Template | Node ID | Use Case |
|--------|----------|---------|----------|
| A | Core Design | 1:760 | Full lifestyle editorial — stacked hero room vignettes with CTAs. Seasonal editorial, lifestyle story |
| B | Core Design | 1:920 | Multi-product editorial — lifestyle hero + individually named products. Named product feature, shop the look |
| C | Collection | 1:1032 | Single collection spotlight — large hero + detail shots + fabric customization CTA. New product/collection launch |
| D | Made for Me | 1:1092 | Personalization-led — lifestyle room + customer testimonial + customization features. MTO story, UGC |
| E | Product Focus | 1:1411 | New Arrivals — large hero + individual product cards stacked vertically. Product drop |
| F | Collection Focus | 2:197 | Single product hero + craftsmanship/story copy + lifestyle context. Bedroom collection, furniture story |
| G | Category Feature | 2:385 | Lifestyle hero + category browse section below. New arrivals with shop-by-category |
| H | Product Categories | 2:467 | Editorial hero + multi-category product grid (2×2 or 2×3). Accent edit, category browse |
| I | Lifestyle + Product Highlight | 1:3253 | Room-specific editorial — hero + 3 curated sections with product pairs. Dining, entertaining |
| J | Render Body Send | 1:3331 | Sale product listing — lifestyle hero + product cards with sale prices. Sale send |
| K | Graphic Number Treatment | 2:2119 | Typography-led — bold "new new new" + numbered product list. New arrivals with graphic feel |
| L | Editorial Highlight | 1:3565 | Editorial catalog style — hero + 3 side-by-side editorial sections. Design inspiration |
| M | Hero Grid | 2:2314 | Hero + product grid layout |
| N | Hero Gif | 2:2374 | "Faster by Design" — single product hero + Quick Ship/MTO messaging |
| BNDL | Hero BNDL | 51:1161 | "Buy now / Decide later" split-screen sofa comparison. BNDL program |
| P | Swatch Talk: UGC | 185:618 | UGC-style swatch editorial |

### Specialty Sections

| Section | Node ID | Use Case |
|---------|---------|----------|
| Swatch Talk | 2:2194 | Fabric/swatch-focused sends (6 layouts: multi-hero, editorial, grid, gif hero, fabric hero, sofa hero) |
| In Stock + Quick Ship | 2:2313 | In-stock availability and Quick Ship campaigns (5 layouts) |
| Retail | 2:2195 | Showroom events, partner events, Sip & Sit (3 layouts) |
| Guides | 2:2196 | Buying guides — sectional, rug, comfort, sectional buying guide (4 layouts) |

### Sale-Specific (section `166:116`, parent `142:239`)

| Template | Node ID | Use Case |
|----------|---------|----------|
| BNDL Sale Last Chance | 166:2 | Last-chance BNDL sale email |
| EA Reminder | 167:121 | Early access reminder |
| Sale Reminder | 167:429 | Mid-sale reminder |
| Sale Last Chance PM | 167:432 | Final-hours last-chance PM send |

Sale add-on components: **Banners** (`162:50`) · **Kickers** (`162:188`): BNDL, Partner Banners, In Stock Banner, Best Sellers Kicker

### Body Copy Fields by Template

ID emails are more visual than copy-heavy. The key fields to include in every brief are a short Hero HED, product names for the grid, and a CTA.

| Letter | Template | Body Copy Fields |
|--------|----------|-----------------|
| A | Core Design | Hero HED, Section 1–3 HED, Section 1–3 Product Names, Section 1–3 CTA |
| B | Core Design | Eyebrow (e.g. "HOME REFRESH"), Hero HED, Hero CTA, Product 1–N: Product Name + Product DEK (1–2 sentences) + Product CTA ("Shop the collection"), Footer CTA ("Shop all [category]") |
| C | Collection | Eyebrow ("INTRODUCING" — only if this is a genuine new collection/product launch; otherwise use a descriptive label, e.g. the collection name), Hero HED (collection name), Hero DEK (1–2 sentence description), Hero CTA ("Shop Now") |
| D | Made for Me | Eyebrow ("MADE FOR ME"), Hero HED (customer name or tagline), Hero DEK, Testimonial Quote, Feature List (3–5 customization specs with checkmarks), CTA |
| E | Product Focus | Eyebrow ("THIS JUST IN"), Hero HED ("New Arrivals"), Hero CTA, Product 1–N: Product Name + Fabric ("in [Fabric] [Color]") + Product CTA ("Shop the collection") |
| F | Collection Focus | Eyebrow ("SPOTLIGHT ON"), Hero HED (product name), Hero DEK (paragraph on craftsmanship/story), Hero CTA ("Shop [product]"), Section HED + Section Subhead (top right), Section DEK (bottom left — feature/benefit paragraph) |
| G | Category Feature | Eyebrow (e.g. "THIS JUST IN"), Hero HED, Hero DEK (1–2 sentences), Hero CTA, Section HED (featured category), Section DEK (paragraph), Section availability note (optional), Section CTA |
| H | Product Categories | Eyebrow (e.g. "FINISHING TOUCHES"), Hero HED (e.g. "The Accent Edit"), Hero CTA, Category 1–N: Category HED + 4 Product Names (2×2 grid) |
| I | Lifestyle + Product Highlight | Hero HED, Hero CTA, Section 1–3: Section HED + Section DEK (2 sentences) + 2 Product Names + Fabric + Section CTA, Footer body + Footer CTA |
| J | Render Body Send | Eyebrow ("IN STOCK AND ON SALE"), Hero HED (discount %, e.g. "30% off select styles"), Hero CTA, Product 1–N: Product Name + Fabric + Sale Price |
| K | Graphic Number Treatment | Eyebrow ("THIS JUST IN"), Body DEK (e.g. "Brand new styles, ready to make your own."), CTA, Product 1–N: Product Name + Fabric caption — note: "new new new" decoration is baked in, not a text field |
| L | Editorial Highlight | Hero Eyebrow, Hero HED, Hero DEK, Hero CTA, Section 1–3 HED (vertical), Section 1–3 Product Name + Fabric, Section 1–3 CTA ("Shop now") |
| M | Hero Grid | Body DEK (e.g. "Our most-loved styles, at your door in 1–3 weeks."), CTA ("Shop in stock") — note: "In Stock / COLLECTION" center label is baked in, not a text field |
| N | Hero Gif | Hero Body DEK ("Your choices, your details…"), Hero CTA ("Shop [Product Name]"), Quick Ship HED ("Custom, Without the Wait"), Quick Ship DEK, Quick Ship CTA ("Shop Quick Ship") — note: "Faster by Design" headline is baked into the GIF, not a text field |
| BNDL | Hero BNDL | Hero HED ("Buy now, decide later"), Feature Bullets (3–4 fabric benefits), Swatch CTA |
| P | Swatch Talk: UGC | Hero HED ("It all started with a swatch…"), Hero CTA, Intro DEK ("See how our customers designed and styled…"), then Section 1–3 each: @handle, Product Name, Fabric Name + Fabric Type, Spec 1–3 (customization details with checkmarks), Swatch CTA ("Order free swatches") |
| swatch_talk | Swatch Talk (6 variants) | Eyebrow ("SWATCH TALK"), Hero HED (fabric/collection name), Hero DEK (intro), Hero CTA ("Order Swatches"). Section 1–3: Section HED + Body copy + Section CTA. Grid variant (C): 4 swatches each with Sofa/Chair Name + Fabric Color Name. Performance variant (F): Feature bullets instead of product sections. |
| instock | In Stock + Quick Ship (5 variants) | Hero HED, Body DEK, CTA. Multi-product variant (D): Product 1–4 Name + DEK + CTA. Editorial variant (E): Eyebrow badge + Hero HED + Body DEK + CTA. |
| retail | Retail (3 variants) | A. Partner Event: Eyebrow, Hero HED, body, RSVP CTA. B. Retail Hero: Hero HED, Hero Subhead, body ×2, CTA, Footer. C. Sip & Sit: Eyebrow, Hero HED, body, CTA, Best Sellers kicker. |
| guides | Guides (4 variants) | Eyebrow/subhead label, Hero HED (guide name), body (intro), CTA. Rug/Comfort variants add: product name labels for a photo grid. |

---

## Trade Email Figma Templates

File key: `e7qLewGYDpx18n5dqxV0sa` — [HAVENLY BRANDS TRADE](https://www.figma.com/design/e7qLewGYDpx18n5dqxV0sa/HAVENLY-BRANDS-TRADE)
URL format: `?node-id=[NODE_ID_HYPHENATED]`
Always include template in task **notes field** (not comment).

### HAV Trade
| Template | Node ID | Best For |
|----------|---------|----------|
| A. Sale Feature | 1075:6 | Hero discount + DPS/marketplace split CTA; multi-brand sale events |
| B. Sale Feature | 1075:410 | Alternate sale layout with brand grid — multiple brands in one send |
| C. Sale Feature | 1075:698 | Sale with benefits/reasons-to-buy footer |
| D. Grid Layout | 1075:996 | Non-sale sends showcasing multiple products/collections |

### ID Trade
| Template | Node ID | Best For |
|----------|---------|----------|
| A. In Stock | 1075:2007 | In-stock collection hero + product grid |
| B. Editorial Edit | 1075:2284 | Brand story or seasonal editorial |
| C. Contract Grade | 1075:2117 | Trade-specific durability/COM features |
| D. Category Highlight | 1075:2583 | Single category deep-dive (sofas, dining, etc.) |
| E. Designer Spotlight | 1075:2454 | Designer partnerships or Trade program spotlights |

### CZ Trade
| Template | Node ID | Best For |
|----------|---------|----------|
| A. Editorial Edit | 1075:3536 | Brand intro or artisan story |
| B. Hero Only | 1075:3746 | Single full-bleed hero |
| C. Seasonal Moodboard | 1075:3719 | Seasonal collection previews |
| D. Product Highlight | 1075:3794 | Hero product launches |
| E. Product Highlight (Alt) | 1075:3862 | Alternate product highlight layout |
| F. Swatches | 1075:3930 | Trade swatch programs or material stories |
| G. Room Categories | 1075:4047 | Broad assortment — multiple room types |

### TI Trade
| Template | Node ID | Best For |
|----------|---------|----------|
| A. Print Feature | 1075:4881 | New print or pattern launches |
| B. Inside(r) Report | 1075:5061 | Trend roundups or curated edit sends |
| C. Editorial Edit | 1075:5208 | Brand story or seasonal editorial |
| D. Fabrics | 1075:5263 | Fabric story or COM/Trade fabric program |
| E. Category Feature | 1075:5417 | Category-specific campaigns |
| F. Seasonal Preview | 1075:5694 | New season or collection preview |

### STF Trade
| Template | Node ID | Best For |
|----------|---------|----------|
| A. Editorial Edit | 1075:7058 | Brand story or origin/craft sends |
| B. Fabric Feature | 1075:7200 | Fabric or textile-focused Trade sends |
| C. Hero Only | 1075:7625 | Single product or lifestyle moment |
| D. Editorial Category | 1075:7391 | "Top Picks" curated product assortment |
| E. Behind the Scenes | 1075:7496 | Artisan spotlights or process storytelling |

---

## TI (The Inside) Email Figma Templates

File key: `B2DuEEQLOCrQNhY3iKTkhi` — [TI Templates](https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates)
URL format: `?node-id=[NODE_ID_HYPHENATED]`

**Use the "TI Templates Update" page** (node `174:2`) for all auto-briefing. 9 active templates below.

### Active Templates ("TI Templates Update" page, node `174:2`)

| Template | Node ID | Section | Best For |
|----------|---------|---------|----------|
| Template 1 | `174:32` | POTM | Print of the Month — single print spotlight with hero + editorial copy + product CTA |
| Template 2 | `174:76` | Swatch edit | Swatch / trend print story — hero + multi-swatch product image grid |
| Template 3 | `174:3` | Swatch edit | Swatch edit (simple / short) — tighter swatch callout format |
| Template 4 | `174:202` | Product multi category | Multi-category product feature — beds, soft goods, outdoor; BNDL block included |
| Template 5 | `174:351` | Product category | Product category (short) — compact single-category feature |
| Template 6 | `174:144` | Product category | Seating / chairs — numbered products (no. 1/2/3) with individual CTAs + BNDL block |
| Template 7 | `175:607` | Color edit | Color edit — bold color title hero + 2×2 product grid by category |
| Template 8 | `175:501` | Destination edit | Travel / destination editorial — large landscape hero + editorial copy sections |
| Template 9 | `175:562` | Category edit | Dining / hosting / entertaining — lifestyle hero + product sections + footer CTA |

### Slice-by-Slice Brief Instructions

> The per-template slice structures (Templates 1–9) are now **generated** from `TI_FIGMA_TEMPLATES` in `scripts/create_calendar_tasks.py` — see [Auto-Briefed Slice Structures → The Inside (TI)](#auto-briefed-slice-structures--generated-cz--stf--ti). That section is the source of truth; do not hand-maintain slice lists here.

### Optional Add-on Kickers (from original TI Templates page — still valid)

These are kicker/add-on components only, not full email templates. Use the node IDs from the original page.

| Component | Node ID | When to Use |
|-----------|---------|-------------|
| BNDL Kicker A | `1:1297` | "Buy Now. Decide Later" program block |
| BNDL Kicker B | `1:1393` | Alternate BNDL layout |
| Link Farm A | `1:1345` | Category link blocks with swatch images. Mixed grid — one full-width photo tile top, then a tall 50/50-left tile beside a stacked 50/50-right pair (top half + bottom half), then a full-width photo tile bottom. Each tile is its own slice; label them `Full width` / `50/50 left` / `50/50 right` accordingly. |
| Link Farm B | `1:1311` | Alternate link farm layout — a **2-column category-tile grid** (900px frame, each tile 450px). Header band is optional/often dropped. Every tile is its own slice; the tiles pair up into 50/50 rows, so **label them `50/50 left` / `50/50 right` alternating**, never full width. |
| Swatch Talk Kicker A | `1:1287` | Swatch showcase footer (3 swatches) |
| Swatch Talk Kicker B | `1:1403` | Lifestyle photo + swatch footer |

**Slice layout labels (all TI templates, per the CZ/STF slice rule):** every slice in a TI brief's Body Copy must state its layout — `Full width`, `50/50 left`, or `50/50 right` — pulled from the actual Figma frame geometry (a slice at `x=0` spanning the full 900px canvas is Full width; a 450px slice at `x=0` is `50/50 left`, one at `x=450` is `50/50 right`). Known 50/50 layouts: **Template 7 Color Edit** 2×2 grid (slices 2–5), **Link Farm A** (see above), **Link Farm B** (all tiles). Template 4 (Multi-Category) and Template 6 (Seating) base slices are all full width — the numbered-product rows in Template 6 place image and copy side-by-side *within one full-width slice*, which is NOT a 50/50 split into two slices.

---

<!-- BEGIN GENERATED: auto-briefed-slices (scripts/generate_figma_templates_doc.py) -->

## Auto-Briefed Slice Structures — GENERATED (CZ / STF / TI)

> **Do not edit by hand.** This section is generated from the template dicts in
> `scripts/create_calendar_tasks.py` by `scripts/generate_figma_templates_doc.py`.
> Those dicts are the source of truth the Asana brief auto-builder actually reads.
> Edit the dicts, then re-run the generator. Narrative rules (template selection,
> sale-banner behavior, historical caveats) live in CLAUDE.md, not here.

### The Citizenry (CZ)

File key `K043FA15z83zW2fhOkTH7J`. Generator: `generate_cz_email_brief()`. Slices follow the 2026-06-05 consolidation rules (logo+hero and same-link adjacent slices merge). During a sale, a Slice 1 sale banner is prepended (all slices +1), a cycled kicker and a sale link-farm header slice are appended (see CLAUDE.md).

#### `A` — Multi-Hero (`789:178`)

- **Use for:** MTO furniture, specific product feature (e.g. Potomac Bed), product launch, artisan story
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-178
- **Slices to deliver (base, no sale banner):** 1

1. **Logo, hero, and sections** — Full width
   - HED: [product or collection headline]
   - Hero CTA: [link text beneath hero headline, e.g. 'Shop the Collection']
   - Section 1 Visual: [describe the first image section]
   - Section 1 DEK: [caption/narrative for first section]
   - Section 2 Visual: [describe the second image section]
   - Section 2 DEK: [caption/narrative for second section]
   - Section 3 Visual: [describe the third image section]
   - Section 3 DEK: [caption/narrative for third section]
   - Section 3 CTA: [final section CTA text, if present]
   - Link: [main LP]

#### `B` — Product Feature Full Bleed (`832:988`)

- **Use for:** sale last chance or reminder, gift guides, single strong product feature
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=832-988
- **Slices to deliver (base, no sale banner):** 6

1. **Logo bar, eyebrow, and HED** — Full width
   - Sale terms bar: [1-sentence urgency line under the logo, e.g. 'Hurry, up to 25% off ends at midnight.'] (optional — include only during an active sale)
   - Eyebrow: [small label above hero, e.g. 'New Arrival' or 'Last Chance']
   - HED: [product or sale headline — large display type over a full-bleed background]
   - Link: [hero/sale LP]
2. **Category 1 — full width** — Full width
   - CTA: [category link text, e.g. 'Shop Rugs →']
   - Link: [category page URL]
3. **Category 2 — 50/50 left** — 50/50 left
   - Layout: 50/50 (paired with Category 3 in the same row)
   - CTA: [category link text]
   - Link: [category page URL]
4. **Category 3 — 50/50 right** — 50/50 right
   - Layout: 50/50 (paired with Category 2 in the same row)
   - CTA: [category link text]
   - Link: [category page URL]
5. **Category 4 — full width** — Full width
   - CTA: [category link text]
   - Link: [category page URL]
6. **CTA over background image** — Full width
   - CTA: [main button CTA text, e.g. 'Shop Up to 25% Off']
   - Link: [hero/sale LP]

#### `C` — Destination (`789:240`)

- **Use for:** destination editorial, travel and culture storytelling (e.g. Kyoto, Japan)
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-240
- **Slices to deliver (base, no sale banner):** 2

1. **Logo bar and hero** — Full width
   - Eyebrow: [small label, e.g. 'Cities That Inspire']
   - HED: [destination name, e.g. 'Kyoto, Japan']
   - Hero CTA: [CTA button, e.g. 'Explore the Capsule']
   - Link: [destination capsule LP]
2. **Meet Us in [Destination]** — Full width
   - Body HED: [section headline for the body narrative]
   - Body DEK: [1–2 sentences about the destination and its connection to The Citizenry]
   - Body CTA: [first CTA, e.g. 'Explore the Capsule']
   - Final CTA: [dark full-bleed bottom banner CTA, e.g. 'The [Destination] Capsule >']
   - Link: [destination capsule LP]

#### `D` — Get the Look (`789:412`)

- **Use for:** shop the look, styled room feature, bedding layers, pillow pairings, UGC, rugs
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-412
- **Slices to deliver (base, no sale banner):** 6

1. **Logo, hero, and body copy** — Full width
   - HED: [styled look name, e.g. 'the autumn LIVING ROOM']
   - Hero CTA: [first CTA above the product grid]
   - DEK: [1–2 sentence styling narrative]
   - Link: [hero LP]
2. **Product Image 1 — 50/50 left** — 50/50 left
   - Layout: 50/50 (paired with Product Image 2 in the same row)
   - Name: [name of product shown in image 1]
   - Link: [product page URL]
3. **Product Image 2 — 50/50 right** — 50/50 right
   - Layout: 50/50 (paired with Product Image 1 in the same row)
   - Name: [name of product shown in image 2]
   - Link: [product page URL]
4. **Product Image 3 — 50/50 left** — 50/50 left
   - Layout: 50/50 (paired with Product Image 4 in the same row)
   - Name: [name of product shown in image 3]
   - Link: [product page URL]
5. **Product Image 4 — 50/50 right** — 50/50 right
   - Layout: 50/50 (paired with Product Image 3 in the same row)
   - Name: [name of product shown in image 4]
   - Link: [product page URL]
6. **CTA button** — Full width _(no visual direction)_
   - CTA: [final button CTA text]
   - Link: [hero LP]

#### `E` — Color Edit (`789:445`)

- **Use for:** color palette editorial, seasonal color story
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-445
- **Slices to deliver (base, no sale banner):** 2

1. **Logo bar and hero** — Full width
   - Eyebrow: Color Edit
   - HED: [PALETTE NAME in all caps, e.g., 'GOLDEN HOUR']
   - DEK: [2–3 palette keywords + a one-sentence mood line, e.g., 'Turmeric. Saffron. Mustard. The warm, golden hues to bring an instant mood boost.']
   - Hero CTA: Shop the Edit
   - Link: [color edit LP]
2. **Color swatches + mosaic** — Full width
   - Swatches: [color palette swatches row for the palette]
   - Mosaic: [4–6 product/lifestyle shots from the palette — textiles, ceramics, art, rugs, accents — arranged as a mosaic grid]
   - CTA: Shop the Edit
   - Link: [color edit LP]

#### `F` — Archive Sale (`789:527`)

- **Use for:** archive sale, clearance sale, end-of-season sale with new styles added
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-527
- **Slices to deliver (base, no sale banner):** 1

1. **Logo, hero, body copy, photo grid, and CTA** — Full width
   - Eyebrow: [small label, e.g. 'New Styles Added']
   - HED: The Archive Sale
   - Hero CTA: Shop up to 70% off  [FIXED — always 70% off, never use active promo discount]
   - DEK: [1–2 sentences driving urgency, e.g. 'Last of the archive. Bring home the pieces you've had your eye on.']
   - Body CTA: Shop Archive Sale
   - Photo grid: [6 photos — row 1 (1 large left + 2 stacked right), row 2 (2 stacked left + 1 large right) — product/lifestyle shots from the archive]
   - CTA button: Shop Archive Sale
   - Link: https://www.the-citizenry.com/collections/archive-sale

#### `G` — Furniture by Room (`789:579`)

- **Use for:** furniture by room, shop by room, UGC, rugs, MTO furniture
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=789-579
- **Slices to deliver (base, no sale banner):** 6

1. **Logo bar, hero, and intro copy** — Full width
   - HED: [e.g. 'Room by Room' or custom headline]
   - Hero CTA: [main CTA above room sections]
   - DEK: [1–2 sentence intro copy row]
   - Link: [hero LP]
2. **Category 1** — Full width
   - HED: [category name, e.g. 'Bedroom']
   - DEK: [1–2 sentences for this category]
   - CTA: Shop Now >
   - Link: [category 1 LP]
3. **Category 2** — Full width
   - HED: [category name, e.g. 'Living Room']
   - DEK: [1–2 sentences for this category]
   - CTA: Shop Now >
   - Link: [category 2 LP]
4. **Category 3** — Full width
   - HED: [category name, e.g. 'Bath']
   - DEK: [1–2 sentences for this category]
   - CTA: Shop Now >
   - Link: [category 3 LP]
5. **Category 4** — Full width
   - HED: [category name, e.g. 'Kitchen']
   - DEK: [1–2 sentences for this category]
   - CTA: Shop Now >
   - Link: [category 4 LP]
6. **CTA button** — Full width _(no visual direction)_
   - CTA: [e.g. 'Shop All Furniture']
   - Link: [hero LP]

#### `H` — Shop by Category (`811:737`)

- **Use for:** sale launch, early access, sale reminder, last chance, bedding sale, shop by category
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=811-737
- **Slices to deliver (base, no sale banner):** 6

1. **Logo and hero** — Full width
   - HED: [sale event name or headline]
   - Hero CTA: [main CTA button text]
   - Link: [hero LP]
2. **Category Block 1** — Full width
   - Eyebrow: [discount or label, e.g. '25% OFF']
   - HED: [category name, e.g. 'heirloom rugs']
   - Link: [category page URL]
3. **Category Block 2** — Full width
   - Eyebrow: [discount or label]
   - HED: [category name]
   - Link: [category page URL]
4. **Category Block 3** — Full width
   - Eyebrow: [discount or label]
   - HED: [category name]
   - Link: [category page URL]
5. **Category Block 4** — Full width
   - Eyebrow: [discount or label]
   - HED: [category name]
   - Link: [category page URL]
6. **Category Block 5** — Full width
   - Eyebrow: [discount or label]
   - HED: [category name]
   - Link: [category page URL]
7. **Category Block 6** — Full width _(optional)_
   - Eyebrow: [discount or label] (optional)
   - HED: [category name] (optional)
   - Link: [category page URL] (optional)

#### `I` — Rugs (`811:800`)

- **Use for:** rugs feature, rug sale, rug-focused editorial
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=811-800
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar, hero, and all content** — Full width
   - Eyebrow: [small label, e.g. 'hand-woven']
   - HED: [main headline, e.g. 'HEIRLOOMS']
   - Hero CTA: [CTA text, e.g. 'Shop the Sale']
   - Body DEK: [1–2 sentences about the rugs]
   - Body CTA: [body section CTA text]
   - Product grid: [rug product/lifestyle shots]
   - Link: [rugs LP]

#### `J` — Hero Only (`824:975`)

- **Use for:** spring preview, collection launch, specific product feature, Meadow Press
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=824-975
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar and hero** — Full width
   - HED: [main headline]
   - DEK: [1–2 sentence description]
   - CTA: [button CTA text]
   - Link: [hero LP]

#### `K` — Back in Stock (`876:1171`)

- **Use for:** back in stock announcement, restocked products
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=876-1171
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar and hero** — Full width
   - HED: Back In Stock
   - DEK: [1–2 sentences, e.g. 'Your favorite items are back…']
   - Hero CTA: Shop Now
   - Link: [hero LP / BIS LP]

#### `L` — Monthly Edit (`1363:434`)

- **Use for:** monthly edit, trend forecast, newsletter, seasonal recap
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=1363-434
- **Slices to deliver (base, no sale banner):** 4

1. **Logo bar and hero** — Full width
   - Eyebrow: [volume/date label, e.g. 'VOL. / 05.26']
   - HED: [e.g. 'THE MAY EDIT']
   - DEK: [1–2 sentences setting the month's mood]
   - CTA: [first CTA button text — ghost button]
   - Link: [hero LP]
2. **Section 1** — Full width
   - Eyebrow: [section label, e.g. 'BACK IN STOCK']
   - HED: [section headline, e.g. 'best-sellers']
   - DEK: [1 sentence]
   - CTA: [CTA text]
   - Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]
3. **Section 2** — Full width
   - Eyebrow: [section label, e.g. 'BEDDING SPOTLIGHT']
   - HED: [section headline]
   - DEK: [1 sentence]
   - CTA: [CTA text]
   - Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]
4. **Section 3** — Full width
   - Eyebrow: [section label, e.g. 'TRAVEL SPOTLIGHT']
   - HED: [section headline]
   - DEK: [1 sentence]
   - CTA: [CTA text]
   - Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]

#### `M` — General Edit (`1382:566`)

- **Use for:** The Spa Edit, bedding guide, bath essentials, shop by category editorial
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=1382-566
- **Slices to deliver (base, no sale banner):** 5

1. **Logo bar and hero** — Full width
   - Eyebrow: [small label, e.g. 'Bath Essentials']
   - HED: [e.g. 'THE SPA EDIT']
   - DEK: [1–2 sentences about the category edit]
   - CTA: [CTA button text]
   - Link: [hero LP]
2. **Category 1 — full width** — Full width
   - CTA: [category link text, e.g. 'Shop Bath Towels →']
   - Link: [category page URL]
3. **Category 2 — 50/50 left** — 50/50 left
   - Layout: 50/50 (paired with Category 3 in the same row)
   - CTA: [category link text]
   - Link: [category page URL]
4. **Category 3 — 50/50 right** — 50/50 right
   - Layout: 50/50 (paired with Category 2 in the same row)
   - CTA: [category link text]
   - Link: [category page URL]
5. **Category 4 — full width** — Full width
   - CTA: [category link text, e.g. 'Shop All Bath →']
   - Link: [category page URL]

#### `N` — UGC (`1672:446`)

- **Use for:** UGC campaign, community showcase, customer-styled photos
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=1672-446
- **Slices to deliver (base, no sale banner):** 4

1. **Logo bar and hero (UGC photo 1)** — Full width
   - HED: [e.g. 'Spring, Styled by You']
   - DEK: [1–2 sentences about the community theme]
   - CTA: [CTA text, e.g. 'Shop Now' — ghost button]
   - Name: [product tag — name of product shown in hero photo]
   - Instagram handle: @[handle of person who took hero photo]
   - Link: [hero LP]
2. **UGC photo 2** — Full width
   - Name: [product tag — name of product shown in photo 2]
   - Instagram handle: @[handle of person who took photo 2]
   - Link: [product page URL]
3. **UGC photo 3** — Full width
   - Name: [product tag — name of product shown in photo 3]
   - Instagram handle: @[handle of person who took photo 3]
   - Link: [product page URL]
4. **CTA button** — Full width _(no visual direction)_
   - CTA: [final button CTA text, e.g. 'Shop Now']
   - Link: [hero LP]

#### `O` — Meet the Makers (`1735:760`)

- **Use for:** artisan story, maker spotlight, destination with craft narrative
- **Figma:** https://www.figma.com/design/K043FA15z83zW2fhOkTH7J/2026-CZ-EDITORIALS?node-id=1735-760
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar, hero, and maker story** — Full width
   - Eyebrow: Meet the Makers
   - HED: [maker or artisan name, e.g. 'SUNHOUSE CRAFT']
   - DEK: [2–3 sentences about the artisan, their craft, and location]
   - CTA: [CTA text, e.g. 'Meet the Maker >']
   - Link: [artisan LP]

### St. Frank (STF)

File key `Bnne2c9xMqh3fiUp3VfLIM`. Generator: `generate_stf_email_brief()`. During a sale, a Slice 1 sale banner is prepended (all slices +1) EXCEPT the sale hero (`t7`). No kicker cycling or link-farm slice — kickers are manual (see below).

#### `t1` — Template 1 — Studio By STF (long editorial) (`252:96`)

- **Use for:** studio, custom furniture, MTO furniture, made-to-order, long editorial, craft story
- **Description:** Studio By STF long editorial — hero + copy + photo collage grid + optional Shop More Styles kicker.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-96&m=dev
- **Slices to deliver (base, no sale banner):** 2

1. **Logo bar and hero** — Full width
   - Eyebrow: [hero eyebrow, e.g. 'The Studio Collection']
   - HED: [hero headline]
   - Link: [hero LP]
2. **Body copy and photo collage** — Full width
   - Eyebrow: [body eyebrow]
   - DEK: [1–2 sentence craft/story narrative]
   - CTA: [body CTA]
   - Link: [same as hero]
3. **Shop More Styles kicker** — Full width _(optional, no visual direction)_
   - CTA: [Shop More Styles]
   - Link: [category LP]

#### `t2` — Template 2 — Studio By STF (short + swatch callout) (`252:164`)

- **Use for:** studio, shorter send, swatch callout, explore swatches, category grid
- **Description:** Studio short — hero + Explore Swatches callout + Shop More Styles header + 2×2 category grid.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-164&m=dev
- **Slices to deliver (base, no sale banner):** 7

1. **Logo bar and hero** — Full width
   - HED: [hero headline]
   - Link: [hero LP]
2. **Explore Swatches callout** — Full width
   - CTA: [Explore Swatches]
   - Link: https://www.stfrank.com/collections/swatches
3. **Shop More Styles header** — Full width
   - HED: [Shop More Styles]
   - Link: [same as hero]
4. **Category 1** — 50/50 left
   - Name: [category label, e.g. 'New Releases']
   - Link: [category LP]
5. **Category 2** — 50/50 right
   - Name: [category label]
   - Link: [category LP]
6. **Category 3** — 50/50 left
   - Name: [category label]
   - Link: [category LP]
7. **Category 4** — 50/50 right
   - Name: [category label]
   - Link: [category LP]

#### `t3` — Template 3 — Color Edit (`252:854`)

- **Use for:** color edit, color story, palette, print, pattern
- **Description:** Color edit — palette hero + section header + 2×2 category/product grid.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-854&m=dev
- **Slices to deliver (base, no sale banner):** 6

1. **Logo bar and color palette hero** — Full width
   - Eyebrow: [color story eyebrow]
   - HED: [color/palette name]
   - DEK: [1–2 sentence color story]
   - CTA: [hero CTA]
   - Link: [hero LP]
2. **Section header** — Full width
   - HED: [section headline]
   - Link: [same as hero]
3. **Category 1** — 50/50 left
   - Eyebrow: [category eyebrow]
   - HED: [category headline]
   - CTA: [category CTA]
   - Link: [category LP]
4. **Category 2** — 50/50 right
   - Eyebrow: [category eyebrow]
   - HED: [category headline]
   - CTA: [category CTA]
   - Link: [category LP]
5. **Category 3** — 50/50 left
   - Eyebrow: [category eyebrow]
   - HED: [category headline]
   - CTA: [category CTA]
   - Link: [category LP]
6. **Category 4** — 50/50 right
   - Eyebrow: [category eyebrow]
   - HED: [category headline]
   - CTA: [category CTA]
   - Link: [category LP]

#### `t4` — Template 4 — Print of the Month (`252:1038`)

- **Use for:** POTM, print of the month, featured print, print spotlight
- **Description:** Print of the Month — featured print hero + body header + 2×2 product variants + CTA.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-1038&m=dev
- **Slices to deliver (base, no sale banner):** 7

1. **Logo bar and hero** — Full width
   - Eyebrow: [print eyebrow, e.g. 'Print of the Month']
   - HED: [print name]
   - DEK: [1–2 sentence print origin/story]
   - CTA: [hero CTA]
   - Link: [print LP]
2. **Body header** — Full width
   - Body HED: [body headline, e.g. 'An Instant Icon']
   - Body DEK: [supporting copy]
   - Link: [same as hero]
3. **Product variant 1** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
4. **Product variant 2** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
5. **Product variant 3** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
6. **Product variant 4** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
7. **CTA button** — Full width _(no visual direction)_
   - Body CTA: [closing CTA]
   - Link: [same as hero]

#### `t5` — Template 5 — Pattern Drenching (`252:1229`)

- **Use for:** pattern drenching, full-bleed pattern, bold pattern, maximalism
- **Description:** Pattern drenching — single full-bleed bold pattern hero image with eyebrow/HED/CTA.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-1229&m=dev
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar and full-bleed hero** — Full width
   - Eyebrow: [hero eyebrow]
   - HED: [hero headline]
   - CTA: [hero CTA]
   - Link: [hero LP]

#### `t6` — Template 6 — Product Feature / Design Edit (`252:2035`)

- **Use for:** product feature, design edit, outdoor, pillows, fabric, lifestyle feature, two-section product edit
- **Description:** Product/lifestyle feature — hero + two product sections (4 products each, 50/50) + closer.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2035&m=dev
- **Slices to deliver (base, no sale banner):** 12

1. **Logo bar and hero** — Full width
   - HED: [hero headline]
   - DEK: [hero supporting copy]
   - Hero CTA: [hero CTA]
   - Link: [hero LP]
2. **Section 1 header** — Full width
   - Eyebrow: [optional — only if an active sale, e.g. '25% Off']
   - HED: [section 1 headline]
   - Link: [section 1 LP]
3. **Section 1 Product 1** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
4. **Section 1 Product 2** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
5. **Section 1 Product 3** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
6. **Section 1 Product 4** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
7. **Section 2 header** — Full width
   - HED: [section 2 headline]
   - Link: [section 2 LP]
8. **Section 2 Product 1** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
9. **Section 2 Product 2** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
10. **Section 2 Product 3** — 50/50 left
   - Name: [product name]
   - Link: [product LP]
11. **Section 2 Product 4** — 50/50 right
   - Name: [product name]
   - Link: [product LP]
12. **Closer** — Full width
   - HED: [closing section headline]
   - DEK: [closing supporting copy]
   - CTA: [closing CTA]
   - Link: [closer LP]

#### `t7` — Template 7 — Sale Hero / Last Chance (`252:2283`)

- **Use for:** sale, last chance, final hours, single hero, sale announcement, gallery sale
- **Description:** Single full-width sale hero image + CTA only. The hero IS the sale message — no separate sale banner is added.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2283&m=dev
- **Slices to deliver (base, no sale banner):** 1
- **Sale hero:** the hero *is* the sale message — no sale banner is prepended.

1. **Logo bar and hero** — Full width
   - Eyebrow: [e.g. 'Last Chance to Shop']
   - HED: [sale name, e.g. 'The Gallery Sale']
   - DEK: [discount + categories, e.g. '25% off Art, Wallpaper, & Curtains']
   - Hero CTA: [Shop Now]
   - Link: [sale LP or homepage]

#### `t8` — Template 8 — Trends / Seasonal Edit (`252:2386`)

- **Use for:** trends, seasonal edit, three trends, trend report, fall trends, seasonal trends
- **Description:** 3 named trends (each: photo + copy + CTA) + Shop More Styles header + 2×2 category grid.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2386&m=dev
- **Slices to deliver (base, no sale banner):** 9

1. **Logo bar and hero** — Full width
   - Eyebrow: [e.g. 'The Just In']
   - HED: [edit name, e.g. 'Fall Trends']
   - Link: [hero LP]
2. **Trend 1** — Full width
   - HED: [trend 1 name]
   - DEK: [trend 1 copy]
   - CTA: [trend 1 CTA]
   - Link: [trend 1 LP]
3. **Trend 2** — Full width
   - HED: [trend 2 name]
   - DEK: [trend 2 copy]
   - CTA: [trend 2 CTA]
   - Link: [trend 2 LP]
4. **Trend 3** — Full width
   - HED: [trend 3 name]
   - DEK: [trend 3 copy]
   - CTA: [trend 3 CTA]
   - Link: [trend 3 LP]
5. **Shop More Styles header** — Full width
   - HED: [Shop More Styles]
   - Link: [same as hero]
6. **Category 1** — 50/50 left
   - Name: [category label]
   - Link: [category LP]
7. **Category 2** — 50/50 right
   - Name: [category label]
   - Link: [category LP]
8. **Category 3** — 50/50 left
   - Name: [category label]
   - Link: [category LP]
9. **Category 4** — 50/50 right
   - Name: [category label]
   - Link: [category LP]

#### `t9` — Template 9 — UGC (Styled By You) (`252:427`)

- **Use for:** UGC, styled by you, influencer, customer photos, community, instagram
- **Description:** Hero UGC photo + 2 more UGC photos with product tags + Instagram handles + CTA button.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-427&m=dev
- **Slices to deliver (base, no sale banner):** 4

1. **Logo bar and hero (UGC photo 1)** — Full width
   - HED: [Styled By You headline]
   - DEK: [intro copy]
   - Hero CTA: [Shop Now]
   - Name: [featured product name]
   - Instagram handle: @[handle]
   - Link: [hero LP]
2. **UGC photo 2** — Full width
   - Name: [featured product name]
   - Instagram handle: @[handle]
   - Link: [product LP]
3. **UGC photo 3** — Full width
   - Name: [featured product name]
   - Instagram handle: @[handle]
   - Link: [product LP]
4. **CTA button** — Full width _(no visual direction)_
   - CTA: [Shop Now]
   - Link: [same as hero]

#### `t10` — Template 10 — Destination (`252:2654`)

- **Use for:** destination, travel, editorial journey, Lake Como, Milan, Paris
- **Description:** Destination editorial — hero + 3 destination sections (HED/DEK/CTA each) + kicker.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2654&m=dev
- **Slices to deliver (base, no sale banner):** 5

1. **Logo bar and hero** — Full width
   - HED: [destination headline]
   - DEK: [1–2 sentence destination intro]
   - Hero CTA: [hero CTA]
   - Link: [hero LP]
2. **Section 1** — Full width
   - HED: [section 1 headline]
   - DEK: [section 1 copy]
   - CTA: [section 1 CTA]
   - Link: [section 1 LP]
3. **Section 2** — Full width
   - HED: [section 2 headline]
   - DEK: [section 2 copy]
   - CTA: [section 2 CTA]
   - Link: [section 2 LP]
4. **Section 3** — Full width
   - HED: [section 3 headline]
   - DEK: [section 3 copy]
   - CTA: [section 3 CTA]
   - Link: [section 3 LP]
5. **Kicker** — Full width
   - HED: [kicker headline]
   - CTA: [kicker CTA]
   - Link: [kicker LP]

#### `t11` — Template 11 — Moodboard / Lookbook (`252:1439`)

- **Use for:** moodboard, seasonal moodboard, mosaic, lifestyle collage, typographic hero
- **Description:** Seasonal moodboard — typographic hero + intro copy + lifestyle collage grid + category links.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-1439&m=dev
- **Slices to deliver (base, no sale banner):** 3

1. **Logo bar and hero** — Full width
   - HED: [big typographic moodboard name]
   - Link: [hero LP]
2. **Intro copy** — Full width
   - Body DEK: [1–2 sentence intro]
   - Body CTA: [intro CTA]
   - Link: [same as hero]
3. **Lifestyle collage grid** — Full width
   - DEK: [optional collage caption]
   - Link: [same as hero]
4. **Category links** — Full width _(optional)_
   - CTA: [Shop More Styles]
   - Link: [category LP]

#### `t12` — Template 12 — Lookbook / Seasonal Launch (`252:1611`)

- **Use for:** lookbook, seasonal launch, collection launch, date callout
- **Description:** Lookbook / seasonal launch — single hero image + date callout + CTA.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-1611&m=dev
- **Slices to deliver (base, no sale banner):** 1

1. **Logo bar and hero** — Full width
   - HED: [launch/lookbook headline]
   - Hero CTA: [hero CTA]
   - Date: [launch/event date callout]
   - Link: [hero LP]

#### `t13` — Template 13 — Back in Stock (`252:2783`)

- **Use for:** back in stock, BIS, restocked, available again, waitlist
- **Description:** Hero-only back-in-stock announcement + copy band.
- **Figma:** https://www.figma.com/design/Bnne2c9xMqh3fiUp3VfLIM/St.-Frank-Templates-2026?node-id=252-2783&m=dev
- **Slices to deliver (base, no sale banner):** 2

1. **Logo bar and hero** — Full width
   - HED: [back-in-stock headline]
   - Hero CTA: [Shop Now]
   - Link: [BIS/hero LP]
2. **Copy band** — Full width _(no visual direction)_
   - DEK: [back-in-stock supporting copy]
   - Link: [same as hero]

**STF standalone kickers / category blocks** (manual add-ons; not auto-attached):

- `swatch_kicker_1` — **Swatch Kicker 1** (`252:2473`) — Full width — Explore Swatches — minimal callout.
- `category_block_1` — **Category Block 1** (`252:2484`) — Full width — Shop More Styles — stacked text links.
- `category_block_2` — **Category Block 2** (`252:2514`) — 50/50 grid — Sale only — 'X% Off Sitewide' 6-cell category grid (50/50 pairs).
- `category_block_3` — **Category Block 3** (`252:2552`) — 50/50 grid — Shop More Styles — 2×2 photo grid (50/50 pairs).
- `swatch_kicker_2` — **Swatch Kicker 2** (`252:2571`) — Full width — Explore Swatches — with lifestyle image.
- `edit_kicker_1` — **Edit Kicker 1** (`252:2594`) — 50/50 pair — 'Tis the Season edit kicker (50/50 pair).
- `category_block_4` — **Category Block 4** (`252:2603`) — Full width — Sale reminders — 'Up to X% Off' 4 full-width category rows.
- `category_block_5` — **Category Block 5** (`252:2620`) — Full width — Alternate 'Tis the Season kicker.

### The Inside (TI)

File key `B2DuEEQLOCrQNhY3iKTkhi`. Generator: `generate_ti_email_brief()`. Slices are authored as pre-formatted text per template. During a sale, a Slice 1 sale banner is prepended via the prompt; kickers are selected by `pick_ti_kicker()`.

#### `potm` — POTM — Print of the Month (`174:32`)

- **Use for:** print of the month, POTM, single print spotlight, featured print, print hero
- **Description:** Single print spotlight — hero + editorial copy + product CTA.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-32

    Slice 1 — Hero · Logo / Eyebrow: "PRINT OF THE MONTH" (fixed) / HED: [print name] / DEK: [editorial copy] / CTA: [CTA copy] / Link: [print LP]
    Slice 2 — Lifestyle image · Descriptor: [2–4 words, italicized, e.g. print name] / Link: [print LP]
    Slice 3 — Image (no copy) · Link: [print LP]
    Slice 4 — CTA block · Copy: [above-CTA copy] / CTA: [CTA copy] / Link: [print LP]

#### `swatch_story` — Swatch Story — Swatch / Trend Print Story (`174:76`)

- **Use for:** swatch story, trend print, multiple swatches, swatch grid, print trend, seasonal print round-up, fabric edit
- **Description:** Hero + multi-swatch product image grid (3 rows default).
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-76

    Slice 1 — Hero · Logo / HED: [theme title] / Sub-HED: [italic phrase] / DEK: [editorial copy] / CTA: [CTA copy] / Note: hero includes swatch image overlaid on background — deliver as one asset / Link: https://www.theinside.com/fabric-swatches
    Slice 2 — Swatch grid [full-width; 3 rows, alternating swatch image side] · Row 1: Image left / Copy right · Print name: [name] / Descriptor: [2–3 word tag] · Row 2: Copy left / Image right · Print name: [name] / Descriptor: [2–3 word tag] · Row 3: Image left / Copy right · Print name: [name] / Descriptor: [2–3 word tag] / Link: https://www.theinside.com/fabric-swatches
    Slice 3 — CTA block · Background image / HED: [copy] / CTA: [CTA copy] / Link: https://www.theinside.com/fabric-swatches

#### `swatch_party` — Swatch Party — Swatch Edit (`174:3`)

- **Use for:** swatch party, free swatches, swatch promo, order swatches, swatch offer
- **Description:** Evergreen swatch promo — animated GIF cycling through prints. All copy is fixed.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-3

    Slice 1 — Full email · Logo / HED: "Swatch Party" (fixed) / CTA: "ORDER FREE SWATCHES" (fixed) / DEK: "Major savings are right around the corner. Get a head start and bring home five free swatches now." (fixed) / Promo code: "USE CODE: 5FREESWATCHES" (fixed) / Animated GIF: [prints to feature — background + swatch image per print, cycling] / Link: https://www.theinside.com/fabric-swatches

#### `product_multi` — Product Multi — Multi-Category Product Feature (`174:202`)

- **Use for:** multi-category, three products, product feature, beds and curtains, soft goods, outdoor, product round-up, category mix
- **Description:** Hero + 3 product/collection lifestyle images. Optional BNDL kicker.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-202

    Slice 1 — Hero · Logo / HED: [headline] / DEK: [editorial copy] / CTA: [CTA copy] / Link: [collection LP]
    Slice 2 — Product/Collection 1 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]
    Slice 3 — Product/Collection 2 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]
    Slice 4 — Product/Collection 3 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]
    [Optional BNDL kicker]

#### `product_single` — Product Single — Product Category / Hero (`174:351`)

- **Use for:** single category hero, ottoman feature, one product, one category, hero only, product spotlight, influencer, UGC product
- **Description:** Full-email hero with large editorial HED + product image inset + CTA.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-351

    Slice 1 — Full email · Logo / HED: [headline] / Background image + product image inset (baked into one asset) / CTA: [CTA copy] / Instagram handle: @[handle] (include only when featuring influencer content, otherwise omit) / Link: [product or collection LP]

#### `seating` — Seating — Seating / Product Category (`174:144`)

- **Use for:** seating, chairs, best of seating, accent chairs, benches, ottomans, numbered products, 3 chairs, product lineup
- **Description:** Hero + 3 numbered products (50/50 layout, alternating) + footer CTA. Optional BNDL kicker.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=174-144

    Slice 1 — Hero · Logo / Eyebrow: "THE BEST OF" (default; adjust if needed) / HED: [headline] / CTA: [CTA copy] / Link: [collection LP]
    Slice 2 — Product 1 [image left, copy right] · no. 1 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]
    Slice 3 — Product 2 [copy left, image right] · no. 2 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]
    Slice 4 — Product 3 [image left, copy right] · no. 3 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]
    Slice 5 — Footer CTA · Background image / HED: [copy] / CTA: [CTA copy] / Link: [collection LP]
    [Optional BNDL kicker]

#### `color_edit` — Color Edit — Color Edit (`175:607`)

- **Use for:** color edit, color story, color theme, greens, blues, neutrals, color palette, shop by color, color trend
- **Description:** Color theme hero + 2×2 product category grid + swatch kicker (default).
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=175-607

    Slice 1 — Hero + subhead · Logo / HED: [color theme headline] / DEK: [editorial copy] / CTA: [CTA copy] / Subhead: "designer-loved style" (default; can vary — note: subhead sits on a separate light tan background row below the hero image, not overlaid on it) / Link: [color/collection LP]
    Slice 2 — Category 1 [50/50 — top left of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]
    Slice 3 — Category 2 [50/50 — top right of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]
    Slice 4 — Category 3 [50/50 — bottom left of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]
    Slice 5 — Category 4 [50/50 — bottom right of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]
    [Default: Swatch kicker · HED: [color theme, e.g. 'Go-to Greens:'] / Fabric name: [italic] / CTA: [CTA copy] / Link: https://www.theinside.com/fabric-swatches]

#### `destination` — Destination — Travel / Destination Editorial (`175:501`)

- **Use for:** travel, destination, travel edit, scotland, highlands, abroad, landscape, wanderlust, destination editorial
- **Description:** Destination editorial — landscape hero + editorial section + lifestyle image + CTA block.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=175-501

    Slice 1 — Hero · Logo / Eyebrow: "TRAVEL EDIT" (fixed) / Destination: [destination name, e.g. "SCOTLAND"] / HED: [destination headline] / CTA: [CTA copy] / Link: [destination edit LP]
    Slice 2 — Editorial · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop the edit'] / Oval-framed lifestyle image / Link: [destination edit LP]
    Slice 3 — Lifestyle image · Full-bleed image / Short italic copy: [2–5 word descriptor overlaid on image] / Link: [destination edit LP]
    Slice 4 — CTA block · Layered destination + interior images / HED: [copy] / CTA: [CTA copy] / Link: [destination edit LP]

#### `dining` — Dining — Dining / Hosting / Entertaining (`175:562`)

- **Use for:** dining, hosting, entertaining, brunch, table setting, dinner party, table linens, dining chairs, hosting season
- **Description:** Hosting editorial — lifestyle hero + two editorial sections + lifestyle image + CTA block.
- **Figma:** https://www.figma.com/design/B2DuEEQLOCrQNhY3iKTkhi/TI-Templates?node-id=175-562

    Slice 1 — Hero · Logo / Eyebrow: [e.g. 'IT'S HOSTING TIME'] / HED: [headline] / CTA: [CTA copy] / Link: [collection LP]
    Slice 2 — Editorial 1 · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop dining chairs'] / Decorative framed lifestyle image / Link: [category LP]
    Slice 3 — Lifestyle image · Full-bleed image / Short italic copy: [2–5 word descriptor overlaid] / Link: [collection LP]
    Slice 4 — Editorial 2 · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop table linens'] / Lifestyle image / Link: [category LP]
    Slice 5 — CTA block · Background image / HED: [copy] / CTA: [CTA copy] / Link: [collection LP]

**TI kickers** (selected by `pick_ti_kicker()`):

#### `bndl_a` — BNDL Kicker A (`1:1297`)

    Kicker — BNDL Kicker A (1 slice) · 'Buy Now. Decide Later.' / 'Decisions are hard. Buy now, select your fabric later (and still get up to {pct} off).' / CTA: 'SHOP THE SALE' / Background border: [match to email] / Link: https://www.theinside.com/

#### `bndl_b` — BNDL Kicker B (`1:1393`)

    Kicker — BNDL Kicker B (1 slice) · 'Buy now. Decide later.' / 'Decisions are hard. Buy now, select your fabric later (and still get up to {pct} off).' / CTA: 'SHOP NOW' / Background color: [match to email] / Link: https://www.theinside.com/

#### `swatch_a` — Swatch Kicker A (`1:1287`)

    Kicker — Swatch Kicker A (1 slice) · HED: 'Find your favorite fabric' (fixed) / DEK: 'When you\'ve got 100+ fabrics to choose from, falling in love is kind of inevitable.' (fixed) / CTA: 'GET SWOONING' (fixed) / Border: [match to email] / Link: https://www.theinside.com/fabric-swatches

#### `swatch_b` — Swatch Kicker B (`1:1403`)

    Kicker — Swatch Kicker B (1 slice) · HED: 'Swoon-Worthy Swatches' (fixed) / DEK: 'When you\'ve got 100+ fabrics to choose from, falling in love is kind of inevitable.' (fixed) / CTA: 'shop now →' (fixed) / Border: [match to email] / Link: https://www.theinside.com/fabric-swatches

#### `link_farm_a` — Link Farm A (`1:1345`)

    Kicker — Link Farm A (6 slices) [% off per category — fill in from promo]:
      Kicker Slice 1 — Beds [full-width] · [% off] / Link: https://www.theinside.com/c/bedroom-furniture/beds
      Kicker Slice 2 — Curtains [50/50 left] · [% off] / Link: https://www.theinside.com/c/home-decor/curtains
      Kicker Slice 3 — Ottomans [50/50 right] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/ottomans
      Kicker Slice 4 — Curtains [50/50 left] · [% off] / Link: https://www.theinside.com/c/home-decor/curtains
      Kicker Slice 5 — Chairs [50/50 right] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/chairs
      Kicker Slice 6 — Sofas [full-width] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/sofas

#### `link_farm_b` — Link Farm B (`1:1311`)

    Kicker — Link Farm B (7 slices) [sale name, % off, and colors change per send]:
      Kicker Slice 1 — Header [full-width] · Eyebrow: '{sale_name_upper}' / Headline: 'Up To {pct} Off' / Link: https://www.theinside.com/
      Kicker Slice 2 — Beds [50/50 left] · Link: https://www.theinside.com/c/bedroom-furniture/beds
      Kicker Slice 3 — Furniture [50/50 right] · Link: https://www.theinside.com/collections/furniture
      Kicker Slice 4 — Curtains [50/50 left] · Link: https://www.theinside.com/c/home-decor/curtains
      Kicker Slice 5 — Ottomans [50/50 right] · Link: https://www.theinside.com/c/living-room-furniture/ottomans
      Kicker Slice 6 — Outdoor [50/50 left] · Link: https://www.theinside.com/collections/outdoorliving
      Kicker Slice 7 — Accent Chairs [50/50 right] · Link: https://www.theinside.com/c/living-room-furniture/chairs

<!-- END GENERATED: auto-briefed-slices -->
