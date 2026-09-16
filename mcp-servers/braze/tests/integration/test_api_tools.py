"""Integration tests for API-based tools with mocked HTTP."""

import re
import pytest
from pytest_httpx import HTTPXMock


class TestListCampaignsTool:
    """Test braze_list_campaigns tool."""

    @pytest.fixture
    def mock_campaigns_api(self, httpx_mock: HTTPXMock, sample_campaign_list_response):
        """Mock the campaigns/list endpoint."""
        httpx_mock.add_response(
            url=re.compile(r".*/campaigns/list.*"),
            json=sample_campaign_list_response,
        )
        return httpx_mock

    async def test_list_campaigns(
        self, mock_campaigns_api, env_with_hav_config, sample_campaign_list_response
    ):
        """Should list campaigns for a brand."""
        from braze_mcp.tools.api_tools import list_campaigns

        result = await list_campaigns(brand="HAV", page=0, include_archived=False)

        assert len(result) == 1
        assert result[0]["id"] == "abc123-def456"

    async def test_list_campaigns_invalid_brand(self, env_with_hav_config):
        """Should raise for invalid brand."""
        from braze_mcp.tools.api_tools import list_campaigns
        from braze_mcp.config import BrazeConfigError

        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            await list_campaigns(brand="INVALID", page=0)


class TestGetCampaignTool:
    """Test braze_get_campaign tool."""

    @pytest.fixture
    def mock_campaign_details_api(self, httpx_mock: HTTPXMock, sample_campaign):
        """Mock the campaigns/details endpoint."""
        httpx_mock.add_response(
            url=re.compile(r".*/campaigns/details.*"),
            json=sample_campaign,
        )
        return httpx_mock

    async def test_get_campaign(
        self, mock_campaign_details_api, env_with_hav_config, sample_campaign
    ):
        """Should get campaign details."""
        from braze_mcp.tools.api_tools import get_campaign

        result = await get_campaign(brand="HAV", campaign_id="abc123-def456")

        assert result["id"] == "abc123-def456"
        assert "messages" in result


class TestGetCampaignAnalyticsTool:
    """Test braze_get_campaign_analytics tool."""

    @pytest.fixture
    def mock_analytics_api(self, httpx_mock: HTTPXMock, sample_campaign_analytics):
        """Mock the campaigns/data_series endpoint."""
        httpx_mock.add_response(
            url=re.compile(r".*/campaigns/data_series.*"),
            json=sample_campaign_analytics,
        )
        return httpx_mock

    async def test_get_campaign_analytics(
        self, mock_analytics_api, env_with_hav_config, sample_campaign_analytics
    ):
        """Should get campaign analytics."""
        from braze_mcp.tools.api_tools import get_campaign_analytics

        result = await get_campaign_analytics(
            brand="HAV", campaign_id="abc123-def456", days=30
        )

        assert "data" in result
        assert len(result["data"]) == 1


class TestListCanvasesTool:
    """Test braze_list_canvases tool."""

    @pytest.fixture
    def mock_canvases_api(self, httpx_mock: HTTPXMock, sample_canvas):
        """Mock the canvas/list endpoint."""
        httpx_mock.add_response(
            url=re.compile(r".*/canvas/list.*"),
            json={"canvases": [sample_canvas], "message": "success"},
        )
        return httpx_mock

    async def test_list_canvases(
        self, mock_canvases_api, env_with_hav_config, sample_canvas
    ):
        """Should list canvases for a brand."""
        from braze_mcp.tools.api_tools import list_canvases

        result = await list_canvases(brand="HAV", page=0, include_archived=False)

        assert len(result) == 1
        assert result[0]["id"] == "canvas-123-456"


class TestListTemplatesTool:
    """Test braze_list_templates tool."""

    @pytest.fixture
    def mock_templates_api(self, httpx_mock: HTTPXMock, sample_template):
        """Mock the templates/email/list endpoint."""
        httpx_mock.add_response(
            url=re.compile(r".*/templates/email/list.*"),
            json={"templates": [sample_template], "message": "success"},
        )
        return httpx_mock

    async def test_list_templates(
        self, mock_templates_api, env_with_hav_config, sample_template
    ):
        """Should list email templates for a brand."""
        from braze_mcp.tools.api_tools import list_templates

        result = await list_templates(brand="HAV", limit=100)

        assert len(result) == 1
        assert result[0]["template_name"] == "Summer Sale Template"


class TestApiErrorHandling:
    """Test API error handling in tools."""

    async def test_handles_auth_error(self, httpx_mock: HTTPXMock, env_with_hav_config):
        """Should raise proper error for auth failures."""
        from braze_mcp.tools.api_tools import list_campaigns
        from braze_mcp.api.client import BrazeApiError

        httpx_mock.add_response(
            url=re.compile(r".*/campaigns/list.*"),
            status_code=401,
            json={"message": "Invalid API key"},
        )

        with pytest.raises(BrazeApiError) as exc:
            await list_campaigns(brand="HAV", page=0)

        assert exc.value.status_code == 401

    async def test_handles_rate_limit(self, httpx_mock: HTTPXMock, env_with_hav_config):
        """Should detect rate limit errors."""
        from braze_mcp.tools.api_tools import list_campaigns
        from braze_mcp.api.client import BrazeApiError

        httpx_mock.add_response(
            url=re.compile(r".*/campaigns/list.*"),
            status_code=429,
            json={"message": "Rate limit exceeded"},
        )

        with pytest.raises(BrazeApiError) as exc:
            await list_campaigns(brand="HAV", page=0)

        assert exc.value.is_rate_limit
