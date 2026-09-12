"""Braze REST API client.

Handles HTTP requests to Braze API with multi-brand support.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import get_api_key, get_base_url, validate_brand


class BrazeApiError(Exception):
    """Error from Braze API."""

    def __init__(self, message: str, status_code: int = 0, body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}

    @property
    def is_rate_limit(self) -> bool:
        """Check if this is a rate limit error."""
        return self.status_code == 429

    @classmethod
    def from_response(cls, status_code: int, body: dict) -> "BrazeApiError":
        """Create error from API response."""
        message = body.get("message", f"API error {status_code}")
        return cls(message=message, status_code=status_code, body=body)


class BrazeClient:
    """HTTP client for Braze REST API."""

    def __init__(self, brand: str):
        """Initialize client for a specific brand.

        Args:
            brand: Brand code (HAV, BUR, ID, STF, CZ, TI)

        Raises:
            BrazeConfigError: If brand is invalid or config missing
        """
        self.brand = validate_brand(brand)
        self.api_key = get_api_key(self.brand)
        self.base_url = get_base_url(self.brand)
        self._client: httpx.AsyncClient | None = None

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.get_headers(),
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make GET request to Braze API.

        Args:
            endpoint: API endpoint (e.g., "campaigns/list")
            params: Query parameters

        Returns:
            JSON response as dict

        Raises:
            BrazeApiError: If request fails
        """
        client = await self._get_client()
        response = await client.get(endpoint, params=params)

        if response.status_code >= 400:
            raise BrazeApiError.from_response(
                status_code=response.status_code,
                body=response.json() if response.content else {},
            )

        return response.json()

    async def post(self, endpoint: str, json: dict | None = None) -> dict:
        """Make POST request to Braze API.

        Args:
            endpoint: API endpoint
            json: JSON body

        Returns:
            JSON response as dict

        Raises:
            BrazeApiError: If request fails
        """
        client = await self._get_client()
        response = await client.post(endpoint, json=json)

        if response.status_code >= 400:
            raise BrazeApiError.from_response(
                status_code=response.status_code,
                body=response.json() if response.content else {},
            )

        return response.json()


# Parameter builders


def build_campaign_list_params(
    page: int = 0,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Build parameters for campaigns/list endpoint."""
    return {
        "page": page,
        "include_archived": include_archived,
        "sort_direction": "desc",
    }


def build_campaign_analytics_params(
    campaign_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """Build parameters for campaigns/data_series endpoint.

    Note: Braze caps at 100 days for campaign analytics.
    """
    length = min(days, 100)  # Cap at 100 days
    ending_at = datetime.now(timezone.utc).isoformat()

    return {
        "campaign_id": campaign_id,
        "length": length,
        "ending_at": ending_at,
    }


def build_canvas_analytics_params(
    canvas_id: str,
    days: int = 14,
) -> dict[str, Any]:
    """Build parameters for canvas/data_series endpoint.

    Note: Braze caps at 14 days for canvas analytics.
    """
    length = min(days, 14)  # Cap at 14 days
    ending_at = datetime.now(timezone.utc).isoformat()

    return {
        "canvas_id": canvas_id,
        "length": length,
        "ending_at": ending_at,
        "include_variant_breakdown": "true",
        "include_step_breakdown": "true",
    }


# Response parsers


def parse_campaign_list(response: dict) -> list[dict]:
    """Parse campaigns/list response."""
    return response.get("campaigns", [])


def parse_campaign_details(response: dict) -> dict:
    """Parse campaigns/details response."""
    return response


def parse_analytics(response: dict) -> dict:
    """Parse analytics response (campaigns or canvas)."""
    return response
