"""Configuration management for Braze MCP server.

Handles:
- Multi-brand API key/URL resolution
- Dashboard (Playwright) credentials
- Brand code validation and mapping
"""

from __future__ import annotations

import os
from typing import TypedDict


class BrazeConfigError(Exception):
    """Raised when configuration is invalid or missing."""

    pass


# Brand code to Braze workspace name mapping
BRAND_WORKSPACE_MAP: dict[str, str] = {
    "HAV": "havenly",
    "BUR": "Burrow - Production",
    "ID": "Interior Define",
    "STF": "St Frank",
    "CZ": "The Citizenry",
    "TI": "The Inside",
}

# Valid brand codes
VALID_BRANDS = set(BRAND_WORKSPACE_MAP.keys())

# Brand name aliases -> brand code
BRAND_ALIASES: dict[str, str] = {
    # Havenly
    "HAVENLY": "HAV",
    # Burrow
    "BURROW": "BUR",
    # Interior Define
    "INTERIOR DEFINE": "ID",
    "INTERIORDEFINE": "ID",
    # St. Frank
    "ST FRANK": "STF",
    "ST. FRANK": "STF",
    "STFRANK": "STF",
    # The Citizenry
    "THE CITIZENRY": "CZ",
    "CITIZENRY": "CZ",
    "THECITIZENRY": "CZ",
    # The Inside
    "THE INSIDE": "TI",
    "THEINSIDE": "TI",
    "INSIDE": "TI",
}

# Default Braze REST API base URL
DEFAULT_BASE_URL = "https://rest.iad-07.braze.com"


class DashboardConfig(TypedDict):
    """Dashboard configuration for Playwright automation."""

    url: str
    email: str
    password: str
    totp_secret: str | None
    login_method: str  # "password" or "google"


def normalize_brand(brand: str) -> str:
    """Normalize brand input to brand code.

    Accepts brand codes (HAV, BUR, etc.) or full names (Havenly, Burrow, etc.)

    Args:
        brand: Brand code or name (case-insensitive)

    Returns:
        Normalized uppercase brand code

    Raises:
        BrazeConfigError: If brand is unknown
    """
    normalized = brand.upper().strip()

    # Check if it's already a valid brand code
    if normalized in VALID_BRANDS:
        return normalized

    # Check aliases
    if normalized in BRAND_ALIASES:
        return BRAND_ALIASES[normalized]

    # Build helpful error message
    valid_options = sorted(VALID_BRANDS) + ["Havenly", "Burrow", "Interior Define", "St Frank", "The Citizenry", "The Inside"]
    raise BrazeConfigError(
        f"Unknown brand: {brand}. Valid options: {', '.join(sorted(VALID_BRANDS))} "
        f"(or full names like Havenly, Burrow, etc.)"
    )


def validate_brand(brand: str) -> str:
    """Validate and normalize a brand code.

    Args:
        brand: Brand code or name (case-insensitive)

    Returns:
        Normalized uppercase brand code

    Raises:
        BrazeConfigError: If brand code is unknown
    """
    return normalize_brand(brand)


def get_api_key(brand: str) -> str:
    """Get the API key for a brand.

    Looks for BRAZE_API_KEY_{BRAND} first, falls back to BRAZE_API_KEY.

    Args:
        brand: Brand code (case-insensitive)

    Returns:
        API key string

    Raises:
        BrazeConfigError: If no API key found
    """
    normalized = validate_brand(brand)

    # Try brand-specific key first
    key = os.environ.get(f"BRAZE_API_KEY_{normalized}")
    if key:
        return key

    # Fall back to generic key
    key = os.environ.get("BRAZE_API_KEY")
    if key:
        return key

    raise BrazeConfigError(
        f"No API key found for brand {normalized}. "
        f"Set BRAZE_API_KEY_{normalized} or BRAZE_API_KEY environment variable."
    )


def get_base_url(brand: str) -> str:
    """Get the base URL for a brand.

    Looks for BRAZE_BASE_URL_{BRAND} first, falls back to BRAZE_BASE_URL,
    then to DEFAULT_BASE_URL.

    Args:
        brand: Brand code (case-insensitive)

    Returns:
        Base URL string
    """
    normalized = validate_brand(brand)

    # Try brand-specific URL first
    url = os.environ.get(f"BRAZE_BASE_URL_{normalized}")
    if url:
        return url

    # Fall back to generic URL
    url = os.environ.get("BRAZE_BASE_URL")
    if url:
        return url

    # Use default
    return DEFAULT_BASE_URL


def get_dashboard_config() -> DashboardConfig:
    """Get dashboard configuration for Playwright automation.

    Supports two login methods:
    - "password" (default): Uses email/password + optional TOTP
    - "google": Manual Google SSO login (user completes OAuth flow)

    Set BRAZE_LOGIN_METHOD=google to use Google SSO.

    Returns:
        DashboardConfig with URL, email, password, and optional TOTP secret

    Raises:
        BrazeConfigError: If required config is missing
    """
    url = os.environ.get("BRAZE_DASHBOARD_URL")
    login_method = os.environ.get("BRAZE_LOGIN_METHOD", "password").lower()
    email = os.environ.get("BRAZE_DASHBOARD_EMAIL")
    password = os.environ.get("BRAZE_DASHBOARD_PASSWORD")
    totp_secret = os.environ.get("BRAZE_TOTP_SECRET")

    missing = []
    if not url:
        missing.append("BRAZE_DASHBOARD_URL")
    
    # Only require email/password for password login method
    if login_method == "password":
        if not email:
            missing.append("BRAZE_DASHBOARD_EMAIL")
        if not password:
            missing.append("BRAZE_DASHBOARD_PASSWORD")

    if missing:
        raise BrazeConfigError(
            f"Missing dashboard config: {', '.join(missing)}. "
            "These are required for Playwright automation. "
            "For Google SSO login, set BRAZE_LOGIN_METHOD=google"
        )

    return DashboardConfig(
        url=url,
        email=email or "",
        password=password or "",
        totp_secret=totp_secret,
        login_method=login_method,
    )
