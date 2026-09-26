#!/usr/bin/env python3
"""
Braze API Client for fetching campaign and canvas analytics.

This module provides functions to fetch campaign and canvas analytics data
from the Braze REST API and transform it into DataFrames matching the CSV
format expected by combine_braze_ga4.py.
"""

import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pandas as pd
import requests


def get_braze_config(api_key: Optional[str] = None, api_url: Optional[str] = None, brand: Optional[str] = None):
    """Get Braze API configuration from environment or arguments."""
    if brand:
        brand = brand.upper()
        api_key = api_key or os.environ.get(f"BRAZE_API_KEY_{brand}")
        api_url = api_url or os.environ.get(f"BRAZE_BASE_URL_{brand}")

    api_key = api_key or os.environ.get("BRAZE_API_KEY")
    api_url = api_url or os.environ.get("BRAZE_BASE_URL") or os.environ.get("BRAZE_API_URL")

    if not api_key:
        raise ValueError("BRAZE_API_KEY not set in environment and not provided as argument")
    if not api_url:
        api_url = "https://rest.iad-07.braze.com"

    return {"api_key": api_key, "api_url": api_url.rstrip("/")}


def braze_request(endpoint: str, params: Optional[Dict] = None, api_key: Optional[str] = None,
                  api_url: Optional[str] = None, brand: Optional[str] = None, max_retries: int = 3, retry_delay: float = 1.0):
    """Make a request to Braze API with retry logic."""
    config = get_braze_config(api_key, api_url, brand)
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json"
    }
    url = f"{config['api_url']}/{endpoint.lstrip('/')}"

    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
            elif response.status_code == 401:
                raise ValueError(f"Unauthorized: Check your Braze API key. Status: {response.status_code}")
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                time.sleep(wait_time)
            else:
                raise

    return None


def get_all_campaigns(api_key: Optional[str] = None, api_url: Optional[str] = None,
                      brand: Optional[str] = None, include_archived: bool = False) -> List[Dict]:
    """Fetch all campaigns from Braze."""
    all_campaigns = []
    page = 0

    while True:
        params = {
            "page": page,
            "include_archived": include_archived,
            "sort_direction": "desc"
        }
        data = braze_request("campaigns/list", params, api_key, api_url, brand)

        if not data or "campaigns" not in data:
            break

        campaigns = data["campaigns"]
        if not campaigns:
            break

        all_campaigns.extend(campaigns)
        page += 1

        if page > 100:
            break

    return all_campaigns


def get_campaign_analytics(campaign_id: str, start_date: datetime, end_date: datetime,
                          api_key: Optional[str] = None, api_url: Optional[str] = None,
                          brand: Optional[str] = None) -> Optional[Dict]:
    """Fetch analytics for a specific campaign over a date range."""
    now = datetime.now()
    if end_date > now:
        end_date = now

    length = (end_date - start_date).days + 1
    if length < 1:
        return None

    params = {
        "campaign_id": campaign_id,
        "length": min(length, 100),
        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    }

    return braze_request("campaigns/data_series", params, api_key, api_url, brand)


def aggregate_campaign_analytics(analytics: Dict, campaign_name: str) -> Dict:
    """Aggregate campaign analytics data to match CSV format."""
    if not analytics or "data" not in analytics:
        return {
            "Campaign Name": campaign_name,
            "Deliveries (Email)": 0,
            "Machine Opens (Email)": 0,
            "Other Opens (Email)": 0,
            "Total Opens (Email)": 0,
            "Total Open Rate (Email)": "0%",
            "Unique Opens (Email)": 0,
            "Unique Open Rate (Email)": "0%",
            "Unique Clicks (Email)": 0,
            "Unique Click Rate (Email)": "0%",
            "Total Clicks (Email)": 0,
            "Total Click Rate (Email)": "0%",
            "Unsubscribes (Email)": 0,
            "Confirmed Deliveries (SMS)": "",
            "Total Clicks (SMS)": "",
            "Total Click Rate (SMS)": ""
        }

    total_delivered_email = 0
    total_machine_opens = 0
    total_other_opens = 0
    total_unique_opens = 0
    total_unique_clicks_email = 0
    total_clicks_email = 0
    total_unsubscribes = 0
    total_delivered_sms = 0
    total_clicks_sms = 0

    for day_data in analytics["data"]:
        messages = day_data.get("messages", {})

        if "email" in messages:
            email_data = messages["email"]
            if isinstance(email_data, list):
                for variant in email_data:
                    total_delivered_email += variant.get("delivered", 0)
                    total_machine_opens += variant.get("machine_opens", 0)
                    total_other_opens += variant.get("other_opens", 0)
                    total_unique_opens += variant.get("unique_opens", 0)
                    total_unique_clicks_email += variant.get("unique_clicks", 0)
                    total_clicks_email += variant.get("clicks", 0)
                    total_unsubscribes += variant.get("unsubscribes", 0)
            elif isinstance(email_data, dict):
                total_delivered_email += email_data.get("delivered", 0)
                total_machine_opens += email_data.get("machine_opens", 0)
                total_other_opens += email_data.get("other_opens", 0)
                total_unique_opens += email_data.get("unique_opens", 0)
                total_unique_clicks_email += email_data.get("unique_clicks", 0)
                total_clicks_email += email_data.get("clicks", 0)
                total_unsubscribes += email_data.get("unsubscribes", 0)

        if "sms" in messages:
            sms_data = messages["sms"]
            if isinstance(sms_data, list):
                for variant in sms_data:
                    total_delivered_sms += variant.get("delivered", 0)
                    total_clicks_sms += variant.get("clicks", 0)
            elif isinstance(sms_data, dict):
                total_delivered_sms += sms_data.get("delivered", 0)
                total_clicks_sms += sms_data.get("clicks", 0)

    total_opens = total_machine_opens + total_other_opens
    open_rate = (total_opens / total_delivered_email * 100) if total_delivered_email > 0 else 0
    unique_open_rate = (total_unique_opens / total_delivered_email * 100) if total_delivered_email > 0 else 0
    unique_click_rate = (total_unique_clicks_email / total_delivered_email * 100) if total_delivered_email > 0 else 0
    total_click_rate = (total_clicks_email / total_delivered_email * 100) if total_delivered_email > 0 else 0
    sms_click_rate = (total_clicks_sms / total_delivered_sms * 100) if total_delivered_sms > 0 else 0

    return {
        "Campaign Name": campaign_name,
        "Deliveries (Email)": int(total_delivered_email),
        "Machine Opens (Email)": int(total_machine_opens),
        "Other Opens (Email)": int(total_other_opens),
        "Total Opens (Email)": int(total_opens),
        "Total Open Rate (Email)": f"{open_rate:.2f}%",
        "Unique Opens (Email)": int(total_unique_opens),
        "Unique Open Rate (Email)": f"{unique_open_rate:.2f}%",
        "Unique Clicks (Email)": int(total_unique_clicks_email),
        "Unique Click Rate (Email)": f"{unique_click_rate:.2f}%",
        "Total Clicks (Email)": int(total_clicks_email),
        "Total Click Rate (Email)": f"{total_click_rate:.2f}%",
        "Unsubscribes (Email)": int(total_unsubscribes),
        "Confirmed Deliveries (SMS)": int(total_delivered_sms) if total_delivered_sms > 0 else "",
        "Total Clicks (SMS)": int(total_clicks_sms) if total_clicks_sms > 0 else "",
        "Total Click Rate (SMS)": f"{sms_click_rate:.2f}%" if total_delivered_sms > 0 else ""
    }


def fetch_campaign_analytics(start_date: datetime, end_date: datetime, brand: Optional[str] = None,
                            api_key: Optional[str] = None, api_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch all campaign analytics for a date range and return as DataFrame matching Braze CSV format.
    
    Note: This fetches analytics for ALL campaigns since old campaigns may have sends in the report period.
    For faster performance, use Braze CSV exports instead of the API.
    """
    if end_date < start_date:
        raise ValueError(f"End date ({end_date.date()}) must be after start date ({start_date.date()})")

    print("Fetching campaigns from Braze API...")
    try:
        campaigns = get_all_campaigns(api_key, api_url, brand)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch campaigns from Braze API: {e}") from e

    if not campaigns:
        print("Warning: No campaigns found in Braze.")
        return pd.DataFrame(columns=["Campaign Name", "Deliveries (Email)", "Total Opens (Email)",
                                     "Unique Opens (Email)", "Total Clicks (Email)", "Unique Clicks (Email)",
                                     "Confirmed Deliveries (SMS)", "Total Clicks (SMS)"])

    if brand:
        brand_upper = brand.upper()
        campaigns = [c for c in campaigns if brand_upper in c.get("name", "").upper()]
        print(f"Filtered to {len(campaigns)} campaigns matching brand '{brand_upper}'")

    print(f"Found {len(campaigns)} campaigns. Fetching analytics for {start_date.date()} to {end_date.date()}...")
    results = []
    errors = []
    for i, campaign in enumerate(campaigns, 1):
        campaign_id = campaign["id"]
        campaign_name = campaign["name"]
        if i % 10 == 0:
            print(f"  Processing campaign {i}/{len(campaigns)}: {campaign_name[:50]}...")
        try:
            analytics = get_campaign_analytics(campaign_id, start_date, end_date, api_key, api_url, brand)
            aggregated = aggregate_campaign_analytics(analytics, campaign_name)
            results.append(aggregated)
        except Exception as e:
            errors.append(f"Campaign '{campaign_name}': {e}")
            print(f"  Warning: {errors[-1]}")
            results.append(aggregate_campaign_analytics(None, campaign_name))
        time.sleep(0.1)

    if errors:
        print(f"\nWarning: {len(errors)} errors while fetching campaign analytics.")
    print(f"Fetched analytics for {len(results)} campaigns.")
    return pd.DataFrame(results)


def get_all_canvases(api_key: Optional[str] = None, api_url: Optional[str] = None,
                     brand: Optional[str] = None) -> List[Dict]:
    """Fetch all canvases from Braze."""
    all_canvases = []
    page = 0
    while True:
        params = {"page": page, "include_archived": False, "sort_direction": "desc"}
        data = braze_request("canvas/list", params, api_key, api_url, brand)
        if not data or "canvases" not in data:
            break
        canvases = data["canvases"]
        if not canvases:
            break
        all_canvases.extend(canvases)
        page += 1
        if page > 50:
            break
    return all_canvases


def get_canvas_details(canvas_id: str, api_key: Optional[str] = None, api_url: Optional[str] = None,
                      brand: Optional[str] = None) -> Optional[Dict]:
    """Fetch detailed info for a specific canvas."""
    return braze_request("canvas/details", {"canvas_id": canvas_id}, api_key, api_url, brand)


def get_canvas_analytics(canvas_id: str, start_date: datetime, end_date: datetime,
                        api_key: Optional[str] = None, api_url: Optional[str] = None,
                        brand: Optional[str] = None) -> Optional[Dict]:
    """Fetch analytics for a specific canvas over a date range (max 14 days)."""
    now = datetime.now()
    if end_date > now:
        end_date = now
    length = (end_date - start_date).days + 1
    if length < 1:
        return None
    if length > 14:
        start_date = end_date - timedelta(days=13)
        length = 14
    params = {
        "canvas_id": canvas_id,
        "length": length,
        "ending_at": end_date.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
        "include_variant_breakdown": "true",
        "include_step_breakdown": "true"
    }
    return braze_request("canvas/data_series", params, api_key, api_url, brand)


def aggregate_canvas_analytics(analytics: Dict, canvas_name: str, canvas_details: Optional[Dict] = None, verbose: bool = False) -> List[Dict]:
    """Aggregate canvas analytics to match CSV format. Returns list of rows (one per step/variant).
    
    Note: The Braze canvas/data_series API returns step names directly in the response,
    so we extract them from there (more reliable than canvas_details).
    """
    if not analytics or "data" not in analytics:
        return [{
            "Canvas Name": canvas_name, "Variant Name": "", "Step Name": "", "Type": "",
            "Deliveries (Email)": 0, "Unique Opens (Email)": 0, "Unique Open Rate (Email)": "0%",
            "Confirmed Deliveries (SMS)": 0, "Total Clicks (SMS)": 0, "Total Click Rate (SMS)": "0%",
            "Unique Clicks (Email)": 0, "Total Clicks (Email)": 0
        }]

    # The API response structure is:
    # analytics["data"] = dict with "name", "stats"
    # analytics["data"]["stats"] = list of day stats
    # Each day stat has "step_stats" = {step_id: {name: "...", messages: {...}}}
    data = analytics["data"]
    
    # Handle both list and dict formats for data
    if isinstance(data, list):
        stats_list = []
        for day_data in data:
            stats_list.extend(day_data.get("stats", []))
    elif isinstance(data, dict):
        stats_list = data.get("stats", [])
    else:
        return []

    # Aggregate stats by (step_id, variant_id, channel)
    step_variant_stats = {}
    step_names_from_response = {}  # step_id -> name (from analytics response)
    
    for stat in stats_list:
        if not isinstance(stat, dict):
            continue
        step_stats = stat.get("step_stats", {})
        if not isinstance(step_stats, dict):
            continue
            
        for step_id, step_data in step_stats.items():
            if not isinstance(step_data, dict):
                continue
            
            # Extract step name from the response (this is what GA4 tracks!)
            if step_id not in step_names_from_response:
                step_names_from_response[step_id] = step_data.get("name", step_id)
            
            messages = step_data.get("messages", {})
            if not isinstance(messages, dict):
                continue
                
            for channel, msg_list in messages.items():
                if not isinstance(msg_list, list):
                    continue
                for variant in msg_list:
                    if not isinstance(variant, dict):
                        continue
                    vid = variant.get("variation_api_id", variant.get("variation_id", "default"))
                    key = (step_id, vid, channel)
                    if key not in step_variant_stats:
                        step_variant_stats[key] = {"delivered": 0, "unique_opens": 0, "unique_clicks": 0, "clicks": 0}
                    step_variant_stats[key]["delivered"] += variant.get("delivered", 0)
                    step_variant_stats[key]["unique_opens"] += variant.get("unique_opens", 0)
                    step_variant_stats[key]["unique_clicks"] += variant.get("unique_clicks", 0)
                    step_variant_stats[key]["clicks"] += variant.get("clicks", 0)

    if verbose and step_names_from_response:
        print(f"    Canvas '{canvas_name[:40]}' steps from analytics:")
        for sid, sname in list(step_names_from_response.items())[:5]:
            print(f"      - '{sname}'")

    results = []
    for (step_id, variant_id, channel), stats in step_variant_stats.items():
        # Get step name from the analytics response (this is what GA4 tracks)
        step_name = step_names_from_response.get(step_id, step_id)
        
        if channel == "email":
            d, uo, uc, tc = stats["delivered"], stats["unique_opens"], stats["unique_clicks"], stats["clicks"]
            open_rate = (uo / d * 100) if d > 0 else 0
            results.append({
                "Canvas Name": canvas_name, "Variant Name": variant_id if variant_id != "default" else "",
                "Step Name": step_name, "Type": "email",
                "Deliveries (Email)": int(d), "Unique Opens (Email)": int(uo),
                "Unique Open Rate (Email)": f"{open_rate:.2f}%",
                "Confirmed Deliveries (SMS)": "", "Total Clicks (SMS)": "", "Total Click Rate (SMS)": "",
                "Unique Clicks (Email)": int(uc), "Total Clicks (Email)": int(tc)
            })
        elif channel == "sms":
            d, c = stats["delivered"], stats["clicks"]
            click_rate = (c / d * 100) if d > 0 else 0
            results.append({
                "Canvas Name": canvas_name, "Variant Name": variant_id if variant_id != "default" else "",
                "Step Name": step_name, "Type": "sms",
                "Deliveries (Email)": "", "Unique Opens (Email)": "", "Unique Open Rate (Email)": "",
                "Confirmed Deliveries (SMS)": int(d), "Total Clicks (SMS)": int(c),
                "Total Click Rate (SMS)": f"{click_rate:.2f}%" if d > 0 else "0%",
                "Unique Clicks (Email)": "", "Total Clicks (Email)": ""
            })

    if not results:
        results.append({
            "Canvas Name": canvas_name, "Variant Name": "", "Step Name": "", "Type": "",
            "Deliveries (Email)": 0, "Unique Opens (Email)": 0, "Unique Open Rate (Email)": "0%",
            "Confirmed Deliveries (SMS)": 0, "Total Clicks (SMS)": 0, "Unique Clicks (Email)": 0, "Total Clicks (Email)": 0
        })
    return results


def fetch_canvas_analytics(start_date: datetime, end_date: datetime, brand: Optional[str] = None,
                           api_key: Optional[str] = None, api_url: Optional[str] = None,
                           verbose: bool = False) -> pd.DataFrame:
    """Fetch all canvas analytics for a date range and return as DataFrame matching Braze Canvas CSV format.
    
    Note: Canvas names often don't contain brand codes, but step/message names do.
    We fetch all canvases and filter at the step level based on brand in step name.
    """
    if end_date < start_date:
        raise ValueError(f"End date ({end_date.date()}) must be after start date ({start_date.date()})")

    print("Fetching canvases from Braze API...")
    try:
        canvases = get_all_canvases(api_key, api_url, brand)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch canvases from Braze API: {e}") from e

    if not canvases:
        print("Warning: No canvases found in Braze.")
        return pd.DataFrame(columns=["Canvas Name", "Step Name", "Deliveries (Email)", "Unique Opens (Email)",
                                     "Unique Clicks (Email)", "Total Clicks (Email)",
                                     "Confirmed Deliveries (SMS)", "Total Clicks (SMS)"])

    # NOTE: Don't filter canvases by brand in canvas name!
    # Brand codes are typically in step/message names, not canvas names.
    # We'll filter at the step level after fetching details.

    print(f"Found {len(canvases)} canvases. Fetching analytics for {start_date.date()} to {end_date.date()}...")
    all_results = []
    errors = []
    for i, canvas in enumerate(canvases, 1):
        canvas_id = canvas["id"]
        canvas_name = canvas["name"]
        if i % 5 == 0 or verbose:
            print(f"  Processing canvas {i}/{len(canvases)}: {canvas_name[:50]}...")
        try:
            details = get_canvas_details(canvas_id, api_key, api_url, brand)
            analytics = get_canvas_analytics(canvas_id, start_date, end_date, api_key, api_url, brand)
            all_results.extend(aggregate_canvas_analytics(analytics, canvas_name, details, verbose=verbose))
        except Exception as e:
            errors.append(f"Canvas '{canvas_name}': {e}")
            print(f"  Warning: {errors[-1]}")
        time.sleep(0.2)

    if errors:
        print(f"\nWarning: {len(errors)} errors while fetching canvas analytics.")
    
    df = pd.DataFrame(all_results)
    
    # Filter by brand in step name (since canvas names often don't contain brand)
    if brand and not df.empty and "Step Name" in df.columns:
        brand_upper = brand.upper()
        before_count = len(df)
        # Keep steps where step name contains brand code
        df = df[df["Step Name"].astype(str).str.upper().str.contains(brand_upper, na=False)]
        print(f"Filtered to {len(df)} steps matching brand '{brand_upper}' (from {before_count} total)")
    else:
        print(f"Fetched analytics for {len(df)} canvas steps.")
    
    return df
