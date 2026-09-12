# Email Component Library

Reusable Liquid components for email templates, extracted from production campaigns across 5 brands.

## Components Summary

| Component | Frequency | Description |
|-----------|-----------|-------------|
| `hero_image.liquid` | 84.4% | Full-width linked image |
| `product_grid_2col.liquid` | 56.3% | Two-column product grid |
| `cta_button.liquid` | 27.8% | Styled button with Outlook VML |
| `paragraph.liquid` | 26.9% | Body text block |
| `divider.liquid` | 97% | Visible horizontal line separator |
| `product_card.liquid` | 12% | Product with image, name, and price |
| `product_grid_4col.liquid` | 7% | Four-column category grid |
| `headline.liquid` | 4.2% | Centered heading (h1), urgency callouts |
| `spacer.liquid` | 4.5% | Vertical spacing (invisible) |

---

## hero_image.liquid

**Full-width linked image** - The most common email pattern (84.4% of campaigns).

### Usage

```liquid
{% assign image = 'https://cdn.example.com/hero.jpg' %}
{% assign link = 'https://shop.example.com/sale' %}
{% assign alt = 'Summer Sale - Up to 50% Off' %}
{% render 'hero_image' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `image` | Yes | - | URL of the hero image |
| `link` | Yes | - | Click-through URL |
| `alt` | No | `''` | Alt text for accessibility |
| `title` | No | `alt` | Title attribute |
| `container_width` | No | `600` | Container width (600 or 640) |

---

## product_grid_2col.liquid

**Two-column product image grid** - Used in 56.3% of campaigns (1,857 files).

### Usage

```liquid
{% assign left_image = 'https://cdn.example.com/product1.png' %}
{% assign left_link = 'https://shop.example.com/product1' %}
{% assign left_alt = 'Product 1 Name' %}
{% assign right_image = 'https://cdn.example.com/product2.png' %}
{% assign right_link = 'https://shop.example.com/product2' %}
{% assign right_alt = 'Product 2 Name' %}
{% render 'product_grid_2col' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `left_image` | Yes | - | URL of left product image |
| `left_link` | Yes | - | URL for left product link |
| `right_image` | Yes | - | URL of right product image |
| `right_link` | Yes | - | URL for right product link |
| `left_alt` | No | `''` | Alt text for left image |
| `right_alt` | No | `''` | Alt text for right image |
| `container_width` | No | `600` | Container width in pixels |

### Brand-Specific Widths

| Brand | Container Width | Column Width |
|-------|-----------------|--------------|
| STF, ID, CZ | 600px | 300px |
| HAV | 640px | 320px |

---

## cta_button.liquid

**Call-to-action button** with Outlook VML support (27.8% of campaigns).

### Usage

```liquid
{% assign text = 'SHOP NOW' %}
{% assign link = 'https://shop.example.com' %}
{% render 'cta_button' %}

{% comment %} Custom colors {% endcomment %}
{% assign text = 'READ MORE' %}
{% assign link = 'https://blog.example.com/article' %}
{% assign bg_color = '#000000' %}
{% render 'cta_button' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `text` | Yes | - | Button label |
| `link` | Yes | - | Click-through URL |
| `bg_color` | No | `#d99218` | Background color |
| `text_color` | No | `#FFFFFF` | Text color |
| `font_size` | No | `16` | Font size in pixels |
| `font_family` | No | `'Bitter','Arial',Sans-serif` | Font stack |
| `border_radius` | No | `2` | Border radius in pixels |
| `padding_v` | No | `5` | Vertical padding |
| `padding_h` | No | `10` | Horizontal padding |

---

## headline.liquid

**Centered heading block** for section titles and urgency callouts (4.2% of campaigns).

### Usage

```liquid
{% comment %} Primary headline (34px Georgia) {% endcomment %}
{% assign text = 'Your Headline Here' %}
{% render 'headline' %}

{% comment %} Subheadline (18px Roboto) {% endcomment %}
{% assign text = 'Supporting text goes here' %}
{% assign font_size = 18 %}
{% assign font_family = "Roboto,Arial,Sans-serif" %}
{% render 'headline' %}

{% comment %} Urgency callout with background {% endcomment %}
{% assign text = 'ENDS TONIGHT' %}
{% assign font_size = 14 %}
{% assign bg_color = '#d99218' %}
{% assign color = '#ffffff' %}
{% assign text_transform = 'uppercase' %}
{% render 'headline' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `text` | Yes | - | Headline text |
| `font_size` | No | `34` | Font size in pixels |
| `font_family` | No | `Georgia,Arial,Sans-serif` | Font stack |
| `font_weight` | No | `400` | Font weight |
| `color` | No | `#2e3c47` | Text color |
| `line_height` | No | `1.2` | Line height multiplier |
| `padding` | No | `10` | Cell padding |
| `bg_color` | No | - | Background color (for urgency callouts) |
| `text_transform` | No | `none` | CSS text-transform (e.g., `uppercase`) |

---

## paragraph.liquid

**Body text block** for email content (26.9% of campaigns).

### Usage

```liquid
{% assign text = 'Your paragraph content here. Can include <strong>HTML</strong>.' %}
{% render 'paragraph' %}

{% comment %} Left-aligned variant {% endcomment %}
{% assign text = 'Left-aligned body copy.' %}
{% assign text_align = 'left' %}
{% render 'paragraph' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `text` | Yes | - | Paragraph content (HTML allowed) |
| `font_size` | No | `14` | Font size in pixels |
| `font_family` | No | `'Open Sans',Arial,Sans-serif` | Font stack |
| `color` | No | `#101b24` | Text color |
| `text_align` | No | `center` | Alignment (left/center/right) |
| `line_height` | No | `inherit` | Line height |
| `padding` | No | `10` | Cell padding |

---

## spacer.liquid

**Vertical spacing** (invisible) between sections. Common values: 5px, 20px, 25px.

### Usage

```liquid
{% assign height = 20 %}
{% render 'spacer' %}

{% comment %} Small spacer {% endcomment %}
{% assign height = 5 %}
{% render 'spacer' %}

{% comment %} Large spacer {% endcomment %}
{% assign height = 30 %}
{% render 'spacer' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `height` | No | `20` | Height in pixels |

---

## divider.liquid

**Visible horizontal line** to separate email sections. Use `spacer.liquid` for invisible spacing.

### Usage

```liquid
{% comment %} Simple gray divider {% endcomment %}
{% render 'divider' %}

{% comment %} Thick colored divider, centered {% endcomment %}
{% assign height = 2 %}
{% assign color = '#d4a574' %}
{% assign width = '60%' %}
{% render 'divider' %}

{% comment %} Divider with spacing {% endcomment %}
{% assign margin_top = 20 %}
{% assign margin_bottom = 20 %}
{% render 'divider' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `height` | No | `1` | Line thickness in pixels |
| `color` | No | `#e0e0e0` | Line color |
| `width` | No | `100%` | Width as percentage or pixels |
| `margin_top` | No | `0` | Top margin in pixels |
| `margin_bottom` | No | `0` | Bottom margin in pixels |

---

## product_card.liquid

**Product display** with image, name, and optional pricing. Use in grids or standalone for featured products.

### Usage

```liquid
{% comment %} Simple product {% endcomment %}
{% assign image = 'https://...' %}
{% assign link = 'https://...' %}
{% assign name = 'Union 3-Seat Sofa' %}
{% render 'product_card' %}

{% comment %} Product with sale price {% endcomment %}
{% assign image = 'https://...' %}
{% assign link = 'https://...' %}
{% assign name = 'Union 3-Seat Sofa' %}
{% assign original_price = '$2,499' %}
{% assign price = '$1,999' %}
{% render 'product_card' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `image` | Yes | - | Product image URL |
| `link` | Yes | - | Product page URL |
| `name` | Yes | - | Product name |
| `alt` | No | `name` | Image alt text |
| `price` | No | - | Current/sale price (e.g., "$1,999") |
| `original_price` | No | - | Original price for sale items (strikethrough) |
| `price_label` | No | `Sale` | Label before sale price |
| `width` | No | `270` | Image width in pixels |
| `font_family` | No | `'Open Sans',Arial,Sans-serif` | Font stack |
| `name_color` | No | `#383633` | Product name color |
| `price_color` | No | `#383633` | Sale price color |
| `original_price_color` | No | `#74706D` | Strikethrough price color |
| `show_underline` | No | `true` | Underline product name |

---

## product_grid_4col.liquid

**Four-column category navigation grid** — commonly used for category links (Seating, Dining, Storage, Bedroom).

### Usage

```liquid
{% assign col1_image = 'https://...' %}
{% assign col1_link = 'https://...' %}
{% assign col1_alt = 'Seating' %}
{% assign col2_image = 'https://...' %}
{% assign col2_link = 'https://...' %}
{% assign col2_alt = 'Dining' %}
{% assign col3_image = 'https://...' %}
{% assign col3_link = 'https://...' %}
{% assign col3_alt = 'Storage' %}
{% assign col4_image = 'https://...' %}
{% assign col4_link = 'https://...' %}
{% assign col4_alt = 'Bedroom' %}
{% render 'product_grid_4col' %}
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `col1_image` | Yes | - | First column image URL |
| `col1_link` | Yes | - | First column link URL |
| `col2_image` | Yes | - | Second column image URL |
| `col2_link` | Yes | - | Second column link URL |
| `col3_image` | Yes | - | Third column image URL |
| `col3_link` | Yes | - | Third column link URL |
| `col4_image` | Yes | - | Fourth column image URL |
| `col4_link` | Yes | - | Fourth column link URL |
| `col1_alt` | No | `''` | First column alt text |
| `col2_alt` | No | `''` | Second column alt text |
| `col3_alt` | No | `''` | Third column alt text |
| `col4_alt` | No | `''` | Fourth column alt text |
| `container_width` | No | `600` | Container width in pixels |
| `bg_color` | No | `transparent` | Background color |

---

## Email Structure

All components follow Braze email HTML conventions:

- **Table-based layouts** for maximum email client compatibility
- **Inline styles** (no external CSS)
- **MSO-specific styles** in conditional comments for Outlook
- **Mobile-responsive** via media queries (620px breakpoint)

### Typical Email Structure

```liquid
{% comment %} Full email example {% endcomment %}

{% assign image = 'https://...' %}
{% assign link = 'https://...' %}
{% render 'hero_image' %}

{% assign height = 20 %}
{% render 'spacer' %}

{% assign text = 'Main Headline' %}
{% render 'headline' %}

{% assign height = 5 %}
{% render 'spacer' %}

{% assign text = 'Subheadline text here' %}
{% assign font_size = 18 %}
{% assign font_family = "Roboto,Arial,Sans-serif" %}
{% render 'headline' %}

{% assign text = 'READ MORE' %}
{% assign link = 'https://...' %}
{% render 'cta_button' %}

{% assign height = 25 %}
{% render 'spacer' %}

{% assign left_image = 'https://...' %}
{% assign left_link = 'https://...' %}
{% assign right_image = 'https://...' %}
{% assign right_link = 'https://...' %}
{% render 'product_grid_2col' %}
```

---

## Testing

### Test Harness

`test_all_components.html` provides a complete email wrapper with all components. Render at 600px width to verify output.

### Visual Comparison

Screenshots are in this directory:
- `reference_original.png` - Original HAV Hideaway email
- `components_rendered.png` - Assembled components
- `component_library_report.png` - Full comparison report

---

## Source Reference

Components extracted from production campaigns:
- `p_2025_04_29_hav_conv_hideaway.html` (HAV - editorial)
- `p_2025_04_02_d_stf_trade_newness.html` (STF - product promo)
- `p_em_2025_07_19_id_d_finishing_touches.html` (ID - product grid)
