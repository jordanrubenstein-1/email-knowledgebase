"""Browser automation for Braze dashboard."""

from .campaign import (
    archive_campaign,
    close_session,
    create_campaign,
    fill_campaign_form,
    render_html,
)
from .login import generate_totp, handle_mfa, login, perform_login
from .session import SessionManager
from .workspace import get_current_workspace, get_workspace_name, select_workspace

__all__ = [
    # Session
    "SessionManager",
    # Login
    "generate_totp",
    "handle_mfa",
    "login",
    "perform_login",
    # Workspace
    "get_current_workspace",
    "get_workspace_name",
    "select_workspace",
    # Campaign
    "archive_campaign",
    "close_session",
    "create_campaign",
    "fill_campaign_form",
    "render_html",
]
