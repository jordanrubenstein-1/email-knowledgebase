#!/usr/bin/env python3
"""
Backfill [AI Brief] separator and fix bare Subject/Preheader labels on Asana tasks.

For each task:
  1. Plain notes: prepend "[AI Brief]" if not already present; rename bare
     "Subject:" / "Preheader:" lines to the standard "SL/PH Suggestions (AI generated):" format.
  2. html_notes: prepend "[AI Brief]" right after the opening <body> tag if not already present;
     rename any bare "<strong>Subject:</strong>" / "<strong>Preheader:</strong>" patterns.

Usage:
    uv run python scripts/backfill_ai_brief_label.py --dry-run
    uv run python scripts/backfill_ai_brief_label.py
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_WORKSPACE_GID = "5257710284167"

AI_BRIEF_MARKER = "[AI Brief]"

# All 80 task GIDs to update (Awaiting Creative, due 2026-06-01+, excl. CZ and TE)
TASK_GIDS = [
    # --- Batch 2: due 2026-06-23+ (excl. CZ, TE, and the 80 already updated) ---
    "1215192740630374",
    "1215155010509339",
    "1215191375141222",
    "1215192740385298",
    "1215155029087605",
    "1215191310001908",
    "1215155095148401",
    "1215155095825197",
    "1215192740516325",
    "1215191256594598",
    "1215041215891251",
    "1215191651435375",
    "1215193909351034",
    "1215192750531593",
    "1215191310127841",
    "1215191273088066",
    "1215154989400859",
    "1215155047591512",
    "1215041375682519",
    "1215192750783415",
    "1215191176531732",
    "1215194050751260",
    "1215192826155666",
    "1215192874366282",
    "1215155096270476",
    "1215191256608015",
    "1215155011511724",
    "1215192751237788",
    "1215191375464861",
    "1215191225575038",
    "1215192874846719",
    "1215161085000123",
    "1215191310762081",
    "1215192842525822",
    "1215192875228518",
    "1215191310884044",
    "1215192751536843",
    "1215154806462996",
    "1215191273195002",
    "1215192875389719",
    "1215191310671677",
    "1215191401518667",
    "1215192827037366",
    "1215192741842929",
    "1215192741586346",
    "1215191284984435",
    "1215192752223993",
    "1215191375817156",
    "1215192875803693",
    "1215191375427218",
    "1215192975800447",
    "1215192876225310",
    "1215192875948316",
    "1215191310912463",
    "1215191375574408",
    "1215192876470530",
    "1215192843054535",
    "1215191401524645",
    "1215191401636040",
    "1215192875727619",
    "1215191310670631",
    "1215194075801181",
    "1215194156858316",
    "1215194156739592",
    "1215194053701472",
    "1215194167525013",
]

_UNUSED_BATCH1 = [
    "1214210747942668",
    "1215041043092971",
    "1214163795545838",
    "1214210722183865",
    "1215154555469062",
    "1214163987271345",
    "1215041042997729",
    "1215192693645512",
    "1215041043736437",
    "1215154490834763",
    "1215154648107536",
    "1215192693645511",
    "1215154582255256",
    "1215191284277225",
    "1215191132699030",
    "1215154647652531",
    "1215156368777977",
    "1215156248794596",
    "1215156248794590",
    "1215197913359631",
    "1215154606000787",
    "1215191309876770",
    "1215041248629549",
    "1215192738388025",
    "1215191133476190",
    "1215154706242031",
    "1215160594067141",
    "1215154707882952",
    "1215041225868854",
    "1215197913359640",
    "1215194531809828",
    "1215191309821554",
    "1215041089133409",
    "1215192593931611",
    "1215191255865143",
    "1215192593873940",
    "1215154646661956",
    "1215191176298415",
    "1215194254140261",
    "1215192593838018",
    "1214416188151309",
    "1215157824080628",
    "1215041214683931",
    "1215192594157427",
    "1215192693629807",
    "1215154834399554",
    "1215191284692411",
    "1215192720096814",
    "1215192694351431",
    "1215191310122330",
    "1215191310127713",
    "1215041346170476",
    "1215197913359648",
    "1215192594700306",
    "1215191224592395",
    "1215154880905965",
    "1215154935737323",
    "1215155046591802",
    "1215197913359654",
    "1215192738747462",
    "1215191273064563",
    "1215192653591006",
    "1215191273080770",
    "1215191225010707",
    "1215154988968911",
    "1215192653290867",
    "1215192720096836",
    "1215191273035190",
    "1215154966386772",
    "1215154988441754",
    "1215155029518293",
    "1215191651435369",
    "1215192740385276",
    "1215192653790377",
    "1215192695221011",
    "1215191375142362",
    "1215191256487124",
    "1215155133269944",
    "1215155132981155",
    "1215193966872959",
]


def _headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("ASANA_ACCESS_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(endpoint: str, params: dict = None):
    resp = requests.get(
        f"{ASANA_BASE_URL}/{endpoint}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — sleeping {wait}s")
        time.sleep(wait)
        resp = requests.get(
            f"{ASANA_BASE_URL}/{endpoint}",
            headers=_headers(),
            params=params,
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        print(f"  GET error {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json().get("data")


def _put(endpoint: str, data: dict):
    resp = requests.put(
        f"{ASANA_BASE_URL}/{endpoint}",
        headers=_headers(),
        json={"data": data},
        timeout=30,
    )
    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — sleeping {wait}s")
        time.sleep(wait)
        resp = requests.put(
            f"{ASANA_BASE_URL}/{endpoint}",
            headers=_headers(),
            json={"data": data},
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        print(f"  PUT error {resp.status_code}: {resp.text[:200]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Text transformations
# ---------------------------------------------------------------------------

# Matches bare "Subject: ..." lines — lines that start with "Subject:" but
# are NOT already part of an "SL/PH Suggestions" block or inside HTML tags.
_BARE_SUBJECT_RE = re.compile(
    r"^Subject:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)
_BARE_PREHEADER_RE = re.compile(
    r"^Preheader:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


def _fix_plain_notes(notes: str) -> Optional[str]:
    """Return updated notes string, or None if no changes needed."""
    if not notes or not notes.strip():
        return None

    changed = False
    result = notes

    # 1. Add [AI Brief] at the start if not present
    if AI_BRIEF_MARKER not in result:
        result = f"{AI_BRIEF_MARKER}\n\n{result.lstrip()}"
        changed = True

    # 2. Fix bare "Subject: ..." / "Preheader: ..." labels that aren't already
    #    inside an "SL/PH Suggestions (AI generated):" block.
    #    Strategy: find the first bare Subject: line, replace with the standard header.
    #    Then find the immediately following Preheader: line (if any) and fold it in.
    def _replace_subject_block(text: str) -> tuple[str, bool]:
        m = _BARE_SUBJECT_RE.search(text)
        if not m:
            return text, False
        # Check it's not already labelled
        preceding = text[max(0, m.start() - 60): m.start()]
        if "AI generated" in preceding or "SL/PH" in preceding:
            return text, False

        sl_value = m.group(1).strip()
        # Look for a Preheader: line immediately after (within 3 lines)
        after_subject = text[m.end():]
        ph_m = re.match(r"\s*Preheader:\s*(.+)", after_subject, re.IGNORECASE)
        if ph_m:
            ph_value = ph_m.group(1).strip()
            replacement = (
                f"SL/PH Suggestions (AI generated):\nSL: {sl_value}\nPH: {ph_value}"
            )
            end_pos = m.end() + ph_m.end()
        else:
            replacement = f"SL/PH Suggestions (AI generated):\nSL: {sl_value}"
            end_pos = m.end()
        return text[: m.start()] + replacement + text[end_pos:], True

    result, sub_changed = _replace_subject_block(result)
    if sub_changed:
        changed = True

    return result if changed else None


def _fix_html_notes(html: str) -> Optional[str]:
    """Return updated html_notes string, or None if no changes needed."""
    if not html or not html.strip():
        return None

    changed = False
    result = html

    # 1. Add [AI Brief] at the start of the body if not present
    if AI_BRIEF_MARKER not in result:
        if result.lstrip().startswith("<body>"):
            result = result.replace("<body>", f"<body>{AI_BRIEF_MARKER}\n", 1)
        else:
            result = f"{AI_BRIEF_MARKER}\n{result}"
        changed = True

    # 2. Fix bare <strong>Subject:</strong> labels in html_notes
    # Replace  <strong>Subject:</strong> VALUE  →  <strong>SL/PH Suggestions (AI generated):</strong><ul><li>SL: VALUE</li></ul>
    def _fix_html_subject(text: str) -> tuple[str, bool]:
        pat = re.compile(
            r"<strong>Subject:</strong>\s*([^<\n]+)",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if not m:
            return text, False
        # Make sure it's not already inside an SL/PH block
        preceding = text[max(0, m.start() - 100): m.start()]
        if "AI generated" in preceding or "SL/PH" in preceding:
            return text, False
        sl_value = m.group(1).strip()
        # Look for a Preheader: line right after
        after = text[m.end():]
        ph_pat = re.compile(r"\s*<strong>Preheader:</strong>\s*([^<\n]+)", re.IGNORECASE)
        ph_m = ph_pat.match(after)
        if ph_m:
            ph_value = ph_m.group(1).strip()
            replacement = (
                f"<strong>SL/PH Suggestions (AI generated):</strong>"
                f"<ul><li>SL: {sl_value}</li><li>PH: {ph_value}</li></ul>"
            )
            end_pos = m.end() + ph_m.end()
        else:
            replacement = (
                f"<strong>SL/PH Suggestions (AI generated):</strong>"
                f"<ul><li>SL: {sl_value}</li></ul>"
            )
            end_pos = m.end()
        return text[: m.start()] + replacement + text[end_pos:], True

    result, sub_changed = _fix_html_subject(result)
    if sub_changed:
        changed = True

    return result if changed else None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def process_task(gid: str, dry_run: bool) -> bool:
    task = _get(
        f"tasks/{gid}",
        params={
            "opt_fields": "gid,name,notes,html_notes",
        },
    )
    if not task:
        print(f"  [SKIP] Could not fetch task {gid}")
        return False

    name = task.get("name", "(no name)")
    notes = task.get("notes") or ""
    html_notes = task.get("html_notes") or ""

    new_notes = _fix_plain_notes(notes)
    new_html_notes = _fix_html_notes(html_notes)

    if new_notes is None and new_html_notes is None:
        print(f"  [OK]   {name} — no changes needed")
        return True

    changes = []
    if new_notes is not None:
        changes.append("notes")
    if new_html_notes is not None:
        changes.append("html_notes")
    print(f"  [UPD]  {name} — updating: {', '.join(changes)}")

    if dry_run:
        if new_notes:
            print(f"         notes preview: {new_notes[:120].replace(chr(10), ' | ')}...")
        return True

    payload = {}
    if new_notes is not None:
        payload["notes"] = new_notes
    if new_html_notes is not None:
        payload["html_notes"] = new_html_notes

    ok = _put(f"tasks/{gid}", payload)
    if not ok:
        print(f"  [FAIL] {name}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Backfill [AI Brief] label on Asana tasks")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n=== Backfill [AI Brief] label ({mode}) — {len(TASK_GIDS)} tasks ===\n")

    ok_count = 0
    for i, gid in enumerate(TASK_GIDS, 1):
        print(f"[{i:02d}/{len(TASK_GIDS)}] GID {gid}")
        ok = process_task(gid, dry_run=args.dry_run)
        if ok:
            ok_count += 1
        # Gentle rate limiting — Asana allows ~150 req/min for reads, ~60/min for writes
        time.sleep(0.5)

    print(f"\nDone — {ok_count}/{len(TASK_GIDS)} tasks processed successfully.")


if __name__ == "__main__":
    main()
