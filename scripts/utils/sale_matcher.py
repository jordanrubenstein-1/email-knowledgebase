"""
Sale Period Matching Utility

Functions to match email campaigns to sale/promo periods based on send dates.

For Havenly (HAV), sales can be tagged with ``havenly_audience`` (PC or CONV)
to distinguish DPS (pre-converted) from Marketplace (converted) promos.  The
matcher extracts the audience from campaign names (``_PC_`` or ``_CONV_``) and
only matches sales whose ``havenly_audience`` agrees, or that have no audience
set (backward-compatible).
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import re
import yaml


def load_sale_schedules(schedule_file: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load sale schedules from YAML file.
    
    Args:
        schedule_file: Path to sale_schedules.yaml. If None, uses default location.
    
    Returns:
        List of sale dictionaries with keys: id, brand, name, start_date, end_date, etc.
    """
    if schedule_file is None:
        schedule_file = Path(__file__).parent.parent.parent / "data" / "sale_schedules.yaml"
    
    if not schedule_file.exists():
        return []
    
    with open(schedule_file) as f:
        data = yaml.safe_load(f) or {}
        return data.get("sales", [])


def get_havenly_audience(campaign: Dict[str, Any]) -> Optional[str]:
    """Extract the Havenly audience (PC or CONV) from a campaign.

    Looks at the campaign ``name`` field for ``_PC_`` or ``_CONV_`` segments,
    which follow the naming convention
    ``P_EM_YYYY_MM_DD_HAV_D_PC_...`` / ``P_EM_YYYY_MM_DD_HAV_D_CONV_...``.

    Returns:
        "PC", "CONV", or None if not a Havenly campaign or audience unknown.
    """
    name = campaign.get("name", "")
    if not name:
        return None
    name_upper = name.upper()
    # Look for _PC_ or _CONV_ anywhere in the campaign name
    if "_PC_" in name_upper or name_upper.endswith("_PC"):
        return "PC"
    if "_CONV_" in name_upper or name_upper.endswith("_CONV"):
        return "CONV"
    return None


def _sale_matches_havenly_audience(
    sale: Dict[str, Any],
    campaign_audience: Optional[str],
) -> bool:
    """Check whether a HAV sale record matches the campaign's audience.

    Rules:
    - If the sale has no ``havenly_audience`` field, it matches any audience
      (backward-compatible with old data).
    - If the campaign has no detectable audience, it matches any sale.
    - Otherwise, the sale's ``havenly_audience`` must equal the campaign's.
    """
    sale_audience = sale.get("havenly_audience")
    if not sale_audience or not campaign_audience:
        return True  # No constraint → match
    return sale_audience == campaign_audience


def parse_campaign_date(date_str: str) -> Optional[datetime]:
    """Parse campaign date string to datetime object.
    
    Handles ISO format timestamps and date strings.
    Returns timezone-naive datetime for date comparison.
    """
    if not date_str:
        return None
    
    try:
        # Handle ISO format with timezone
        date_str = str(date_str).replace("Z", "+00:00")
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
        else:
            # Date only
            dt = datetime.fromisoformat(date_str)
        
        # Convert to timezone-naive for comparison with sale dates
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        
        # Return date-only (no time) for comparison
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, AttributeError):
        return None


def parse_sale_date(date_str: str) -> Optional[datetime]:
    """Parse sale date string (YYYY-MM-DD format) to datetime object."""
    if not date_str:
        return None
    
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def date_overlaps(
    start1: datetime, end1: datetime,
    start2: datetime, end2: datetime
) -> bool:
    """Check if two date ranges overlap.
    
    Args:
        start1, end1: First date range
        start2, end2: Second date range
    
    Returns:
        True if ranges overlap (including touching at boundaries)
    """
    # Ranges overlap if start1 <= end2 and start2 <= end1
    return start1 <= end2 and start2 <= end1


def match_campaign_to_sales(
    campaign: Dict[str, Any],
    sale_schedules: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Match a campaign to sale periods based on send dates.
    
    Args:
        campaign: Campaign dictionary with dates.first_sent and dates.last_sent
        sale_schedules: List of sale dictionaries. If None, loads from default file.
    
    Returns:
        List of matching sale dictionaries. Empty list if no matches.
    """
    if sale_schedules is None:
        sale_schedules = load_sale_schedules()
    
    if not sale_schedules:
        return []
    
    # Get campaign dates
    dates = campaign.get("dates", {})
    first_sent_str = dates.get("first_sent")
    last_sent_str = dates.get("last_sent")
    
    if not first_sent_str and not last_sent_str:
        return []
    
    # Use last_sent if first_sent not available, or vice versa
    campaign_date_str = last_sent_str or first_sent_str
    campaign_date = parse_campaign_date(campaign_date_str)
    
    if not campaign_date:
        return []
    
    # Get campaign brand
    brand = campaign.get("brand")
    if not brand:
        return []
    
    # For Havenly campaigns, determine the audience (PC or CONV) so we
    # can match to the correct promo (DPS vs Marketplace).
    hav_audience = get_havenly_audience(campaign) if brand == "HAV" else None
    
    # Find matching sales
    matching_sales = []
    
    for sale in sale_schedules:
        # Check brand match
        if sale.get("brand") != brand:
            continue
        
        # For HAV, also check audience compatibility
        if brand == "HAV" and not _sale_matches_havenly_audience(sale, hav_audience):
            continue
        
        # Parse sale dates
        sale_start = parse_sale_date(sale.get("start_date"))
        sale_end = parse_sale_date(sale.get("end_date"))
        
        if not sale_start:
            continue
        
        # Default end_date to start_date if not provided
        if not sale_end:
            sale_end = sale_start
        
        # Check if campaign date falls within sale period
        if sale_start <= campaign_date <= sale_end:
            matching_sales.append(sale)
        # Also check if campaign spans sale period (for campaigns with date ranges)
        elif first_sent_str and last_sent_str:
            campaign_start = parse_campaign_date(first_sent_str)
            campaign_end = parse_campaign_date(last_sent_str)
            if campaign_start and campaign_end:
                if date_overlaps(campaign_start, campaign_end, sale_start, sale_end):
                    matching_sales.append(sale)
    
    return matching_sales


def is_during_sale(
    campaign_date: str,
    brand: str,
    sale_schedules: Optional[List[Dict[str, Any]]] = None,
    havenly_audience: Optional[str] = None,
) -> bool:
    """Check if a campaign date falls during any sale period for the brand.
    
    Args:
        campaign_date: ISO date string or datetime
        brand: Brand code (HAV, CZ, ID, etc.)
        sale_schedules: List of sale dictionaries. If None, loads from default file.
        havenly_audience: Optional "PC" or "CONV" for Havenly-specific matching.
    
    Returns:
        True if campaign date is during a sale period for the brand.
    """
    if sale_schedules is None:
        sale_schedules = load_sale_schedules()
    
    if not sale_schedules:
        return False
    
    date_obj = parse_campaign_date(campaign_date)
    if not date_obj:
        return False
    
    for sale in sale_schedules:
        if sale.get("brand") != brand:
            continue
        
        # For HAV, respect audience if provided
        if brand == "HAV" and not _sale_matches_havenly_audience(sale, havenly_audience):
            continue
        
        sale_start = parse_sale_date(sale.get("start_date"))
        sale_end = parse_sale_date(sale.get("end_date")) or sale_start
        
        if sale_start and sale_start <= date_obj <= sale_end:
            return True
    
    return False


def get_sale_context(
    campaign: Dict[str, Any],
    sale_schedules: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Get sale context for a campaign.
    
    Returns a dictionary with sale information if the campaign occurred during a sale.
    
    Args:
        campaign: Campaign dictionary
        sale_schedules: List of sale dictionaries. If None, loads from default file.
    
    Returns:
        Dictionary with keys:
        - during_sale: bool
        - matching_sales: list of sale dicts
        - primary_sale: first matching sale (if any)
        - sale_name: name of primary sale
        - sale_discount: discount of primary sale
    """
    matching_sales = match_campaign_to_sales(campaign, sale_schedules)
    
    context = {
        "during_sale": len(matching_sales) > 0,
        "matching_sales": matching_sales,
        "primary_sale": matching_sales[0] if matching_sales else None,
    }
    
    if matching_sales:
        primary = matching_sales[0]
        context["sale_name"] = primary.get("name")
        context["sale_discount"] = primary.get("discount")
        context["sale_type"] = primary.get("type")
        context["sale_start"] = primary.get("start_date")
        context["sale_end"] = primary.get("end_date")
        context["havenly_audience"] = primary.get("havenly_audience")
    else:
        context["sale_name"] = None
        context["sale_discount"] = None
        context["sale_type"] = None
        context["sale_start"] = None
        context["sale_end"] = None
        context["havenly_audience"] = None
    
    return context


def tag_campaigns_with_sales(
    campaigns: List[Dict[str, Any]],
    sale_schedules: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Tag a list of campaigns with sale period information.
    
    Adds a '_sale_context' key to each campaign dictionary.
    
    Args:
        campaigns: List of campaign dictionaries
        sale_schedules: List of sale dictionaries. If None, loads from default file.
    
    Returns:
        List of campaigns with '_sale_context' added (modifies in place, also returns).
    """
    if sale_schedules is None:
        sale_schedules = load_sale_schedules()
    
    for campaign in campaigns:
        campaign["_sale_context"] = get_sale_context(campaign, sale_schedules)
    
    return campaigns


def filter_campaigns_by_sale(
    campaigns: List[Dict[str, Any]],
    during_sale: bool = True,
    sale_schedules: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Filter campaigns by whether they occurred during a sale period.
    
    Args:
        campaigns: List of campaign dictionaries
        during_sale: If True, return campaigns during sales. If False, return campaigns not during sales.
        sale_schedules: List of sale dictionaries. If None, loads from default file.
    
    Returns:
        Filtered list of campaigns.
    """
    if sale_schedules is None:
        sale_schedules = load_sale_schedules()
    
    filtered = []
    for campaign in campaigns:
        context = get_sale_context(campaign, sale_schedules)
        if context["during_sale"] == during_sale:
            filtered.append(campaign)
    
    return filtered
