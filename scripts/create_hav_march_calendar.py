#!/usr/bin/env python3
"""One-time script: Create Havenly DPS + MP tasks for 2/26 – 3/31."""

import os, sys, time, requests
from pathlib import Path
from typing import Dict, Optional, List
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Asana constants
# ---------------------------------------------------------------------------
ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"

FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TYPE = "1207522425689987"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_CATEGORY = "1207522425689885"
FIELD_SEGMENT = "1211927654349290"
FIELD_AUDIENCE = "1207522425689896"
FIELD_SEND_TIME = "1212524397761931"
FIELD_SUBJECT_LINE = "1207522425689914"
FIELD_PRE_HEADER = "1207522425689916"

BRAND_HAVENLY = "1207522425689881"
CHANNEL_EMAIL = "1207562370794989"
CHANNEL_PUSH = "1207562370794991"
TYPE_BATCH_BLAST = "1209982215610998"
STATUS_AWAITING_CREATIVE = "1209982215610994"

CATEGORY_GIDS = {
    "sale_merch": "1207522425689886",
    "editorial": "1207522425689887",
    "product_launch": "1207522425689888",
    "product_category": "1207522425689889",
    "dps": "1207522425689891",
}

SEGMENT_GIDS = {
    "full_file": "1211927654349291",
    "engaged_file": "1211927654349292",
}

AUDIENCE_GIDS = {
    "pre_converted": "1207522425689897",
    "customers": "1207522425689898",
}

# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------
def get_asana_token():
    return os.environ["ASANA_ACCESS_TOKEN"]

def asana_headers():
    return {
        "Authorization": f"Bearer {get_asana_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def asana_request(method, endpoint, json_data=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=asana_headers(), json=json_data)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.request(method, url, headers=asana_headers(), json=json_data)
    if resp.status_code not in (200, 201):
        print(f"  Asana error {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json().get("data")

# ---------------------------------------------------------------------------
# AI generation (direction + SL/PH in one call)
# ---------------------------------------------------------------------------
def generate_direction_and_slph(task: Dict) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    audience_desc = (
        "pre-converted customers who have NOT yet purchased design services — "
        "goal is to inspire them to explore Havenly's design services and browse furniture"
        if task["audience"] == "pre_converted"
        else "converted/marketplace customers who HAVE used design services — "
        "goal is to get them to shop their design, buy additional furniture, and complete their rooms"
    )

    prompt = f"""Write email creative direction and subject line options for this Havenly email.

AUDIENCE: {task['prefix']} — {audience_desc}
EMAIL TOPIC: {task['name']}
CATEGORY: {task['category']}
CHANNEL: {task['channel']}
SEGMENT: {"Full subscriber list (biggest sends, most compelling content)" if task['segment'] == 'full_file' else "Engaged subscribers (more targeted, can be softer content)"}

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
            print(f"  AI error {resp.status_code}: {resp.text[:200]}")
            return None
        text = resp.json()["content"][0]["text"].strip()
        text = text.replace("\\n", "\n")  # Haiku sometimes outputs literal \n instead of newlines
        return text
    except Exception as e:
        print(f"  AI exception: {e}")
        return None

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

def build_tasks() -> List[Dict]:
    """Return all task definitions for 2/26 – 3/31."""
    tasks = []

    def add(date, prefix, name, channel, category, segment, audience, send_time=""):
        tasks.append({
            "date": date,
            "prefix": prefix,
            "name": f"{prefix}: {name}",
            "topic": name,
            "channel": channel,
            "category": category,
            "segment": segment,
            "audience": audience,
            "send_time": send_time,
        })

    # Helper for paired DPS/MP sends
    def add_pair(date, name, channel, category, segment, send_time=""):
        add(date, "DPS", name, channel, category, segment, "pre_converted", send_time)
        add(date, "MP", name, channel, category, segment, "customers", send_time)

    # ===== Week of Feb 26 (partial: Thu-Sat) — 3 emails + 1 push each =====
    add_pair("2026-02-26", "Spring Preview: What's New", "email", "product_launch", "full_file", "10 AM")
    add_pair("2026-02-27", "Bright & Airy: Spring Room Inspiration", "email", "editorial", "full_file", "10 AM")
    add("2026-02-28", "DPS", "Start Your Spring Design Project", "email", "dps", "engaged_file", "pre_converted", "4 PM")
    add("2026-02-28", "MP", "Shop Your Spring Design", "email", "editorial", "engaged_file", "customers", "4 PM")
    add_pair("2026-02-27", "Spring is almost here", "push", "editorial", "full_file", "3 PM")

    # ===== Week of Mar 2 — 6 emails + 2 push each =====
    # Monday
    add_pair("2026-03-02", "Spring New Arrivals", "email", "product_launch", "full_file", "10 AM")
    # Tuesday
    add_pair("2026-03-03", "The #1 Spring Decorating Mistake", "email", "editorial", "full_file", "10 AM")
    # Wednesday
    add_pair("2026-03-04", "Category Spotlight: Living Room Refresh", "email", "product_category", "full_file", "10 AM")
    # Thursday
    add_pair("2026-03-05", "Spring Color Trends 2026", "email", "editorial", "full_file", "10 AM")
    # Friday
    add("2026-03-06", "DPS", "Before & After: Room Makeover Inspiration", "email", "editorial", "engaged_file", "pre_converted", "4 PM")
    add("2026-03-06", "MP", "Complete Your Room: Spring Accents", "email", "product_category", "engaged_file", "customers", "4 PM")
    # Saturday
    add("2026-03-07", "DPS", "Work with a Havenly Designer This Spring", "email", "dps", "engaged_file", "pre_converted", "10 AM")
    add("2026-03-07", "MP", "Trending Now: Most-Loved Spring Picks", "email", "editorial", "engaged_file", "customers", "10 AM")
    # Push
    add_pair("2026-03-03", "Spring arrivals just dropped", "push", "product_launch", "full_file", "3 PM")
    add_pair("2026-03-06", "Your spring room refresh starts here", "push", "editorial", "full_file", "3 PM")

    # ===== Week of Mar 9 — 6 emails + 2 push each =====
    add_pair("2026-03-09", "This 'Outdated' Color Is Trending Again", "email", "editorial", "full_file", "10 AM")
    add_pair("2026-03-10", "Outdoor Living Preview", "email", "product_category", "full_file", "10 AM")
    add_pair("2026-03-11", "New Arrivals: Spring Rugs & Pillows", "email", "product_launch", "full_file", "10 AM")
    add_pair("2026-03-12", "Small Changes That Transform a Room", "email", "editorial", "full_file", "10 AM")
    add("2026-03-13", "DPS", "Smart Updates: Easy Spring Swaps", "email", "editorial", "engaged_file", "pre_converted", "4 PM")
    add("2026-03-13", "MP", "Your Design, Refreshed for Spring", "email", "editorial", "engaged_file", "customers", "4 PM")
    add("2026-03-14", "DPS", "Design Package Spotlight: Kitchen Refresh", "email", "dps", "engaged_file", "pre_converted", "10 AM")
    add("2026-03-14", "MP", "Customer Spotlight: Real Spring Makeovers", "email", "editorial", "engaged_file", "customers", "10 AM")
    add_pair("2026-03-10", "Outdoor season is coming — see what's new", "push", "product_category", "full_file", "3 PM")
    add_pair("2026-03-13", "Fresh spring design inspo inside", "push", "editorial", "full_file", "3 PM")

    # ===== Week of Mar 16 — 6 emails + 2 push each =====
    add_pair("2026-03-16", "The #1 Rug Mistake That Ruins a Room", "email", "editorial", "full_file", "10 AM")
    add_pair("2026-03-17", "Spring Entertaining: Dining Room Refresh", "email", "product_category", "full_file", "10 AM")
    add_pair("2026-03-18", "New Arrivals: Statement Lighting", "email", "product_launch", "full_file", "10 AM")
    add_pair("2026-03-19", "First Day of Spring: Fresh Starts", "email", "editorial", "full_file", "10 AM")
    add("2026-03-20", "DPS", "How to Choose the Right Sofa", "email", "editorial", "engaged_file", "pre_converted", "4 PM")
    add("2026-03-20", "MP", "Finish Your Look: Spring Accent Pieces", "email", "product_category", "engaged_file", "customers", "4 PM")
    add("2026-03-21", "DPS", "Why Designers Love Spring Makeovers", "email", "dps", "engaged_file", "pre_converted", "10 AM")
    add("2026-03-21", "MP", "Spring Cleaning, Design Edition", "email", "editorial", "engaged_file", "customers", "10 AM")
    add_pair("2026-03-17", "Refresh your dining room for spring", "push", "product_category", "full_file", "3 PM")
    add_pair("2026-03-20", "Happy first day of spring — new arrivals", "push", "editorial", "full_file", "3 PM")

    # ===== Week of Mar 23 — 6 emails + 2 push each =====
    add_pair("2026-03-23", "Why Designers Say Your Sofa Is in the Wrong Spot", "email", "editorial", "full_file", "10 AM")
    add_pair("2026-03-24", "Category Spotlight: Bedroom Retreat", "email", "product_category", "full_file", "10 AM")
    add_pair("2026-03-25", "New Arrivals: Spring Outdoor Collection", "email", "product_launch", "full_file", "10 AM")
    add_pair("2026-03-26", "The Color Combo That Looks Expensive", "email", "editorial", "full_file", "10 AM")
    add("2026-03-27", "DPS", "Ready for a Room Makeover? Start Here", "email", "dps", "engaged_file", "pre_converted", "4 PM")
    add("2026-03-27", "MP", "Shop the Look: Designer-Curated Rooms", "email", "product_category", "engaged_file", "customers", "4 PM")
    add("2026-03-28", "DPS", "Spring Style Quiz: Your Design Personality", "email", "editorial", "engaged_file", "pre_converted", "10 AM")
    add("2026-03-28", "MP", "Restock & Refresh: Spring Essentials", "email", "editorial", "engaged_file", "customers", "10 AM")
    add_pair("2026-03-24", "Refresh your bedroom for spring", "push", "product_category", "full_file", "3 PM")
    add_pair("2026-03-27", "The color combo everyone's loving", "push", "editorial", "full_file", "3 PM")

    # ===== Week of Mar 30 (partial: Mon-Tue) — 2 emails + 1 push each =====
    add_pair("2026-03-30", "April Preview: What's Coming Next", "email", "editorial", "full_file", "10 AM")
    add_pair("2026-03-31", "The Design Trend Taking Over This Spring", "email", "editorial", "full_file", "10 AM")
    add_pair("2026-03-31", "April is going to be good — sneak peek", "push", "editorial", "full_file", "3 PM")

    return tasks


# ---------------------------------------------------------------------------
# Create Asana tasks
# ---------------------------------------------------------------------------

def create_task(task: Dict, description: str, dry_run: bool = False) -> Optional[str]:
    channel_gid = CHANNEL_EMAIL if task["channel"] == "email" else CHANNEL_PUSH
    category_gid = CATEGORY_GIDS.get(task["category"])
    segment_gid = SEGMENT_GIDS.get(task["segment"])
    audience_gid = AUDIENCE_GIDS.get(task["audience"])

    custom_fields = {
        FIELD_BRAND: BRAND_HAVENLY,
        FIELD_CHANNEL: channel_gid,
        FIELD_TASK_STATUS: STATUS_AWAITING_CREATIVE,
    }
    if task["channel"] == "email":
        custom_fields[FIELD_TYPE] = TYPE_BATCH_BLAST
    if category_gid:
        custom_fields[FIELD_CATEGORY] = category_gid
    if segment_gid:
        custom_fields[FIELD_SEGMENT] = segment_gid
    if audience_gid:
        custom_fields[FIELD_AUDIENCE] = audience_gid
    if task.get("send_time"):
        custom_fields[FIELD_SEND_TIME] = task["send_time"]

    payload = {
        "data": {
            "name": task["name"],
            "due_on": task["date"],
            "projects": [ASANA_PROJECT_GID],
            "notes": description,
            "custom_fields": custom_fields,
        }
    }

    if dry_run:
        print(f"  [DRY RUN] {task['name']} ({task['channel']}, {task['segment']})")
        return "dry-run"

    result = asana_request("POST", "tasks", json_data=payload)
    if result:
        return result.get("gid")
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI direction/SL generation")
    args = parser.parse_args()

    tasks = build_tasks()
    print(f"Total tasks to create: {len(tasks)}")
    print(f"  Email: {sum(1 for t in tasks if t['channel'] == 'email')}")
    print(f"  Push: {sum(1 for t in tasks if t['channel'] == 'push')}")
    print(f"  DPS: {sum(1 for t in tasks if t['prefix'] == 'DPS')}")
    print(f"  MP: {sum(1 for t in tasks if t['prefix'] == 'MP')}")
    print()

    created = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        label = f"[{i}/{len(tasks)}] {task['date']} | {task['name']} ({task['channel']}, {task['segment']})"
        print(label)

        # Generate AI direction + SL/PH
        description = ""
        if not args.skip_ai and task["channel"] == "email":
            ai_text = generate_direction_and_slph(task)
            if ai_text:
                description = ai_text
                print(f"  ✓ AI direction generated")
            else:
                print(f"  ⚠ AI generation failed, creating without direction")
        elif task["channel"] == "push":
            description = f"Push notification for {task['prefix']} audience.\nContent: {task['topic']}"

        description += f"\n\n[Auto-created: HAV {task['prefix']} calendar fill 2/26–3/31]"

        gid = create_task(task, description, dry_run=args.dry_run)
        if gid:
            created += 1
            if not args.dry_run:
                print(f"  ✓ Created: {gid}")
        else:
            failed += 1
            print(f"  ✗ Failed")

        # Small delay to avoid rate limits
        if not args.dry_run:
            time.sleep(0.5)

    print(f"\nSummary: {created} created, {failed} failed")
    if args.dry_run:
        print("(dry run — no changes made)")


if __name__ == "__main__":
    main()
