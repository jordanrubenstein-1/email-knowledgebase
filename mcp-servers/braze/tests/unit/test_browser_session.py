"""Tests for browser session management - TDD: write tests first."""

import pytest


class TestSessionManager:
    """Test browser session singleton management."""

    def test_session_singleton(self):
        """Should return same session instance."""
        from braze_mcp.browser.session import SessionManager

        manager1 = SessionManager.get_instance()
        manager2 = SessionManager.get_instance()
        assert manager1 is manager2

    def test_session_initially_not_logged_in(self):
        """Session should start not logged in."""
        from braze_mcp.browser.session import SessionManager

        manager = SessionManager.get_instance()
        assert not manager.is_logged_in

    def test_session_initially_no_browser(self):
        """Session should start without browser."""
        from braze_mcp.browser.session import SessionManager

        manager = SessionManager.get_instance()
        assert manager.browser is None
        assert manager.page is None


class TestTotpGeneration:
    """Test TOTP code generation."""

    def test_generate_totp(self):
        """Should generate valid 6-digit TOTP."""
        from braze_mcp.browser.login import generate_totp

        # Standard test secret
        code = generate_totp("JBSWY3DPEHPK3PXP")
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_totp_invalid_secret(self):
        """Should raise for invalid secret."""
        from braze_mcp.browser.login import generate_totp

        with pytest.raises(Exception):
            generate_totp("not-valid-base32!")


class TestWorkspaceMapping:
    """Test workspace name resolution."""

    def test_get_workspace_name(self):
        """Should resolve brand to workspace name."""
        from braze_mcp.browser.workspace import get_workspace_name

        assert get_workspace_name("HAV") == "havenly"
        assert get_workspace_name("BUR") == "Burrow - Production"

    def test_get_workspace_name_case_insensitive(self):
        """Brand codes should be case-insensitive."""
        from braze_mcp.browser.workspace import get_workspace_name

        assert get_workspace_name("hav") == "havenly"
        assert get_workspace_name("Hav") == "havenly"

    def test_get_workspace_name_invalid(self):
        """Should raise for invalid brand."""
        from braze_mcp.browser.workspace import get_workspace_name
        from braze_mcp.config import BrazeConfigError

        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            get_workspace_name("INVALID")
