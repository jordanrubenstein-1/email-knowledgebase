#!/usr/bin/env python3
"""
Set trade_migration_batch on specific ID trade contacts' Braze profiles, so Braze-side
segments/canvases can key off which migration batch a contact is in.

Identification is the same two-step as scripts/flag_trade_chronic_bounces.py, whose
resolve_braze_ids/write_attribute helpers this script reuses. No profiles are created;
addresses with no Braze profile are skipped and reported.

Usage:
    uv run python scripts/mark_trade_migration_batch.py --batch batch_1 \\
        --email carlos.gartner+swatches@interiordefine.com \\
        --email hcrockett@the-citizenry.com \\
        --email jordan.rubenstein+tradetest1@havenly.com

    uv run python scripts/mark_trade_migration_batch.py --batch batch_2 --emails-file batch2.txt
    uv run python scripts/mark_trade_migration_batch.py --batch batch_1 --email ... --dry-run
    uv run python scripts/mark_trade_migration_batch.py --batch batch_1 --email ... --unset
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from flag_trade_chronic_bounces import resolve_braze_ids, write_attribute  # noqa: E402

ATTRIBUTE = "trade_migration_batch"
KEY_ENV = "BRAZE_USERS_API_KEY_ID"
ID_CACHE = REPO / "data" / "trade_migration_batch_braze_ids.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help='value to write, e.g. "batch_1"')
    ap.add_argument("--email", action="append", default=[], help="repeatable")
    ap.add_argument("--emails-file", type=Path, help="one email per line")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--unset", action="store_true",
                     help=f"clear {ATTRIBUTE} (sets it to an empty string) instead of writing --batch")
    args = ap.parse_args()

    emails = [e.strip().lower() for e in args.email if e.strip()]
    if args.emails_file:
        emails += [line.strip().lower() for line in args.emails_file.read_text().splitlines()
                   if line.strip()]
    emails = sorted(set(emails))
    if not emails:
        raise SystemExit("no emails provided -- pass --email (repeatable) and/or --emails-file")

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} not set in .env")

    value = "" if args.unset else args.batch

    print(f"Resolving braze_ids for {len(emails)} address(es)...")
    id_map = resolve_braze_ids(emails, key, cache_path=ID_CACHE)

    targets: list[str] = []
    no_profile = []
    for email in emails:
        ids = id_map.get(email)
        if not ids:
            no_profile.append(email)
            continue
        targets.extend(ids if isinstance(ids, list) else [ids])

    print(f"  {len(emails) - len(no_profile)} address(es) resolved to {len(targets)} Braze profile(s)")
    if no_profile:
        print(f"  no Braze profile found (skipped): {', '.join(no_profile)}")

    if args.dry_run:
        print(f"\n--dry-run: would set {ATTRIBUTE} = {value!r} on {len(targets)} profile(s)")
        return

    print(f"\nSetting {ATTRIBUTE} = {value!r} on {len(targets)} profile(s)...")
    processed, failed = write_attribute(targets, key, value, attribute=ATTRIBUTE)
    print(f"  attributes_processed: {processed}   failed: {failed}")


if __name__ == "__main__":
    main()
