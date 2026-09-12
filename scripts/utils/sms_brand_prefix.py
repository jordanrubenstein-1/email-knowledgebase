"""Validate the brand prefix on SMS copy before a campaign is built.

Per the SMS Standards in CLAUDE.md, every SMS must carry the brand name either
as a leading prefix ("The Inside: ...") **or** embedded in the body copy
("Final call from The Inside.") — but not both. Copy is written by hand into
the Asana task and passed through to Braze/Klaviyo verbatim, so a copywriter
working from a mislabeled task can hand a send the *wrong* brand's prefix.

That happened on 2026-08-11: three TI SMS tasks whose Lacy copy subtasks had
been stamped `Brand = The Citizenry` by the native Asana rule's fixed-value
action came back with copy starting "The Citizenry:", and two were auto-built
into Klaviyo in the ~3 minutes before the copy was corrected.

This module only checks the *prefix* form. Copy that embeds the brand name mid
-sentence — or leads with a non-brand prefix like "LAST CHANCE:" or
"Reminder:" — is left alone, since both are valid house style.
"""

from __future__ import annotations

import re

# Brand code -> the brand name as it appears in SMS copy (CLAUDE.md SMS
# Standards). Every name here is also used to *detect* a foreign prefix, so
# brands that never share a builder (HAV, TE) still belong in the map.
BRAND_SMS_NAMES: dict[str, str] = {
    "TI":  "The Inside",
    "CZ":  "The Citizenry",
    "BUR": "Burrow",
    "ID":  "Interior Define",
    "STF": "St. Frank",
    "HAV": "Havenly",
    "TE":  "The Expert",
}

# A brand prefix sits at the very front of the message. Cap the candidate
# length so an ordinary sentence that happens to end in a colon
# ("...ends tonight — save up to 25%:") is never read as a prefix.
_MAX_PREFIX_CHARS = 40

_PREFIX_RE = re.compile(rf"^(?P<candidate>[^:\n]{{1,{_MAX_PREFIX_CHARS}}}):")
# Possessive lead-in, e.g. "The Citizenry's Labor Day Event is here: <link>",
# where the first colon falls far past the brand name.
_POSSESSIVE_RE = re.compile(r"^(?P<candidate>.{1,40}?)['’]s\b")


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation/emoji so 'St. Frank' == 'st frank'."""
    text = re.sub(r"^[^A-Za-z]+", "", text.strip())   # leading emoji/symbols
    text = re.sub(r"[.,''‘’\"]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def detect_brand_prefix(body: str) -> str | None:
    """Return the brand CODE whose name leads `body`, or None if no brand prefix.

    None means "no brand prefix present" — either the copy embeds the brand
    later in the sentence, or it leads with a non-brand prefix. Both are valid.
    """
    if not body:
        return None
    lookup = {_normalize(name): code for code, name in BRAND_SMS_NAMES.items()}
    for pattern in (_PREFIX_RE, _POSSESSIVE_RE):
        match = pattern.match(body.lstrip())
        if not match:
            continue
        code = lookup.get(_normalize(match.group("candidate")))
        if code:
            return code
    return None


def check_sms_brand_prefix(body: str, brand: str) -> str | None:
    """Return an error message if `body` leads with another brand's prefix.

    Returns None when the copy is fine — which includes the common case of
    carrying no brand prefix at all.
    """
    brand = brand.upper()
    found = detect_brand_prefix(body)
    if found is None or found == brand:
        return None

    expected = BRAND_SMS_NAMES.get(brand, brand)
    return (
        f"SMS copy starts with the wrong brand prefix: "
        f"'{BRAND_SMS_NAMES[found]}:' but this is a {brand} send "
        f"(expected '{expected}:' or the brand embedded in the body).\n"
        f"  Body: {body[:120]}\n"
        f"  Fix the copy on the Asana task before rebuilding. Check the Brand "
        f"field on the task's copy subtask too — a subtask mislabeled with "
        f"another brand is what causes this."
    )
