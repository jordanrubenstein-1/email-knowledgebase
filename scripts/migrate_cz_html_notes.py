#!/usr/bin/env python3
"""
Migrate CZ Asana task html_notes from 2026-06-05 onwards to the new nested format.

Old formats produced by the old briefing system:
  1. Plain text: <body>    Field: value\n</body>
  2. All-in-ul:  <body><ul><li><strong>Field:</strong> value</li>...</ul></body>

New format (matching build_html_notes output):
  <body><strong>Field:</strong> value\n...\n
  <strong>Body Copy (X. Name):</strong><ul><li>header<ul><li>sub</li></ul></li></ul></body>

Changes applied:
  - Field labels use <strong> with \n separators (not inside <ul>)
  - Body copy slices use nested <ul><li> (sub-fields indented under slice header)
  - [IMAGE], [text-only], [brand asset] labels stripped from slice headers
  - [YMAL], [Text link farm], Kicker: X → final "Slice N — Kicker [content block...]" entry
  - "Slices to deliver: N" corrected for Template F (was 1, should be 6)
"""

import html as _html
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_PAT = os.environ.get("ASANA_ACCESS_TOKEN") or os.environ.get("ASANA_PAT")
ASANA_BASE = "https://app.asana.com/api/1.0"
CZ_FIGMA_FILE_KEY = "K043FA15z83zW2fhOkTH7J"

# Template F: correct image count is 6 (was generating 1 in old notes)
TEMPLATE_F_IMAGE_COUNT = 6

# Tasks to migrate (in date order). GID 1213983434646767 (F, 6/12) already updated.
TASK_GIDS = [
    "1213983391730926",  # 6/5  Color Edit: Sunwashed Isles    (E)
    "1213983416021461",  # 6/8  Back in Stock                   (K)
    "1213983391817474",  # 6/9  Style Guide: Entryway Styling   (D)
    "1214949468224390",  # 6/11 Summer Retreat Sale Launch       (H)
    "1213983389813075",  # 6/13 MTO Furniture                   (A)
    "1214949439537462",  # 6/15 Summer Retreat Sale Last Chance  (J)
    "1213983390190349",  # 6/16 Washable Rugs                   (I)
    "1213983390147043",  # 6/18 Swatch Push                     (J)
    "1214949485873378",  # 6/19 Fourth of July EA Launch         (H)
    "1214949379345263",  # 6/21 Fourth of July EA Last Chance    (J)
    "1214949587878446",  # 6/22 Fourth of July Event Launch      (H)
    "1213983390271753",  # 6/23 Back in Stock                   (K)
    "1213983390294886",  # 6/25 Archive Sale                    (F)
    "1213983416381627",  # 6/27 The Portugal Capsule             (J)
    "1213983390113299",  # 6/29 Celebrating Summer               (D)
    "1213983416161012",  # 7/3  Linen Bedding                   (M)
    "1213983392124795",  # 7/5  Pillow Pairings                  (D)
    "1214949697278451",  # 7/7  Fourth of July Event Last Day    (J)
    "1213983415818736",  # 7/9  Hinoki Mirrors                   (J)
]


# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def asana_get(task_gid: str, fields: str) -> Dict:
    url = f"{ASANA_BASE}/tasks/{task_gid}"
    r = requests.get(url, headers={"Authorization": f"Bearer {ASANA_PAT}"},
                     params={"opt_fields": fields})
    r.raise_for_status()
    return r.json()["data"]


def asana_put_html_notes(task_gid: str, html_notes: str) -> None:
    url = f"{ASANA_BASE}/tasks/{task_gid}"
    r = requests.put(url, headers={"Authorization": f"Bearer {ASANA_PAT}"},
                     json={"data": {"html_notes": html_notes}})
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Notes parsing
# ---------------------------------------------------------------------------

# Section header patterns — match after stripping 4-space indent
_SECTION_RE = re.compile(
    r"^(Creative Direction|LP|Figma|Products|SL/PH \(AI generated\)|Body Copy \([^)]+\)):\s*(.*)"
)
_BODY_COPY_RE = re.compile(r"^Body Copy \(([^)]+)\):\s*(.*)")
_SLICE_HDR_RE = re.compile(r"^Slice (\d+)\s*[—–-]\s*(.*)")
_SLICES_DELIVER_RE = re.compile(r"^Slices to deliver:\s*(\d+)")
_SALE_BANNER_RE = re.compile(r"^[Ss]ale\s*[Bb]anner\s*$")

# Kicker bracket lines: [YMAL], [Text link farm], etc.
_BRACKET_KICKER_RE = re.compile(r"^\[(.+)\]$")
# Old "Kicker: Label" format
_KICKER_COLON_RE = re.compile(r"^Kicker:\s*(.*)")

# Map display name → kicker_id for old "Kicker: Label" format (default/first variant)
_KICKER_DISPLAY_TO_ID: Dict[str, str] = {
    "swatches": "swatches",
    "back in stock": "back-in-stock-1",
    "fair trade guaranteed": "fair-trade-1",
    "archive sale": "archive-1",
    "ymal": None,          # YMAL uses ${product_recs}, no kicker_id variable
    "link farm": "text",   # default to text variant
}
# Old "Kicker modules:" + "* label"
_KICKER_MODULES_RE = re.compile(r"^Kicker modules:\s*$")
_KICKER_STAR_RE = re.compile(r"^\*\s*(.*)")

# Strip type-label suffixes from slice headers: [IMAGE], [text-only], [brand asset]
_TYPE_LABEL_RE = re.compile(r"\s*\[(IMAGE[^\]]*|text-only[^\]]*|brand asset[^\]]*)\]")


def _enrich_kicker_label(label: str) -> str:
    """Add (kicker_id: X) to a bare kicker display name from old 'Kicker: Label' format."""
    kid = _KICKER_DISPLAY_TO_ID.get(label.lower())
    if kid is None:
        return label  # YMAL or unknown — leave as-is
    if kid == "text":
        return f"{label} (link_farm_id: text)"
    return f"{label} (kicker_id: {kid})"


def _strip_4space(line: str) -> str:
    """Remove the 4-space indent that the old notes format uses."""
    if line.startswith("    "):
        return line[4:]
    return line.strip()


def _bracket_to_kicker_module(text: str) -> Optional[str]:
    """Convert a bracket-enclosed auto-module label to a kicker module string.

    [YMAL]                             → "YMAL"
    [Text link farm]                   → "Link farm (link_farm_id: text)"
    [Image link farm]                  → "Link farm (link_farm_id: image)"
    [Text link farm (or Image ...)]    → "Link farm (link_farm_id: text)"
    """
    inner = text.strip()
    if inner.upper() == "YMAL":
        return "YMAL"
    if re.match(r"(?i)text\s*link\s*farm", inner):
        return "Link farm (link_farm_id: text)"
    if re.match(r"(?i)image\s*link\s*farm", inner):
        return "Link farm (link_farm_id: image)"
    # Mixed / uncertain — take the first type mentioned
    if re.match(r"(?i)text\s*link\s*farm\s*\(or", inner):
        return "Link farm (link_farm_id: text)"
    # Generic fallback: preserve as-is
    return inner


def parse_notes(raw_notes: str) -> Dict[str, Any]:
    """Parse plain text task notes into structured sections.

    Returns dict with keys:
      creative_direction, lp, figma, sl_ph_lines, body_copy_label, body_copy_lines
    """
    lines = [_strip_4space(ln) for ln in raw_notes.split("\n")]

    result: Dict[str, Any] = {
        "creative_direction": "",
        "lp": "",
        "figma": "",
        "sl_ph_lines": [],
        "body_copy_label": "",
        "body_copy_lines": [],
    }

    current_section: Optional[str] = None
    current_content: List[str] = []

    def flush(section: Optional[str], content: List[str]):
        if section == "sl_ph":
            result["sl_ph_lines"] = [ln for ln in content if ln]
        elif section == "body_copy":
            result["body_copy_lines"] = [ln for ln in content if ln != ""]
        # products and other multi-line sections are dropped (not shown in html_notes)

    for line in lines:
        # Check for a known section header
        m_sec = _SECTION_RE.match(line)
        m_body = _BODY_COPY_RE.match(line)

        if m_body:
            flush(current_section, current_content)
            current_content = []
            label_raw = m_body.group(1).strip()
            extra = m_body.group(2).strip()  # text after the colon (e.g. "CURTAINS NOT APPLICABLE")
            result["body_copy_label"] = label_raw
            if extra:
                current_content.append(extra)  # preserve inline note
            current_section = "body_copy"

        elif m_sec:
            flush(current_section, current_content)
            current_content = []
            label = m_sec.group(1)
            rest = m_sec.group(2).strip()

            if label == "Creative Direction":
                result["creative_direction"] = rest
                current_section = None
            elif label == "LP":
                result["lp"] = rest
                current_section = None
            elif label == "Figma":
                result["figma"] = rest
                current_section = None
            elif label == "SL/PH (AI generated)":
                if rest:
                    current_content.append(rest)
                current_section = "sl_ph"
            elif label == "Products":
                current_section = "products"

        elif current_section and line:
            current_content.append(line)

    flush(current_section, current_content)
    return result


def extract_template_letter(figma_str: str) -> Optional[str]:
    """Extract template letter from 'F. Archive Sale — URL' → 'F'."""
    m = re.match(r"^([A-Z])\.\s+", figma_str.strip())
    if m:
        return m.group(1)
    return None


def parse_body_copy(body_copy_lines: List[str]) -> Dict[str, Any]:
    """Parse body copy lines into slices, sale banner flag, and kicker modules.

    Returns:
      {
        "slices_to_deliver": Optional[str],   # raw string from notes (may be wrong for F)
        "has_sale_banner": bool,
        "pre_slice_notes": [str],             # any non-slice, non-banner lines before first slice
        "slices": [(num, name, [sub_fields])],
        "kicker_modules": [str],
        "max_slice_num": int,
      }
    """
    result: Dict[str, Any] = {
        "slices_to_deliver": None,
        "has_sale_banner": False,
        "pre_slice_notes": [],
        "slices": [],
        "kicker_modules": [],
        "max_slice_num": 0,
    }

    current_slice: Optional[Tuple[int, str, List[str]]] = None  # (num, name, sub_fields)
    in_kicker_modules = False
    found_first_slice = False

    def flush_slice():
        if current_slice is not None:
            result["slices"].append(current_slice)

    for line in body_copy_lines:
        # "Slices to deliver: N"
        m_deliver = _SLICES_DELIVER_RE.match(line)
        if m_deliver:
            result["slices_to_deliver"] = m_deliver.group(1)
            in_kicker_modules = False
            continue

        # "Sale Banner" / "Sale banner"
        if _SALE_BANNER_RE.match(line):
            result["has_sale_banner"] = True
            in_kicker_modules = False
            continue

        # "Slice N — Name ..." header
        m_slice = _SLICE_HDR_RE.match(line)
        if m_slice:
            flush_slice()
            in_kicker_modules = False
            found_first_slice = True
            num = int(m_slice.group(1))
            name_raw = m_slice.group(2).strip()
            result["max_slice_num"] = max(result["max_slice_num"], num)
            current_slice = (num, name_raw, [])
            continue

        # Bracket auto-module lines: [YMAL], [Text link farm], etc.
        m_bracket = _BRACKET_KICKER_RE.match(line)
        if m_bracket:
            module = _bracket_to_kicker_module(m_bracket.group(1))
            if module:
                result["kicker_modules"].append(module)
            flush_slice()
            current_slice = None
            in_kicker_modules = False
            continue

        # "Kicker: Label" format — enrich with kicker_id if known
        m_kicker_colon = _KICKER_COLON_RE.match(line)
        if m_kicker_colon:
            label = m_kicker_colon.group(1).strip()
            if label:
                result["kicker_modules"].append(_enrich_kicker_label(label))
            flush_slice()
            current_slice = None
            in_kicker_modules = False
            continue

        # "Kicker modules:" header
        if _KICKER_MODULES_RE.match(line):
            flush_slice()
            current_slice = None
            in_kicker_modules = True
            continue

        # "* module label" under "Kicker modules:"
        m_star = _KICKER_STAR_RE.match(line)
        if m_star and in_kicker_modules:
            result["kicker_modules"].append(m_star.group(1).strip())
            continue

        # Sub-field of current slice
        if current_slice is not None:
            current_slice[2].append(line)
            continue

        # Lines before the first slice (inline notes on "Body Copy (X):" line)
        if not found_first_slice:
            result["pre_slice_notes"].append(line)

    flush_slice()
    return result


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    return _html.escape(str(text) if text else "")


def href(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    return f'<a href="{url}">{url}</a>'


def nested_ul(items: List[str]) -> str:
    inner = "".join(f"<li>{esc(i)}</li>" for i in items if i)
    return f"<ul>{inner}</ul>"


def clean_slice_header(raw: str) -> str:
    """Strip [IMAGE], [text-only], [brand asset] from slice header name.

    Preserves [content block ...] since it carries meaning.
    """
    return _TYPE_LABEL_RE.sub("", raw).strip()


def render_body_copy_nested(
    slices_to_deliver: Optional[str],
    has_sale_banner: bool,
    pre_slice_notes: List[str],
    slices: List[Tuple[int, str, List[str]]],
    kicker_modules: List[str],
    max_slice_num: int,
    template_letter: str,
) -> str:
    """Render the body copy section as a nested <ul>."""
    items: List[str] = []

    # Pre-slice notes (e.g. "CURTAINS NOT APPLICABLE")
    for note in pre_slice_notes:
        items.append(f"<li>{esc(note)}</li>")

    # "Slices to deliver: N"
    if slices_to_deliver is not None:
        # Template F was generated with wrong count (1) — correct it
        count = TEMPLATE_F_IMAGE_COUNT if template_letter == "F" else slices_to_deliver
        items.append(f"<li>{esc(f'Slices to deliver: {count}')}</li>")

    # Sale Banner (plain bullet, not a slice header)
    if has_sale_banner:
        items.append(f"<li>{esc('Sale Banner')}</li>")

    # Slices with nested sub-fields
    for (num, name_raw, sub_fields) in slices:
        header = f"Slice {num} — {clean_slice_header(name_raw)}"
        if sub_fields:
            nested = "".join(f"<li>{esc(sf)}</li>" for sf in sub_fields if sf)
            items.append(f"<li>{esc(header)}<ul>{nested}</ul></li>")
        else:
            items.append(f"<li>{esc(header)}</li>")

    # Kicker as final numbered slice
    if kicker_modules:
        kicker_num = max_slice_num + 1
        kicker_header = f"Slice {kicker_num} — Kicker [content block - no slice needed]"
        nested = "".join(f"<li>{esc(m)}</li>" for m in kicker_modules if m)
        items.append(f"<li>{esc(kicker_header)}<ul>{nested}</ul></li>")

    return "<ul>" + "".join(items) + "</ul>"


def build_new_html_notes(parsed: Dict, body_parsed: Dict, template_letter: str) -> str:
    """Build the new html_notes string from parsed sections."""
    parts: List[str] = []

    # Creative Direction
    cd = parsed.get("creative_direction", "").strip()
    parts.append(f"<strong>Creative Direction:</strong> {esc(cd)}")

    # LP
    lp = parsed.get("lp", "").strip()
    parts.append(f"<strong>LP:</strong> {href(lp) if lp else ''}")

    # Figma — extract letter.name part + rebuild URL
    figma_raw = parsed.get("figma", "").strip()
    # Split on " — " to get "F. Archive Sale" and URL
    if " — " in figma_raw:
        figma_label, figma_url = figma_raw.split(" — ", 1)
    elif " – " in figma_raw:
        figma_label, figma_url = figma_raw.split(" – ", 1)
    else:
        figma_label = figma_raw
        figma_url = ""
    figma_part = f"{esc(figma_label.strip())} — {href(figma_url.strip())}" if figma_url else esc(figma_label.strip())
    parts.append(f"<strong>Figma:</strong> {figma_part}")

    # SL/PH — omit if every line is blank or only contains "SL:" / "PH:" with no value
    sl_ph_lines = parsed.get("sl_ph_lines", [])
    sl_ph_lines_content = [ln for ln in sl_ph_lines if re.sub(r"^(SL|PH):\s*", "", ln).strip()]
    if sl_ph_lines_content:
        sl_ph_lines_clean = [ln for ln in sl_ph_lines if ln.strip()]
        parts.append(f"<strong>SL/PH (AI generated):</strong>{nested_ul(sl_ph_lines_clean)}")

    # Body Copy
    label = parsed.get("body_copy_label", "")
    if label:
        body_html = render_body_copy_nested(
            slices_to_deliver=body_parsed.get("slices_to_deliver"),
            has_sale_banner=body_parsed.get("has_sale_banner", False),
            pre_slice_notes=body_parsed.get("pre_slice_notes", []),
            slices=body_parsed.get("slices", []),
            kicker_modules=body_parsed.get("kicker_modules", []),
            max_slice_num=body_parsed.get("max_slice_num", 0),
            template_letter=template_letter,
        )
        parts.append(f"<strong>Body Copy ({esc(label)}):</strong>{body_html}")

    return "<body>" + "\n".join(parts) + "</body>"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def migrate_task(task_gid: str, dry_run: bool = False) -> str:
    """Fetch, parse, rebuild, and PUT html_notes for one task.

    Returns a summary line for logging.
    """
    task = asana_get(task_gid, "name,notes")
    name = task.get("name", "?")
    raw_notes = task.get("notes", "") or ""

    if not raw_notes.strip():
        return f"  SKIP {name} — no notes"

    parsed = parse_notes(raw_notes)

    if not parsed.get("body_copy_label"):
        return f"  SKIP {name} — no body copy section found"

    template_letter = extract_template_letter(parsed.get("figma", ""))
    if not template_letter:
        return f"  SKIP {name} — could not extract template letter from Figma field"

    body_parsed = parse_body_copy(parsed["body_copy_lines"])
    new_html = build_new_html_notes(parsed, body_parsed, template_letter)

    if dry_run:
        print(f"\n{'='*70}")
        print(f"  TASK: {name} (GID: {task_gid})")
        print(f"  Template: {template_letter}")
        print(f"  has_sale_banner: {body_parsed['has_sale_banner']}")
        print(f"  kicker_modules: {body_parsed['kicker_modules']}")
        print(f"  max_slice_num: {body_parsed['max_slice_num']}")
        print(f"  NEW html_notes ({len(new_html)} chars):")
        print(new_html)
        return f"  DRY-RUN {name}"

    asana_put_html_notes(task_gid, new_html)
    return f"  DONE {name} → {len(new_html)} chars"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate CZ task html_notes to new nested format")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--gid", help="Migrate only this specific task GID")
    args = parser.parse_args()

    if not ASANA_PAT:
        print("ERROR: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    gids = [args.gid] if args.gid else TASK_GIDS
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"Migrating {len(gids)} CZ tasks ({mode})")

    for gid in gids:
        try:
            result = migrate_task(gid, dry_run=args.dry_run)
            print(result)
            if not args.dry_run:
                time.sleep(0.5)  # avoid rate limit
        except Exception as e:
            print(f"  ERROR {gid}: {e}")

    print(f"\nDone. {len(gids)} tasks processed.")


if __name__ == "__main__":
    main()
