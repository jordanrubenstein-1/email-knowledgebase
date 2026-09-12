#!/usr/bin/env python3
"""
One-off fix script — May 25, 2026.

Actions:
  1. CLEAR BOUNCES: all jordan.rubenstein* aliases, chaz.parrino,
     peter.salathe, carlos.gartner, brady.rushing, sabrina@the-citizenry.com
  2. UNSUBSCRIBE: deleted-customer addresses, david.meehan* aliases,
     catherine.sylvester, quinn.fitzpatrick, blair, eweatherl

Run:
    uv run python scripts/fix_bounces_may25.py --dry-run
    uv run python scripts/fix_bounces_may25.py
"""

import os, sys, time, json, argparse, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.environ["BRAZE_BASE_URL"].rstrip("/")

BRANDS = {
    "BUR": os.environ["BRAZE_API_KEY_BUR"],
    "HAV": os.environ["BRAZE_API_KEY_HAV"],
    "CZ":  os.environ["BRAZE_API_KEY_CZ"],
}

# ── Addresses ─────────────────────────────────────────────────────────────────

CLEAR_BOUNCE = [
    # jordan.rubenstein aliases (all workspaces)
    "jordan.rubenstein+20260204@havenly.com",
    "jordan.rubenstein+2@havenly.com",
    "jordan.rubenstein+20250924@havenly.com",
    "jordan.rubenstein+20251120v1@havenly.com",
    "jordan.rubenstein+20251204@havenly.com",
    "jordan.rubenstein+20260109@havenly.com",
    "jordan.rubenstein+20260321@havenly.com",
    "jordan.rubenstein+4@havenly.com",
    "jordan.rubenstein+trade_ti1@havenly.com",
    "jordan.rubenstein+3@havenly.com",
    # Staff / other
    "chaz.parrino@havenly.com",
    # interiordefine.com
    "peter.salathe@interiordefine.com",
    "carlos.gartner@interiordefine.com",
    "brady.rushing@interiordefine.com",
    # the-citizenry.com
    "sabrina@the-citizenry.com",
]

UNSUBSCRIBE = [
    # Deleted customers
    "3645354-deleted-customer@havenly.com",
    "3687658-deleted-customer@havenly.com",
    # david.meehan aliases
    "david.meehan+feb6@havenly.com",
    "david.meehan+1@havenly.com",
    # interior define / citizenry staff — confirmed inactive
    "catherine.sylvester@interiordefine.com",
    "quinn.fitzpatrick@interiordefine.com",
    "blair@the-citizenry.com",
    "eweatherl@the-citizenry.com",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def post(brand: str, endpoint: str, payload: dict, dry_run: bool) -> dict:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {BRANDS[brand]}",
        "Content-Type": "application/json",
    }
    if dry_run:
        print(f"  [DRY RUN] POST {endpoint}  {json.dumps(payload)[:120]}")
        return {"message": "dry_run"}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def clear_bounce(email: str, dry_run: bool):
    """Removes from bounce list and spam list in all three workspaces."""
    print(f"\n  Clearing bounce + spam for: {email}")
    for brand in ("BUR", "HAV", "CZ"):
        r1 = post(brand, "/email/bounce/remove", {"email": email}, dry_run)
        r2 = post(brand, "/email/spam/remove",   {"email": email}, dry_run)
        if not dry_run:
            ok1 = r1.get("message") == "success"
            ok2 = r2.get("message") == "success"
            print(f"    [{brand}] bounce/remove={'✓' if ok1 else '✗'} "
                  f"spam/remove={'✓' if ok2 else '✗'}")
            time.sleep(0.2)


def unsubscribe(email: str, dry_run: bool):
    """Sets subscription_state=unsubscribed in all three workspaces."""
    print(f"\n  Unsubscribing: {email}")
    for brand in ("BUR", "HAV", "CZ"):
        r = post(brand, "/email/status",
                 {"email": email, "subscription_state": "unsubscribed"}, dry_run)
        if not dry_run:
            ok = r.get("message") == "success"
            print(f"    [{brand}] {'✓' if ok else f'✗ {r}'}")
            time.sleep(0.2)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN — no changes will be made ===\n")

    print(f"── CLEAR BOUNCES ({len(CLEAR_BOUNCE)} addresses) ──────────────────")
    for email in CLEAR_BOUNCE:
        clear_bounce(email, args.dry_run)

    print(f"\n── UNSUBSCRIBE ({len(UNSUBSCRIBE)} addresses) ──────────────────────")
    for email in UNSUBSCRIBE:
        unsubscribe(email, args.dry_run)

    print("\nDone.")

if __name__ == "__main__":
    main()
