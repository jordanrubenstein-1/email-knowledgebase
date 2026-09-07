#!/usr/bin/env python3
"""
Revenue-focused recommendation engine for plain text email campaigns.

Uses historical revenue data from GA4 to provide recommendations for
optimizing plain text email campaigns for purchases and revenue.

This module can be imported and used by the automation system to provide
real-time recommendations during campaign creation.
"""

import yaml
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


def is_plain_text(campaign: dict) -> bool:
    """Identify plain text emails."""
    name = campaign.get("name", "")
    if "_pt" in name.lower():
        return True
    
    structure = campaign.get("structure", {})
    if structure.get("layout_type") == "text_only":
        return True
    
    return False


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


def load_high_revenue_campaigns(brand: Optional[str] = None, 
                                min_revenue: float = 100.0,
                                min_sends: int = 100) -> List[Dict[str, Any]]:
    """Load plain text campaigns with significant revenue."""
    campaigns = []
    
    for yaml_file in CAMPAIGNS_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if not data:
                    continue
                
                # Filter by brand
                if brand and data.get("brand") != brand:
                    continue
                
                # Must be plain text
                if not is_plain_text(data):
                    continue
                
                # Must have performance data
                perf = data.get("performance_summary", {})
                total_sends = perf.get("total_sends", 0)
                if total_sends < min_sends:
                    continue
                
                # Must have GA4 revenue data
                ga4 = get_ga4_metrics(data)
                if not ga4["has_ga4_data"] or ga4["revenue"] < min_revenue:
                    continue
                
                data["_filename"] = yaml_file.name
                campaigns.append(data)
        except Exception:
            pass
    
    return campaigns


def calculate_revenue_performance_score(campaign: dict) -> float:
    """Calculate a revenue performance score for a campaign.
    
    Higher score = better revenue performance.
    Considers revenue per send, purchase rate, and total revenue.
    """
    perf = campaign.get("performance_summary", {})
    total_sends = perf.get("total_sends", 0)
    ga4 = get_ga4_metrics(campaign)
    
    if total_sends == 0 or not ga4["has_ga4_data"]:
        return 0.0
    
    revenue = ga4["revenue"]
    purchases = ga4["purchases"]
    
    # Revenue per send (normalized, higher is better)
    revenue_per_send = revenue / total_sends
    
    # Purchase rate (normalized, higher is better)
    purchase_rate = purchases / total_sends
    
    # Combined score (weighted)
    # Revenue per send gets 70% weight, purchase rate gets 30%
    score = (revenue_per_send * 0.7) + (purchase_rate * 1000 * 0.3)  # Scale purchase rate
    
    return score


def extract_campaign_patterns(campaigns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract patterns from high-revenue campaigns."""
    if not campaigns:
        return {}
    
    # Sort by revenue performance
    campaigns_sorted = sorted(
        campaigns,
        key=calculate_revenue_performance_score,
        reverse=True
    )
    
    top_20_percent = campaigns_sorted[:max(1, len(campaigns_sorted) // 5)]
    
    patterns = {
        "subject_features": defaultdict(int),
        "body_features": defaultdict(int),
        "brand_patterns": defaultdict(int),
        "category_patterns": defaultdict(int),
        "timing_patterns": defaultdict(int),
    }
    
    for campaign in top_20_percent:
        brand = campaign.get("brand", "")
        category = campaign.get("category", "")
        
        patterns["brand_patterns"][brand] += 1
        patterns["category_patterns"][category] += 1
        
        # Extract subject features
        for send in campaign.get("sends", []):
            if send.get("channel") == "email":
                subject = send.get("subject", "")
                if subject:
                    subject_lower = subject.lower()
                    
                    if re.search(r'\b(you|your)\b', subject_lower):
                        patterns["subject_features"]["has_you_your"] += 1
                    if '%' in subject or re.search(r'\d+%', subject):
                        patterns["subject_features"]["has_percent"] += 1
                    if '?' in subject:
                        patterns["subject_features"]["has_question"] += 1
                    if re.search(r'\b[A-Z]{3,}\b', subject):
                        patterns["subject_features"]["has_all_caps"] += 1
                    
                    patterns["subject_features"]["avg_length"] += len(subject)
                    patterns["subject_features"]["count"] += 1
                break
        
        # Extract timing
        dates = campaign.get("dates", {})
        first_sent = dates.get("first_sent")
        if first_sent:
            try:
                from datetime import datetime
                if isinstance(first_sent, str):
                    dt = datetime.fromisoformat(first_sent.replace("Z", "+00:00"))
                else:
                    dt = first_sent
                
                # Day of week (0=Monday, 6=Sunday)
                weekday = dt.weekday()
                patterns["timing_patterns"][f"weekday_{weekday}"] += 1
                
                # Hour of day
                hour = dt.hour
                patterns["timing_patterns"][f"hour_{hour}"] += 1
            except Exception:
                pass
    
    # Calculate averages
    if patterns["subject_features"]["count"] > 0:
        patterns["subject_features"]["avg_length"] /= patterns["subject_features"]["count"]
    
    # Convert defaultdicts to regular dicts
    return {
        "subject_features": dict(patterns["subject_features"]),
        "body_features": dict(patterns["body_features"]),
        "brand_patterns": dict(patterns["brand_patterns"]),
        "category_patterns": dict(patterns["category_patterns"]),
        "timing_patterns": dict(patterns["timing_patterns"]),
        "sample_size": len(top_20_percent),
    }


def get_revenue_recommendations(
    brand: str,
    subject: str,
    preheader: str,
    body: str,
    category: str,
    min_revenue: float = 100.0
) -> List[Tuple[str, str]]:
    """
    Get revenue-focused recommendations for a plain text email campaign.
    
    Args:
        brand: Brand code
        subject: Email subject line
        preheader: Email preheader
        body: Email body text
        category: Campaign category
        min_revenue: Minimum revenue threshold for learning campaigns
    
    Returns:
        List of (severity, recommendation) tuples where severity is:
        - "error": Critical issue that likely hurts revenue
        - "warning": Suboptimal pattern that may reduce revenue
        - "info": Optimization opportunity based on high-revenue patterns
    """
    recommendations = []
    
    # Load high-revenue campaigns for this brand
    high_revenue_campaigns = load_high_revenue_campaigns(
        brand=brand,
        min_revenue=min_revenue
    )
    
    if not high_revenue_campaigns:
        # No historical data - use general best practices
        recommendations.append((
            "info",
            "No historical revenue data available for this brand. Using general best practices."
        ))
    else:
        # Extract patterns from high-revenue campaigns
        patterns = extract_campaign_patterns(high_revenue_campaigns)
        
        # Subject line recommendations
        if subject:
            subject_lower = subject.lower()
            subject_features = patterns.get("subject_features", {})
            
            # Check for "You/Your" (strong positive signal)
            has_you_your = bool(re.search(r'\b(you|your)\b', subject_lower))
            you_your_pct = (subject_features.get("has_you_your", 0) / 
                          max(1, patterns.get("sample_size", 1))) * 100
            
            if not has_you_your and you_your_pct > 50:
                if brand == "CZ":
                    recommendations.append((
                        "warning",
                        f"Consider using 'You/Your' in subject line. {you_your_pct:.0f}% of high-revenue campaigns use it (+6.8pt open rate for CZ)."
                    ))
                else:
                    recommendations.append((
                        "info",
                        f"Consider using 'You/Your' in subject line. {you_your_pct:.0f}% of high-revenue campaigns use it (+2.2pt open rate)."
                    ))
            
            # Check for percent signs (negative signal)
            has_percent = '%' in subject or bool(re.search(r'\d+%', subject))
            percent_pct = (subject_features.get("has_percent", 0) / 
                          max(1, patterns.get("sample_size", 1))) * 100
            
            if has_percent and percent_pct < 30:
                recommendations.append((
                    "warning",
                    f"Percent signs in subject correlate with -3.4pt open rate. Only {percent_pct:.0f}% of high-revenue campaigns use them."
                ))
            
            # Check for questions (negative signal)
            has_question = '?' in subject
            question_pct = (subject_features.get("has_question", 0) / 
                           max(1, patterns.get("sample_size", 1))) * 100
            
            if has_question and question_pct < 20:
                recommendations.append((
                    "warning",
                    f"Question marks in subject correlate with -2.7pt open rate. Only {question_pct:.0f}% of high-revenue campaigns use them."
                ))
            
            # Check for ALL CAPS (negative for most brands)
            has_all_caps = bool(re.search(r'\b[A-Z]{3,}\b', subject))
            all_caps_pct = (subject_features.get("has_all_caps", 0) / 
                          max(1, patterns.get("sample_size", 1))) * 100
            
            if has_all_caps and brand != "BUR" and all_caps_pct < 20:
                recommendations.append((
                    "warning",
                    f"ALL CAPS words correlate with -4.4pt open rate. Only {all_caps_pct:.0f}% of high-revenue campaigns use them."
                ))
            
            # Check subject length
            avg_length = subject_features.get("avg_length", 0)
            if avg_length > 0:
                if len(subject) < avg_length * 0.7:
                    recommendations.append((
                        "info",
                        f"Subject line is shorter than average for high-revenue campaigns ({len(subject)} vs {avg_length:.0f} chars)."
                    ))
                elif len(subject) > avg_length * 1.3:
                    recommendations.append((
                        "info",
                        f"Subject line is longer than average for high-revenue campaigns ({len(subject)} vs {avg_length:.0f} chars)."
                    ))
        
        # Category recommendations
        category_patterns = patterns.get("category_patterns", {})
        if category_patterns:
            top_category = max(category_patterns.items(), key=lambda x: x[1])[0]
            if category != top_category:
                recommendations.append((
                    "info",
                    f"Most high-revenue plain text campaigns are '{top_category}' category. Your campaign is '{category}'."
                ))
    
    # General best practices (always include)
    if body:
        # Check for personalization
        if not re.search(r'\{\{.*first_name.*\}\}', body, re.IGNORECASE):
            recommendations.append((
                "warning",
                "Email body should start with personalized greeting (e.g., 'Hi {{${first_name} | default: 'there'}}')."
            ))
        
        # Check link count (0-2 links perform best)
        link_count = len(re.findall(r'<a\s+href|<a\s+[^>]*href', body, re.IGNORECASE))
        if link_count > 2:
            recommendations.append((
                "warning",
                f"Email has {link_count} links. Campaigns with 0-2 links perform 92% better (1.81% vs 0.94% click rate)."
            ))
    
    return recommendations


def format_recommendations(recommendations: List[Tuple[str, str]]) -> str:
    """Format recommendations for display."""
    if not recommendations:
        return "✓ No revenue-focused recommendations."
    
    lines = []
    for severity, message in recommendations:
        if severity == "error":
            lines.append(f"✗ {message}")
        elif severity == "warning":
            lines.append(f"⚠ {message}")
        else:
            lines.append(f"ℹ {message}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Example usage
    recommendations = get_revenue_recommendations(
        brand="HAV",
        subject="Your discount is now up to 70% off",
        preheader="Shop our best deals before they're gone",
        body="Hi {{${first_name} | default: 'there'}},\n\nThis is a test email.",
        category="sale_promo"
    )
    
    print("Revenue-Focused Recommendations:")
    print("=" * 80)
    print(format_recommendations(recommendations))
