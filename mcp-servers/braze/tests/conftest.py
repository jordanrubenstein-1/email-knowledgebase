"""Shared test fixtures for Braze MCP server tests."""

import pytest
from pathlib import Path
from dotenv import load_dotenv

# Load .env file for e2e tests
env_path = Path(__file__).parent.parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


@pytest.fixture
def sample_campaign():
    """Sample campaign data from Braze API."""
    return {
        "id": "abc123-def456",
        "name": "P_EM_2025_01_20_HAV_Test_Campaign",
        "draft_state": "draft",
        "tags": ["automated", "test"],
        "created_at": "2025-01-20T10:00:00Z",
        "updated_at": "2025-01-20T12:00:00Z",
        "messages": {
            "message_variation_abc": {
                "channel": "email",
                "name": "Variant 1",
                "subject": "Test Subject Line",
                "preheader": "Test preheader text",
                "body": "<html><body><h1>Test</h1></body></html>",
            }
        },
    }


@pytest.fixture
def sample_campaign_list_response(sample_campaign):
    """Sample response from campaigns/list endpoint."""
    return {
        "campaigns": [sample_campaign],
        "message": "success",
    }


@pytest.fixture
def sample_campaign_analytics():
    """Sample response from campaigns/data_series endpoint."""
    return {
        "data": [
            {
                "time": "2025-01-20T00:00:00Z",
                "messages": {
                    "message_variation_abc": {
                        "sent": 1000,
                        "delivered": 980,
                        "unique_opens": 450,
                        "unique_clicks": 25,
                        "unsubscribes": 5,
                        "bounces": 10,
                    }
                },
            }
        ],
        "message": "success",
    }


@pytest.fixture
def sample_canvas():
    """Sample canvas data from Braze API."""
    return {
        "id": "canvas-123-456",
        "name": "Cart Abandonment Flow",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-20T00:00:00Z",
        "tags": ["triggered", "ecommerce"],
        "steps": [
            {
                "id": "step-1",
                "name": "Initial Email",
                "type": "message",
                "channels": ["email"],
                "messages": {
                    "email_msg": {
                        "channel": "email",
                        "subject": "You left something behind!",
                        "body": "<html>...</html>",
                    }
                },
            },
            {
                "id": "step-2",
                "name": "Follow-up Email",
                "type": "message",
                "channels": ["email"],
            },
        ],
    }


@pytest.fixture
def sample_template():
    """Sample email template from Braze API."""
    return {
        "email_template_id": "template-abc-123",
        "template_name": "Summer Sale Template",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-15T00:00:00Z",
        "subject": "Summer Sale - {{first_name}}",
        "preheader": "Don't miss out!",
        "body": "<html><body>{{content}}</body></html>",
        "tags": ["sale", "seasonal"],
    }


@pytest.fixture
def env_with_hav_config(monkeypatch):
    """Set up environment with HAV brand configuration."""
    monkeypatch.setenv("BRAZE_API_KEY_HAV", "test-hav-api-key")
    monkeypatch.setenv("BRAZE_BASE_URL_HAV", "https://rest.iad-07.braze.com")
    monkeypatch.setenv("BRAZE_DASHBOARD_URL", "https://dashboard-07.braze.com")
    monkeypatch.setenv("BRAZE_DASHBOARD_EMAIL", "test@example.com")
    monkeypatch.setenv("BRAZE_DASHBOARD_PASSWORD", "test-password")
    monkeypatch.setenv("BRAZE_TOTP_SECRET", "JBSWY3DPEHPK3PXP")


