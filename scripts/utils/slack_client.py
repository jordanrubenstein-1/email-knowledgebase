"""Minimal Slack client — posts to a pre-configured Incoming Webhook URL."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def post_message(text: str, webhook_url: str | None = None) -> bool:
    """Post `text` to the Slack channel bound to the Incoming Webhook URL.

    Reads the URL from `webhook_url`, falling back to the
    SLACK_WEBHOOK_URL_TEAM_LIFECYCLE env var. Never raises — logs and
    returns False on failure so the caller can decide how to handle it
    (e.g. retry on the next poll instead of losing the event).
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL_TEAM_LIFECYCLE")
    if not url:
        logger.error("SLACK_WEBHOOK_URL_TEAM_LIFECYCLE not set — cannot post to Slack")
        return False
    try:
        resp = requests.post(url, json={"text": text}, timeout=15)
    except Exception:
        logger.exception("Slack webhook request failed")
        return False
    if resp.status_code != 200 or resp.text.strip() != "ok":
        logger.error(f"Slack webhook error ({resp.status_code}): {resp.text[:300]}")
        return False
    return True
