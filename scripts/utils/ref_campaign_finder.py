"""
Reference Campaign Finder

Finds the best past CZ designed campaign to use as "Ref Braze Campaign" when
briefing a new designed email task in Asana.

Matching is hierarchical:
  Pass 1 — content keyword match (descriptive words: Rug, Archive, Bedding, …)
  Pass 2 — generic keyword match (Sale, Reminder, Extension, …)
  Pass 3 — most recent campaign (fallback)

Within each pass, campaigns that match the requested Figma template letter
(from template_inspiration in the YAML) are sorted above non-matching ones.
Recency (dates.last_sent or dates.first_sent) is the final tiebreaker.

Usage:
    uv run python scripts/utils/ref_campaign_finder.py --task-name "Rug Roundup"
    uv run python scripts/utils/ref_campaign_finder.py --task-name "Archive Sale" --template "A"
    uv run python scripts/utils/ref_campaign_finder.py --task-name "Archive" --top 3
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

CAMPAIGNS_DIR = Path(__file__).parent.parent.parent / "campaigns"

# Generic email words — only used for matching when no content keywords match.
GENERIC_STOPLIST = {
    "sale", "reminder", "extension", "last", "chance", "final", "hours",
    "announcement", "launch", "new", "arrivals", "email", "send", "blast",
    "the", "and", "for", "with",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date() if hasattr(dt, "date") else dt
        except ValueError:
            pass
    # Try dateutil-style fallback: just grab YYYY-MM-DD prefix
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _campaign_date(campaign: dict) -> date | None:
    dates = campaign.get("dates") or {}
    return _parse_date(dates.get("last_sent") or dates.get("first_sent"))


def _template_letter(campaign: dict) -> str | None:
    """Return the single-letter template code from template_inspiration, or None."""
    ti = campaign.get("template_inspiration")
    if not ti:
        return None
    m = re.match(r"([A-Za-z])\b", str(ti).strip())
    return m.group(1).upper() if m else None


def _task_words(task_name: str) -> list[str]:
    """Split task name into lowercase words, stripping punctuation."""
    return [w.lower() for w in re.split(r"[\s\-_/]+", task_name) if re.sub(r"[^a-z]", "", w.lower())]


def _campaign_tokens(name: str) -> set[str]:
    """Split campaign name on underscores → lowercase token set."""
    return {t.lower() for t in name.split("_") if t}


def load_candidates(brand: str = "CZ") -> list[dict]:
    """Load all past designed email campaigns for the given brand."""
    today = date.today()
    candidates = []
    for path in CAMPAIGNS_DIR.glob("*.yaml"):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not data:
            continue
        if data.get("brand") != brand:
            continue
        if data.get("channel") != "email":
            continue
        name = data.get("name", "")
        if "_D_" not in name:
            continue
        if not name.startswith("P_"):
            continue
        sent = _campaign_date(data)
        if not sent or sent > today:
            continue
        data["_sent_date"] = sent
        candidates.append(data)
    return candidates


def find_ref_campaign(
    task_name: str,
    template: Optional[str] = None,
    brand: str = "CZ",
    top_n: int = 1,
) -> list[dict]:
    """
    Return up to top_n past designed campaigns ranked by the matching logic.

    Each returned item is a campaign dict with an extra '_match_info' key
    containing a human-readable explanation of why it was selected.
    """
    candidates = load_candidates(brand)
    if not candidates:
        return []

    words = _task_words(task_name)
    template_letter = template.upper() if template else None

    content_words = [w for w in words if w not in GENERIC_STOPLIST and len(w) > 2]
    generic_words = [w for w in words if w in GENERIC_STOPLIST]

    def score(campaign: dict, keyword_tier: int, matched_keywords: list[str]) -> tuple:
        tmpl = _template_letter(campaign)
        template_match = 1 if (template_letter and tmpl == template_letter) else 0
        recency = campaign["_sent_date"].toordinal()
        return (len(matched_keywords), template_match, recency)

    def rank(pool: list[dict], keyword_tier: int, keyword_pool: list[str]) -> list[dict]:
        results = []
        for c in pool:
            tokens = _campaign_tokens(c.get("name", ""))
            matched = [w for w in keyword_pool if w in tokens]
            if matched:
                c["_matched_keywords"] = matched
                c["_keyword_tier"] = keyword_tier
                c["_score"] = score(c, keyword_tier, matched)
                results.append(c)
        return sorted(results, key=lambda x: x["_score"], reverse=True)

    # Pass 1: content keywords
    ranked = rank(candidates, 1, content_words)

    # Pass 2: generic keywords (only if pass 1 empty)
    if not ranked:
        ranked = rank(candidates, 2, generic_words)

    # Pass 3: recency fallback
    if not ranked:
        ranked = sorted(candidates, key=lambda c: c["_sent_date"].toordinal(), reverse=True)
        for c in ranked:
            c["_matched_keywords"] = []
            c["_keyword_tier"] = 0
            c["_score"] = (0, 0, c["_sent_date"].toordinal())

    # When a template was requested and keyword matching found candidates,
    # summarise what template data existed across the full keyword-matching pool
    # so the caller knows whether the template argument had any effect.
    keyword_matched = any(c.get("_keyword_tier", 0) > 0 for c in ranked)
    template_pool_note: str | None = None
    if template_letter and ranked and keyword_matched:
        pool = ranked  # full keyword pool, not sliced
        with_data = [c for c in pool if _template_letter(c) is not None]
        matched = [c for c in with_data if _template_letter(c) == template_letter]
        total = len(pool)
        if matched:
            template_pool_note = f"template {template_letter} matched"
        elif with_data:
            found_letters = sorted({_template_letter(c) for c in with_data})
            template_pool_note = (
                f"no template-{template_letter} match in {total} candidates "
                f"(found: {', '.join(found_letters)})"
            )
        else:
            template_pool_note = f"no template data in {total} candidates"

    # Attach human-readable match info
    for c in ranked[:top_n]:
        kws = c.get("_matched_keywords", [])
        tier = c.get("_keyword_tier", 0)
        tmpl = _template_letter(c)
        parts = []
        if kws:
            tier_label = "keywords" if tier == 1 else "generic"
            parts.append(f"{tier_label}: {', '.join(kws)}")
        if template_pool_note:
            parts.append(template_pool_note)
        elif tmpl:
            parts.append(f"template: {tmpl}")
        parts.append(f"sent: {c['_sent_date']}")
        c["_match_info"] = "; ".join(parts) if parts else "fallback (most recent)"

    return ranked[:top_n]


def main() -> None:
    parser = argparse.ArgumentParser(description="Find a reference CZ designed campaign")
    parser.add_argument("--task-name", required=True, help="New task name or description")
    parser.add_argument("--template", default=None, help="Figma template letter (e.g. 'A')")
    parser.add_argument("--top", type=int, default=1, metavar="N", help="Return top N results")
    parser.add_argument("--brand", default="CZ", help="Brand code (default: CZ)")
    args = parser.parse_args()

    results = find_ref_campaign(
        task_name=args.task_name,
        template=args.template,
        brand=args.brand,
        top_n=args.top,
    )

    if not results:
        print("ERROR: No past designed campaigns found in campaigns/ for brand", args.brand, file=sys.stderr)
        sys.exit(1)

    if args.top == 1:
        c = results[0]
        if args.template:
            print(f"{c['name']}  [{c['_match_info']}]")
        else:
            print(c["name"])
    else:
        for i, c in enumerate(results, 1):
            print(f"{i}. {c['name']}  [{c['_match_info']}]")


if __name__ == "__main__":
    main()
