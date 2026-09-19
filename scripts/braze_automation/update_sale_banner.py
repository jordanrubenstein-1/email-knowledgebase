#!/usr/bin/env python3
"""
Update Braze sale banner content blocks for a new sale.

Fetches the current HTML for each brand's sale banner content blocks, rewrites
the Liquid date variables and image blocks for the new sale, and pushes the
update back via content_blocks/update. The prior sale's variables are renamed
with a prefix so they stay as reference for future manual editors.

Currently supported brands: CZ (clean HTML/Liquid), ID (DnD wrapper)

Usage:
    # CZ Summer Retreat Sale (reg-only, single phase)
    uv run python scripts/braze_automation/update_sale_banner.py \\
        --brand CZ \\
        --reg-start  "2026-06-05 07:00:00" \\
        --sale-end   "2026-06-09 07:00:00" \\
        --reg-image  "https://braze-images.com/.../original.png" \\
        --reg-link   "https://www.the-citizenry.com/" \\
        --reg-alt    "Summer Retreat Sale" \\
        --dry-run

    # Full 3-phase sale (EA + main + extension)
    uv run python scripts/braze_automation/update_sale_banner.py \\
        --brand CZ \\
        --ea-start   "2026-11-24 07:00:00" \\
        --ea-image   "https://braze-images.com/.../ea.png" \\
        --ea-link    "https://www.the-citizenry.com/" \\
        --ea-alt     "Early Access: 25% Off" \\
        --reg-start  "2026-11-28 07:00:00" \\
        --reg-image  "https://braze-images.com/.../main.png" \\
        --reg-link   "https://www.the-citizenry.com/" \\
        --reg-alt    "Black Friday Sale: 25% Off" \\
        --ext-start  "2026-12-01 07:00:00" \\
        --ext-image  "https://braze-images.com/.../ext.png" \\
        --ext-link   "https://www.the-citizenry.com/" \\
        --ext-alt    "Extended: 25% Off" \\
        --sale-end   "2026-12-03 07:00:00"

Variable convention:
    sale_ea_start, sale_reg_start, sale_extension_start, sale_end are the
    standardized names always used for the current active sale.

    When a phase is omitted:
        --ea-start omitted  → sale_ea_start = sale_reg_start (EA window = 0)
        --ext-start omitted → sale_extension_start = sale_end (extension = 0)
"""

import argparse
import asyncio
from datetime import datetime
import json
import logging
import re
import string
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from import_braze import init_config, get_api_key, get_base_url, normalize_brand
from braze_campaign_api import braze_post_request

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Brand config — blocks to update per brand
# ---------------------------------------------------------------------------

BRAND_BLOCKS = {
    "CZ": {
        "api_key_env": "BRAZE_API_KEY_CZ",
        "structure": "plain",   # clean HTML/Liquid, no DnD wrapper
        "blocks": [
            {"name": "sale_b2c_banner",    "id": "a71504fd-ec1f-4c01-b143-03fc277d26ab", "has_evergreen": False},
            {"name": "Welcome_Promo_Banner","id": "a9ff9798-f4b0-4489-a0b5-d48d1c9f072e", "has_evergreen": True},
        ],
    },
    "BUR": {
        "api_key_env": "BRAZE_API_KEY_BUR",
        "structure": "plain",   # clean HTML/Liquid, same as CZ — API update
        "blocks": [
            {"name": "2025Q3_Abandon_Banner", "id": "b04c8f92-ac84-4e1e-9bb8-a0f7868a12f6", "has_evergreen": False},
        ],
    },
    "ID": {
        "api_key_env": "BRAZE_CONTENT_BLOCKS_API_KEY_ID",
        "structure": "dnd",     # DnD-generated wrapper; edit via Playwright (API blocks DnD updates)
        "workspace_id": "6666726b459b5e0059d7d687",
        "blocks": [
            {
                "name": "sale_b2c_banner",
                "id": "e5978bcf-a82a-4ac4-ae24-2451908fe189",
                "edit_url_id": "66cfe9655e8448006720e558",  # Braze dashboard MongoDB ID
                "has_evergreen": False,
            },
            {
                "name": "welcome_promo",
                "id": "4de56627-db9d-4fef-834d-d5edd8338f6b",
                "edit_url_id": "68efafc10f33360083dc832e",
                "has_evergreen": True,
                # Hardcoded evergreen — don't extract from current block (may be absent after cleanup)
                "evergreen_html": (
                    '<div style="max-width:600px">'
                    '<a href="https://www.interiordefine.com/?lid={{${cblid} | lid: \'j7wmgwh38ndf\'}}" target="_blank">'
                    '<img src="https://braze-images.com/appboy/communication/assets/image_assets/images/68efaf4f053179006334c3b0/original.png?1760538446"'
                    ' style="display:block;height:auto;border:0;width:100%" width="600"'
                    ' alt="15% Off Your Next Order. Use Code: WELCOME15-A6J8D3."'
                    ' title="15% Off Your Next Order. Use Code: WELCOME15-A6J8D3." height="auto">'
                    '</a></div>'
                ),
            },
        ],
    },
    "IDTEST": {
        "api_key_env": "BRAZE_CONTENT_BLOCKS_API_KEY_ID",
        "base_brand": "ID",   # used for init_config (base URL lookup)
        "structure": "dnd",
        "workspace_id": "6666726b459b5e0059d7d687",
        "blocks": [
            {
                "name": "welcome_promo_test",
                "id": "919a8ad6-ffc8-446d-a9d9-dad5bf93065a",
                "edit_url_id": None,   # unknown — will navigate via list page
                "has_evergreen": True,
                "evergreen_html": (
                    '<div style="max-width:600px">'
                    '<a href="https://www.interiordefine.com/?lid={{${cblid} | lid: \'j7wmgwh38ndf\'}}" target="_blank">'
                    '<img src="https://braze-images.com/appboy/communication/assets/image_assets/images/68efaf4f053179006334c3b0/original.png?1760538446"'
                    ' style="display:block;height:auto;border:0;width:100%" width="600"'
                    ' alt="15% Off Your Next Order. Use Code: WELCOME15-A6J8D3."'
                    ' title="15% Off Your Next Order. Use Code: WELCOME15-A6J8D3." height="auto">'
                    '</a></div>'
                ),
            },
        ],
    },
}

# Standardized variable names (always these 4 in the block header)
VAR_NAMES = ["sale_ea_start", "sale_reg_start", "sale_extension_start", "sale_end"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand_lid(length: int = 12) -> str:
    """Generate a random Braze link tracking ID (lowercase alphanumeric)."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


def _fetch_block(block_id: str, api_key: str, base_url: str) -> dict:
    """Fetch content block info from Braze."""
    url = f"{base_url}/content_blocks/info"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        params={"content_block_id": block_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_current_vars(content: str) -> dict[str, str]:
    """
    Parse current sale_* variable assignment values from block HTML.

    Returns dict like:
        {"sale_ea_start": "2026-05-07 07:00:00", "sale_reg_start": "...", ...}
    """
    result = {}
    pattern = re.compile(
        r'\{%-?\s*assign\s+(sale_\w+)\s*=\s*"([^"]+)"\s*\|\s*date:'
    )
    for m in pattern.finditer(content):
        result[m.group(1)] = m.group(2)
    return result


def _extract_else_block(content: str) -> str:
    """
    Extract the HTML content inside the {% else %} ... {% endif %} section.
    Returns empty string if no else block.
    """
    m = re.search(
        r'\{%-?\s*else\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}',
        content,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return ""


def _make_image_table(image_url: str, link: str, alt: str, lid: str) -> str:
    """Build the <table> HTML for one banner image, matching CZ's existing style."""
    # Liquid syntax: {{${cblid} | lid: 'xxx'}} — avoid f-string escaping by concatenation
    lid_tag = "{{${cblid} | lid: '" + lid + "'}}"
    base_link = link.rstrip("/")
    sep = "&" if "?" in base_link else "?"
    href = f"{base_link}{sep}lid={lid_tag}"
    return f"""<table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;">
  <tr>
    <td align="center" style="width: 100%">
      <a target="_blank" rel="noopener noreferrer"
         href="{href}">
        <img
          alt="{alt}"
          width="600"
          style="display:block;width:100%;max-width:100%;font-size:20px;font-family:Arial,'sans-serif';color:#383633;background-color:#FFFFFF;"
          border="0"
          src="{image_url}" />
      </a>
    </td>
  </tr>
</table>"""


# DnD outer shell — preserved from ID blocks (nl-container → row → row-content → column)
_DND_OPEN = (
    '<table class="nl-container" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"'
    ' style="mso-table-lspace:0;mso-table-rspace:0;background-color:#fff"><tbody><tr><td>'
    '<table class="row row-1" align="center" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"'
    ' style="mso-table-lspace:0;mso-table-rspace:0"><tbody><tr><td>'
    '<table class="row-content stack" align="center" border="0" cellpadding="0" cellspacing="0" role="presentation"'
    ' style="mso-table-lspace:0;mso-table-rspace:0;color:#000;width:600px;margin:0 auto" width="600"><tbody><tr>'
    '<td class="column column-1" width="100%"'
    ' style="mso-table-lspace:0;mso-table-rspace:0;font-weight:400;text-align:left;vertical-align:top">\n'
)
_DND_HTML_BLOCK_OPEN = (
    '<table class="html_block block-1" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"'
    ' style="mso-table-lspace:0;mso-table-rspace:0"><tr><td class="pad">'
    '<div style="font-family:\'Open Sans\',Arial,Sans-serif;text-align:center" align="center">'
)
_DND_HTML_BLOCK_CLOSE = '</div></td></tr></table>\n'
_DND_CLOSE = (
    '</td></tr></tbody></table></td></tr></tbody></table></td></tr></tbody></table>\n<!-- End -->'
)


def _make_image_div(image_url: str, link: str, alt: str, lid: str) -> str:
    """Build the image div for inside a DnD html_block, matching ID's image_block style."""
    lid_tag = "{{${cblid} | lid: '" + lid + "'}}"
    sep = "&" if "?" in link else "?"
    href = f"{link.rstrip('/')}{sep}lid={lid_tag}"
    return (
        f'<div style="max-width:600px">'
        f'<a href="{href}" target="_blank">'
        f'<img src="{image_url}" style="display:block;height:auto;border:0;width:100%"'
        f' width="600" alt="{alt}" title="{alt}" height="auto">'
        f'</a></div>'
    )


# ---------------------------------------------------------------------------
# Multi-sale key generation and section management
# ---------------------------------------------------------------------------

_SALE_SECTION_MARKER = "SALE_SECTION:"


def _generate_sale_key(task_name: str) -> str:
    """
    Derive a short sale key from an Asana task name.
    Strips brand prefix like [Burrow], [The Citizenry], etc.
    Takes first letter of text words and leading digits of number tokens.

    Examples:
        "[Burrow] Summer Ready Flash Sale"  → "srfs"
        "[The Citizenry] July 4th Sale"     → "j4s"
        "[Interior Define] Memorial Day Sale" → "mds"
        "Black Friday Event"                → "bfe"
    """
    # Strip brand prefix
    name = re.sub(r'^\[.*?\]\s*', '', task_name).strip()
    parts = []
    for token in name.split():
        # Leading digits (e.g. "4th" → "4", "1st" → "1")
        leading = re.match(r'^(\d+)', token)
        if leading:
            parts.append(leading.group(1))
        elif re.match(r'^[a-zA-Z]', token):
            parts.append(token[0].lower())
    key = ''.join(parts)
    return key[:8] if key else "sale"


def _parse_sale_sections(content: str) -> list:
    """Parse SALE_SECTION JSON blobs from block content. Returns list of section dicts."""
    pattern = re.compile(
        r'\{%-?\s*comment\s*-?%\}' + re.escape(_SALE_SECTION_MARKER) + r'(\{.*?\})' + r'\{%-?\s*endcomment\s*-?%\}',
        re.DOTALL,
    )
    sections = []
    for m in pattern.finditer(content):
        try:
            sections.append(json.loads(m.group(1)))
        except (json.JSONDecodeError, ValueError):
            pass
    return sections


def _section_comment(section: dict) -> str:
    """Build the hidden SALE_SECTION comment line for a section."""
    return "{%- comment -%}" + _SALE_SECTION_MARKER + json.dumps(section, separators=(',', ':')) + "{%- endcomment -%}"


def _sale_branches(sec: dict, image_fn) -> list:
    """Return list of (condition_str, image_html) for each phase of a sale."""
    key = sec["key"]
    ea    = sec.get("ea_start")
    reg   = sec["reg_start"]
    ext   = sec.get("ext_start")
    end   = sec["end"]
    has_ea  = ea  and ea  != reg
    has_ext = ext and ext != end
    branches = []

    if has_ea:
        cond = f"now >= {key}_ea_start and now < {key}_reg_start"
        img  = image_fn(sec["ea_image"], sec["ea_link"], sec["ea_alt"], _rand_lid()) if sec.get("ea_image") else ""
        branches.append((cond, img))

    reg_end = f"{key}_ext_start" if has_ext else f"{key}_end"
    cond = f"now >= {key}_reg_start and now < {reg_end}"
    img  = image_fn(sec["reg_image"], sec["reg_link"], sec["reg_alt"], _rand_lid()) if sec.get("reg_image") else ""
    branches.append((cond, img))

    if has_ext:
        cond = f"now >= {key}_ext_start and now < {key}_end"
        img  = image_fn(sec["ext_image"], sec["ext_link"], sec["ext_alt"], _rand_lid()) if sec.get("ext_image") else ""
        branches.append((cond, img))

    return branches


def _rebuild_from_sections(
    sections: list,
    has_evergreen: bool,
    evergreen_html: str,
    structure: str,
) -> str:
    """
    Rebuild the full content block Liquid from a list of sale sections.
    Sections are sorted chronologically by reg_start.
    Each section dict: {key, name, reg_start, end, [ea_start], [ext_start],
                        [ea/reg/ext]_image/link/alt}
    """
    image_fn = _make_image_div if structure == "dnd" else _make_image_table
    sections = sorted(sections, key=lambda s: s.get("reg_start", ""))

    lines = []

    # Hidden metadata (machine-parseable on next update)
    for sec in sections:
        lines.append(_section_comment(sec))
    lines.append("")

    # Human-readable variable assignments
    for sec in sections:
        key  = sec["key"]
        name = sec.get("name", key)
        ea   = sec.get("ea_start")
        ext  = sec.get("ext_start")
        has_ea  = ea  and ea  != sec["reg_start"]
        has_ext = ext and ext != sec["end"]
        lines.append(f"{{%- comment -%}}{name} ({key}){{%- endcomment -%}}")
        if has_ea:
            lines.append(f'{{% assign {key}_ea_start        = "{ea}" | date: "%s" %}}')
        lines.append(    f'{{% assign {key}_reg_start       = "{sec["reg_start"]}" | date: "%s" %}}')
        if has_ext:
            lines.append(f'{{% assign {key}_ext_start       = "{ext}" | date: "%s" %}}')
        lines.append(    f'{{% assign {key}_end             = "{sec["end"]}" | date: "%s" %}}')
    lines.append('{%- assign now = \'now\' | date: "%s" -%}')
    lines.append("")

    # Conditional tree (all phases across all sales, in chronological order)
    all_branches = []
    for sec in sections:
        all_branches.extend(_sale_branches(sec, image_fn))

    for i, (cond, img) in enumerate(all_branches):
        tag = "{% if" if i == 0 else "{% elsif"
        lines.append(f"{tag} {cond} %}}")
        if img:
            lines.append(img)
        else:
            lines.append("{%- comment -%}no banner for this phase{%- endcomment -%}")

    if has_evergreen and evergreen_html:
        lines.append("{% else %}")
        lines.append(evergreen_html)
    lines.append("{% endif %}")

    liquid = "\n".join(lines)

    if structure == "dnd":
        return _DND_OPEN + _DND_HTML_BLOCK_OPEN + liquid + _DND_HTML_BLOCK_CLOSE + _DND_CLOSE
    return liquid


def _extract_dnd_evergreen(content: str) -> str:
    """
    Extract the evergreen image div from the last image_block in the block HTML.
    Used for ID's welcome_promo to preserve the 15% off fallback.
    Returns the inner <div style="max-width:600px">...</div> HTML.
    """
    # Find all image_block tables, take the last one (the evergreen in welcome_promo)
    image_blocks = re.findall(
        r'<table class="image_block[^"]*"[^>]*>.*?</table>',
        content, re.DOTALL
    )
    if not image_blocks:
        return ""
    last = image_blocks[-1]
    # Extract the inner div (max-width:600px container with a/img)
    m = re.search(r'(<div[^>]*max-width:600px[^>]*>.*?</div>)', last, re.DOTALL)
    return m.group(1) if m else ""


def _build_liquid_body(
    *,
    ea_start: str,
    reg_start: str,
    ext_start: str,
    sale_end: str,
    ea_image: str | None,
    ea_link: str | None,
    ea_alt: str | None,
    reg_image: str,
    reg_link: str,
    reg_alt: str,
    ext_image: str | None,
    ext_link: str | None,
    ext_alt: str | None,
    evergreen_html: str,
    has_evergreen: bool,
    image_fn,  # callable(url, link, alt, lid) → HTML string
) -> str:
    """Build the Liquid conditional body (variables + if/elsif/else/endif)."""
    lines = []
    lines.append(f'{{% assign sale_ea_start        = "{ea_start}" | date: "%s" %}}')
    lines.append(f'{{% assign sale_reg_start       = "{reg_start}" | date: "%s" %}}')
    lines.append(f'{{% assign sale_extension_start = "{ext_start}" | date: "%s" %}}')
    lines.append(f'{{% assign sale_end             = "{sale_end}" | date: "%s" %}}')
    lines.append('{%- assign now = \'now\' | date: "%s" -%}')
    lines.append("")
    lines.append("{% if now >= sale_ea_start and now < sale_reg_start %}")
    if ea_image:
        lines.append(image_fn(ea_image, ea_link, ea_alt, _rand_lid()))
    else:
        lines.append("{%- comment -%}no EA banner for this sale{%- endcomment -%}")
    lines.append("{% elsif now >= sale_reg_start and now <= sale_extension_start %}")
    lines.append(image_fn(reg_image, reg_link, reg_alt, _rand_lid()))
    lines.append("{% elsif now >= sale_extension_start and now <= sale_end %}")
    if ext_image:
        lines.append(image_fn(ext_image, ext_link, ext_alt, _rand_lid()))
    else:
        lines.append("{%- comment -%}no extension banner for this sale{%- endcomment -%}")
    if has_evergreen and evergreen_html:
        lines.append("{% else %}")
        lines.append(evergreen_html)
    lines.append("{% endif %}")
    return "\n".join(lines)


def _build_new_content(
    *,
    ea_start: str,
    reg_start: str,
    ext_start: str,
    sale_end: str,
    ea_image: str | None,
    ea_link: str | None,
    ea_alt: str | None,
    reg_image: str,
    reg_link: str,
    reg_alt: str,
    ext_image: str | None,
    ext_link: str | None,
    ext_alt: str | None,
    evergreen_html: str,
    has_evergreen: bool,
    structure: str,  # "plain" (CZ) or "dnd" (ID)
) -> str:
    """Build the full new content block HTML."""
    kwargs = dict(
        ea_start=ea_start, reg_start=reg_start, ext_start=ext_start, sale_end=sale_end,
        ea_image=ea_image, ea_link=ea_link, ea_alt=ea_alt,
        reg_image=reg_image, reg_link=reg_link, reg_alt=reg_alt,
        ext_image=ext_image, ext_link=ext_link, ext_alt=ext_alt,
        evergreen_html=evergreen_html, has_evergreen=has_evergreen,
    )

    if structure == "plain":
        # CZ: pure Liquid+HTML, no wrapper
        return _build_liquid_body(image_fn=_make_image_table, **kwargs)

    else:  # "dnd"
        # ID: Liquid+images go inside a single html_block within the DnD shell
        liquid = _build_liquid_body(image_fn=_make_image_div, **kwargs)
        return _DND_OPEN + _DND_HTML_BLOCK_OPEN + liquid + _DND_HTML_BLOCK_CLOSE + _DND_CLOSE


# ---------------------------------------------------------------------------
# Main update logic
# ---------------------------------------------------------------------------

def update_blocks(
    brand: str,
    sale_name: str,                    # Asana task name → used to derive/confirm sale key
    sale_key: str | None,              # explicit override; auto-derived from sale_name if None
    ea_start: str | None,
    reg_start: str,
    ext_start: str | None,
    sale_end: str,
    ea_image: str | None,
    ea_link: str | None,
    ea_alt: str | None,
    reg_image: str,
    reg_link: str,
    reg_alt: str,
    ext_image: str | None,
    ext_link: str | None,
    ext_alt: str | None,
    dry_run: bool,
    interactive: bool = False,
    block_filter: str | None = None,
    diagnose: bool = False,
) -> bool:
    brand = normalize_brand(brand)
    if brand not in BRAND_BLOCKS:
        print(f"ERROR: brand '{brand}' not yet supported. Supported: {list(BRAND_BLOCKS)}")
        return False

    # Derive sale key from task name if not provided
    key = sale_key or _generate_sale_key(sale_name)
    print(f"Sale key: {key!r}  (from {sale_name!r})")

    brand_cfg   = BRAND_BLOCKS[brand]
    structure   = brand_cfg["structure"]
    api_key_env = brand_cfg["api_key_env"]

    import os
    api_key  = os.environ.get(api_key_env)
    if not api_key:
        print(f"ERROR: {api_key_env} not set in .env")
        return False
    init_config(brand_cfg.get("base_brand", brand))
    base_url = get_base_url()

    # Build this sale's section dict
    new_section = {
        "key":       key,
        "name":      re.sub(r'^\[.*?\]\s*', '', sale_name).strip(),
        "reg_start": reg_start,
        "end":       sale_end,
    }
    if ea_start and ea_start != reg_start:
        new_section["ea_start"] = ea_start
    if ext_start and ext_start != sale_end:
        new_section["ext_start"] = ext_start
    if ea_image:
        new_section.update(ea_image=ea_image, ea_link=ea_link, ea_alt=ea_alt)
    if reg_image:
        new_section.update(reg_image=reg_image, reg_link=reg_link, reg_alt=reg_alt)
    if ext_image:
        new_section.update(ext_image=ext_image, ext_link=ext_link, ext_alt=ext_alt)

    all_ok = True
    blocks_for_playwright: list = []

    for block_cfg in brand_cfg["blocks"]:
        if block_filter and block_cfg["name"] != block_filter:
            continue
        block_name = block_cfg["name"]
        block_id   = block_cfg["id"]
        has_ev     = block_cfg["has_evergreen"]

        print(f"\n{'='*60}")
        print(f"Block: {block_name}  ({block_id})")

        # Fetch current content
        try:
            info = _fetch_block(block_id, api_key, base_url)
        except Exception as e:
            print(f"  ERROR fetching block: {e}")
            all_ok = False
            continue

        current_content = info.get("content", "")
        print(f"  Last edited: {info.get('last_edited', '?')}")

        # Parse existing sale sections from hidden comment markers
        existing = _parse_sale_sections(current_content)
        existing_keys = [s["key"] for s in existing]

        if key in existing_keys:
            # Replace the existing section for this sale key
            sections = [new_section if s["key"] == key else s for s in existing]
            action = f"updated section '{key}'"
        else:
            # New sale — append
            sections = existing + [new_section]
            action = f"added new section '{key}'"

        print(f"  Sections: {existing_keys} → {action}")
        print(f"  Active sales after update: {[s['key'] for s in sections]}")

        # Extract evergreen
        if has_ev:
            if block_cfg.get("evergreen_html"):
                evergreen_html = block_cfg["evergreen_html"]
            elif structure == "dnd":
                evergreen_html = _extract_dnd_evergreen(current_content)
            else:
                evergreen_html = _extract_else_block(current_content)
        else:
            evergreen_html = ""

        # Build new content from all sections
        new_content = _rebuild_from_sections(sections, has_ev, evergreen_html, structure)

        if structure == "dnd":
            # Extract just the liquid body for Playwright injection
            liquid = new_content  # _rebuild_from_sections returns full DnD HTML for dnd
            # For DnD, the liquid body is embedded in the DnD shell — extract the inner part
            inner_m = re.search(
                re.escape(_DND_HTML_BLOCK_OPEN) + r'(.*?)' + re.escape(_DND_HTML_BLOCK_CLOSE),
                new_content, re.DOTALL
            )
            liquid_body = inner_m.group(1) if inner_m else new_content
            print(f"  Liquid body built ({len(liquid_body)} chars); queued for Playwright update")
            if dry_run:
                print(f"\n  [DRY RUN] Liquid for {block_name}:\n")
                print("  " + "\n  ".join(liquid_body.splitlines()))
            blocks_for_playwright.append((block_cfg, liquid_body))
        else:
            if dry_run:
                print(f"\n  [DRY RUN] New content for {block_name}:\n")
                print("  " + "\n  ".join(new_content.splitlines()))
                print(f"\n  [DRY RUN] Evergreen {'preserved' if has_ev and evergreen_html else 'N/A'}.")
            else:
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                resp = requests.post(
                    f"{base_url}/content_blocks/update",
                    headers=headers,
                    json={"content_block_id": block_id, "name": block_name,
                          "content": new_content, "content_type": "html", "state": "active"},
                    timeout=30,
                )
                if resp.status_code not in (200, 201, 202):
                    print(f"  ERROR updating {block_name}: {resp.status_code} {resp.text}")
                    all_ok = False
                else:
                    result = resp.json()
                    if "errors" in result:
                        print(f"  ERROR: {result['errors']}")
                        all_ok = False
                    else:
                        print(f"  ✓ Updated {block_name}")

    # DnD blocks: run Playwright in one browser session for all blocks
    if blocks_for_playwright and not dry_run:
        print(f"\nLaunching Playwright to update {len(blocks_for_playwright)} DnD block(s){'  [interactive]' if interactive else ''}{'  [diagnose]' if diagnose else ''}...")
        ok = asyncio.run(_run_playwright_updates(brand_cfg, brand, blocks_for_playwright, dry_run=False, interactive=interactive, diagnose=diagnose))
        if not ok:
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Playwright path — DnD content blocks (Braze API blocks DnD updates)
# ---------------------------------------------------------------------------

async def _fill_monaco(page, html_body: str) -> bool:
    """Fill an open Monaco editor with html_body. Returns True on success."""
    html_json = json.dumps(html_body)
    monaco = page.locator(".monaco-editor")
    if await monaco.count() == 0:
        return False
    # Try Monaco JS API first
    result = await page.evaluate(f"""(() => {{
        const content = {html_json};
        try {{
            const editors = window.monaco?.editor?.getEditors?.();
            if (editors?.length) {{ editors[0].setValue(content); return {{ok:true,m:'getEditors'}}; }}
        }} catch(e) {{}}
        try {{
            const models = window.monaco?.editor?.getModels?.();
            if (models?.length) {{ models[0].setValue(content); return {{ok:true,m:'getModels'}}; }}
        }} catch(e) {{}}
        return {{ok:false}};
    }})()""")
    if result.get("ok"):
        logger.info(f"Monaco filled via JS API ({result['m']})")
        return True
    # Clipboard paste fallback
    await page.evaluate(f"navigator.clipboard.writeText({html_json})")
    await monaco.first.click()
    await page.wait_for_timeout(200)
    await page.keyboard.press("Meta+a")
    await page.wait_for_timeout(100)
    await page.keyboard.press("Meta+v")
    await page.wait_for_timeout(500)
    logger.info("Monaco filled via clipboard paste")
    return True


async def _playwright_update_dnd_block(
    page,
    edit_url: str,
    liquid_body: str,
    block_name: str,
    dry_run: bool,
    interactive: bool = False,
    diagnose: bool = False,
) -> bool:
    """Update a single DnD content block via the Braze content block DnD editor."""
    if edit_url:
        logger.info(f"Navigating to {block_name}: {edit_url}")
        await page.goto(edit_url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2000)
    else:
        # No direct URL — navigate to content blocks list and find the block by name
        workspace_id = "6666726b459b5e0059d7d687"
        list_url = f"https://dashboard-07.braze.com/engagement/templates_and_media/content_blocks/{workspace_id}"
        logger.info(f"Navigating to content blocks list to find {block_name}")
        await page.goto(list_url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2000)
        block_link = page.get_by_role("link", name=block_name).or_(
            page.locator(f"text={block_name}").first
        )
        try:
            await block_link.wait_for(state="visible", timeout=10000)
            await block_link.click()
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.error(f"Could not find block '{block_name}' in list: {e}")
            await page.screenshot(path=str(Path(__file__).parent / f"debug_{block_name}_not_found.png"))
            return False

    if dry_run:
        print(f"\n  [DRY RUN] Would update {block_name} at:\n  {edit_url}")
        print(f"\n  [DRY RUN] Content to inject (first 300 chars):\n  {liquid_body[:300]}...")
        return True

    # Click "Edit Content Block body" to enter the DnD editor
    try:
        edit_btn = page.get_by_role("button", name="Edit Content Block body")
        await edit_btn.wait_for(state="visible", timeout=10000)
        await edit_btn.click()
        logger.info("Clicked 'Edit Content Block body'")
    except Exception as e:
        dbg = Path(__file__).parent / f"debug_{block_name}_no_edit_btn.png"
        await page.screenshot(path=str(dbg))
        logger.error(f"'Edit Content Block body' not found — {dbg}: {e}")
        return False

    # Wait for DnD editor to load — "Edit width" button appears once the canvas is ready
    try:
        await page.wait_for_selector("text=Edit width", timeout=15000)
        logger.info("DnD editor loaded")
    except Exception:
        dbg = Path(__file__).parent / f"debug_{block_name}_no_editor.png"
        await page.screenshot(path=str(dbg))
        logger.error(f"DnD editor did not load — {dbg}")
        return False

    await page.wait_for_timeout(2000)
    await page.bring_to_front()

    if interactive:
        # Step 1: hover over the html_block → reveals inline toolbar with "HTML" button
        logger.info("Hovering over html_block at (570, 190) to reveal toolbar...")
        await page.mouse.move(570, 190)
        await asyncio.sleep(0.8)
        logger.info("Clicking 'HTML' toolbar button at (770, 246)...")
        await page.mouse.click(770, 246)
        await asyncio.sleep(2.0)   # wait for HTML PROPERTIES panel to appear

        # Step 2: inject via CodeMirror v6 dispatch in the BEE frame (app.getbee.io).
        # The BEE editor uses CM6 — inject content directly without EXPAND.
        bee = next((f for f in page.frames if "getbee.io" in f.url), None)
        expand_clicked = True  # not using EXPAND — CM6 dispatch is more direct

        # Screenshot for diagnose / debugging
        dbg_pre = Path(__file__).parent / f"debug_{block_name}_pre_paste.png"
        await page.screenshot(path=str(dbg_pre))
        logger.info(f"Pre-paste screenshot: {dbg_pre}")

        if diagnose:
            print(f"\n  [DIAGNOSE] Screenshot: {dbg_pre}")
            print(f"  [DIAGNOSE] bee_frame found: {bee is not None}")
            if bee:
                cm_count = await bee.locator(".cm-editor").count()
                print(f"  [DIAGNOSE] .cm-editor elements in BEE frame: {cm_count}")
            print(f"  [DIAGNOSE] Stopping — no paste made.")
            return True

        # Step 3: inject via CodeMirror v6 dispatch API in the BEE frame
        filled = False
        if bee:
            # Try Playwright's native fill() on the cm-content contenteditable first
            try:
                cm_loc = bee.locator(".cm-content").first
                await cm_loc.click()
                await asyncio.sleep(0.3)
                await cm_loc.fill(liquid_body)
                await asyncio.sleep(0.5)
                result = {"ok": True, "method": "locator.fill() on cm-content"}
                logger.info("Filled via locator.fill()")
            except Exception as fill_err:
                logger.warning(f"locator.fill() failed: {fill_err} — trying JS dispatch")
                result = None

            if not (result and result.get("ok")):
              result = await bee.evaluate("""(newContent) => {
                const cmEl = document.querySelector('.cm-editor');
                if (!cmEl) return {ok: false, reason: 'no .cm-editor'};

                // Method 1: CM6 EditorView via Symbol keys
                for (const sym of Object.getOwnPropertySymbols(cmEl)) {
                    const v = cmEl[sym];
                    if (v && typeof v.dispatch === 'function' && v.state && v.state.doc) {
                        v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: newContent}});
                        v.focus && v.focus();
                        return {ok: true, method: 'CM6 Symbol dispatch'};
                    }
                }

                // Method 2: CM6 via string keys
                for (const k of Object.keys(cmEl)) {
                    const v = cmEl[k];
                    if (v && typeof v.dispatch === 'function' && v.state && v.state.doc) {
                        v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: newContent}});
                        return {ok: true, method: 'CM6 key dispatch ' + k};
                    }
                }

                // Method 3: Walk parent elements looking for CM6 view
                let el = cmEl.parentElement;
                for (let i = 0; i < 10 && el; i++, el = el.parentElement) {
                    for (const sym of Object.getOwnPropertySymbols(el)) {
                        const v = el[sym];
                        if (v && typeof v.dispatch === 'function' && v.state) {
                            v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: newContent}});
                            return {ok: true, method: 'CM6 via parent Symbol'};
                        }
                    }
                }

                // Method 4: Select all + delete + insert via BeforeInput events
                const content = document.querySelector('.cm-content');
                if (content) {
                    content.focus();
                    // Select all text in CM6 via keyboard-like before-input
                    const selectEvt = new KeyboardEvent('keydown', {key: 'a', metaKey: true, ctrlKey: true, bubbles: true});
                    content.dispatchEvent(selectEvt);
                    const beforeInsert = new InputEvent('beforeinput', {
                        inputType: 'insertText', data: newContent,
                        bubbles: true, cancelable: true
                    });
                    const inserted = content.dispatchEvent(beforeInsert);
                    return {ok: true, method: 'beforeinput event (cancelable=' + beforeInsert.cancelable + ')'};
                }

                return {ok: false, reason: 'all methods exhausted'};
            }""", liquid_body)

            logger.info(f"CM6 injection result: {result}")
            if result.get("ok"):
                logger.info(f"Content injected via {result.get('method')}")
                filled = True
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"CM6 injection failed: {result}")

        if not filled:
            logger.warning("BEE frame CM6 injection failed — content not injected")
            await page.screenshot(path=str(Path(__file__).parent / f"debug_{block_name}_inject_failed.png"))
            return False

        await page.screenshot(path=str(Path(__file__).parent / f"debug_{block_name}_after_fill.png"))

        # Step 4: click Done (top bar of DnD editor)
        done_clicked = False
        for done_name in ["Done", "Save"]:
            try:
                btn = page.get_by_role("button", name=done_name)
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(2)
                    logger.info(f"Clicked '{done_name}'")
                    done_clicked = True
                    break
            except Exception:
                continue
        if not done_clicked:
            await page.mouse.click(1370, 20)
            await asyncio.sleep(2)

        # Step 5: Launch Content Block to publish
        try:
            launch_btn = page.get_by_role("button", name="Launch Content Block")
            await launch_btn.wait_for(state="visible", timeout=8000)
            await launch_btn.click()
            await asyncio.sleep(2)
            logger.info(f"Launched {block_name}")
        except Exception as e:
            logger.warning(f"Launch Content Block not found — may need manual launch: {e}")

        await page.screenshot(path=str(Path(__file__).parent / f"debug_{block_name}_after_save.png"))
        return True

    # Non-interactive: automated path not yet implemented for DnD
    logger.error(f"DnD update requires --interactive flag")
    return False


async def _run_playwright_updates(
    brand_cfg: dict,
    brand: str,
    blocks_with_content: list[tuple[dict, str]],  # [(block_cfg, liquid_body), ...]
    dry_run: bool,
    interactive: bool = False,
    diagnose: bool = False,
) -> bool:
    from playwright.async_api import async_playwright
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from login import login, save_session, create_context_with_session, BRAZE_DASHBOARD_URL

    workspace_id = brand_cfg["workspace_id"]
    dashboard = BRAZE_DASHBOARD_URL.rstrip("/")

    all_ok = True
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-save-password-bubble", "--disable-password-manager-reauthentication"],
        )
        context = await create_context_with_session(browser)
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        # 1440×900 keeps the BEE right panel (HTML PROPERTIES) on-screen on most laptops
        await page.set_viewport_size({"width": 1440, "height": 900})

        try:
            await login(page)
            await save_session(context)

            for block_cfg, liquid_body in blocks_with_content:
                url_id = block_cfg.get("edit_url_id")
                edit_url = (
                    f"{dashboard}/engagement/templates_and_media/content_blocks"
                    f"/{workspace_id}/edit/{url_id}"
                ) if url_id else None
                ok = await _playwright_update_dnd_block(
                    page, edit_url, liquid_body, block_cfg["name"], dry_run, interactive, diagnose
                )
                print(f"  {'✓' if ok else '✗'} {block_cfg['name']}")
                if not ok:
                    all_ok = False
        finally:
            await browser.close()

    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Update Braze sale banner content blocks (multi-sale aware)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # BW Summer Ready Flash Sale
  update_sale_banner.py --brand BUR \\
    --sale-name "[Burrow] Summer Ready Flash Sale" \\
    --reg-start "2026-06-05 05:00:00" --sale-end "2026-06-09 05:00:00" \\
    --reg-image "https://braze-images.com/.../original.jpg" \\
    --reg-link "https://burrow.com" --reg-alt "Summer Ready Flash Sale"

  # When July 4th Sale banner arrives later — block gets BOTH sales:
  update_sale_banner.py --brand BUR \\
    --sale-name "[Burrow] July 4th Sale" \\
    --reg-start "2026-07-01 05:00:00" --sale-end "2026-07-05 05:00:00" \\
    --reg-image "..." --reg-link "https://burrow.com" --reg-alt "July 4th Sale"
""")
    parser.add_argument("--brand",      required=True,  help="Brand code (CZ, BUR, ID, etc.)")
    # Sale identification — key is auto-derived from name, can be overridden
    parser.add_argument("--sale-name",  required=True,
                        help='Asana task name, used to derive sale key (e.g. "[Burrow] Summer Ready Flash Sale" → srfs)')
    parser.add_argument("--sale-key",   default=None,
                        help="Override auto-derived key (e.g. srfs). Use same key to update an existing sale's dates.")
    # Required sale dates + banner
    parser.add_argument("--reg-start",  required=True,  help='Reg sale start: "YYYY-MM-DD HH:MM:SS"')
    parser.add_argument("--sale-end",   required=True,  help='Sale end (exclusive): "YYYY-MM-DD HH:MM:SS"')
    parser.add_argument("--reg-image",  required=True,  help="Reg sale banner image URL (Braze CDN)")
    parser.add_argument("--reg-link",   required=True,  help="Reg sale banner click URL")
    parser.add_argument("--reg-alt",    required=True,  help="Reg sale banner alt text")
    # EA phase (optional)
    parser.add_argument("--ea-start",  default=None, help="EA start date (omit = no EA phase)")
    parser.add_argument("--ea-image",  default=None)
    parser.add_argument("--ea-link",   default=None)
    parser.add_argument("--ea-alt",    default=None)
    # Extension phase (optional)
    parser.add_argument("--ext-start",  default=None, help="Extension start date (omit = no extension phase)")
    parser.add_argument("--ext-image",  default=None)
    parser.add_argument("--ext-link",   default=None)
    parser.add_argument("--ext-alt",    default=None)
    # Other flags
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--interactive", action="store_true", help="Required for DnD brands (ID)")
    parser.add_argument("--block",      default=None, help="Only update one block by name")
    parser.add_argument("--diagnose",   action="store_true")
    args = parser.parse_args()

    if args.ea_start and not (args.ea_image and args.ea_link and args.ea_alt):
        parser.error("--ea-start requires --ea-image, --ea-link, and --ea-alt")
    if args.ext_start and not (args.ext_image and args.ext_link and args.ext_alt):
        parser.error("--ext-start requires --ext-image, --ext-link, and --ext-alt")

    ok = update_blocks(
        brand=args.brand,
        sale_name=args.sale_name,
        sale_key=args.sale_key,
        ea_start=args.ea_start,
        reg_start=args.reg_start,
        ext_start=args.ext_start,
        sale_end=args.sale_end,
        ea_image=args.ea_image,
        ea_link=args.ea_link,
        ea_alt=args.ea_alt,
        reg_image=args.reg_image,
        reg_link=args.reg_link,
        reg_alt=args.reg_alt,
        ext_image=args.ext_image,
        ext_link=args.ext_link,
        ext_alt=args.ext_alt,
        dry_run=args.dry_run,
        interactive=args.interactive,
        block_filter=args.block,
        diagnose=args.diagnose,
    )

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
