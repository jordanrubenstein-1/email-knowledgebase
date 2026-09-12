"""Tests for config module - TDD: write tests first."""

import os
import pytest


class TestBrandMapping:
    """Test brand code to workspace name mapping."""

    def test_valid_brand_codes(self):
        """All valid brand codes should map to workspace names."""
        from braze_mcp.config import BRAND_WORKSPACE_MAP

        assert "HAV" in BRAND_WORKSPACE_MAP
        assert "BUR" in BRAND_WORKSPACE_MAP
        assert "ID" in BRAND_WORKSPACE_MAP
        assert "STF" in BRAND_WORKSPACE_MAP
        assert "CZ" in BRAND_WORKSPACE_MAP
        assert "TI" in BRAND_WORKSPACE_MAP

    def test_workspace_names(self):
        """Workspace names should match Braze dashboard."""
        from braze_mcp.config import BRAND_WORKSPACE_MAP

        assert BRAND_WORKSPACE_MAP["HAV"] == "havenly"
        assert BRAND_WORKSPACE_MAP["BUR"] == "Burrow - Production"
        assert BRAND_WORKSPACE_MAP["ID"] == "Interior Define"
        assert BRAND_WORKSPACE_MAP["STF"] == "St Frank"
        assert BRAND_WORKSPACE_MAP["CZ"] == "The Citizenry"
        assert BRAND_WORKSPACE_MAP["TI"] == "The Inside"


class TestGetApiKey:
    """Test API key retrieval for brands."""

    def test_get_api_key_for_brand(self, monkeypatch):
        """Should return brand-specific API key."""
        from braze_mcp.config import get_api_key

        monkeypatch.setenv("BRAZE_API_KEY_HAV", "test-hav-key")
        assert get_api_key("HAV") == "test-hav-key"

    def test_get_api_key_case_insensitive(self, monkeypatch):
        """Brand codes should be case-insensitive."""
        from braze_mcp.config import get_api_key

        monkeypatch.setenv("BRAZE_API_KEY_HAV", "test-hav-key")
        assert get_api_key("hav") == "test-hav-key"
        assert get_api_key("Hav") == "test-hav-key"

    def test_get_api_key_fallback(self, monkeypatch):
        """Should fall back to generic key if brand-specific not found."""
        from braze_mcp.config import get_api_key

        monkeypatch.delenv("BRAZE_API_KEY_HAV", raising=False)
        monkeypatch.setenv("BRAZE_API_KEY", "fallback-key")
        assert get_api_key("HAV") == "fallback-key"

    def test_get_api_key_missing_raises(self, monkeypatch):
        """Should raise if no API key found."""
        from braze_mcp.config import get_api_key, BrazeConfigError

        monkeypatch.delenv("BRAZE_API_KEY_HAV", raising=False)
        monkeypatch.delenv("BRAZE_API_KEY", raising=False)
        with pytest.raises(BrazeConfigError, match="No API key found"):
            get_api_key("HAV")

    def test_get_api_key_invalid_brand(self):
        """Should raise for unknown brand codes."""
        from braze_mcp.config import get_api_key, BrazeConfigError

        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            get_api_key("INVALID")


class TestGetBaseUrl:
    """Test base URL retrieval for brands."""

    def test_get_base_url_for_brand(self, monkeypatch):
        """Should return brand-specific base URL."""
        from braze_mcp.config import get_base_url

        monkeypatch.setenv("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com")
        assert get_base_url("HAV") == "https://rest.iad-07.braze.com"

    def test_get_base_url_fallback(self, monkeypatch):
        """Should fall back to generic URL if brand-specific not found."""
        from braze_mcp.config import get_base_url

        monkeypatch.delenv("BRAZE_BASE_URL_HAV", raising=False)
        monkeypatch.setenv("BRAZE_BASE_URL", "https://rest.iad-01.braze.com")
        assert get_base_url("HAV") == "https://rest.iad-01.braze.com"

    def test_get_base_url_default(self, monkeypatch):
        """Should use default URL if none configured."""
        from braze_mcp.config import get_base_url, DEFAULT_BASE_URL

        monkeypatch.delenv("BRAZE_BASE_URL_HAV", raising=False)
        monkeypatch.delenv("BRAZE_BASE_URL", raising=False)
        assert get_base_url("HAV") == DEFAULT_BASE_URL


class TestDashboardConfig:
    """Test dashboard (Playwright) configuration."""

    def test_get_dashboard_url(self, monkeypatch):
        """Should return dashboard URL."""
        from braze_mcp.config import get_dashboard_config

        monkeypatch.setenv("BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com")
        monkeypatch.setenv("BRAZE_DASHBOARD_EMAIL", "test@example.com")
        monkeypatch.setenv("BRAZE_DASHBOARD_PASSWORD", "secret")
        monkeypatch.setenv("BRAZE_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

        config = get_dashboard_config()
        assert config["url"] == "https://dashboard-07.braze.com"
        assert config["email"] == "test@example.com"
        assert config["password"] == "secret"
        assert config["totp_secret"] == "JBSWY3DPEHPK3PXP"

    def test_get_dashboard_config_missing_raises(self, monkeypatch):
        """Should raise if required dashboard config missing."""
        from braze_mcp.config import get_dashboard_config, BrazeConfigError

        monkeypatch.delenv("BRAZE_DASHBOARD_EMAIL", raising=False)
        with pytest.raises(BrazeConfigError, match="Missing dashboard config"):
            get_dashboard_config()


class TestValidateBrand:
    """Test brand validation."""

    def test_validate_known_brands(self):
        """Should accept valid brand codes."""
        from braze_mcp.config import validate_brand

        for brand in ["HAV", "BUR", "ID", "STF", "CZ", "TI"]:
            assert validate_brand(brand) == brand.upper()

    def test_validate_brand_normalizes_case(self):
        """Should normalize to uppercase."""
        from braze_mcp.config import validate_brand

        assert validate_brand("hav") == "HAV"
        assert validate_brand("Hav") == "HAV"

    def test_validate_brand_rejects_unknown(self):
        """Should reject unknown brand codes."""
        from braze_mcp.config import validate_brand, BrazeConfigError

        with pytest.raises(BrazeConfigError, match="Unknown brand"):
            validate_brand("FAKE")

    def test_validate_brand_accepts_full_names(self):
        """Should accept full brand names as aliases."""
        from braze_mcp.config import validate_brand

        assert validate_brand("Havenly") == "HAV"
        assert validate_brand("havenly") == "HAV"
        assert validate_brand("HAVENLY") == "HAV"
        assert validate_brand("Burrow") == "BUR"
        assert validate_brand("Interior Define") == "ID"
        assert validate_brand("St Frank") == "STF"
        assert validate_brand("St. Frank") == "STF"
        assert validate_brand("The Citizenry") == "CZ"
        assert validate_brand("Citizenry") == "CZ"
        assert validate_brand("The Inside") == "TI"
