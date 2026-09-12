#!/usr/bin/env python3
"""
Analyze CZ SMS performance by placement of "The Citizenry" in the message body.

Categories:
- "Starts with": Message body begins with "The Citizenry:" (or very close to the start)
- "Mentioned later": "The Citizenry" appears somewhere in the body but NOT at the very beginning
- "Not mentioned": "The Citizenry" doesn't appear in the message at all
- "Unknown": Can't determine (no body available)

Fetches SMS bodies from the Braze API since they aren't stored in the YAML files.
"""

import os
import re
import sys
import glob
import time
import json
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv
import requests

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Braze config for CZ
BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY_CZ") or os.environ.get("BRAZE_API_KEY")
BRAZE_BASE_URL = os.environ.get("BRAZE_BASE_URL_CZ", os.environ.get("BRAZE_BASE_URL", "https://rest.iad-07.braze.com"))

CAMPAIGNS_DIR = PROJECT_ROOT / "campaigns"
CACHE_FILE = PROJECT_ROOT / "scripts" / "analysis" / "_cz_sms_bodies_cache.json"


def braze_request(endpoint, params=None):
    """Make a request to Braze API."""
    headers = {
        "Authorization": f"Bearer {BRAZE_API_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{BRAZE_BASE_URL}/{endpoint}"
    response = requests.get(url, headers=headers, params=params)
    if response.status_code not in (200, 201):
        print(f"  Error {response.status_code}: {response.text[:200]}")
        return None
    return response.json()


def load_cz_sms_campaigns():
    """Load all CZ SMS campaign YAML files."""
    campaigns = []
    for f in glob.glob(str(CAMPAIGNS_DIR / "*.yaml")):
        with open(f) as fh:
            try:
                data = yaml.safe_load(fh)
            except Exception:
                continue
        if not data:
            continue
        # Check for CZ SMS campaigns
        if data.get("brand") == "CZ" and data.get("channel") == "sms":
            data["_file"] = os.path.basename(f)
            campaigns.append(data)
    return campaigns


def get_sms_body_from_braze(campaign_id, canvas_id=None, step_id=None):
    """Fetch SMS body text from Braze API."""
    if canvas_id:
        # Canvas step - get canvas details
        data = braze_request("canvas/details", {"canvas_id": canvas_id})
        if data and "steps" in data:
            for step in data["steps"]:
                if step.get("id") == step_id:
                    messages = step.get("messages", {})
                    for msg_key, msg_data in messages.items():
                        if isinstance(msg_data, dict):
                            body = msg_data.get("body", "")
                            if body:
                                return body
        return None
    else:
        # Regular campaign
        data = braze_request("campaigns/details", {"campaign_id": campaign_id})
        if not data:
            return None

        # Look for SMS body in messages
        messages = data.get("messages", {})
        for msg_key, msg_data in messages.items():
            if isinstance(msg_data, dict):
                # SMS messages have a "body" field
                body = msg_data.get("body", "")
                if body:
                    return body
                # Also check "message" field
                message = msg_data.get("message", "")
                if message:
                    return message

        return None


def load_or_fetch_sms_bodies(campaigns):
    """Load SMS bodies from cache or fetch from Braze API."""
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        print(f"Loaded {len(cache)} cached SMS bodies")

    fetched = 0
    for c in campaigns:
        cid = c.get("braze_id") or c.get("id")
        if cid in cache:
            c["_sms_body"] = cache[cid]
            continue

        # Need to fetch from Braze
        canvas_id = c.get("canvas_id")
        step_id = None
        if c.get("braze_type") == "canvas_step":
            # For canvas steps, find the step ID
            for send in c.get("sends", []):
                if send.get("step_id"):
                    step_id = send["step_id"]
                    break

        body = get_sms_body_from_braze(cid, canvas_id=canvas_id, step_id=step_id)
        c["_sms_body"] = body
        cache[cid] = body
        fetched += 1

        if fetched % 10 == 0:
            print(f"  Fetched {fetched} SMS bodies from Braze...")
            # Save cache periodically
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f, indent=2)

        # Rate limit
        time.sleep(0.1)

    # Save cache
    if fetched > 0:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"Fetched {fetched} new SMS bodies from Braze (total cached: {len(cache)})")

    return campaigns


def categorize_sms(body):
    """Categorize SMS by placement of 'The Citizenry' in the body."""
    if not body:
        return "Unknown"

    # Clean up the body - remove leading whitespace
    clean_body = body.strip()

    # Check if it starts with "The Citizenry" (with possible Liquid tags before)
    # Also handle cases like "The Citizenry:" or "The Citizenry -"
    # Remove any leading Liquid tags like {{${first_name}}} etc
    stripped = re.sub(r'^\s*(\{\{[^}]*\}\}\s*)*', '', clean_body)

    if re.match(r'^The Citizenry\b', stripped, re.IGNORECASE):
        return "Starts with"

    if re.search(r'The Citizenry', clean_body, re.IGNORECASE):
        return "Mentioned later"

    # Also check for just "Citizenry"
    if re.search(r'Citizenry', clean_body, re.IGNORECASE):
        return "Mentioned later"

    return "Not mentioned"


def analyze_performance(campaigns_by_category):
    """Analyze performance metrics for each category."""
    results = {}
    for category, campaigns in campaigns_by_category.items():
        total_sends = 0
        total_clicks = 0
        total_delivered = 0
        total_unsubscribes = 0
        total_opens = 0
        click_rates = []
        count = 0

        for c in campaigns:
            perf = c.get("performance_summary", {})
            sends = perf.get("total_sends", 0)
            clicks = perf.get("total_clicks", 0)
            delivered = perf.get("total_delivered", 0)
            unsubs = perf.get("total_unsubscribes", 0)
            opens = perf.get("total_opens", 0)

            if sends > 0:
                total_sends += sends
                total_clicks += clicks
                total_delivered += delivered
                total_unsubscribes += unsubs
                total_opens += opens
                click_rates.append(perf.get("click_rate", 0))
                count += 1

        avg_click_rate = sum(click_rates) / len(click_rates) if click_rates else 0
        overall_click_rate = total_clicks / total_sends if total_sends > 0 else 0
        unsub_rate = total_unsubscribes / total_sends if total_sends > 0 else 0

        # GA4 revenue data
        total_revenue = 0
        total_sessions = 0
        total_purchases = 0
        for c in campaigns:
            ga4 = c.get("performance_summary", {}).get("ga4", {})
            total_revenue += ga4.get("revenue", 0) or 0
            total_sessions += ga4.get("sessions", 0) or 0
            total_purchases += ga4.get("purchases", 0) or 0

        results[category] = {
            "count": count,
            "total_sends": total_sends,
            "total_clicks": total_clicks,
            "total_delivered": total_delivered,
            "total_unsubscribes": total_unsubscribes,
            "avg_click_rate": avg_click_rate,
            "overall_click_rate": overall_click_rate,
            "unsub_rate": unsub_rate,
            "revenue": total_revenue,
            "sessions": total_sessions,
            "purchases": total_purchases,
            "revenue_per_send": total_revenue / total_sends if total_sends > 0 else 0,
        }

    return results


def print_report(campaigns_by_category, perf_results):
    """Print the analysis report."""
    print("\n" + "=" * 80)
    print("CZ SMS ANALYSIS: 'The Citizenry' Brand Name Placement")
    print("=" * 80)

    # Summary table
    print("\n## PERFORMANCE SUMMARY BY CATEGORY\n")
    print(f"{'Category':<20} {'Count':>6} {'Sends':>10} {'Clicks':>8} {'Click Rate':>12} {'Avg CR':>10} {'Unsub Rate':>12} {'Revenue':>10} {'Rev/Send':>10}")
    print("-" * 110)

    for cat in ["Starts with", "Mentioned later", "Not mentioned", "Unknown"]:
        if cat in perf_results:
            r = perf_results[cat]
            print(f"{cat:<20} {r['count']:>6} {r['total_sends']:>10,} {r['total_clicks']:>8,} "
                  f"{r['overall_click_rate']:>11.2%} {r['avg_click_rate']:>9.2%} "
                  f"{r['unsub_rate']:>11.4%} ${r['revenue']:>9,.0f} ${r['revenue_per_send']:>9.4f}")

    # Examples for each category
    for cat in ["Starts with", "Mentioned later", "Not mentioned", "Unknown"]:
        campaigns = campaigns_by_category.get(cat, [])
        if not campaigns:
            continue

        print(f"\n\n## EXAMPLES: {cat.upper()} ({len(campaigns)} campaigns)")
        print("-" * 80)

        # Sort by sends (descending) to show most impactful examples
        examples = sorted(campaigns, key=lambda c: c.get("performance_summary", {}).get("total_sends", 0), reverse=True)

        for c in examples[:5]:
            perf = c.get("performance_summary", {})
            body = c.get("_sms_body", "")
            name = c.get("name", "Unknown")
            sends = perf.get("total_sends", 0)
            clicks = perf.get("total_clicks", 0)
            cr = perf.get("click_rate", 0)
            ga4 = perf.get("ga4", {})
            rev = ga4.get("revenue", 0) or 0
            date = c.get("dates", {}).get("first_sent", "")[:10]

            print(f"\n  Campaign: {name}")
            print(f"  Date: {date} | Sends: {sends:,} | Clicks: {clicks:,} | Click Rate: {cr:.2%} | Revenue: ${rev:,.0f}")
            if body:
                # Truncate long bodies
                display_body = body[:300] + ("..." if len(body) > 300 else "")
                print(f"  Body: {display_body}")
            else:
                print(f"  Body: [not available]")

    # Statistical comparison
    print("\n\n## KEY FINDINGS")
    print("=" * 80)

    starts = perf_results.get("Starts with", {})
    mentioned = perf_results.get("Mentioned later", {})
    not_mentioned = perf_results.get("Not mentioned", {})

    if starts and mentioned:
        diff = starts.get("overall_click_rate", 0) - mentioned.get("overall_click_rate", 0)
        pct_diff = (diff / mentioned.get("overall_click_rate", 1)) * 100 if mentioned.get("overall_click_rate", 0) > 0 else 0
        print(f"\n  'Starts with' vs 'Mentioned later' click rate difference: {diff:+.4f} ({pct_diff:+.1f}%)")

    if starts and not_mentioned:
        diff = starts.get("overall_click_rate", 0) - not_mentioned.get("overall_click_rate", 0)
        pct_diff = (diff / not_mentioned.get("overall_click_rate", 1)) * 100 if not_mentioned.get("overall_click_rate", 0) > 0 else 0
        print(f"  'Starts with' vs 'Not mentioned' click rate difference: {diff:+.4f} ({pct_diff:+.1f}%)")

    if mentioned and not_mentioned:
        diff = mentioned.get("overall_click_rate", 0) - not_mentioned.get("overall_click_rate", 0)
        pct_diff = (diff / not_mentioned.get("overall_click_rate", 1)) * 100 if not_mentioned.get("overall_click_rate", 0) > 0 else 0
        print(f"  'Mentioned later' vs 'Not mentioned' click rate difference: {diff:+.4f} ({pct_diff:+.1f}%)")

    # Revenue comparison
    print("\n  Revenue per Send:")
    for cat in ["Starts with", "Mentioned later", "Not mentioned"]:
        if cat in perf_results:
            r = perf_results[cat]
            print(f"    {cat}: ${r['revenue_per_send']:.4f} ({r['purchases']} purchases from {r['total_sends']:,} sends)")

    # Unsubscribe comparison
    print("\n  Unsubscribe Rate:")
    for cat in ["Starts with", "Mentioned later", "Not mentioned"]:
        if cat in perf_results:
            r = perf_results[cat]
            print(f"    {cat}: {r['unsub_rate']:.4%} ({r['total_unsubscribes']:,} unsubs)")


def main():
    if not BRAZE_API_KEY:
        print("Error: No Braze API key found for CZ. Set BRAZE_API_KEY_CZ or BRAZE_API_KEY in .env")
        sys.exit(1)

    print("Loading CZ SMS campaigns from YAML files...")
    campaigns = load_cz_sms_campaigns()
    print(f"Found {len(campaigns)} CZ SMS campaigns")

    if not campaigns:
        print("No CZ SMS campaigns found!")
        sys.exit(1)

    print("\nFetching SMS bodies from Braze API (or cache)...")
    campaigns = load_or_fetch_sms_bodies(campaigns)

    # Show how many have bodies
    with_body = sum(1 for c in campaigns if c.get("_sms_body"))
    print(f"\n{with_body}/{len(campaigns)} campaigns have SMS body text")

    # Categorize
    campaigns_by_category = {
        "Starts with": [],
        "Mentioned later": [],
        "Not mentioned": [],
        "Unknown": [],
    }

    for c in campaigns:
        category = categorize_sms(c.get("_sms_body"))
        c["_category"] = category
        campaigns_by_category[category].append(c)

    print(f"\nCategorization:")
    for cat, camps in campaigns_by_category.items():
        print(f"  {cat}: {len(camps)}")

    # Analyze performance
    perf_results = analyze_performance(campaigns_by_category)

    # Print report
    print_report(campaigns_by_category, perf_results)


if __name__ == "__main__":
    main()
