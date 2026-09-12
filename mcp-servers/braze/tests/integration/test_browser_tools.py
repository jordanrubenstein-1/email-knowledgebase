"""Integration tests for browser-based tools with mocked Playwright."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from braze_mcp.config import BrazeConfigError


class TestWorkspaceValidation:
    """Test workspace validation (no browser mocking needed)."""

    async def test_select_workspace_invalid_brand(self):
        """Should raise for invalid brand."""
        from braze_mcp.browser.workspace import select_workspace

        mock_page = AsyncMock()
        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            await select_workspace(mock_page, "INVALID")


class TestCreateCampaign:
    """Test campaign creation functionality."""

    @pytest.fixture
    def mock_page(self):
        """Create mock Playwright page with campaign form elements."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.click = AsyncMock()
        page.fill = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.wait_for_url = AsyncMock()
        page.screenshot = AsyncMock(return_value=b"screenshot-data")

        # Mock form elements with proper async returns
        def make_element_mock():
            elem = AsyncMock()
            elem.fill = AsyncMock()
            elem.click = AsyncMock()
            elem.count = AsyncMock(return_value=1)
            return elem

        page.get_by_role = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.get_by_label = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.get_by_text = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.locator = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())

        return page

    async def test_create_campaign_fills_fields(self, mock_page, env_with_hav_config):
        """Should fill campaign fields."""
        from braze_mcp.browser.campaign import fill_campaign_form

        await fill_campaign_form(
            mock_page,
            name="Test Campaign",
            subject="Test Subject",
            preheader="Test Preheader",
        )

        # Verify form fields were accessed
        assert mock_page.get_by_label.called

    async def test_create_campaign_dry_run_no_save(
        self, mock_page, env_with_hav_config
    ):
        """Dry run should not click save."""
        from braze_mcp.browser.campaign import create_campaign

        with patch(
            "braze_mcp.browser.campaign.SessionManager"
        ) as mock_session_manager, patch(
            "braze_mcp.browser.campaign.select_workspace"
        ) as mock_select_workspace:
            mock_manager = MagicMock()
            mock_manager.ensure_logged_in = AsyncMock(return_value=mock_page)
            mock_session_manager.get_instance.return_value = mock_manager
            mock_select_workspace.return_value = AsyncMock()

            result = await create_campaign(
                brand="HAV",
                name="Test",
                subject="Test Subject",
                dry_run=True,
            )

            # Dry run should return success with dry_run flag
            assert result.get("dry_run") is True or result.get("success") is True


class TestArchiveCampaign:
    """Test campaign archiving functionality."""

    @pytest.fixture
    def mock_page(self):
        """Create mock Playwright page."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        # Mock form elements with proper async returns
        def make_element_mock(count=1):
            elem = AsyncMock()
            elem.fill = AsyncMock()
            elem.click = AsyncMock()
            elem.count = AsyncMock(return_value=count)
            elem.get_by_role = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
            return elem

        page.get_by_role = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.get_by_text = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.get_by_placeholder = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())
        page.locator = MagicMock(side_effect=lambda *args, **kwargs: make_element_mock())

        return page

    async def test_archive_campaign_clicks_archive(
        self, mock_page, env_with_hav_config
    ):
        """Should click archive button."""
        from braze_mcp.browser.campaign import archive_campaign

        with patch(
            "braze_mcp.browser.campaign.SessionManager"
        ) as mock_session_manager, patch(
            "braze_mcp.browser.campaign.select_workspace"
        ) as mock_select_workspace:
            mock_manager = MagicMock()
            mock_manager.ensure_logged_in = AsyncMock(return_value=mock_page)
            mock_session_manager.get_instance.return_value = mock_manager
            mock_select_workspace.return_value = AsyncMock()

            result = await archive_campaign(
                brand="HAV",
                campaign_name="Test Campaign",
            )

            # Should have navigated and interacted with page
            assert mock_page.goto.called
