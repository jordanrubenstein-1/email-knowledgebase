"""Shared plain-text-email text helpers.

The Braze PT builder (``scripts/braze_automation/build_pt_campaign.py``) and
the Klaviyo PT builder (``scripts/create_klaviyo_email.py``) were written
independently and accumulated their own copies of the same parsing rules, which
drifted apart in several places.  Anything both need lives here instead.
"""

from __future__ import annotations

import re

# Leading/trailing markdown emphasis left over after a label prefix is removed.
# Asana descriptions sometimes bold the whole label, "**SL:** Ends tonight" or
# "**SL: Ends tonight**", and the prefix pattern only consumes up to the colon.
_MD_EMPHASIS_EDGES = re.compile(r"^(?:\*{1,3}|_{1,3})\s*|\s*(?:\*{1,3}|_{1,3})$")


def strip_markdown_emphasis(value: str) -> str:
    """Strip markdown bold/italic markers from both ends of *value*.

    Applied to an extracted subject line so a bolded label doesn't leave its
    closing ``**`` sitting in the subject that ships.
    """
    if not value:
        return value
    out = value.strip()
    # Run twice so "***x***" / mixed "**_x_**" clear from both ends.
    for _ in range(2):
        out = _MD_EMPHASIS_EDGES.sub("", out).strip()
    return out
