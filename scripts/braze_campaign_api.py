#!/usr/bin/env python3
"""
Braze API wrapper for creating and managing email campaigns.

Provides functions for:
- Creating content blocks (email templates)
- Creating campaigns
- Scheduling campaigns
- Launching campaigns
"""

import sys
import time
import requests
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from import_braze import get_config, init_config, braze_request, normalize_brand, get_api_key, get_base_url

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_sender_info(brand: str, email_type: str = "pt") -> Dict[str, str]:
    """Load sender info for a brand from brand_config.yaml.

    Args:
        brand: Normalized brand code (HAV, CZ, ID, BUR, STF, TI, TRADE)
        email_type: "pt" for plain-text, "designed" for designed emails

    Returns:
        Dict with from_name, from_email, reply_to (may be empty strings).
    """
    config_path = _PROJECT_ROOT / "data" / "brand_config.yaml"
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f)

    brands = config.get("brands", {})

    # Try exact match first, then with _PC suffix (for HAV)
    entry = brands.get(brand) or brands.get(f"{brand}_PC") or {}
    sender = entry.get("sender_info", {}).get(email_type, {})
    return {
        "from_name": sender.get("from_name", ""),
        "from_email": sender.get("from_email", ""),
        "reply_to": sender.get("reply_to", ""),
    }


def braze_post_request(endpoint, json_data, brand=None, max_retries=3, retry_delay=1):
    """Make a POST request to Braze API with retry logic for rate limiting.
    
    Args:
        endpoint: API endpoint path
        json_data: JSON body data
        brand: Brand code for API key selection
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (seconds)
    
    Returns:
        Tuple of (response_data, error_message). response_data is None on error.
    """
    if brand:
        init_config(brand)
    
    api_key = get_api_key()
    base_url = get_base_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{base_url}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
            
            # Handle rate limiting (429)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    # Check for Retry-After header
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    
                    print(f"Rate limit exceeded. Retrying in {wait_time} seconds... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    return None, f"Rate limit exceeded after {max_retries} attempts"
            
            # Handle other errors
            # Accept 200 (OK), 201 (Created), and 202 (Accepted) as success
            if response.status_code not in (200, 201, 202):
                error_msg = f"API error {response.status_code}: {response.text}"
                if response.status_code >= 500 and attempt < max_retries - 1:
                    # Retry on server errors
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"Server error. Retrying in {wait_time} seconds... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    return None, error_msg
            
            # Success
            try:
                return response.json(), None
            except ValueError:
                return None, f"Invalid JSON response: {response.text}"
        
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"Request timeout. Retrying in {wait_time} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                return None, "Request timeout after multiple attempts"
        
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"Request error: {e}. Retrying in {wait_time} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                return None, f"Request failed: {e}"
    
    return None, "Failed after maximum retries"


def create_content_block(campaign_config: Dict[str, Any], brand: str) -> Optional[str]:
    """Create a plain text email content block in Braze.
    
    Args:
        campaign_config: Campaign configuration dictionary
        brand: Brand code (HAV, CZ, ID, etc.)
    
    Returns:
        Content block ID if successful, None otherwise
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    email_config = campaign_config.get("email", {})
    campaign_name = campaign_config.get("name", "Untitled Campaign")
    
    # Build plain text email body
    body = email_config.get("body", "")
    cta_links = email_config.get("cta_links", [])
    
    # Format CTA links in plain text
    formatted_body = body
    if cta_links:
        formatted_body += "\n\n"
        for i, cta in enumerate(sorted(cta_links, key=lambda x: x.get("priority", 999)), 1):
            cta_text = cta.get("text", f"Link {i}")
            cta_url = cta.get("url", "")
            formatted_body += f"{cta_text}: {cta_url}\n"
    
    # Create content block payload
    # Braze content blocks API expects content as a string, not nested object
    content_block_data = {
        "name": f"{campaign_name}_ContentBlock",
        "description": f"Plain text email content block for {campaign_name}",
        "content_type": "email",
        "content": formatted_body  # Content must be a string
    }
    
    response_data, error = braze_post_request("content_blocks/create", content_block_data, brand)
    
    if error:
        print(f"Failed to create content block: {error}")
        return None
    
    if response_data and "content_block_id" in response_data:
        return response_data["content_block_id"]
    elif response_data and "id" in response_data:
        return response_data["id"]
    else:
        print(f"Failed to create content block. Unexpected response: {response_data}")
        return None


def create_campaign(campaign_config: Dict[str, Any], content_block_id: str, brand: str) -> Optional[str]:
    """Create a scheduled email campaign in Braze.
    
    Args:
        campaign_config: Campaign configuration dictionary
        content_block_id: ID of the content block to use
        brand: Brand code
    
    Returns:
        Campaign ID if successful, None otherwise
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    campaign_name = campaign_config.get("name", "Untitled Campaign")
    email_config = campaign_config.get("email", {})
    audience_config = campaign_config.get("audience", {})
    settings = campaign_config.get("settings", {})
    
    # Load sender info from brand config (PT emails by default)
    sender_info = _load_sender_info(brand, email_type="pt")

    # Build the "from" field in RFC 5322 format: "Display Name <email>"
    from_field = email_config.get("from")
    if not from_field and sender_info.get("from_email"):
        if sender_info.get("from_name"):
            from_field = f"{sender_info['from_name']} <{sender_info['from_email']}>"
        else:
            from_field = sender_info["from_email"]

    reply_to_field = email_config.get("reply_to") or sender_info.get("reply_to") or None

    # Build campaign payload
    campaign_data = {
        "name": campaign_name,
        "description": f"Plain text email campaign: {campaign_name}",
        "schedule": {
            "type": "scheduled",
            "time": None,  # Will be set via schedule endpoint
            "in_local_time": False
        },
        "messages": {
            "email": {
                "app_id": None,  # Will need to be set based on brand
                "subject": email_config.get("subject", ""),
                "preheader": email_config.get("preheader", ""),
                "from": from_field,
                "reply_to": reply_to_field,
                "body": None,  # Will use content block
                "content_block_id": content_block_id,
                "plain_text": True
            }
        },
        "audience": {
            "audience_type": audience_config.get("type", "segment")
        }
    }
    
    # Configure audience
    audience_type = audience_config.get("type", "segment")
    if audience_type == "segment":
        campaign_data["audience"]["segment_id"] = audience_config.get("id")
    elif audience_type == "connected_audience":
        campaign_data["audience"]["connected_audience_id"] = audience_config.get("connected_audience_id")
    elif audience_type == "user_list":
        campaign_data["audience"]["external_user_ids"] = audience_config.get("external_user_ids", [])
    
    # Configure subscription group
    subscription_group = settings.get("subscription_group", "Marketing")
    campaign_data["subscription_group_id"] = subscription_group  # May need to resolve to ID
    
    # Configure frequency capping if enabled
    freq_cap = settings.get("frequency_capping", {})
    if freq_cap.get("enabled", False):
        campaign_data["frequency_capping"] = {
            "max_sends": freq_cap.get("max_sends", 1),
            "period_days": freq_cap.get("period_days", 7)
        }
    
    response_data, error = braze_post_request("campaigns/create", campaign_data, brand)
    
    if error:
        print(f"Failed to create campaign: {error}")
        return None
    
    if response_data and "campaign_id" in response_data:
        return response_data["campaign_id"]
    elif response_data and "id" in response_data:
        return response_data["id"]
    else:
        print(f"Failed to create campaign. Unexpected response: {response_data}")
        return None


def schedule_campaign(campaign_id: str, send_datetime: datetime, timezone: str, brand: str) -> bool:
    """Schedule a campaign to send at a specific date and time.
    
    Args:
        campaign_id: Braze campaign ID
        send_datetime: Datetime object for when to send
        timezone: IANA timezone string (e.g., "America/New_York")
        brand: Brand code
    
    Returns:
        True if successful, False otherwise
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    # Format datetime for Braze API (ISO 8601)
    send_time_str = send_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    
    schedule_data = {
        "campaign_id": campaign_id,
        "schedule": {
            "time": send_time_str,
            "in_local_time": timezone != "UTC",
            "at_optimal_time": False
        }
    }
    
    if timezone != "UTC":
        schedule_data["schedule"]["timezone"] = timezone
    
    response_data, error = braze_post_request("campaigns/trigger/schedule/create", schedule_data, brand)
    
    if error:
        print(f"Failed to schedule campaign {campaign_id}: {error}")
        return False
    
    return True


def launch_campaign(campaign_id: str, brand: str, audience: Optional[Dict] = None) -> bool:
    """Launch/send a campaign immediately.
    
    Args:
        campaign_id: Braze campaign ID
        brand: Brand code
        audience: Optional audience override (if not using campaign's default)
    
    Returns:
        True if successful, False otherwise
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    launch_data = {
        "campaign_id": campaign_id
    }
    
    if audience:
        launch_data["audience"] = audience
    
    response_data, error = braze_post_request("campaigns/trigger/send", launch_data, brand)
    
    if error:
        print(f"Failed to launch campaign {campaign_id}: {error}")
        return False
    
    return True


def get_segment_info(segment_id: str, brand: str) -> Optional[Dict]:
    """Get information about a Braze segment (for validation).
    
    Args:
        segment_id: Braze segment ID
        brand: Brand code
    
    Returns:
        Segment information dict or None if not found
    """
    brand = normalize_brand(brand)
    init_config(brand)
    
    # List segments and find the one we need
    response = braze_request("segments/list", params={"page": 0})
    
    if not response or "segments" not in response:
        return None
    
    # Search through pages if needed
    page = 0
    while True:
        segments = response.get("segments", [])
        for segment in segments:
            if segment.get("id") == segment_id:
                return segment
        
        # Check if there are more pages
        if len(segments) == 0:
            break
        
        page += 1
        response = braze_request("segments/list", params={"page": page})
        if not response or "segments" not in response:
            break
    
    return None
