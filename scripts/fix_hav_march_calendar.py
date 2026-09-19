#!/usr/bin/env python3
"""Fix HAV March calendar: diversify spring content & add Sunday sends."""

import os, sys, time, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"

def asana_headers():
    return {
        "Authorization": f"Bearer {os.environ['ASANA_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def asana_update(task_gid, updates, dry_run=False):
    label = updates.get("name", task_gid)
    if dry_run:
        print(f"  [DRY RUN] Would update {task_gid}: {updates}")
        return True
    url = f"{ASANA_BASE_URL}/tasks/{task_gid}"
    resp = requests.put(url, headers=asana_headers(), json={"data": updates})
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.put(url, headers=asana_headers(), json={"data": updates})
    if resp.status_code not in (200, 201):
        print(f"  ✗ Error {resp.status_code}: {resp.text[:200]}")
        return False
    return True

def generate_direction(name, prefix, audience, category, segment):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    audience_desc = (
        "pre-converted customers who have NOT yet purchased design services — "
        "goal is to inspire them to explore Havenly's design services and browse furniture"
        if audience == "pre_converted"
        else "converted/marketplace customers who HAVE used design services — "
        "goal is to get them to shop their design, buy additional furniture, and complete their rooms"
    )

    prompt = f"""Write email creative direction and subject line options for this Havenly email.

AUDIENCE: {prefix} — {audience_desc}
EMAIL TOPIC: {name}
CATEGORY: {category}
SEGMENT: {"Full subscriber list (biggest sends, most compelling content)" if segment == "full_file" else "Engaged subscribers (more targeted, can be softer content)"}

BRAND CONTEXT: Havenly is an online interior design service and furniture marketplace.
Best-performing HAV emails use curiosity-driven subject lines (e.g. "The #1 TV styling mistake...", "This 'controversial' color is back").
Editorial content outperforms sale/promo by 3-4x on click rate.
Avoid discount language in subject lines. Use aspirational, confident tone.
SL format: 30-40 characters (short title). PH format: 150-170 characters (lowercase, complementary).

Be concise — one short sentence per bullet, no fluff.

Return EXACTLY this format:

Direction: [1 sentence — goal and tone]
Hero: [1 sentence — what the hero image/section shows]
Feature: [1 sentence — products or offer to spotlight]
CTA: [1 sentence — button text and where it goes]

Option 1:
SL: [subject line, 30-40 chars]
PH: [pre-header, 150-170 chars, lowercase]

Option 2:
SL: [subject line, 30-40 chars]
PH: [pre-header, 150-170 chars, lowercase]"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"  AI error {resp.status_code}")
            return None
        text = resp.json()["content"][0]["text"].strip()
        text = text.replace("\\n", "\n")  # Haiku sometimes outputs literal \n instead of newlines
        return text
    except Exception as e:
        print(f"  AI exception: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-ai", action="store_true")
    args = parser.parse_args()

    # =====================================================================
    # 1. Rename spring-heavy tasks (2/26 – 3/3)
    # =====================================================================
    renames = [
        # (gid, new_name, prefix, audience, category, segment)
        ("1213213403681331", "DPS: Our Most-Loved New Arrivals", "DPS", "pre_converted", "product_launch", "full_file"),
        ("1213220649112344", "MP: Our Most-Loved New Arrivals", "MP", "customers", "product_launch", "full_file"),
        ("1213220640131099", "DPS: The Color Combo Designers Can't Stop Using", "DPS", "pre_converted", "editorial", "full_file"),
        ("1213213658717468", "MP: The Color Combo Designers Can't Stop Using", "MP", "customers", "editorial", "full_file"),
        ("1213220625690342", "DPS: Ready for a Room Refresh? Start Here", "DPS", "pre_converted", "dps", "engaged_file"),
        ("1213221341067485", "MP: New Picks for Your Design", "MP", "customers", "editorial", "engaged_file"),
        ("1213221592228313", "DPS: New Arrivals: Statement Pieces for March", "DPS", "pre_converted", "product_launch", "full_file"),
        ("1213213569837299", "MP: New Arrivals: Statement Pieces for March", "MP", "customers", "product_launch", "full_file"),
        ("1213221760930055", "DPS: The #1 Decorating Mistake Everyone Makes", "DPS", "pre_converted", "editorial", "full_file"),
        ("1213220655023728", "MP: The #1 Decorating Mistake Everyone Makes", "MP", "customers", "editorial", "full_file"),
    ]

    # Push renames (no AI needed)
    push_renames = [
        ("1213221334871989", "DPS: New arrivals just dropped"),
        ("1213213658686840", "MP: New arrivals just dropped"),
    ]

    print("=== Renaming spring-heavy tasks (2/26–3/3) ===\n")
    for gid, new_name, prefix, audience, category, segment in renames:
        topic = new_name.split(": ", 1)[1]
        print(f"  {new_name}")

        updates = {"name": new_name}

        if not args.skip_ai:
            direction = generate_direction(topic, prefix, audience, category, segment)
            if direction:
                updates["notes"] = direction + "\n\n[Auto-created: HAV calendar fill 2/26–3/31]"
                print(f"    ✓ AI direction generated")
            else:
                print(f"    ⚠ AI generation failed")

        ok = asana_update(gid, updates, dry_run=args.dry_run)
        print(f"    {'✓' if ok else '✗'} {'Updated' if ok else 'Failed'}")
        if not args.dry_run:
            time.sleep(0.5)

    for gid, new_name in push_renames:
        topic = new_name.split(": ", 1)[1]
        print(f"  {new_name}")
        updates = {
            "name": new_name,
            "notes": f"Push notification for {new_name.split(':')[0]} audience.\nContent: {topic}\n\n[Auto-created: HAV calendar fill 2/26–3/31]",
        }
        ok = asana_update(gid, updates, dry_run=args.dry_run)
        print(f"    {'✓' if ok else '✗'} {'Updated' if ok else 'Failed'}")
        if not args.dry_run:
            time.sleep(0.5)

    # =====================================================================
    # 2. Move Saturday emails → Sunday
    # =====================================================================
    print("\n=== Moving Saturday emails to Sunday ===\n")

    date_moves = [
        # (gid, task_name, old_date, new_date)
        # Partial week: 2/28 (Sat) → 3/1 (Sun)
        ("1213220625690342", "DPS: Ready for a Room Refresh? Start Here", "2026-02-28", "2026-03-01"),
        ("1213221341067485", "MP: New Picks for Your Design", "2026-02-28", "2026-03-01"),
        # Week of Mar 2: 3/7 (Sat) → 3/8 (Sun)
        ("1213222172330062", "DPS: Work with a Havenly Designer This Spring", "2026-03-07", "2026-03-08"),
        ("1213222177766771", "MP: Trending Now: Most-Loved Spring Picks", "2026-03-07", "2026-03-08"),
        # Week of Mar 9: 3/14 (Sat) → 3/15 (Sun)
        ("1213222194996305", "DPS: Design Package Spotlight: Kitchen Refresh", "2026-03-14", "2026-03-15"),
        ("1213213570013052", "MP: Customer Spotlight: Real Spring Makeovers", "2026-03-14", "2026-03-15"),
        # Week of Mar 16: 3/21 (Sat) → 3/22 (Sun)
        ("1213222216829539", "DPS: Why Designers Love Spring Makeovers", "2026-03-21", "2026-03-22"),
        ("1213222216815405", "MP: Spring Cleaning, Design Edition", "2026-03-21", "2026-03-22"),
        # Week of Mar 23: 3/28 (Sat) → 3/29 (Sun)
        ("1213222226712696", "DPS: Spring Style Quiz: Your Design Personality", "2026-03-28", "2026-03-29"),
        ("1213213405002472", "MP: Restock & Refresh: Spring Essentials", "2026-03-28", "2026-03-29"),
    ]

    for gid, name, old_date, new_date in date_moves:
        print(f"  {name}: {old_date} → {new_date}")
        ok = asana_update(gid, {"due_on": new_date}, dry_run=args.dry_run)
        print(f"    {'✓' if ok else '✗'} {'Updated' if ok else 'Failed'}")
        if not args.dry_run:
            time.sleep(0.3)

    print("\nDone!")
    if args.dry_run:
        print("(dry run — no changes made)")


if __name__ == "__main__":
    main()
