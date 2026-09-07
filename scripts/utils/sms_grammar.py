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
