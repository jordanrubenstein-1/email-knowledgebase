#!/usr/bin/env python3
"""
Render screenshots for canvas step HTML files referenced by the canvas map dashboard.

Substitutes content blocks (fetched via fetch_content_blocks.py) before rendering,
evaluating Liquid date conditionals as of RENDER_DATE so sale banners don't appear.

Usage:
    uv run python scripts/render_canvas_screenshots.py
    uv run python scripts/render_canvas_screenshots.py --force   # re-render all
"""

import argparse
import json
import re
import sys
import yaml
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML_DIR = ROOT / "campaigns" / "html"
YAML_DIR = ROOT / "campaigns"
RENDERED_DIR = ROOT / "campaigns" / "screenshots" / "rendered"
CONTENT_BLOCKS_DIR = ROOT / "data" / "content_blocks"
KICKER_CATALOG_CACHE_FILE = CONTENT_BLOCKS_DIR / "_kicker_catalog_cache.json"


def compute_render_date(brand: str | None = None) -> datetime:
    """Return noon UTC on the day *before* the most-recently-started sale.

    Reads data/sale_schedules.yaml and picks the highest start_date that is
    on or before today. Rendering at this date ensures sale banners in
    content blocks show their evergreen variant, since 'now' is always before
    the active sale began. No manual update is needed — re-running the script
    after syncing sale_schedules.yaml automatically picks the correct date.

    When `brand` is given, only that brand's sales are considered. Without it,
    sales are considered across all brands — this is wrong whenever two brands'
    sales start on different nearby dates (e.g. HAV starts a day after BUR):
    the freeze date would land after the earlier brand's sale already started,
    incorrectly showing its banner as active. Always pass `brand` when the
    render target's brand is known.
    """
    schedule_file = ROOT / "data" / "sale_schedules.yaml"
    today = datetime.now(timezone.utc).date()
    best: date | None = None
    try:
        sales = yaml.safe_load(schedule_file.read_text()).get("sales", [])
        for s in sales:
            if brand is not None and s.get("brand") != brand:
                continue
            try:
                sd = date.fromisoformat(str(s["start_date"]))
            except Exception:
                continue
            if sd <= today and (best is None or sd > best):
                best = sd
    except Exception:
        pass
    render_day = (best or today) - timedelta(days=1)
    return datetime(render_day.year, render_day.month, render_day.day, 12, 0, 0, tzinfo=timezone.utc)


# Freeze to noon UTC on the day before the most-recently-started sale so that
# content block date conditionals resolve to their evergreen (non-promo) branch.
# Computed automatically from data/sale_schedules.yaml — no manual update needed.
# This is the cross-brand fallback (used only where a brand isn't known); brand-specific
# rendering always computes its own render_ts via _render_ts_for_brand() below.
RENDER_DATE = compute_render_date()
RENDER_TS = int(RENDER_DATE.timestamp())

_BRAND_RENDER_TS_CACHE: dict[str, int] = {}


def _render_ts_for_brand(brand: str | None) -> int:
    if not brand:
        return RENDER_TS
    if brand not in _BRAND_RENDER_TS_CACHE:
        _BRAND_RENDER_TS_CACHE[brand] = int(compute_render_date(brand).timestamp())
    return _BRAND_RENDER_TS_CACHE[brand]

# Content blocks that require live user/session data — replaced with empty div
PERSONALIZATION_BLOCKS = {
    "browse_product_recs", "browse_product_recs_ab", "browsed_products",
    "cart_product_recs", "purchase_product_recs", "shopping_cart_items",
    "shopping_cart_items_2", "shopping_cart_items_DM",
    "shopping_cart_items_cart_viewed", "swatch_shopping_cart",
    "recs_sofas", "recs_sectionals", "recs_chairs", "recs_ottomans",
    "recs_beds", "recs_nightstands", "recs_rugs", "recs_pillows",
    "recs_dining_tables", "recs_dining_seating", "recs_lighting",
    "recs_art", "recs_accent_tables", "recs_benches",
}

# No per-slug banner suppression needed currently.
SUPPRESS_WELCOME_BANNER_SLUGS: set[str] = set()


# ── Liquid evaluator ──────────────────────────────────────────────────────────

def _eval_liquid_expr(expr: str, variables: dict, render_ts: int | None = None) -> int | str | None:
    """Evaluate a simple Liquid expression (variable reference or string | date: "%s")."""
    expr = expr.strip()
    # String literal | date: "%s" -> parse date string to Unix timestamp
    m = re.match(r'^"([^"]+)"\s*\|\s*date:\s*"%s"$', expr)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return None
    # 'now' | date: "%s" -> frozen render timestamp (brand-specific when given)
    if re.match(r"^'now'\s*\|\s*date:\s*\"%s\"$", expr):
        return render_ts if render_ts is not None else RENDER_TS
    # Variable reference
    if expr in variables:
        return variables[expr]
    return None


def _eval_condition(cond: str, variables: dict, render_ts: int | None = None) -> bool:
    """Evaluate a Liquid if-condition string like 'now >= sale_start and now < sale_end'."""
    # Split on ' and '/' or ' (process left-to-right, all must be true for 'and')
    parts = re.split(r'\s+and\s+', cond, flags=re.IGNORECASE)
    for part in parts:
        m = re.match(r'(\S+)\s*(>=|<=|==|!=|>|<)\s*(\S+)', part.strip())
        if not m:
            # Bare variable reference (no operator) — only evaluate if it's in our
            # known variables dict; otherwise it's a personalization variable we can't
            # evaluate, so default False (hide the branch rather than show wrong content).
            bare = part.strip()
            if bare in variables:
                return bool(variables[bare])
            return False
        lhs = _eval_liquid_expr(m.group(1), variables, render_ts)
        lhs = variables.get(m.group(1), lhs)
        rhs = _eval_liquid_expr(m.group(3), variables, render_ts)
        rhs = variables.get(m.group(3), rhs)
        op = m.group(2)
        if lhs is None or rhs is None:
            return False  # unknown variable — skip this branch
        try:
            lhs, rhs = int(lhs), int(rhs)
        except (TypeError, ValueError):
            return True
        if op == ">=" and not (lhs >= rhs): return False
        if op == "<=" and not (lhs <= rhs): return False
        if op == ">"  and not (lhs >  rhs): return False
        if op == "<"  and not (lhs <  rhs): return False
        if op == "==" and not (lhs == rhs): return False
        if op == "!=" and not (lhs != rhs): return False
    return True


def evaluate_liquid_dates(html: str, render_ts: int | None = None) -> str:
    """
    Evaluate Liquid assign + if/elsif/else/endif blocks that involve date comparisons.
    Everything else (personalization, canvas_entry_properties, etc.) is left as-is
    and will be handled by the content block substitution step or stripped later.

    `render_ts` is the frozen 'now' used for date comparisons — pass the brand-specific
    value from _render_ts_for_brand() so sale windows are evaluated against that brand's
    own sale calendar, not another brand's (see compute_render_date's docstring).
    """
    variables: dict = {}

    def process(text: str) -> str:
        out = []
        i = 0
        while i < len(text):
            # Find next Liquid tag
            tag_start = text.find("{%", i)
            if tag_start == -1:
                out.append(text[i:])
                break
            out.append(text[i:tag_start])
            tag_end = text.find("%}", tag_start)
            if tag_end == -1:
                out.append(text[tag_start:])
                break
            tag_content = text[tag_start + 2:tag_end].strip().lstrip('-').rstrip('-').strip()
            tag_end += 2

            # {% assign varname = expr %}
            m_assign = re.match(r'^assign\s+(\w+)\s*=\s*(.+)$', tag_content)
            if m_assign:
                varname = m_assign.group(1)
                val = _eval_liquid_expr(m_assign.group(2).strip(), variables, render_ts)
                if val is not None:
                    variables[varname] = val
                i = tag_end
                continue

            # {% if condition %}
            m_if = re.match(r'^if\s+(.+)$', tag_content)
            if m_if:
                # Collect all branches: if / elsif / else / endif
                # Find matching endif (handling nesting)
                depth = 1
                j = tag_end
                branches = [(m_if.group(1), tag_end)]  # (condition, content_start)
                else_pos = None
                while j < len(text) and depth > 0:
                    next_tag = text.find("{%", j)
                    if next_tag == -1:
                        break
                    next_end = text.find("%}", next_tag)
                    if next_end == -1:
                        break
                    inner = text[next_tag + 2:next_end].strip().lstrip('-').rstrip('-').strip()
                    if re.match(r'^if\b', inner):
                        depth += 1
                    elif inner == "endif":
                        depth -= 1
                        if depth == 0:
                            if else_pos is None:
                                branches[-1] = (branches[-1][0], branches[-1][1], next_tag)
                            else:
                                branches[-1] = (branches[-1][0], branches[-1][1], next_tag)
                            j = next_end + 2
                            break
                    elif depth == 1 and re.match(r'^elsif\b', inner):
                        # close previous branch
                        branches[-1] = (branches[-1][0], branches[-1][1], next_tag)
                        m_elsif = re.match(r'^elsif\s+(.+)$', inner)
                        branches.append((m_elsif.group(1) if m_elsif else "true", next_end + 2))
                    elif depth == 1 and inner == "else":
                        branches[-1] = (branches[-1][0], branches[-1][1], next_tag)
                        branches.append(("__else__", next_end + 2))
                    j = next_end + 2

                # Evaluate which branch to use
                chosen = None
                for branch in branches:
                    cond = branch[0]
                    content_start = branch[1]
                    content_end = branch[2] if len(branch) > 2 else j
                    if cond == "__else__":
                        chosen = text[content_start:content_end]
                        break
                    if _eval_condition(cond, variables, render_ts):
                        chosen = text[content_start:content_end]
                        break

                if chosen is not None:
                    out.append(process(chosen))
                i = j
                continue

            # {% comment %}...{% endcomment %} — skip entire block including content
            if tag_content == "comment":
                endcomment = text.find("endcomment", tag_end)
                if endcomment != -1:
                    close = text.find("%}", endcomment)
                    i = close + 2 if close != -1 else tag_end
                else:
                    i = tag_end
                continue

            # Skip other tags (for, endfor, elsif, else, endif handled above, etc.)
            i = tag_end

        return "".join(out)

    return process(html)


# ── Content block substitution ────────────────────────────────────────────────

def load_content_blocks(brand: str) -> dict[str, str]:
    """Load cached content block HTML for a brand. Returns name -> rendered_html."""
    brand_dir = CONTENT_BLOCKS_DIR / brand
    if not brand_dir.exists():
        return {}
    render_ts = _render_ts_for_brand(brand)
    blocks = {}
    for f in brand_dir.glob("*.html"):
        raw = f.read_text(encoding="utf-8")
        # Evaluate date Liquid in the block itself, against this brand's own sale calendar
        blocks[f.stem] = evaluate_liquid_dates(raw, render_ts=render_ts)
    return blocks


def _load_kicker_catalog_cache() -> dict:
    if KICKER_CATALOG_CACHE_FILE.exists():
        try:
            return json.loads(KICKER_CATALOG_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_kicker_catalog_cache(cache: dict) -> None:
    KICKER_CATALOG_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    KICKER_CATALOG_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def resolve_catalog_kicker(kicker_id: str, brand: str) -> str:
    """
    BUR's 'kicker' content block resolves its image via a Braze Catalog lookup
    (`{% catalog_items kickers {{ kicker_id }} %}`) rather than static Liquid —
    not something the local date/if evaluator can execute, so it otherwise renders
    blank. Fetch the resolved catalog item directly from the Braze Catalogs API
    (cached locally) and render the same img+link markup the content block uses.
    """
    cache = _load_kicker_catalog_cache()
    key = f"{brand}:{kicker_id}"
    if key not in cache:
        item = None
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from import_braze import init_config, braze_request
            init_config(brand)
            resp = braze_request(f"catalogs/kickers/items/{kicker_id}")
            items = (resp or {}).get("items", [])
            item = items[0] if items else None
        except Exception:
            item = None
        cache[key] = item
        _save_kicker_catalog_cache(cache)
    item = cache.get(key)
    if not item:
        return ""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td align="center" style="padding:0; margin:0;">'
        f'<a href="{item["url"]}">'
        f'<img src="{item["image_url"]}" alt="{item["alt_text"]}" width="600" '
        'style="display:block; width:100%; max-width:600px; height:auto; border:0;">'
        '</a></td></tr></table>'
    )


def _brand_for_html(slug: str) -> str | None:
    """Look up the brand for a canvas HTML file via its YAML."""
    yaml_path = YAML_DIR / f"{slug}.yaml"
    if not yaml_path.exists():
        return None
    try:
        data = yaml.safe_load(yaml_path.read_text())
        return data.get("brand")
    except Exception:
        return None


def substitute_content_blocks(html: str, blocks: dict[str, str], slug: str = "", brand: str | None = None) -> str:
    """Replace {{content_blocks.${name}}} tags with fetched HTML (or empty for personalization)."""
    suppress_welcome = slug in SUPPRESS_WELCOME_BANNER_SLUGS

    kicker_id_match = re.search(r'assign\s+kicker_id\s*=\s*"([^"]+)"', html)
    kicker_id = kicker_id_match.group(1) if kicker_id_match else None

    def replace(m):
        name = m.group(1)
        if name in PERSONALIZATION_BLOCKS:
            return ""
        if suppress_welcome and name == "2025Q3_Welcome_Banner_2":
            return ""
        if name == "kicker" and kicker_id and brand:
            resolved = resolve_catalog_kicker(kicker_id, brand)
            if resolved:
                return resolved
        if name in blocks:
            return blocks[name]
        return ""  # unknown block: remove rather than show raw Liquid

    return re.sub(
        r'\{\{content_blocks\.\$\{([^}]+)\}(?:[^}]*)?\}\}',
        replace,
        html,
    )


def strip_remaining_liquid(html: str) -> str:
    """Remove any remaining Liquid tags (output and block tags) that Playwright can't render."""
    # Strip full comment blocks including their text content
    html = re.sub(r'\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}', '', html, flags=re.DOTALL)
    html = re.sub(r'\{\{[^}]*\}\}', '', html)   # {{ ... }}
    html = re.sub(r'\{%[^%]*%\}', '', html)      # {% ... %}
    return html


def _inject_desktop_override(html: str) -> str:
    """
    Inject a CSS override that forces desktop column layout regardless of viewport width.

    BEE-editor emails include a responsive media query:
        @media (max-width:620px) { .stack .column { width:100%; display:block } }
    When a multi-column content block (e.g. nav_bar) is injected into a .stack row of
    the outer email, the block's <td class="column ..."> elements become descendants of
    .stack and get stacked at a narrow viewport.  Since we render at 640px (below the
    email's 620px breakpoint is avoided, but keep this as belt-and-suspenders), inject a
    rule AFTER the existing <style> block so it takes precedence via source order.
    """
    override = (
        "\n<style>"
        "/* render-override: prevent responsive stacking in dashboard thumbnails */"
        ".stack .column{width:auto!important;display:table-cell!important;}"
        "</style>\n"
    )
    if "</head>" in html:
        return html.replace("</head>", override + "</head>", 1)
    if "<body" in html:
        idx = html.find("<body")
        return html[:idx] + override + html[idx:]
    return override + html


def prepare_html(html: str, blocks: dict[str, str], slug: str = "", brand: str | None = None) -> str:
    html = evaluate_liquid_dates(html, render_ts=_render_ts_for_brand(brand))
    html = substitute_content_blocks(html, blocks, slug=slug, brand=brand)
    html = strip_remaining_liquid(html)
    html = _inject_desktop_override(html)
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def get_expected_filenames() -> list[str]:
    src = (ROOT / "scripts" / "lifecycle_canvas_map_dashboard.py").read_text()
    return re.findall(r'"f":\s*"(canvas-[^"]+\.png)"', src)


def main():
    parser = argparse.ArgumentParser(description="Render canvas step screenshots from HTML files")
    parser.add_argument("--force", action="store_true", help="Re-render even if PNG already exists")
    parser.add_argument("--only", help="Comma-separated HTML slugs (no extension) to force-render, ignoring existing files")
    args = parser.parse_args()

    RENDERED_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-load content blocks per brand
    brand_blocks: dict[str, dict] = {}

    only_slugs = {s.strip() for s in args.only.split(",")} if args.only else None

    expected = get_expected_filenames()
    to_render = []
    for fname in expected:
        slug = fname.replace(".png", "")
        if only_slugs is not None:
            if slug not in only_slugs:
                continue
        elif not args.force and (RENDERED_DIR / fname).exists():
            continue
        out = RENDERED_DIR / fname
        html_path = HTML_DIR / fname.replace(".png", ".html")
        if html_path.exists():
            to_render.append((html_path, out))
        else:
            print(f"  SKIP (no HTML): {fname}")

    if not to_render:
        print("All canvas screenshots already rendered.")
        return

    print(f"Rendering {len(to_render)} canvas screenshots (date frozen to {RENDER_DATE.date()})...")

    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT / "scripts"))
    from backfill_html_screenshots import capture_screenshot

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i, (html_path, out_path) in enumerate(to_render, 1):
            slug = html_path.stem
            brand = _brand_for_html(slug)

            # Load content blocks for this brand (cached per brand)
            if brand and brand not in brand_blocks:
                brand_blocks[brand] = load_content_blocks(brand)
            blocks = brand_blocks.get(brand, {})

            raw_html = html_path.read_text(encoding="utf-8")
            html = prepare_html(raw_html, blocks, slug=slug, brand=brand)

            ok = capture_screenshot(html, out_path, browser, width=640)
            # Convert PNG→JPEG in-place to reduce file size (~10x smaller, faster loads).
            # PIL reads by magic bytes so the .png extension is fine.
            if ok and out_path.exists():
                try:
                    from PIL import Image as _Image
                    _img = _Image.open(out_path).convert("RGB")
                    _img.save(out_path, format="JPEG", quality=85, optimize=True)
                except Exception:
                    pass
            status = "✓" if ok else "✗"
            brand_label = f"[{brand}]" if brand else ""
            print(f"  [{i}/{len(to_render)}] {status} {brand_label} {out_path.name}")
        browser.close()

    succeeded = sum(1 for _, out in to_render if out.exists())
    print(f"\nDone — {succeeded}/{len(to_render)} rendered to {RENDERED_DIR}")


if __name__ == "__main__":
    main()
