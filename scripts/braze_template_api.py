#!/usr/bin/env python3
"""
Braze Templates API wrapper for creating email templates programmatically.

Since Braze doesn't support creating campaigns via API, we use Templates API
to create email templates, then those can be used in API-triggered campaigns
or referenced when creating campaigns manually.
"""

import sys
from pathlib import Path
from typing import Dict, Optional, Any, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from braze_campaign_api import braze_post_request, normalize_brand, init_config


def create_email_template(campaign_config: Dict[str, Any], brand: str) -> Tuple[Optional[str], Optional[str]]:
    """Create an email template in Braze via Templates API.
    
    This is the programmatic way to create email content that can then be used
    in API-triggered campaigns or referenced when creating campaigns.
    
    Args:
        campaign_config: Campaign configuration dictionary
        brand: Brand code
    
    Returns:
        Tuple of (template_id, error_message). template_id is None on error.
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    email_config = campaign_config.get("email", {})
    campaign_name = campaign_config.get("name", "Untitled Campaign")
    
    # Build HTML email body (plain text style, but wrapped in HTML with 600px width)
    body = email_config.get("body", "")
    cta_links = email_config.get("cta_links", [])
    
    # Convert plain text body to HTML format
    html_body = body
    
    # Replace CTA link text with HTML hyperlinks
    if cta_links:
        for cta in sorted(cta_links, key=lambda x: x.get("priority", 999)):
            cta_text = cta.get("text", "")
            cta_url = cta.get("url", "")
            
            if cta_text and cta_url:
                # Replace the plain text with a hyperlink
                if cta_text in html_body:
                    # Check for punctuation after the text
                    punctuation = ""
                    cta_index = html_body.find(cta_text)
                    if cta_index >= 0:
                        next_char_index = cta_index + len(cta_text)
                        if next_char_index < len(html_body):
                            next_char = html_body[next_char_index]
                            if next_char in ".!?,;:":
                                punctuation = next_char
                                # Remove punctuation from original location
                                html_body = html_body[:next_char_index] + html_body[next_char_index+1:]
                    
                    # Create HTML hyperlink with styling and add punctuation after the closing tag
                    hyperlink = f'<a href="{cta_url}" style="color: #0000EE; text-decoration: underline;">{cta_text}</a>{punctuation}'
                    html_body = html_body.replace(cta_text, hyperlink, 1)
    
    # Convert line breaks (\n) to HTML <br> tags
    # Normalize multiple consecutive newlines first
    html_body = html_body.replace("\n\n\n", "\n\n")  # Normalize triple newlines to double
    html_body = html_body.replace("\n\n", "<br><br>")  # Double newline = paragraph break
    html_body = html_body.replace("\n", "<br>")  # Single newline = line break
    
    # Wrap in HTML structure with 600px width constraint
    formatted_body = f"""<!DOCTYPE html>
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
{html_body}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    
    # For plaintext_body, use the original body with line breaks (for email clients that don't support HTML)
    plaintext_body = body
    if cta_links:
        for cta in sorted(cta_links, key=lambda x: x.get("priority", 999)):
            cta_text = cta.get("text", "")
            cta_url = cta.get("url", "")
            if cta_text and cta_url and cta_text in plaintext_body:
                # For plain text, format as "Link Text: URL"
                punctuation = ""
                cta_index = plaintext_body.find(cta_text)
                if cta_index >= 0:
                    next_char_index = cta_index + len(cta_text)
                    if next_char_index < len(plaintext_body):
                        next_char = plaintext_body[next_char_index]
                        if next_char in ".!?,;:":
                            punctuation = next_char
                            plaintext_body = plaintext_body[:next_char_index] + plaintext_body[next_char_index+1:]
                plaintext_body = plaintext_body.replace(cta_text, f"{cta_text}: {cta_url}{punctuation}", 1)
    
    # Create email template payload
    # body is HTML format with 600px width, plaintext_body is plain text fallback
    template_data = {
        "template_name": campaign_name,
        "subject": email_config.get("subject", ""),
        "preheader": email_config.get("preheader", ""),
        "body": formatted_body,  # HTML email body (600px width, plain text style)
        "plaintext_body": plaintext_body  # Plain text fallback version
    }
    
    response_data, error = braze_post_request("templates/email/create", template_data, brand)
    
    if error:
        return None, error
    
    if response_data and "email_template_id" in response_data:
        return response_data["email_template_id"], None
    elif response_data and "id" in response_data:
        return response_data["id"], None
    else:
        return None, f"Unexpected response: {response_data}"


def trigger_api_campaign(campaign_id: str, audience: Dict[str, Any], 
                        trigger_properties: Optional[Dict] = None, brand: str = None) -> Tuple[bool, Optional[str]]:
    """Trigger an existing API-triggered campaign to send.
    
    This requires that you've already created an API-triggered campaign in Braze UI.
    Once created, you can trigger it programmatically with different audiences/content.
    
    Args:
        campaign_id: Braze API-triggered campaign ID
        audience: Audience configuration (segment_id, external_user_ids, etc.)
        trigger_properties: Optional properties to inject into template
        brand: Brand code
    
    Returns:
        Tuple of (success, error_message)
    """
    brand = normalize_brand(brand) if brand else None
    if brand:
        init_config(brand)
    
    trigger_data = {
        "campaign_id": campaign_id,
        "audience": audience
    }
    
    if trigger_properties:
        trigger_data["trigger_properties"] = trigger_properties
    
    response_data, error = braze_post_request("campaigns/trigger/send", trigger_data, brand)
    
    if error:
        return False, error
    
    return True, None
