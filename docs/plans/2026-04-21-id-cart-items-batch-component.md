# ID Cart Items Batch Component Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `components/id_cart_items_batch.liquid` — a drop-in "In Your Cart" module for ID batch/blast emails, adapted from the existing canvas cart content block.

**Architecture:** Single Liquid/HTML file. Reads `custom_attribute.${shopping_cart_items_cart_viewed}` (user-level, available in batch sends). Wraps everything in an empty-check so nothing renders if the attribute is unset. Fixes the original's divider bug (border-bottom on every row including last) using `{% unless forloop.last %}`.

**Tech Stack:** Braze Liquid templating, HTML email tables (600px, Outlook-safe)

---

## Context

The original code lives in the ID cart abandonment canvas as a content block. Key differences from the original:

| Original (canvas) | New (batch) |
|---|---|
| No title | "In Your Cart" heading row |
| `border-bottom` on every product row (including last) | `border-top` separator only between products via `{% unless forloop.last %}` |
| No empty-state guard | Entire module hidden when attribute empty/unset |

The field names on `shopping_cart_items_cart_viewed` items are: `item.url`, `item.title`, `item.image`. These are unchanged.

---

### Task 1: Create the component file

**Files:**
- Create: `components/id_cart_items_batch.liquid`

**Step 1: Create the file with the empty-state guard and title**

Create `components/id_cart_items_batch.liquid` with the following content:

```liquid
{% assign cart_products = {{custom_attribute.${shopping_cart_items_cart_viewed}}} %}
{% if cart_products.size > 0 %}
<table align="center" cellpadding="0" cellspacing="0" style="background-color: #ffffff;" width="600">
  <tbody>
    <tr>
      <td style="padding: 20px 0 10px 0;">
        <p style="font-family: Roboto, Helvetica, Arial, sans-serif; font-size: 24px; line-height: 30px; color: #362b24; text-align: left; font-weight: 200; margin: 0; padding: 0;">In Your Cart</p>
      </td>
    </tr>
  </tbody>
</table>
{% for item in cart_products limit:8 %}
  <tr>
  <td>
  <table align="center" cellpadding="0" cellspacing="0" style="background-color: #ffffff; padding: 0px 0px 0px 0px;" width="600px">
  <tbody>
  <tr>
  <td>
  <table align="center" cellpadding="0" cellspacing="0">
  <tbody>
  <tr>
  <td align="center">
  <table border="0" cellpadding="0" cellspacing="0" style="margin: 0px auto; padding-top: 20px; padding-bottom: 20px; height: 200px; width: 600px;" width="600">
  <tbody>
  <tr>
  <td align="left" style="width: 200px; padding-right: 30px;"><a href="{{item.url}}?lid={{${cblid} | lid: 'sqfab9lkpbh2'}}" rel="noopener" target="_blank"><img alt="{{item.title}}" src="{{item.image}}" border="10" style="width: 200px; display: block; border: none;"> </a></td>
  <td align="center" style="width: 400px;">
  <p style="font-family: Roboto, Helvetica, Arial, sans-serif; font-size: 20px; line-height: 30px; color: #362b24; text-align: left; font-weight: 200; padding-bottom: 20px;">{{item.title}} </p>
  <div style="text-align: left;"><a class="CTA" href="{{item.url}}?lid={{${cblid} | lid: 'v6qq2yznb05l'}}" rel="noopener" style="background-color: #ffffff; border: 1px solid #000000; border-radius: 30px; color: #000000; display: inline-block; font-family: 'Sailec', Helvetica, Arial, sans-serif; font-size: 20px; font-weight: 450; line-height: 45px; text-align: center; text-decoration: none; width: 175px; -webkit-text-size-adjust: none;" target="_blank">Shop Now</a></div>
  </td>
  </tr>
  </tbody>
  </table>
  </td>
  </tr>
  </tbody>
  </table>
  </td>
  </tr>
  </tbody>
  </table>
  </td>
  </tr>
  {% unless forloop.last %}
  <tr>
  <td>
  <table align="center" cellpadding="0" cellspacing="0" width="600">
  <tbody>
  <tr>
  <td style="border-top: 1px solid rgb(238, 238, 238); font-size: 0; line-height: 0;">&nbsp;</td>
  </tr>
  </tbody>
  </table>
  </td>
  </tr>
  {% endunless %}
{% endfor %}
{% endif %}
```

Key changes from the original:
- `{% if cart_products.size > 0 %}...{% endif %}` wraps everything
- Title `<table>` block added before the `{% for %}` loop
- **Removed** `border-bottom: 1px solid rgb(238, 238, 238)` from the inner product table (`style="margin: 0px auto; padding-top: 20px; padding-bottom: 20px; height: 200px; width: 600px;"`)
- **Added** `{% unless forloop.last %}` separator row after each product row

**Step 2: Commit**

```bash
git add components/id_cart_items_batch.liquid
git commit -m "feat(id): add cart items batch component with title and conditional dividers"
```

---

### Task 2: Verify in Braze

**Step 1: Create a content block in Braze**

In the Braze dashboard: Content Blocks → Create Content Block → paste the contents of `id_cart_items_batch.liquid`. Note: Braze will auto-assign new LID values to replace the placeholder LID strings (`sqfab9lkpbh2`, `v6qq2yznb05l`) when you save.

**Step 2: Test with a populated cart attribute**

Preview the content block with a test user who has `shopping_cart_items_cart_viewed` set. Verify:
- "In Your Cart" title appears above the first product
- Each product has a 200px image left, title + "Shop Now" button right
- Horizontal dividers appear between products
- No divider appears after the last product

**Step 3: Test with an empty/unset attribute**

Preview with a user who has no `shopping_cart_items_cart_viewed` value. Verify: nothing renders — no title, no table, no whitespace gap.

**Step 4: Test edge cases**
- 1 product: title + product, no dividers
- 2 products: title + product + divider + product (no trailing divider)
- 8+ products: only first 8 shown, last has no trailing divider
