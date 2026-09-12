"""
Analyze CZ (The Citizenry) SMS campaign performance when a correlated email
is sent on the same day vs. a different day.

Matching strategy:
1. Extract descriptive keywords from campaign names (strip date, brand, channel prefix, suffixes)
2. Combine keyword overlap with temporal proximity (within 7 days)
3. Also consider category, sale_period, and subject line keywords
4. Score matches and take best match per SMS campaign

Key metrics compared:
- click_rate (unique clicks / total sends) — primary metric
- total_clicks — absolute engagement
- GA4 sessions & revenue where available
"""

import os
import re
import yaml
import glob
from datetime import datetime, timedelta
from collections import defaultdict
from difflib import SequenceMatcher

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
CAMPAIGNS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "campaigns")
MIN_SENDS = 1000  # minimum sends to include
MAX_DAYS_APART = 7  # maximum days between SMS and email to consider a match
MIN_MATCH_SCORE = 0.25  # minimum combined score to accept a match

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_campaigns():
    """Load all CZ campaigns from YAML files."""
    campaigns = []
    pattern = os.path.join(CAMPAIGNS_DIR, "*.yaml")
    for filepath in glob.glob(pattern):
        try:
            with open(filepath, "r") as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict) and data.get("brand") == "CZ":
                data["_filepath"] = filepath
                campaigns.append(data)
        except Exception as e:
            pass  # skip malformed files
    return campaigns


def parse_send_date(campaign):
    """Extract the send date as a date object from first_sent."""
    dates = campaign.get("dates", {})
    first_sent = dates.get("first_sent")
    if not first_sent:
        return None
    if isinstance(first_sent, str):
        # Handle various datetime formats
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(first_sent, fmt).date()
            except ValueError:
                continue
        # Try dateutil as fallback
        try:
            from dateutil.parser import parse as dateparse
            return dateparse(first_sent).date()
        except:
            pass
    elif isinstance(first_sent, datetime):
        return first_sent.date()
    return None


def extract_keywords(campaign_name):
    """
    Extract descriptive keywords from a campaign name.

    Examples:
        P_EM_2025_10_09_CZ_D_PR_Anniversary_Sale_Announcement -> anniversary sale announcement
        P_SMS_2025_10_09_CZ_Anniversary_Sale_Launch -> anniversary sale launch
        P_2025_5_15_CZ_MDW_Announcement_SMS -> mdw announcement
    """
    if not campaign_name:
        return set()

    name = campaign_name.upper()

    # Remove common prefixes: P_EM_, P_SMS_, P_, COPY-OF-, TRADE_
    name = re.sub(r'^(COPY[-_]OF[-_])?', '', name)
    name = re.sub(r'^(P_EM_|P_SMS_|P_|TRADE_)', '', name)

    # Remove date patterns: 2025_10_09, 2025_5_15, 20250504
    name = re.sub(r'\d{4}_\d{1,2}_\d{1,2}_?', '', name)
    name = re.sub(r'\d{8}_?', '', name)

    # Remove brand code CZ
    name = re.sub(r'_?CZ_?', ' ', name)

    # Remove common channel/type suffixes and prefixes
    noise_words = {
        'SMS', 'EMAIL', 'EM', 'D', 'PR', 'PT', 'AM', 'PM',
        'PF', 'ME', 'PC', 'B', 'VARIANT', 'CONTROL', 'GROUP',
        'ENGAGED', 'TRADE', 'COPY', 'OF',
    }

    # Split on underscores and hyphens
    parts = re.split(r'[_\-\s]+', name)

    # Filter out noise and empty parts
    keywords = set()
    for part in parts:
        part = part.strip()
        if part and part not in noise_words and len(part) > 1:
            keywords.add(part.lower())

    return keywords


def extract_subject_keywords(campaign):
    """Extract keywords from email subject lines."""
    keywords = set()
    sends = campaign.get("sends", [])
    for send in sends:
        subject = send.get("subject", "")
        if subject:
            # Remove punctuation and common words
            words = re.findall(r'[a-zA-Z]+', subject.lower())
            stop_words = {
                'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be',
                'been', 'being', 'have', 'has', 'had', 'do', 'does',
                'did', 'will', 'would', 'could', 'should', 'may',
                'might', 'must', 'shall', 'can', 'for', 'and', 'nor',
                'but', 'or', 'yet', 'so', 'at', 'by', 'in', 'of',
                'on', 'to', 'up', 'it', 'its', 'your', 'our', 'you',
                'we', 'this', 'that', 'with', 'from', 'off', 'now',
                'new', 'just', 'get', 'all', 'out', 'don', 'miss',
            }
            for w in words:
                if w not in stop_words and len(w) > 2:
                    keywords.add(w)
    return keywords


def get_sale_context(campaign):
    """Extract sale context info for matching."""
    sale_period = campaign.get("sale_period", {})
    if not sale_period:
        return None, None
    sale_name = sale_period.get("sale_name", "")
    sale_discount = sale_period.get("sale_discount", "")
    return sale_name, sale_discount


def compute_match_score(sms_campaign, email_campaign):
    """
    Compute a match score (0-1) between an SMS campaign and an email campaign.

    Combines:
    - Keyword overlap from campaign names (weight: 0.5)
    - Subject line keyword overlap (weight: 0.15)
    - Category match (weight: 0.1)
    - Sale period match (weight: 0.15)
    - Temporal proximity (weight: 0.1)
    """
    score = 0.0
    details = {}

    # 1. Keyword overlap from names
    sms_kw = extract_keywords(sms_campaign.get("name", ""))
    email_kw = extract_keywords(email_campaign.get("name", ""))

    if sms_kw and email_kw:
        intersection = sms_kw & email_kw
        union = sms_kw | email_kw
        jaccard = len(intersection) / len(union) if union else 0
        score += 0.5 * jaccard
        details["keyword_overlap"] = intersection
        details["jaccard"] = jaccard

    # 2. Subject line keywords (email has subject, SMS may not)
    email_subj_kw = extract_subject_keywords(email_campaign)
    if email_subj_kw and sms_kw:
        subj_overlap = sms_kw & email_subj_kw
        if sms_kw:
            subj_score = len(subj_overlap) / len(sms_kw)
            score += 0.15 * min(subj_score, 1.0)
            details["subject_overlap"] = subj_overlap

    # 3. Category match
    sms_cat = sms_campaign.get("category", "")
    email_cat = email_campaign.get("category", "")
    if sms_cat and email_cat and sms_cat == email_cat:
        score += 0.1
        details["category_match"] = True
    elif sms_cat and email_cat:
        # Partial credit for related categories
        related = {
            frozenset({"sale_promo", "reminder"}),
            frozenset({"product_launch", "editorial"}),
        }
        if frozenset({sms_cat, email_cat}) in related:
            score += 0.05
            details["category_related"] = True

    # 4. Sale period match
    sms_sale, _ = get_sale_context(sms_campaign)
    email_sale, _ = get_sale_context(email_campaign)
    if sms_sale and email_sale and sms_sale == email_sale:
        score += 0.15
        details["sale_match"] = sms_sale
    elif sms_sale and email_sale:
        # Fuzzy sale name match
        ratio = SequenceMatcher(None, sms_sale.lower(), email_sale.lower()).ratio()
        if ratio > 0.6:
            score += 0.15 * ratio
            details["sale_fuzzy_match"] = (sms_sale, email_sale, ratio)

    # 5. Temporal proximity
    sms_date = parse_send_date(sms_campaign)
    email_date = parse_send_date(email_campaign)
    if sms_date and email_date:
        days_apart = abs((sms_date - email_date).days)
        if days_apart <= MAX_DAYS_APART:
            proximity = 1.0 - (days_apart / MAX_DAYS_APART)
            score += 0.1 * proximity
            details["days_apart"] = days_apart

    details["total_score"] = score
    return score, details


def find_best_email_match(sms_campaign, email_campaigns):
    """Find the best matching email campaign for a given SMS campaign."""
    sms_date = parse_send_date(sms_campaign)
    if not sms_date:
        return None, 0, {}

    best_match = None
    best_score = 0
    best_details = {}

    for email in email_campaigns:
        email_date = parse_send_date(email)
        if not email_date:
            continue

        # Only consider emails within the time window
        days_apart = abs((sms_date - email_date).days)
        if days_apart > MAX_DAYS_APART:
            continue

        score, details = compute_match_score(sms_campaign, email)
        if score > best_score and score >= MIN_MATCH_SCORE:
            best_score = score
            best_match = email
            best_details = details

    return best_match, best_score, best_details


def fmt_pct(value, digits=4):
    """Format a decimal as a percentage string."""
    if value is None:
        return "N/A"
    return f"{value * 100:.{digits}f}%"


def fmt_num(value):
    """Format a number with comma separators."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}"


# ──────────────────────────────────────────────────────────────────────────────
# Main Analysis
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("CZ (The Citizenry) SMS + Email Correlation Analysis")
    print("=" * 80)
    print()

    # Load campaigns
    all_campaigns = load_campaigns()
    print(f"Total CZ campaigns loaded: {len(all_campaigns)}")

    # Separate by channel
    sms_campaigns = []
    email_campaigns = []
    other_campaigns = []

    for c in all_campaigns:
        channel = c.get("channel", "")
        # Also check name for channel hints
        name = c.get("name", "").upper()
        perf = c.get("performance_summary", {})
        total_sends = perf.get("total_sends", 0)

        if channel == "sms" or (channel == "other" and "SMS" in name):
            if total_sends >= MIN_SENDS:
                sms_campaigns.append(c)
        elif channel == "email":
            if total_sends >= MIN_SENDS:
                email_campaigns.append(c)
        else:
            other_campaigns.append(c)

    print(f"CZ SMS campaigns (>= {MIN_SENDS} sends): {len(sms_campaigns)}")
    print(f"CZ Email campaigns (>= {MIN_SENDS} sends): {len(email_campaigns)}")
    print()

    # Exclude canvas/triggered campaigns — focus on batch sends (one-time)
    # Canvas steps are triggered journeys, not comparable for same-day analysis
    batch_sms = [c for c in sms_campaigns if c.get("braze_type") != "canvas_step"]
    batch_email = [c for c in email_campaigns if c.get("braze_type") != "canvas_step"]

    print(f"Batch SMS campaigns (excluding canvas steps): {len(batch_sms)}")
    print(f"Batch Email campaigns (excluding canvas steps): {len(batch_email)}")
    print()

    # ── Match SMS to Email ──────────────────────────────────────────────────
    print("-" * 80)
    print("MATCHING SMS CAMPAIGNS TO CORRELATED EMAILS")
    print("-" * 80)
    print()

    matched_pairs = []
    unmatched_sms = []

    for sms in batch_sms:
        email_match, score, details = find_best_email_match(sms, batch_email)
        if email_match:
            days_apart = details.get("days_apart", None)
            sms_date = parse_send_date(sms)
            email_date = parse_send_date(email_match)
            same_day = (days_apart == 0) if days_apart is not None else False

            matched_pairs.append({
                "sms": sms,
                "email": email_match,
                "score": score,
                "details": details,
                "days_apart": days_apart,
                "same_day": same_day,
                "sms_date": sms_date,
                "email_date": email_date,
            })
        else:
            unmatched_sms.append(sms)

    print(f"Matched SMS-email pairs: {len(matched_pairs)}")
    print(f"Unmatched SMS campaigns: {len(unmatched_sms)}")
    print()

    # Show match quality distribution
    score_bins = {"0.25-0.40": 0, "0.40-0.55": 0, "0.55-0.70": 0, "0.70-0.85": 0, "0.85-1.0": 0}
    for pair in matched_pairs:
        s = pair["score"]
        if s < 0.40:
            score_bins["0.25-0.40"] += 1
        elif s < 0.55:
            score_bins["0.40-0.55"] += 1
        elif s < 0.70:
            score_bins["0.55-0.70"] += 1
        elif s < 0.85:
            score_bins["0.70-0.85"] += 1
        else:
            score_bins["0.85-1.0"] += 1

    print("Match Score Distribution:")
    for bin_label, count in score_bins.items():
        bar = "#" * count
        print(f"  {bin_label}: {count:3d} {bar}")
    print()

    # ── Split into Same-Day vs. Different-Day ──────────────────────────────
    same_day_pairs = [p for p in matched_pairs if p["same_day"]]
    diff_day_pairs = [p for p in matched_pairs if not p["same_day"]]

    print(f"Same-day pairs: {len(same_day_pairs)}")
    print(f"Different-day pairs: {len(diff_day_pairs)}")
    print()

    # ── Aggregate SMS Performance Comparison ───────────────────────────────
    print("=" * 80)
    print("SMS PERFORMANCE: SAME-DAY vs. DIFFERENT-DAY EMAIL CORRELATION")
    print("=" * 80)
    print()

    def aggregate_sms_metrics(pairs):
        """Aggregate SMS metrics from a list of matched pairs."""
        total_sends = 0
        total_clicks = 0
        total_delivered = 0
        click_rates = []
        ga4_sessions = 0
        ga4_revenue = 0.0
        ga4_purchases = 0
        campaigns_with_ga4 = 0

        for pair in pairs:
            perf = pair["sms"].get("performance_summary", {})
            sends = perf.get("total_sends", 0)
            clicks = perf.get("total_clicks", 0)
            delivered = perf.get("total_delivered", 0)
            cr = perf.get("click_rate", 0)

            total_sends += sends
            total_clicks += clicks
            total_delivered += delivered
            if cr > 0:
                click_rates.append(cr)

            ga4 = perf.get("ga4", {})
            if ga4:
                ga4_sessions += ga4.get("sessions", 0)
                ga4_revenue += ga4.get("revenue", 0.0) or 0.0
                ga4_purchases += ga4.get("purchases", 0)
                campaigns_with_ga4 += 1

        avg_click_rate = sum(click_rates) / len(click_rates) if click_rates else 0
        weighted_click_rate = total_clicks / total_sends if total_sends > 0 else 0

        return {
            "count": len(pairs),
            "total_sends": total_sends,
            "total_clicks": total_clicks,
            "total_delivered": total_delivered,
            "avg_click_rate": avg_click_rate,
            "weighted_click_rate": weighted_click_rate,
            "median_click_rate": sorted(click_rates)[len(click_rates) // 2] if click_rates else 0,
            "ga4_sessions": ga4_sessions,
            "ga4_revenue": ga4_revenue,
            "ga4_purchases": ga4_purchases,
            "campaigns_with_ga4": campaigns_with_ga4,
        }

    same_day_metrics = aggregate_sms_metrics(same_day_pairs)
    diff_day_metrics = aggregate_sms_metrics(diff_day_pairs)

    # Print comparison table
    headers = ["Metric", "Same Day", "Different Day", "Delta"]
    col_widths = [35, 18, 18, 18]

    def print_row(cells, widths=col_widths):
        row = ""
        for cell, w in zip(cells, widths):
            row += str(cell).ljust(w)
        print(row)

    def delta_str(same, diff, is_pct=False):
        if same == 0 and diff == 0:
            return "N/A"
        if diff == 0:
            return "+inf"
        change = (same - diff) / diff
        sign = "+" if change >= 0 else ""
        if is_pct:
            return f"{sign}{change * 100:.1f}%"
        return f"{sign}{change * 100:.1f}%"

    print_row(headers)
    print_row(["-" * w for w in col_widths])

    print_row([
        "Campaign Count",
        same_day_metrics["count"],
        diff_day_metrics["count"],
        ""
    ])
    print_row([
        "Total SMS Sends",
        fmt_num(same_day_metrics["total_sends"]),
        fmt_num(diff_day_metrics["total_sends"]),
        ""
    ])
    print_row([
        "Total SMS Clicks",
        fmt_num(same_day_metrics["total_clicks"]),
        fmt_num(diff_day_metrics["total_clicks"]),
        ""
    ])
    print_row([
        "Weighted Click Rate",
        fmt_pct(same_day_metrics["weighted_click_rate"]),
        fmt_pct(diff_day_metrics["weighted_click_rate"]),
        delta_str(same_day_metrics["weighted_click_rate"], diff_day_metrics["weighted_click_rate"])
    ])
    print_row([
        "Avg Click Rate (per campaign)",
        fmt_pct(same_day_metrics["avg_click_rate"]),
        fmt_pct(diff_day_metrics["avg_click_rate"]),
        delta_str(same_day_metrics["avg_click_rate"], diff_day_metrics["avg_click_rate"])
    ])
    print_row([
        "Median Click Rate",
        fmt_pct(same_day_metrics["median_click_rate"]),
        fmt_pct(diff_day_metrics["median_click_rate"]),
        delta_str(same_day_metrics["median_click_rate"], diff_day_metrics["median_click_rate"])
    ])
    print_row([
        "GA4 Sessions (total)",
        fmt_num(same_day_metrics["ga4_sessions"]),
        fmt_num(diff_day_metrics["ga4_sessions"]),
        ""
    ])
    print_row([
        "GA4 Revenue (total)",
        f"${fmt_num(same_day_metrics['ga4_revenue'])}",
        f"${fmt_num(diff_day_metrics['ga4_revenue'])}",
        ""
    ])
    print_row([
        "GA4 Purchases (total)",
        fmt_num(same_day_metrics["ga4_purchases"]),
        fmt_num(diff_day_metrics["ga4_purchases"]),
        ""
    ])

    # Revenue per send
    same_rps = same_day_metrics["ga4_revenue"] / same_day_metrics["total_sends"] if same_day_metrics["total_sends"] > 0 else 0
    diff_rps = diff_day_metrics["ga4_revenue"] / diff_day_metrics["total_sends"] if diff_day_metrics["total_sends"] > 0 else 0
    print_row([
        "GA4 Revenue per Send",
        f"${same_rps:.4f}",
        f"${diff_rps:.4f}",
        delta_str(same_rps, diff_rps)
    ])
    print()

    # ── Breakdown by Days Apart ────────────────────────────────────────────
    print("=" * 80)
    print("SMS PERFORMANCE BY DAYS APART FROM CORRELATED EMAIL")
    print("=" * 80)
    print()

    days_buckets = defaultdict(list)
    for pair in matched_pairs:
        d = pair["days_apart"]
        if d == 0:
            days_buckets["0 (Same Day)"].append(pair)
        elif d == 1:
            days_buckets["1 Day"].append(pair)
        elif d == 2:
            days_buckets["2 Days"].append(pair)
        elif d <= 4:
            days_buckets["3-4 Days"].append(pair)
        else:
            days_buckets["5-7 Days"].append(pair)

    bucket_order = ["0 (Same Day)", "1 Day", "2 Days", "3-4 Days", "5-7 Days"]

    b_headers = ["Days Apart", "Count", "Avg Click Rate", "Wtd Click Rate", "GA4 Rev/Send"]
    b_widths = [18, 8, 18, 18, 18]
    print_row(b_headers, b_widths)
    print_row(["-" * w for w in b_widths], b_widths)

    for bucket in bucket_order:
        pairs = days_buckets.get(bucket, [])
        if not pairs:
            continue
        metrics = aggregate_sms_metrics(pairs)
        rps = metrics["ga4_revenue"] / metrics["total_sends"] if metrics["total_sends"] > 0 else 0
        print_row([
            bucket,
            metrics["count"],
            fmt_pct(metrics["avg_click_rate"]),
            fmt_pct(metrics["weighted_click_rate"]),
            f"${rps:.4f}",
        ], b_widths)
    print()

    # ── Breakdown by Category ──────────────────────────────────────────────
    print("=" * 80)
    print("SMS PERFORMANCE BY CATEGORY: SAME-DAY vs. DIFFERENT-DAY")
    print("=" * 80)
    print()

    # Group by category
    categories = defaultdict(lambda: {"same_day": [], "diff_day": []})
    for pair in matched_pairs:
        cat = pair["sms"].get("category", "unknown")
        if pair["same_day"]:
            categories[cat]["same_day"].append(pair)
        else:
            categories[cat]["diff_day"].append(pair)

    for cat in sorted(categories.keys()):
        data = categories[cat]
        sd_pairs = data["same_day"]
        dd_pairs = data["diff_day"]

        if not sd_pairs and not dd_pairs:
            continue

        print(f"Category: {cat}")
        print(f"  Same-day: {len(sd_pairs)} pairs | Different-day: {len(dd_pairs)} pairs")

        if sd_pairs:
            sd_m = aggregate_sms_metrics(sd_pairs)
            print(f"    Same-Day    -> Avg CR: {fmt_pct(sd_m['avg_click_rate'])} | "
                  f"Wtd CR: {fmt_pct(sd_m['weighted_click_rate'])} | "
                  f"Sends: {fmt_num(sd_m['total_sends'])}")
        if dd_pairs:
            dd_m = aggregate_sms_metrics(dd_pairs)
            print(f"    Diff-Day    -> Avg CR: {fmt_pct(dd_m['avg_click_rate'])} | "
                  f"Wtd CR: {fmt_pct(dd_m['weighted_click_rate'])} | "
                  f"Sends: {fmt_num(dd_m['total_sends'])}")

        if sd_pairs and dd_pairs:
            sd_m = aggregate_sms_metrics(sd_pairs)
            dd_m = aggregate_sms_metrics(dd_pairs)
            delta = delta_str(sd_m["weighted_click_rate"], dd_m["weighted_click_rate"])
            print(f"    Delta (same vs diff weighted CR): {delta}")
        print()

    # ── Specific Examples ──────────────────────────────────────────────────
    print("=" * 80)
    print("EXAMPLE MATCHED PAIRS")
    print("=" * 80)
    print()

    # Sort by score descending for best examples
    sorted_pairs = sorted(matched_pairs, key=lambda p: p["score"], reverse=True)

    # Show top same-day examples
    same_day_sorted = [p for p in sorted_pairs if p["same_day"]]
    diff_day_sorted = [p for p in sorted_sorted if not p["same_day"]] if False else [p for p in sorted_pairs if not p["same_day"]]

    print("--- TOP SAME-DAY PAIRS (highest match score) ---")
    print()
    for i, pair in enumerate(same_day_sorted[:8]):
        sms = pair["sms"]
        email = pair["email"]
        sms_perf = sms.get("performance_summary", {})
        email_perf = email.get("performance_summary", {})

        print(f"  Pair {i+1} (match score: {pair['score']:.3f})")
        print(f"    SMS:   {sms.get('name', 'N/A')}")
        print(f"    Email: {email.get('name', 'N/A')}")
        print(f"    Date:  {pair['sms_date']}")

        # Get email subject
        email_subjects = [s.get("subject", "") for s in email.get("sends", []) if s.get("subject")]
        if email_subjects:
            print(f"    Email Subject: \"{email_subjects[0]}\"")

        print(f"    SMS Click Rate:   {fmt_pct(sms_perf.get('click_rate', 0))} "
              f"({fmt_num(sms_perf.get('total_clicks', 0))} clicks / {fmt_num(sms_perf.get('total_sends', 0))} sends)")
        print(f"    Email Click Rate: {fmt_pct(email_perf.get('click_rate', 0))} "
              f"({fmt_num(email_perf.get('total_clicks', 0))} clicks / {fmt_num(email_perf.get('total_sends', 0))} sends)")

        # GA4 data
        sms_ga4 = sms_perf.get("ga4", {})
        email_ga4 = email_perf.get("ga4", {})
        if sms_ga4:
            print(f"    SMS GA4:  {sms_ga4.get('sessions', 0)} sessions, "
                  f"${sms_ga4.get('revenue', 0):,.2f} revenue, "
                  f"{sms_ga4.get('purchases', 0)} purchases")
        if email_ga4:
            print(f"    Email GA4: {email_ga4.get('sessions', 0)} sessions, "
                  f"${email_ga4.get('revenue', 0):,.2f} revenue, "
                  f"{email_ga4.get('purchases', 0)} purchases")

        kw_overlap = pair["details"].get("keyword_overlap", set())
        if kw_overlap:
            print(f"    Keyword Overlap: {', '.join(sorted(kw_overlap))}")
        print()

    print("--- TOP DIFFERENT-DAY PAIRS (highest match score) ---")
    print()
    for i, pair in enumerate(diff_day_sorted[:8]):
        sms = pair["sms"]
        email = pair["email"]
        sms_perf = sms.get("performance_summary", {})
        email_perf = email.get("performance_summary", {})

        print(f"  Pair {i+1} (match score: {pair['score']:.3f}, {pair['days_apart']} day(s) apart)")
        print(f"    SMS:   {sms.get('name', 'N/A')}  (sent {pair['sms_date']})")
        print(f"    Email: {email.get('name', 'N/A')}  (sent {pair['email_date']})")

        email_subjects = [s.get("subject", "") for s in email.get("sends", []) if s.get("subject")]
        if email_subjects:
            print(f"    Email Subject: \"{email_subjects[0]}\"")

        print(f"    SMS Click Rate:   {fmt_pct(sms_perf.get('click_rate', 0))} "
              f"({fmt_num(sms_perf.get('total_clicks', 0))} clicks / {fmt_num(sms_perf.get('total_sends', 0))} sends)")
        print(f"    Email Click Rate: {fmt_pct(email_perf.get('click_rate', 0))} "
              f"({fmt_num(email_perf.get('total_clicks', 0))} clicks / {fmt_num(email_perf.get('total_sends', 0))} sends)")

        sms_ga4 = sms_perf.get("ga4", {})
        email_ga4 = email_perf.get("ga4", {})
        if sms_ga4:
            print(f"    SMS GA4:  {sms_ga4.get('sessions', 0)} sessions, "
                  f"${sms_ga4.get('revenue', 0):,.2f} revenue, "
                  f"{sms_ga4.get('purchases', 0)} purchases")
        if email_ga4:
            print(f"    Email GA4: {email_ga4.get('sessions', 0)} sessions, "
                  f"${email_ga4.get('revenue', 0):,.2f} revenue, "
                  f"{email_ga4.get('purchases', 0)} purchases")

        kw_overlap = pair["details"].get("keyword_overlap", set())
        if kw_overlap:
            print(f"    Keyword Overlap: {', '.join(sorted(kw_overlap))}")
        print()

    # ── Unmatched SMS Campaigns ────────────────────────────────────────────
    print("=" * 80)
    print(f"UNMATCHED SMS CAMPAIGNS ({len(unmatched_sms)} total)")
    print("=" * 80)
    print()

    for sms in sorted(unmatched_sms, key=lambda c: parse_send_date(c) or datetime.min.date()):
        perf = sms.get("performance_summary", {})
        d = parse_send_date(sms)
        print(f"  {d} | {sms.get('name', 'N/A')} | "
              f"CR: {fmt_pct(perf.get('click_rate', 0))} | "
              f"Sends: {fmt_num(perf.get('total_sends', 0))}")
    print()

    # ── High-Match-Score Only Analysis ─────────────────────────────────────
    # Repeat the core comparison with only high-confidence matches (score >= 0.45)
    high_conf_pairs = [p for p in matched_pairs if p["score"] >= 0.45]
    high_same = [p for p in high_conf_pairs if p["same_day"]]
    high_diff = [p for p in high_conf_pairs if not p["same_day"]]

    print("=" * 80)
    print(f"SENSITIVITY CHECK: HIGH-CONFIDENCE MATCHES ONLY (score >= 0.45)")
    print(f"  Total: {len(high_conf_pairs)} | Same-day: {len(high_same)} | Diff-day: {len(high_diff)}")
    print("=" * 80)
    print()

    if high_same and high_diff:
        hsd_m = aggregate_sms_metrics(high_same)
        hdd_m = aggregate_sms_metrics(high_diff)

        print(f"  Same-Day   -> Wtd CR: {fmt_pct(hsd_m['weighted_click_rate'])} | "
              f"Avg CR: {fmt_pct(hsd_m['avg_click_rate'])} | "
              f"Sends: {fmt_num(hsd_m['total_sends'])} | "
              f"Campaigns: {hsd_m['count']}")
        print(f"  Diff-Day   -> Wtd CR: {fmt_pct(hdd_m['weighted_click_rate'])} | "
              f"Avg CR: {fmt_pct(hdd_m['avg_click_rate'])} | "
              f"Sends: {fmt_num(hdd_m['total_sends'])} | "
              f"Campaigns: {hdd_m['count']}")
        print(f"  Delta (wtd CR): {delta_str(hsd_m['weighted_click_rate'], hdd_m['weighted_click_rate'])}")
        print(f"  Delta (avg CR): {delta_str(hsd_m['avg_click_rate'], hdd_m['avg_click_rate'])}")
    elif high_same:
        hsd_m = aggregate_sms_metrics(high_same)
        print(f"  Same-Day only -> Wtd CR: {fmt_pct(hsd_m['weighted_click_rate'])} | Campaigns: {hsd_m['count']}")
        print("  No high-confidence different-day pairs for comparison.")
    elif high_diff:
        hdd_m = aggregate_sms_metrics(high_diff)
        print(f"  Diff-Day only -> Wtd CR: {fmt_pct(hdd_m['weighted_click_rate'])} | Campaigns: {hdd_m['count']}")
        print("  No high-confidence same-day pairs for comparison.")
    else:
        print("  Not enough high-confidence matches for comparison.")
    print()

    # ── SMS Sent Before vs. After Email ────────────────────────────────────
    print("=" * 80)
    print("SMS TIMING RELATIVE TO EMAIL (for different-day pairs)")
    print("=" * 80)
    print()

    sms_before_email = [p for p in diff_day_pairs if p["sms_date"] and p["email_date"] and p["sms_date"] < p["email_date"]]
    sms_after_email = [p for p in diff_day_pairs if p["sms_date"] and p["email_date"] and p["sms_date"] > p["email_date"]]

    print(f"  SMS sent BEFORE email: {len(sms_before_email)} pairs")
    print(f"  SMS sent AFTER email:  {len(sms_after_email)} pairs")
    print()

    if sms_before_email:
        before_m = aggregate_sms_metrics(sms_before_email)
        print(f"  Before -> Wtd CR: {fmt_pct(before_m['weighted_click_rate'])} | "
              f"Avg CR: {fmt_pct(before_m['avg_click_rate'])} | "
              f"Campaigns: {before_m['count']}")
    if sms_after_email:
        after_m = aggregate_sms_metrics(sms_after_email)
        print(f"  After  -> Wtd CR: {fmt_pct(after_m['weighted_click_rate'])} | "
              f"Avg CR: {fmt_pct(after_m['avg_click_rate'])} | "
              f"Campaigns: {after_m['count']}")

    if sms_before_email and sms_after_email:
        before_m = aggregate_sms_metrics(sms_before_email)
        after_m = aggregate_sms_metrics(sms_after_email)
        print(f"  Delta (before vs after, wtd CR): {delta_str(before_m['weighted_click_rate'], after_m['weighted_click_rate'])}")
    print()

    # ── Complete Pair Listing ──────────────────────────────────────────────
    print("=" * 80)
    print("ALL MATCHED PAIRS (sorted by SMS send date)")
    print("=" * 80)
    print()

    date_sorted = sorted(matched_pairs, key=lambda p: p["sms_date"] or datetime.min.date())

    list_headers = ["Date", "SMS Name", "Email Name", "Days", "Score", "SMS CR", "Email CR"]
    list_widths = [12, 42, 42, 6, 7, 10, 10]

    print_row(list_headers, list_widths)
    print_row(["-" * w for w in list_widths], list_widths)

    for pair in date_sorted:
        sms = pair["sms"]
        email = pair["email"]
        sms_perf = sms.get("performance_summary", {})
        email_perf = email.get("performance_summary", {})

        sms_name = sms.get("name", "N/A")
        if len(sms_name) > 40:
            sms_name = sms_name[:37] + "..."
        email_name = email.get("name", "N/A")
        if len(email_name) > 40:
            email_name = email_name[:37] + "..."

        day_str = "SAME" if pair["same_day"] else str(pair["days_apart"])

        print_row([
            str(pair["sms_date"]),
            sms_name,
            email_name,
            day_str,
            f"{pair['score']:.2f}",
            fmt_pct(sms_perf.get("click_rate", 0), 2),
            fmt_pct(email_perf.get("click_rate", 0), 2),
        ], list_widths)
    print()

    # ── Summary & Findings ─────────────────────────────────────────────────
    print("=" * 80)
    print("SUMMARY & KEY FINDINGS")
    print("=" * 80)
    print()

    print(f"1. DATA SCOPE:")
    print(f"   - {len(batch_sms)} batch CZ SMS campaigns analyzed (>= {MIN_SENDS} sends)")
    print(f"   - {len(batch_email)} batch CZ email campaigns available for matching")
    print(f"   - {len(matched_pairs)} SMS-email pairs matched ({len(unmatched_sms)} SMS unmatched)")
    print(f"   - {len(same_day_pairs)} same-day pairs, {len(diff_day_pairs)} different-day pairs")
    print()

    print(f"2. SAME-DAY vs. DIFFERENT-DAY SMS PERFORMANCE:")
    if same_day_pairs and diff_day_pairs:
        sd = same_day_metrics
        dd = diff_day_metrics

        cr_delta = delta_str(sd["weighted_click_rate"], dd["weighted_click_rate"])
        avg_delta = delta_str(sd["avg_click_rate"], dd["avg_click_rate"])

        winner = "same-day" if sd["weighted_click_rate"] > dd["weighted_click_rate"] else "different-day"

        print(f"   - Weighted click rate: Same-day {fmt_pct(sd['weighted_click_rate'])} "
              f"vs. Different-day {fmt_pct(dd['weighted_click_rate'])} ({cr_delta})")
        print(f"   - Average click rate:  Same-day {fmt_pct(sd['avg_click_rate'])} "
              f"vs. Different-day {fmt_pct(dd['avg_click_rate'])} ({avg_delta})")
        print(f"   - SMS campaigns perform better on a {winner} basis (by weighted CR)")
    else:
        print("   - Not enough data for both groups to compare.")
    print()

    print(f"3. DAYS-APART PATTERN:")
    for bucket in bucket_order:
        pairs = days_buckets.get(bucket, [])
        if pairs:
            m = aggregate_sms_metrics(pairs)
            print(f"   - {bucket}: {fmt_pct(m['weighted_click_rate'])} weighted CR ({m['count']} campaigns)")
    print()

    if sms_before_email and sms_after_email:
        before_m = aggregate_sms_metrics(sms_before_email)
        after_m = aggregate_sms_metrics(sms_after_email)
        print(f"4. SMS TIMING:")
        print(f"   - SMS sent BEFORE email: {fmt_pct(before_m['weighted_click_rate'])} CR ({len(sms_before_email)} campaigns)")
        print(f"   - SMS sent AFTER email:  {fmt_pct(after_m['weighted_click_rate'])} CR ({len(sms_after_email)} campaigns)")
        timing_winner = "before" if before_m["weighted_click_rate"] > after_m["weighted_click_rate"] else "after"
        print(f"   - SMS performs better when sent {timing_winner} the correlated email")
        print()

    print(f"5. METHODOLOGY NOTES:")
    print(f"   - Matching uses keyword extraction from campaign names (Jaccard similarity),")
    print(f"     subject line overlap, category matching, sale period matching, and temporal")
    print(f"     proximity within a {MAX_DAYS_APART}-day window. Minimum match score: {MIN_MATCH_SCORE}.")
    print(f"   - Click rate = unique clicks / total sends (not total clicks).")
    print(f"   - Canvas/triggered campaigns excluded (only batch sends analyzed).")
    print(f"   - Minimum {MIN_SENDS} sends per campaign to filter out test sends.")
    print(f"   - SMS campaigns may match to the closest email about the same topic,")
    print(f"     but the exact pairing depends on naming conventions.")
    print()


if __name__ == "__main__":
    main()
