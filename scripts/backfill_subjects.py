"""
Backfill missing subject lines for email campaign YAMLs.

Targets:
  - Klaviyo TI/TE campaigns with empty sends (klaviyo_message_id: None)
  - Braze canvas_step YAMLs with empty sends
  - Braze campaign YAMLs with sends but no subject

Usage:
    uv run python scripts/backfill_subjects.py [--brand TI|TE|all] [--dry-run]
"""

import argparse
import glob
import os
import sys

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.utils.klaviyo_client import KlaviyoClient


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def has_subject(record):
    """Return True if the record already has a subject somewhere."""
    if record.get("subject", "").strip():
        return True
    for s in record.get("sends", []):
        if isinstance(s, dict) and s.get("subject", "").strip():
            return True
    return False


def find_missing(brands=None):
    """Return list of (path, record) for email YAMLs missing a subject."""
    results = []
    for f in sorted(glob.glob("campaigns/*.yaml")):
        try:
            d = load_yaml(f)
        except Exception:
            continue
        if d.get("channel") != "email":
            continue
        if brands and d.get("brand") not in brands:
            continue
        if not has_subject(d):
            results.append((f, d))
    return results


# --------------------------------------------------------------------------- #
# Klaviyo backfill
# --------------------------------------------------------------------------- #

def _klv_client(brand):
    key_var = f"KLAVIYO_API_KEY_{brand}"
    key = os.environ.get(key_var)
    if not key:
        print(f"  ERROR: {key_var} not set in .env — skipping {brand}")
        return None
    return KlaviyoClient(api_key=key, brand=brand)


def backfill_klaviyo(paths_records, dry_run=False):
    """Fetch subject lines for Klaviyo campaigns with empty sends."""
    # Group by brand
    by_brand = {}
    for path, rec in paths_records:
        brand = rec.get("brand")
        if brand not in ("TI", "TE"):
            continue
        cid = rec.get("klaviyo_campaign_id")
        if not cid:
            continue
        by_brand.setdefault(brand, []).append((path, rec, cid))

    total_updated = 0

    for brand, items in by_brand.items():
        print(f"\n[{brand}] Backfilling {len(items)} Klaviyo campaigns...")
        client = _klv_client(brand)
        if not client:
            continue

        for path, rec, campaign_id in items:
            try:
                messages = client.get_campaign_messages(campaign_id)
            except Exception as e:
                print(f"  WARN: {campaign_id} fetch failed: {e}")
                continue

            if not messages:
                print(f"  SKIP: {campaign_id} — no messages returned")
                continue

            # Extract subject from first message
            msg = messages[0]
            msg_id = msg.get("id", "")
            msg_attrs = msg.get("attributes", {})
            content = msg_attrs.get("content") or {}
            subject = (content.get("subject") or "").strip()
            preheader = (content.get("preview_text") or "").strip()

            if not subject:
                print(f"  SKIP: {campaign_id} — API returned empty subject")
                continue

            print(f"  {rec['name'][:60]}")
            print(f"    subject: {subject}")

            if not dry_run:
                # Build a proper sends entry
                send = {
                    "id": msg_id,
                    "channel": "email",
                    "name": msg_attrs.get("label") or "Variant A",
                    "subject": subject,
                    "preheader": preheader,
                }
                rec["sends"] = [send]
                rec["klaviyo_message_id"] = msg_id
                save_yaml(path, rec)
                total_updated += 1

    print(f"\nKlaviyo: updated {total_updated} YAMLs")
    return total_updated


# --------------------------------------------------------------------------- #
# Braze backfill
# --------------------------------------------------------------------------- #

def _braze_request(endpoint, params, brand):
    """Make a Braze API request for a given brand."""
    import requests

    key_var = f"BRAZE_API_KEY_{brand}"
    key = os.environ.get(key_var) or os.environ.get("BRAZE_API_KEY")
    if not key:
        print(f"  ERROR: {key_var} not set — skipping")
        return None

    base_url = "https://rest.iad-01.braze.com"
    resp = requests.get(
        f"{base_url}/{endpoint}",
        headers={"Authorization": f"Bearer {key}"},
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  ERROR: {resp.status_code} for {endpoint}")
        return None
    return resp.json()


def _get_braze_base_url(brand):
    """Get Braze REST endpoint for a brand from env."""
    return os.environ.get(f"BRAZE_REST_ENDPOINT_{brand}") or "https://rest.iad-01.braze.com"


def backfill_braze_campaigns(paths_records, dry_run=False):
    """Fetch subject lines for Braze campaign YAMLs missing subjects."""
    import requests

    total_updated = 0
    braze_items = [(p, r) for p, r in paths_records
                   if r.get("braze_type") == "campaign"
                   and r.get("brand") not in ("TI", "TE")]

    if not braze_items:
        return 0

    print(f"\n[Braze campaigns] Backfilling {len(braze_items)} campaigns...")

    for path, rec in braze_items:
        brand = rec.get("brand", "")
        campaign_id = rec.get("id", "")
        if not campaign_id or campaign_id.startswith("klaviyo-"):
            continue

        key_var = f"BRAZE_API_KEY_{brand}"
        key = os.environ.get(key_var) or os.environ.get("BRAZE_API_KEY")
        if not key:
            print(f"  SKIP: no API key for {brand}")
            continue

        base_url = "https://rest.iad-01.braze.com"
        try:
            resp = requests.get(
                f"{base_url}/campaigns/details",
                headers={"Authorization": f"Bearer {key}"},
                params={"campaign_id": campaign_id},
                timeout=30,
            )
        except Exception as e:
            print(f"  WARN: {campaign_id}: {e}")
            continue

        if resp.status_code != 200:
            print(f"  SKIP: {campaign_id} — {resp.status_code}")
            continue

        data = resp.json()
        messages = data.get("messages", {})
        subject = ""
        preheader = ""
        msg_id = ""
        msg_name = "Variant 1"

        for key_name, msg in messages.items():
            if isinstance(msg, dict) and msg.get("channel") == "email":
                subject = (msg.get("subject") or "").strip()
                preheader = (msg.get("preheader") or "").strip()
                msg_id = key_name
                msg_name = msg.get("name", "Variant 1")
                if subject:
                    break

        if not subject:
            print(f"  SKIP: {rec['name'][:50]} — no subject in API response")
            continue

        print(f"  [{brand}] {rec['name'][:60]}")
        print(f"    subject: {subject}")

        if not dry_run:
            rec["sends"] = [{
                "id": msg_id,
                "channel": "email",
                "name": msg_name,
                "subject": subject,
                "preheader": preheader,
            }]
            save_yaml(path, rec)
            total_updated += 1

    print(f"Braze campaigns: updated {total_updated} YAMLs")
    return total_updated


def backfill_braze_canvas_steps(paths_records, dry_run=False):
    """Fetch subject lines for Braze canvas_step YAMLs with empty sends."""
    import requests

    total_updated = 0
    step_items = [(p, r) for p, r in paths_records
                  if r.get("braze_type") == "canvas_step"
                  and r.get("canvas_id")]

    if not step_items:
        return 0

    print(f"\n[Braze canvas_steps] Backfilling {len(step_items)} steps...")

    # Group by canvas_id to minimize API calls
    canvas_cache = {}
    for path, rec in step_items:
        brand = rec.get("brand", "")
        canvas_id = rec.get("canvas_id", "")
        step_id = rec.get("id", "")

        if canvas_id not in canvas_cache:
            key_var = f"BRAZE_API_KEY_{brand}"
            key = os.environ.get(key_var) or os.environ.get("BRAZE_API_KEY")
            if not key:
                print(f"  SKIP: no API key for {brand}")
                canvas_cache[canvas_id] = None
                continue

            base_url = "https://rest.iad-01.braze.com"
            try:
                resp = requests.get(
                    f"{base_url}/canvas/details",
                    headers={"Authorization": f"Bearer {key}"},
                    params={"canvas_id": canvas_id},
                    timeout=30,
                )
                canvas_cache[canvas_id] = resp.json() if resp.status_code == 200 else None
            except Exception as e:
                print(f"  WARN: canvas {canvas_id}: {e}")
                canvas_cache[canvas_id] = None

        canvas_data = canvas_cache.get(canvas_id)
        if not canvas_data:
            print(f"  SKIP: {rec['name'][:50]} — canvas fetch failed")
            continue

        # Find matching step
        subject = ""
        preheader = ""
        for step in canvas_data.get("steps", []):
            if step.get("id") != step_id:
                continue
            messages = step.get("messages", {})
            for _, msg in (messages.items() if isinstance(messages, dict) else []):
                if isinstance(msg, dict) and msg.get("channel") == "email":
                    subject = (msg.get("subject") or "").strip()
                    preheader = (msg.get("preheader") or "").strip()
                    break
            break

        if not subject:
            print(f"  SKIP: {rec['name'][:50]} — no subject found in canvas steps")
            continue

        print(f"  [{brand}] {rec['name'][:60]}")
        print(f"    subject: {subject}")

        if not dry_run:
            rec["subject"] = subject
            if preheader:
                rec["preheader"] = preheader
            rec["sends"] = [{
                "id": step_id,
                "channel": "email",
                "name": rec.get("name", ""),
                "subject": subject,
                "preheader": preheader,
            }]
            save_yaml(path, rec)
            total_updated += 1

    print(f"Braze canvas_steps: updated {total_updated} YAMLs")
    return total_updated


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Backfill missing subject lines in email campaign YAMLs")
    parser.add_argument("--brand", default="all", help="Brand code (TI, TE, HAV, CZ, ID, BUR, STF) or 'all'")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing files")
    args = parser.parse_args()

    brands = None
    if args.brand.lower() != "all":
        brands = {args.brand.upper()}

    print(f"Scanning for email YAMLs missing subject lines...")
    missing = find_missing(brands)
    print(f"Found {len(missing)} email YAMLs missing subject")

    if not missing:
        print("Nothing to do.")
        return

    # Breakdown
    from collections import Counter
    by_bt = Counter(r.get("braze_type", "?") for _, r in missing)
    by_brand = Counter(r.get("brand", "?") for _, r in missing)
    print(f"  By braze_type: {dict(by_bt.most_common())}")
    print(f"  By brand: {dict(by_brand.most_common())}")

    if args.dry_run:
        print("\n[DRY RUN — no files will be written]")

    total = 0
    total += backfill_klaviyo(missing, dry_run=args.dry_run)
    total += backfill_braze_campaigns(missing, dry_run=args.dry_run)
    total += backfill_braze_canvas_steps(missing, dry_run=args.dry_run)

    print(f"\nTotal YAMLs updated: {total}")
    remaining = len(missing) - total
    if remaining > 0:
        print(f"Remaining without subject (modals/popups/canvases): {remaining}")
        print("  These are likely popup capture forms, webhook tests, or canvas parent entries")
        print("  that legitimately have no email subject line.")


if __name__ == "__main__":
    main()
