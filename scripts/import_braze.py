#!/usr/bin/env python3
"""
Import campaigns and canvases (triggered journeys) from Braze.

Fetches campaigns/canvases, their details (subjects, variants, steps), and analytics.
Analytics date range is calculated per-campaign based on last_sent/last_entry date.

Usage:
    uv run python scripts/import_braze.py --brand HAV
    uv run python scripts/import_braze.py --brand HAV --skip-existing
    uv run python scripts/import_braze.py --brand HAV --workers 10
    uv run python scripts/import_braze.py --brand HAV --include-canvases
    uv run python scripts/import_braze.py --brand HAV --canvases-only --dry-run

Options:
    --brand NAME        Brand to import (ID, TI, CZ, HAV, BUR, STF)
    --skip-existing     Only import new campaigns/canvases
    --workers N         Parallel API workers (default: 5)
    --dry-run           Print without writing files
    --include-canvases  Also import Braze Canvases (triggered journeys like cart abandon, welcome)
    --canvases-only     Only import Canvases, skip regular campaigns
"""

import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from dotenv import load_dotenv
import requests
import yaml

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Brand aliases for normalization
BRAND_ALIASES = {
    "id": "ID",
    "interior define": "ID",
    "ti": "TI",
    "the inside": "TI",
    "cz": "CZ",
    "the citizenry": "CZ",
    "citizenry": "CZ",
    "hav": "HAV",
    "havenly": "HAV",
    "bur": "BUR",
    "burrow": "BUR",
    "stf": "STF",
    "st. frank": "STF",
    "st frank": "STF",
}

def normalize_brand(brand):
    """Normalize brand name to standard code."""
    if not brand:
        return None
    return BRAND_ALIASES.get(brand.lower(), brand.upper())


def get_config(brand=None):
    """Get configuration from environment, optionally for a specific brand."""
    if brand:
        brand = normalize_brand(brand)
        api_key = os.environ.get(f"BRAZE_API_KEY_{brand}")
        base_url = os.environ.get(f"BRAZE_BASE_URL_{brand}", "https://rest.iad-07.braze.com")

        if not api_key:
            # Fall back to generic key
            api_key = os.environ.get("BRAZE_API_KEY")
            base_url = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")

            if not api_key:
                print(f"Error: BRAZE_API_KEY_{brand} not set (and no fallback BRAZE_API_KEY)")
                print("Add to .env: BRAZE_API_KEY_{brand}=your-key")
                sys.exit(1)
    else:
        api_key = os.environ.get("BRAZE_API_KEY")
        base_url = os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com")

        if not api_key:
            print("Error: BRAZE_API_KEY not set")
            print("Copy .env.example to .env and fill in your API key")
            sys.exit(1)

    return {"api_key": api_key, "base_url": base_url, "brand": brand}


CONFIG = None

def init_config(brand=None):
    """Initialize config for a brand."""
    global CONFIG
    CONFIG = get_config(brand)


def get_api_key():
    global CONFIG
    if CONFIG is None:
        CONFIG = get_config()
    return CONFIG["api_key"]


def get_base_url():
    global CONFIG
    if CONFIG is None:
        CONFIG = get_config()
    return CONFIG["base_url"]

def braze_request(endpoint, params=None, method="GET", json_data=None):
    """Make a request to Braze API.
    
    Args:
        endpoint: API endpoint path (e.g., "campaigns/list")
        params: Query parameters for GET requests
        method: HTTP method ("GET" or "POST")
        json_data: JSON body for POST requests
    
    Returns:
        Response JSON data or None on error
    """
    api_key = get_api_key()
    base_url = get_base_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{base_url}/{endpoint}"
    
    if method.upper() == "POST":
        response = requests.post(url, headers=headers, params=params, json=json_data)
    else:
        response = requests.get(url, headers=headers, params=params)

    if response.status_code not in (200, 201):
        print(f"Error {response.status_code}: {response.text}")
        return None

    return response.json()

def get_campaigns(include_archived=False):
    """Fetch list of campaigns from Braze."""
    params = {
        "page": 0,
        "include_archived": include_archived,
        "sort_direction": "desc"
    }

    all_campaigns = []
    while True:
        data = braze_request("campaigns/list", params)
        if not data or "campaigns" not in data:
            break

        campaigns = data["campaigns"]
        if not campaigns:
            break

        all_campaigns.extend(campaigns)
        params["page"] += 1

        # Safety limit
        if params["page"] > 50:
            break

    return all_campaigns

def get_campaign_details(campaign_id):
    """Fetch detailed info for a specific campaign."""
    data = braze_request("campaigns/details", {"campaign_id": campaign_id})
    return data

def get_campaign_analytics(campaign_id, start_date, end_date):
    """Fetch analytics for a campaign over a date range."""
    # Cap to current UTC time — hardcoded -05:00 causes 400 errors on UTC CI servers
    now = datetime.utcnow()
    if end_date > now:
        end_date = now

    # Ensure we have a valid range
    length = (end_date - start_date).days + 1
    if length < 1:
        return None

    params = {
        "campaign_id": campaign_id,
        "length": min(length, 100),  # Braze limits to 100 days
        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    }
    data = braze_request("campaigns/data_series", params)
    return data

def get_canvases():
    """Fetch list of canvases (multi-step campaigns)."""
    params = {
        "page": 0,
        "include_archived": False,
        "sort_direction": "desc"
    }

    all_canvases = []
    while True:
        data = braze_request("canvas/list", params)
        if not data or "canvases" not in data:
            break

        canvases = data["canvases"]
        if not canvases:
            break

        all_canvases.extend(canvases)
        params["page"] += 1

        if params["page"] > 50:
            break

    return all_canvases

def get_canvas_details(canvas_id):
    """Fetch detailed info for a specific canvas."""
    data = braze_request("canvas/details", {"canvas_id": canvas_id})
    return data


def get_canvas_analytics(canvas_id, start_date, end_date):
    """Fetch analytics for a canvas over a date range."""
    # Cap to current UTC time — hardcoded -05:00 causes 400 errors on UTC CI servers
    now = datetime.utcnow()
    if end_date > now:
        end_date = now

    # Ensure we have a valid range
    length = (end_date - start_date).days + 1
    if length < 1:
        return None

    params = {
        "canvas_id": canvas_id,
        "length": min(length, 14),  # Braze limits to 14 days for canvas
        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "include_variant_breakdown": "true",  # Must be string, not Python bool
        "include_step_breakdown": "true",
    }
    data = braze_request("canvas/data_series", params)
    return data


def transform_canvas(canvas, details, analytics, default_brand=None):
    """Transform Braze canvas data to our schema."""

    # Parse dates
    created_at = parse_date(canvas.get("created_at"))
    last_entry = parse_date(canvas.get("last_entry"))

    # Infer brand from name, fall back to CLI arg
    brand = infer_brand_from_name(canvas["name"]) or default_brand

    # Determine channel from the canvas's actual channels (email/sms/multi)
    canvas_channels = (details or {}).get("channels") or []
    if "email" in canvas_channels and "sms" in canvas_channels:
        canvas_channel = "multi"
    elif "sms" in canvas_channels and "email" not in canvas_channels:
        canvas_channel = "sms"
    else:
        canvas_channel = "email"  # preserves prior default when channels missing/email-only

    # Build canvas object (similar to campaign but marked as canvas)
    canvas_data = {
        "id": canvas["id"],
        "name": canvas["name"],
        "brand": brand,
        "channel": canvas_channel,
        "category": classify_category(canvas["name"]),
        "type": infer_campaign_type(canvas["name"], canvas.get("tags")),
        "theme": infer_theme(canvas["name"]),
        "braze_id": canvas["id"],
        "braze_type": "canvas",  # Key distinction from campaigns
        "campaign_type": "Triggered Journey",  # Mark as triggered
        "dates": {},
        "tags": canvas.get("tags", []),
        "sends": [],
        "performance_summary": {},
        "canvas_steps": [],  # Store step info for flow analysis
    }

    if created_at:
        canvas_data["dates"]["created"] = created_at.strftime("%Y-%m-%d")

    # Get dates from details if available
    first_entry_detail = parse_date(details.get("first_entry")) if details else None
    last_entry_detail = parse_date(details.get("last_entry")) if details else None

    if first_entry_detail:
        canvas_data["dates"]["first_sent"] = first_entry_detail.isoformat()
    if last_entry_detail:
        canvas_data["dates"]["last_sent"] = last_entry_detail.isoformat()
    elif last_entry:
        canvas_data["dates"]["last_sent"] = last_entry.isoformat()

    # Extract step information from details
    if details:
        steps = details.get("steps", [])
        for step in steps:
            if not isinstance(step, dict):
                continue

            step_info = {
                "id": step.get("id"),
                "name": step.get("name"),
                "type": step.get("type"),
            }

            # Only message steps have email/sms content
            if step.get("type") == "message":
                messages = step.get("messages", {})
                if isinstance(messages, dict):
                    for msg_key, msg_data in messages.items():
                        if not isinstance(msg_data, dict):
                            continue
                        if msg_data.get("channel") == "email":
                            step_info["channel"] = "email"
                            step_info["subject"] = msg_data.get("subject", "")
                            step_info["preheader"] = msg_data.get("preheader", "")
                            # Add as a send entry too for consistency
                            canvas_data["sends"].append({
                                "id": msg_key,
                                "channel": "email",
                                "name": step.get("name", msg_key),
                                "subject": msg_data.get("subject", ""),
                                "preheader": msg_data.get("preheader", ""),
                                "step_id": step.get("id"),
                            })
                        elif msg_data.get("channel") == "sms":
                            step_info["channel"] = "sms"
                            step_info["body"] = msg_data.get("body", "")
                            # Add as a send entry too for consistency
                            canvas_data["sends"].append({
                                "id": msg_key,
                                "channel": "sms",
                                "name": step.get("name", msg_key),
                                "body": msg_data.get("body", ""),
                                "step_id": step.get("id"),
                            })

            canvas_data["canvas_steps"].append(step_info)

    # Add analytics (canvas analytics structure: data.stats[].step_stats.{step_id}.messages.email[])
    if analytics and "data" in analytics:
        total_entries = 0
        total_sends = 0
        total_opens = 0
        total_clicks = 0
        total_revenue = 0
        total_delivered = 0
        total_conversions = 0
        total_unsubscribes = 0
        total_bounces = 0

        data = analytics["data"]
        stats_list = data.get("stats", []) if isinstance(data, dict) else []

        for day_data in stats_list:
            if not isinstance(day_data, dict):
                continue

            # Total stats (entries, revenue, conversions)
            total_stats = day_data.get("total_stats", {})
            if isinstance(total_stats, dict):
                total_entries += total_stats.get("entries", 0)
                total_revenue += total_stats.get("revenue", 0)
                total_conversions += total_stats.get("conversions", 0)

            # Step-level message stats
            step_stats = day_data.get("step_stats", {})
            if isinstance(step_stats, dict):
                for step_id, step_data in step_stats.items():
                    if not isinstance(step_data, dict):
                        continue

                    total_revenue += step_data.get("revenue", 0)

                    # Process messages by channel (email, sms, etc.)
                    messages = step_data.get("messages", {})
                    
                    # Email messages are in messages.email[] array
                    email_list = messages.get("email", [])
                    for email_stats in email_list:
                        if isinstance(email_stats, dict):
                            total_sends += email_stats.get("sent", 0)
                            total_opens += email_stats.get("unique_opens", 0)
                            total_clicks += email_stats.get("unique_clicks", 0)
                            total_delivered += email_stats.get("delivered", 0)
                            total_unsubscribes += email_stats.get("unsubscribes", 0)
                            total_bounces += email_stats.get("bounces", 0)
                    
                    # SMS messages are in messages.sms[] array
                    # SMS uses "clicks" field instead of "unique_clicks"
                    sms_list = messages.get("sms", [])
                    for sms_stats in sms_list:
                        if isinstance(sms_stats, dict):
                            total_sends += sms_stats.get("sent", 0)
                            # SMS typically doesn't have opens, but check for it
                            total_opens += sms_stats.get("unique_opens", 0)
                            total_clicks += sms_stats.get("clicks", 0)
                            total_delivered += sms_stats.get("delivered", 0)
                            total_unsubscribes += sms_stats.get("unsubscribes", 0)
                            total_bounces += sms_stats.get("bounces", 0)

        if total_sends > 0:
            canvas_data["performance_summary"] = {
                "total_entries": total_entries,
                "total_sends": total_sends,
                "total_delivered": total_delivered,
                "total_opens": total_opens,
                "total_clicks": total_clicks,
                "open_rate": round(total_opens / total_sends, 4) if total_sends > 0 else 0,
                "click_rate": round(total_clicks / total_sends, 4) if total_sends > 0 else 0,
            }
            if total_revenue > 0:
                canvas_data["performance_summary"]["total_revenue"] = round(total_revenue, 2)
            if total_conversions > 0:
                canvas_data["performance_summary"]["total_conversions"] = total_conversions
            if total_unsubscribes > 0:
                canvas_data["performance_summary"]["total_unsubscribes"] = total_unsubscribes
            if total_bounces > 0:
                canvas_data["performance_summary"]["total_bounces"] = total_bounces
        elif total_entries > 0:
            canvas_data["performance_summary"] = {
                "total_entries": total_entries,
                "note": "Canvas entries found but no message sends in analytics period"
            }

    return canvas_data

def infer_campaign_type(name, tags):
    """Attempt to infer campaign type from name and tags."""
    name_lower = name.lower()
    tags_lower = [t.lower() for t in (tags or [])]

    # Check for sale indicators
    sale_keywords = ["sale", "% off", "discount", "bogo", "promo", "deal"]
    if any(kw in name_lower for kw in sale_keywords):
        return "sale"

    # Check for seasonal/holiday
    seasonal_keywords = ["christmas", "holiday", "fall", "spring", "summer", "winter",
                        "valentine", "halloween", "thanksgiving", "black friday", "cyber"]
    if any(kw in name_lower for kw in seasonal_keywords):
        return "seasonal"

    # Check for product launches
    launch_keywords = ["launch", "new", "introducing", "announce"]
    if any(kw in name_lower for kw in launch_keywords):
        return "product_launch"

    # Check for lifecycle
    lifecycle_keywords = ["welcome", "onboard", "winback", "re-engage", "abandon", "cart"]
    if any(kw in name_lower for kw in lifecycle_keywords):
        return "lifecycle"

    return "announcement"  # default


def classify_category(name: str) -> str:
    """Classify campaign category from name for analysis."""
    name_lower = name.lower()

    # Reminder/Follow-up patterns (check first - more specific)
    reminder_patterns = [
        "reminder", "ends_soon", "ends-soon", "last_chance", "last-chance",
        "final_hours", "final-hours", "final_day", "ending", "extended",
        "last_day", "don't_miss", "dont_miss", "hurry", "_lc_", "_lc"
    ]
    for pattern in reminder_patterns:
        if pattern in name_lower:
            return "reminder"

    # Editorial patterns
    editorial_patterns = [
        "trend", "forecast", "style_guide", "style-guide", "edit_", "_edit",
        "spotlight", "hideaway", "tips", "how_to", "how-to", "guide",
        "inspiration", "designer", "color_edit", "color-edit", "room_refresh",
        "palette", "behind_the", "behind-the", "story", "meet_the", "meet-the"
    ]
    for pattern in editorial_patterns:
        if pattern in name_lower:
            return "editorial"

    # Product launch patterns
    product_patterns = [
        "new_arrival", "new-arrival", "just_dropped", "just-dropped",
        "introducing", "launch", "new_", "collection", "debut", "reveal",
        "first_look", "first-look", "sneak_peek", "sneak-peek"
    ]
    for pattern in product_patterns:
        if pattern in name_lower:
            return "product_launch"

    # Sale/Promo patterns
    sale_patterns = [
        "sale", "promo", "_off", "-off", "discount", "flash", "clearance",
        "labor_day", "labor-day", "memorial_day", "memorial-day",
        "black_friday", "black-friday", "cyber", "bfcm",
        "july_4", "july-4", "fourth_of_july", "fourth-of-july",
        "presidents_day", "presidents-day", "ldw", "mdw",
        "event", "save", "deal", "percent_off", "percent-off"
    ]
    for pattern in sale_patterns:
        if pattern in name_lower:
            return "sale_promo"

    return "other"


def determine_channel(name: str, sends: list = None) -> str:
    """Determine channel from campaign name and sends data."""
    name_upper = name.upper() if name else ""

    # Check name patterns first
    if "_SMS_" in name_upper or name_upper.startswith("SMS_") or name_upper.endswith("_SMS"):
        return "sms"
    if "_EM_" in name_upper or name_upper.startswith("EM_") or "_EMAIL" in name_upper:
        return "email"
    if "_PUSH_" in name_upper or name_upper.startswith("PUSH_"):
        return "push"

    # Check sends array
    if sends:
        channels = set()
        for send in sends:
            ch = send.get("channel", "").lower()
            if ch in ("email", "sms", "push"):
                channels.add(ch)
            elif send.get("subject"):
                channels.add("email")

        if len(channels) == 1:
            return channels.pop()
        elif len(channels) > 1:
            return "multi"

    # Default to email
    return "email"

def infer_theme(name):
    """Attempt to infer theme from campaign name."""
    name_lower = name.lower()

    themes = {
        "christmas": ["christmas", "holiday", "xmas"],
        "fall": ["fall", "autumn"],
        "summer": ["summer"],
        "spring": ["spring"],
        "winter": ["winter"],
        "valentines": ["valentine"],
        "halloween": ["halloween"],
        "black_friday": ["black friday", "bfcm", "cyber monday"],
    }

    for theme, keywords in themes.items():
        if any(kw in name_lower for kw in keywords):
            return theme

    return None

def infer_channel_from_name(name):
    """Infer channel from campaign name patterns like P_EM_, P_SMS_."""
    name_upper = name.upper()
    if "_EM_" in name_upper or name_upper.startswith("EM_"):
        return "email"
    if "_SMS_" in name_upper or name_upper.startswith("SMS_"):
        return "sms"
    if "_PUSH_" in name_upper or name_upper.startswith("PUSH_"):
        return "push"
    return None

def extract_channel(message_type, campaign_name=None):
    """Map Braze message types to our channel names."""
    channel_map = {
        "email": "email",
        "push": "push",
        "sms": "sms",
        "in_app": "push",
        "webhook": "other",
        "content_card": "other"
    }
    channel = channel_map.get(message_type)
    if channel and channel != "other":
        return channel
    # Fall back to inferring from campaign name
    if campaign_name:
        inferred = infer_channel_from_name(campaign_name)
        if inferred:
            return inferred
    return channel_map.get(message_type, "other")

def parse_date(date_str):
    """Safely parse ISO date string from Braze."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_date_from_name(name):
    """Extract date from campaign name patterns like P_EM_2025_11_28_... or 2024_11_02_..."""
    if not name:
        return None
    # Match patterns like 2024_11_28 or 2024-11-28
    date_match = re.search(r'(\d{4})[-_](\d{1,2})[-_](\d{1,2})', name)
    if date_match:
        year, month, day = date_match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def infer_brand_from_name(name):
    """Infer brand from campaign name patterns like P_EM_2025_11_28_ID_D_..."""
    if not name:
        return None
    name_upper = name.upper()

    # Check for brand codes in common positions
    # Pattern: prefix_channel_date_BRAND_type_name or similar
    brand_patterns = {
        "ID": ["_ID_", "_ID-", "ID_D_", "ID_PT_", "ID_SEG_"],
        "TI": ["_TI_", "_TI-", "TI_D_", "TI_PT_"],
        "CZ": ["_CZ_", "_CZ-", "CZ_D_", "CZ_PT_", "CZ_TRADE"],
        "HAV": ["_HAV_", "_HAV-", "HAV_D_", "HAVENLY"],
        "BUR": ["_BUR_", "_BUR-", "BUR_D_", "BURROW"],
        "STF": ["_STF_", "_STF-", "STF_D_", "ST_FRANK", "STFRANK"],
    }

    for brand, patterns in brand_patterns.items():
        if any(p in name_upper for p in patterns):
            return brand

    return None

def transform_campaign(campaign, details, analytics, default_brand=None):
    """Transform Braze campaign data to our schema."""

    # Parse dates
    created_at = parse_date(campaign.get("created_at"))
    last_sent = parse_date(campaign.get("last_sent"))

    # Infer brand from name, fall back to CLI arg
    brand = infer_brand_from_name(campaign["name"]) or default_brand

    # Build campaign object
    campaign_data = {
        "id": campaign["id"],
        "name": campaign["name"],
        "brand": brand,
        "channel": None,  # Set after we process sends
        "category": classify_category(campaign["name"]),
        "type": infer_campaign_type(campaign["name"], campaign.get("tags")),
        "theme": infer_theme(campaign["name"]),
        "braze_id": campaign["id"],
        "dates": {},
        "tags": campaign.get("tags", []),
        "sends": [],
        "performance_summary": {}
    }

    if created_at:
        campaign_data["dates"]["created"] = created_at.strftime("%Y-%m-%d")

    # send_date: canonical analysis date parsed from campaign name
    # More reliable than first_sent/last_sent for "when was this campaign sent?" analysis.
    # Local-time and STO sends spread first_sent/last_sent over 20-48h; the name date is stable.
    send_date = extract_date_from_name(campaign["name"])
    if send_date:
        campaign_data["dates"]["send_date"] = send_date

    # schedule_type from Braze /campaigns/details response.
    # Values: time_based (batch send), action_based (triggered), api_triggered
    # NOTE: Braze does NOT distinguish local-time vs STO vs fixed-time in schedule_type
    # for already-sent campaigns — all batch sends show as time_based.
    if details:
        schedule_type = details.get("schedule_type")
        if schedule_type:
            campaign_data["schedule_type"] = schedule_type

    # Store full timestamps for delivery window analysis
    # Get from details if available (has full datetime), fall back to campaign list data
    first_sent_detail = parse_date(details.get("first_sent")) if details else None
    last_sent_detail = parse_date(details.get("last_sent")) if details else None

    if first_sent_detail:
        campaign_data["dates"]["first_sent"] = first_sent_detail.isoformat()
    if last_sent_detail:
        campaign_data["dates"]["last_sent"] = last_sent_detail.isoformat()
    elif last_sent:
        campaign_data["dates"]["last_sent"] = last_sent.isoformat()
    else:
        # Try to extract date from campaign name as fallback (date only)
        name_date = extract_date_from_name(campaign["name"])
        if name_date:
            campaign_data["dates"]["last_sent"] = name_date

    # Infer delivery mode from first_sent/last_sent spread (best guess, not confirmed).
    # scheduled   = spread < 15h  (fixed UTC time, including queue delays for large lists)
    # local_time  = spread 15-30h (rolling 24h window across time zones)
    # sto         = spread > 30h  (exceeds 24h, consistent with Intelligent Timing)
    fs = parse_date(campaign_data["dates"].get("first_sent"))
    ls = parse_date(campaign_data["dates"].get("last_sent"))
    if fs and ls:
        spread_h = (ls - fs).total_seconds() / 3600
        if spread_h >= 0:
            if spread_h < 15:
                campaign_data["dates"]["inferred_send_type"] = "scheduled"
            elif spread_h < 30:
                campaign_data["dates"]["inferred_send_type"] = "local_time"
            else:
                campaign_data["dates"]["inferred_send_type"] = "sto"

    # Add message/channel info from details
    campaign_name = campaign.get("name", "")
    campaign_channel = infer_channel_from_name(campaign_name)

    if details and "messages" in details:
        for msg_key, msg_data in details.get("messages", {}).items():
            msg_type = msg_data.get("type", "")
            subject = msg_data.get("subject", "")
            preheader = msg_data.get("preheader", "")

            # Determine channel - if has subject, it's likely email
            if subject and not msg_type:
                channel = "email"
            else:
                channel = extract_channel(msg_type, campaign_name)

            send = {
                "id": msg_key,
                "channel": channel,
                "name": msg_data.get("name", msg_key),
            }

            # Always capture subject/preheader if present (email campaigns)
            # This ensures we get subjects even when type is unknown
            if subject:
                send["subject"] = subject
            if preheader:
                send["preheader"] = preheader

            campaign_data["sends"].append(send)

    # Add analytics
    if analytics and "data" in analytics:
        total_sends = 0
        total_opens = 0
        total_clicks = 0
        total_revenue = 0
        total_delivered = 0
        total_bounces = 0
        total_unsubscribes = 0

        for day_data in analytics["data"]:
            # Data can be at top level or nested under messages.{channel}
            # Check for nested structure first (messages.email, messages.sms, etc.)
            messages = day_data.get("messages", {})
            for channel, variants in messages.items():
                if isinstance(variants, list):
                    for variant in variants:
                        total_sends += variant.get("sent", 0)
                        total_opens += variant.get("unique_opens", 0)
                        # SMS uses "clicks" field, email uses "unique_clicks"
                        if channel == "sms":
                            total_clicks += variant.get("clicks", 0)
                        else:
                            total_clicks += variant.get("unique_clicks", 0)
                        total_revenue += variant.get("revenue", 0)
                        total_delivered += variant.get("delivered", 0)
                        total_bounces += variant.get("bounces", 0)
                        total_unsubscribes += variant.get("unsubscribes", 0)

            # Also check top-level (older API format or summary data)
            if not messages:
                total_sends += day_data.get("sent", 0)
                total_opens += day_data.get("unique_opens", 0)
                total_clicks += day_data.get("unique_clicks", 0)
                total_revenue += day_data.get("revenue", 0)

        if total_sends > 0:
            campaign_data["performance_summary"] = {
                "total_sends": total_sends,
                "total_delivered": total_delivered,
                "total_opens": total_opens,
                "total_clicks": total_clicks,
                "open_rate": round(total_opens / total_sends, 4),
                "click_rate": round(total_clicks / total_sends, 4),
            }

            if total_revenue > 0:
                campaign_data["performance_summary"]["total_revenue"] = round(total_revenue, 2)
            if total_bounces > 0:
                campaign_data["performance_summary"]["total_bounces"] = total_bounces
            if total_unsubscribes > 0:
                campaign_data["performance_summary"]["total_unsubscribes"] = total_unsubscribes

    # Determine channel from name and sends
    campaign_data["channel"] = determine_channel(campaign["name"], campaign_data["sends"])

    return campaign_data

def slugify(name):
    """Convert campaign name to filename-safe slug."""
    # Remove special characters, replace spaces with hyphens
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    return slug[:60]  # Limit length

# Module-level registry: slug -> campaign_id, guards against same-run collisions
_filename_registry = {}
_filename_registry_lock = threading.Lock()

def resolve_filename(campaign_name, campaign_id, output_dir):
    """Return the filename for a campaign, appending an ID suffix on slug collision."""
    slug = slugify(campaign_name)
    candidate = f"{slug}.yaml"

    with _filename_registry_lock:
        if slug in _filename_registry:
            if _filename_registry[slug] != campaign_id:
                # Another campaign in this run already claimed this slug
                unique_slug = f"{slug[:51]}-{campaign_id[:8]}"
                _filename_registry[unique_slug] = campaign_id
                return f"{unique_slug}.yaml"
            # Same campaign (re-import) — reuse the slug
        else:
            # Check filesystem for collisions from previous runs
            filepath = output_dir / candidate
            if filepath.exists():
                try:
                    with open(filepath) as f:
                        existing = yaml.safe_load(f)
                    if existing and existing.get('id') != campaign_id:
                        unique_slug = f"{slug[:51]}-{campaign_id[:8]}"
                        _filename_registry[unique_slug] = campaign_id
                        return f"{unique_slug}.yaml"
                except Exception:
                    pass
            _filename_registry[slug] = campaign_id

    return candidate

def write_campaign(campaign_data, output_dir, dry_run=False, quiet=False):
    """Write campaign to YAML file."""
    filename = resolve_filename(campaign_data['name'], campaign_data.get('id', ''), output_dir)
    filepath = output_dir / filename
    campaign_data['_filename'] = filename  # stash for update_index

    if dry_run:
        print(f"Would write: {filepath}")
        print(yaml.dump(campaign_data, default_flow_style=False, sort_keys=False)[:500])
        print("---")
        return

    with open(filepath, 'w') as f:
        yaml.dump(campaign_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if not quiet:
        print(f"Wrote: {filepath}")

def update_index(campaigns, output_dir, dry_run=False):
    """Update the campaigns index file."""
    index_data = {
        "campaigns": [
            {
                "id": c["id"],
                "name": c["name"],
                "type": c["type"],
                "file": c.get("_filename") or f"{slugify(c['name'])}.yaml"
            }
            for c in campaigns
        ],
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "braze"
    }

    index_path = output_dir / "_index.yaml"

    if dry_run:
        print(f"Would update index with {len(campaigns)} campaigns")
        return

    with open(index_path, 'w') as f:
        yaml.dump(index_data, f, default_flow_style=False, sort_keys=False)

    print(f"Updated index: {index_path}")


def main():
    parser = argparse.ArgumentParser(description="Import campaigns from Braze")
    parser.add_argument("--brand", type=str, help="Brand to import (ID, TI, CZ, etc.)")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--output", type=str, default="campaigns", help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of campaigns")
    parser.add_argument("--skip-existing", action="store_true", help="Skip campaigns that already have files")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")
    parser.add_argument("--include-canvases", action="store_true", help="Also import Braze Canvases (triggered journeys)")
    parser.add_argument("--canvases-only", action="store_true", help="Only import Canvases, not campaigns")
    args = parser.parse_args()

    # Initialize config for brand
    init_config(args.brand)
    brand_label = CONFIG.get("brand") or "default"

    # Setup
    script_dir = Path(__file__).parent
    output_dir = script_dir.parent / args.output
    output_dir.mkdir(exist_ok=True)

    # Thread-safe counters and storage (shared for campaigns and canvases)
    print_lock = threading.Lock()
    processed = []
    processed_lock = threading.Lock()

    # ============================================
    # CAMPAIGNS
    # ============================================
    campaigns_skipped = 0
    if not args.canvases_only:
        print(f"Fetching campaigns from Braze ({brand_label})...")
        campaigns = get_campaigns()
        print(f"Found {len(campaigns)} campaigns")

        if args.limit:
            campaigns = campaigns[:args.limit]
            print(f"Limited to {args.limit} campaigns")

        # Filter out "Copy of ..." campaigns — these are unsent drafts, not real sends
        copy_count = sum(1 for c in campaigns if c['name'].startswith('Copy of '))
        if copy_count:
            campaigns = [c for c in campaigns if not c['name'].startswith('Copy of ')]
            print(f"Skipping {copy_count} 'Copy of ...' draft campaigns")

        # Filter out existing if --skip-existing
        if args.skip_existing:
            campaigns_to_process = []
            for campaign in campaigns:
                filename = resolve_filename(campaign['name'], campaign['id'], output_dir)
                filepath = output_dir / filename
                if filepath.exists():
                    campaigns_skipped += 1
                else:
                    campaigns_to_process.append(campaign)
            if campaigns_skipped:
                print(f"Skipping {campaigns_skipped} existing campaigns")
            campaigns = campaigns_to_process

        if campaigns:
            print(f"Processing {len(campaigns)} campaigns with {args.workers} workers...")
            print()

            completed_count = [0]
            total_count = len(campaigns)

            def process_campaign(campaign):
                """Process a single campaign - fetch details, analytics, transform, and write."""
                try:
                    details = get_campaign_details(campaign["id"])

                    # Calculate per-campaign date range for analytics
                    last_sent = parse_date(campaign.get("last_sent"))
                    if not last_sent:
                        name_date = extract_date_from_name(campaign.get("name", ""))
                        if name_date:
                            last_sent = datetime.strptime(name_date, "%Y-%m-%d")

                    if not last_sent:
                        last_sent = datetime.now() - timedelta(days=30)

                    analytics_start = last_sent - timedelta(days=1)
                    analytics_end = min(last_sent + timedelta(days=14), datetime.now())
                    analytics = get_campaign_analytics(campaign["id"], analytics_start, analytics_end)

                    campaign_data = transform_campaign(campaign, details, analytics, default_brand=CONFIG.get("brand"))

                    if not args.dry_run:
                        write_campaign(campaign_data, output_dir, dry_run=False, quiet=True)

                    with processed_lock:
                        processed.append(campaign_data)
                        completed_count[0] += 1
                        count = completed_count[0]

                    with print_lock:
                        status = "(dry-run)" if args.dry_run else "done"
                        print(f"[{count}/{total_count}] {campaign['name'][:50]}... {status}")

                    return campaign_data

                except Exception as e:
                    with print_lock:
                        print(f"[ERROR] {campaign['name'][:50]}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_campaign, c): c for c in campaigns}
                for future in as_completed(futures):
                    pass

            print(f"Processed {len([p for p in processed if p.get('braze_type') != 'canvas'])} campaigns")
            print()

    # ============================================
    # CANVASES (Triggered Journeys)
    # ============================================
    canvases_skipped = 0
    if args.include_canvases or args.canvases_only:
        print(f"Fetching canvases from Braze ({brand_label})...")
        canvases = get_canvases()
        print(f"Found {len(canvases)} canvases")

        # Filter out "Copy of ..." canvases — same as campaigns, these are unsent drafts
        canvas_copy_count = sum(1 for c in canvases if c['name'].startswith('Copy of '))
        if canvas_copy_count:
            canvases = [c for c in canvases if not c['name'].startswith('Copy of ')]
            print(f"Skipping {canvas_copy_count} 'Copy of ...' draft canvases")

        if args.limit and args.canvases_only:
            canvases = canvases[:args.limit]
            print(f"Limited to {args.limit} canvases")

        # Filter out existing if --skip-existing
        if args.skip_existing:
            canvases_to_process = []
            for canvas in canvases:
                filename = resolve_filename(canvas['name'], canvas['id'], output_dir)
                filepath = output_dir / filename
                if filepath.exists():
                    canvases_skipped += 1
                else:
                    canvases_to_process.append(canvas)
            if canvases_skipped:
                print(f"Skipping {canvases_skipped} existing canvases")
            canvases = canvases_to_process

        if canvases:
            print(f"Processing {len(canvases)} canvases with {args.workers} workers...")
            print()

            completed_count = [0]
            total_count = len(canvases)

            def process_canvas(canvas):
                """Process a single canvas - fetch details, analytics, transform, and write."""
                try:
                    details = get_canvas_details(canvas["id"])

                    # Calculate date range for analytics
                    last_entry = parse_date(canvas.get("last_entry"))
                    if not last_entry:
                        name_date = extract_date_from_name(canvas.get("name", ""))
                        if name_date:
                            last_entry = datetime.strptime(name_date, "%Y-%m-%d")

                    if not last_entry:
                        last_entry = datetime.now() - timedelta(days=7)

                    # Canvas analytics API limits to 14 days max
                    analytics_start = last_entry - timedelta(days=1)
                    analytics_end = min(last_entry + timedelta(days=13), datetime.now())
                    analytics = get_canvas_analytics(canvas["id"], analytics_start, analytics_end)

                    canvas_data = transform_canvas(canvas, details, analytics, default_brand=CONFIG.get("brand"))

                    if not args.dry_run:
                        write_campaign(canvas_data, output_dir, dry_run=False, quiet=True)

                    with processed_lock:
                        processed.append(canvas_data)
                        completed_count[0] += 1
                        count = completed_count[0]

                    with print_lock:
                        status = "(dry-run)" if args.dry_run else "done"
                        print(f"[Canvas {count}/{total_count}] {canvas['name'][:50]}... {status}")

                    return canvas_data

                except Exception as e:
                    with print_lock:
                        print(f"[ERROR Canvas] {canvas['name'][:50]}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_canvas, c): c for c in canvases}
                for future in as_completed(futures):
                    pass

            canvas_count = len([p for p in processed if p.get('braze_type') == 'canvas'])
            print(f"Processed {canvas_count} canvases")
            print()

    # Update index
    update_index(processed, output_dir, args.dry_run)

    # Summary
    print()
    campaign_count = len([p for p in processed if p.get('braze_type') != 'canvas'])
    canvas_count = len([p for p in processed if p.get('braze_type') == 'canvas'])
    print(f"Done! Imported to {output_dir}:")
    if campaign_count:
        print(f"  - {campaign_count} campaigns")
    if canvas_count:
        print(f"  - {canvas_count} canvases (triggered journeys)")
    if campaigns_skipped or canvases_skipped:
        print(f"  - Skipped {campaigns_skipped + canvases_skipped} existing")

if __name__ == "__main__":
    main()
