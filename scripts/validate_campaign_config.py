#!/usr/bin/env python3
"""
Validation logic for campaign configuration.

Validates campaign config YAML files before creating campaigns in Braze.
"""

import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urlparse
import pytz

sys.path.insert(0, str(Path(__file__).parent))
from import_braze import normalize_brand

# Try to import revenue recommender (optional - won't fail if not available)
try:
    from plain_text_revenue_recommender import get_revenue_recommendations
    HAS_REVENUE_RECOMMENDER = True
except ImportError:
    HAS_REVENUE_RECOMMENDER = False

# Valid brand codes
VALID_BRANDS = {"HAV", "CZ", "ID", "BUR", "STF", "TI"}

# Valid categories
VALID_CATEGORIES = {"reminder", "sale_promo", "editorial", "product_launch", "other"}

# Valid campaign types
VALID_TYPES = {"sale", "seasonal", "product_launch", "lifecycle", "announcement"}

# Valid audience types
VALID_AUDIENCE_TYPES = {"segment", "connected_audience", "user_list"}

# Valid subscription groups
VALID_SUBSCRIPTION_GROUPS = {"Marketing", "Transactional"}

# Brand domain mapping
BRAND_DOMAINS = {
    "HAV": ["havenly.com"],
    "CZ": ["the-citizenry.com"],
    "ID": ["interiordefine.com"],
    "BUR": ["burrow.com"],
    "STF": ["stfrank.com"],
    "TI": ["theinside.com"],
}


class ValidationError(Exception):
    """Raised when campaign configuration validation fails."""
    pass


def validate_brand(brand: str) -> Tuple[bool, Optional[str]]:
    """Validate brand code.
    
    Returns:
        (is_valid, error_message)
    """
    if not brand:
        return False, "Brand is required"
    
    normalized = normalize_brand(brand)
    if normalized not in VALID_BRANDS:
        return False, f"Invalid brand '{brand}'. Must be one of: {', '.join(VALID_BRANDS)}"
    
    return True, None


def validate_category(category: str) -> Tuple[bool, Optional[str]]:
    """Validate category.
    
    Returns:
        (is_valid, error_message)
    """
    if not category:
        return False, "Category is required"
    
    if category not in VALID_CATEGORIES:
        return False, f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}"
    
    return True, None


def validate_type(campaign_type: str) -> Tuple[bool, Optional[str]]:
    """Validate campaign type.
    
    Returns:
        (is_valid, error_message)
    """
    if not campaign_type:
        return False, "Campaign type is required"
    
    if campaign_type not in VALID_TYPES:
        return False, f"Invalid type '{campaign_type}'. Must be one of: {', '.join(VALID_TYPES)}"
    
    return True, None


def validate_send_schedule(send_config: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[datetime]]:
    """Validate send date and time.
    
    Returns:
        (is_valid, error_message, parsed_datetime)
    """
    if not send_config:
        return False, "Send schedule is required", None
    
    date_str = send_config.get("date")
    time_str = send_config.get("time")
    timezone_str = send_config.get("timezone", "UTC")
    
    if not date_str:
        return False, "Send date is required", None
    
    if not time_str:
        return False, "Send time is required", None
    
    # Validate timezone
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return False, f"Invalid timezone '{timezone_str}'. Must be a valid IANA timezone.", None
    
    # Parse date
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, f"Invalid date format '{date_str}'. Must be YYYY-MM-DD.", None
    
    # Parse time
    try:
        time_obj = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return False, f"Invalid time format '{time_str}'. Must be HH:MM in 24-hour format.", None
    
    # Combine date and time
    try:
        dt = datetime.combine(date_obj, time_obj)
        # Localize to timezone
        if timezone_str != "UTC":
            dt = tz.localize(dt)
        else:
            dt = pytz.UTC.localize(dt)
    except Exception as e:
        return False, f"Error combining date and time: {e}", None
    
    # Check if send time is in the future
    now = datetime.now(pytz.UTC)
    if dt <= now:
        return False, f"Send datetime must be in the future. Provided: {dt.isoformat()}, Current: {now.isoformat()}", None
    
    return True, None, dt


def validate_personalization_greeting(body: str) -> Tuple[bool, Optional[str]]:
    """Validate that email body starts with personalized greeting.
    
    Returns:
        (is_valid, error_message)
    """
    if not body:
        return False, "Email body is required"
    
    # Check for common greeting patterns with first_name personalization
    # Patterns: "Hi {{${first_name}}", "Hi {{${first_name} | default: 'there'}}", etc.
    greeting_patterns = [
        r'^Hi\s+\{\{\s*\$\{first_name\}',
        r'^Hi\s+\{\{\s*api_trigger_properties\.\$\{first_name\}',
        r'^Hi\s+\{\{\s*.*first_name.*\}\}',
    ]
    
    body_start = body.strip()[:50]  # Check first 50 characters
    for pattern in greeting_patterns:
        if re.search(pattern, body_start, re.IGNORECASE):
            return True, None
    
    return False, "Email body must start with a personalized greeting like 'Hi {{${first_name} | default: 'there'}}'"


def validate_cta_domains(cta_links: List[Dict[str, Any]], brand: str) -> Tuple[bool, Optional[str]]:
    """Validate that all CTA URLs are on the brand's domain.
    
    Returns:
        (is_valid, error_message)
    """
    if not cta_links:
        return False, "At least one CTA link is required"
    
    normalized_brand = normalize_brand(brand)
    if normalized_brand not in BRAND_DOMAINS:
        return False, f"Unknown brand '{brand}' for domain validation"
    
    allowed_domains = BRAND_DOMAINS[normalized_brand]
    
    for i, cta in enumerate(cta_links, 1):
        url = cta.get("url", "").strip()
        if not url:
            continue
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix for comparison
            if domain.startswith("www."):
                domain = domain[4:]
            
            # Check if domain matches any allowed domain
            domain_match = False
            for allowed_domain in allowed_domains:
                if domain == allowed_domain.lower() or domain.endswith("." + allowed_domain.lower()):
                    domain_match = True
                    break
            
            if not domain_match:
                return False, f"CTA link {i} URL must be on brand domain ({', '.join(allowed_domains)}). Found: {domain}"
        except Exception as e:
            return False, f"CTA link {i} has invalid URL format: {e}"
    
    return True, None


def validate_body_structure(body: str) -> Tuple[bool, Optional[str]]:
    """Validate body has minimum paragraphs and content length.
    
    Returns:
        (is_valid, error_message)
    """
    if not body:
        return False, "Email body is required"
    
    # Check minimum length
    if len(body.strip()) < 100:
        return False, "Email body must be at least 100 characters"
    
    # Count paragraphs - split by double newlines or <br><br> or <br/> tags
    # Remove HTML tags for counting, but preserve structure
    body_for_parsing = body
    
    # Count paragraph breaks (double newlines, <br><br>, <br/><br/>, etc.)
    paragraph_breaks = len(re.findall(r'\n\s*\n|<br\s*/?>\s*<br\s*/?>', body_for_parsing, re.IGNORECASE))
    
    # Also check for single newlines that might indicate paragraphs
    # Split by newlines and filter out empty/whitespace-only lines
    lines = [line.strip() for line in body_for_parsing.split('\n') if line.strip()]
    
    # If we have at least 2 non-empty lines separated by breaks, consider it 2+ paragraphs
    # Or if we have paragraph breaks, count them + 1
    if paragraph_breaks > 0:
        paragraph_count = paragraph_breaks + 1
    elif len(lines) >= 2:
        # Check if there's meaningful separation (blank lines or HTML breaks)
        has_separation = bool(re.search(r'\n\s*\n|<br\s*/?>', body_for_parsing, re.IGNORECASE))
        paragraph_count = 2 if has_separation else 1
    else:
        paragraph_count = 1
    
    if paragraph_count < 2:
        return False, "Email body must have at least 2 paragraphs (separated by blank lines or <br> tags)"
    
    return True, None


def validate_subject_line_quality(subject: str, brand: str) -> List[str]:
    """Validate subject line quality and return warnings.
    
    Returns:
        List of warning messages (empty if no warnings)
    """
    warnings = []
    
    if not subject:
        return warnings
    
    normalized_brand = normalize_brand(brand)
    
    # Check for ALL CAPS words (except BUR where it works)
    if normalized_brand != "BUR":
        if re.search(r'\b[A-Z]{3,}\b', subject):
            warnings.append("Subject contains ALL CAPS words (correlates with -4.4pt open rate). Consider using sentence case.")
    
    # Check for percent signs
    if '%' in subject or re.search(r'\d+%', subject):
        warnings.append("Subject contains percent signs (correlates with -3.4pt open rate). Consider describing the benefit instead.")
    
    # Check for question marks
    if '?' in subject:
        warnings.append("Subject contains question marks (correlates with -2.7pt open rate). Consider a statement instead.")
    
    # Check for "You/Your" (positive signal)
    if not re.search(r'\b(you|your)\b', subject, re.IGNORECASE):
        if normalized_brand == "CZ":
            warnings.append("Consider using 'You/Your' in subject (correlates with +6.8pt open rate for CZ)")
        elif normalized_brand in ["HAV", "BUR"]:
            warnings.append("Consider using 'You/Your' in subject (correlates with +2.2pt open rate)")
    
    # Check subject length
    if len(subject) < 10:
        warnings.append("Subject line is very short (less than 10 characters). Consider adding more context.")
    elif len(subject) > 100:
        warnings.append("Subject line is very long (over 100 characters). May be truncated in some email clients.")
    
    # Brand-specific checks
    if normalized_brand == "STF":
        # STF can use emojis (positive signal)
        pass  # No warning needed
    elif normalized_brand == "ID":
        # ID should avoid emojis
        if re.search(r'[😀-🙏🌀-🗿]', subject):
            warnings.append("ID emails with emojis in subject correlate with -6.1pt open rate. Consider removing emojis.")
    
    return warnings


def validate_preheader(preheader: str) -> Tuple[bool, Optional[str], List[str]]:
    """Validate preheader exists and is optimal length.
    
    Returns:
        (is_valid, error_message, warnings)
    """
    warnings = []
    
    if not preheader or not preheader.strip():
        return False, "Preheader is required (correlates with +8.7pt open rate vs no preheader)", warnings
    
    preheader_len = len(preheader.strip())
    
    # Check optimal length
    if preheader_len < 60:
        warnings.append(f"Preheader is {preheader_len} characters. Optimal length is 60-90 characters (47.6% open rate).")
    elif preheader_len > 90:
        warnings.append(f"Preheader is {preheader_len} characters. Optimal length is 60-90 characters (47.6% open rate).")
    
    return True, None, warnings


def validate_no_repetition(subject: str, preheader: str, body: str) -> List[str]:
    """Detect repetition between subject, preheader, and body.
    
    Returns:
        List of warning messages (empty if no warnings)
    """
    warnings = []
    
    if not subject or not preheader or not body:
        return warnings
    
    # Normalize text for comparison (lowercase, remove punctuation)
    def normalize_text(text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = ' '.join(text.split())
        return text
    
    subject_norm = normalize_text(subject)
    preheader_norm = normalize_text(preheader)
    body_norm = normalize_text(body)
    
    # Check subject-preheader overlap
    if subject_norm and preheader_norm:
        subject_words = set(subject_norm.split())
        preheader_words = set(preheader_norm.split())
        
        if subject_words and preheader_words:
            overlap = subject_words & preheader_words
            overlap_ratio = len(overlap) / len(subject_words | preheader_words)
            
            if overlap_ratio > 0.5:
                warnings.append("Subject and preheader have significant word overlap (>50%). Preheader should add new information, not repeat subject (complementary: 45.9% open vs reinforcing: 43.5% open).")
    
    # Check if subject is repeated verbatim in body
    if subject_norm and body_norm:
        # Check for exact phrase match (subject appears as-is in body)
        if subject_norm in body_norm:
            warnings.append("Subject line appears to be repeated verbatim in body copy. Consider varying the language.")
        else:
            # Check for significant word overlap
            subject_words = set(subject_norm.split())
            body_words = set(body_norm.split())
            
            if subject_words and body_words:
                overlap = subject_words & body_words
                overlap_ratio = len(overlap) / len(subject_words)
                
                if overlap_ratio > 0.7:
                    warnings.append("Subject line has significant word overlap with body copy (>70%). Consider varying the language.")
    
    # Check if preheader is repeated verbatim in body
    if preheader_norm and body_norm:
        if preheader_norm in body_norm:
            warnings.append("Preheader appears to be repeated verbatim in body copy. Consider varying the language.")
    
    return warnings


def validate_link_count(cta_links: List[Dict[str, Any]]) -> List[str]:
    """Warn if more than 2 links (performance optimization).
    
    Returns:
        List of warning messages (empty if no warnings)
    """
    warnings = []
    
    if not cta_links:
        return warnings
    
    link_count = len(cta_links)
    
    if link_count > 2:
        warnings.append(f"Email has {link_count} CTA links. Campaigns with 0-2 links perform 92% better than 2-5 links (1.81% vs 0.94% click rate). Consider reducing to 2 or fewer links.")
    
    return warnings


def validate_email_content(
    email_config: Dict[str, Any], 
    brand: str,
    campaign_category: str = "other",
    include_revenue_recommendations: bool = True
) -> Tuple[bool, Optional[str], List[str]]:
    """Validate email subject, body, and CTA links with guardrails.
    
    Args:
        email_config: Email configuration dictionary
        brand: Brand code
        campaign_category: Campaign category (for revenue recommendations)
        include_revenue_recommendations: Whether to include revenue-focused recommendations
    
    Returns:
        (is_valid, error_message, warnings)
    """
    warnings = []
    
    if not email_config:
        return False, "Email configuration is required", warnings
    
    subject = email_config.get("subject", "").strip()
    if not subject:
        return False, "Email subject is required and cannot be empty", warnings
    
    body = email_config.get("body", "").strip()
    if not body:
        return False, "Email body is required and cannot be empty", warnings
    
    preheader = email_config.get("preheader", "").strip()
    
    cta_links = email_config.get("cta_links", [])
    if not cta_links or len(cta_links) == 0:
        return False, "At least one CTA link is required", warnings
    
    # Validate each CTA link structure
    for i, cta in enumerate(cta_links, 1):
        if not isinstance(cta, dict):
            return False, f"CTA link {i} must be a dictionary", warnings
        
        text = cta.get("text", "").strip()
        url = cta.get("url", "").strip()
        
        if not text:
            return False, f"CTA link {i} is missing 'text' field", warnings
        
        if not url:
            return False, f"CTA link {i} is missing 'url' field", warnings
        
        # Basic URL validation
        if not (url.startswith("http://") or url.startswith("https://")):
            return False, f"CTA link {i} URL must start with http:// or https://", warnings
    
    # Guardrail validations (hard requirements)
    is_valid, error = validate_personalization_greeting(body)
    if not is_valid:
        return False, error, warnings
    
    is_valid, error = validate_cta_domains(cta_links, brand)
    if not is_valid:
        return False, error, warnings
    
    is_valid, error = validate_body_structure(body)
    if not is_valid:
        return False, error, warnings
    
    # Preheader validation (required)
    is_valid, error, preheader_warnings = validate_preheader(preheader)
    if not is_valid:
        return False, error, warnings
    warnings.extend(preheader_warnings)
    
    # Warning-only validations
    warnings.extend(validate_subject_line_quality(subject, brand))
    warnings.extend(validate_no_repetition(subject, preheader, body))
    warnings.extend(validate_link_count(cta_links))
    
    # Revenue-focused recommendations (if available and enabled)
    if include_revenue_recommendations and HAS_REVENUE_RECOMMENDER:
        try:
            revenue_recs = get_revenue_recommendations(
                brand=brand,
                subject=subject,
                preheader=preheader,
                body=body,
                category=campaign_category
            )
            # Add revenue recommendations as info-level warnings
            for severity, message in revenue_recs:
                if severity in ["warning", "error"]:
                    warnings.append(f"[Revenue] {message}")
                else:
                    # Info-level recommendations are less critical
                    warnings.append(f"[Revenue Optimization] {message}")
        except Exception:
            # Don't fail validation if revenue recommender has issues
            pass
    
    return True, None, warnings


def validate_audience(audience_config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate audience configuration.
    
    Returns:
        (is_valid, error_message)
    """
    if not audience_config:
        return False, "Audience configuration is required"
    
    audience_type = audience_config.get("type")
    if not audience_type:
        return False, "Audience type is required"
    
    if audience_type not in VALID_AUDIENCE_TYPES:
        return False, f"Invalid audience type '{audience_type}'. Must be one of: {', '.join(VALID_AUDIENCE_TYPES)}"
    
    if audience_type == "segment":
        segment_id = audience_config.get("id")
        if not segment_id:
            return False, "Segment ID is required when audience type is 'segment'"
    
    elif audience_type == "connected_audience":
        audience_id = audience_config.get("connected_audience_id")
        if not audience_id:
            return False, "Connected audience ID is required when audience type is 'connected_audience'"
    
    elif audience_type == "user_list":
        user_ids = audience_config.get("external_user_ids", [])
        if not user_ids or len(user_ids) == 0:
            return False, "External user IDs list is required when audience type is 'user_list'"
        if not isinstance(user_ids, list):
            return False, "External user IDs must be a list"
    
    return True, None


def validate_settings(settings: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate campaign settings.
    
    Returns:
        (is_valid, error_message)
    """
    if not settings:
        return False, "Settings are required"
    
    subscription_group = settings.get("subscription_group")
    if not subscription_group:
        return False, "Subscription group is required in settings"
    
    if subscription_group not in VALID_SUBSCRIPTION_GROUPS:
        return False, f"Invalid subscription group '{subscription_group}'. Must be one of: {', '.join(VALID_SUBSCRIPTION_GROUPS)}"
    
    # Validate frequency capping if present
    freq_cap = settings.get("frequency_capping")
    if freq_cap:
        if not isinstance(freq_cap, dict):
            return False, "Frequency capping must be a dictionary"
        
        if freq_cap.get("enabled", False):
            max_sends = freq_cap.get("max_sends")
            period_days = freq_cap.get("period_days")
            
            if max_sends is not None and (not isinstance(max_sends, int) or max_sends < 1):
                return False, "Frequency capping max_sends must be a positive integer"
            
            if period_days is not None and (not isinstance(period_days, int) or period_days < 1):
                return False, "Frequency capping period_days must be a positive integer"
    
    return True, None


def validate_campaign_config(
    config: Dict[str, Any],
    include_revenue_recommendations: bool = True,
    html_content: Optional[str] = None,
) -> Tuple[bool, List[str], Optional[datetime], List[str]]:
    """Validate complete campaign configuration.
    
    Args:
        config: Campaign configuration dictionary
        include_revenue_recommendations: Whether to include revenue-focused recommendations
        html_content: Optional HTML body to run HTML-level QA checks
            (image alt tags, unsubscribe link, domain validation, etc.)
    
    Returns:
        (is_valid, error_messages, parsed_send_datetime, warnings)
    """
    errors = []
    warnings = []
    
    if "campaign" not in config:
        return False, ["Root 'campaign' key is required"], None, warnings
    
    campaign = config["campaign"]
    
    # Validate required top-level fields
    name = campaign.get("name", "").strip()
    if not name:
        errors.append("Campaign name is required")
    
    # Validate brand
    is_valid, error = validate_brand(campaign.get("brand"))
    if not is_valid:
        errors.append(error)
    
    brand = campaign.get("brand", "")
    
    # Validate category
    is_valid, error = validate_category(campaign.get("category"))
    if not is_valid:
        errors.append(error)
    
    # Validate type
    is_valid, error = validate_type(campaign.get("type"))
    if not is_valid:
        errors.append(error)
    
    # Validate send schedule
    send_config = campaign.get("send", {})
    is_valid, error, send_datetime = validate_send_schedule(send_config)
    if not is_valid:
        errors.append(error)
    
    # Validate email content (now returns warnings too)
    email_config = campaign.get("email", {})
    is_valid, error, email_warnings = validate_email_content(
        email_config, 
        brand,
        campaign_category=campaign.get("category", "other"),
        include_revenue_recommendations=include_revenue_recommendations
    )
    if not is_valid:
        errors.append(error)
    warnings.extend(email_warnings)
    
    # Validate audience
    audience_config = campaign.get("audience", {})
    is_valid, error = validate_audience(audience_config)
    if not is_valid:
        errors.append(error)
    
    # Validate settings
    settings = campaign.get("settings", {})
    is_valid, error = validate_settings(settings)
    if not is_valid:
        errors.append(error)
    
    # Optional HTML-level validation
    if html_content:
        try:
            from validate_html import validate_html as _validate_html

            subscription_group = settings.get("subscription_group", "Marketing")
            html_errors, html_warnings = _validate_html(
                html_content=html_content,
                brand=brand,
                channel="email",
                subscription_group=subscription_group,
            )
            errors.extend(html_errors)
            warnings.extend(html_warnings)
        except ImportError:
            warnings.append(
                "validate_html module not available — skipping HTML checks."
            )

    is_valid = len(errors) == 0
    return is_valid, errors, send_datetime, warnings
