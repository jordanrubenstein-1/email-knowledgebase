"""
Braze Dashboard Automation via Playwright.

This module provides tools to automate Braze dashboard operations,
starting with campaign creation as a POC.
"""

from .login import (
    login,
    ensure_logged_in,
    handle_mfa,
    select_workspace,
    get_current_workspace,
    BRAND_WORKSPACE_MAP,
)
from .create_campaign import create_draft_campaign
from .element_utils import fill_field, click_button, wait_for_element

__all__ = [
    "login",
    "ensure_logged_in",
    "handle_mfa",
    "select_workspace",
    "get_current_workspace",
    "BRAND_WORKSPACE_MAP",
    "create_draft_campaign",
    "fill_field",
    "click_button",
    "wait_for_element",
]
