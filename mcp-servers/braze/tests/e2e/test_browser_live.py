"""End-to-end tests for browser automation against live Braze dashboard.

These tests require valid credentials in environment variables.
Run with: uv run pytest tests/e2e -v -m e2e

Uses SessionManager to maintain a persistent browser session.
Tests run sequentially in a single test to avoid multiple logins.
"""

import os

import pytest
import pytest_asyncio

from braze_mcp.browser.session import SessionManager

# Skip all tests if credentials not available
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.getenv("BRAZE_DASHBOARD_EMAIL"),
        reason="BRAZE_DASHBOARD_EMAIL not set",
    ),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def session():
    """Get the SessionManager instance, cleaned up after all tests."""
    manager = SessionManager.get_instance()
    yield manager
    await manager.close()
    SessionManager.reset_instance()


class TestBrazeWorkflow:
    """Sequential test of core Braze browser automation workflow."""

    async def test_full_workflow(self, session):
        """Test login -> workspace selection -> campaign navigation.

        This runs as a single test to avoid multiple logins and MFA prompts.
        Each step validates before proceeding to the next.
        """
        # ========== STEP 1: Login ==========
        page = await session.ensure_logged_in()

        # Validate login worked
        assert session.is_logged_in, "SessionManager should report logged in"
        assert "/sign_in" not in page.url, f"Should not be on sign_in page, got {page.url}"
        assert "/auth" not in page.url, f"Should not be on auth page, got {page.url}"

        # ========== STEP 2: Workspace button visible ==========
        workspace_btn = page.locator('[aria-controls="workspace-navigation-menu"]')
        await workspace_btn.wait_for(state="visible", timeout=10000)
        assert await workspace_btn.count() == 1, "Workspace button should be visible"

        # ========== STEP 3: Switch to HAV workspace ==========
        from braze_mcp.browser.workspace import select_workspace

        result = await select_workspace(page, "HAV")
        assert result is True, "Should successfully switch to HAV workspace"

        # Validate by checking workspace button text contains "havenly"
        workspace_btn = page.locator('[aria-controls="workspace-navigation-menu"]')
        workspace_text = await workspace_btn.text_content()
        assert "havenly" in workspace_text.lower(), f"Workspace should show havenly, got {workspace_text}"

        # ========== STEP 4: Switch to ID workspace ==========
        result = await select_workspace(page, "ID")
        assert result is True, "Should successfully switch to ID workspace"

        # Validate by checking workspace button text
        workspace_btn = page.locator('[aria-controls="workspace-navigation-menu"]')
        workspace_text = await workspace_btn.text_content()
        assert "interior" in workspace_text.lower(), f"Workspace should show Interior Define, got {workspace_text}"

        # ========== STEP 5: Navigate to campaign list ==========
        await page.goto("https://dashboard-07.braze.com/engagement/campaigns", timeout=30000)

        # Validate by waiting for Create Campaign button (indicates page loaded)
        create_btn = page.get_by_role("button", name="Create campaign")
        await create_btn.wait_for(state="visible", timeout=15000)

        assert "/campaigns" in page.url, f"Should be on campaigns page, got {page.url}"
        assert await create_btn.count() == 1, "Create campaign button should be visible"
