"""API-based tool implementations.

These tools use the Braze REST API for read and write operations.
"""

import html
import logging
from typing import Optional

from ..api.client import (
    BrazeClient,
    build_campaign_analytics_params,
    build_campaign_list_params,
    build_canvas_analytics_params,
    parse_analytics,
    parse_campaign_details,
    parse_campaign_list,
)

logger = logging.getLogger("braze-mcp.api")


async def list_campaigns(
    brand: str,
    page: int = 0,
    include_archived: bool = False,
) -> list[dict]:
    """List campaigns for a brand.

    Args:
        brand: Brand code (HAV, BUR, ID, STF, CZ, TI)
        page: Page number (0-indexed)
        include_archived: Include archived campaigns

    Returns:
        List of campaign dicts
    """
    client = BrazeClient(brand)
    try:
        params = build_campaign_list_params(page, include_archived)
        response = await client.get("campaigns/list", params)
        return parse_campaign_list(response)
    finally:
        await client.close()


async def get_campaign(brand: str, campaign_id: str) -> dict:
    """Get campaign details including messages and variants.

    Args:
        brand: Brand code
        campaign_id: Braze campaign ID

    Returns:
        Campaign details dict
    """
    client = BrazeClient(brand)
    try:
        response = await client.get("campaigns/details", {"campaign_id": campaign_id})
        return parse_campaign_details(response)
    finally:
        await client.close()


async def get_campaign_analytics(
    brand: str,
    campaign_id: str,
    days: int = 30,
) -> dict:
    """Get campaign performance metrics.

    Args:
        brand: Brand code
        campaign_id: Braze campaign ID
        days: Number of days of data (max 100)

    Returns:
        Analytics data dict
    """
    client = BrazeClient(brand)
    try:
        params = build_campaign_analytics_params(campaign_id, days)
        response = await client.get("campaigns/data_series", params)
        return parse_analytics(response)
    finally:
        await client.close()


async def list_canvases(
    brand: str,
    page: int = 0,
    include_archived: bool = False,
) -> list[dict]:
    """List canvases (triggered journeys) for a brand.

    Args:
        brand: Brand code
        page: Page number (0-indexed)
        include_archived: Include archived canvases

    Returns:
        List of canvas dicts
    """
    client = BrazeClient(brand)
    try:
        params = {
            "page": page,
            "include_archived": include_archived,
            "sort_direction": "desc",
        }
        response = await client.get("canvas/list", params)
        return response.get("canvases", [])
    finally:
        await client.close()


async def get_canvas(brand: str, canvas_id: str) -> dict:
    """Get canvas structure including steps and messages.

    Args:
        brand: Brand code
        canvas_id: Braze canvas ID

    Returns:
        Canvas details dict
    """
    client = BrazeClient(brand)
    try:
        response = await client.get("canvas/details", {"canvas_id": canvas_id})
        return response
    finally:
        await client.close()


async def get_canvas_analytics(
    brand: str,
    canvas_id: str,
    days: int = 14,
) -> dict:
    """Get canvas step-level analytics.

    Args:
        brand: Brand code
        canvas_id: Braze canvas ID
        days: Number of days of data (max 14)

    Returns:
        Analytics data dict
    """
    client = BrazeClient(brand)
    try:
        params = build_canvas_analytics_params(canvas_id, days)
        response = await client.get("canvas/data_series", params)
        return parse_analytics(response)
    finally:
        await client.close()


async def list_templates(
    brand: str,
    limit: int = 100,
) -> list[dict]:
    """List email templates for a brand.

    Args:
        brand: Brand code
        limit: Max templates to return

    Returns:
        List of template dicts
    """
    client = BrazeClient(brand)
    try:
        params = {"limit": limit}
        response = await client.get("templates/email/list", params)
        return response.get("templates", [])
    finally:
        await client.close()


async def get_template(brand: str, template_id: str) -> dict:
    """Get email template details including HTML.

    Args:
        brand: Brand code
        template_id: Braze template ID

    Returns:
        Template details dict
    """
    client = BrazeClient(brand)
    try:
        response = await client.get(
            "templates/email/info", {"email_template_id": template_id}
        )
        return response
    finally:
        await client.close()


def _plain_text_to_html(text: str) -> str:
    """Convert plain text to simple HTML email body.

    Wraps text in a 600px table structure suitable for email clients.

    Args:
        text: Plain text content

    Returns:
        HTML string with proper email formatting
    """
    escaped = html.escape(text)
    # Normalize triple+ newlines, then convert to HTML breaks
    escaped = escaped.replace("\n\n\n", "\n\n")
    escaped = escaped.replace("\n\n", "<br><br>")
    escaped = escaped.replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; font-size: 16px; line-height: 1.6; color: #333333; background-color: #ffffff;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff;">
        <tr>
            <td align="center" style="padding: 20px 0;">
                <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width: 600px; width: 100%; background-color: #ffffff;">
                    <tr>
                        <td style="padding: 20px; font-family: Arial, sans-serif; font-size: 16px; line-height: 1.6; color: #333333;">
{escaped}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


async def create_template(
    brand: str,
    template_name: str,
    subject: str,
    body_html: Optional[str] = None,
    body_plain_text: Optional[str] = None,
    preheader: str = "",
) -> dict:
    """Create an email template in Braze via Templates API.

    This is the fast path for getting email content into Braze -- the template
    can then be selected when creating a campaign via browser automation,
    avoiding slow HTML editor entry entirely.

    Args:
        brand: Brand code (HAV, BUR, ID, STF, CZ, TI)
        template_name: Name for the template
        subject: Email subject line
        body_html: HTML body content (used directly if provided)
        body_plain_text: Plain text body (converted to HTML if body_html not provided)
        preheader: Email preheader text

    Returns:
        Dict with template_id and template details

    Raises:
        BrazeApiError: If API call fails
        ValueError: If neither body_html nor body_plain_text is provided
    """
    if not body_html and not body_plain_text:
        raise ValueError("Either body_html or body_plain_text must be provided")

    # Convert plain text to HTML if no HTML body provided
    html_body = body_html if body_html else _plain_text_to_html(body_plain_text)
    plaintext_body = body_plain_text or ""

    payload = {
        "template_name": template_name,
        "subject": subject,
        "body": html_body,
        "plaintext_body": plaintext_body,
    }
    if preheader:
        payload["preheader"] = preheader

    logger.info(f"Creating email template '{template_name}' for brand {brand}")

    client = BrazeClient(brand)
    try:
        response = await client.post("templates/email/create", json=payload)
        template_id = response.get("email_template_id") or response.get("id")
        logger.info(f"Template created: {template_id}")
        return {
            "template_id": template_id,
            "template_name": template_name,
            "message": response.get("message", "success"),
        }
    finally:
        await client.close()
