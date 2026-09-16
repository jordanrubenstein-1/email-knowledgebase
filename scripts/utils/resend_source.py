"""
Resend detection + source-campaign resolution for auto-briefed email tasks.

Two jobs, both driven by the standing rule in CLAUDE.md ("Resend / Re-run Sends"):

1. Detect that a calendar row is a re-run of a past send, and fix the creative
   direction wording. The AI kept writing "Resend to non-openers — ..." which is
   wrong twice over: these sends go to the previous campaign's FULL audience
   (openers included), and the creative is rebuilt fresh rather than literally
   re-sent. `normalize_resend_direction()` rewrites that to
   "Re-run of past campaign with fresh creative — ...".

2. Resolve WHICH past send it re-runs, so the brief can link to it. Returns the
   source campaign's exact name, send date, subject, and platform campaign link.

Why the Asana link isn't resolved here: campaign YAMLs carry no `asana:` block
(verified 2026-08-19 — zero files have one), so the source ticket has to be looked
up through the Asana API by name at briefing time. `asana_search_name` is the
cleaned string to search with. Same story for the platform link on Braze brands:
the YAML `id` is the campaign *API* ID (UUID), not the 24-hex internal ID that
dashboard URLs use, so a dashboard URL cannot be synthesized from it — take it from
the source task's own "Braze Campaign Link" field (GID 1210710306792280), which the
campaign builders populate. Klaviyo IS synthesizable from `klaviyo_campaign_id`.

Usage:
    uv run python scripts/utils/resend_source.py --brand TI --task-name "Perfect Pairs Resend"
    uv run python scripts/utils/resend_source.py --brand TI --task-name "Perfect Pairs Resend" --before 2026-08-22 --top 3
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

import yaml

try:
    from .braze_datashare import APP_GROUP_IDS
except ImportError:  # direct script execution
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from braze_datashare import APP_GROUP_IDS  # type: ignore

CAMPAIGNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "campaigns")

# Brands whose sends live in Klaviyo rather than Braze.
KLAVIYO_BRANDS = {"TI", "TE"}

# The correct opener for a re-run send's creative direction.
RESEND_DIRECTION_PREFIX = "Re-run of past campaign with fresh creative — "

# Signals in a calendar row / task name that this is a re-run of a past send.
# "Refresh/Resend" is an actual Content Type value on the marketing calendar.
_RESEND_SIGNAL_RE = re.compile(
    r"(?:\bre-?sends?\b|\bre-?send(?:ing)?\b|\bre-?runs?\b|refresh\s*/\s*re-?send"
    r"|\bpull\s+re-?send\b|\bre-?use\s+(?:the\s+)?(?:past|prior|previous|old)\b)",
    re.I,
)

# The wrong-but-plausible leading clause the AI produces, e.g.
#   "Resend to non-openers — pair bedding essentials with..."
#   "Resend to non openers:"
#   "Resend of the Perfect Pairs email to non-openers -"
_WRONG_LEADING_CLAUSE_RE = re.compile(
    r"^\s*re-?send(?:ing)?\b[^—–:\-]{0,80}?non[\s-]?openers?\b[^—–:]{0,40}?\s*(?:[—–:]|\s-\s)\s*",
    re.I,
)

# A bare leading "Resend — " / "Resend of X — " with no non-opener claim.
_BARE_LEADING_RESEND_RE = re.compile(
    r"^\s*re-?send(?:ing)?\b(?:\s+of\b[^—–:]{0,60})?\s*(?:[—–:]|\s-\s)\s*",
    re.I,
)

# Mid-sentence audience claim to delete outright — these sends are not non-opener-only.
_NON_OPENER_PHRASE_RE = re.compile(
    r"\s*(?:,\s*)?(?:sent\s+)?(?:out\s+)?to\s+(?:the\s+)?non[\s-]?openers?(?:\s+(?:only|of\s+"
    r"(?:the\s+)?(?:previous|prior|original|past)(?:\s+\w+)?))?",
    re.I,
)

_NON_OPENER_RESIDUE_RE = re.compile(r"non[\s-]?opener", re.I)

# Campaign records that must never be offered as a resend source.
_EXCLUDED_NAME_RE = re.compile(r"\[delete\]|\btest[_\s]send\b|\bdo[_\s]not[_\s]use\b", re.I)

# Words stripped from a task name before matching it against past campaign names.
_TASK_NAME_NOISE_RE = re.compile(
    r"\b(?:re-?send|re-?run|refresh|promo|sms|push|copy|designed?|plain[\s-]?text|pt|em|email"
    r"|batch|blast|final|updated?|new|v\d+)\b",
    re.I,
)

# Generic email words that shouldn't drive a match on their own.
_GENERIC_TOKENS = {
    "sale", "reminder", "extension", "last", "chance", "hours", "announcement",
    "launch", "arrivals", "send", "the", "and", "for", "with", "event", "day",
    "highlight", "feature", "edit", "spotlight", "roundup", "round", "up",
}


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value).strip())
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


def _campaign_send_date(data: dict) -> Optional[date]:
    """Send date per CLAUDE.md: dates.send_date is canonical, first_sent is a fallback."""
    dates = data.get("dates") or {}
    return _parse_date(dates.get("send_date")) or _parse_date(dates.get("first_sent"))


def detect_resend(record: Optional[Dict[str, str]] = None,
                  task_name: str = "") -> Optional[str]:
    """Return the matched resend signal snippet, or None.

    Scans the calendar row's story/notes/content-type plus the task name. `record`
    is the parsed sheet row used everywhere else in create_calendar_tasks.py.
    """
    haystacks: List[str] = []
    if task_name:
        haystacks.append(task_name)
    for key in ("story", "notes", "content_type", "format", "promo"):
        val = (record or {}).get(key)
        if val:
            haystacks.append(str(val))
    for text in haystacks:
        m = _RESEND_SIGNAL_RE.search(text)
        if m:
            return m.group(0)
    return None


def normalize_resend_direction(direction: str) -> str:
    """Rewrite a re-run send's creative direction to the correct framing.

    Strips the AI's "Resend to non-openers — " style opener (and any mid-sentence
    non-opener audience claim), then applies RESEND_DIRECTION_PREFIX.

    >>> normalize_resend_direction("Resend to non-openers — pair bedding with beds.")
    'Re-run of past campaign with fresh creative — pair bedding with beds.'
    """
    text = (direction or "").strip()
    if not text:
        return text

    if text.lower().startswith(RESEND_DIRECTION_PREFIX.strip().lower()[:20]):
        return text  # already normalized

    text = _WRONG_LEADING_CLAUSE_RE.sub("", text, count=1)
    text = _BARE_LEADING_RESEND_RE.sub("", text, count=1)
    text = _NON_OPENER_PHRASE_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"^[—–\-:,]\s*", "", text).strip()

    if _NON_OPENER_RESIDUE_RE.search(text):
        print(
            "[WARN] resend direction still mentions non-openers after normalization; "
            f"reword by hand: {text!r}",
            file=sys.stderr,
        )

    if not text:
        return RESEND_DIRECTION_PREFIX.rstrip(" —")
    # Lowercase a leading capital so it reads as a continuation of the prefix,
    # unless the first word is a proper noun / acronym already.
    first, _, rest = text.partition(" ")
    if first[:1].isupper() and not first.isupper() and first[1:].islower():
        text = first[0].lower() + first[1:] + (" " + rest if rest else "")
    return RESEND_DIRECTION_PREFIX + text


def clean_task_name_for_search(task_name: str) -> str:
    """Strip channel/type/resend noise so the name matches the ORIGINAL send.

    >>> clean_task_name_for_search("SMS: Perfect Pairs Resend")
    'Perfect Pairs'
    """
    name = re.sub(r"^\s*(?:SMS|Push|PT|Promo)\s*:\s*", "", task_name or "", flags=re.I)
    name = re.sub(r"\((?:re-?send|refresh)[^)]*\)", " ", name, flags=re.I)
    name = _TASK_NAME_NOISE_RE.sub(" ", name)
    name = re.sub(r"[-–—_]+", " ", name)
    return re.sub(r"\s{2,}", " ", name).strip()


def _tokens(text: str) -> set:
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text or "")}


# Structural scaffolding stripped from a campaign name to get a display title:
# type code, channel, brand, design type, HAV audience, and the file markers that
# show up in nearly every TI name. Deliberately NOT stripped: content-type codes
# that carry real meaning to a human (BIS, CLR, GTL, UGC, RTS, CS, EA, BNDL, POTM).
# parse_campaign_name() is not used for this — it silently leaves the brand and
# design code in `description` when a brand isn't in its own code table (real names
# use BUR where the convention says BW), and bails entirely on pre-convention names
# with no channel segment.
_STRUCTURAL_NAME_TOKENS = {
    # Types
    "P", "OT", "CX", "WTL", "SEG", "TRG", "TRIG",
    # Channels
    "EM", "SMS", "PUSH",
    # Brands (convention codes + the variants real names actually use)
    "HAV", "CZ", "SF", "STF", "ID", "TI", "BW", "BUR", "TE", "TRADE", "XBRAND", "X",
    # Design types
    "D", "H", "PT",
    # HAV audience
    "PC", "CONV",
    # File markers
    "PF", "PR",
}


def campaign_display_title(campaign_name: str) -> str:
    """Human-readable title for a campaign name, for the no-link fallback reference.

    >>> campaign_display_title("P_EM_2025_08_20_BUR_D_Pillow_Pairings")
    'Pillow Pairings'
    >>> campaign_display_title("P_2025_05_08_D_TI_Pattern_Pairings")
    'Pattern Pairings'
    >>> campaign_display_title("Good Things Come in Pairs - 6/22/23")
    'Good Things Come in Pairs'
    >>> campaign_display_title("03-10-26 | New Arrivals | Shopping")
    'New Arrivals — Shopping'
    """
    name = (campaign_name or "").strip()
    if not name:
        return ""

    # TE-style pipe-delimited names: "03-10-26 | New Arrivals | Shopping"
    if "|" in name:
        name = re.sub(r"\b\d{1,4}[-/]\d{1,2}[-/]\d{2,4}\b", " ", name)
        segments = [s.strip(" -–—_|") for s in name.split("|")]
        return re.sub(r"\s{2,}", " ", " — ".join(s for s in segments if s))

    if "_" in name:
        tokens = [t for t in name.split("_") if t]
        kept: List[str] = []
        skip_date_parts = 0
        for token in tokens:
            if skip_date_parts and re.fullmatch(r"\d{1,2}", token):
                skip_date_parts -= 1
                continue
            skip_date_parts = 0
            if re.fullmatch(r"20\d{2}", token):
                skip_date_parts = 2  # the MM and DD that follow the year
                continue
            if token.upper() in _STRUCTURAL_NAME_TOKENS:
                continue
            kept.append(token)
        if kept:
            return re.sub(r"\s{2,}", " ", " ".join(kept))

    # Legacy names with a trailing date: "Perfect Match - 2/14/23"
    name = re.sub(r"\b\d{1,4}[-/]\d{1,2}[-/]\d{2,4}\b", " ", name)
    return re.sub(r"\s{2,}", " ", name.replace("_", " ").strip(" -–—:"))


def format_send_date_short(send_date: str) -> str:
    """ISO date -> M/D/YY, the format the team writes dates in.

    >>> format_send_date_short("2025-08-20")
    '8/20/25'
    """
    parsed = _parse_date(send_date)
    if not parsed:
        return ""
    return f"{parsed.month}/{parsed.day}/{parsed.strftime('%y')}"


def format_campaign_reference(source: Dict[str, object]) -> str:
    """Text reference used when no clickable campaign link is available.

    Braze dashboard URLs can't be synthesized from the knowledgebase (see module
    docstring), so a Braze source gets a date + title reference to search on rather
    than the field being dropped:

    >>> format_campaign_reference({"platform": "braze", "send_date": "2025-08-20",
    ...                            "campaign_name": "P_EM_2025_08_20_BUR_D_Pillow_Pairings"})
    'Braze Campaign: 8/20/25 Pillow Pairings'
    """
    platform = "Klaviyo" if str(source.get("platform") or "").lower() == "klaviyo" else "Braze"
    parts = [
        format_send_date_short(str(source.get("send_date") or "")),
        campaign_display_title(str(source.get("campaign_name") or "")),
    ]
    detail = " ".join(p for p in parts if p)
    return f"{platform} Campaign: {detail}" if detail else ""


def klaviyo_campaign_url(campaign_id: str) -> str:
    """Overview URL — the read-only view, correct for a reference link in a brief."""
    return f"https://www.klaviyo.com/campaign/{campaign_id}/overview"


def braze_campaigns_url(brand: str) -> Optional[str]:
    """Workspace campaign list. NOT a per-campaign deep link — see module docstring."""
    app_group_id = APP_GROUP_IDS.get(brand.upper())
    if not app_group_id:
        return None
    return f"https://dashboard-07.braze.com/engagement/campaigns/{app_group_id}"


def find_resend_source(brand: str,
                       task_name: str,
                       before_date: Optional[str] = None,
                       top: int = 1) -> List[Dict[str, object]]:
    """Find the past campaign(s) a re-run send is based on, best match first.

    Matching: content-token overlap with the cleaned task name, generic tokens
    weighted lower, recency as the tiebreaker. Only campaigns that actually sent
    (a resolvable send date) and, when `before_date` is given, sent before it.
    """
    brand = brand.upper()
    cleaned = clean_task_name_for_search(task_name)
    want = _tokens(cleaned)
    content_tokens = want - _GENERIC_TOKENS
    cutoff = _parse_date(before_date)

    scored: List[Dict[str, object]] = []
    for path in glob.glob(os.path.join(CAMPAIGNS_DIR, "*.yaml")):
        try:
            with open(path, errors="ignore") as fh:
                data = yaml.safe_load(fh)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("brand") != brand:
            continue
        if data.get("channel") not in (None, "email", "multi"):
            continue

        send_date = _campaign_send_date(data)
        if not send_date or (cutoff and send_date >= cutoff):
            continue

        name = str(data.get("name") or "")
        # Real data carries retired duplicates ("[delete]P_EM_2025_08_23_BW_D_...")
        # and internal test sends — never offer either as a resend source.
        if _EXCLUDED_NAME_RE.search(name):
            continue
        have = _tokens(name)
        content_hits = content_tokens & have
        generic_hits = (want & _GENERIC_TOKENS) & have
        if not content_hits:
            continue

        score = len(content_hits) * 10 + len(generic_hits)
        # Reward covering the whole cleaned name (a true same-name original).
        if content_tokens and content_tokens <= have:
            score += 25
        # Prefer the original over another re-run of it.
        if _RESEND_SIGNAL_RE.search(name):
            score -= 5

        sends = data.get("sends") or []
        subject = ""
        for s in sends:
            if isinstance(s, dict) and s.get("subject"):
                subject = str(s["subject"]).strip()
                break

        cid = data.get("klaviyo_campaign_id")
        is_klaviyo = bool(cid) or brand in KLAVIYO_BRANDS
        scored.append({
            "campaign_name": name,
            "send_date": send_date.isoformat(),
            "subject": subject,
            "platform": "klaviyo" if is_klaviyo else "braze",
            "campaign_url": klaviyo_campaign_url(str(cid)) if cid else None,
            "campaign_api_id": str(data.get("id") or "").replace("klaviyo-", ""),
            "asana_search_name": cleaned,
            "yaml_file": os.path.relpath(path, os.path.join(CAMPAIGNS_DIR, "..")),
            "performance": data.get("performance_summary") or {},
            "_score": score,
            "_date": send_date,
        })

    scored.sort(key=lambda c: (c["_score"], c["_date"]), reverse=True)
    for c in scored:
        c.pop("_score", None)
        c.pop("_date", None)
    return scored[:max(1, top)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Find the past send a re-run brief is based on")
    parser.add_argument("--brand", required=True, help="Brand code (TI, CZ, BUR, STF, ID, HAV, TE)")
    parser.add_argument("--task-name", required=True, help="Asana task name, e.g. 'Perfect Pairs Resend'")
    parser.add_argument("--before", help="Only consider sends before this date (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=1, help="How many candidates to show")
    args = parser.parse_args()

    matches = find_resend_source(args.brand, args.task_name, args.before, args.top)
    if not matches:
        print(
            f"No past {args.brand} send matches '{clean_task_name_for_search(args.task_name)}'.\n"
            "Do NOT invent a source — confirm with the calendar owner what this re-runs.",
            file=sys.stderr,
        )
        sys.exit(1)

    for i, m in enumerate(matches, 1):
        perf = m.get("performance") or {}
        print(f"[{i}] {m['campaign_name']}")
        print(f"    sent:     {m['send_date']}")
        print(f"    subject:  {m['subject']}")
        print(f"    platform: {m['platform']}")
        print(f"    link:     {m['campaign_url'] or '(none — use the reference below)'}")
        if not m["campaign_url"]:
            print(f"    ref:      ({format_campaign_reference(m)})")
        print(f"    api id:   {m['campaign_api_id']}")
        if perf.get("total_sends"):
            print(f"    perf:     {perf.get('total_sends')} sends, "
                  f"open {perf.get('open_rate')}, click {perf.get('click_rate')}")
        print(f"    yaml:     {m['yaml_file']}")
        print(f"    -> search Asana for a task named like: {m['asana_search_name']!r}")


if __name__ == "__main__":
    main()
