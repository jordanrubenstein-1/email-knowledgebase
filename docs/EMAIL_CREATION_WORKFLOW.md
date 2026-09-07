# Email Component Analysis

*Analysis Date: January 2025*
*Brands Analyzed: BUR (Burrow), ID (Interior Define), CZ (The Citizenry)*
*Updated: January 2025 — Added Hero Suite recommendation from AI debate*

---

## Executive Summary

Despite HTML being hand-coded per email, **visual structures are highly repetitive**. The "design" per email is actually:
1. Which 4-6 components to stack
2. What order
3. What images/copy to slot in

**A ~10 component library could cover 90%+ of emails.**

However, the hero component requires special treatment. After extensive analysis and AI-assisted debate (Claude vs. Gemini), we recommend a **"Hero Suite"** of three distinct modules rather than one, plus an evolution in upstream creative workflow.

---

## Performance Data by Brand

| Brand | Avg Click Rate | Design Approach | Notes |
|-------|----------------|-----------------|-------|
| BUR | 1.01% | Most bespoke HTML | Lowest performer |
| ID | 1.07% | Builder-style templates | List quality issues documented |
| CZ | 1.58% | Hybrid approach | — |
| HAV | 1.87% | Diverse layouts | Best opens (52.5%) |
| STF | 2.06% | Product-focused | Highest clicks, most standardized |

**Key Insight**: The most bespoke approach (BUR) correlates with the lowest click rates. The most standardized/product-focused approach (STF) correlates with the highest. However, causation is unclear — other factors (AOV, list quality, product mix) confound the data.

---

## Universal Components (All Brands)

| Component | Description | Variation Per Email |
|-----------|-------------|---------------------|
| **Header** | Brand logo + nav | Fixed per brand |
| **Hero** | Full-width image with text | See "Hero Suite" below |
| **Text Block + CTA** | Centered headline + body + button | Copy changes, layout identical |
| **2-Col Product Grid** | Product image + name (+ price) | Products change, grid identical |
| **Footer** | Legal, social, unsubscribe | Fixed per brand |

---

## Brand-Specific Patterns

| Pattern | BUR | ID | CZ |
|---------|-----|----|----|
| Hero with text overlay baked into image | ✓ | ✓ | ✓ |
| Category section (header → lifestyle → products) | ✓ | ✓ | ✓ |
| Category buttons grid | | ✓ | ✓ |
| Feature callouts (icon + text) | ✓ | | |
| Cross-brand section | | ✓ | ✓ |
| Banner CTA (full-width colored) | ✓ | | |

---

## Typical Email Structures

```
BUR Flash Sale:           ID Spring Edit:           CZ Spring Event:
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ Header          │       │ Header          │       │ Header          │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Hero + overlay  │       │ Hero + overlay  │       │ Hero + overlay  │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Text + CTA      │       │ Text + CTA      │       │ Text + CTA      │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Product Grid    │       │ Category Section│       │ Category Buttons│
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Banner CTA      │       │ Category Section│       │ Cross-brand     │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Footer          │       │ Footer          │       │ Footer          │
└─────────────────┘       └─────────────────┘       └─────────────────┘
```

---

## Hero Text Analysis (Deep Dive)

### Current Implementation
All three brands bake text into hero images. Text is NOT HTML — it's part of the image file.

### Text Position Variations Observed

| Email | Position | Font Style | Treatment |
|-------|----------|------------|-----------|
| BUR Flash Sale Launch | Center-top | Sans-serif bold | Dark semi-transparent bar |
| BUR Flash Sale Shift | Upper-left | Sans-serif bold | None (white on photo) |
| BUR Bestsellers | Upper-left | Script/cursive | Orange background band |
| ID Friends & Family | Center-middle | Script/cursive | None (on photo) |
| ID Spring Edit | Upper-left | Serif | Solid color band (not on photo) |
| CZ Spring Event | Center-left | Mixed sizes | Dark overlay on photo |
| CZ Morocco | Above image | Serif | Solid background (not overlaid) |

### The Variation Problem

```
BUR Flash Sale:        BUR Bestsellers:       ID Friends & Family:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ ██████████████  │    │Bestsellers      │    │                 │
│ ██ CENTERED ██  │    │ script font     │    │  friends &      │
│ ██████████████  │    │                 │    │  family sale    │
│                 │    │                 │    │    [button]     │
│    [photo]      │    │    [photo]      │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

**Positions vary**: center, left, top, middle, above image entirely
**Fonts vary**: sans-serif, serif, script/cursive, mixed sizes
**Treatments vary**: overlay bars, floating text, solid color bands

---

## AI Debate: Standardization vs. Customization

### The Debate (Claude vs. Gemini)

**Claude's initial position**: Design variations are critically important to brand identity.

**Gemini's counter-arguments**:
1. Performance data shows most-bespoke (BUR) = lowest clicks; most-standardized (STF) = highest clicks
2. Text-in-image creates accessibility, deliverability, and dark mode problems
3. "Escape hatches" for custom designs undermine system adoption

**Convergence point**: Neither full standardization nor full customization is optimal.

### Recommendation: The "Hero Suite" (3 Modules)

Instead of one hero template or unlimited customization, implement three purpose-built hero modules:

| Module | Use Case | Frequency | Text Handling |
|--------|----------|-----------|---------------|
| **Live Text Hero** | Background image + HTML text overlay | ~80% | HTML text, AI places in safe zones |
| **Split Hero** | Text on solid color above image | ~15% | HTML text, no overlap with image |
| **Branded Image Hero** | Full image with text baked in | <5% | Image-based, requires ALT text |

#### Live Text Hero
- **When to use**: Image has a "text-safe zone" (sky, wall, negative space)
- **How it works**: 3-4 pre-defined positions (center-top, left-top, bottom with overlay)
- **Benefits**: Accessible, responsive, performant

#### Split Hero
- **When to use**: Image has no text-safe zone, or editorial/storytelling focus
- **How it works**: Solid color band with headline, image below
- **Benefits**: Works with any image, clean separation

#### Branded Image Hero
- **When to use**: Script fonts, complex compositions, true "brand moments"
- **How it works**: Designer creates complete hero as static image
- **Requirements**: Must include ALT text with headline content
- **Benefits**: Full creative control for special campaigns

---

## Text Placement: AI vs. Designer

### What AI Can Do Well
- Detect readable zones (low complexity areas)
- Apply composition rules (rule of thirds, golden ratio)
- Identify visual balance
- Measure contrast for readability

### What AI Cannot Do (Yet)
- Judge "does this feel premium?" for your specific brand
- Match brand-specific aesthetic preferences without training
- Make subjective compositional calls that break rules intentionally

### Recommended Approach

| Email Type | Text Placement Approach |
|------------|------------------------|
| **Routine batch emails (60%)** | AI places automatically using safe zone detection + composition rules |
| **Brand-moment emails (40%)** | AI proposes 2-3 options, designer picks or adjusts |

**Key principle**: For premium brands where aesthetics matter, text placement isn't just readability — it's beauty. AI proposes, designer approves (at least until brand-specific training exists).

### Future Option: Brand-Trained AI

Train AI on 50+ "exemplary" heroes per brand to learn brand-specific aesthetic preferences:
- BUR prefers: centered text, dark overlays, bold sans-serif
- CZ prefers: airy top placement, minimal overlay, elegant serif
- ID prefers: left-aligned, color band separators, modern sans

---

## Upstream Creative Process Changes

### Current Problem
Designers composite text over arbitrary images, creating technical fragility and inconsistent results.

### Recommended Evolution

1. **Plan photoshoots with "text-safe zones"** when images are destined for email
2. **Create email-specific assets** rather than repurposing web/social images
3. **Train creative teams** on "channel-aware" production (email is a distinct medium)

This isn't restricting creativity — it's mastering the medium, like photographers do for magazine covers.

---

## Final Component Library (~10 components)

```
1. header_{brand}           ← Fixed per brand
2. hero_live_text           ← Background image + HTML text (80% of heroes)
3. hero_split               ← Text above, image below (15% of heroes)
4. hero_branded_image       ← Full baked image for special cases (5% of heroes)
5. text_block_centered      ← AI fills copy
6. cta_button               ← AI fills text/URL
7. product_grid_2col        ← Dynamic from catalog
8. category_section         ← Header + lifestyle image + products
9. category_buttons_grid    ← AI generates from category list
10. feature_callouts        ← Icon + text pairs
11. banner_cta              ← Full-width colored banner
12. footer_{brand}          ← Fixed per brand
```

---

## Designer vs AI Responsibility (Updated)

### Designer's Work Per Campaign
- **Select/create hero image** — provide image asset
- **For Live Text Hero**: Approve AI's text placement (or adjust)
- **For Branded Image Hero**: Create full hero with text baked in
- **Review final assembled email**

### AI's Work Per Campaign
- Recommend component stack based on campaign type
- **Analyze hero image for text-safe zones**
- **Propose text placement options** (for Live Text Hero)
- Fill copy into text blocks
- Generate product grid from catalog
- Assemble email from components
- Handle segment variations

---

## Workflow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. BRIEF GENERATION (AI)                                        │
│    - Recommend component stack                                  │
│    - Suggest hero type (Live Text / Split / Branded Image)      │
│    - Generate copy for text blocks                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. HERO IMAGE (Designer)                                        │
│    - Provide/select hero image                                  │
│    - For Branded Image: create full hero with text              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. TEXT PLACEMENT (AI proposes, Designer approves)              │
│    - AI analyzes image for safe zones                           │
│    - AI suggests 2-3 placement options                          │
│    - Designer picks or routine emails auto-approve              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. ASSEMBLY (AI)                                                │
│    - Combine components + hero + copy + products                │
│    - Generate segment variations if needed                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. REVIEW & PUBLISH                                             │
│    - Designer/Marketer reviews preview                          │
│    - Push to Braze                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Screenshots Analyzed

### Burrow (BUR)
- `20241022_index-highlight_ip-warming-day-1.png`
- `20241022_seating-highlight-ip-warming-day-1.png`
- `20241023_bestsellers_ip-warming-day-2.png`
- `20241024_seating-flash-sale-launch_ip-warming-day-.png`
- `20241027_seating-flash-sale-shift-highlight_ip-war.png`

### Interior Define (ID)
- `2025_03_08_id_the_finishing_touches_decor_d.png`
- `2025_03_09_id_the_spring_edit_email.png`
- `2025_04_10_id_friends_family_sale_start_email.png`

### The Citizenry (CZ)
- `copy-of-p_2024_08_13_d_cz_l_morocco_collection_lau.png`
- `braze-support-copy-of-p_2025_1_23_d_cz_potomac_bed.png`
- `bfcm-2024-black-friday-fund-post-purchase.png`
- `copy-of-p_2025_03_12_d_cz_the_spring_event_ea_laun.png`

---

## Appendix: AI Debate Summary

**Participants**: Claude (Opus 4.5) vs. Gemini 2.5 Pro

**Topic**: Should email hero design be standardized or remain bespoke?

**Key arguments for standardization (Gemini)**:
1. Performance data doesn't support bespoke → better results
2. Text-in-image is technically fragile (accessibility, deliverability)
3. Escape hatches undermine system adoption
4. Operational efficiency enables focus on higher-impact work

**Key arguments for customization (Claude)**:
1. Brand aesthetics matter for premium positioning
2. Script fonts can't be replicated in HTML
3. Compositional decisions are creative, not just functional
4. Low-volume, high-AOV businesses may value brand over speed

**Convergence**:
- Adopt "Live Text First" as default (accessible, performant)
- Build Hero Suite with three modules for different needs
- Evolve upstream creative process to plan for email constraints
- AI proposes text placement, designer approves for aesthetic judgment
