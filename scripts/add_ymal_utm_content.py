#!/usr/bin/env python3
"""
Add utm_content parameters to YMAL recs content block product links.

Each recs_* block uses Liquid arrays:
    _ur = "url1|url2|..." | split: "|"   (product URLs, 1 per pool product)
    _k0 .. _k5                            (index vars — resolved per rotation)
    href="{{ _ur[_k0] }}"                 (6 slots per rotation)

This script:
  1. Parses _ur to build a parallel _sl (slug) array
  2. Inserts {% assign _sl = "..." | split: "|" %} after _ur
  3. Rewrites each href="{{ _ur[_kN] }}" to
         href="{{ _ur[_kN] }}&utm_content=ymal_{{ _sl[_kN] }}_sN"

Result: utm_content resolves at send time to e.g. "ymal_graham-bed_s1",
queryable via PROD.ID_WAREHOUSE.MAPPED_ACTIONS.UTM_CONTENT.

Usage:
    uv run python scripts/add_ymal_utm_content.py --dry-run
    uv run python scripts/add_ymal_utm_content.py
    uv run python scripts/add_ymal_utm_content.py --block recs_beds
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))
from import_braze import init_config, braze_request  # noqa: E402

RECS_BLOCK_NAMES = [
    "recs_sofas",
    "recs_sectionals",
    "recs_chairs",
    "recs_ottomans",
    "recs_rugs",
    "recs_dining_seating",
    "recs_dining_tables",
    "recs_beds",
    "recs_accent_tables",
    "recs_lighting",
    "recs_art",
    "recs_pillows",
    "recs_benches",
    "recs_nightstands",
]

TYPE_KEYWORDS = [
    "sofa", "sectional", "chair", "bed", "bench", "ottoman",
    "rug", "table", "chaise", "lounge", "cabinet", "dresser",
    "nightstand", "pendant", "sconce", "lamp", "pillow", "art",
    "shelf", "bookcase", "credenza", "console",
]

# Matches the {% assign _ur = "..." | split: "|" %} line
UR_ASSIGN_RE = re.compile(
    r'({%-?\s*assign _ur\s*=\s*")([^"]+)("\s*\|\s*split:[^%]+%})',
    re.DOTALL,
)

# Matches href="{{ _ur[_k0] }}" through href="{{ _ur[_k5] }}"
HREF_RE = re.compile(r'href="\{\{\s*_ur\[(_k\d)\]\s*\}\}"')


def make_slug(url: str) -> str:
    """Short product slug from a product URL path."""
    path = url.split("?")[0].rstrip("/").split("/")[-1]
    parts = path.split("-")
    name = parts[0]
    type_word = next((p for p in parts[1:] if p in TYPE_KEYWORDS), "")
    return f"{name}-{type_word}" if type_word else name


def add_utm_to_html(html: str) -> str:
    """
    Insert _sl slug array and add utm_content to each slot href.
    Returns unchanged html if the expected structure isn't found.
    """
    ur_match = UR_ASSIGN_RE.search(html)
    if not ur_match:
        return html

    # Skip if already updated
    if "_sl" in html and "utm_content=ymal_" in html:
        return html

    # Build slug array from _ur URLs
    urls = ur_match.group(2).split("|")
    slugs = [make_slug(u.strip()) for u in urls]
    sl_value = "|".join(slugs)

    # Insert {% assign _sl = "..." | split: "|" %} on the line after _ur
    ur_end = ur_match.end()
    insert_pos = html.find("\n", ur_end)
    if insert_pos == -1:
        insert_pos = ur_end
    sl_line = f'\n{{% assign _sl = "{sl_value}" | split: "|" %}}'
    html = html[:insert_pos] + sl_line + html[insert_pos:]

    # Rewrite each href="{{ _ur[_kN] }}" to include utm_content
    def rewrite_href(m):
        kvar = m.group(1)              # e.g. "_k0"
        slot_num = int(kvar[2]) + 1    # _k0 -> s1, _k1 -> s2 ...
        return (
            f'href="{{{{ _ur[{kvar}] }}}}'
            f'&utm_content=ymal_{{{{ _sl[{kvar}] }}}}_s{slot_num}"'
        )

    html = HREF_RE.sub(rewrite_href, html)
    return html


def list_recs_blocks(name_filter: str | None = None) -> list[dict]:
    data = braze_request("content_blocks/list", {"limit": 1000})
    if not data:
        print("ERROR: content_blocks/list returned None — check API key permissions.")
        sys.exit(1)
    blocks = data.get("content_blocks", [])
    target = [name_filter] if name_filter else RECS_BLOCK_NAMES
    matched = [b for b in blocks if b.get("name") in target]
    missing = set(target) - {b["name"] for b in matched}
    if missing:
        print(f"WARNING: not found in Braze: {sorted(missing)}")
    return matched


def get_block_html(block_id: str) -> dict:
    return braze_request(
        "content_blocks/info",
        {"content_block_id": block_id, "include_inclusion_data": "false"},
    ) or {}


def update_block(block_id: str, name: str, html: str) -> bool:
    result = braze_request(
        "content_blocks/update",
        method="POST",
        json_data={"content_block_id": block_id, "name": name, "content": html, "state": "active"},
    )
    return bool(result and result.get("content_block_id"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print changes without updating Braze")
    parser.add_argument("--block", help="Only update this block name (e.g. recs_beds)")
    args = parser.parse_args()

    init_config("ID")
    cb_key = os.environ.get("BRAZE_CONTENT_BLOCKS_API_KEY_ID")
    if cb_key:
        import import_braze as _ib
        _ib.CONFIG["api_key"] = cb_key

    blocks = list_recs_blocks(name_filter=args.block)
    if not blocks:
        print("No matching blocks found.")
        sys.exit(0)

    print(f"{'DRY RUN — ' if args.dry_run else ''}Processing {len(blocks)} block(s)...\n")
    ok = skipped = errors = 0

    for block in blocks:
        block_id = block["content_block_id"]
        name = block["name"]
        print(f"  {name}")

        info = get_block_html(block_id)
        original = info.get("content", "")
        if not original:
            print(f"    SKIP: empty content")
            skipped += 1
            continue

        updated = add_utm_to_html(original)

        if updated == original:
            print(f"    SKIP: already updated or unexpected structure")
            skipped += 1
            continue

        # Show sample utm_content values for this block
        sample = re.findall(r"utm_content=ymal_[^}\"]+", updated)[:6]
        for s in sample:
            print(f"    → {s}")

        if args.dry_run:
            ok += 1
            continue

        if update_block(block_id, name, updated):
            print(f"    ✓ updated")
            ok += 1
        else:
            print(f"    ✗ update failed")
            errors += 1

        time.sleep(0.2)

    print(f"\nDone: {ok} updated, {skipped} skipped, {errors} errors")
    if args.dry_run:
        print("(Dry run — no changes pushed to Braze)")


if __name__ == "__main__":
    main()
