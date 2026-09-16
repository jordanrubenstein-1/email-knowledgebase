"""
Persisted per-task consecutive-failure counts for the campaign auto-builders.

Why this exists
---------------
The "already built" guards in the build path only recognise builds the service
performed itself — they look for the Braze campaign link it writes back, or its
own auto-build comment. A campaign a human built and launched by hand leaves
neither. If that task is also left sitting in Asana at Task Status = Ready to
Code, the Ready-to-Code pollers re-queue it every ~35 minutes indefinitely.

Confirmed 2026-09-13 on two CZ Labor Day Event Ext tasks: 75 and 42 consecutive
failures, every one the same malformed-brief error, both for campaigns that had
already launched. Nothing surfaced to a human.

Counts are persisted rather than held in memory because the webhook server
restarts on every scripts/braze_automation/ commit, which would reset an
in-memory counter long before any cap was reached.

Shared by both build paths on purpose — scripts/braze_automation/webhook_server.py
(instant, webhook-driven) and scripts/braze_automation/poll_ready_tasks.py (the
15-minute LaunchAgent safety net) — so the cap cannot be enforced in one and
silently missing from the other.
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
RETRY_STATE_PATH = PROJECT_ROOT / "data" / "build_retry_state.yaml"

# ~14 hours of poller retries at the observed 35-minute interval. Deliberately
# generous: a transient cause (expired Braze session, Asana API blip, laptop
# asleep mid-build) must never trip it — only a genuinely stuck task should.
BUILD_RETRY_CAP = 25

_lock = threading.Lock()
_task_names: dict[str, str] = {}


def remember_task_name(task_gid: str, task_name: str) -> None:
    """Cache a task's name so failure sites without the task dict in scope can label state."""
    if task_name:
        _task_names[task_gid] = task_name


def load_state() -> dict:
    """Read the persisted failure counts. Never raises."""
    try:
        with open(RETRY_STATE_PATH) as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning(f"Could not read {RETRY_STATE_PATH} — treating as empty", exc_info=True)
        return {}


def save_state(state: dict) -> None:
    """Write the persisted failure counts. Never raises."""
    try:
        RETRY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RETRY_STATE_PATH, "w") as fh:
            yaml.safe_dump(state, fh, sort_keys=True)
    except Exception:
        logger.warning(f"Could not write {RETRY_STATE_PATH}", exc_info=True)


def get_entry(task_gid: str) -> dict:
    with _lock:
        return dict(load_state().get(task_gid) or {})


def failure_count(task_gid: str) -> int:
    return int(get_entry(task_gid).get("failures", 0))


def is_capped(task_gid: str) -> bool:
    return failure_count(task_gid) >= BUILD_RETRY_CAP


def record_failure(task_gid: str, task_name: str, error_msg: str) -> int:
    """Increment and persist this task's consecutive-failure count. Returns the new count."""
    task_name = task_name or _task_names.get(task_gid, "")
    with _lock:
        state = load_state()
        entry = state.get(task_gid) or {}
        count = int(entry.get("failures", 0)) + 1
        state[task_gid] = {
            "failures": count,
            "name": task_name or entry.get("name", ""),
            "last_error": (error_msg or "")[:300],
            "last_failed_at": datetime.now(timezone.utc).isoformat(),
            "capped_notified": bool(entry.get("capped_notified", False)),
        }
        save_state(state)
    return count


def clear(task_gid: str) -> None:
    """Drop this task's failure count — it built, or moved out of Ready to Code."""
    with _lock:
        state = load_state()
        if task_gid in state:
            del state[task_gid]
            save_state(state)


def mark_capped_notified(task_gid: str) -> None:
    """Record that a human has been told, so the cap comment is posted only once."""
    with _lock:
        state = load_state()
        if task_gid in state:
            state[task_gid]["capped_notified"] = True
            save_state(state)
