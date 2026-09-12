"""Air (air.inc) REST API client wrapper.

Handles auth and cursor pagination. Bypasses the MCP server entirely — talks
directly to Air's REST API so it can run headless (cron/CI), not just inside
a Claude session.

Auth: x-api-key + x-air-workspace-id headers
Base URL: https://api.air.inc/v1
Pagination: cursor-based, sorted newest-updatedAt-first (confirmed empirically
2026-07-15 — not documented, but consistent across every board checked).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

AIR_BASE_URL = "https://api.air.inc/v1"


class AirClient:
    def __init__(self, api_key: str | None = None, workspace_id: str | None = None):
        self.api_key = api_key or os.environ["AIR_API_KEY"]
        self.workspace_id = workspace_id or os.environ["AIR_WORKSPACE_ID"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "x-api-key": self.api_key,
                "x-air-workspace-id": self.workspace_id,
            }
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self.session.get(f"{AIR_BASE_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_board(self, board_id: str) -> dict:
        return self._get(f"/boards/{board_id}")

    def list_assets_page(
        self,
        parent_board_id: str,
        cursor: str | None = None,
        limit: int = 100,
        include_nested: bool = True,
    ) -> dict:
        params: dict[str, Any] = {
            "parentBoardId": parent_board_id,
            "limit": limit,
            "includeNestedAssets": str(include_nested).lower(),
        }
        if cursor:
            params["cursor"] = cursor
        return self._get("/assets", params=params)

    def iter_assets(
        self,
        parent_board_id: str,
        limit: int = 100,
        include_nested: bool = True,
        stop_at_updated_at: str | None = None,
    ) -> Iterator[dict]:
        """Yield assets newest-updatedAt-first.

        If stop_at_updated_at is set, stops as soon as an asset's
        coverVersion.updatedAt is <= that watermark — everything after that
        point in the feed was already seen on a prior sync.
        """
        cursor = None
        while True:
            page = self.list_assets_page(
                parent_board_id, cursor=cursor, limit=limit, include_nested=include_nested
            )
            for asset in page.get("data", []):
                updated_at = (asset.get("coverVersion") or {}).get("updatedAt")
                if stop_at_updated_at and updated_at and updated_at <= stop_at_updated_at:
                    return
                yield asset
            pagination = page.get("pagination", {})
            if not pagination.get("hasMore") or not pagination.get("cursor"):
                return
            cursor = pagination["cursor"]
