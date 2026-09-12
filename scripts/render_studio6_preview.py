"""
Render mock previews for the Studio 6 email family (HAV).

These three canvases key their entire body off canvas_entry_properties (room
render image, product list, alternative styles, moodboard image, call-recap
transcript/offer) — a webhook/event payload, not a Braze content block or
simple Liquid personalization tag. render_liquid_preview.py's generic
preprocess_html() has no notion of these fields, so this module substitutes
a realistic mock payload (same values as the previously-approved preview
render) and resolves the real converted_footer/unsubscribe/pre_converted_footer
content blocks from data/content_blocks/HAV/, then renders with Playwright.

Usage:
    uv run python scripts/render_studio6_preview.py
    uv run python scripts/render_studio6_preview.py --only recap
"""

import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
HTML_DIR = ROOT / "campaigns" / "html"
OUT_DIR = ROOT / "campaigns" / "screenshots" / "rendered"
CB_DIR = ROOT / "data" / "content_blocks" / "HAV"

# ── Mock event payload (canvas_entry_properties) ──────────────────────────────
# Same values as the originally-approved preview (components/hav_s6_followup_email_preview.html)
# so the look stays consistent with what's already been reviewed.

MOCK = {
    "room_render_image_url": "https://images.unsplash.com/photo-1616137466211-f939a420be84?w=1120&q=85&auto=format&fit=crop",
    "moodboard_image_url": "https://images.unsplash.com/photo-1616137466211-f939a420be84?w=1120&q=85&auto=format&fit=crop",
    "room_page_url": "https://havenly.com/rooms/preview",
    "purchase_url": "https://havenly.com/shop",
    "style_name": "Warm Transitional",
    "transcript_summary": (
        "You're looking for a warm, transitional living room that balances comfort with "
        "sophistication. Key priorities: a sectional that seats 5+, durable performance "
        "fabric for pets, and a dining table that extends for hosting."
    ),
    "upgrade_offer_message": (
        "As a thank you for your time today, we're offering 15% off your full room "
        "purchase if you complete checkout within 7 days."
    ),
    "product_list": [
        {"name": "Rowan Arm Chair", "price": 499, "image_url": "https://images.unsplash.com/photo-1506439773649-6e0eb8cfb237?w=180&q=80&auto=format&fit=crop", "pdp_url": "https://havenly.com/shop"},
        {"name": "Caramel Velvet Sectional", "price": 1099, "image_url": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=180&q=80&auto=format&fit=crop", "pdp_url": "https://havenly.com/shop"},
        {"name": "Barton Dining Table", "price": 1893.75, "image_url": "https://images.unsplash.com/photo-1549488344-1f9b8d2bd1f3?w=180&q=80&auto=format&fit=crop", "pdp_url": "https://havenly.com/shop"},
        {"name": "Linden Coffee Table", "price": 629, "image_url": "https://images.unsplash.com/photo-1567538096630-e0c55bd6374c?w=180&q=80&auto=format&fit=crop", "pdp_url": "https://havenly.com/shop"},
        {"name": "Josephine Machine Woven Rug", "price": 401.25, "image_url": "https://images.unsplash.com/photo-1600166898405-da9535204843?w=180&q=80&auto=format&fit=crop", "pdp_url": "https://havenly.com/shop"},
    ],
    "alternative_styles": [
        {"title": "Warm Transitional", "thumbnail_url": "https://images.unsplash.com/photo-1618220179428-22790b461013?w=400&q=80&auto=format&fit=crop", "url": "https://havenly.com/"},
        {"title": "Modern Organic", "thumbnail_url": "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=400&q=80&auto=format&fit=crop", "url": "https://havenly.com/"},
        {"title": "Coastal Classic", "thumbnail_url": "https://images.unsplash.com/photo-1600210492493-0946911123ea?w=400&q=80&auto=format&fit=crop", "url": "https://havenly.com/"},
    ],
}


def fmt_price(price: float) -> str:
    if float(price) == int(price):
        return f"${int(price):,}"
    return f"${price:,.2f}"


def resolve_content_blocks(html: str) -> str:
    """Swap {{content_blocks.${name} | id: '...'}} for the real cached block HTML."""
    def _sub(m):
        name = m.group(1)
        path = CB_DIR / f"{name}.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    return re.sub(r"\{\{content_blocks\.\$\{([^}]+)\}[^}]*\}\}", _sub, html, flags=re.IGNORECASE)


def strip_if(html: str, condition_pattern: str, keep: bool = True) -> str:
    """Strip a single {% if <condition_pattern> %}...{% endif %} pair (non-nested),
    keeping or dropping the inner content."""
    pattern = re.compile(
        r"\{%-?\s*if\s+" + condition_pattern + r"\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}",
        re.DOTALL,
    )
    return pattern.sub(lambda m: m.group(1) if keep else "", html, count=1)


def strip_trailing_liquid(html: str) -> str:
    html = re.sub(r"\{\{\$\{first_name\}\s*\|[^}]+\}\}", "there", html)
    html = re.sub(r"\{%-?.*?-?%\}", "", html, flags=re.DOTALL)
    # Braze personalization tags are {{${var}}} — three closing braces, since
    # ${...} itself ends in one. Strip these BEFORE the generic {{...}} catch-all,
    # which only consumes two braces and would leave a stray "}" behind.
    html = re.sub(r"\{\{\$\{[^}]+\}\}\}", "", html)
    html = re.sub(r"\{\{[^}]+\}\}", "", html)
    return html


# ── Per-template resolvers ────────────────────────────────────────────────────

def _resolve_assign_style_loop(html: str) -> str:
    """
    Handles the {% assign alt_styles = ... %}...{% for style in alt_styles %}
    {% if forloop.first %}{% assign _scp = "..." %}{% elsif forloop.last %}...{% else %}...{% endif %}
    <td ... style="...;{{_scp}}"> ... {% endfor %}
    shape used by 3D Room Generated and Canvas Generated Abandoned: the assign
    chain computes _scp but doesn't emit it inline — {{_scp}} is referenced
    later inside the <td> style attribute, so the assign block must be
    stripped to nothing (not substituted with the value) and {{_scp}} resolved
    separately at its own usage site.
    """
    style_loop_re = re.compile(
        r"\{%-?\s*assign\s+alt_styles\s*=\s*canvas_entry_properties\.alternative_styles\s*-?%\}"
        r"(.*?)\{%-?\s*for\s+style\s+in\s+alt_styles\s*-?%\}(.*?)\{%-?\s*endfor\s*-?%\}",
        re.DOTALL,
    )
    m = style_loop_re.search(html)
    if not m:
        return html
    prefix, inner = m.group(1), m.group(2)
    # Strip the {% if forloop.first %}...{% endif %} assign chain to nothing —
    # it only ever computes _scp, it never outputs anything itself.
    inner = re.sub(
        r"\{%-?\s*if\s+forloop\.first\s*-?%\}.*?\{%-?\s*endif\s*-?%\}",
        "",
        inner,
        count=1,
        flags=re.DOTALL,
    )
    chunks = []
    n = len(MOCK["alternative_styles"])
    for i, style in enumerate(MOCK["alternative_styles"]):
        chunk = inner
        if i == 0:
            pad = "padding-right:10px;"
        elif i == n - 1:
            pad = "padding-left:10px;"
        else:
            pad = "padding:0 5px;"
        chunk = chunk.replace("{{_scp}}", pad)
        chunk = chunk.replace("{{style.url}}", style["url"])
        chunk = chunk.replace("{{style.thumbnail_url}}", style["thumbnail_url"])
        chunk = chunk.replace("{{style.title}}", style["title"])
        chunks.append(chunk)
    return html[: m.start()] + prefix + "".join(chunks) + html[m.end() :]


def render_3d_room_generated(html: str) -> str:
    # style_name is present in the mock -> keep the if-branch
    html = strip_if(html, r"canvas_entry_properties\.style_name", keep=True)

    # Product loop: {% for product in products_arr %}{% if forloop.last %}{% assign _ppb = ... %}{% else %}...{% endif %}
    # <tr><td style="padding:0 40px {{_ppb}} 40px;">...{% assign _pc = ... %}...{% endif %}<p>{{_pfmt}}</p>...{% endfor %}
    # Both _ppb and _pfmt are computed by an assign chain and referenced LATER
    # via {{_ppb}}/{{_pfmt}} — the assign chains themselves emit nothing.
    loop_re = re.compile(
        r"\{%-?\s*assign\s+products_arr\s*=\s*canvas_entry_properties\.product_list\s*-?%\}"
        r"\s*\{%-?\s*for\s+product\s+in\s+products_arr\s*-?%\}(.*?)\{%-?\s*endfor\s*-?%\}",
        re.DOTALL,
    )
    m = loop_re.search(html)
    if m:
        inner = m.group(1)
        # Strip the forloop.last if/else/assign chain (computes _ppb, emits nothing)
        inner = re.sub(
            r"\{%-?\s*if\s+forloop\.last\s*-?%\}.*?\{%-?\s*endif\s*-?%\}",
            "",
            inner,
            count=1,
            flags=re.DOTALL,
        )
        # Strip the price-format assign chain (computes _pfmt, emits nothing)
        inner = re.sub(
            r"\{%-?\s*assign\s+_pc\s*=.*?\{%-?\s*endif\s*-?%\}",
            "",
            inner,
            count=1,
            flags=re.DOTALL,
        )
        chunks = []
        n = len(MOCK["product_list"])
        for i, product in enumerate(MOCK["product_list"]):
            chunk = inner
            is_last = i == n - 1
            chunk = chunk.replace("{{_ppb}}", "32px" if is_last else "16px")
            chunk = chunk.replace("{{_pfmt}}", fmt_price(product["price"]))
            chunk = chunk.replace("{{product.name}}", product["name"])
            chunk = chunk.replace("{{product.image_url}}", product["image_url"])
            chunk = chunk.replace("{{product.pdp_url}}", product["pdp_url"])
            chunks.append(chunk)
        html = html[: m.start()] + "".join(chunks) + html[m.end() :]

    html = _resolve_assign_style_loop(html)

    for key in ("room_render_image_url", "room_page_url", "purchase_url"):
        html = html.replace(f"{{{{canvas_entry_properties.${{{key}}}}}}}", MOCK[key])
    html = html.replace("{{canvas_entry_properties.${style_name}}}", MOCK["style_name"])

    html = resolve_content_blocks(html)
    return strip_trailing_liquid(html)


def render_canvas_generated_abandoned(html: str) -> str:
    # moodboard_image_url and style_name both present in mock -> keep both if-branches
    html = strip_if(html, r"canvas_entry_properties\.moodboard_image_url", keep=True)
    html = strip_if(html, r"canvas_entry_properties\.style_name", keep=True)

    html = _resolve_assign_style_loop(html)

    for key in ("room_page_url", "moodboard_image_url"):
        html = html.replace(f"{{{{canvas_entry_properties.${{{key}}}}}}}", MOCK[key])
    html = html.replace("{{canvas_entry_properties.${style_name}}}", MOCK["style_name"])

    html = resolve_content_blocks(html)
    return strip_trailing_liquid(html)


def render_recap(html: str) -> str:
    # Innermost-first: resolve the nested if/endif pairs before the outer wrapper.
    html = strip_if(
        html,
        r"canvas_entry_properties\.\$\{transcript_summary\}\s+and\s+canvas_entry_properties\.\$\{upgrade_offer_message\}",
        keep=True,
    )
    html = strip_if(html, r"canvas_entry_properties\.\$\{transcript_summary\}", keep=True)
    html = strip_if(html, r"canvas_entry_properties\.\$\{upgrade_offer_message\}", keep=True)
    html = strip_if(
        html,
        r"canvas_entry_properties\.\$\{transcript_summary\}\s+or\s+canvas_entry_properties\.\$\{upgrade_offer_message\}",
        keep=True,
    )
    html = strip_if(html, r"canvas_entry_properties\.style_name", keep=True)

    # Product loop (inline if/elsif price-format chain, no _pfmt/_ppb assigns)
    loop_re = re.compile(
        r"\{%-?\s*assign\s+products_arr\s*=\s*canvas_entry_properties\.product_list\s*-?%\}"
        r"\s*\{%-?\s*for\s+product\s+in\s+products_arr\s*-?%\}(.*?)\{%-?\s*endfor\s*-?%\}",
        re.DOTALL,
    )
    m = loop_re.search(html)
    if m:
        inner = m.group(1)
        chunks = []
        n = len(MOCK["product_list"])
        for i, product in enumerate(MOCK["product_list"]):
            chunk = inner
            is_last = i == n - 1
            chunk = re.sub(
                r"\{%-?\s*if\s+forloop\.last\s*-?%\}.*?\{%-?\s*endif\s*-?%\}",
                "32px" if is_last else "16px",
                chunk,
                flags=re.DOTALL,
            )
            chunk = re.sub(
                r"\{%-?\s*assign\s+_pc\s*=.*?\{%-?\s*endif\s*-?%\}",
                fmt_price(product["price"]),
                chunk,
                flags=re.DOTALL,
            )
            chunk = chunk.replace("{{product.name}}", product["name"])
            chunk = chunk.replace("{{product.image_url}}", product["image_url"])
            chunk = chunk.replace("{{product.pdp_url}}", product["pdp_url"])
            chunks.append(chunk)
        html = html[: m.start()] + "".join(chunks) + html[m.end() :]

    # Style loop — Recap's if/elsif/else/endif emits THREE COMPLETE <td> opening
    # tags (one per branch), not just a padding fragment referenced later like
    # the other two templates. Pick the matching branch per position, then
    # append the shared tail (everything from {% endif %} through </td>).
    style_loop_re = re.compile(
        r"\{%-?\s*for\s+style\s+in\s+alt_styles\s*-?%\}"
        r"\s*\{%-?\s*if\s+forloop\.first\s*-?%\}\s*(<td.*?>)\s*"
        r"\{%-?\s*elsif\s+forloop\.last\s*-?%\}\s*(<td.*?>)\s*"
        r"\{%-?\s*else\s*-?%\}\s*(<td.*?>)\s*"
        r"\{%-?\s*endif\s*-?%\}(.*?)</td>\s*"
        r"\{%-?\s*endfor\s*-?%\}",
        re.DOTALL,
    )
    m = style_loop_re.search(html)
    if m:
        td_first, td_last, td_middle, tail = m.group(1), m.group(2), m.group(3), m.group(4)
        chunks = []
        n = len(MOCK["alternative_styles"])
        for i, style in enumerate(MOCK["alternative_styles"]):
            if i == 0:
                td_open = td_first
            elif i == n - 1:
                td_open = td_last
            else:
                td_open = td_middle
            chunk = td_open + tail + "</td>"
            chunk = chunk.replace("{{style.url}}", style["url"])
            chunk = chunk.replace("{{style.thumbnail_url}}", style["thumbnail_url"])
            chunk = chunk.replace("{{style.title}}", style["title"])
            chunks.append(chunk)
        html = html[: m.start()] + "".join(chunks) + html[m.end() :]

    for key in ("room_render_image_url", "room_page_url", "purchase_url", "transcript_summary", "upgrade_offer_message"):
        html = html.replace(f"{{{{canvas_entry_properties.${{{key}}}}}}}", MOCK[key])
    html = html.replace("{{canvas_entry_properties.${style_name}}}", MOCK["style_name"])

    html = resolve_content_blocks(html)
    return strip_trailing_liquid(html)


JOBS = {
    "3d_room_generated": {
        "html_file": "canvas-studio-6-follow-up-3d-room-generated-t1-17f36cd5.html",
        "out_file": "canvas-studio-6-follow-up-3d-room-generated-t1-17f36cd5.png",
        "resolver": render_3d_room_generated,
        "width": 640,
        "scale": 2,
    },
    "canvas_generated_abandoned": {
        "html_file": "canvas-studio-6-follow-up-canvas-generated-abandoned-t1-a7a0474d.html",
        "out_file": "canvas-studio-6-follow-up-canvas-generated-abandoned-t1-a7a0474d.png",
        "resolver": render_canvas_generated_abandoned,
        "width": 640,
        "scale": 2,
    },
    "recap": {
        "html_file": "canvas-studio-6-recap-t1-658fbfe6.html",
        "out_file": "canvas-studio-6-recap-t1-658fbfe6.png",
        "resolver": render_recap,
        "width": 640,
        "scale": 2,
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=list(JOBS.keys()), help="Render a single job")
    args = parser.parse_args()

    jobs = {args.only: JOBS[args.only]} if args.only else JOBS

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for key, job in jobs.items():
            html = (HTML_DIR / job["html_file"]).read_text(encoding="utf-8")
            processed = job["resolver"](html)

            debug_path = OUT_DIR / (Path(job["out_file"]).stem + ".processed.html")
            debug_path.write_text(processed, encoding="utf-8")

            out = OUT_DIR / job["out_file"]
            width, scale = job["width"], job["scale"]
            context = browser.new_context(viewport={"width": width, "height": 800}, device_scale_factor=scale)
            page = context.new_page()
            page.set_content(processed, wait_until="networkidle")
            height = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": width, "height": min(height, 6000)})
            page.screenshot(path=str(out), full_page=True)
            context.close()
            print(f"{key}: {out.name}  ({width}x{height} @ {scale}x)")
        browser.close()


if __name__ == "__main__":
    main()
