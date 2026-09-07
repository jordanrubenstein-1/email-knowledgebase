#!/usr/bin/env python3
"""
Merge data from multiple sources (Braze, Asana) into unified campaign files.

This script correlates campaigns across sources using:
1. Direct Braze campaign ID links from Asana (cf_braze_campaign_link)
2. Fuzzy name matching as fallback
3. Date proximity
4. Manual mappings (for edge cases)

Usage:
    uv run python scripts/merge_sources.py

Options:
    --asana FILE      Asana export file (default: asana_id.yaml)
    --dry-run         Show matches without writing
    --threshold N     Fuzzy match threshold 0-100 (default: 70)
    --mappings FILE   YAML file with manual ID mappings
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher
import yaml
import re


def extract_braze_id_from_url(url):
    """Extract Braze campaign ID from dashboard URL."""
    if not url:
        return None
    # Pattern: https://dashboard-07.braze.com/engagement/campaigns/{id}/...
    match = re.search(r'/campaigns/([a-f0-9-]+)', url)
    if match:
        return match.group(1)
    # Also check for canvas URLs
    match = re.search(r'/canvas/([a-f0-9-]+)', url)
    if match:
        return match.group(1)
    return None


def extract_date_from_braze_name(name):
    """Extract date from Braze campaign naming pattern like P_EM_2025_11_28_... or P_2024_1_2_..."""
    if not name:
        return None
    # Pattern: YYYY_M(M)_D(D) - supports single or double digit month/day
    match = re.search(r'(\d{4})[-_](\d{1,2})[-_](\d{1,2})', name)
    if match:
        try:
            return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
        except:
            pass
    return None


def build_braze_id_index(asana_entries):
    """Build index of Asana entries by Braze campaign ID."""
    index = {}
    for entry in asana_entries:
        braze_url = entry.get('cf_braze_campaign_link')
        braze_id = extract_braze_id_from_url(braze_url)
        if braze_id:
            if braze_id not in index:
                index[braze_id] = []
            index[braze_id].append(entry)
    return index


def build_date_index(asana_entries, window_days=7):
    """Build index of Asana entries by date for fast lookup."""
    from collections import defaultdict
    index = defaultdict(list)
    for entry in asana_entries:
        date_str = entry.get('date') or entry.get('due_date')
        if date_str:
            index[date_str[:10]].append(entry)
    return index


def get_entries_near_date(date_index, target_date, window_days=7):
    """Get all Asana entries within window_days of target_date."""
    if not target_date:
        return []

    from datetime import datetime, timedelta
    try:
        target = datetime.strptime(str(target_date)[:10], "%Y-%m-%d")
    except:
        return []

    entries = []
    for delta in range(-window_days, window_days + 1):
        check_date = (target + timedelta(days=delta)).strftime("%Y-%m-%d")
        entries.extend(date_index.get(check_date, []))
    return entries

def load_yaml(filepath):
    """Load a YAML file."""
    with open(filepath) as f:
        return yaml.safe_load(f)

def save_yaml(data, filepath):
    """Save data to YAML file."""
    with open(filepath, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

def fuzzy_match_score(str1, str2):
    """
    Calculate similarity score between two strings (0-100).
    Uses multiple strategies and returns the best score.
    """
    if not str1 or not str2:
        return 0

    str1 = str1.lower().strip()
    str2 = str2.lower().strip()

    # Exact match
    if str1 == str2:
        return 100

    # Remove common prefixes/suffixes that vary between systems
    noise_patterns = [
        r'^\d{4}[-_]?\d{2}[-_]?\d{2}\s*[-_]?\s*',  # Date prefixes
        r'\s*[-_]\s*(email|sms|push)\s*$',  # Channel suffixes
        r'\s*[-_]\s*(v\d+|final|draft)\s*$',  # Version suffixes
        r'^\[.*?\]\s*',  # Bracketed prefixes
    ]

    clean1, clean2 = str1, str2
    for pattern in noise_patterns:
        clean1 = re.sub(pattern, '', clean1, flags=re.IGNORECASE)
        clean2 = re.sub(pattern, '', clean2, flags=re.IGNORECASE)

    # SequenceMatcher on cleaned strings
    ratio = SequenceMatcher(None, clean1, clean2).ratio() * 100

    # Also check if one contains the other
    if clean1 in clean2 or clean2 in clean1:
        containment_score = min(len(clean1), len(clean2)) / max(len(clean1), len(clean2)) * 100
        ratio = max(ratio, containment_score)

    # Check word overlap
    words1 = set(clean1.split())
    words2 = set(clean2.split())
    if words1 and words2:
        overlap = len(words1 & words2) / len(words1 | words2) * 100
        ratio = max(ratio, overlap)

    return ratio

def date_proximity_score(date1, date2, max_days=7):
    """
    Score based on how close two dates are.
    Returns 100 if same day, decreasing to 0 at max_days apart.
    """
    if not date1 or not date2:
        return 0

    try:
        if isinstance(date1, str):
            date1 = datetime.strptime(date1[:10], "%Y-%m-%d")
        if isinstance(date2, str):
            date2 = datetime.strptime(date2[:10], "%Y-%m-%d")

        days_apart = abs((date1 - date2).days)
        if days_apart > max_days:
            return 0
        return (1 - days_apart / max_days) * 100
    except:
        return 0

def extract_keywords(text):
    """Extract meaningful keywords from campaign/task name."""
    if not text:
        return set()
    # Remove common prefixes, dates, channels
    text = re.sub(r'^[A-Z]_[A-Z]+_\d{4}_\d{1,2}_\d{1,2}_', '', text)  # P_EM_2025_01_01_
    text = re.sub(r'^\d{1,2}/\d{1,2}\s*', '', text)  # 1/03
    text = re.sub(r'\d{4}', '', text)  # years
    text = text.lower()
    # Split and filter
    words = re.split(r'[_\s\-]+', text)
    stopwords = {'email', 'sms', 'push', 'd', 'pt', 'pr', 'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'for'}
    return {w for w in words if len(w) > 2 and w not in stopwords}


def find_best_match(campaign, asana_entries, threshold=70):
    """
    Find the best matching Asana entry for a Braze campaign.
    Returns (match, score, match_type) or (None, 0, None) if no good match.
    """
    campaign_name = campaign.get("name", "")

    # Try to get date from campaign data, or extract from name
    campaign_date = (
        campaign.get("dates", {}).get("last_sent") or
        campaign.get("dates", {}).get("created") or
        extract_date_from_braze_name(campaign_name)
    )

    campaign_keywords = extract_keywords(campaign_name)

    best_match = None
    best_score = 0
    best_type = None

    for entry in asana_entries:
        entry_date = entry.get("date") or entry.get("due_date")
        entry_name = entry.get("name", "")
        entry_keywords = extract_keywords(entry_name)

        # Calculate date proximity (within 7 days)
        date_score = date_proximity_score(campaign_date, entry_date, max_days=7)

        # Calculate keyword overlap
        if campaign_keywords and entry_keywords:
            overlap = campaign_keywords & entry_keywords
            keyword_score = len(overlap) / max(len(campaign_keywords), len(entry_keywords)) * 100
        else:
            keyword_score = 0

        # Name similarity (traditional fuzzy)
        name_score = fuzzy_match_score(campaign_name, entry_name)

        # Scoring strategy:
        # 1. Exact/near date match (within 2 days) + any keyword overlap = high confidence
        # 2. Close date (within 7 days) + good keyword overlap = medium confidence
        # 3. Traditional fuzzy matching as fallback

        if campaign_date and entry_date:
            days_apart = abs((datetime.strptime(str(campaign_date)[:10], "%Y-%m-%d") -
                            datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")).days) if campaign_date and entry_date else 999
        else:
            days_apart = 999

        # Strategy 1: Date within 2 days + keyword overlap
        if days_apart <= 2 and keyword_score > 20:
            combined_score = 70 + (keyword_score * 0.3)  # Base 70 + keyword bonus
            match_type = f"date+kw_{days_apart}d"
        # Strategy 2: Date within 5 days + strong keyword overlap
        elif days_apart <= 5 and keyword_score > 40:
            combined_score = 60 + (keyword_score * 0.3)
            match_type = f"date+kw_{days_apart}d"
        # Strategy 3: Traditional combined scoring
        elif campaign_date and entry_date:
            combined_score = (name_score * 0.4) + (date_score * 0.4) + (keyword_score * 0.2)
            match_type = "fuzzy"
        else:
            combined_score = name_score
            match_type = "fuzzy"

        if combined_score > best_score:
            best_score = combined_score
            best_match = entry
            best_type = match_type

    if best_score >= threshold:
        return best_match, best_score, best_type

    return None, 0, None

def load_manual_mappings(mappings_file):
    """Load manual ID mappings from YAML file."""
    if not mappings_file or not Path(mappings_file).exists():
        return {}

    data = load_yaml(mappings_file)
    return data.get("mappings", {})

def merge_campaign_with_asana(campaign, asana_match):
    """Merge Asana data into a campaign."""
    if not asana_match:
        return campaign

    # Add Asana reference
    campaign["asana"] = {
        "gid": asana_match.get("asana_gid"),
        "name": asana_match.get("name"),
        "matched_by": "auto"
    }

    # Add planning notes if present
    if asana_match.get("notes"):
        campaign["planning_notes"] = asana_match["notes"]

    # Add assignee if present
    if asana_match.get("assignee"):
        campaign["owner"] = asana_match["assignee"]

    # Pull in subject line from Asana if we don't have one
    asana_subject = asana_match.get("cf_subject_line")
    if asana_subject:
        campaign["asana_subject"] = asana_subject
        # Also add to sends if they don't have subjects
        for send in campaign.get("sends", []):
            if not send.get("subject"):
                send["subject"] = asana_subject

    # Pull in preheader
    asana_preheader = asana_match.get("cf_pre-header") or asana_match.get("cf_preheader")
    if asana_preheader:
        campaign["asana_preheader"] = asana_preheader
        for send in campaign.get("sends", []):
            if not send.get("preheader"):
                send["preheader"] = asana_preheader

    # Add template inspiration
    template_link = asana_match.get("cf_template_inspiration_(with_reasoning)")
    if template_link:
        campaign["template_inspiration"] = template_link

    # Add design assets link
    assets_link = asana_match.get("cf_email_slices/banners/blocks_details")
    if assets_link:
        campaign["design_assets"] = assets_link

    # Add category and type
    if asana_match.get("cf_category"):
        campaign["category"] = asana_match["cf_category"]
    if asana_match.get("cf_type"):
        campaign["email_type"] = asana_match["cf_type"]

    # Add KPI objective
    if asana_match.get("cf_top_kpi/objective"):
        campaign["kpi_objective"] = asana_match["cf_top_kpi/objective"]

    # Merge tags
    existing_tags = set(campaign.get("tags", []))
    asana_tags = set(asana_match.get("tags", []))
    campaign["tags"] = list(existing_tags | asana_tags)

    return campaign

def infer_brand_from_name(name):
    """Infer brand from campaign name."""
    if not name:
        return None
    name_upper = name.upper()
    brand_patterns = {
        "ID": ["_ID_", "_ID-", "ID_D_", "ID_PT_"],
        "TI": ["_TI_", "_TI-", "TI_D_", "TI_PT_"],
        "CZ": ["_CZ_", "_CZ-", "CZ_D_", "CZ_PT_", "CZ_TRADE"],
        "HAV": ["_HAV_", "_HAV-", "HAV_D_", "HAVENLY"],
        "BUR": ["_BUR_", "_BUR-", "BUR_D_", "BURROW"],
        "STF": ["_STF_", "_STF-", "STF_D_", "ST_FRANK"],
    }
    for brand, patterns in brand_patterns.items():
        if any(p in name_upper for p in patterns):
            return brand
    return None


def main():
    parser = argparse.ArgumentParser(description="Merge campaign data from multiple sources")
    parser.add_argument("--asana", type=str, default="imports/asana_id.yaml", help="Asana export file")
    parser.add_argument("--brand", type=str, help="Only merge campaigns for this brand (ID, CZ, HAV, TI, etc.)")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without writing")
    parser.add_argument("--threshold", type=int, default=70, help="Fuzzy match threshold (0-100)")
    parser.add_argument("--mappings", type=str, help="Manual mappings YAML file")
    args = parser.parse_args()

    # Paths
    script_dir = Path(__file__).parent
    base_dir = script_dir.parent
    campaigns_dir = base_dir / "campaigns"
    asana_file = base_dir / args.asana

    # Load Asana data
    if not asana_file.exists():
        print(f"No Asana data found at {asana_file}. Run import_asana.py first.")
        print("Proceeding with Braze-only data...")
        asana_entries = []
        braze_id_index = {}
        date_index = {}
    else:
        asana_data = load_yaml(asana_file)
        asana_entries = asana_data.get("calendar", [])
        print(f"Loaded {len(asana_entries)} Asana entries")

        # Build index by Braze campaign ID for direct matching
        braze_id_index = build_braze_id_index(asana_entries)
        print(f"Built index with {len(braze_id_index)} Braze campaign IDs")

        # Build date index for fast date-based lookups
        date_index = build_date_index(asana_entries)
        print(f"Built date index with {len(date_index)} dates")

    # Load manual mappings
    manual_mappings = load_manual_mappings(args.mappings)
    if manual_mappings:
        print(f"Loaded {len(manual_mappings)} manual mappings")

    # Process each campaign file
    campaign_files = list(campaigns_dir.glob("*.yaml"))
    campaign_files = [f for f in campaign_files if not f.name.startswith("_")]

    print(f"Found {len(campaign_files)} campaign files")

    # Filter by brand if specified
    target_brand = args.brand.upper() if args.brand else None
    if target_brand:
        print(f"Filtering to brand: {target_brand}")
    print()

    matched = 0
    unmatched = 0
    skipped = 0
    total = len(campaign_files)

    for idx, campaign_file in enumerate(campaign_files):
        # Progress every 500
        if idx > 0 and idx % 500 == 0:
            print(f"... processed {idx}/{total} ({matched} matched, {unmatched} unmatched)", flush=True)
        campaign = load_yaml(campaign_file)
        if not campaign:
            continue

        campaign_id = campaign.get("id") or campaign.get("braze_id")
        campaign_name = campaign.get("name", campaign_file.stem)

        # Filter by brand
        if target_brand:
            campaign_brand = campaign.get("brand") or infer_brand_from_name(campaign_name)
            if campaign_brand != target_brand:
                skipped += 1
                continue

        asana_match = None
        match_type = None

        # 1. Check manual mappings first
        if campaign_id in manual_mappings:
            asana_gid = manual_mappings[campaign_id]
            asana_match = next((e for e in asana_entries if e.get("asana_gid") == asana_gid), None)
            if asana_match:
                match_type = "manual"

        # 2. Check direct Braze ID match from Asana links
        if not asana_match and campaign_id in braze_id_index:
            matches = braze_id_index[campaign_id]
            asana_match = matches[0]  # Take first match if multiple
            match_type = "braze_id"

        # 3. Fall back to fuzzy/date-based matching (use date index for speed)
        if not asana_match:
            campaign_date = (
                campaign.get("dates", {}).get("last_sent") or
                campaign.get("dates", {}).get("created") or
                extract_date_from_braze_name(campaign_name)
            )
            # Only search entries near the campaign date (huge speedup)
            nearby_entries = get_entries_near_date(date_index, campaign_date) if date_index else asana_entries
            asana_match, score, match_method = find_best_match(campaign, nearby_entries, args.threshold)
            if asana_match:
                match_type = f"{match_method}_{score:.0f}%"

        # Report and merge
        if asana_match:
            if args.dry_run:
                print(f"[{match_type.upper()}] {campaign_name[:40]}")
                print(f"    -> {asana_match.get('name', '')[:40]}")
            campaign = merge_campaign_with_asana(campaign, asana_match)
            campaign["asana"]["matched_by"] = match_type
            matched += 1
        else:
            unmatched += 1

        # Save updated campaign
        if not args.dry_run:
            save_yaml(campaign, campaign_file)

    print()
    print(f"Summary:")
    print(f"  Matched: {matched}")
    print(f"  Unmatched: {unmatched}")
    if skipped:
        print(f"  Skipped (other brands): {skipped}")

    if unmatched > 0 and not args.dry_run:
        print()
        print("To manually map unmatched campaigns, create a mappings.yaml file:")
        print("  mappings:")
        print('    "braze-campaign-id": "asana-task-gid"')
        print()
        print("Then run: python scripts/merge_sources.py --mappings mappings.yaml")

if __name__ == "__main__":
    main()
