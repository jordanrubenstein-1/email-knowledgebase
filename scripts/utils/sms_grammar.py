"""Shared SMS copy-quality checks, used by both the Braze and Klaviyo SMS builders.

Extracted from ``scripts/braze_automation/build_sms_campaign.py`` (2026-09-04) so
the Klaviyo builder (``scripts/create_klaviyo_sms.py``) could reuse the exact same
checks instead of duplicating (and inevitably drifting from) the regexes.
"""

from __future__ import annotations

import re

# A URL together with its UTM / Liquid tail.
#
# Liquid blocks can contain spaces — e.g.
#   {{${email_address} | base64_encode | url_param_escape}}
# — so a plain `https?://\S+` stops mid-expression and leaves
# " | base64_encode | url_param_escape}}" behind as apparent copy.
#
# Confirmed 2026-08-16: that leftover manufactured a phantom
# "Multiple spaces at position 179" warning on an ID SMS whose real Braze body
# was clean, and drove a false "body does not match Asana brief" QA flag.
#
# Surrounding whitespace is consumed as well, so removing a mid-sentence URL
# never creates a double space that was not in the copy to begin with. A real
# double space elsewhere in the copy is still reported.
SMS_URL_PATTERN = r'https?://(?:\{\{.*?\}\}|[^\s{])+'
SMS_URL_STRIP_RE = re.compile(r'\s*' + SMS_URL_PATTERN + r'\s*')
_SMS_URL_RE = re.compile(SMS_URL_PATTERN)

# Braze's SMS Link Shortening replaces any link in the body with a fixed-length
# shortened URL at send time, regardless of the configured URL's real length —
# so a link plus its UTM parameters and Liquid personalization tags (which can
# run 100+ characters on their own, e.g. a `bzt={{${email_address} | ...}}`
# tag) never actually counts against the 130-character SMS body limit at that
# length. This is the length Braze's own composer uses for a shortened link.
BRAZE_SHORTENED_LINK_LENGTH = 23


def check_copy_grammar(copy: str) -> list:
    """Return a list of human-readable grammar warnings for an SMS copy string.

    Checks for unambiguous mechanical errors that are nearly always mistakes:
    - Space before punctuation: "word ." / "word ," / "word ?" / "word !"
    - Double spaces
    - Colon immediately followed by a period: ":."

    Callers should strip any URL out of ``copy`` first (via ``SMS_URL_STRIP_RE``)
    so a link's own formatting never produces a false positive.
    """
    issues = []
    # Space before punctuation (e.g. "drops .")
    for m in re.finditer(r'\s+([.,!?;])', copy):
        issues.append(
            f"Space before punctuation '{m.group(1)}' at position {m.start()}: "
            f"\"…{copy[max(0,m.start()-10):m.end()+5].strip()}…\""
        )
    # Double (or more) spaces
    for m in re.finditer(r'  +', copy):
        issues.append(
            f"Multiple spaces at position {m.start()}: "
            f"\"…{copy[max(0,m.start()-5):m.end()+5].strip()}…\""
        )
    # Colon-period sequence (":.")
    for m in re.finditer(r':\s*\.', copy):
        issues.append(
            f"Colon followed by period at position {m.start()}: "
            f"\"…{copy[max(0,m.start()-10):m.end()+5].strip()}…\""
        )
    return issues


def normalize_sms_copy_for_compare(text: str) -> str:
    """Reduce an SMS body to just its copy, for comparing built vs. briefed text.

    Drops the link and its UTM/Liquid tail (the builder resolves LINK / appends
    the URL, so it is never part of the briefed copy) and ignores trailing
    punctuation, since the SMS Link Formatting rule rewrites the
    sentence-ending period before the link into a colon.

    Deliberately does NOT strip a "Brand: " prefix by regex. An earlier
    version of this check (both the Braze and Klaviyo QA paths each had their
    own copy) used `^[^:]+:\\s*`, which removes everything before the FIRST
    colon anywhere in the string — and because the link rule puts a colon
    immediately before the URL, that ate the entire message on any SMS without
    a brand-name prefix, leaving only the URL and guaranteeing a false "does
    not match Asana brief" flag. Prefix asymmetry is handled by
    ``sms_copy_matches()``'s two-way containment check instead. Fixed for
    Braze/webhook_server.py 2026-08-16 (commit b39a70f06); the Klaviyo QA path
    (qa_klaviyo.py) carried the same bug, unfixed, until this shared helper
    replaced both call sites on 2026-09-11.
    """
    text = SMS_URL_STRIP_RE.sub(' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.rstrip(' .:;,-–—').lower()


def sms_copy_matches(expected: str, actual: str) -> bool:
    """True if *expected* (briefed) and *actual* (built) SMS copy are the same,
    tolerant of: the period→colon rewrite before an appended link, the
    link/UTM/Liquid tail itself, and a brand-name prefix present on only one
    side (checked via two-way containment, since neither side is reliably the
    superset).

    An empty ``expected`` means there was nothing to compare (always matches).
    A non-empty ``expected`` against an empty ``actual`` is always a mismatch —
    a body that is nothing but the tracked link normalizes to "", and an empty
    string is trivially "in" any string, so this must be checked explicitly
    rather than falling into the containment check below.
    """
    norm_expected = normalize_sms_copy_for_compare(expected)
    norm_actual = normalize_sms_copy_for_compare(actual)
    if not norm_expected:
        return True
    if not norm_actual:
        return False
    return (
        norm_expected == norm_actual
        or norm_expected in norm_actual
        or norm_actual in norm_expected
    )


def sms_body_length_for_limit_check(body: str) -> int:
    """Character count of *body* as it will actually reach the recipient — with
    any link replaced by its shortened length, not the raw configured URL.

    A raw SMS link commonly carries `utm_source`/`utm_medium`/`utm_campaign`
    and a Liquid `bzt=` personalization tag, easily 100+ characters, none of
    which count toward the 130-char body limit once Braze shortens the link at
    send time. Counting ``len(body)`` directly overstates the effective length
    by that same amount and can flag a body as over-limit when the actual
    copy — the only part a human can shorten — is well within budget.
    """
    return len(_SMS_URL_RE.sub("x" * BRAZE_SHORTENED_LINK_LENGTH, body))
