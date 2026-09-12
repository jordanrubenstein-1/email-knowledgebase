# Email Link Guide — When to Use Each Page Type

Analysis based on 1,556 email HTML files sent in the last year across HAV, CZ, ID, BUR (Aug 2025+), STF, and TI. SF and TI collections verified live March 2026.

---

## Universal Pattern: Cross-Brand Footer Links

Every brand includes homepage links to all five sister brands in the email footer:
- `https://burrow.com` → `https://interiordefine.com` → `https://the-citizenry.com` → `https://stfrank.com` → `https://theinside.com` → `https://havenly.com`

These are homepage-only links and appear in nearly every email. No action required — just a standard footer element.

---

## Linking to PDPs: Variant Selection Rules

When an email features a specific product in a specific color/fabric/finish, **always link directly to that variant** — not the base PDP. Showing a blue sofa in the email but landing on the default beige version creates friction and increases bounce.

### How variant links work (Shopify / most brands)
Shopify PDPs accept variant selection via query parameters. The exact parameter names and values must match the option names configured in the product exactly — including capitalization and spacing.

**Format:**
```
https://[brand].com/products/[product-slug]?[Option Name]=[Option Value]
```

**Example (The Citizenry):**
```
https://the-citizenry.com/products/lalita-wool-area-rug?Size=8%27%20x%2010%27&Color=Natural
```

**How to get the correct variant URL:** Navigate to the PDP on the live site, select the desired variant, and copy the URL from the browser address bar — this will have the correct parameter names and encoded values already populated.

### ⚠️ Burrow: Braze URL encoding bug with variant links
See the full details in the [Burrow section below](#️-burrow-pdp-links-variant-selection--braze-url-encoding-bug), but the short version: **all spaces in Burrow PDP query parameters must be encoded as `%20`, never `+`** — Braze converts `+` to `%2B` on save, which breaks variant selection.

---

## Burrow (burrow.com)

### Category / Department Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://burrow.com` | Default CTA when no specific category applies; general brand awareness |
| Seating | `https://burrow.com/seating` | Seating highlight emails, general promotional |
| Dining | `https://burrow.com/dining` | Dining-focused highlights |
| Storage | `https://burrow.com/storage` | Storage/shelving highlights |
| Bedroom | `https://burrow.com/bedroom` | Bedroom-focused emails |
| Rugs & Decor | `https://burrow.com/rugs-decor` | Rug/decor spotlights |
| Outdoor | `https://burrow.com/outdoor` | Outdoor/seasonal emails |
| Living | `https://burrow.com/living` | Living room roundups |

### Collection / Curated Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Clearance | `https://burrow.com/collections/clearance` | Sale emails, clearance CTAs |
| Best Sellers | `https://burrow.com/collections/best-sellers` | "Best of" roundups, re-engagement |
| Ready to Ship | `https://burrow.com/ready-to-ship` | Urgency/availability messaging |
| Sleeper Sofas | `https://burrow.com/collections/sleeper-sofas` | Sleeper-specific spotlight |
| Modular Furniture | `https://burrow.com/collections/modular-furniture` | Modular system feature emails |
| Pro Collection | `https://burrow.com/collections/pro-collection` | Pro/Plus tier messaging |
| Pro + Plus series | `https://burrow.com/pro-and-plus-series` | Upgrade/comparison content |
| Range Collection | `https://burrow.com/collections/range` | Range feature emails |
| Nomad Collection | `https://burrow.com/collections/nomad` | Nomad feature emails |
| Union Collection | `https://burrow.com/collections/union` | Union feature emails |
| Span Collection | `https://burrow.com/collections/span` | Span/sleeper storage feature |
| Sectionals | `https://burrow.com/sectionals` | Sectional category spotlight |
| Accent Chairs | `https://burrow.com/collections/accent-chairs` | Accent chair highlight |
| Dining Tables | `https://burrow.com/collections/dining-tables` | Dining table feature |
| Dining Chairs | `https://burrow.com/collections/dining-chairs` | Dining chair feature |
| Sofas | `https://burrow.com/sofas` | Sofa roundup / general |
| Leather Seating | `https://burrow.com/leather-seating` | Leather-specific callout |

### Specific Products (most frequently linked)
| Product | URL |
|---------|-----|
| Opera Media Console | `https://burrow.com/products/opera-media-console` |
| Opera Tall Media Console | `https://burrow.com/products/opera-tall-media-console` |
| Span Sleeper Sofa | `https://burrow.com/products/span-sleeper-sofa` |
| Shift Sleeper Sofa | `https://burrow.com/products/shift-sleeper-sofa` |
| Listo Dining Table | `https://burrow.com/products/listo-dining-table` |
| Gimlet Chair | `https://burrow.com/products/gimlet-chair` |
| Airmail Chair | `https://burrow.com/products/airmail-chair` |
| Vesper Leather Lounge Chair | `https://burrow.com/products/vesper-leather-lounge-chair` |
| Rye Recliner | `https://burrow.com/products/rye-recliner` |
| Range Plus 3-Piece Sofa | `https://burrow.com/products/range-plus-3-piece-sofa` |
| Union Pro 108 Chaise Sectional | `https://burrow.com/products/union-pro-108-chaise-sectional` |

### ⚠️ Burrow PDP Links: Variant Selection + Braze URL Encoding Bug

When linking to a Burrow PDP with a pre-selected variant (e.g. a specific fabric or finish), the variant is passed as query parameters — for example:
```
https://burrow.com/products/nomad-plus-sofa?Wood%20Finish=Walnut%20-%20Wood&Fabric=Nomad%20Linen%20Natural
```

**Critical rule: all spaces in parameter names and values must be encoded as `%20`, never as `+`.**

Braze has a known behavior where it re-encodes `+` characters in saved URLs — converting `+` to `%2B` on save. This means:
- If you enter `Wood+Finish=Walnut+-+Wood`, Braze saves it as `Wood%2BFinish=Walnut%20-%20Wood`
- The parameter key is now `Wood+Finish` (a literal plus) instead of `Wood Finish`, so the PDP's variant-matching script can't find a matching option and falls back to the default/base variant

**Always build Burrow PDP variant links using `%20` for spaces — never `+`.** Verify the final saved URL in Braze before launching to confirm no `%2B` appears where a space is intended.

### Utility / Content Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Swatches | `https://burrow.com/swatches` | Free swatch offers, fabric-first messaging |
| Showrooms | `https://burrow.com/showrooms` | In-person/local event tie-ins |
| Pet-Friendly Furniture | `https://burrow.com/pet-friendly-furniture` | Pet owner segment emails |
| Gift Card | `https://burrow.com/products/burrow-gift-card` | Gift guide or holiday emails |
| Refer a Friend | `https://burrow.com/refer` | Referral/loyalty campaigns |
| Fall Preview | `https://burrow.com/fall-preview` | Seasonal preview launches |
| Back to School | `https://burrow.com/collections/back-to-school` | Seasonal dorm/student campaign |

### Appointment Booking
| Page | URL | When to Use |
|------|-----|-------------|
| Showroom booking | `https://burrowhouseappointments.as.me/schedule/...` | In-person design consult campaigns |

---

## The Citizenry (the-citizenry.com)

### Top-Level Shop Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://the-citizenry.com` | Default CTA, general brand |
| Shop All Bedding | `https://the-citizenry.com/collections/shop-all-bedding-2` | Bedding-focused campaigns |
| Shop All Rugs | `https://the-citizenry.com/collections/shop-all-rugs-1` | Rug feature / rug sale |
| Shop All Furniture | `https://the-citizenry.com/collections/shop-all-furniture` | Furniture spotlight |
| Shop All Pillows | `https://the-citizenry.com/collections/shop-all-pillows` | Pillow highlight |
| All Best Sellers | `https://the-citizenry.com/collections/all-best-sellers` | Re-engagement, best-of roundups |
| All New Arrivals | `https://the-citizenry.com/collections/all-new-arrivals` | New arrival announcement |
| All Back in Stock | `https://the-citizenry.com/collections/all-back-in-stock` | BIS/back-in-stock alerts |
| All Accents | `https://the-citizenry.com/collections/all-accents` | Décor-focused sends |
| Shop All Bath | `https://the-citizenry.com/collections/shop-all-bath` | Bath product spotlights |
| All Baskets | `https://the-citizenry.com/collections/all-baskets` | Basket/storage feature |
| All Bed Bundles | `https://the-citizenry.com/collections/all-bed-bundles` | Bundle / value messaging |
| Ready to Ship | `https://the-citizenry.com/collections/ready-to-ship` | Availability / urgency |
| Ready to Ship — Furniture | `https://the-citizenry.com/collections/ready-to-ship-furniture` | Furniture-specific urgency |

### Sale / Event Landing Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Archive Sale | `https://the-citizenry.com/collections/archive-sale` | Clearance/archive sale campaigns (highest use) |
| Fresh Foundations Sale | `https://the-citizenry.com/collections/the-fresh-foundations-sale` | This specific sale |
| Spring Event | `https://the-citizenry.com/collections/the-spring-event` | Spring sale/event |
| Bedroom Event | `https://the-citizenry.com/collections/the-bedroom-event` | Bedroom-focused event |
| Summer Retreat Sale | `https://the-citizenry.com/collections/the-summer-retreat-sale` | Summer sale |
| Sunset Sale | `https://the-citizenry.com/collections/the-sunset-sale` | Late-summer sale |
| Weekender Sale | `https://the-citizenry.com/collections/the-weekender-sale` | Weekender event |
| Fall Refresh Event | `https://the-citizenry.com/collections/the-fall-refresh-event-2025` | Fall event |
| Holiday Shop | `https://the-citizenry.com/pages/2025-holiday-shop` | Holiday gift guide |

### Content / Editorial Pages
| Page | URL | When to Use |
|------|-----|-------------|
| The Layered Bed | `https://the-citizenry.com/pages/the-layered-bed` | Bedding editorial / how-to style |
| American Craft Collection | `https://the-citizenry.com/pages/the-american-craft-collection` | Craft/artisan editorial |
| Fall Collection 2025 | `https://the-citizenry.com/pages/the-fall-collection-2025` | New collection reveal |
| Pillow Pairings | `https://the-citizenry.com/pages/pillow-pairings` | Pillow styling guide |
| Artisan Index | `https://the-citizenry.com/pages/artisan-index` | Brand story / artisan origin content |
| Shop by Country | `https://the-citizenry.com/pages/shop-by-country` | Origin/artisan-focused emails |
| Sustainability | `https://the-citizenry.com/collections/shop-sustainably` | Impact / values messaging |
| About | `https://the-citizenry.com/pages/about` | Brand story, new subscriber onboarding |

### Destination / Inspiration Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Morocco Collection | `https://the-citizenry.com/collections/the-morocco-collection` | Collection-specific campaign |
| Mexico Collection | `https://the-citizenry.com/collections/the-mexico-collection` | Collection-specific campaign |
| Portugal Linen Collection | `https://the-citizenry.com/pages/the-portugal-stonewashed-linen-bedding-collection` | Collection-specific |
| Oaxaca Collection | `https://the-citizenry.com/pages/the-oaxaca-collection` | Collection-specific |
| Greenery Shop | `https://the-citizenry.com/pages/the-greenery-shop` | Seasonal/plant-adjacent |

### Editorial Blog
| Pattern | Example URL | When to Use |
|---------|-------------|-------------|
| Design | `https://the-citizenry.com/blogs/design/the-summer-trend-forecast` | Trend/style content |
| Travel | `https://the-citizenry.com/blogs/travel/the-kyoto-guide` | Travel/origin story content |

### Utility Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Trade Program | `https://the-citizenry.com/pages/trade-program-1` | Trade segment or cross-sell |
| Dallas Store | `https://the-citizenry.com/pages/the-citizenry-dallas` | Local event / store-specific |
| CZ Flagship | `https://the-citizenry.com/pages/the-citizenry-flagship` | Flagship store / in-person |
| Store Locator | `https://the-citizenry.com/pages/store-locator` | Event-driven / proximity |
| Rug Size Guide | `https://the-citizenry.com/pages/rug-size-and-style-guide` | Educational / nurture |
| Cart | `https://the-citizenry.com/cart` | Abandoned cart flows only |
| Gift Card | `https://the-citizenry.com/products/gift-card` | Gift-focused campaigns |
| Write a Review | `https://the-citizenry.com/a/review/write` | Post-purchase review request |
| Catalog Opt-In | `https://the-citizenry.com/pages/catalog-opt-in` | Physical catalog campaign |

### Third-Party Tools
| Tool | When to Use |
|------|-------------|
| `https://citizenryflagshipstyling.as.me/schedule/...` (Acuity) | Flagship styling appointment booking |
| `https://form.typeform.com/to/CKxdXtJj` | Sweepstakes / feedback form |

---

## Havenly (havenly.com)

### Core Service / Conversion Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://havenly.com` | Default CTA |
| Shop | `https://havenly.com/shop` | Product shop landing |
| Pricing | `https://havenly.com/pricing` | Conversion / nurture for non-customers |
| Interior Design Services | `https://havenly.com/interior-design-services` | Service pitch |
| AI Interior Design | `https://havenly.com/ai-interior-design` | AI feature campaigns |
| In-Person | `https://havenly.com/in-person` | In-person design service promotion |
| Interior Designers | `https://havenly.com/interior-designers` | Find-a-designer CTAs |
| Current Promotions | `https://havenly.com/current-promotions` | Sale / promo landing |
| Shop My Room | `https://havenly.com/shop-my-room` | Post-consult / design reveal follow-up |

### Shop by Category
| Page | URL | When to Use |
|------|-----|-------------|
| Living Room Furniture | `https://havenly.com/shop/category/living-room-furniture` | Room-specific campaigns |
| Bedroom Furniture | `https://havenly.com/shop/category/bedroom-furniture` | Bedroom-specific |
| Dining Room Furniture | `https://havenly.com/shop/category/dining-room-furniture` | Dining-specific |
| Decor & Pillows | `https://havenly.com/shop/category/decor-pillows` | Decor-focused |
| Rugs | `https://havenly.com/shop/category/rugs` | Rug highlight |
| Lighting | `https://havenly.com/shop/category/lighting` | Lighting feature |
| Outdoor Furniture | `https://havenly.com/shop/category/outdoor-furniture` | Outdoor/seasonal |

### Shop by Collection / Brand
| Page | URL | When to Use |
|------|-----|-------------|
| The Citizenry | `https://havenly.com/shop/collection/the-citizenry` | CZ cross-sell or CZ-focused |
| Burrow | `https://havenly.com/shop/collection/burrow` | BUR cross-sell |
| Interior Define | `https://havenly.com/shop/collection/interior-define` | ID cross-sell |
| St. Frank | `https://havenly.com/shop/collection/st-frank` | STF cross-sell |
| The Inside by Havenly | `https://havenly.com/shop/collection/the-inside-by-havenly` | Private label |
| Sale | `https://havenly.com/shop/collection/sale` | Sale discovery |
| Sofas & Sectionals | `https://havenly.com/shop/collection/sofas-sectionals` | Sofa feature |
| Dining Tables | `https://havenly.com/shop/collection/dining-tables` | Dining feature |
| Bedroom Favorites | `https://havenly.com/shop/collection/bedroom-favorites` | Bedroom roundup |
| Decor Under $100 | `https://havenly.com/shop/collection/decor-under-100` | Budget/gifting |

### Blog (SEO / Content Nurture)
Havenly links to blog posts more heavily than any other brand — used to nurture unconverted leads with design inspiration content.

| Category | Example URL | When to Use |
|----------|-------------|-------------|
| Room ideas | `https://havenly.com/blog/small-living-room-ideas-with-tv` | Room-specific segments |
| Trend content | `https://havenly.com/blog/mid-century-modern-trend` | Trend newsletters |
| Product guides | `https://havenly.com/blog/best-rugs` | Pre-purchase nurture |
| Color content | `https://havenly.com/blog/sage-green-paint` | Decorating inspiration |
| Before/after | `https://havenly.com/blog/room-makeover` | Transformation stories |
| Design mistakes | `https://havenly.com/blog/interior-design-regrets` | Problem-aware messaging |

### Inspiration / Portfolio
| Page | URL | When to Use |
|------|-----|-------------|
| Rooms | `https://havenly.com/rooms` | Design portfolio / inspiration |
| Interior Design Ideas | `https://havenly.com/exp/interior-design-ideas` | SEO landing / browse |
| Design Board (specific) | `https://havenly.com/interior-design-ideas/design-board/{id}` | Show actual work in emails |
| Style Quiz | `https://havenly.com/interior-design-style-quiz` | Top-of-funnel / re-engagement |

### Utility
| Page | URL | When to Use |
|------|-----|-------------|
| Reviews | `https://havenly.com/reviews` | Social proof emails |
| Gift | `https://havenly.com/gift` | Gift card / gifting campaigns |
| Cart | `https://havenly.com/cart` | Abandoned cart flows |

### Third-Party Tools
| Tool | When to Use |
|------|-------------|
| `https://havenly.app.link/...` (Branch.io) | App download / deep link CTAs |
| `https://apps.apple.com/us/app/havenly-interior-design/id1149153371` | App download (iOS) |
| `https://docs.google.com/forms/...` | Survey / feedback |

---

## Interior Define (interiordefine.com)

### Main Category Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://interiordefine.com` | Default CTA |
| Living — All Custom Sectionals | `https://interiordefine.com/living/all-custom-sectionals` | Sectional spotlight |
| Living — All Custom Sofas | `https://interiordefine.com/living/all-custom-sofas` | Sofa feature |
| Living — All Custom Chairs | `https://interiordefine.com/living/all-custom-chairs` | Accent chair feature |
| Custom Accent Chairs | `https://interiordefine.com/living/all-custom-chairs/custom-accent-chairs` | Accent chair specific |
| Dining | `https://interiordefine.com/dining` | Dining category |
| Bedroom | `https://interiordefine.com/bedroom` | Bedroom category |
| All Beds | `https://interiordefine.com/bedroom/all-beds` | Bed-specific |
| Rugs | `https://interiordefine.com/rugs` | Rug feature |
| Decor | `https://interiordefine.com/decor` | Décor / accessories |
| Lighting | `https://interiordefine.com/lighting` | Lighting feature |
| Outdoor | `https://interiordefine.com/outdoor` | Outdoor seasonal |
| New Arrivals | `https://interiordefine.com/new-arrivals` | Launch / new product |

### Availability / Urgency Pages
| Page | URL | When to Use |
|------|-----|-------------|
| In Stock | `https://interiordefine.com/in-stock` | Inventory-based urgency messaging |
| Quick Ship | `https://interiordefine.com/quick-ship` | Lead time / shipping-focused |
| Quick Ship Collections | `https://interiordefine.com/quick-ship-collections` | Urgency-driven promotions |

### Collection / Product Pages (most used)
| Collection | URL | When to Use |
|-----------|-----|-------------|
| Sloan Collection | `https://interiordefine.com/sloan-collection` | Sloan feature email |
| James Collection | `https://interiordefine.com/james-collection` | James feature email |
| Maxwell Collection | `https://interiordefine.com/maxwell-collection` | Maxwell feature email |
| Tatum Collection | `https://interiordefine.com/tatum-collection` | Tatum feature email |
| Jasper Collection | `https://interiordefine.com/jasper-collection` | Jasper feature |
| Lee Collection | `https://interiordefine.com/lee-collection` | Lee feature |
| Saylor Collection | `https://interiordefine.com/saylor-collection` | Saylor feature |

### Content / Resource Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Design Services | `https://interiordefine.com/design-services` | Free design consultation offer |
| Sectional Buying Guide | `https://interiordefine.com/sectional-buying-guide` | Educational / nurture |
| Rug Buying Guide | `https://interiordefine.com/rug-buying-guide` | Rug-specific nurture |
| Performance Fabrics Guide | `https://interiordefine.com/performance-fabrics-guide` | Fabric education |
| Comfort Guide | `https://interiordefine.com/comfort-guide` | Consideration-stage nurture |
| Shop the Catalog | `https://interiordefine.com/shop-the-catalog` | Full catalog discovery |
| Best Sellers | `https://interiordefine.com/best-sellers` | Re-engagement |
| Contract Grade | `https://interiordefine.com/contract-grade` | Trade / commercial segment |
| Book (consult) | `https://interiordefine.com/book` | Design consultation conversion |

### Location Pages
| Page | URL | When to Use |
|------|-----|-------------|
| All Locations | `https://interiordefine.com/locations` | Event-driven / store visits |
| Dallas | `https://interiordefine.com/locations/dallas` | Geo-targeted campaigns |
| Boston | `https://interiordefine.com/locations/boston` | Geo-targeted campaigns |
| Baltimore | `https://interiordefine.com/locations/baltimore` | Geo-targeted campaigns |

### Utility
| Page | URL | When to Use |
|------|-----|-------------|
| Gift Card | `https://interiordefine.com/gift-card` | Holiday / gifting |
| Sale | `https://interiordefine.com/sale` | Sale-specific campaigns |
| Cart | `https://interiordefine.com/cart` | Abandoned cart flows |
| Contact Us | `https://interiordefine.com/contact-us` | CS-driven or support follow-up |
| Fall Preview | `https://interiordefine.com/fall-preview` | Seasonal preview |
| Spring Edit | `https://interiordefine.com/the-spring-edit` | Seasonal preview |

### Subdomains
| Domain | URL | When to Use |
|--------|-----|-------------|
| Swatches | `https://swatches.interiordefine.com` | Free swatch request CTAs |
| Trade | `https://trade.interiordefine.com` | Trade program / B2B emails |

### Third-Party Tools
| Tool | When to Use |
|------|-------------|
| `https://form.typeform.com/to/avQR2W9q` | Feedback or survey (shared with CZ) |
| `https://docs.google.com/forms/...` | Survey / VIP feedback |
| `https://instagram.com/interiordefine` | Social follow CTAs (rare) |

---

## St. Frank (stfrank.com)

### Core Category Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://stfrank.com` | Default CTA |
| Pillows | `https://stfrank.com/collections/pillows` | Pillow-focused campaigns (most used) |
| Bedding | `https://stfrank.com/collections/bedding` | Bedding spotlight |
| Wallpaper | `https://stfrank.com/collections/wallpaper` | Wallpaper feature |
| Window Treatments | `https://stfrank.com/collections/window-treatments` | Curtain/drapery feature |
| Fabric by the Yard | `https://stfrank.com/collections/fabric-by-the-yard` | Fabric yardage purchase |
| Fabric Custom | `https://stfrank.com/collections/fabric-custom` | Custom order CTAs |
| New Release | `https://stfrank.com/collections/new-release` | New pattern launches |
| Outdoor Fabric | `https://stfrank.com/collections/outdoor-fabric` | Outdoor/summer feature |
| Outdoor Pillows | `https://stfrank.com/collections/outdoor-pillows` | Outdoor pillow highlight |
| All Outdoor | `https://stfrank.com/collections/all-outdoor` | Outdoor category page |
| Shop All Furniture | `https://stfrank.com/collections/shop-all-furniture` | Furniture cross-sell |
| Furniture | `https://stfrank.com/collections/furniture` | Furniture category (broader) |
| Rugs | `https://stfrank.com/collections/rugs` | Rug feature emails |
| Decor | `https://stfrank.com/collections/decor` | General décor/accessories |
| Swatches | `https://stfrank.com/collections/swatches` | Free swatch offer |
| Best Sellers | `https://stfrank.com/collections/best-seller` | Re-engagement / top picks |
| Back in Stock | `https://stfrank.com/collections/back-in-stock` | BIS / restocked product alerts |
| Quick Ship | `https://stfrank.com/collections/quick-ship` | Lead time / availability messaging |
| Art & Curiosities | `https://stfrank.com/collections/art-curiosities` | Wall art / decor feature |
| Sale | `https://stfrank.com/collections/sale` | General sale landing page |

### Sale Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Studio Sale | `https://stfrank.com/collections/the-studio-sale` | Clearance / archive sale |
| Spring Event | `https://stfrank.com/collections/the-spring-event` | Seasonal sale |
| Winter Refresh Event | `https://stfrank.com/collections/the-winter-refresh-event` | Winter sale event |
| Outdoor Flash Sale | `https://stfrank.com/collections/the-outdoor-flash-sale` | Flash sale / urgency |
| Black Friday Sale | `https://stfrank.com/collections/black-friday-sale` | BFCM campaigns |
| Sample Sale | `https://stfrank.com/collections/sample-sale` | Clearance / one-off availability |
| Yardage Sale | `https://stfrank.com/collections/yardage-sale` | Fabric-by-the-yard discount |
| Pillow Sale | `https://stfrank.com/collections/pillow-sale` | Pillow-specific markdown |
| Collaboration Sale | `https://stfrank.com/collections/collaboration-sale` | End-of-collaboration clearance |

### Pattern / Collection Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Gary Linden × St. Frank | `https://stfrank.com/collections/gary-linden-x-st-frank` | Collaboration launch |
| Forsyth × St. Frank | `https://stfrank.com/collections/forsyth-x-st-frank` | Collaboration feature |
| Forsyth × St. Frank Pillows | `https://stfrank.com/collections/forsyth-x-st-frank-pillows` | Collaboration pillow spotlight |
| Forsyth × St. Frank Rugs | `https://stfrank.com/collections/forsyth-x-st-frank-rugs` | Collaboration rug spotlight |
| Etkie × St. Frank | `https://stfrank.com/collections/st-frank-x-etkie` | Collaboration feature |
| Sally King Benedict × St. Frank | `https://stfrank.com/collections/sally-king-benedict-x-st-frank` | Collaboration feature |
| The Foggy Dog × St. Frank | `https://stfrank.com/collections/the-foggy-dog-x-st-frank` | Pet-themed collaboration |
| Mexico City in Photographs | `https://stfrank.com/collections/robert-malmberg-x-st-frank` | Photography / artisan collaboration |
| Green Lattice Baule & Indigo Daisy Suzani | `https://stfrank.com/collections/green-lattice-baule-indigo-daisy-suzani` | Pattern pairing spotlight |
| Suzani | `https://stfrank.com/collections/suzani` | Suzani pattern feature |
| Fuchsia Daisy Suzani | `https://stfrank.com/collections/fuchsia-daisy-suzani` | Pattern spotlight |
| Espresso Checkerboard | `https://stfrank.com/collections/espresso-checkerboard-suzani` | Pattern spotlight |
| Teal Vines Suzani | `https://stfrank.com/collections/teal-vines-suzani` | Pattern spotlight |
| Black Daisy Suzani | `https://stfrank.com/collections/black-daisy-suzani` | Pattern spotlight |
| Chambray Lattice Baule | `https://stfrank.com/collections/chambray-lattice-baule` | Pattern spotlight |
| Sage Ribbon Suzani Bedding | `https://stfrank.com/collections/sage-ribbon-suzani-bedding` | Bedding + pattern bundle |
| Shell Daisy Suzani | `https://stfrank.com/collections/shell-daisy-suzani` | Pattern spotlight |
| Perfect Pairings | `https://stfrank.com/collections/perfect-pairings` | Cross-sell / how-to-style |
| French Pleat Curtains | `https://stfrank.com/collections/french-pleat-curtains` | Curtain-focused CTAs |
| Coastal Cool | `https://stfrank.com/collections/coastal-cool` | Coastal / summer feature |

### Bedding Sub-Categories
| Page | URL | When to Use |
|------|-----|-------------|
| Sheet Sets | `https://stfrank.com/collections/sheet-sets` | Bedding detail / separation |
| Duvets | `https://stfrank.com/collections/duvets` | Duvet-specific |
| Quilts / Coverlets | `https://stfrank.com/collections/quilts-coverlets` | Seasonal warm/layer |
| Tabletop Linens | `https://stfrank.com/collections/tabletop-linens` | Entertaining / dining |
| Bedding Bundles | `https://stfrank.com/collections/bedding-bundles` | Value / gifting |

### Destination / Theme Collections
| Page | URL | When to Use |
|------|-----|-------------|
| Destination: Paris | `https://stfrank.com/collections/destination-paris` | Travel/editorial themed |
| Destination: Nantucket | `https://stfrank.com/collections/destination-nantucket` | Coastal/seasonal |
| Destination: Lake Como | `https://stfrank.com/collections/destination-lake-como` | Aspirational lifestyle |
| Destination: Tuscany | `https://stfrank.com/collections/destination-tuscany` | Aspirational lifestyle |
| Destination: Venice | `https://stfrank.com/collections/destination-venice` | Aspirational lifestyle |
| Italian Getaway | `https://stfrank.com/collections/your-italian-getaway` | Travel/editorial |

### Content / Editorial Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Press | `https://stfrank.com/press` | Brand credibility / editorial feature (very high use — appears in nearly every email as a nav item) |
| FAQ | `https://stfrank.com/pages/faq` | Objection-handling / post-purchase |
| Shop the Look: Dining | `https://stfrank.com/pages/shop-the-look-dining-rooms` | Styled room inspiration |
| Shop the Look: Living | `https://stfrank.com/pages/shop-the-look-living-rooms` | Styled room inspiration |
| Shop the Look: Bedrooms | `https://stfrank.com/pages/shop-the-look-bedrooms` | Styled room inspiration |
| Style Guide | `https://stfrank.com/pages/style-guide` | How-to-style educational |
| Trade | `https://stfrank.com/pages/trade` | Trade program |

### Seasonal Edits
| Page | URL | When to Use |
|------|-----|-------------|
| The Fall Edit | `https://stfrank.com/collections/the-fall-edit` | Fall seasonal email |
| The Winter Edit | `https://stfrank.com/collections/the-winter-edit` | Winter seasonal email |
| The Spring Edit | `https://stfrank.com/collections/the-spring-edit` | Spring seasonal email |
| Summer Essentials | `https://stfrank.com/collections/summer-essentials` | Summer seasonal email |
| The Atelier Collection | `https://stfrank.com/collections/the-atelier` | Elevated / curated capsule |

### Tabletop & Dining
| Page | URL | When to Use |
|------|-----|-------------|
| Tabletop | `https://stfrank.com/collections/tabletop` | General tabletop / entertaining |
| Entertaining | `https://stfrank.com/collections/entertaining` | Entertaining-focused emails |
| Dinnerware | `https://stfrank.com/collections/dinnerware` | Dinnerware feature |
| Serveware | `https://stfrank.com/collections/serveware` | Serving pieces spotlight |
| Glassware | `https://stfrank.com/collections/glassware` | Glassware feature |
| Table Linens | `https://stfrank.com/collections/table-linens` | Table linens (overlaps with tabletop linens) |
| Tabletop Linens + Decor | `https://stfrank.com/collections/tabletop-linens-decor` | Table styling roundup |

### Art & Framed
| Page | URL | When to Use |
|------|-----|-------------|
| Framed Art | `https://stfrank.com/collections/framed-textiles-and-prints` | Framed art spotlight |
| Framed Textiles | `https://stfrank.com/collections/framed-textiles` | Framed textile feature |
| Framed Prints | `https://stfrank.com/collections/prints` | Print collection |
| Vintage Art | `https://stfrank.com/collections/vintage-art` | Vintage / one-of-a-kind art |
| Photography | `https://stfrank.com/collections/photography` | Photography art feature |

### Specialty Rugs & Textiles
| Page | URL | When to Use |
|------|-----|-------------|
| Cactus Silk Rugs | `https://stfrank.com/collections/cactus-silk-rugs` | Cactus silk rug feature |
| Boujaad Rugs | `https://stfrank.com/collections/boujaad-rugs` | Moroccan rug spotlight |
| Kilim Collection | `https://stfrank.com/collections/kilim-collection` | Kilim rug feature |
| Oaxacan Embroidery | `https://stfrank.com/collections/oaxacan-embroidery` | Artisan / origin-story content |
| Huipil Collection | `https://stfrank.com/collections/huipil-pillows-art` | Artisan / cultural origin content |
| Linen Bedding | `https://stfrank.com/collections/linen-bedding` | Linen-specific bedding feature |
| Cotton Percale Bedding | `https://stfrank.com/collections/cotton-percale-bedding` | Percale-specific bedding feature |

### Gift Collections
| Page | URL | When to Use |
|------|-----|-------------|
| Gifts | `https://stfrank.com/collections/gifts` | Gift-focused campaigns |
| Gift Guide | `https://stfrank.com/collections/gift-guide` | Holiday gift guide CTA |
| Gift Sets | `https://stfrank.com/collections/gift-bundles` | Bundled gift sets |
| For Her | `https://stfrank.com/collections/for-her` | Gifting for her segment |
| For Him | `https://stfrank.com/collections/for-him` | Gifting for him segment |
| For the Host | `https://stfrank.com/collections/gifts-for-the-host` | Entertaining / host gift CTA |
| Mother's Day | `https://stfrank.com/collections/mothers-day` | Mother's Day campaign |
| Valentine's Day | `https://stfrank.com/collections/valentines-day` | Valentine's Day campaign |

### Holiday
| Page | URL | When to Use |
|------|-----|-------------|
| Holiday | `https://stfrank.com/collections/holiday` | General holiday landing |
| Holiday Decor | `https://stfrank.com/collections/holiday-decor` | Holiday décor spotlight |
| Stocking Stuffers | `https://stfrank.com/collections/stocking-stuffers` | Stocking-stuffer gift guide |
| For the Tree | `https://stfrank.com/collections/for-the-tree` | Tree ornaments / holiday decor |
| Stockings & Tree Skirts | `https://stfrank.com/collections/stockings-tree-skirts` | Holiday accessories |

### Nursery & Kids
| Page | URL | When to Use |
|------|-----|-------------|
| Nursery + Kids | `https://stfrank.com/collections/nursery-kids` | Kids / nursery segment |
| Nursery + Kids Decor | `https://stfrank.com/collections/nursery-kids-decor` | Nursery décor feature |

### Utility
| Page | URL | When to Use |
|------|-----|-------------|
| Gift Card | `https://stfrank.com/products/gift-card-1` | Holiday / gifting |

---

## The Inside (theinside.com)

Custom upholstered furniture brand — pieces are fully customizable with hundreds of fabric options. Collections are organized around fabric patterns, colorways, and editorial themes rather than product type alone.

### Core Pages
| Page | URL | When to Use |
|------|-----|-------------|
| Homepage | `https://theinside.com` | Default CTA |
| Living Room Edit | `https://www.theinside.com/collections/living-room-edit` | Living room / sofa feature |
| The Bedroom Edit | `https://www.theinside.com/collections/the-bedroom-edit` | Bedroom-focused campaign |
| Benches & Ottomans | `https://www.theinside.com/collections/benchesandottomans` | Accent / accent furniture feature |
| Kids' Furniture | `https://www.theinside.com/collections/kids-furniture` | Kids' room segment |

### Fabric & Customization
| Page | URL | When to Use |
|------|-----|-------------|
| Fabric Swatches | `https://www.theinside.com/fabric-swatches` | Free swatch offer; fabric-first messaging |
| Decide Fabric Later | `https://www.theinside.com/collections/decide-fabric-later` | Low-commitment entry CTA |

### Seasonal / Editorial Collections
| Page | URL | When to Use |
|------|-----|-------------|
| Spring Into Style | `https://www.theinside.com/collections/spring-2025-trends` | Spring seasonal send |
| Garden Party Edit | `https://www.theinside.com/collections/garden-party-edit` | Spring / outdoor entertaining |
| French Riviera Era | `https://www.theinside.com/collections/frenchrivieraera` | Aspirational summer editorial |
| Country Club Edit | `https://www.theinside.com/collections/country-club-edit` | Preppy / summer lifestyle |
| Hosting Edit | `https://www.theinside.com/collections/summer-dining-edit` | Dining / entertaining feature |
| Hosting Essentials | `https://www.theinside.com/collections/hosting-essentials` | Dining / hosting roundup |

### Pattern / Colorway Collections
| Page | URL | When to Use |
|------|-----|-------------|
| Marigold Delphine | `https://www.theinside.com/collections/marigolddelphine` | Pattern spotlight |
| Delphine | `https://www.theinside.com/collections/delphine` | Pattern spotlight |
| Florals | `https://www.theinside.com/collections/floral` | Floral print feature |
| Stripes | `https://www.theinside.com/collections/striped-furniture` | Stripe pattern feature |
| Tigresse | `https://www.theinside.com/collections/tigresse` | Pattern spotlight |
| Coastal Cool | `https://www.theinside.com/collections/coastalcool` | Coastal / casual palette |
| Coastal Fisherman | `https://www.theinside.com/collections/trending-coastal-fisherman` | Trending coastal look |
| Cherry Blossom | `https://www.theinside.com/collections/cherry-blossom` | Spring / floral pattern |
| Citrus Season | `https://www.theinside.com/collections/citrusseason` | Summer / bright palette |
| Citrine Cabana Stripe | `https://www.theinside.com/collections/citrine-cabana-stripe` | Summer stripe feature |
| Summer Blues | `https://www.theinside.com/collections/blue-furniture` | Blue colorway / summer |
| It Was All Yellow | `https://www.theinside.com/collections/yellow-furniture` | Yellow colorway feature |
| Central Park Toile | `https://www.theinside.com/collections/central-park-toile` | Toile / NYC-themed pattern |
| Animal Prints | `https://www.theinside.com/collections/animal-prints` | Animal print feature |

### Destination Collections
| Page | URL | When to Use |
|------|-----|-------------|
| Hudson Valley | `https://www.theinside.com/collections/destination-hudson-valley` | Destination / lifestyle editorial |
| New England | `https://www.theinside.com/collections/new-england-summer` | Coastal / preppy summer |
| Italy Travel Edit | `https://www.theinside.com/collections/italy-travel-edit` | Aspirational travel editorial |

### Collaborators
| Page | URL | When to Use |
|------|-----|-------------|
| CW Stockwell | `https://www.theinside.com/collaborators/cw-stockwell` | Collaboration launch / feature |

---

## Scheduling / Booking Tools (Third-Party)

| Brand | Tool | URL | When to Use |
|-------|------|-----|-------------|
| BUR | Acuity | `https://burrowhouseappointments.as.me/schedule/...` | Showroom appointment emails |
| CZ | Acuity | `https://citizenryflagshipstyling.as.me/schedule/...` | Flagship styling appointments |

## Surveys / Forms

| Brand | Tool | URL | When to Use |
|-------|------|-----|-------------|
| CZ | Typeform | `https://form.typeform.com/to/CKxdXtJj` | Sweepstakes entry |
| CZ + ID | Typeform | `https://form.typeform.com/to/avQR2W9q` | Shared feedback survey |
| HAV + ID | Google Forms | `https://docs.google.com/forms/d/e/...` | Customer feedback / VIP surveys |

---

## Notes

- **CZ `/cart`** appears only in triggered/abandonment flows, not batch sends
- **ID `/cart`** same — cart-abandon specific
- **HAV `/cart`** same — cart-abandon specific
- **STF `/press`** is linked in virtually every email as a footer navigation item, not a CTA
- **BUR sister-brand homepages** (ID, CZ, HAV, STF, TI) all appear 29x each — this is a fixed number indicating a single template variant that includes sister-brand footer links on every send
- **ID `clicks.interiordefine.com`** links are legacy click-tracking URLs from an older email platform — these should be phased out in favor of Braze native tracking
- **HAV** is the only brand with an app (iOS), reflected in Apple App Store links
- **BUR PDP variant links** — always use `%20` for spaces in query parameters; Braze converts `+` → `%2B` on save, which breaks variant selection (see Burrow section above for full details)
- **TI URLs** use `www.theinside.com` — the guide preserves this as-is; both `theinside.com` and `www.theinside.com` resolve correctly
- **STF "Chambray Lattice" in TI emails** — TI occasionally links to `stfrank.com/collections/chambray-lattice-baule` as a cross-brand product feature; treat as an STF link, not a TI link
- **STF internal collections** (Nacelle, Home page merch, OTM, Test Collection, etc.) are live Shopify collections but should not be used in customer-facing emails
