"""
build_lock.py — Cross-process, per-task build lock for the Braze auto-build pipeline.

Two independent processes trigger campaign builds from the same Asana "Ready to Code"
status:

  * com.havenly.webhook-server   — the live Asana-webhook handler + its Poll-RTC fallback
  * com.havenly.poll-ready-tasks — the 15-minute LaunchAgent fallback poller

Each has its own *in-process* dedup (webhook: the ``_processing`` set; poller: a re-fetch
"skip if the Braze Campaign Link field is already set" guard). Nothing coordinates the two
processes with each other. That guard only becomes effective once a build FINISHES and
writes the link field — and a PT/designed build takes several minutes. If the second
process starts inside that window it reads an empty link field and builds a duplicate
campaign.

Observed 2026-07-06 on ID "Warehouse Sale Reminder - PT": the webhook Poll-RTC started a
build at 16:46:15Z; the poller LaunchAgent fired at 16:48:51Z, saw the link field still
empty (webhook build not finished), and built a second campaign. Two campaigns for the
same task, 95s apart.

This module provides a file-based lock keyed on the Asana task GID. A builder acquires the
lock BEFORE building and releases it after, so a second process that starts mid-build finds
the lock held and skips. Both services run on the same host, so a lock file on the local
filesystem is a valid cross-process mutex. The lock self-heals via a TTL: if a builder
crashes without releasing, the stale lock is reclaimed after DEFAULT_TTL_SECONDS.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Both services run on the same host; /tmp is where the pipeline already writes its logs.
LOCK_DIR = Path(os.environ.get("BRAZE_BUILD_LOCK_DIR", "/tmp/braze_build_locks"))

# Must exceed any real build (PT ~4 min; designed email + Playwright + image uploads up to
# ~10 min) so a legitimate in-flight build is never reclaimed as "stale", yet be short
# enough that a crashed builder's orphaned lock is reclaimed within a couple of poll cycles.
DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes


def _lock_path(task_gid: str) -> Path:
    return LOCK_DIR / f"{task_gid}.lock"


def _is_stale(path: Path, ttl_seconds: float) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > ttl_seconds


def try_acquire(task_gid: str, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> bool:
    """Atomically claim the build lock for ``task_gid``. Returns True if acquired.

    Uses ``O_CREAT | O_EXCL`` for an atomic create-if-absent, so exactly one caller wins
    when several race. A lock file older than ``ttl_seconds`` is treated as a crashed
    builder's orphan and reclaimed.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = _lock_path(task_gid)

    # Reclaim a stale lock left behind by a crashed builder.
    if _is_stale(path, ttl_seconds):
        logger.warning(
            f"[build-lock] Reclaiming stale lock for {task_gid} (age > {ttl_seconds}s)"
        )
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, f"{os.getpid()} {time.time():.0f}\n".encode())
    finally:
        os.close(fd)
    return True


def release(task_gid: str) -> None:
    """Release the build lock for ``task_gid``. Safe to call even if not held."""
    with contextlib.suppress(FileNotFoundError):
        _lock_path(task_gid).unlink()


@contextlib.contextmanager
def build_lock(task_gid: str, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> Iterator[bool]:
    """Context manager wrapping :func:`try_acquire` / :func:`release`.

    Yields ``True`` if the lock was acquired (caller should build) or ``False`` otherwise
    (another process is already building this task — caller should skip). The lock is only
    released if THIS ``with`` block acquired it, so a losing caller never deletes the
    winner's lock file.

    Usage::

        with build_lock(task_gid) as acquired:
            if not acquired:
                logger.info(f"Task {task_gid} is being built by another process — skipping")
                return
            ... build ...
    """
    acquired = try_acquire(task_gid, ttl_seconds)
    try:
        yield acquired
    finally:
        if acquired:
            release(task_gid)
