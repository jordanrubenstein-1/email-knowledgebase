#!/usr/bin/env python3
"""
Asana Webhook Server — receives Asana task events and dispatches campaign builds.

Listens on port 8765. Handles:
  - Asana handshake (X-Hook-Secret echo)
  - HMAC-SHA256 signature verification
  - Event routing: task changed → Status=Ready to Code →
      Channel=SMS  → orchestrate_sms
      Channel=Push → build_push_campaign
      Channel=Email + Ref Braze Campaign filled + TI brand → build_klaviyo_designed_campaign
      Channel=Email + Ref Braze Campaign filled + Braze brand → build_designed_campaign
      Channel=Email + Type=Plain-Text or name ends _PT → build_pt_campaign / create_klaviyo_email

The Asana webhook flow:
  1. You register a webhook pointing at your ngrok URL
  2. Asana immediately POSTs a handshake with X-Hook-Secret header
  3. This server echoes X-Hook-Secret back and saves the secret
  4. All future deliveries include X-Hook-Signature: sha256=<hmac>
  5. This server verifies the signature before processing

Usage:
    # Start via convenience script (recommended — also starts ngrok)
    bash scripts/braze_automation/start_webhook_service.sh

    # Or start standalone
    uv run uvicorn scripts.braze_automation.webhook_server:app --host 0.0.0.0 --port 8765

    # With auto-reload for development
    uv run uvicorn scripts.braze_automation.webhook_server:app --host 0.0.0.0 --port 8765 --reload
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Set

import yaml
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — mirror orchestrate_sms.py so imports resolve correctly
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "braze_automation"))

load_dotenv(PROJECT_ROOT / ".env")

_SESSION_ERROR_KEYWORDS = ("could not navigate", "login", "session", "auth", "401", "403")

from build_sms_campaign import (  # noqa: E402
    fetch_task_by_gid,
    _asana_request,
    _get_enum_value_gid,
    _get_enum_value_name,
    _get_text_value,
    FIELD_BRAND,
    FIELD_BRAZE_LINK,
    FIELD_CHANNEL,
    FIELD_TASK_STATUS,
    STATUS_READY_TO_CODE,
    STATUS_READY_FOR_QA,
    CHANNEL_OPTIONS,
    CHANNEL_GID_TO_NAME,
    BRAND_GID_TO_CODE,
)
from orchestrate_sms import orchestrate  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AI Feedback log — captures "AI feedback: ..." comments from Asana stories
# and immediately posts them to the AI Build Feedback Asana project.
# ---------------------------------------------------------------------------
AI_FEEDBACK_LOG = PROJECT_ROOT / "data" / "ai_feedback_log.yaml"
_feedback_log_lock = threading.Lock()

FEEDBACK_PROJECT_GID = os.environ.get("ASANA_FEEDBACK_PROJECT_GID", "").strip()
MASTER_PROJECT_GID = "1207522423363072"
ASANA_WORKSPACE_GID = "5257710284167"

# Marker posted as an Asana comment whenever the QA automation attempts a run.
# The polling fallback checks for this text to skip already-processed tasks.
QA_AUTOMATION_MARKER = "🤖 QA automation complete."

# How often the polling fallback scans for missed Ready-for-QA tasks (seconds).
QA_POLL_INTERVAL = 5 * 60
_feedback_section_new_gid: Optional[str] = None


def _load_feedback_log() -> dict:
    if not AI_FEEDBACK_LOG.exists():
        return {"entries": []}
    with open(AI_FEEDBACK_LOG) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("entries", [])
    return data


def _save_feedback_log(data: dict) -> None:
    with open(AI_FEEDBACK_LOG, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _append_feedback_entry(entry: dict) -> None:
    """Thread-safe append to ai_feedback_log.yaml. Deduplicates by story_gid."""
    with _feedback_log_lock:
        data = _load_feedback_log()
        existing_story_gids = {e.get("story_gid") for e in data["entries"]}
        if entry.get("story_gid") in existing_story_gids:
            logger.debug(f"Story {entry['story_gid']} already in feedback log — skipping")
            return
        data["entries"].append(entry)
        _save_feedback_log(data)
        logger.info(f"[AI Feedback] Logged from {entry.get('commenter', '?')}: {entry['raw_comment'][:80]}")


def _get_new_section_gid() -> Optional[str]:
    """Lazy-load and cache the 'New' section GID from the AI Build Feedback project."""
    global _feedback_section_new_gid
    if _feedback_section_new_gid:
        return _feedback_section_new_gid
    if not FEEDBACK_PROJECT_GID:
        return None
    sections = _asana_request(
        "GET", f"projects/{FEEDBACK_PROJECT_GID}/sections",
        params={"opt_fields": "gid,name"},
    )
    if not sections:
        return None
    for s in sections:
        if s.get("name") == "New":
            _feedback_section_new_gid = s["gid"]
            return _feedback_section_new_gid
    return None


def _create_feedback_asana_task(entry: dict) -> Optional[str]:
    """Create a task in the AI Build Feedback project. Returns task GID or None."""
    if not FEEDBACK_PROJECT_GID:
        logger.warning("[AI Feedback] ASANA_FEEDBACK_PROJECT_GID not set — cannot post to Asana")
        return None

    brand = entry.get("brand") or "?"
    channel = (entry.get("channel") or "?").upper()
    comment = entry["raw_comment"]

    # Strip "AI feedback:" / "AI feedback -" prefix for the title
    title_body = comment
    for prefix in ("AI feedback:", "AI feedback -"):
        if comment.lower().startswith(prefix.lower()):
            title_body = comment[len(prefix):].strip()
            break
    if len(title_body) > 80:
        title_body = title_body[:80].rsplit(" ", 1)[0] + "…"
    title = f"[{brand} · {channel}] {title_body}"

    notes = "\n".join([
        "── What the producer changed ──",
        comment,
        "",
        "── Original Campaign Task ──",
        f"https://app.asana.com/0/{MASTER_PROJECT_GID}/{entry['task_gid']}",
        "",
        f"Captured: {entry.get('captured_at', '')}",
        f"Commenter: {entry.get('commenter', '?')}",
        f"Log ID: {entry.get('id', '?')}",
    ])

    task = _asana_request("POST", "tasks", json_data={
        "data": {"name": title, "notes": notes, "projects": [FEEDBACK_PROJECT_GID]},
    })
    if not task:
        return None

    task_gid = task["gid"]
    section_gid = _get_new_section_gid()
    if section_gid:
        _asana_request(
            "POST", f"sections/{section_gid}/addTask",
            json_data={"data": {"task": task_gid}},
        )
    return task_gid


def _post_feedback_entry(entry: dict) -> None:
    """Create Asana feedback task and update the log entry status. Thread-safe."""
    task_gid = _create_feedback_asana_task(entry)
    if not task_gid:
        logger.error(f"[AI Feedback] Failed to create Asana task for entry {entry['id']}")
        return

    logger.info(f"[AI Feedback] ✓ Posted to Asana — task {task_gid}")

    with _feedback_log_lock:
        data = _load_feedback_log()
        for e in data["entries"]:
            if e.get("id") == entry["id"]:
                e["status"] = "posted_to_asana"
                e["asana_feedback_task_gid"] = task_gid
                break
        _save_feedback_log(data)


def _fetch_story_sync(story_gid: str) -> Optional[dict]:
    """Fetch a single Asana story (blocking)."""
    return _asana_request(
        "GET",
        f"stories/{story_gid}",
        params={"opt_fields": "gid,type,text,created_by.name,created_at"},
    )


async def _handle_story_event(story_gid: str, task_gid: str) -> None:
    """
    Triggered when a story (comment) is added to any project task.
    Checks for "AI feedback" anywhere in the comment; if found, logs to ai_feedback_log.yaml.
    """
    story = await asyncio.to_thread(_fetch_story_sync, story_gid)
    if not story:
        return

    if story.get("type") != "comment":
        return

    text = (story.get("text") or "").strip()
    if "ai feedback" not in text.lower():
        return

    # Feedback comment found — fetch task details for metadata
    raw_task = await asyncio.to_thread(fetch_task_by_gid, task_gid)
    if not raw_task:
        logger.warning(f"[AI Feedback] Could not fetch task {task_gid} — logging with partial metadata")
        brand_code = None
        channel_name = None
        task_name = task_gid
    else:
        brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
        brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
        channel_gid = _get_enum_value_gid(raw_task, FIELD_CHANNEL)
        channel_name = CHANNEL_GID_TO_NAME.get(channel_gid or "")
        task_name = raw_task.get("name", task_gid)

    commenter = story.get("created_by", {}).get("name", "Unknown")

    entry = {
        "id": str(uuid.uuid4())[:8],
        "story_gid": story_gid,
        "source": "webhook",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "task_gid": task_gid,
        "task_name": task_name,
        "brand": brand_code,
        "channel": channel_name,
        "commenter": commenter,
        "raw_comment": text,
        "status": "unprocessed",
        "asana_feedback_task_gid": None,
    }

    await asyncio.to_thread(_append_feedback_entry, entry)
    await asyncio.to_thread(_post_feedback_entry, entry)


# ---------------------------------------------------------------------------
# Webhook secret management
#
# The secret arrives via the Asana handshake (X-Hook-Secret header on the
# first POST after webhook registration). We save it to .webhook_secret so it
# survives server restarts without user action. ASANA_WEBHOOK_SECRET in .env
# is a fallback only — the file always takes priority because _save_secret()
# updates it on every handshake, keeping it fresher than a manually set env var.
# ---------------------------------------------------------------------------
SECRET_FILE = Path(__file__).parent / ".webhook_secret"

# In-memory secret — populated at startup and updated during handshake
_webhook_secret: str = ""


def _load_secret() -> str:
    """Load secret from .webhook_secret file, then env var fallback."""
    if SECRET_FILE.exists():
        secret = SECRET_FILE.read_text().strip()
        if secret:
            logger.info(f"Loaded webhook secret from {SECRET_FILE}")
            return secret
    secret = os.environ.get("ASANA_WEBHOOK_SECRET", "").strip()
    if secret:
        return secret
    return ""


def _save_secret(secret: str) -> None:
    """Persist secret to .webhook_secret file and update in-memory value."""
    global _webhook_secret
    _webhook_secret = secret
    SECRET_FILE.write_text(secret)
    logger.info(
        "\n" + "=" * 60 + "\n"
        "WEBHOOK SECRET RECEIVED AND SAVED\n"
        + "=" * 60 + "\n"
        f"Secret stored in: {SECRET_FILE}\n"
        f"To make it permanent, add to .env:\n"
        f"  ASANA_WEBHOOK_SECRET={secret}\n"
        + "=" * 60
    )


# ---------------------------------------------------------------------------
# In-flight deduplication + FIFO build queue
#
# _processing: task GIDs currently queued or actively building.
#   Added at enqueue time; removed by the queue worker when the build finishes.
#   Prevents the same task from being enqueued twice if Asana fires a duplicate event.
#
# _build_queue: serialises all builds so only one Playwright session runs at a time.
#   The worker pulls one job at a time; later arrivals wait in FIFO order.
#
# _rtc_skipped: task GIDs that were dequeued by the Ready-to-Code poll, checked,
#   and found ineligible (wrong type, missing ref campaign, etc.).  The poll skips
#   these for RTC_SKIP_TTL seconds to prevent infinite re-queuing.  Cleared when a
#   fresh webhook event arrives for the task (status change may have made it eligible).
# ---------------------------------------------------------------------------
_processing: Set[str] = set()
_build_queue: asyncio.Queue = asyncio.Queue()
_rtc_skipped: dict[str, float] = {}   # gid → timestamp when skip expires
RTC_SKIP_TTL = 30 * 60                # 30 minutes

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Asana Webhook Server", version="1.0.0")

SMS_CHANNEL_GID = CHANNEL_OPTIONS["sms"]
PUSH_CHANNEL_GID = CHANNEL_OPTIONS["push"]
EMAIL_CHANNEL_GID = CHANNEL_OPTIONS["email"]

# Asana GID for the "Ref Braze Campaign" custom field (designed email only)
FIELD_REF_BRAZE_CAMPAIGN = "1214484659930023"

# Asana "Email Slices/Banners/Blocks Details" field — Drive folder link for design assets
FIELD_EMAIL_SLICES = "1208664127595091"

# HTML/CSS image-based designed email auto-build: per-brand first-eligible send date.
# A task on/after its brand's cutoff WITH a Drive URL routes to the from-scratch HTML/CSS
# builder; everything else falls through to the DnD duplicator (Braze) or ref-campaign
# clone (Klaviyo). See CLAUDE.md § "HTML/CSS Brand Migration".
#
# Braze brands (CZ, STF, BUR) dispatch to build_cz_designed_email (brand-parameterized);
# Klaviyo brands (TI) dispatch to build_klaviyo_designed_email. The detection below is
# generic across both — the builder split happens in _dispatch_htmlcss_designed_build.
CZ_DESIGNED_CUTOFF = "2026-05-30"
STF_DESIGNED_CUTOFF = "2026-07-20"
TI_DESIGNED_CUTOFF = "2026-07-21"
BUR_DESIGNED_CUTOFF = "2026-08-18"
HTMLCSS_DESIGNED_CUTOFFS = {
    "CZ": CZ_DESIGNED_CUTOFF,
    "STF": STF_DESIGNED_CUTOFF,
    "TI": TI_DESIGNED_CUTOFF,
    "BUR": BUR_DESIGNED_CUTOFF,
}

# Asana "Type" field — used to detect plain-text vs designed emails
FIELD_TYPE = "1207522425689987"
TYPE_PLAIN_TEXT = "1207522425689988"  # enum value: "Plain-Text"

# Braze workspace IDs — used to build campaign dashboard URLs.
# Source: BRAND_WORKSPACE_DIRECT_URL in login.py (the 24-char hex at the end of each URL).
BRAND_WORKSPACE_ID_MAP: dict[str, str] = {
    "HAV": "664223fb71bcf3005760dfc2",
    "CZ":  "666672a4d8965b005ac6c1bd",
    "BUR": "67093a1f24ebbe0065cb9c77",
    "STF": "666716b3858150005b566956",
    "ID":  "6666726b459b5e0059d7d687",
    "TI":  "666672c6459b5e0059d7d77d",
}

# The Braze campaign naming convention uses different codes than YAML/Asana for two brands.
BRAND_BRAZE_NAME_CODE: dict[str, str] = {
    "BUR": "BW", "STF": "SF",
    "HAV": "HAV", "CZ": "CZ", "ID": "ID", "TI": "TI",
}

# Tokens that carry no descriptive content and should be ignored during name matching.
_CAMPAIGN_LOOKUP_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "in", "of", "to", "for", "at", "on",
    "d", "pt", "h", "pc", "conv", "em", "sms", "push", "p", "ot",
    "hav", "cz", "id", "bur", "bw", "stf", "sf", "ti", "te",
    # Asana task names often end with " | Email" or " | SMS" as a channel suffix;
    # treat these as noise so they don't inflate task_words and hurt match ratio.
    "email", "sms",
})


def _normalize_name_words(text: str) -> frozenset[str]:
    """Split a task name or campaign description into lowercase content words."""
    tokens = re.split(r"[_\s\-]+", text.lower())
    return frozenset(t for t in tokens if len(t) >= 3 and t not in _CAMPAIGN_LOOKUP_STOP_WORDS)


def _strip_campaign_prefix(name: str, channel_code: str, date_str: str, braze_brand: str) -> str:
    """Return the description portion of a campaign name.

    Strips the leading P_{channel}_{date}_{brand}_ segment plus any optional
    design code (D/PT/H) and HAV audience code (PC/CONV) that follow it.
    """
    prefix = f"P_{channel_code}_{date_str}_{braze_brand}_".upper()
    if not name.upper().startswith(prefix):
        return name
    rest = name[len(prefix):]
    # Strip design and audience tokens (order matters: check PT before D to avoid eating "D" from "PT")
    for tok in ("PT_", "CONV_", "PC_", "D_", "H_"):
        if rest.upper().startswith(tok):
            rest = rest[len(tok):]
            break
    # HAV can have D_PC_ or D_CONV_ — strip a second audience token if present
    for tok in ("PC_", "CONV_"):
        if rest.upper().startswith(tok):
            rest = rest[len(tok):]
            break
    return rest


async def _resolve_campaign_url_via_playwright(
    brand_code: str, campaign_name: str, dashboard_base: str, workspace_id: str
) -> Optional[str]:
    """Navigate to the Braze campaigns list, search by name, and return the hex-based URL.

    The Braze API returns UUID campaign IDs which don't work in dashboard URLs.
    This function uses Playwright to search the campaigns list UI and grabs the
    href from the campaign row link, which contains the real hex ObjectID.
    """
    from playwright.async_api import async_playwright
    from login import ensure_logged_in, select_workspace, create_context_with_session

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await create_context_with_session(browser)
            page = await context.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})
            await ensure_logged_in(page)
            await select_workspace(page, brand_code)

            # Navigate to campaigns list
            campaigns_url = f"{dashboard_base}/engagement/campaigns/{workspace_id}"
            await page.goto(campaigns_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # Search for the campaign by name
            search_input = page.get_by_placeholder("Search").first
            if await search_input.count() == 0:
                search_input = page.locator("input[type='search'], input[placeholder*='earch']").first
            await search_input.fill(campaign_name)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)

            # Find the campaign row link
            rows = page.locator("tr, [role='row']")
            count = await rows.count()
            for i in range(count):
                row = rows.nth(i)
                link = row.locator("a").first
                if await link.count() == 0:
                    continue
                name = (await link.text_content() or "").strip()
                if campaign_name.lower() in name.lower() or name.lower() in campaign_name.lower():
                    href = await link.get_attribute("href")
                    if href and "/campaigns/" in href:
                        # Make absolute if relative
                        if href.startswith("/"):
                            href = f"{dashboard_base}{href}"
                        return href

            await browser.close()
    except Exception as exc:
        logger.warning(f"[QA] Playwright URL resolution failed for {campaign_name!r}: {exc}")
    return None


async def _find_braze_campaign_for_task(
    raw_task: dict, brand_code: str, channel_gid: str
) -> Optional[str]:
    """Search Braze for a campaign matching this task's date, brand, channel, and name.

    Returns a full dashboard URL if exactly one candidate clears the confidence
    threshold (≥2 overlapping content words AND ≥50% of the task's content words
    covered). Returns None if no match or multiple ambiguous matches are found.
    """
    from braze_api_client import get_all_campaigns

    due_on = (raw_task.get("due_on") or "").strip()
    task_name = (raw_task.get("name") or "").strip()
    if not due_on or not task_name:
        return None

    braze_brand = BRAND_BRAZE_NAME_CODE.get(brand_code, brand_code)
    workspace_id = BRAND_WORKSPACE_ID_MAP.get(brand_code)
    if not workspace_id:
        return None

    channel_name = CHANNEL_GID_TO_NAME.get(channel_gid, "")
    channel_code = {"email": "EM", "sms": "SMS", "push": "PUSH"}.get(channel_name.lower())
    if not channel_code:
        return None

    date_str = due_on.replace("-", "_")           # "2026-05-21" → "2026_05_21"
    prefix_upper = f"P_{channel_code}_{date_str}_{braze_brand}_".upper()

    try:
        all_campaigns = await asyncio.to_thread(get_all_campaigns, brand=brand_code)
    except Exception as exc:
        logger.warning(f"[QA] Braze campaign lookup failed for {brand_code}: {exc}")
        return None

    candidates = [c for c in all_campaigns if c.get("name", "").upper().startswith(prefix_upper)]
    if not candidates:
        logger.info(f"[QA] No campaigns found with prefix {prefix_upper!r} for task {raw_task.get('gid')}")
        return None

    task_words = _normalize_name_words(task_name)
    if not task_words:
        return None

    matches = []
    for c in candidates:
        desc = _strip_campaign_prefix(c["name"], channel_code, date_str, braze_brand)
        campaign_words = _normalize_name_words(desc)
        overlap = task_words & campaign_words
        if len(overlap) >= 2 and len(overlap) / len(task_words) >= 0.5:
            matches.append(c)

    if len(matches) != 1:
        logger.info(
            f"[QA] Auto-lookup for {task_name!r} on {due_on}: "
            f"{len(matches)} candidate(s) — {'ambiguous' if matches else 'no match'}"
        )
        return None

    campaign_id = matches[0]["id"]
    campaign_name = matches[0]["name"]
    dashboard_base = os.environ.get("BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com").rstrip("/")

    # The Braze API returns the public API identifier (UUID format), NOT the internal
    # hex ObjectID used in dashboard URLs. UUID-based URLs navigate to the wrong page
    # (e.g. the Segments library) instead of the campaign editor, causing all QA checks
    # to fail. When the API returns a UUID, use Playwright to resolve the real hex URL
    # by searching the campaigns list and grabbing the link href.
    UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE)
    if UUID_RE.match(campaign_id):
        logger.info(
            f"[QA] API returned UUID for {campaign_name!r} — resolving hex URL via Playwright"
        )
        hex_url = await _resolve_campaign_url_via_playwright(brand_code, campaign_name, dashboard_base, workspace_id)
        if hex_url:
            logger.info(f"[QA] Resolved hex URL: {hex_url}")
            return hex_url
        logger.warning(f"[QA] Could not resolve hex URL for {campaign_name!r} — skipping auto-fill")
        return None

    url = f"{dashboard_base}/engagement/campaigns/{campaign_id}/{workspace_id}"
    logger.info(f"[QA] Auto-found Braze campaign: {campaign_name!r} → {url}")
    return url


def _fetch_ready_for_qa_tasks() -> list[dict]:
    """Return all tasks in Master CRM with Task Status = Ready for QA (blocking)."""
    resp = _asana_request(
        "GET",
        f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search",
        params={
            f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_FOR_QA,
            "projects.any": MASTER_PROJECT_GID,
            "opt_fields": f"gid,name,due_on,custom_fields.gid,custom_fields.enum_value",
            "limit": "100",
        },
    )
    return resp or []


_QA_COMMENT_PREFIXES = (
    QA_AUTOMATION_MARKER,          # legacy crash-only fallback
    "QA flagged items for human review:",
    "Automated QA complete",
    "Automated QA failed",
    "The Braze campaign link couldn't be resolved for auto-QA",
)


def _qa_already_ran(task_gid: str) -> bool:
    """Return True if any QA automation comment is present on the task (blocking)."""
    resp = _asana_request(
        "GET",
        f"tasks/{task_gid}/stories",
        params={"opt_fields": "type,text", "limit": "100"},
    )
    stories = resp or []
    return any(
        s.get("type") == "comment"
        and any((s.get("text") or "").startswith(p) for p in _QA_COMMENT_PREFIXES)
        for s in stories
    )


def _fetch_ready_to_code_tasks() -> list[dict]:
    """Return upcoming tasks in Master CRM with Task Status = Ready to Code (blocking).

    Filters to due_on >= yesterday at the API level so the 100-task limit only
    applies to relevant upcoming tasks, not accumulated historical ones.
    Tasks with no due_on are excluded by this filter (they're handled via webhooks).
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    resp = _asana_request(
        "GET",
        f"workspaces/{ASANA_WORKSPACE_GID}/tasks/search",
        params={
            f"custom_fields.{FIELD_TASK_STATUS}.value": STATUS_READY_TO_CODE,
            "projects.any": MASTER_PROJECT_GID,
            "due_on.after": yesterday,
            "opt_fields": "gid,name,due_on,custom_fields.gid,custom_fields.enum_value",
            "limit": "100",
        },
    )
    return resp or []


async def _poll_ready_to_code() -> None:
    """
    Polling fallback: every QA_POLL_INTERVAL seconds, scan Master CRM for tasks
    in Ready to Code that the webhook missed and queue them for building.

    Skips tasks that are already in-flight (_processing), stale (due > 1 day ago),
    or recently checked and found ineligible (_rtc_skipped TTL not yet expired).
    """
    import time as _time
    while True:
        await asyncio.sleep(QA_POLL_INTERVAL)
        try:
            # Prune expired skip entries
            now = _time.monotonic()
            expired = [g for g, exp in _rtc_skipped.items() if now >= exp]
            for g in expired:
                del _rtc_skipped[g]

            tasks = await asyncio.to_thread(_fetch_ready_to_code_tasks)
            if not tasks:
                continue
            logger.info(f"[Poll-RTC] Found {len(tasks)} Ready-to-Code task(s) — checking for missed events")
            for task in tasks:
                gid = task.get("gid", "")
                name = task.get("name", gid)
                if not gid:
                    continue
                due_on = task.get("due_on")
                if due_on and due_on < (date.today() - timedelta(days=1)).isoformat():
                    logger.debug(f"[Poll-RTC] {gid} ({name!r}) due {due_on} — stale, skipping")
                    continue
                if gid in _processing:
                    logger.debug(f"[Poll-RTC] {gid} ({name!r}) already in-flight — skipping")
                    continue
                if gid in _rtc_skipped:
                    logger.debug(f"[Poll-RTC] {gid} ({name!r}) recently checked — skipping until TTL expires")
                    continue
                logger.info(f"[Poll-RTC] Queuing missed Ready-to-Code task: {gid} ({name!r})")
                await _check_and_dispatch(gid)
        except Exception:
            logger.exception("[Poll-RTC] Error during Ready-to-Code poll")


async def _poll_ready_for_qa() -> None:
    """
    Polling fallback: every QA_POLL_INTERVAL seconds, scan Master CRM for tasks
    in Ready for QA that the webhook missed and queue them for processing.

    Skips tasks that are already in-flight (_processing) or that already have
    the QA automation marker comment (i.e. QA was already attempted).
    """
    while True:
        await asyncio.sleep(QA_POLL_INTERVAL)
        try:
            tasks = await asyncio.to_thread(_fetch_ready_for_qa_tasks)
            if not tasks:
                continue
            logger.info(f"[Poll] Found {len(tasks)} Ready-for-QA task(s) — checking for missed events")
            for task in tasks:
                gid = task.get("gid", "")
                name = task.get("name", gid)
                if not gid:
                    continue
                due_on = task.get("due_on")
                if due_on and due_on < (date.today() - timedelta(days=1)).isoformat():
                    logger.debug(f"[Poll] {gid} ({name!r}) due {due_on} — stale, skipping")
                    continue
                if gid in _processing:
                    logger.debug(f"[Poll] {gid} ({name!r}) already in-flight — skipping")
                    continue
                brand_gid = _get_enum_value_gid(task, FIELD_BRAND)
                brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
                if brand_code in _KLAVIYO_DESIGNED_BRANDS:
                    logger.debug(f"[Poll] {gid} ({name!r}) is Klaviyo brand ({brand_code}) — skipping")
                    continue
                already_ran = await asyncio.to_thread(_qa_already_ran, gid)
                if already_ran:
                    logger.debug(f"[Poll] {gid} ({name!r}) QA marker found — skipping")
                    continue
                logger.info(f"[Poll] Queuing missed QA task: {gid} ({name!r})")
                await _check_and_dispatch(gid)
        except Exception:
            logger.exception("[Poll] Error during Ready-for-QA poll")


@app.on_event("startup")
async def startup() -> None:
    global _webhook_secret
    _webhook_secret = _load_secret()
    if _webhook_secret:
        logger.info("Webhook secret loaded — ready to verify signatures")
    else:
        logger.warning(
            "No ASANA_WEBHOOK_SECRET configured. "
            "The secret will be captured automatically on the next Asana handshake. "
            "Register your webhook to trigger the handshake."
        )
    asyncio.create_task(_queue_worker())
    logger.info("Build queue worker started")
    asyncio.create_task(_poll_ready_for_qa())
    logger.info(f"Ready-for-QA polling fallback started (interval={QA_POLL_INTERVAL}s)")
    asyncio.create_task(_poll_ready_to_code())
    logger.info(f"Ready-to-Code polling fallback started (interval={QA_POLL_INTERVAL}s)")


@app.get("/health")
async def health() -> dict:
    """Health check — useful for confirming ngrok can reach the server."""
    return {
        "status": "ok",
        "secret_configured": bool(_webhook_secret),
        "queue_depth": _build_queue.qsize(),
        "tasks_queued_or_building": list(_processing),
    }


@app.post("/webhook/asana")
async def asana_webhook(request: Request) -> Response:
    """
    Main webhook endpoint. Handles:
      - Asana handshake (X-Hook-Secret echo, no signature check)
      - HMAC-SHA256 signature verification
      - Event parsing and dispatch to orchestrate()
    """
    body_bytes = await request.body()

    # -------------------------------------------------------------------
    # 1. Handshake — Asana sends X-Hook-Secret with no signature
    #    We echo the secret back and save it for future verification.
    # -------------------------------------------------------------------
    hook_secret = request.headers.get("X-Hook-Secret")
    if hook_secret:
        logger.info("Asana handshake received — echoing X-Hook-Secret and saving")
        _save_secret(hook_secret)
        return Response(
            status_code=200,
            headers={"X-Hook-Secret": hook_secret},
        )

    # -------------------------------------------------------------------
    # 2. Signature verification — all event deliveries must be signed
    # -------------------------------------------------------------------
    sig_header = request.headers.get("X-Hook-Signature", "")

    if not _webhook_secret:
        logger.error(
            "No webhook secret — cannot verify signature. "
            "Re-register your webhook so the handshake runs again."
        )
        return Response(status_code=403)

    expected_sig = hmac.new(
        _webhook_secret.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, sig_header):
        logger.warning("Invalid X-Hook-Signature — rejecting request")
        return Response(status_code=403)

    # -------------------------------------------------------------------
    # 3. Parse event payload
    # -------------------------------------------------------------------
    try:
        payload = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        logger.warning("Could not parse webhook payload as JSON")
        return Response(status_code=200)  # Return 200 to avoid Asana retries

    events = payload.get("events", [])
    if not events:
        return Response(status_code=200)

    # Collect task GIDs for SMS build eligibility checks (task-changed events)
    # and story GIDs for AI feedback capture (story-added events).
    candidate_task_gids: Set[str] = set()
    story_events: list = []

    for event in events:
        resource = event.get("resource", {})
        resource_type = resource.get("resource_type")
        action = event.get("action")

        if action == "changed" and resource_type == "task":
            candidate_task_gids.add(resource["gid"])
        elif action == "added" and resource_type == "story":
            parent = event.get("parent", {})
            if parent.get("resource_type") == "task":
                story_events.append({
                    "story_gid": resource["gid"],
                    "task_gid": parent["gid"],
                })

    if not candidate_task_gids and not story_events:
        logger.debug("No relevant events in payload — ignoring")
        return Response(status_code=200)

    if candidate_task_gids:
        logger.info(f"Received {len(events)} event(s), {len(candidate_task_gids)} task GID(s) to check")
    if story_events:
        logger.info(f"Received {len(story_events)} story event(s) — checking for AI feedback")

    # -------------------------------------------------------------------
    # 4. Dispatch as background tasks so we return quickly.
    #    Asana requires a response within 10 seconds.
    # -------------------------------------------------------------------
    for task_gid in candidate_task_gids:
        asyncio.create_task(_check_and_dispatch(task_gid))

    for ev in story_events:
        asyncio.create_task(_handle_story_event(ev["story_gid"], ev["task_gid"]))

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Single-slice HAV designed email helpers
# ---------------------------------------------------------------------------

def _is_combined_hav_task(task_name: str) -> bool:
    """True if the task is a combined DPS+MP or MP+DPS designed email (should be skipped)."""
    n = task_name.strip().upper()
    return bool(
        re.search(r'\bDPS\s+(AND|&)\s+MP\b', n) or
        re.search(r'\bMP\s+(AND|&)\s+DPS\b', n)
    )


def _detect_hav_audience(task_name: str) -> Optional[str]:
    """Return 'PC' or 'CONV' based on task name tokens, or None if ambiguous."""
    n = task_name.strip().upper()
    if "_PC_" in n or re.match(r'^DPS[\s:]', n):
        return "PC"
    if "_CONV_" in n or re.match(r'^MP[\s:]', n):
        return "CONV"
    return None


async def _check_single_slice_opportunity(raw_task: dict) -> Optional[dict]:
    """Return {"ref_campaign": str, "banner_drive_url": str} if the task qualifies for
    single-slice auto-build, else None.

    Conditions:
      - Not a combined DPS+MP task
      - "Email Slices/Banners/Blocks Details" field contains a Drive folder URL
      - That folder has exactly one image file
      - Task name encodes a detectable HAV audience (PC or CONV)
    """
    from utils.drive_client import list_folder_images
    from build_designed_campaign import HAV_PC_FALLBACK_TEMPLATE, HAV_CONV_FALLBACK_TEMPLATE
    from build_sms_campaign import _get_text_value

    task_name = raw_task.get("name", "")

    if _is_combined_hav_task(task_name):
        logger.info(f"Single-slice check: combined DPS+MP task ({task_name!r}) — skipping")
        return None

    slices_url = _get_text_value(raw_task, FIELD_EMAIL_SLICES)
    if not slices_url:
        return None

    if "/drive/folders/" not in slices_url:
        # Field is set but to a file URL, not a folder — not applicable
        return None

    try:
        images = await asyncio.to_thread(list_folder_images, slices_url)
    except Exception as exc:
        logger.warning(f"Single-slice: could not list Drive folder {slices_url!r}: {exc}")
        return None

    if len(images) != 1:
        logger.info(
            f"Single-slice: folder has {len(images)} image(s) — "
            f"need exactly 1 to auto-build ({task_name!r})"
        )
        return None

    audience = _detect_hav_audience(task_name)
    if not audience:
        logger.warning(
            f"Single-slice: could not detect PC/CONV audience from task name {task_name!r} — skipping"
        )
        return None

    ref_campaign = HAV_PC_FALLBACK_TEMPLATE if audience == "PC" else HAV_CONV_FALLBACK_TEMPLATE
    file_id = images[0]["id"]
    banner_drive_url = f"https://drive.google.com/file/d/{file_id}/view"
    logger.info(
        f"Single-slice opportunity: audience={audience}, ref={ref_campaign}, "
        f"image={images[0]['name']!r}"
    )
    return {"ref_campaign": ref_campaign, "banner_drive_url": banner_drive_url}


async def _dispatch_single_slice_designed_build(
    task_gid: str, brand_code: str, single_slice_ref: dict
) -> None:
    """Build a single-slice HAV designed email using the fallback template."""
    from build_designed_campaign import build_designed_campaign

    result = await build_designed_campaign(
        task_gid=task_gid,
        brand=brand_code,
        dry_run=False,
        headless=True,
        auto_confirm=True,
        ref_campaign_override=single_slice_ref["ref_campaign"],
        banner_drive_url_override=single_slice_ref["banner_drive_url"],
        single_slice_build=True,
    )

    if result.get("success"):
        logger.info(
            f"Single-slice designed email built: "
            f"{result.get('campaign_name')} → {result.get('braze_url')}"
        )
    else:
        errors = result.get("errors") or []
        error_msg = '; '.join(errors) if errors else 'unknown error'
        logger.error(f"Single-slice build failed for task {task_gid}: {error_msg}")
        if any(kw in error_msg.lower() for kw in _SESSION_ERROR_KEYWORDS):
            raise Exception(f"Playwright error: {error_msg}")


async def _queue_worker() -> None:
    """Process build jobs one at a time to prevent concurrent Playwright sessions."""
    while True:
        task_gid, build_coro = await _build_queue.get()
        pending = _build_queue.qsize()
        logger.info(f"[Queue] Starting build for task {task_gid} ({pending} job(s) still waiting)")
        try:
            await build_coro
        except Exception:
            logger.exception(f"[Queue] Unhandled error building task {task_gid}")
        finally:
            _processing.discard(task_gid)
            _build_queue.task_done()
            # Mark as recently-checked so the RTC poll doesn't immediately re-queue.
            # Successful builds move the task to Ready-for-QA (no longer RTC), so this
            # only matters for skipped/ineligible tasks that remain in Ready-to-Code.
            import time as _time
            _rtc_skipped[task_gid] = _time.monotonic() + RTC_SKIP_TTL


async def _check_and_dispatch(task_gid: str) -> None:
    """
    Enqueue a build job for the given task GID if it isn't already queued or building.
    The queue worker processes jobs one at a time to prevent concurrent Playwright sessions.
    """
    # A fresh webhook event means the task may have changed — clear any RTC skip TTL
    # so it gets a fresh eligibility check.
    _rtc_skipped.pop(task_gid, None)

    if task_gid in _processing:
        logger.info(f"Task {task_gid} already queued or in flight — skipping duplicate event")
        return

    # Claim the slot before any await so asyncio's single-threaded scheduler keeps this atomic.
    _processing.add(task_gid)
    await _build_queue.put((task_gid, _check_and_build(task_gid)))
    logger.info(f"Task {task_gid} enqueued (queue depth now {_build_queue.qsize()})")


async def _follow_up_qa(task_gid: str, task_name: str) -> None:
    """Dispatch QA immediately after a successful build, bypassing webhook/search latency.

    Re-fetches the task to get the post-build state. Skips if QA already ran (prevents
    double-dispatch when a late webhook event also triggers the Ready-for-QA path).
    """
    fresh_task = await asyncio.to_thread(fetch_task_by_gid, task_gid)
    if not fresh_task:
        return
    if _get_enum_value_gid(fresh_task, FIELD_TASK_STATUS) != STATUS_READY_FOR_QA:
        logger.info(f"Post-build QA: task {task_gid} not in Ready for QA — skipping")
        return
    braze_link = _get_text_value(fresh_task, FIELD_BRAZE_LINK)
    brand_code = BRAND_GID_TO_CODE.get(_get_enum_value_gid(fresh_task, FIELD_BRAND) or "")
    if not braze_link or not brand_code or brand_code in _KLAVIYO_DESIGNED_BRANDS:
        return
    already_ran = await asyncio.to_thread(_qa_already_ran, task_gid)
    if already_ran:
        logger.info(f"Post-build QA: already ran for task {task_gid} — skipping")
        return
    logger.info(f"Post-build: dispatching QA for [{brand_code}] {task_name}")
    channel_gid = _get_enum_value_gid(fresh_task, FIELD_CHANNEL)
    if channel_gid == SMS_CHANNEL_GID:
        await _dispatch_qa_sms(task_gid, fresh_task, brand_code, braze_link)
    else:
        await _dispatch_qa_designed_email(task_gid, fresh_task, brand_code, braze_link)


async def _check_and_build(task_gid: str) -> None:
    """Inner check-and-build logic, called only after the task is reserved in _processing."""
    # Brief delay so Asana's API has time to propagate the field change before we read it.
    # Without this, a webhook fired immediately after a custom field save can return stale
    # task data (e.g. Ref Braze Campaign still appearing empty), causing the task to be
    # incorrectly skipped as ineligible with no retry.
    await asyncio.sleep(3)

    # Fetch full task to inspect custom fields
    raw_task = await asyncio.to_thread(fetch_task_by_gid, task_gid)
    if not raw_task:
        logger.warning(f"Could not fetch task {task_gid} from Asana")
        return

    # --- Check: Channel = SMS, Push, or Email ---
    channel_gid = _get_enum_value_gid(raw_task, FIELD_CHANNEL)
    if channel_gid not in (SMS_CHANNEL_GID, PUSH_CHANNEL_GID, EMAIL_CHANNEL_GID):
        logger.info(
            f"Task {task_gid} skipped: channel={channel_gid} "
            f"(not SMS/Push/Email)"
        )
        return

    # --- Check: Status ---
    status_gid = _get_enum_value_gid(raw_task, FIELD_TASK_STATUS)

    # Ready for QA → run Playwright QA verification + test send (email/SMS/push, Braze brands)
    if status_gid == STATUS_READY_FOR_QA:
        braze_link = _get_text_value(raw_task, FIELD_BRAZE_LINK)
        brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
        brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
        if not brand_code:
            logger.warning(f"Task {task_gid} Ready for QA: unknown brand GID {brand_gid!r}")
            return
        if brand_code in _KLAVIYO_DESIGNED_BRANDS:
            # Klaviyo brands use API-based QA (no Playwright)
            klaviyo_link = braze_link  # stored as "Braze Campaign Link" field for both platforms
            if not klaviyo_link:
                _asana_request(
                    "POST",
                    f"tasks/{task_gid}/stories",
                    json_data={"data": {
                        "text": "No Klaviyo campaign link found — add it manually to trigger QA.",
                        "is_pinned": False,
                    }},
                )
                return
            # Extract campaign ID from Klaviyo URL
            # e.g. https://www.klaviyo.com/campaign/01KVBEEKADZ4F5A3MEFNDV731M/overview
            #      https://www.klaviyo.com/text-message/campaign/01KVBEEKADZ4F5A3MEFNDV731M/edit
            m_id = re.search(r'/campaign/([A-Z0-9]+)', klaviyo_link)
            if not m_id:
                logger.warning(f"Task {task_gid}: could not parse Klaviyo campaign ID from {klaviyo_link!r}")
                return
            klaviyo_campaign_id = m_id.group(1)
            channel_name = "sms" if channel_gid == SMS_CHANNEL_GID else "email"
            already_ran = await asyncio.to_thread(_qa_already_ran, task_gid)
            if already_ran:
                logger.info(f"Task {task_gid} QA already ran — skipping duplicate dispatch")
                return
            logger.info(
                f"Klaviyo QA dispatch: [{brand_code}] {raw_task.get('name', task_gid)} "
                f"— {channel_name} — campaign {klaviyo_campaign_id}"
            )
            try:
                from qa_klaviyo import run_klaviyo_qa_async
                await run_klaviyo_qa_async(
                    task_gid=task_gid,
                    brand=brand_code,
                    campaign_id=klaviyo_campaign_id,
                    channel=channel_name,
                    raw_task=raw_task,
                    dry_run=False,
                )
            except Exception:
                logger.exception(f"Klaviyo QA failed for task {task_gid}")
                _asana_request(
                    "POST",
                    f"tasks/{task_gid}/stories",
                    json_data={"data": {"text": "Automated QA failed — check server logs."}},
                )
            return
        already_ran = await asyncio.to_thread(_qa_already_ran, task_gid)
        if already_ran:
            logger.info(f"Task {task_gid} QA already ran — skipping duplicate dispatch")
            return
        if not braze_link:
            # No link set — try to auto-resolve by matching brand + date + campaign name
            braze_link = await _find_braze_campaign_for_task(raw_task, brand_code, channel_gid)
            if braze_link:
                from build_sms_campaign import update_asana_with_braze_link
                await asyncio.to_thread(update_asana_with_braze_link, task_gid, braze_link)
                logger.info(f"Task {task_gid}: auto-filled Braze link → {braze_link}")
            else:
                already_noted = await asyncio.to_thread(_qa_already_ran, task_gid)
                if not already_noted:
                    _asana_request(
                        "POST",
                        f"tasks/{task_gid}/stories",
                        json_data={
                            "data": {
                                "text": (
                                    "The Braze campaign link couldn't be resolved for auto-QA, so several QA steps were skipped. "
                                    "Please add the Braze campaign link manually and re-run QA."
                                ),
                                "is_pinned": False,
                            }
                        },
                    )
                else:
                    logger.info(
                        f"Task {task_gid}: no campaign found but 'no matching' comment already posted — skipping"
                    )
                return
        if channel_gid == SMS_CHANNEL_GID:
            await _dispatch_qa_sms(task_gid, raw_task, brand_code, braze_link)
        else:
            await _dispatch_qa_designed_email(task_gid, raw_task, brand_code, braze_link)
        return

    if status_gid != STATUS_READY_TO_CODE:
        logger.info(
            f"Task {task_gid} skipped: status={status_gid} "
            f"(not Ready to Code={STATUS_READY_TO_CODE})"
        )
        return

    # --- For email tasks: handle designed (Ref Braze Campaign filled), plain-text,
    #     single-slice HAV auto-build, or CZ image-based designed email (due CZ_DESIGNED_CUTOFF+)
    # PT detection: Type field = "Plain-Text" OR task name ends in _PT / contains _PT_
    #
    # *** ADDING A NEW HTML/CSS BRAND? Update ALL of these (see CLAUDE.md § "HTML/CSS Brand Migration"): ***
    #   1. This file — add the brand + its cutoff to HTMLCSS_DESIGNED_CUTOFFS (the detection below is generic)
    #   2. poll_ready_tasks.py — add the brand + cutoff to its HTMLCSS_DESIGNED_CUTOFFS map
    #   3. Ensure build_cz_designed_email.py handles the brand (footer, API key, fallback link, sale lookup)
    #   4. Confirm the brand has BRAZE_API_KEY_{BRAND} + BRAZE_API_KEY_MEDIA_{BRAND} in .env and a brand_config entry
    single_slice_ref: Optional[dict] = None
    is_htmlcss_designed: bool = False
    if channel_gid == EMAIL_CHANNEL_GID:
        type_gid = _get_enum_value_gid(raw_task, FIELD_TYPE)
        _name_upper = raw_task.get("name", "").strip().upper()
        _is_pt_name = _name_upper.endswith("_PT") or "_PT_" in _name_upper

        # HTML/CSS image-based designed email (CZ, STF): check before ref_campaign so a
        # populated Ref Braze Campaign field doesn't accidentally route to the DnD duplicator.
        if type_gid != TYPE_PLAIN_TEXT and not _is_pt_name:
            brand_gid_early = _get_enum_value_gid(raw_task, FIELD_BRAND)
            brand_code_early = BRAND_GID_TO_CODE.get(brand_gid_early or "")
            htmlcss_cutoff = HTMLCSS_DESIGNED_CUTOFFS.get(brand_code_early or "")
            if htmlcss_cutoff:
                htmlcss_drive_url = _get_text_value(raw_task, FIELD_EMAIL_SLICES)
                due_on = raw_task.get("due_on") or ""
                if (
                    htmlcss_drive_url
                    and "drive.google.com" in htmlcss_drive_url
                    and due_on >= htmlcss_cutoff
                ):
                    is_htmlcss_designed = True

        ref_campaign = _get_text_value(raw_task, FIELD_REF_BRAZE_CAMPAIGN)
        if not is_htmlcss_designed and not ref_campaign:
            if type_gid != TYPE_PLAIN_TEXT and not _is_pt_name:
                brand_gid_early = _get_enum_value_gid(raw_task, FIELD_BRAND)
                brand_code_early = BRAND_GID_TO_CODE.get(brand_gid_early or "")
                if brand_code_early == "HAV":
                    # Check if this qualifies as a single-slice HAV designed email
                    single_slice_ref = await _check_single_slice_opportunity(raw_task)
                elif brand_code_early in HTMLCSS_DESIGNED_CUTOFFS:
                    # HTML/CSS brand but doesn't meet image-build criteria and has no ref campaign — skip
                    logger.info(
                        f"Task {task_gid} skipped: {brand_code_early} email but no Drive URL or due before "
                        f"{HTMLCSS_DESIGNED_CUTOFFS[brand_code_early]} "
                        f"(due_on={raw_task.get('due_on')!r}, "
                        f"drive={_get_text_value(raw_task, FIELD_EMAIL_SLICES)!r})"
                    )
                    return
                if not single_slice_ref:
                    logger.info(
                        f"Task {task_gid} skipped: email, no Ref Braze Campaign, "
                        f"Type={type_gid!r}, name={raw_task.get('name', '')!r} — not PT, not single-slice, not CZ designed"
                    )
                    return

    # --- Skip if already built ---
    # All builders write the campaign URL to FIELD_BRAZE_LINK.
    # Writing that field triggers another Asana webhook event, so guard here
    # to avoid a second build + duplicate comment.
    #
    # Exception: combined DPS+MP push tasks build two campaigns (PC + CONV).
    # The first variant writes its link to FIELD_BRAZE_LINK, but the second
    # variant still needs to be built. Only skip if the auto-build comment
    # confirms both were written (checked below via _has_auto_build_story).
    existing_braze_link = _get_text_value(raw_task, FIELD_BRAZE_LINK)
    task_name_for_guard = raw_task.get("name", "")
    is_combined_push = (
        channel_gid == PUSH_CHANNEL_GID
        and re.search(r'\bDPS\s+and\s+(?:MP|MKPL)\b', task_name_for_guard, re.IGNORECASE)
    )
    if existing_braze_link and not is_combined_push:
        logger.info(f"Task {task_gid} already has Braze link ({existing_braze_link}) — skipping")
        return

    # --- Secondary guard: check task stories for an existing auto-build comment ---
    # The Braze link field check above can race if Asana's API returns stale task data
    # in the brief window after a write. Fetching stories is a separate API call on a
    # different resource, so it's unlikely to return the same stale snapshot.
    def _has_auto_build_story(gid: str) -> bool:
        resp = _asana_request("GET", f"tasks/{gid}/stories", params={"opt_fields": "text,html_text,resource_subtype"})
        if not resp:
            return False
        for story in (resp or []):
            if story.get("resource_subtype") != "comment":
                continue
            text = story.get("text") or story.get("html_text") or ""
            if "automatically created in Braze" in text or "automatically created in Klaviyo" in text:
                return True
        return False

    already_commented = await asyncio.to_thread(_has_auto_build_story, task_gid)
    if already_commented:
        logger.info(f"Task {task_gid} already has an auto-build comment — skipping to avoid duplicate")
        return

    # --- Determine brand ---
    brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
    brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
    if not brand_code:
        logger.warning(
            f"Task {task_gid} has unknown brand GID {brand_gid!r} — skipping"
        )
        return

    task_name = raw_task.get("name", task_gid)

    # Determine email sub-type for routing and logging
    is_pt_email = (
        channel_gid == EMAIL_CHANNEL_GID
        and not _get_text_value(raw_task, FIELD_REF_BRAZE_CAMPAIGN)
        and not single_slice_ref
        and not is_htmlcss_designed
    )

    # --- Dispatch (with one session-refresh retry) ---
    async def _run_build() -> None:
        if channel_gid == SMS_CHANNEL_GID:
            await orchestrate(
                brand_code=brand_code,
                dry_run=False,
                headless=True,
                single_task_gid=task_gid,
            )
        elif channel_gid == EMAIL_CHANNEL_GID:
            if is_pt_email:
                await _dispatch_pt_email_build(task_gid, raw_task, brand_code)
            elif single_slice_ref:
                await _dispatch_single_slice_designed_build(task_gid, brand_code, single_slice_ref)
            elif is_htmlcss_designed:
                await _dispatch_htmlcss_designed_build(task_gid, raw_task, brand_code)
            elif brand_code in _KLAVIYO_DESIGNED_BRANDS:
                await _dispatch_klaviyo_designed_build(task_gid, brand_code)
            else:
                await _dispatch_designed_build(task_gid, brand_code)
        else:  # PUSH
            await _dispatch_push_build(task_gid, raw_task)

    channel_label = {
        SMS_CHANNEL_GID: "SMS",
        PUSH_CHANNEL_GID: "Push",
        EMAIL_CHANNEL_GID: (
            "PT Email" if is_pt_email
            else "Single-Slice Designed Email" if single_slice_ref
            else "HTML/CSS Designed Email" if is_htmlcss_designed
            else "Klaviyo Designed Email" if brand_code in _KLAVIYO_DESIGNED_BRANDS
            else "Designed Email"
        ),
    }.get(channel_gid, "Unknown")
    logger.info(
        f"Eligible {channel_label} task detected: [{brand_code}] {task_name} (gid={task_gid})\n"
        f"  Dispatching campaign build..."
    )

    # Cross-process build lock. The standalone poll-ready-tasks LaunchAgent is a separate
    # process and can start building this same task while we're mid-build — the Braze-link
    # idempotency guard only takes effect once a build finishes and writes the link, which
    # is several minutes away for PT/designed builds. Claim a shared per-GID lock so exactly
    # one process builds a given task. See build_lock.py.
    from build_lock import try_acquire as _acquire_build_lock, release as _release_build_lock
    if not await asyncio.to_thread(_acquire_build_lock, task_gid):
        logger.info(
            f"Task {task_gid} is being built by another process (poll-ready-tasks) — "
            f"skipping to avoid a duplicate campaign"
        )
        return

    build_ok = False
    try:
        await _run_build()
        build_ok = True
        if channel_gid == SMS_CHANNEL_GID:
            logger.info(f"SMS build complete: [{brand_code}] {task_name} (gid={task_gid})")
        elif channel_gid == PUSH_CHANNEL_GID:
            logger.info(f"Push build complete: [{brand_code}] {task_name} (gid={task_gid})")
    except Exception as exc:
        err_lower = str(exc).lower()
        if any(kw in err_lower for kw in _SESSION_ERROR_KEYWORDS):
            logger.warning(
                f"Build failed with likely session error ({exc!r}) — "
                f"refreshing session and retrying once..."
            )
            # Re-fetch the task before retrying — if the build already succeeded
            # (campaign created + Asana comment posted) but then threw during
            # cleanup, the Braze link may already be set. Retrying in that case
            # would create a duplicate campaign.
            pre_retry_task = await asyncio.to_thread(fetch_task_by_gid, task_gid)
            if pre_retry_task:
                pre_retry_link = _get_text_value(pre_retry_task, FIELD_BRAZE_LINK)
                if pre_retry_link:
                    logger.info(
                        f"Task {task_gid} already has Braze link ({pre_retry_link}) — "
                        f"skipping retry to avoid duplicate campaign"
                    )
                    return
            try:
                from refresh_session import main as _refresh_session
                await _refresh_session()
                logger.info("Session refreshed — retrying build...")
                await _run_build()
                build_ok = True
                logger.info(f"Retry succeeded for task {task_gid}")
            except Exception:
                logger.exception(f"Retry also failed for task {task_gid}")
        else:
            logger.exception(f"Error building campaign for task {task_gid}")
    finally:
        # Release even on the early `return` in the retry-skip branch above.
        await asyncio.to_thread(_release_build_lock, task_gid)

    if build_ok:
        await _follow_up_qa(task_gid, task_name)


async def _dispatch_push_build(task_gid: str, raw_task: dict) -> None:
    """Build push notification campaign(s) in Braze for a single Asana task.

    A combined DPS+MP task produces two campaigns (HAV_PC + HAV_CONV); both
    are built sequentially and their links written back to the Asana task.
    """
    from build_push_campaign import (
        parse_asana_push_task,
        build_single_push_campaign,
        _writeback_to_asana as _push_writeback_to_asana,
        load_brand_config,
    )

    task_name = raw_task.get("name", task_gid)
    brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
    brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")

    parsed_tasks = await asyncio.to_thread(parse_asana_push_task, raw_task)
    if not parsed_tasks:
        logger.warning(
            f"Push task {task_gid} ({task_name}) could not be parsed "
            f"(missing Title/Description copy, wrong brand, or wrong channel?) — skipping"
        )
        return

    logger.info(
        f"Eligible PUSH task detected: [{brand_code}] {task_name} (gid={task_gid})\n"
        f"  Dispatching {len(parsed_tasks)} push campaign(s)..."
    )

    global_config = await asyncio.to_thread(load_brand_config)

    results = []
    for task in parsed_tasks:
        try:
            result = await build_single_push_campaign(
                task=task,
                global_config=global_config,
                dry_run=False,
                auto_confirm=True,
                headless=True,
            )
            results.append(result)
        except Exception:
            logger.exception(
                f"Error building push campaign variant {task.get('variant')} for task {task_gid}"
            )

    if results:
        if len(results) < len(parsed_tasks):
            # Partial failure — one or more variants failed to build.
            # Do NOT set the task to Ready for QA; leave it in Ready to Code
            # so the next poll will retry.
            succeeded = [r.get("variant") for r in results]
            failed = [t.get("variant") for t in parsed_tasks if t.get("variant") not in succeeded]
            logger.warning(
                f"Push task {task_gid}: only {len(results)}/{len(parsed_tasks)} variants succeeded "
                f"(built: {succeeded}, failed: {failed}). "
                "Skipping Asana writeback — task remains in Ready to Code for retry."
            )
        else:
            await asyncio.to_thread(_push_writeback_to_asana, results, parsed_tasks)


async def _dispatch_designed_build(task_gid: str, brand_code: str) -> None:
    """Build a designed email campaign in Braze for a single Asana task."""
    from build_designed_campaign import build_designed_campaign

    result = await build_designed_campaign(
        task_gid=task_gid,
        brand=brand_code,
        dry_run=False,
        headless=True,
        auto_confirm=True,
    )

    if result.get("success"):
        logger.info(
            f"Designed email built: {result.get('campaign_name')} → {result.get('braze_url')}"
        )
    else:
        errors = result.get("errors") or []
        error_msg = '; '.join(errors) if errors else 'unknown error'
        logger.error(f"Designed email build failed for task {task_gid}: {error_msg}")
        if any(kw in error_msg.lower() for kw in _SESSION_ERROR_KEYWORDS):
            raise Exception(f"Playwright error: {error_msg}")


async def _dispatch_htmlcss_designed_build(task_gid: str, raw_task: dict, brand_code: str) -> None:
    """Build an HTML/CSS image-based designed email from a task marked Ready to Code.

    Reads the Drive folder URL from the 'Email Slices/Banners/Blocks Details' field,
    downloads slices, assembles HTML, creates the campaign, and posts the QA comment.

    Braze brands (CZ, STF)  → build_cz_designed_email (Playwright, Braze campaign).
    Klaviyo brands (TI)     → build_klaviyo_designed_email (API, Klaviyo campaign + CDN).
    Both share designed_email_core (Drive listing/download, layout, HTML assembly).
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    drive_url = _get_text_value(raw_task, FIELD_EMAIL_SLICES)

    if brand_code in _KLAVIYO_DESIGNED_BRANDS:
        # --- Klaviyo path (TI): API-based, uploads to Klaviyo CDN. The builder reads
        #     the Drive URL from the task itself, so it isn't passed positionally here. ---
        from build_klaviyo_designed_email import build_klaviyo_designed_email

        result = await build_klaviyo_designed_email(
            task_gid=task_gid,
            brand=brand_code,
            dry_run=False,
            auto_confirm=True,
        )
        built_url = result.get("overview_url") or result.get("edit_url")
    else:
        # --- Braze path (CZ, STF): Playwright-based, creates a Braze campaign. ---
        from build_cz_designed_email import build_cz_designed_email

        result = await build_cz_designed_email(
            task_gid=task_gid,
            drive_url=drive_url,
            dry_run=False,
            headless=True,
            brand=brand_code,
        )
        built_url = result.get("braze_url")

    if result.get("success"):
        logger.info(
            f"{brand_code} HTML/CSS designed email built: {built_url}"
        )
    else:
        errors = result.get("errors") or []
        error_msg = "; ".join(errors) if errors else "unknown error"
        logger.error(f"{brand_code} designed email build failed for task {task_gid}: {error_msg}")
        if any(kw in error_msg.lower() for kw in _SESSION_ERROR_KEYWORDS):
            raise Exception(f"Playwright error: {error_msg}")


async def _dispatch_qa_sms(
    task_gid: str, raw_task: dict, brand_code: str, braze_url: str
) -> None:
    """Run automated QA for a Braze SMS campaign.

    Runs the same Playwright-based send time / segment / filter checks as
    email via run_qa_and_test_send, then additionally reads the SMS body back
    from the Braze API and verifies it matches the Asana brief copy.
    """
    import re as _re
    import urllib.request as _urllib

    from qa_designed_email import run_qa_and_test_send, _braze_get, find_campaign_api_id_by_name

    task_name = raw_task.get("name", task_gid)
    notes = raw_task.get("notes", "")
    logger.info(f"[SMS QA] [{brand_code}] {task_name}")

    # --- Step 1: Run standard Playwright QA (send time, segment, filters) ---
    # run_qa_and_test_send already skips test send for SMS (result["test_send_ok"] = True).
    # It posts its own Asana comment with the results of those checks, so we only need
    # to append the copy-check result after it finishes.
    assignee_name: Optional[str] = (raw_task.get("assignee") or {}).get("name")
    try:
        await run_qa_and_test_send(
            task_gid=task_gid,
            brand=brand_code,
            braze_url=braze_url,
            assignee_name=assignee_name,
            dry_run=False,
            raw_task=raw_task,
        )
    except Exception:
        logger.exception(f"[SMS QA] Playwright checks failed for task {task_gid}")
        _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": "Automated QA (send time/segment/filters) failed — check server logs."}},
        )

    # --- Step 2: Copy check via Braze API ---
    # Resolve campaign API ID from the Braze URL campaignName param, or derive it.
    m = _re.search(r'campaignName=([^&]+)', braze_url)
    if m:
        import urllib.parse as _up
        campaign_name = _up.unquote_plus(m.group(1))
    else:
        from qa_designed_email import _derive_campaign_name
        campaign_name = _derive_campaign_name("", raw_task.get("name", ""), raw_task.get("due_on", ""), brand_code)

    api_id = await asyncio.to_thread(find_campaign_api_id_by_name, campaign_name, brand_code)
    if not api_id:
        logger.warning(f"[SMS QA] Campaign not found in Braze for copy check: {campaign_name!r}")
        _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": f"Copy check skipped — could not find Braze campaign '{campaign_name}'. Verify SMS body manually."}},
        )
        return

    details = await asyncio.to_thread(_braze_get, "campaigns/details", {"campaign_id": api_id}, brand_code)
    if not details:
        _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": "Copy check skipped — could not fetch campaign details from Braze."}},
        )
        return

    # Extract SMS body from campaigns/details messages dict
    sms_body = ""
    for msg in details.get("messages", {}).values():
        if (msg.get("channel") or "").upper() == "SMS":
            sms_body = msg.get("body", "") or msg.get("message", "") or ""
            break

    if not sms_body:
        _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": "Copy check skipped — could not read SMS body from Braze campaign. Verify copy manually."}},
        )
        return

    logger.info(f"[SMS QA] Actual SMS body: {sms_body!r}")

    copy_issues: list = []

    def _extract_expected(raw_notes: str) -> str:
        lines, out = raw_notes.splitlines(), []
        for line in lines:
            if _re.match(r'^\[AI Brief\]', line.strip(), _re.IGNORECASE):
                break
            out.append(line)
        body = "\n".join(out).strip()
        paras = _re.split(r'\n{2,}', body)
        return paras[0].strip() if paras else body

    def _normalise(text: str) -> str:
        """Reduce an SMS body to just its copy, for comparison.

        Drops the link and its UTM tail (the builder resolves LINK / appends the
        URL, so it is never part of the briefed copy) and ignores trailing
        punctuation, since the SMS link rule rewrites the sentence-ending period
        before the link into a colon.

        Deliberately does NOT strip a "Brand: " prefix by regex. The old
        `^[^:]+:\\s*` did, but it removed everything before the FIRST colon
        anywhere in the string — and because the link rule puts a colon
        immediately before the URL, that ate the whole message on any SMS
        without a brand prefix, leaving only the URL and guaranteeing a false
        "does not match Asana brief" flag. Prefix asymmetry is handled by the
        two-way containment check below instead.
        """
        from build_sms_campaign import SMS_URL_STRIP_RE

        text = SMS_URL_STRIP_RE.sub(' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()
        return text.rstrip(' .:;,-–—').lower()

    expected = _extract_expected(notes)
    # Substitute LINK placeholder with the actual URL so it doesn't cause a false mismatch
    url_in_actual = _re.search(r'https?://\S+', sms_body)
    url_str = url_in_actual.group(0) if url_in_actual else ""
    expected_for_compare = _re.sub(r'\bLINK\b', url_str, expected) if url_str else expected

    norm_expected = _normalise(expected_for_compare)
    norm_actual = _normalise(sms_body)

    # Two-way containment: the brief and the built body legitimately differ by a
    # leading "Brand: " prefix in either direction, so neither being a subset of
    # the other is the real mismatch signal.
    if norm_expected and not (
        norm_expected == norm_actual
        or norm_expected in norm_actual
        or norm_actual in norm_expected
    ):
        copy_issues.append(
            f"SMS body does not match Asana brief.\n"
            f"  Expected: {expected_for_compare!r}\n"
            f"  Actual:   {sms_body!r}"
        )
        logger.warning(f"[SMS QA] Copy mismatch — expected {norm_expected!r}, got {norm_actual!r}")
    else:
        logger.info("[SMS QA] Copy matches brief ✓")

    # Character count
    if len(sms_body) > 130:
        copy_issues.append(f"SMS body is {len(sms_body)} characters (limit 130) — shorten copy")

    # Link resolves
    if url_str:
        url_clean = url_str.rstrip('.,)')
        try:
            req = _urllib.Request(url_clean, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
            with _urllib.urlopen(req, timeout=10) as resp:
                link_ok = resp.status < 400
        except Exception:
            link_ok = False
        if not link_ok:
            copy_issues.append(f"SMS link does not resolve: {url_clean}")
        else:
            logger.info(f"[SMS QA] Link resolves ✓ ({url_clean})")
    else:
        copy_issues.append("No URL found in SMS body — verify link")

    if copy_issues:
        bullets = "\n".join(f"• {i}" for i in copy_issues)
        comment = f"Copy check flagged items for human review:\n{bullets}"
    else:
        comment = "Copy check passed — SMS body matches Asana brief ✓"
    _asana_request(
        "POST",
        f"tasks/{task_gid}/stories",
        json_data={"data": {"text": comment, "is_pinned": False}},
    )


async def _dispatch_qa_designed_email(
    task_gid: str, raw_task: dict, brand_code: str, braze_url: str
) -> None:
    """Run QA verification + test send when a task transitions to Ready for QA.

    Fires for email tasks on Braze brands only (Klaviyo brands are skipped upstream).
    The test email is sent to the task assignee's mapped address.
    """
    from qa_designed_email import run_qa_and_test_send

    assignee_name: Optional[str] = (raw_task.get("assignee") or {}).get("name")
    task_name = raw_task.get("name", task_gid)
    logger.info(
        f"QA dispatch: [{brand_code}] {task_name} "
        f"(assignee={assignee_name!r}, url={braze_url})"
    )

    try:
        result = await run_qa_and_test_send(
            task_gid=task_gid,
            brand=brand_code,
            braze_url=braze_url,
            assignee_name=assignee_name,
            dry_run=False,
            raw_task=raw_task,
        )
        logger.info(
            f"QA complete for [{brand_code}] {task_name}: "
            f"send_time={'✓' if result['send_time_ok'] else '✗'} "
            f"segment={'✓' if result['segment_ok'] else '✗'} "
            f"filters={'✓' if result['filters_ok'] else '✗'} "
            f"test_send={'✓' if result['test_send_ok'] else '✗'}"
        )
    except Exception:
        logger.exception(f"QA dispatch failed for task {task_gid} ({task_name})")
        # Post a failure comment so the polling fallback won't retry indefinitely.
        _asana_request(
            "POST",
            f"tasks/{task_gid}/stories",
            json_data={"data": {"text": "Automated QA failed — check server logs."}},
        )


# Klaviyo brands that use the Playwright designed-email builder instead of Braze
_KLAVIYO_DESIGNED_BRANDS: set[str] = {"TI", "TE"}


async def _dispatch_klaviyo_designed_build(task_gid: str, brand_code: str) -> None:
    """Build a designed email campaign shell in Klaviyo for a single Asana task (TI)."""
    from build_klaviyo_designed_campaign import build_klaviyo_designed_campaign

    result = await build_klaviyo_designed_campaign(
        task_gid=task_gid,
        brand=brand_code,
        dry_run=False,
        auto_confirm=True,
    )

    if result.get("success"):
        logger.info(
            f"Klaviyo designed email built: {result.get('campaign_name')} → {result.get('braze_url')}"
        )
    else:
        errors = result.get("errors") or []
        error_msg = '; '.join(errors) if errors else 'unknown error'
        logger.error(f"Klaviyo designed email build failed for task {task_gid}: {error_msg}")
        if any(kw in error_msg.lower() for kw in _SESSION_ERROR_KEYWORDS):
            raise Exception(f"Playwright error: {error_msg}")


async def _dispatch_pt_email_build(task_gid: str, raw_task: dict, brand_code: str) -> None:
    """Build a plain-text email campaign in Braze or Klaviyo for a single Asana task.

    Braze brands (HAV/CZ/ID/BUR/STF/TRADE): Playwright-based PT builder.
    Klaviyo brand (TI): API-based builder that posts its own Asana comment.
    After a successful build, updates the task status to 'Ready for QA'.
    """
    _KLAVIYO_BRANDS = {"TI"}
    task_name = raw_task.get("name", task_gid)

    if brand_code in _KLAVIYO_BRANDS:
        # --- Klaviyo path (TI) ---
        # build_klaviyo_email_campaign() writes the Klaviyo edit URL to Asana
        # and posts its own comment (with URL + any missing-subject/inferred-link warnings).
        # We only need to update the status afterward.
        from create_klaviyo_email import build_klaviyo_email_campaign

        logger.info(
            f"PT Email (Klaviyo) task: [{brand_code}] {task_name} (gid={task_gid})"
        )
        edit_url = await asyncio.to_thread(
            build_klaviyo_email_campaign,
            brand=brand_code,
            asana_gid=task_gid,
        )
        success = edit_url is not None
        braze_url = edit_url  # Klaviyo edit URL; comment already posted by builder

    else:
        # --- Braze path (HAV, CZ, ID, BUR, STF, TRADE) ---
        from build_pt_campaign import (
            fetch_task_by_gid as _pt_fetch_task,
            parse_asana_task as _pt_parse_task,
            load_brand_config as _pt_load_config,
            build_single_campaign as _pt_build,
        )
        from orchestrate_sms import post_campaign_created_comment

        logger.info(
            f"PT Email (Braze) task: [{brand_code}] {task_name} (gid={task_gid})"
        )

        # Fetch the full task — webhook raw_task may lack notes and custom field opt_fields
        full_task_raw = await asyncio.to_thread(_pt_fetch_task, task_gid)
        if not full_task_raw:
            logger.error(
                f"Could not fetch full task data for {task_gid} — aborting PT build"
            )
            return

        parsed_task = await asyncio.to_thread(_pt_parse_task, full_task_raw)
        if not parsed_task:
            logger.error(
                f"PT task {task_gid} ({task_name}) could not be parsed "
                f"(missing brand/channel/body?) — skipping"
            )
            return

        global_config = await asyncio.to_thread(_pt_load_config)

        result = await _pt_build(
            task=parsed_task,
            global_config=global_config,
            dry_run=False,
            auto_confirm=True,
            headless=True,
            skip_comment=True,
        )

        success = result.get("success") and bool(result.get("braze_url"))
        braze_url = result.get("braze_url")

        if success:
            orchestrator_config = global_config.get("orchestrator", {})
            patched_orchestrator = {
                **orchestrator_config,
                "comment_template": (
                    "this email campaign has been automatically created in {platform} "
                    "and is ready for review and scheduling.\n\n"
                    "Campaign link: {braze_url}"
                ),
            }
            assignee_gid = (raw_task.get("assignee") or {}).get("gid")
            post_campaign_created_comment(
                task_gid=task_gid,
                braze_url=braze_url,
                brand_code=brand_code,
                orchestrator_config=patched_orchestrator,
                assignee_gid=assignee_gid,
            )
        else:
            errors = result.get("errors", [])
            error_msg = '; '.join(errors) if errors else 'unknown error'
            logger.error(f"Braze PT email build failed for task {task_gid}: {error_msg}")
            if any(kw in error_msg.lower() for kw in _SESSION_ERROR_KEYWORDS):
                raise Exception(f"Playwright error: {error_msg}")

    # --- Post-build: update Asana status to Ready for QA ---
    if success:
        from build_sms_campaign import update_asana_task_status, STATUS_READY_FOR_QA

        status_ok = await asyncio.to_thread(
            update_asana_task_status, task_gid, STATUS_READY_FOR_QA
        )
        if status_ok:
            logger.info(
                f"PT Email build complete: [{brand_code}] {task_name} → Ready for QA "
                f"({braze_url})"
            )
        else:
            logger.warning(
                f"PT Email built but status update failed for task {task_gid}"
            )
