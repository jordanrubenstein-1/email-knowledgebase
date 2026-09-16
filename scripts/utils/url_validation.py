"""Shared live-URL validation, used by both the Braze and Klaviyo SMS builders.

Extracted from ``scripts/braze_automation/build_sms_campaign.py`` (2026-09-05) so
the Klaviyo builder (``scripts/create_klaviyo_sms.py``) could reuse the exact same
check instead of trusting a resolved link blindly.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse, urlunparse

import requests

# Default reporters — plain print, used by any caller that doesn't pass its own
# (e.g. a caller with a `logging.Logger` to route messages through instead).
_default_on_error = lambda msg: print(f"ERROR: {msg}")  # noqa: E731
_default_on_warning = lambda msg: print(f"WARNING: {msg}")  # noqa: E731


def validate_url(
    url: str,
    on_error: Callable[[str], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> bool:
    """Return True if the URL resolves to the expected page without redirecting elsewhere.

    Checks:
    1. Strips UTM/query params before testing so we hit the actual page path.
    2. Follows redirects — if a specific path (e.g. /collections/pillows) ends up
       at the homepage (/), reports an error and returns False.
    3. Checks final HTTP status >= 400.

    Returns True on any network error (so builds are never hard-blocked), but
    always reports a warning in that case.

    ``on_error``/``on_warning`` let a caller route messages through its own
    logger instead of plain ``print`` (e.g. the Braze SMS builder wraps this in
    ``logger.error``/``logger.warning`` to match its existing log format).
    """
    on_error = on_error or _default_on_error
    on_warning = on_warning or _default_on_warning
    try:
        clean = urlunparse(urlparse(url)._replace(query="", fragment=""))
        resp = requests.head(clean, allow_redirects=True, timeout=10)

        # Detect redirect-to-homepage: started with a specific path, ended at root
        original_path = urlparse(clean).path.rstrip("/")
        final_path = urlparse(resp.url).path.rstrip("/")
        if original_path and original_path != "/" and not final_path:
            on_error(
                f"URL redirects to homepage: {clean} → {resp.url}  "
                f"The URL is broken — find the correct URL before launching."
            )
            return False

        if resp.status_code >= 400:
            on_warning(
                f"URL validation failed (HTTP {resp.status_code}): {clean} — verify before launching"
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        on_warning(f"URL validation error for {url}: {exc} — skipping check")
        return True
