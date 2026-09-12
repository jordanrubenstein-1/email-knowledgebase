"""Tests for Braze API client - TDD: write tests first."""

import pytest


class TestBrazeClient:
    """Test Braze API client initialization and configuration."""

    def test_client_requires_brand(self):
        """Client should require a valid brand."""
        from braze_mcp.api.client import BrazeClient
        from braze_mcp.config import BrazeConfigError

        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            BrazeClient("INVALID")

    def test_client_uses_brand_config(self, monkeypatch):
        """Client should use brand-specific API key and URL."""
        from braze_mcp.api.client import BrazeClient

        monkeypatch.setenv("BRAZE_API_KEY_HAV", "test-key")
        monkeypatch.setenv("BRAZE_BASE_URL_HAV", "https://test.braze.com")

        client = BrazeClient("HAV")
        assert client.api_key == "test-key"
        assert client.base_url == "https://test.braze.com"

    def test_client_headers(self, monkeypatch):
        """Client should set proper auth headers."""
        from braze_mcp.api.client import BrazeClient

        monkeypatch.setenv("BRAZE_API_KEY_HAV", "test-key")

        client = BrazeClient("HAV")
        headers = client.get_headers()

        assert headers["Authorization"] == "Bearer test-key"
        assert headers["Content-Type"] == "application/json"


class TestBuildParams:
    """Test parameter building for API requests."""

    def test_campaign_list_params(self):
        """Should build valid campaign list params."""
        from braze_mcp.api.client import build_campaign_list_params

        params = build_campaign_list_params(page=0, include_archived=False)
        assert params["page"] == 0
        assert params["include_archived"] is False
        assert params["sort_direction"] == "desc"

    def test_campaign_list_params_with_archived(self):
        """Should handle archived flag."""
        from braze_mcp.api.client import build_campaign_list_params

        params = build_campaign_list_params(page=2, include_archived=True)
        assert params["page"] == 2
        assert params["include_archived"] is True

    def test_analytics_params_caps_days(self):
        """Should cap campaign analytics days at 100."""
        from braze_mcp.api.client import build_campaign_analytics_params

        params = build_campaign_analytics_params(
            campaign_id="test-id",
            days=150,
        )
        assert params["length"] == 100  # Capped
        assert params["campaign_id"] == "test-id"

    def test_canvas_analytics_params_caps_days(self):
        """Should cap canvas analytics days at 14."""
        from braze_mcp.api.client import build_canvas_analytics_params

        params = build_canvas_analytics_params(
            canvas_id="test-id",
            days=30,
        )
        assert params["length"] == 14  # Capped
        assert params["canvas_id"] == "test-id"
        assert params["include_variant_breakdown"] == "true"
        assert params["include_step_breakdown"] == "true"


class TestParseResponses:
    """Test response parsing from Braze API."""

    def test_parse_campaign_list(self, sample_campaign_list_response):
        """Should parse campaign list response."""
        from braze_mcp.api.client import parse_campaign_list

        result = parse_campaign_list(sample_campaign_list_response)
        assert len(result) == 1
        assert result[0]["id"] == "abc123-def456"
        assert result[0]["name"] == "P_EM_2025_01_20_HAV_Test_Campaign"

    def test_parse_campaign_list_empty(self):
        """Should handle empty campaign list."""
        from braze_mcp.api.client import parse_campaign_list

        result = parse_campaign_list({"campaigns": [], "message": "success"})
        assert result == []

    def test_parse_campaign_details(self, sample_campaign):
        """Should parse campaign details response."""
        from braze_mcp.api.client import parse_campaign_details

        result = parse_campaign_details(sample_campaign)
        assert result["id"] == "abc123-def456"
        assert "messages" in result

    def test_parse_analytics(self, sample_campaign_analytics):
        """Should parse analytics response."""
        from braze_mcp.api.client import parse_analytics

        result = parse_analytics(sample_campaign_analytics)
        assert "data" in result
        assert len(result["data"]) == 1


class TestApiErrors:
    """Test API error handling."""

    def test_api_error_from_response(self):
        """Should create error from API error response."""
        from braze_mcp.api.client import BrazeApiError

        error = BrazeApiError.from_response(
            status_code=401,
            body={"message": "Invalid API key"},
        )
        assert error.status_code == 401
        assert "Invalid API key" in str(error)

    def test_api_error_rate_limit(self):
        """Should detect rate limit errors."""
        from braze_mcp.api.client import BrazeApiError

        error = BrazeApiError.from_response(
            status_code=429,
            body={"message": "Rate limit exceeded"},
        )
        assert error.is_rate_limit
        assert error.status_code == 429
