#!/usr/bin/env python3
"""
Backfill type and theme fields into existing Klaviyo YAML files.

Reads name from each YAML, infers type/theme locally (no API calls),
and rewrites the file only if something changed.

Usage:
    uv run python scripts/backfill_type_theme.py            # all brands
    uv run python scripts/backfill_type_theme.py --brand TI
    uv run python scripts/backfill_type_theme.py --dry-run
"""
import argparse
import sys
from pathlib import Path

import yaml

# Add scripts/ to path so imports resolve the same way as import_klaviyo.py
sys.path.insert(0, str(Path(__file__).parent))

from import_braze import infer_campaign_type, infer_theme

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"
KLAVIYO_BRANDS = {"TI", "TE"}


def patch_file(path: Path, dry_run: bool) -> str:
    """Patch a single YAML file. Returns 'updated', 'skipped', or 'error'."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"  ERROR reading {path.name}: {e}")
        return "error"

    if not isinstance(data, dict):
        return "skipped"

    # Only touch Klaviyo records
    record_id = data.get("id", "")
    if not str(record_id).startswith("klaviyo-"):
        return "skipped"

    name = data.get("name", "")
    new_type = infer_campaign_type(name, None)
    new_theme = infer_theme(name)

    current_type = data.get("type")
    current_theme = data.get("theme")

    if current_type == new_type and current_theme == new_theme:
        return "skipped"

    if dry_run:
        changes = []
        if current_type != new_type:
            changes.append(f"type: {current_type!r} → {new_type!r}")
        if current_theme != new_theme:
            changes.append(f"theme: {current_theme!r} → {new_theme!r}")
        print(f"  {path.name}: {', '.join(changes)}")
        return "updated"

    # Rebuild dict with type/theme inserted after category, preserving all other fields.
    # We do this manually to control field order rather than relying on yaml sort_keys.
    patched: dict = {}
    inserted = False
    for key, val in data.items():
        if key in ("type", "theme"):
            continue  # drop old values; we'll re-insert in the right spot
        patched[key] = val
        if key == "category" and not inserted:
            patched["type"] = new_type
            if new_theme:
                patched["theme"] = new_theme
            inserted = True

    # Fallback if 'category' wasn't present
    if not inserted:
        patched["type"] = new_type
        if new_theme:
            patched["theme"] = new_theme

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(patched, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return "updated"


def main():
    parser = argparse.ArgumentParser(description="Backfill type/theme into Klaviyo YAMLs")
    parser.add_argument("--brand", choices=sorted(KLAVIYO_BRANDS),
                        help="Limit to a single brand")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing")
    args = parser.parse_args()

    target_brands = {args.brand} if args.brand else KLAVIYO_BRANDS

    files = sorted(CAMPAIGNS_DIR.glob("*.yaml"))
    counts = {"updated": 0, "skipped": 0, "error": 0, "wrong_brand": 0}

    for path in files:
        # Quick brand filter: peek at first few lines before full parse
        try:
            with open(path, encoding="utf-8") as f:
                header = f.read(256)
        except Exception:
            counts["error"] += 1
            continue

        brand_match = False
        for brand in target_brands:
            if f"brand: {brand}" in header:
                brand_match = True
                break
        if not brand_match:
            counts["wrong_brand"] += 1
            continue

        result = patch_file(path, args.dry_run)
        counts[result] += 1

    action = "Would update" if args.dry_run else "Updated"
    print(
        f"\n{action} {counts['updated']} files "
        f"({counts['skipped']} already correct, {counts['error']} errors)"
    )


if __name__ == "__main__":
    main()
