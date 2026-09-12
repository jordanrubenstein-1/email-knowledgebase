# TI SMS Campaign Builder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build reusable infrastructure to create The Inside (TI) SMS campaigns in Klaviyo from Asana tasks marked "Ready to Code", wired into the existing ngrok webhook server so TI SMS tasks are handled automatically alongside Braze SMS/push tasks for other brands.

**Architecture:** (1) Extend `KlaviyoClient` with write methods. (2) Create `scripts/create_klaviyo_sms.py` — resolves link from Asana `HeroImage/Other CTA Link(s)` field, falls back to a keyword→URL map, creates Draft campaign + message. (3) Wire into `webhook_server.py` so `brand=TI + channel=SMS` routes to the Klaviyo builder instead of Braze `orchestrate()`. No scheduling — human schedules in Klaviyo UI.

**Tech Stack:** Python 3, `requests`, `python-dotenv`, Klaviyo REST API v2024-10-15, Asana REST API v1.0, FastAPI (existing webhook server)

---

## Key Constants

```python
# Asana (from create_braze_campaigns.py)
ASANA_BASE_URL           = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID        = "1207522423363072"
ASANA_WORKSPACE_GID      = "5257710284167"
FIELD_BRAND              = "1207522425689880"
FIELD_CHANNEL            = "1207562370794988"
FIELD_TASK_STATUS        = "1209982215610993"
FIELD_SEGMENT            = "1211927654349290"
FIELD_SEND_TIME          = "1212524397761931"
FIELD_BRAZE_LINK         = "1210710306792280"   # "Braze Campaign Link" — write Klaviyo URL here
FIELD_BRAZE_CAMPAIGN_ID  = "1210955430688137"
FIELD_HERO_CTA_LINK      = "1209982221146582"   # "HeroImage/Other CTA Link(s)"
STATUS_READY_TO_CODE     = "1209995669275789"

# Klaviyo (from klaviyo_client.py)
KLAVIYO_BASE_URL         = "https://a.klaviyo.com/api"
KLAVIYO_API_VERSION      = "2024-10-15"
```

---

## Task 1: Add `find_list_or_segment_by_name` to `KlaviyoClient`

**Files:**
- Modify: `scripts/utils/klaviyo_client.py`

**Step 1: Add `_segment_cache` to `__init__`**

Read lines 100–106 of `scripts/utils/klaviyo_client.py` to locate the `__init__` method. After the existing cache attr lines (`self._metric_cache`, `self._placed_order_metric_id`), add:

```python
self._segment_cache: dict[str, str] = {}  # name (lowercased) -> list/segment ID
```

**Step 2: Append method to the class (after line 700)**

```python
# ------------------------------------------------------------------
# Lists / Segments (read)
# ------------------------------------------------------------------

def find_list_or_segment_by_name(self, name: str) -> str | None:
    """Return the Klaviyo ID for a list or segment matching `name` (case-insensitive).

    Searches /api/lists/ first, then /api/segments/. Result is cached.
    Returns None if not found.
    """
    key = name.lower()
    if key in self._segment_cache:
        return self._segment_cache[key]

    for endpoint, field_key in (("/lists/", "list"), ("/segments/", "segment")):
        items = self._paginate(
            endpoint,
            params={f"fields[{field_key}]": "name"},
        )
        for item in items:
            item_name = (item.get("attributes") or {}).get("name", "")
            if item_name.lower() == key:
                self._segment_cache[key] = item["id"]
                return item["id"]

    return None
```

**Step 3: Verify**

```bash
cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase
python -c "from scripts.utils.klaviyo_client import KlaviyoClient; print(hasattr(KlaviyoClient, 'find_list_or_segment_by_name'))"
```
Expected: `True`

**Step 4: Commit**

```bash
git add scripts/utils/klaviyo_client.py
git commit -m "feat(klaviyo): add find_list_or_segment_by_name"
```

---

## Task 2: Add write methods to `KlaviyoClient`

**Files:**
- Modify: `scripts/utils/klaviyo_client.py`

**Step 1: Append three write methods after `find_list_or_segment_by_name`**

```python
# ------------------------------------------------------------------
# Campaigns (write)
# ------------------------------------------------------------------

def create_campaign(self, name: str, channel: str, included_ids: list[str]) -> str | None:
    """Create a Draft campaign with no send strategy (unscheduled).

    Args:
        name: Campaign name.
        channel: "sms" or "email".
        included_ids: List of Klaviyo list/segment IDs to include in the audience.

    Returns:
        New campaign ID string, or None on failure.
    """
    body = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": name,
                "audiences": {
                    "included": included_ids,
                    "excluded": [],
                },
                "campaign-messages": {
                    "data": [
                        {
                            "type": "campaign-message",
                            "attributes": {
                                "channel": channel,
                                "label": name,
                            },
                        }
                    ]
                },
            },
        }
    }
    result = self._post("/campaigns/", body)
    if not result:
        return None
    return (result.get("data") or {}).get("id")

def update_campaign_message_body(self, message_id: str, body_text: str) -> bool:
    """PATCH the SMS body of an existing campaign message.

    Returns True on success.
    """
    import requests as _req
    url = f"{KLAVIYO_BASE_URL}/campaign-messages/{message_id}/"
    payload = {
        "data": {
            "type": "campaign-message",
            "id": message_id,
            "attributes": {
                "content": {
                    "body": body_text,
                },
            },
        }
    }
    self._rate_limiter.acquire()
    resp = _req.patch(url, headers=self._headers(), json=payload, timeout=30)
    if resp.status_code not in (200, 204):
        print(f"  [klaviyo] PATCH campaign-message {message_id}: {resp.status_code} {resp.text[:300]}")
        return False
    return True
```

**Step 2: Verify**

```bash
cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase
python -c "
from scripts.utils.klaviyo_client import KlaviyoClient
methods = [m for m in dir(KlaviyoClient) if 'campaign' in m.lower() or 'segment' in m.lower()]
print(methods)
"
```
Expected: includes `create_campaign`, `update_campaign_message_body`, `find_list_or_segment_by_name`

**Step 3: Commit**

```bash
git add scripts/utils/klaviyo_client.py
git commit -m "feat(klaviyo): add create_campaign and update_campaign_message_body write methods"
```

---

## Task 3: Create `scripts/create_klaviyo_sms.py`

**Files:**
- Create: `scripts/create_klaviyo_sms.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
Create a Klaviyo SMS campaign (Draft, unscheduled) from an Asana task.

Link resolution order:
  1. --link CLI arg (manual override)
  2. Asana "HeroImage/Other CTA Link(s)" custom field (FIELD_HERO_CTA_LINK)
  3. Keyword-based default from TI_DEFAULT_LINKS (matched against campaign name)
  4. If none match: leave placeholder and warn

Usage:
    # Asana-driven (primary):
    uv run python scripts/create_klaviyo_sms.py \\
      --brand TI \\
      --asana-gid 1213758018415441 \\
      --link https://www.theinside.com/collections/new-arrivals

    # Manual override:
    uv run python scripts/create_klaviyo_sms.py \\
      --brand TI \\
      --name "SMS: Spring Arrivals" \\
      --body "The Inside: Spring just dropped..." \\
      --segment "Master SMS Segment"

    # Dry-run:
    uv run python scripts/create_klaviyo_sms.py --brand TI --asana-gid GID --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from utils.klaviyo_client import KlaviyoClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL          = "https://app.asana.com/api/1.0"
KLAVIYO_DASHBOARD_BASE  = "https://www.klaviyo.com/campaign"
KLAVIYO_BRANDS          = {"TI"}

# Asana custom field GIDs
FIELD_BRAZE_LINK        = "1210710306792280"   # "Braze Campaign Link"
FIELD_BRAZE_CAMPAIGN_ID = "1210955430688137"
FIELD_HERO_CTA_LINK     = "1209982221146582"   # "HeroImage/Other CTA Link(s)"

# Default campaign name segment → URL (first keyword match in lowercased campaign name wins)
TI_DEFAULT_LINKS: list[tuple[str, str]] = [
    ("new arrivals",        "https://www.theinside.com/collections/new-arrivals"),
    ("sale",                "https://www.theinside.com/collections/sale"),
    ("outdoor",             "https://www.theinside.com/collections/outdoor-furniture"),
    ("bed",                 "https://www.theinside.com/collections/bedding"),
    ("pillow",              "https://www.theinside.com/collections/pillows"),
    ("curtain",             "https://www.theinside.com/collections/window-treatments"),
    ("sofa",                "https://www.theinside.com/collections/sofas"),
    ("chair",               "https://www.theinside.com/collections/chairs"),
    ("rug",                 "https://www.theinside.com/collections/rugs"),
]

# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def _asana_headers() -> dict[str, str]:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def fetch_asana_task(task_gid: str) -> dict | None:
    """Fetch a single Asana task with name, notes, due_on, and custom fields."""
    resp = requests.get(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        params={
            "opt_fields": (
                "name,notes,due_on,"
                "custom_fields,custom_fields.gid,custom_fields.name,"
                "custom_fields.display_value,custom_fields.text_value,"
                "custom_fields.enum_value,custom_fields.enum_value.name,"
                "custom_fields.type"
            )
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error fetching Asana task {task_gid}: {resp.status_code} {resp.text[:200]}",
              file=sys.stderr)
        return None
    return resp.json().get("data")


def get_text_field(task: dict, field_gid: str) -> str | None:
    """Extract a text custom field value from a task by field GID."""
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            return cf.get("text_value") or cf.get("display_value") or None
    return None


def update_asana_task_link(task_gid: str, klaviyo_url: str, dry_run: bool = False) -> bool:
    """Write the Klaviyo campaign URL into the Asana 'Braze Campaign Link' field."""
    if dry_run:
        print(f"  [DRY RUN] Would update Asana task {task_gid}: Braze Campaign Link = {klaviyo_url}")
        return True
    payload = {
        "data": {
            "custom_fields": {
                FIELD_BRAZE_LINK: klaviyo_url,
            }
        }
    }
    resp = requests.put(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  Warning: Asana update failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Copy parsing
# ---------------------------------------------------------------------------

def extract_sms_body(notes: str) -> str:
    """Return the primary SMS copy from Asana task notes.

    Convention: the first non-empty paragraph (everything before the first
    blank line). The creative-direction block below the separator is ignored.
    """
    lines = notes.strip().splitlines()
    body_lines: list[str] = []
    for line in lines:
        if line.strip() == "" and body_lines:
            break
        if line.strip():
            body_lines.append(line.strip())
    return " ".join(body_lines)


def apply_link(body: str, link: str) -> str:
    """Replace arrow+placeholder patterns with ': <link>'.

    Rules:
      - No space before the colon (colon attaches directly to the last word)
      - One space between colon and URL

    Handles: '→ LINK', '→ [link]', bare 'LINK', bare '[link]'
    """
    # Arrow + placeholder (with optional surrounding spaces)
    body = re.sub(
        r"\s*→\s*(\[?link\]?|LINK|<link>)",
        f": {link}",
        body,
        flags=re.IGNORECASE,
    )
    # Bare placeholder without arrow
    body = re.sub(r"\b(LINK|\[link\]|<link>)\b", link, body, flags=re.IGNORECASE)
    return body


def resolve_link(
    cli_link: str | None,
    asana_task: dict | None,
    campaign_name: str,
) -> str | None:
    """Resolve the destination URL using the priority chain:
      1. --link CLI arg
      2. Asana HeroImage/Other CTA Link(s) field
      3. Keyword match against campaign name from TI_DEFAULT_LINKS
      4. None (caller warns)
    """
    if cli_link:
        return cli_link

    if asana_task:
        field_link = get_text_field(asana_task, FIELD_HERO_CTA_LINK)
        if field_link and field_link.startswith("http"):
            print(f"  Using link from Asana HeroImage field: {field_link}")
            return field_link

    name_lower = campaign_name.lower()
    for keyword, url in TI_DEFAULT_LINKS:
        if keyword in name_lower:
            print(f"  Using default link for keyword '{keyword}': {url}")
            return url

    return None


# ---------------------------------------------------------------------------
# Klaviyo client factory
# ---------------------------------------------------------------------------

def init_klaviyo_client(brand: str) -> KlaviyoClient:
    brand = brand.upper()
    if brand not in KLAVIYO_BRANDS:
        print(f"Error: '{brand}' is not a supported Klaviyo SMS brand. Supported: {KLAVIYO_BRANDS}",
              file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        print(f"Error: KLAVIYO_API_KEY_{brand} not set in .env", file=sys.stderr)
        sys.exit(1)
    return KlaviyoClient(api_key=api_key, brand=brand)


# ---------------------------------------------------------------------------
# Core builder — importable for use from webhook server
# ---------------------------------------------------------------------------

def build_klaviyo_sms_campaign(
    brand: str,
    asana_gid: str | None = None,
    link: str | None = None,
    name: str | None = None,
    body: str | None = None,
    segment: str = "Master SMS Segment",
    dry_run: bool = False,
) -> str | None:
    """Create a Draft Klaviyo SMS campaign. Returns the Klaviyo campaign URL or None."""
    asana_task = None

    if asana_gid:
        print(f"Fetching Asana task {asana_gid}...")
        asana_task = fetch_asana_task(asana_gid)
        if not asana_task:
            print("Error: could not fetch Asana task.", file=sys.stderr)
            return None
        if not name:
            name = asana_task["name"]
        if not body:
            notes = asana_task.get("notes", "")
            body = extract_sms_body(notes)
            if not body:
                print("Error: could not extract SMS body from task notes.", file=sys.stderr)
                return None

    if not name or not body:
        print("Error: --name and --body are required when --asana-gid is not provided.",
              file=sys.stderr)
        return None

    # Resolve link
    resolved_link = resolve_link(link, asana_task, name)
    if resolved_link:
        body = apply_link(body, resolved_link)
    elif re.search(r"\b(LINK|\[link\]|<link>)", body, re.IGNORECASE) or "→" in body:
        print(
            f"Warning: body contains a link placeholder but no URL could be resolved.\n"
            f"  Add a URL to the Asana 'HeroImage/Other CTA Link(s)' field, pass --link,\n"
            f"  or add a keyword entry to TI_DEFAULT_LINKS in create_klaviyo_sms.py."
        )

    print(f"\nCampaign name  : {name}")
    print(f"SMS body       : {body}")
    print(f"Char count     : {len(body)}")
    print(f"Segment        : {segment}")

    if dry_run:
        print("\n[DRY RUN] No Klaviyo API calls made.")
        if asana_gid:
            update_asana_task_link(asana_gid, "https://www.klaviyo.com/campaign/DRY_RUN/overview",
                                   dry_run=True)
        return None

    client = init_klaviyo_client(brand)

    print(f"\nLooking up segment '{segment}'...")
    segment_id = client.find_list_or_segment_by_name(segment)
    if not segment_id:
        print(f"Error: segment '{segment}' not found in Klaviyo for brand {brand}.", file=sys.stderr)
        return None
    print(f"  Found: {segment_id}")

    print(f"Creating campaign '{name}'...")
    campaign_id = client.create_campaign(name=name, channel="sms", included_ids=[segment_id])
    if not campaign_id:
        print("Error: campaign creation failed.", file=sys.stderr)
        return None
    print(f"  Campaign ID: {campaign_id}")

    print("Fetching auto-created campaign message...")
    messages = client.get_campaign_messages(campaign_id)
    if not messages:
        print("Error: could not retrieve campaign messages.", file=sys.stderr)
        return None
    message_id = messages[0]["id"]
    print(f"  Message ID: {message_id}")

    print("Setting SMS body...")
    if not client.update_campaign_message_body(message_id, body):
        print("Error: failed to update message body.", file=sys.stderr)
        return None

    klaviyo_url = f"{KLAVIYO_DASHBOARD_BASE}/{campaign_id}/overview"
    print(f"\n✓ Campaign ready (Draft — unscheduled):")
    print(f"  Name : {name}")
    print(f"  Body : {body}")
    print(f"  URL  : {klaviyo_url}")

    if asana_gid:
        print(f"\nUpdating Asana task {asana_gid}...")
        update_asana_task_link(asana_gid, klaviyo_url)
        print("  Done.")

    return klaviyo_url


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Klaviyo SMS campaign (Draft) from an Asana task."
    )
    parser.add_argument("--brand", required=True, help="Brand code (TI)")
    parser.add_argument("--asana-gid", help="Asana task GID to pull name + copy from")
    parser.add_argument("--link", help="Destination URL (overrides Asana field and default map)")
    parser.add_argument("--name", help="Campaign name (overrides Asana task name)")
    parser.add_argument("--body", help="SMS body text (overrides Asana notes)")
    parser.add_argument("--segment", default="Master SMS Segment",
                        help="Klaviyo list/segment name (default: Master SMS Segment)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without making API calls")
    args = parser.parse_args()

    if not args.asana_gid and not (args.name and args.body):
        parser.error("Provide --asana-gid OR both --name and --body")

    build_klaviyo_sms_campaign(
        brand=args.brand,
        asana_gid=args.asana_gid,
        link=args.link,
        name=args.name,
        body=args.body,
        segment=args.segment,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

```bash
cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase
python -m py_compile scripts/create_klaviyo_sms.py && echo "OK"
```
Expected: `OK`

**Step 3: Dry-run smoke test**

```bash
uv run python scripts/create_klaviyo_sms.py \
  --brand TI \
  --asana-gid 1213758018415441 \
  --link https://www.theinside.com/collections/new-arrivals \
  --dry-run
```

Check:
- Campaign name: `SMS: Spring Arrivals`
- Body has `→ LINK` replaced with `: https://www.theinside.com/collections/new-arrivals` (no space before colon, one space after)
- `[DRY RUN]` line at end
- Character count printed

**Step 4: Commit**

```bash
git add scripts/create_klaviyo_sms.py
git commit -m "feat: add create_klaviyo_sms.py — TI SMS Klaviyo campaign builder"
```

---

## Task 4: Live run — create "SMS: Spring Arrivals"

> Run only after Tasks 1–3 are committed and dry-run output is correct.

**Step 1: Run**

```bash
uv run python scripts/create_klaviyo_sms.py \
  --brand TI \
  --asana-gid 1213758018415441 \
  --link https://www.theinside.com/collections/new-arrivals
```

**Step 2: Verify in Klaviyo**

Open the printed URL. Confirm:
- Name: `SMS: Spring Arrivals`
- Status: Draft (unscheduled)
- SMS body correct (no placeholder, correct URL format)
- Audience: Master SMS Segment (~7.4K)

**Step 3: Verify in Asana**

Open task GID 1213758018415441. Confirm `Braze Campaign Link` field now contains the Klaviyo URL.

**Step 4: Commit any fixes if needed**

---

## Task 5: Wire into `webhook_server.py`

**Files:**
- Modify: `scripts/braze_automation/webhook_server.py`

**Step 1: Understand the current dispatch block**

Read the block around line 513 in `webhook_server.py`. It currently looks like:

```python
if channel_gid == SMS_CHANNEL_GID:
    logger.info(...)
    await orchestrate(
        brand_code=brand_code,
        dry_run=False,
        headless=True,
        single_task_gid=task_gid,
    )
else:  # PUSH
    await _dispatch_push_build(task_gid, raw_task)
```

**Step 2: Add `_dispatch_klaviyo_sms_build` function**

Add this function near the other `_dispatch_*` functions (before the SMS dispatch block):

```python
async def _dispatch_klaviyo_sms_build(task_gid: str) -> None:
    """Build a Klaviyo SMS campaign for a TI task — runs in a thread to avoid blocking."""
    import asyncio
    from create_klaviyo_sms import build_klaviyo_sms_campaign

    logger.info(f"Dispatching Klaviyo SMS build for TI task {task_gid}")

    def _run() -> None:
        build_klaviyo_sms_campaign(
            brand="TI",
            asana_gid=task_gid,
            dry_run=False,
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)
```

**Step 3: Add the TI branch to the SMS dispatch block**

Change:

```python
if channel_gid == SMS_CHANNEL_GID:
    logger.info(
        f"Eligible SMS task detected: [{brand_code}] {task_name} (gid={task_gid})\n"
        f"  Dispatching campaign build..."
    )
    await orchestrate(
        brand_code=brand_code,
        dry_run=False,
        headless=True,
        single_task_gid=task_gid,
    )
```

To:

```python
if channel_gid == SMS_CHANNEL_GID:
    logger.info(
        f"Eligible SMS task detected: [{brand_code}] {task_name} (gid={task_gid})\n"
        f"  Dispatching campaign build..."
    )
    if brand_code == "TI":
        await _dispatch_klaviyo_sms_build(task_gid)
    else:
        await orchestrate(
            brand_code=brand_code,
            dry_run=False,
            headless=True,
            single_task_gid=task_gid,
        )
```

**Step 4: Verify syntax**

```bash
cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase
python -m py_compile scripts/braze_automation/webhook_server.py && echo "OK"
```
Expected: `OK`

**Step 5: Commit**

```bash
git add scripts/braze_automation/webhook_server.py
git commit -m "feat(webhook): route TI SMS tasks to Klaviyo builder instead of Braze"
```

---

## Notes

- **Scheduling**: done manually in Klaviyo UI — the script intentionally leaves status = Draft.
- **`get_campaign_messages` for SMS**: when Klaviyo creates an SMS campaign, it auto-creates one message. The existing `get_campaign_messages()` method requests `?include=template` — SMS messages have no template, so `included` will be empty, but `data[0].id` will still be present. We use that ID for the PATCH.
- **`update_campaign_message_body`**: uses `PATCH`, not `POST`. The `_post` helper only handles POST, so this method calls `requests.patch` directly — same pattern as other one-off HTTP verbs in this codebase.
- **`create_klaviyo_sms.py` is in `scripts/` not `scripts/braze_automation/`**: the webhook server adds `scripts/` to `sys.path`, so `from create_klaviyo_sms import build_klaviyo_sms_campaign` resolves correctly.
- **TI_DEFAULT_LINKS**: ordered list, first keyword match wins. Extend this list as new TI campaign types come in.
- **Link resolution priority**: CLI `--link` → Asana `HeroImage/Other CTA Link(s)` field (GID `1209982221146582`) → keyword match → warn and leave placeholder.
