#!/usr/bin/env python3
"""
Analyze plain text email campaigns by revenue and purchase performance.

Identifies patterns in high-revenue plain text emails to inform automation system.
Uses GA4 revenue data (sessions, purchases, revenue) to find best practices.

Usage:
    uv run python scripts/analyze_plain_text_revenue.py --brand HAV
    uv run python scripts/analyze_plain_text_revenue.py --all
    uv run python scripts/analyze_plain_text_revenue.py --brand CZ --min-revenue 1000
"""

import yaml
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional
import argparse

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


def is_plain_text(campaign: dict) -> bool:
    """
    Identify plain text emails by:
    - Campaign name contains '_PT' (case-insensitive), OR
    - structure.layout_type == 'text_only'
    """
    name = campaign.get("name", "")
    if "_pt" in name.lower():
        return True
    
    structure = campaign.get("structure", {})
    if structure.get("layout_type") == "text_only":
        return True
    
    return False


def load_campaigns(brand: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load campaign YAML files, optionally filtered by brand."""
    campaigns = []
    
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if data:
                    # Filter by brand if specified
                    if brand and data.get("brand") != brand:
                        continue
                    
                    # Only include plain text campaigns
                    if not is_plain_text(data):
                        continue
                    
                    # Must have performance data
                    perf = data.get("performance_summary", {})
                    if not perf.get("total_sends") or perf["total_sends"] < 100:
                        continue
                    
                    data["_filename"] = yaml_file.name
                    campaigns.append(data)
        except Exception as e:
            print(f"Error loading {yaml_file.name}: {e}")
    
    return campaigns


def get_ga4_metrics(campaign: dict) -> Dict[str, Any]:
    """Extract GA4 metrics from campaign data."""
    perf = campaign.get("performance_summary", {})
    ga4 = perf.get("ga4", {})
    
    return {
        "sessions": ga4.get("sessions", 0),
        "purchases": ga4.get("purchases", 0),
        "revenue": ga4.get("revenue", 0.0),
        "has_ga4_data": bool(ga4.get("sessions") or ga4.get("purchases") or ga4.get("revenue")),
    }


def calculate_revenue_metrics(campaign: dict) -> Dict[str, float]:
    """Calculate revenue per send, purchase rate, etc."""
    perf = campaign.get("performance_summary", {})
    total_sends = perf.get("total_sends", 0)
    ga4 = get_ga4_metrics(campaign)
    
    revenue = ga4["revenue"]
    purchases = ga4["purchases"]
    sessions = ga4["sessions"]
    
    metrics = {
        "revenue_per_send": revenue / total_sends if total_sends > 0 else 0.0,
        "purchase_rate": purchases / total_sends if total_sends > 0 else 0.0,
        "revenue_per_purchase": revenue / purchases if purchases > 0 else 0.0,
        "session_to_purchase_rate": purchases / sessions if sessions > 0 else 0.0,
    }
    
    return metrics


def extract_subject_features(subject: str) -> Dict[str, Any]:
    """Extract features from subject line."""
    if not subject:
        return {}
    
    subject_lower = subject.lower()
    
    return {
        "has_you_your": bool(re.search(r'\b(you|your)\b', subject_lower)),
        "has_percent": '%' in subject or bool(re.search(r'\d+%', subject)),
        "has_question": '?' in subject,
        "has_all_caps": bool(re.search(r'\b[A-Z]{3,}\b', subject)),
        "has_emoji": bool(re.search(r'[😀-🙏🌀-🗿]', subject)),
        "length": len(subject),
        "word_count": len(subject.split()),
    }


def extract_body_features(body: str) -> Dict[str, Any]:
    """Extract features from email body."""
    if not body:
        return {}
    
    body_lower = body.lower()
    
    # Count paragraphs (double newlines or <br><br>)
    paragraph_breaks = len(re.findall(r'\n\s*\n|<br\s*/?>\s*<br\s*/?>', body, re.IGNORECASE))
    paragraph_count = paragraph_breaks + 1 if paragraph_breaks > 0 else 1
    
    # Count links
    link_count = len(re.findall(r'<a\s+href|<a\s+[^>]*href', body, re.IGNORECASE))
    
    # Check for personalization
    has_personalization = bool(re.search(r'\{\{.*first_name.*\}\}', body, re.IGNORECASE))
    
    # Check for urgency words
    urgency_words = ['hurry', 'limited', 'ends soon', 'last chance', 'final', 'today only', 'act now']
    has_urgency = any(word in body_lower for word in urgency_words)
    
    return {
        "paragraph_count": paragraph_count,
        "link_count": link_count,
        "has_personalization": has_personalization,
        "has_urgency": has_urgency,
        "length": len(body),
        "word_count": len(body.split()),
    }


def analyze_high_revenue_campaigns(campaigns: List[Dict[str, Any]], 
                                   min_revenue: float = 0.0,
                                   top_n: int = 20) -> Dict[str, Any]:
    """Analyze top revenue-generating plain text campaigns."""
    # Filter campaigns with GA4 data and minimum revenue
    campaigns_with_revenue = [
        c for c in campaigns
        if get_ga4_metrics(c)["has_ga4_data"] and get_ga4_metrics(c)["revenue"] >= min_revenue
    ]
    
    if not campaigns_with_revenue:
        return {
            "total_campaigns": len(campaigns),
            "campaigns_with_ga4": 0,
            "campaigns_with_revenue": 0,
            "top_campaigns": [],
            "insights": {},
        }
    
    # Sort by revenue
    campaigns_with_revenue.sort(
        key=lambda c: get_ga4_metrics(c)["revenue"],
        reverse=True
    )
    
    top_campaigns = campaigns_with_revenue[:top_n]
    
    # Extract features from top campaigns
    subject_features = defaultdict(int)
    body_features = defaultdict(int)
    brand_counts = defaultdict(int)
    category_counts = defaultdict(int)
    
    total_revenue = 0.0
    total_purchases = 0
    total_sends = 0
    
    for campaign in top_campaigns:
        ga4 = get_ga4_metrics(campaign)
        total_revenue += ga4["revenue"]
        total_purchases += ga4["purchases"]
        total_sends += campaign.get("performance_summary", {}).get("total_sends", 0)
        
        brand = campaign.get("brand", "Unknown")
        brand_counts[brand] += 1
        
        category = campaign.get("category", "other")
        category_counts[category] += 1
        
        # Extract subject features
        for send in campaign.get("sends", []):
            if send.get("channel") == "email":
                subject = send.get("subject", "")
                if subject:
                    features = extract_subject_features(subject)
                    for key, value in features.items():
                        if isinstance(value, bool) and value:
                            subject_features[key] += 1
                        elif isinstance(value, (int, float)):
                            subject_features[key] += value
                    break
        
        # Extract body features (from HTML if available)
        for send in campaign.get("sends", []):
            if send.get("channel") == "email":
                html_file = send.get("html_file")
                if html_file:
                    html_path = CAMPAIGNS_DIR.parent / "campaigns" / html_file
                    if html_path.exists():
                        try:
                            with open(html_path) as f:
                                html_content = f.read()
                                # Extract text content (simplified)
                                body_text = re.sub(r'<[^>]+>', ' ', html_content)
                                features = extract_body_features(body_text)
                                for key, value in features.items():
                                    if isinstance(value, bool) and value:
                                        body_features[key] += 1
                                    elif isinstance(value, (int, float)):
                                        body_features[key] += value
                        except Exception:
                            pass
                break
    
    # Calculate averages
    n = len(top_campaigns)
    avg_features = {}
    if n > 0:
        for key in subject_features:
            avg_features[f"subject_{key}"] = subject_features[key] / n
        for key in body_features:
            avg_features[f"body_{key}"] = body_features[key] / n
    
    insights = {
        "avg_revenue": total_revenue / n if n > 0 else 0.0,
        "avg_purchases": total_purchases / n if n > 0 else 0,
        "avg_revenue_per_send": total_revenue / total_sends if total_sends > 0 else 0.0,
        "avg_purchase_rate": total_purchases / total_sends if total_sends > 0 else 0.0,
        "brand_distribution": dict(brand_counts),
        "category_distribution": dict(category_counts),
        "subject_features": dict(subject_features),
        "body_features": dict(body_features),
        "avg_features": avg_features,
    }
    
    return {
        "total_campaigns": len(campaigns),
        "campaigns_with_ga4": len([c for c in campaigns if get_ga4_metrics(c)["has_ga4_data"]]),
        "campaigns_with_revenue": len(campaigns_with_revenue),
        "top_campaigns": [
            {
                "name": c.get("name", ""),
                "brand": c.get("brand", ""),
                "category": c.get("category", ""),
                "revenue": get_ga4_metrics(c)["revenue"],
                "purchases": get_ga4_metrics(c)["purchases"],
                "sessions": get_ga4_metrics(c)["sessions"],
                "sends": c.get("performance_summary", {}).get("total_sends", 0),
                "revenue_per_send": calculate_revenue_metrics(c)["revenue_per_send"],
                "purchase_rate": calculate_revenue_metrics(c)["purchase_rate"],
            }
            for c in top_campaigns
        ],
        "insights": insights,
    }


def print_analysis_report(analysis: Dict[str, Any]):
    """Print formatted analysis report."""
    print("=" * 80)
    print("PLAIN TEXT EMAIL REVENUE ANALYSIS")
    print("=" * 80)
    print()
    
    print(f"Total plain text campaigns analyzed: {analysis['total_campaigns']}")
    print(f"Campaigns with GA4 data: {analysis['campaigns_with_ga4']}")
    print(f"Campaigns with revenue data: {analysis['campaigns_with_revenue']}")
    print()
    
    if not analysis['top_campaigns']:
        print("No campaigns with revenue data found.")
        return
    
    insights = analysis['insights']
    
    print("TOP REVENUE-GENERATING PLAIN TEXT CAMPAIGNS")
    print("-" * 80)
    print(f"{'Rank':<6} {'Brand':<6} {'Campaign Name':<50} {'Revenue':<12} {'Purchases':<12} {'RPS':<10}")
    print("-" * 80)
    
    for idx, campaign in enumerate(analysis['top_campaigns'][:20], 1):
        name = campaign['name'][:47] + "..." if len(campaign['name']) > 50 else campaign['name']
        revenue = f"${campaign['revenue']:,.2f}"
        rps = f"${campaign['revenue_per_send']:.4f}"
        print(f"{idx:<6} {campaign['brand']:<6} {name:<50} {revenue:<12} {campaign['purchases']:<12} {rps:<10}")
    
    print()
    print("KEY INSIGHTS")
    print("-" * 80)
    print(f"Average revenue per campaign: ${insights['avg_revenue']:,.2f}")
    print(f"Average purchases per campaign: {insights['avg_purchases']:.1f}")
    print(f"Average revenue per send: ${insights['avg_revenue_per_send']:.6f}")
    print(f"Average purchase rate: {insights['avg_purchase_rate']*100:.4f}%")
    print()
    
    print("Brand Distribution (Top Campaigns):")
    for brand, count in sorted(insights['brand_distribution'].items(), key=lambda x: -x[1]):
        print(f"  {brand}: {count} campaigns")
    print()
    
    print("Category Distribution (Top Campaigns):")
    for category, count in sorted(insights['category_distribution'].items(), key=lambda x: -x[1]):
        print(f"  {category}: {count} campaigns")
    print()
    
    if insights.get('subject_features'):
        print("Subject Line Features (Top Campaigns):")
        for feature, count in sorted(insights['subject_features'].items(), key=lambda x: -x[1]):
            if isinstance(count, (int, float)) and count > 0:
                pct = (count / len(analysis['top_campaigns'])) * 100 if analysis['top_campaigns'] else 0
                print(f"  {feature}: {count} ({pct:.1f}%)")
        print()
    
    if insights.get('body_features'):
        print("Body Features (Top Campaigns):")
        for feature, value in sorted(insights['body_features'].items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
            if isinstance(value, (int, float)) and value > 0:
                if feature.endswith('_count'):
                    avg = value / len(analysis['top_campaigns']) if analysis['top_campaigns'] else 0
                    print(f"  {feature}: {avg:.1f} (avg)")
                else:
                    pct = (value / len(analysis['top_campaigns'])) * 100 if analysis['top_campaigns'] else 0
                    print(f"  {feature}: {value} ({pct:.1f}%)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze plain text email campaigns by revenue performance"
    )
    parser.add_argument(
        "--brand",
        type=str,
        help="Brand to analyze (HAV, CZ, ID, BUR, STF, TI)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze all brands"
    )
    parser.add_argument(
        "--min-revenue",
        type=float,
        default=0.0,
        help="Minimum revenue threshold (default: 0.0)"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of top campaigns to analyze in detail (default: 20)"
    )
    
    args = parser.parse_args()
    
    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return
    
    print("Loading plain text campaigns...")
    campaigns = load_campaigns(brand=args.brand)
    print(f"Found {len(campaigns)} plain text campaigns")
    
    if not campaigns:
        print("No plain text campaigns found.")
        return
    
    print(f"\nAnalyzing campaigns with revenue >= ${args.min_revenue:,.2f}...")
    analysis = analyze_high_revenue_campaigns(
        campaigns,
        min_revenue=args.min_revenue,
        top_n=args.top_n
    )
    
    print_analysis_report(analysis)


if __name__ == "__main__":
    main()
