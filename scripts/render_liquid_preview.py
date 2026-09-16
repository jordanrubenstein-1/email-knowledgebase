"""
Render Braze canvas HTML emails with mock data substituted for Liquid templates.
Produces realistic-looking preview screenshots for FigJam board.

Usage:
    uv run python scripts/render_liquid_preview.py
    uv run python scripts/render_liquid_preview.py --file canvas-abandon-cart-cart-updated-t1-7a696095.html
"""

import re
import sys
import json
import argparse
import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

_REPO_ROOT = Path(__file__).parent.parent
HTML_DIR = _REPO_ROOT / "campaigns" / "html"
OUT_DIR  = _REPO_ROOT / "campaigns" / "screenshots" / "rendered"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── HTML filename → brand map (built from campaign YAMLs at startup) ──────────
import glob as _glob, yaml as _yaml

def _build_html_brand_map() -> dict[str, str]:
    mapping = {}
    for yf in _glob.glob(str(_REPO_ROOT / "campaigns" / "*.yaml")):
        try:
            data = _yaml.safe_load(open(yf))
            brand = data.get("brand", "")
            for send in (data.get("sends") or []):
                hf = send.get("html_file", "")
                if hf:
                    mapping[Path(hf).name] = brand
        except Exception:
            pass
    return mapping

_HTML_BRAND_MAP: dict[str, str] = _build_html_brand_map()

# ── Content block cache (real HTML fetched from Braze) ────────────────────────
# Sale banner blocks contain Liquid date conditionals.  Use the same directory-based
# loader as render_canvas_screenshots.py so that date conditions are evaluated at a
# frozen render date (day before the most-recently-started sale) rather than 'now'.
# JSON files supplement for any blocks not present in the per-brand directories.
_CB_CACHE_DIR = Path(__file__).parent.parent / "data" / "content_blocks"
sys.path.insert(0, str(Path(__file__).parent))
from render_canvas_screenshots import load_content_blocks as _load_dir_blocks
from render_canvas_screenshots import resolve_catalog_kicker as _resolve_catalog_kicker

_CONTENT_BLOCK_CACHE: dict[str, dict[str, str]] = {}

# Load JSON files first (legacy, no date evaluation — footers etc. with no date gates)
for _f in _CB_CACHE_DIR.glob("*.json"):
    _brand = _f.stem.upper()
    _CONTENT_BLOCK_CACHE[_brand] = json.loads(_f.read_text())

# Load per-brand HTML directories with Liquid date evaluation; directory blocks
# override JSON so date-gated sale banners always resolve to their evergreen variant.
for _brand_dir in sorted(_CB_CACHE_DIR.iterdir()):
    if _brand_dir.is_dir():
        _b = _brand_dir.name.upper()
        _dir_blocks = _load_dir_blocks(_b)
        if _b not in _CONTENT_BLOCK_CACHE:
            _CONTENT_BLOCK_CACHE[_b] = {}
        _CONTENT_BLOCK_CACHE[_b].update(_dir_blocks)

# ── Mock data ──────────────────────────────────────────────────────────────────

# Real Burrow product images from Braze CDN (from browse abandonment emails)
MOCK_PRODUCTS = [
    {
        "name": "Nomad Sofa",
        "url": "https://burrow.com/seating/nomad-sofa",
        "image_url": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a34c429fa006537a906/original.png?177015854",
    },
    {
        "name": "Range Coffee Table",
        "url": "https://burrow.com/storage/range-coffee-table",
        "image_url": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a41a2b1a70063bc058a/original.png?177015857",
    },
]

# Mock recently-browsed products for browse abandonment emails
# (loop uses {{ img }}, {{ url }}, {{ title }} after assign tags are stripped)
MOCK_BROWSE_PRODUCTS = [
    {
        "img": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a34c429fa006537a906/original.png?177015854",
        "url": "https://burrow.com/seating/nomad-sofa",
        "title": "Nomad Sofa",
    },
    {
        "img": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a41a2b1a70063bc058a/original.png?177015857",
        "url": "https://burrow.com/storage/range-coffee-table",
        "title": "Range Coffee Table",
    },
]

MOCK_ORDER = {
    "shopify_order_name": "#BUR-1234",
    "order_id": "BUR-1234",
    "order_status_url": "https://burrow.com/",
    "tracking_url": "https://burrow.com/",
    "subtotal": "1,299.00",
    "shipping": "0",
    "tax": "110.41",
    "total": "1,409.41",
    "discount": "0",
    "fullName": "Jane Smith",
    "address_1": "123 Main Street",
    "address_2": "",
    "city": "New York",
    "state": "NY",
    "zip": "10001",
    "country": "US",
    "orderId": "BUR-1234",
}

MOCK_ORDER_ITEMS = [
    {
        "name": "Nomad Sofa — Crushed Gravel",
        "image": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a34c429fa006537a906/original.png?177015854",
        "productLink": "https://burrow.com/seating/nomad-sofa",
        "quantity": "1",
        "image_url": "https://braze-images.com/appboy/communication/assets/image_assets/images/698e2a34c429fa006537a906/original.png?177015854",
    },
]

# Mock post_purchase_* custom attributes for canvas-post-purchase-table-buyer-no-dining-chairs
# (BUR dining chair rec email). Matches the real (Listo, Walnut) entry in CHAIR_RECS —
# scripts/braze_automation/sync_bur_post_purchase_attributes.py — so previews show the
# same recs/images this canvas has historically been rendered with.
MOCK_POST_PURCHASE_DINING_CHAIR_REC = {
    "post_purchase_product_name": "Listo Extendable Dining Table",
    "post_purchase_rec1_name": "Haiku Dining Chairs (Moss Green / Walnut)",
    "post_purchase_rec1_img": "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/DRST-DC-HKU-S2-MGWN.jpg?v=1744521819",
    "post_purchase_rec1_url": "https://burrow.com/dining/haiku-dining-chairs?sku=DRST-DC-HKU-S2-MGWN",
    "post_purchase_rec2_name": "Alto Dining Chairs (Papyrus / Walnut)",
    "post_purchase_rec2_img": "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/DRST-DC-ALT-S2-PYWN.webp?v=1747772360",
    "post_purchase_rec2_url": "https://burrow.com/dining/alto-dining-chairs?sku=DRST-DC-ALT-S2-PYWN",
    "post_purchase_rec3_name": "Alto Dining Chairs (Moss Green / Walnut)",
    "post_purchase_rec3_img": "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/DRST-DC-ALT-S2-MGWN.webp?v=1747772332",
    "post_purchase_rec3_url": "https://burrow.com/dining/alto-dining-chairs?sku=DRST-DC-ALT-S2-MGWN",
    "post_purchase_rec4_name": "Haiku Dining Chairs (Papyrus / Walnut)",
    "post_purchase_rec4_img": "https://cdn.shopify.com/s/files/1/0932/3220/2030/files/DRST-DC-HKU-S2-PYWN.jpg?v=1744521844",
    "post_purchase_rec4_url": "https://burrow.com/dining/haiku-dining-chairs?sku=DRST-DC-HKU-S2-PYWN",
}

MOCK_BROWSE_ITEM = {
    "image_url": "https://braze-images.com/appboy/communication/assets/image_assets/images/668eff5c6f3d26006319fd10/original.jpeg?1720647516",
    "url": "https://www.stfrank.com/collections/pillows",
    "name": "St. Frank Pillow",
    "event_source_url": "https://www.stfrank.com/collections/pillows",
    "product_url": "https://www.stfrank.com/collections/pillows",
    "sku": "STF-PILLOW-001",
}

# Per-brand mock footers — {year} is filled at render time with the current year
MOCK_FOOTER_BY_BRAND = {
    "BUR": (
        '<table width="100%" style="max-width:600px;">'
        '<tr><td style="padding:20px;text-align:center;font-family:Arial,sans-serif;font-size:11px;color:#888;">'
        '© {year} Burrow. All rights reserved. &nbsp;|&nbsp;'
        '<a href="https://burrow.com/pages/unsubscribe" style="color:#888;">Unsubscribe</a>'
        "</td></tr></table>"
    ),
    "ID": (
        '<table width="100%" style="max-width:600px;">'
        '<tr><td style="padding:20px;text-align:center;font-family:Arial,sans-serif;font-size:10px;color:#aaa;">'
        "Copyright &copy; {year}, Interior Define, 3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209"
        ' &nbsp;|&nbsp; <a href="#" style="color:#aaa;">Unsubscribe</a>'
        ' &nbsp;&middot;&nbsp; <a href="https://www.interiordefine.com/pages/privacy-policy" style="color:#aaa;">Privacy Policy</a>'
        "</td></tr></table>"
    ),
    "CZ": (
        '<table width="100%" style="max-width:600px;">'
        '<tr><td style="padding:15px;text-align:left;font-family:\'Open Sans\',Arial,sans-serif;font-size:10px;'
        'line-height:14px;color:#9D9D9D;">'
        "<em>Copyright &copy; {year}, The Citizenry, All rights reserved.</em><br><br>"
        "<em>3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209</em><br><br>"
        '<em>If you are no longer interested in receiving emails from us you can '
        '<a href="#" style="color:#9D9D9D;">Unsubscribe</a></em>'
        "</td></tr></table>"
    ),
}
# Generic fallback (not brand-specific)
MOCK_FOOTER_HTML = (
    '<table width="100%"><tr>'
    '<td style="padding:16px;text-align:center;font-family:Arial,sans-serif;font-size:11px;color:#888;">'
    '© {year} All rights reserved. &nbsp;|&nbsp;'
    '<a href="#" style="color:#888;">Unsubscribe</a>'
    "</td></tr></table>"
)

MOCK_NAV_HTML = """
<table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;background-color:#F7EEE3;">
  <tr>
    <td style="padding:12px 20px;text-align:center;">
      <a href="https://burrow.com" target="_blank">
        <img src="https://burrow-assets.s3.amazonaws.com/email.burrow/_2024/Workflows/Welcome/Q4-Welcome-touch-1/slice_for_SEATING.jpg"
             alt="Burrow" width="120" style="display:inline-block;height:auto;border:0;" />
      </a>
    </td>
    <td style="padding:12px;text-align:right;font-family:Arial,sans-serif;font-size:12px;color:#383633;">
      <a href="https://burrow.com/seating" style="color:#383633;text-decoration:none;margin:0 8px;">Seating</a>
      <a href="https://burrow.com/dining" style="color:#383633;text-decoration:none;margin:0 8px;">Dining</a>
      <a href="https://burrow.com/bedroom" style="color:#383633;text-decoration:none;margin:0 8px;">Bedroom</a>
    </td>
  </tr>
</table>
"""


# ── Preprocessor ──────────────────────────────────────────────────────────────

def make_product_card(product: dict) -> str:
    """Generate static HTML for a single cart product card."""
    return f"""
<table cellpadding="0" cellspacing="0" border="0" width="100%" align="center">
  <tr>
    <td align="center" style="padding: 20px 0px; background-color: #032033;">
      <table align="center" border="0" cellpadding="0" cellspacing="0" width="90%"
             style="max-width:542px;background-color:#F4F3F1;border-radius:10px;">
        <tr>
          <td align="center" style="padding:50px 0px;">
            <a href="{product['url']}">
              <img style="display:block;border:0;width:100%;max-width:430px;height:auto;margin:0 auto;"
                   width="430" alt="{product['name']}" border="0" src="{product['image_url']}" />
            </a>
            <h2 style="padding:15px 0 0;margin:0;text-align:center;font-family:Arial,sans-serif;
                        font-size:24px;line-height:28px;color:#032033;">
              <a href="{product['url']}" style="text-decoration:none;color:#032033;">{product['name']}</a>
            </h2>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""


def make_order_item_row(item: dict) -> str:
    """Generate static HTML for one order confirmation line item."""
    return f"""
<table align="center" border="0" cellpadding="0" cellspacing="0" width="90%" style="max-width:540px;">
  <tr>
    <td style="background-color:#FFFFFF;padding:0;">
      <div style="width:100%;max-width:540px;">
        <table border="0" cellpadding="0" cellspacing="0" width="540" style="width:100%;max-width:540px;">
          <tr>
            <td align="left" valign="middle" style="padding:40px 40px 40px 0;width:40%;max-width:220px;">
              <a href="{item['productLink']}">
                <img alt="{item['name']}" style="display:block;width:100%;max-width:220px;background:#FFF;"
                     border="0" src="{item['image']}" />
              </a>
            </td>
            <td align="right" valign="middle" style="padding:0;">
              <p style="margin:0;font-family:Arial,sans-serif;font-size:18px;color:#383633;">{item['name']}</p>
              <p style="margin:8px 0 0;font-family:Arial,sans-serif;font-size:16px;color:#888;">Qty. {item['quantity']}</p>
            </td>
          </tr>
        </table>
      </div>
    </td>
  </tr>
</table>"""


def make_shipping_item_row(item: dict) -> str:
    """Generate static HTML for a shipping confirmation line item."""
    return f"""
<table align="center" border="0" cellpadding="0" cellspacing="0" width="100%"
       style="max-width:600px;background-color:#F7EEE3;">
  <tr>
    <td style="padding:20px;text-align:center;">
      <img src="{item.get('image_url', item.get('image', ''))}" alt="{item['name']}"
           style="width:200px;height:auto;display:block;margin:0 auto;" />
      <p style="font-family:Arial,sans-serif;font-size:16px;color:#383633;margin:12px 0 0;">
        {item['name']}</p>
      <p style="font-family:Arial,sans-serif;font-size:14px;color:#888;margin:4px 0 0;">
        Qty. {item.get('quantity','1')}</p>
    </td>
  </tr>
</table>"""


def preprocess_html(html: str, filename: str) -> str:
    """
    Replace Liquid/Handlebars templates with mock data for preview rendering.
    """

    # ── 0a. Strip {% comment %}...{% endcomment %} blocks including content ──
    # Must happen first — comment text is raw visible text inside <div> elements
    html = re.sub(
        r'\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}',
        '', html, flags=re.DOTALL | re.IGNORECASE
    )

    # ── 0b. Handle recently-browsed products loop (browse abandonment emails) ──
    # Pattern: {% assign products_all = custom_attribute.${recently_browsed_products} ... %}
    #          {% assign products = products_all | reverse | slice: 0, 8 %}
    #          {% for product in products %}
    #            {% assign img = product.image_url ... %}
    #            {% assign url = product.url ... %}
    #            {% assign title = product.product_title ... %}
    #            ...HTML with {{ img }}, {{ url }}, {{ title }}...
    #          {% endfor %}
    html = re.sub(
        r'\{%-?\s*assign\s+products_all\s*=\s*custom_attribute[^%]+%\}',
        '', html
    )
    html = re.sub(
        r'\{%-?\s*assign\s+products\s*=\s*products_all[^%]+%\}',
        '', html
    )

    def replace_browse_loop(m):
        inner = m.group(1)
        # Strip all {% assign ... %} tags from the inner body
        inner = re.sub(r'\{%-?\s*assign\s+[^%]+%\}', '', inner)
        # Strip {% if forloop... %}...{% endif %} padding conditionals
        inner = re.sub(
            r'\{%-?\s*if\s+forloop\.[^%]+%\}.*?\{%-?\s*endif\s*-?%\}',
            '', inner, flags=re.DOTALL
        )
        # Duplicate for each mock product, substituting {{ img }}, {{ url }}, {{ title }}
        result = ''
        for p in MOCK_BROWSE_PRODUCTS:
            chunk = inner
            chunk = chunk.replace('{{ img }}', p['img'])
            chunk = chunk.replace('{{img}}', p['img'])
            chunk = chunk.replace('{{ url }}', p['url'])
            chunk = chunk.replace('{{url}}', p['url'])
            chunk = chunk.replace('{{ title | escape }}', p['title'])
            chunk = chunk.replace('{{ title }}', p['title'])
            result += chunk
        return result

    html = re.sub(
        r'\{%-?\s*for product in products\s*-?%\}(.*?)\{%-?\s*endfor\s*-?%\}',
        replace_browse_loop, html, flags=re.DOTALL
    )

    # ── 1. Strip MASTER_HEADER content block (it's the doctype — already have one in full HTML) ──
    html = re.sub(
        r'\{\{content_blocks\.\$\{MASTER_HEADER\}[^}]*\}\}',
        '', html, flags=re.IGNORECASE
    )

    # ── 2. Replace nav_us content block with simple nav ──
    html = re.sub(
        r'\{\{content_blocks\.\$\{nav_us\}[^}]*\}\}',
        MOCK_NAV_HTML, html, flags=re.IGNORECASE
    )

    # ── 3. Resolve content blocks from cache, fall back to mock footer ──
    # Brand lookup: YAML map first (handles canvas slugs with no brand code),
    # then fall back to regex on the filename itself (batch campaigns like
    # p_em_2025_07_15_id_d_quick_ship_email.html carry the brand in the name).
    _brand_key = _HTML_BRAND_MAP.get(filename, "")
    if not _brand_key:
        _brand_m = re.search(r'[_\-](?:BW|BUR|ID|CZ|HAV|STF|TI|TE|TRADE)[_\-\.]', filename.upper())
        _raw_brand = _brand_m.group(0).strip("_-.").upper() if _brand_m else ""
        _brand_key = "BUR" if _raw_brand == "BW" else _raw_brand
    _brand_cache = _CONTENT_BLOCK_CACHE.get(_brand_key, {})
    _footer_mock = (MOCK_FOOTER_BY_BRAND.get(_brand_key) or MOCK_FOOTER_HTML).format(
        year=datetime.date.today().year
    )
    _footer_names = re.compile(
        r'footer_us|footer|b2c_footer[^}]*|pre_converted_footer[^}]*|'
        r'converted_footer|B2C_Footer_Unsub|plain_footer|sale_footer_us|unsub_block|unsubscribe|'
        r'trade_unsubscribe|main_footer|All_Brands_Footer[^}]*',
        re.IGNORECASE,
    )
    _footer_injected = False

    # BUR's 'kicker' content block resolves its image via a Braze Catalog lookup
    # ({% catalog_items kickers {{ kicker_id }} %}), which the cached-HTML substitution
    # below can't execute — it would otherwise leave the block blank/broken. Resolve it
    # from the Braze Catalogs API instead (see resolve_catalog_kicker in
    # render_canvas_screenshots.py, cached locally).
    _kicker_id_match = re.search(r'assign\s+kicker_id\s*=\s*"([^"]+)"', html)
    _kicker_id = _kicker_id_match.group(1) if _kicker_id_match else None

    def _resolve_cb(m):
        nonlocal _footer_injected
        name = m.group(1)
        if name == "kicker" and _kicker_id and _brand_key:
            _resolved = _resolve_catalog_kicker(_kicker_id, _brand_key)
            if _resolved:
                return _resolved
        # If we have the real HTML for this block, use it (each block once)
        if name in _brand_cache:
            return _brand_cache[name]
        # Fall back to mock footer for known footer-pattern blocks (first only)
        if _footer_names.fullmatch(name):
            if not _footer_injected:
                _footer_injected = True
                return _footer_mock
            return ""  # strip duplicates
        return m.group(0)  # leave unknown blocks for step 4 to strip

    html = re.sub(
        r'\{\{content_blocks\.\$\{([^}]+)\}[^}]*\}\}',
        _resolve_cb, html, flags=re.IGNORECASE
    )

    # ── 4. Strip all remaining content_blocks references (banners, promos, etc.) ──
    html = re.sub(
        r'\{\{content_blocks\.\$\{[^}]*\}[^}]*\}\}',
        '', html, flags=re.IGNORECASE
    )

    # ── 4b. Resolve mock custom_attribute.${...} tags (post_purchase_* dining chair rec) ──
    def _resolve_custom_attribute(m):
        name = m.group(1)
        return MOCK_POST_PURCHASE_DINING_CHAIR_REC.get(name, m.group(0))

    html = re.sub(
        r'\{\{custom_attribute\.\$\{([^}]+)\}\}\}',
        _resolve_custom_attribute, html
    )

    # ── 5. Handle cart product loop ──
    # Pattern: {% assign items = canvas_entry_properties.${cart_items} %}
    #          {% for product in items %} ... {% endfor %}
    def replace_cart_loop(m):
        inner = m.group(1)
        result = ''
        for product in MOCK_PRODUCTS:
            chunk = inner
            chunk = chunk.replace('{{product.image_url}}', product['image_url'])
            chunk = chunk.replace('{{product.name}}', product['name'])
            chunk = chunk.replace('{{product.url}}', product['url'])
            chunk = re.sub(r'\{\{product\.[^}]+\}\}', product['name'], chunk)
            result += chunk
        return result

    # canvas_entry_properties.${cart_items} loop
    html = re.sub(
        r'\{%[-\s]*assign items\s*=\s*canvas_entry_properties\.\$\{cart_items\}\s*[-\s]*%\}',
        '', html
    )
    html = re.sub(
        r'\{%[-\s]*for product in items[-\s]*%\}(.*?)\{%[-\s]*endfor[-\s]*%\}',
        replace_cart_loop, html, flags=re.DOTALL
    )

    # ── 6. Handle order/shipping item loops ──
    # {% assign shoppingCartItems = {{ canvas_entry_properties.${products} }} %}
    # {% for item in {{shoppingCartItems}} %} ... {% endfor %}
    html = re.sub(
        r'\{%[-\s]*assign shoppingCartItems\s*=\s*\{\{[^}]+\}\}\s*[-\s]*%\}',
        '', html
    )
    html = re.sub(
        r'\{%[-\s]*assign products\s*=\s*\{\{[^}]+\}\}\s*[-\s]*%\}',
        '', html
    )

    def replace_item_loop(m):
        inner = m.group(1)
        result = ''
        for item in MOCK_ORDER_ITEMS:
            chunk = inner
            chunk = chunk.replace('{{item.image}}', item['image'])
            chunk = chunk.replace('{{item.image_url}}', item.get('image_url', item['image']))
            chunk = chunk.replace('{{item.name}}', item['name'])
            chunk = chunk.replace('{{item.productLink}}', item['productLink'])
            chunk = chunk.replace('{{item.quantity}}', item['quantity'])
            chunk = re.sub(r'\{\{item\.[^}]+\}\}', '', chunk)
            chunk = chunk.replace('{{item.shipmentTrackingUrl}}', '#')
            result += chunk
        return result

    html = re.sub(
        r'\{%[-\s]*for item in\s*\{\{(?:shoppingCartItems|products)\}\}\s*[-\s]*%\}(.*?)\{%[-\s]*endfor[-\s]*%\}',
        replace_item_loop, html, flags=re.DOTALL
    )

    # ── 7. Strip Liquid if/else/endif blocks (keep first/if branch only) ──
    def pick_if_branch(m):
        body = m.group(0)
        # Strip opening if and closing endif tags
        body = re.sub(r'\{%-?\s*if[^%]+%\}', '', body)
        body = re.sub(r'\{%-?\s*endif[-\s]*%\}', '', body)
        # Keep only the "if" branch (before {% else %})
        parts = re.split(r'\{%-?\s*else[-\s]*%\}', body)
        return parts[0]

    html = re.sub(
        r'\{%[-\s]*if[^%]+%\}.*?\{%[-\s]*endif[-\s]*%\}',
        pick_if_branch,
        html, flags=re.DOTALL
    )

    # ── 8. Replace scalar canvas_entry_properties variables ──
    def replace_entry_prop(m):
        key = m.group(1)
        mapping = {
            'shopify_order_name': MOCK_ORDER['shopify_order_name'],
            'order_status_url': MOCK_ORDER['order_status_url'],
            'tracking_url': MOCK_ORDER['tracking_url'],
            'order_id': MOCK_ORDER['order_id'],
            'orderId': MOCK_ORDER['orderId'],
            'subtotal': MOCK_ORDER['subtotal'],
            'shipping': 'Free',
            'tax': MOCK_ORDER['tax'],
            'total': MOCK_ORDER['total'],
            'discount': '',
            'fullName': MOCK_ORDER['fullName'],
            'address_1': MOCK_ORDER['address_1'],
            'address_2': MOCK_ORDER['address_2'],
            'city': MOCK_ORDER['city'],
            'state': MOCK_ORDER['state'],
            'zip': MOCK_ORDER['zip'],
            'country': MOCK_ORDER['country'],
            'name': 'Nomad Sofa',
            'image_url': MOCK_BROWSE_ITEM['image_url'],
            'url': MOCK_BROWSE_ITEM['url'],
            'event_source_url': MOCK_BROWSE_ITEM['event_source_url'],
            'product_url': MOCK_BROWSE_ITEM['product_url'],
        }
        return mapping.get(key, '')

    html = re.sub(
        r'\{\{canvas_entry_properties\.\$\{([^}]+)\}(?:\.[^}]*)?\}\}',
        replace_entry_prop, html
    )

    # ── 9. Replace misc Liquid variables ──
    html = html.replace('{{orderId}}', MOCK_ORDER['orderId'])
    html = re.sub(r'\{\{\$\{first_name\}\s*\|[^}]+\}\}', 'there', html)
    html = re.sub(r'\{\{\$\{[^}]+\}\}\}', '', html)  # strip remaining user attrs
    html = re.sub(r'\{\{[^}]*email_address[^}]*\}\}', 'you@example.com', html)

    # ── 10. Strip Handlebars-style tags from older order confirmation ──
    html = re.sub(r'\{\{#[^}]+\}\}', '', html)
    html = re.sub(r'\{\{/[^}]+\}\}', '', html)
    html = re.sub(r'\{\{#assign[^}]+\}\}.*?\{\{/assign\}\}', '', html, flags=re.DOTALL)

    # ── 11. Strip any remaining Liquid tags ──
    html = re.sub(r'\{%-?.*?-?%\}', '', html, flags=re.DOTALL)
    html = re.sub(r'\{\{[^}]+\}\}', '', html)

    return html


def render_to_png(html: str, output_path: Path, width: int = 640) -> Path:
    """Use Playwright to screenshot the pre-processed HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})

        # Set content and wait for images
        page.set_content(html, wait_until="networkidle")

        # Auto-height screenshot
        full_h = page.evaluate("() => document.body.scrollHeight")
        page.set_viewport_size({"width": width, "height": max(full_h, 100)})
        page.screenshot(path=str(output_path), full_page=True)
        browser.close()
    return output_path


def process_file(html_path: Path) -> Path:
    """Pre-process + render one HTML file. Returns path to new PNG."""
    html = html_path.read_text(encoding="utf-8")
    processed = preprocess_html(html, html_path.name)

    # Save processed HTML for debugging
    debug_path = OUT_DIR / (html_path.stem + ".processed.html")
    debug_path.write_text(processed, encoding="utf-8")

    out_png = OUT_DIR / (html_path.stem + ".png")
    render_to_png(processed, out_png)
    size_kb = out_png.stat().st_size // 1024
    print(f"  ✓ {out_png.name}  {size_kb} KB")
    return out_png


# ── Files to process ──────────────────────────────────────────────────────────
CANVAS_FILES = [
    # Welcome flows
    "canvas-welcome-flow-general-t1-e62bb422.html",
    "canvas-welcome-flow-general-t2-53d2aace.html",
    "canvas-welcome-flow-general-t3-5f5f4ce5.html",
    "canvas-welcome-flow-general-t4-3d70e6e4.html",
    "canvas-welcome-flow-general-t5-877ae7a1.html",
    "canvas-welcome-flow-general-t6-598a16ff.html",
    # Post-order welcome
    "canvas-post-order-welcome-to-new-subscribers-t1-eb805a94.html",
    "canvas-post-order-welcome-to-new-subscribers-t2-5a5b4f43.html",
    "canvas-post-order-welcome-to-new-subscribers-t3-2cf0cab1.html",
    "canvas-post-order-welcome-to-new-subscribers-t4-2a5dde7f.html",
    # Abandon browse
    "canvas-abandon-browse-multi-product-t1-2e9b7807.html",
    "canvas-abandon-browse-multi-product-t3-87c4dd97.html",
    "canvas-abandon-browse-product-viewed-t1-a3b17256.html",
    "canvas-abandon-browse-product-viewed-t3-d37d0bfe.html",
    # Abandon cart
    "canvas-abandon-cart-cart-updated-t1-7a696095.html",
    "canvas-abandon-cart-cart-updated-t3-0f358f66.html",
    "canvas-abandon-cart-cart-updated-t4-476ef1ef.html",
    "canvas-abandon-cart-cart-updated-t6-f5afc812.html",
    # Swatch post-purchase
    "canvas-swatch-post-purchase-t1-31f11c68.html",
    "canvas-swatch-post-purchase-t2-2baac239.html",
    "canvas-swatch-post-purchase-t3-8407a055.html",
    # Post-order cross-sell
    "canvas-post-order-cross-sell-t1-abfae1b7.html",
    # Transactional
    "canvas-order-confirmation-t1-acd00408.html",
    "canvas-shipping-confirmation-t1-e2316e3f.html",
    "canvas-out-for-delivery-t1-d58aa9c7.html",
    "canvas-delivery-confirmation-t1-d1824954.html",
    "canvas-post-shipment-delivered-raf-t1-a5da3eb2.html",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Single HTML filename to process")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        files = CANVAS_FILES

    print(f"Rendering {len(files)} email(s) with mock data...\n")
    results = []
    for fname in files:
        path = HTML_DIR / fname
        if not path.exists():
            print(f"  ⚠ Not found: {fname}")
            continue
        try:
            out = process_file(path)
            results.append(out)
        except Exception as e:
            print(f"  ✗ {fname}: {e}")

    print(f"\nDone → {OUT_DIR}")
    print(f"Rendered {len(results)} files")
