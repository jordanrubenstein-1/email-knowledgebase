#!/usr/bin/env python3
"""
Incrementally sync Air asset boards into a local image library (JSON store +
markdown catalog), so briefers can grep for existing photography without
re-fetching everything from Air on every run.

How the incremental part works:
  - Air's /assets endpoint paginates newest-updatedAt-first (confirmed
    empirically 2026-07-15, not documented). Each board's JSON store records
    the newest updatedAt seen last run (the "watermark"). On the next run we
    page from the top and stop as soon as an asset's updatedAt <= the
    watermark — everything after that point was already captured.
  - This also picks up assets that were only re-tagged/edited (not newly
    created), since editing bumps updatedAt too.
  - It does NOT detect deletions or removals from a board — this is an
    additive sync. Re-run with --full periodically if that matters.

Categorization is a deterministic keyword ruleset (see CATEGORY_KEYWORDS
below) — intentionally simpler than the nuanced LLM judgment used for the
first hand-built pass of these docs on 2026-07-15, so that re-syncs are
consistent and don't require an LLM in the loop. Category counts may drift
slightly from the original docs as a result.

Usage:
    uv run python scripts/sync_air_image_library.py                 # incremental, all boards
    uv run python scripts/sync_air_image_library.py --board id-studios
    uv run python scripts/sync_air_image_library.py --full           # ignore watermark, refetch everything
    uv run python scripts/sync_air_image_library.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from utils.air_client import AirClient


REPO_ROOT = Path(__file__).parent.parent
BOARDS_CONFIG = REPO_ROOT / "data" / "air_image_library_boards.yaml"
STORE_DIR = REPO_ROOT / "data" / "air_image_library"
DOCS_DIR = REPO_ROOT / "docs" / "asset-library"

DO_NOT_USE_MARKERS = ("unedited", "do not use", "duplicate")

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "Living Room": {
        "living room", "sofa", "couch", "sectional", "coffee table",
        "loveseat", "fireplace", "accent chair", "armchair",
    },
    "Bedroom": {
        "bedroom", "bed", "headboard", "nightstand", "bedding", "duvet", "mattress",
    },
    "Dining/Kitchen": {
        "dining", "kitchen", "dining table", "dining chair", "counter",
        "cabinet", "island", "sink", "cookware",
    },
    "Outdoor": {"outdoor", "patio", "garden", "pool", "deck", "backyard"},
    "Bathroom": {"bathroom", "bath", "shower", "tub", "vanity", "towel"},
    "Office/Study": {"office", "desk", "study", "workspace"},
    "Kids": {"child", "children", "kid", "kids", "toddler", "baby", "nursery"},
    "Detail/Product Vignette": {
        "fabric", "swatch", "material", "texture", "upholstery",
        "detail", "cloth", "leather",
    },
    "Lifestyle-with-People": {
        "people", "man", "woman", "person", "smiling", "conversation",
        "family", "couple",
    },
    "Event/Social": {"event", "party", "gathering", "crowd", "social", "mingling"},
}


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def board_url(board_info: dict, board_id: str) -> str:
    """The raw REST API doesn't return a `url` field (that's synthesized by
    the MCP server) — replicate its observed pattern: /b/{slugified-title}-{id}.
    """
    title = board_info.get("title", "")
    return f"https://app.air.inc/b/{slugify(title)}-{board_id}"


def load_board_config() -> list[dict]:
    with open(BOARDS_CONFIG) as f:
        return yaml.safe_load(f)["boards"]


def load_store(slug: str) -> dict[str, dict]:
    path = STORE_DIR / f"{slug}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_store(slug: str, store: dict[str, dict]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / f"{slug}.json"
    with open(path, "w") as f:
        json.dump(store, f, indent=2, sort_keys=True)


def normalize_custom_fields(raw_fields: list[dict]) -> dict[str, str]:
    """Flatten Air's customFields array into {name: joined_value_string}."""
    out: dict[str, str] = {}
    for field in raw_fields or []:
        name = field.get("name")
        if not name:
            continue
        values = field.get("values") or []
        if values:
            out[name] = ", ".join(v.get("name", "") for v in values if v.get("name"))
        elif field.get("value"):
            out[name] = str(field["value"])
    return out


def normalize_asset(asset: dict) -> dict:
    cv = asset.get("coverVersion") or {}
    return {
        "id": asset["id"],
        "file_name": cv.get("fileName", ""),
        "ext": cv.get("ext", ""),
        "type": cv.get("type", ""),
        "smart_tags": sorted({t["name"] for t in cv.get("smartTags", []) if t.get("name")}),
        "tags": sorted({t["name"] for t in cv.get("tags", []) if t.get("name")}),
        "custom_fields": normalize_custom_fields(asset.get("customFields", [])),
        "preview_url": (cv.get("urls") or {}).get("preview", ""),
        "created_at": cv.get("createdAt", ""),
        "updated_at": cv.get("updatedAt", ""),
    }


def categorize(record: dict) -> list[str]:
    haystack = " ".join(record["smart_tags"] + record["tags"]).lower()
    cats = [cat for cat, kws in CATEGORY_KEYWORDS.items() if any(kw in haystack for kw in kws)]
    return cats or ["Uncategorized/Other"]


def is_flagged(record: dict) -> bool:
    field_text = " ".join(record["custom_fields"].values()).lower()
    tag_text = " ".join(record["tags"]).lower()
    combined = f"{field_text} {tag_text}"
    return any(marker in combined for marker in DO_NOT_USE_MARKERS)


def sync_board(client: AirClient, board_cfg: dict, full: bool, dry_run: bool) -> dict:
    slug = board_cfg["slug"]
    board_id = board_cfg["board_id"]
    store = load_store(slug)

    watermark = None
    if not full and store:
        watermark = max((r["updated_at"] for r in store.values() if r.get("updated_at")), default=None)

    new_count = 0
    updated_count = 0
    for raw_asset in client.iter_assets(board_id, stop_at_updated_at=watermark):
        record = normalize_asset(raw_asset)
        if record["id"] in store:
            updated_count += 1
        else:
            new_count += 1
        store[record["id"]] = record

    if not dry_run and (new_count or updated_count or full):
        save_store(slug, store)

    return {
        "slug": slug,
        "board_id": board_id,
        "total": len(store),
        "new": new_count,
        "updated": updated_count,
        "store": store,
    }


def render_markdown(board_cfg: dict, board_info: dict, store: dict[str, dict]) -> str:
    slug = board_cfg["slug"]
    title = board_cfg["title"]
    note = board_cfg.get("note", "")
    total = len(store)

    records = list(store.values())
    categorized = {aid: categorize(r) for aid, r in store.items()}
    flagged = {aid: is_flagged(r) for aid, r in store.items()}

    cat_counts: dict[str, int] = {}
    for cats in categorized.values():
        for c in cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    tag_counts: dict[str, int] = {}
    for r in records:
        for t in r["smart_tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    field_values: dict[str, dict[str, int]] = {}
    for r in records:
        for fname, fval in r["custom_fields"].items():
            field_values.setdefault(fname, {})
            field_values[fname][fval] = field_values[fname].get(fval, 0) + 1

    flagged_ids = [aid for aid, f in flagged.items() if f]

    lines = [
        f"# {title}",
        "",
        f"**Air Board URL:** {board_url(board_info, board_cfg['board_id'])}",
        "",
        f"**Board ID:** `{board_cfg['board_id']}`",
        "",
        f"**Total Assets:** {total}",
        "",
    ]
    if note:
        lines += [note, ""]

    lines += [
        "_Generated by `scripts/sync_air_image_library.py` — deterministic keyword categorization, "
        "not LLM-curated. Re-run the script to refresh incrementally._",
        "",
        "## Category Breakdown",
        "",
        "| Category | Count |",
        "|---|---|",
    ]
    for cat, count in sorted(cat_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {count} |")

    lines += ["", "## Tag Frequency (smartTags, count >= 2)", "", "| smartTag | Count |", "|---|---|"]
    for tag, count in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
        if count >= 2:
            lines.append(f"| {tag} | {count} |")

    lines += ["", "## Custom Field Notes", ""]
    for fname, vals in field_values.items():
        lines.append(f"**{fname}:**")
        lines.append("")
        lines.append("| Value | Count |")
        lines.append("|---|---|")
        for v, count in sorted(vals.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {v or '_(blank)_'} | {count} |")
        lines.append("")

    lines.append(f"**Flagged / Do-Not-Use assets:** {len(flagged_ids)}")
    if 0 < len(flagged_ids) <= 30:
        lines.append("")
        for aid in flagged_ids:
            lines.append(f"- `{store[aid]['file_name']}` (`{aid}`)")
    lines.append("")

    lines += [
        "## Full Asset Index",
        "",
        "| Asset ID | File Name | Type | Categories | Top smartTags | Flag |",
        "|---|---|---|---|---|---|",
    ]
    for aid, r in sorted(store.items(), key=lambda kv: kv[1]["file_name"]):
        cats = ", ".join(categorized[aid])
        tags = ", ".join(r["smart_tags"][:6])
        flag = "⚠️ DO NOT USE" if flagged[aid] else ""
        lines.append(f"| `{aid}` | {r['file_name']} | {r['type']} | {cats} | {tags} | {flag} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--board", help="Only sync this board slug (default: all configured boards)")
    parser.add_argument("--full", action="store_true", help="Ignore the watermark and refetch every asset")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, but don't write store/doc files")
    args = parser.parse_args()

    client = AirClient()
    boards = load_board_config()
    if args.board:
        boards = [b for b in boards if b["slug"] == args.board]
        if not boards:
            print(f"No configured board with slug '{args.board}'", file=sys.stderr)
            sys.exit(1)

    for board_cfg in boards:
        result = sync_board(client, board_cfg, full=args.full, dry_run=args.dry_run)
        print(
            f"[{result['slug']}] total={result['total']} new={result['new']} "
            f"updated={result['updated']}"
            + (" (dry-run, not saved)" if args.dry_run else "")
        )

        if result["new"] or result["updated"] or args.full:
            board_info = client.get_board(result["board_id"])
            md = render_markdown(board_cfg, board_info, result["store"])
            if not args.dry_run:
                DOCS_DIR.mkdir(parents=True, exist_ok=True)
                doc_path = DOCS_DIR / f"{result['slug']}.md"
                doc_path.write_text(md)
                print(f"  wrote {doc_path.relative_to(REPO_ROOT)}")
        else:
            print("  no changes since last sync — doc left as-is")


if __name__ == "__main__":
    main()
