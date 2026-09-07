#!/usr/bin/env python3
"""Regenerate AI descriptions for all HAV 2/26–3/31 calendar tasks with shorter prompt."""

import os, sys, time, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"

FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_CATEGORY = "1207522425689885"
FIELD_SEGMENT = "1211927654349290"
FIELD_AUDIENCE = "1207522425689896"

BRAND_HAVENLY = "1207522425689881"
STATUS_AWAITING_CREATIVE = "1209982215610994"
CHANNEL_EMAIL_GID = "1207562370794989"
CHANNEL_PUSH_GID = "1207562370794991"


def asana_headers():
    return {
        "Authorization": f"Bearer {os.environ['ASANA_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def asana_get(endpoint, params=None):
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=asana_headers(), params=params)
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {wait}s...")
        time.sleep(wait)
        resp = requests.get(url, headers=asana_headers(), params=params)
    if resp.status_code != 200:
        print(f"  Error {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json().get("data")


def asana_update(task_gid, updates):
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


def get_enum_gid(task, field_gid):
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid and cf.get("enum_value"):
            return cf["enum_value"].get("gid")
    return None


def get_enum_name(task, field_gid):
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid and cf.get("enum_value"):
            return cf["enum_value"].get("name")
    return None


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

    seg_desc = "Full subscriber list (biggest sends, most compelling content)" if segment == "full_file" else "Engaged subscribers (more targeted, can be softer content)"

    prompt = f"""Write email creative direction and subject line options for this Havenly email.

AUDIENCE: {prefix} — {audience_desc}
EMAIL TOPIC: {name}
CATEGORY: {category}
SEGMENT: {seg_desc}

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
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"    AI error {resp.status_code}")
            return None
        text = resp.json()["content"][0]["text"].strip()
        text = text.replace("\\n", "\n")  # Haiku sometimes outputs literal \n instead of newlines
        return text
    except Exception as e:
        print(f"    AI exception: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Find all HAV Awaiting Creative tasks due 2/26–3/31
    params = {
        "projects.any": ASANA_PROJECT_GID,
        f"custom_fields.{FIELD_BRAND}.value": BRAND_HAVENLY,
        f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_AWAITING_CREATIVE,
        "due_on.after": "2026-02-25",
        "due_on.before": "2026-04-01",
        "completed": "false",
        "opt_fields": "name,due_on,notes,custom_fields,custom_fields.gid,custom_fields.enum_value,custom_fields.enum_value.gid,custom_fields.enum_value.name",
        "limit": 100,
        "sort_by": "due_date",
        "sort_ascending": "true",
    }

    print("Fetching HAV tasks (2/26–3/31, Awaiting Creative)...", flush=True)
    tasks = asana_get(f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search", params=params)
    if not tasks:
        print("No tasks found.")
        return

    print(f"Found {len(tasks)} total tasks, filtering to auto-created...", flush=True)
    # Filter to only our auto-created tasks
    calendar_tasks = [t for t in tasks if "[Auto-created: HAV" in (t.get("notes") or "")]
    print(f"Found {len(calendar_tasks)} calendar tasks.\n", flush=True)

    updated = 0
    failed = 0

    for i, task in enumerate(calendar_tasks, 1):
        gid = task["gid"]
        name = task["name"]
        due = task.get("due_on", "")

        channel_gid = get_enum_gid(task, FIELD_CHANNEL)
        is_email = channel_gid == CHANNEL_EMAIL_GID
        is_push = channel_gid == CHANNEL_PUSH_GID
        channel = "email" if is_email else "push" if is_push else "?"

        prefix = name.split(":")[0].strip() if ":" in name else "?"
        topic = name.split(": ", 1)[1] if ": " in name else name

        audience_gid = get_enum_gid(task, FIELD_AUDIENCE)
        audience = "pre_converted" if audience_gid == "1207522425689897" else "customers"

        category = get_enum_name(task, FIELD_CATEGORY) or "editorial"
        segment_gid = get_enum_gid(task, FIELD_SEGMENT)
        segment = "full_file" if segment_gid == "1211927654349291" else "engaged_file"

        print(f"[{i}/{len(calendar_tasks)}] {due} | {name} ({channel})")

        if is_email:
            direction = generate_direction(topic, prefix, audience, category, segment)
            if direction:
                new_notes = direction + "\n\n[Auto-created: HAV calendar fill 2/26–3/31]"
                print(f"    ✓ AI direction generated")
            else:
                print(f"    ⚠ AI failed, skipping")
                failed += 1
                continue
        elif is_push:
            new_notes = f"Push notification for {prefix} audience.\nContent: {topic}\n\n[Auto-created: HAV calendar fill 2/26–3/31]"
        else:
            print(f"    ⚠ Unknown channel, skipping")
            failed += 1
            continue

        if args.dry_run:
            print(f"    [DRY RUN] Would update description")
            updated += 1
            continue

        ok = asana_update(gid, {"notes": new_notes})
        if ok:
            print(f"    ✓ Updated")
            updated += 1
        else:
            failed += 1
        time.sleep(0.5)

    print(f"\nSummary: {updated} updated, {failed} failed")
    if args.dry_run:
        print("(dry run — no changes made)")


if __name__ == "__main__":
    main()
