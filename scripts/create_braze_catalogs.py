#!/usr/bin/env python3
"""
Create and populate Braze catalogs for Sloan post-purchase cross-sell.
Catalogs: product_config, fabric_ids, leg_ids

Uses BRAZE_API_KEY_ID from .env. Run from repo root:
  uv run python scripts/create_braze_catalogs.py [--dry-run] [--recreate]
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")
API_KEY  = os.getenv("BRAZE_USERS_API_KEY_ID")  # needs catalog.create + catalog.items.create

CATALOG_DIR = Path(__file__).parent.parent / "data" / "braze_catalogs"

CATALOG_SCHEMAS = {
    "product_config": [
        {"name": "id",             "type": "string"},
        {"name": "base_url",       "type": "string"},
        {"name": "fabric_attr_id", "type": "number"},
        {"name": "leg_attr_id",    "type": "number"},
        {"name": "fixed_params",   "type": "string"},
    ],
    "fabric_ids": [
        {"name": "id",               "type": "string"},
        {"name": "product",          "type": "string"},
        {"name": "fabric_code",      "type": "string"},
        {"name": "material_type_id", "type": "number"},
    ],
    "leg_ids": [
        {"name": "id",            "type": "string"},
        {"name": "product",       "type": "string"},
        {"name": "leg_code",      "type": "string"},
        {"name": "legs_type_id",  "type": "number"},
    ],
}


def headers():
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def list_catalogs():
    r = requests.get(f"{BASE_URL}/catalogs", headers=headers(), timeout=15)
    r.raise_for_status()
    return [c["name"] for c in r.json().get("catalogs", [])]


def create_catalog(name, dry_run=False):
    payload = {
        "catalogs": [{
            "name": name,
            "description": f"Sloan cross-sell {name} — auto-generated",
            "fields": CATALOG_SCHEMAS[name],
        }]
    }
    if dry_run:
        print(f"  [dry-run] POST /catalogs  name={name}")
        return
    r = requests.post(f"{BASE_URL}/catalogs", headers=headers(), json=payload, timeout=15)
    if r.status_code in (200, 201):
        print(f"  ✓ Created catalog {name!r}")
    else:
        print(f"  ✗ Failed to create {name!r}: {r.status_code} {r.text[:200]}")
        sys.exit(1)


def delete_catalog(name, dry_run=False):
    if dry_run:
        print(f"  [dry-run] DELETE /catalogs/{name}")
        return
    r = requests.delete(f"{BASE_URL}/catalogs/{name}", headers=headers(), timeout=15)
    if r.status_code in (200, 204):
        print(f"  ✓ Deleted catalog {name!r}")
    else:
        print(f"  ✗ Could not delete {name!r}: {r.status_code} {r.text[:200]}")


def load_csv(name):
    path = CATALOG_DIR / f"{name}.csv"
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            item = {"id": row["id"]}
            for field in CATALOG_SCHEMAS[name]:
                val = row[field["name"]]
                if field["type"] == "number":
                    val = int(val)
                item[field["name"]] = val
            rows.append(item)
    return rows


def upload_items(catalog_name, items, dry_run=False, batch_size=50):
    total = len(items)
    uploaded = 0
    for i in range(0, total, batch_size):
        batch = items[i : i + batch_size]
        if dry_run:
            print(f"  [dry-run] POST /catalogs/{catalog_name}/items  batch {i//batch_size+1}  ({len(batch)} items)")
            uploaded += len(batch)
            continue
        r = requests.post(
            f"{BASE_URL}/catalogs/{catalog_name}/items",
            headers=headers(),
            json={"items": batch},
            timeout=30,
        )
        if r.status_code in (200, 201, 202):
            uploaded += len(batch)
            print(f"  ✓ {catalog_name}: uploaded {uploaded}/{total}")
        else:
            print(f"  ✗ Batch {i//batch_size+1} failed: {r.status_code} {r.text[:300]}")
            sys.exit(1)
        if i + batch_size < total:
            time.sleep(0.3)  # stay well under 1000 req/min
    return uploaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true", help="Print actions without calling API")
    parser.add_argument("--recreate", action="store_true", help="Delete and re-create catalogs that already exist")
    parser.add_argument("--catalog",  help="Only process this catalog (product_config|fabric_ids|leg_ids)")
    args = parser.parse_args()

    if not API_KEY:
        sys.exit("BRAZE_API_KEY_ID not set in .env")

    catalogs = list(CATALOG_SCHEMAS.keys())
    if args.catalog:
        if args.catalog not in CATALOG_SCHEMAS:
            sys.exit(f"Unknown catalog {args.catalog!r}. Must be one of {list(CATALOG_SCHEMAS)}")
        catalogs = [args.catalog]

    print(f"Braze base: {BASE_URL}")
    print(f"Catalogs to process: {catalogs}\n")

    existing = []
    if not args.dry_run:
        try:
            existing = list_catalogs()
            print(f"Existing catalogs: {existing}\n")
        except Exception as e:
            print(f"Warning: could not list catalogs ({e}). Proceeding anyway.\n")

    for name in catalogs:
        print(f"── {name} ──")
        if name in existing:
            if args.recreate:
                delete_catalog(name, dry_run=args.dry_run)
                time.sleep(1)
                create_catalog(name, dry_run=args.dry_run)
            else:
                print(f"  Already exists — uploading items (will upsert)")
        else:
            create_catalog(name, dry_run=args.dry_run)

        items = load_csv(name)
        print(f"  Loaded {len(items)} items from CSV")
        uploaded = upload_items(name, items, dry_run=args.dry_run)
        print(f"  Done: {uploaded} items\n")

    print("All catalogs populated.")


if __name__ == "__main__":
    main()
