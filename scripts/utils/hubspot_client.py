"""HubSpot CRM API client wrapper.

Handles auth + pagination for CRM v3 objects and lists.
Auth: Authorization: Bearer {private app / service key token}
Base URL: https://api.hubapi.com
"""

from __future__ import annotations

import time

import requests


HUBSPOT_BASE_URL = "https://api.hubapi.com"
BATCH_READ_CHUNK_SIZE = 100


class HubSpotClient:
    """Thin API wrapper for the HubSpot CRM v3 API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None, retries: int = 5) -> dict | None:
        url = path if path.startswith("http") else f"{HUBSPOT_BASE_URL}/{path.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = 2 ** attempt
                    print(f"  [hubspot] {resp.status_code}, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [hubspot] GET {url} failed: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def _post(self, path: str, body: dict, retries: int = 5) -> dict | None:
        url = f"{HUBSPOT_BASE_URL}/{path.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = 2 ** attempt
                    print(f"  [hubspot] {resp.status_code}, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [hubspot] POST {url} failed: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def get_list_membership_ids(self, list_id: str) -> list[str]:
        """Return every contact record ID that is a member of the given list."""
        ids: list[str] = []
        after: str | None = None
        while True:
            params = {"limit": 250}
            if after:
                params["after"] = after
            data = self._get(f"/crm/v3/lists/{list_id}/memberships", params=params)
            if not data:
                break
            ids.extend(r["recordId"] for r in data.get("results", []))
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break
        return ids

    def get_contacts_batch(self, contact_ids: list[str], properties: list[str]) -> list[dict]:
        """Batch-fetch contact properties for a list of contact IDs (chunked to HubSpot's 100/request limit)."""
        contacts: list[dict] = []
        for i in range(0, len(contact_ids), BATCH_READ_CHUNK_SIZE):
            chunk = contact_ids[i:i + BATCH_READ_CHUNK_SIZE]
            body = {
                "inputs": [{"id": cid} for cid in chunk],
                "properties": properties,
            }
            data = self._post("/crm/v3/objects/contacts/batch/read", body)
            if data:
                contacts.extend(data.get("results", []))
        return contacts

    def search_contacts(self, filters: list[dict], properties: list[str], page_size: int = 100) -> list[dict]:
        """Search contacts via the CRM v3 Search API, paginating through all results.

        `filters` is a single filterGroup's filter list (AND'd together), e.g.
        [{"propertyName": "is_trade_partner", "operator": "EQ", "value": "true"}].
        Use this for property-based queries (no static HubSpot list required) —
        contrast with get_list_membership_ids, which reads a pre-built list.
        """
        results: list[dict] = []
        after: str | None = None
        while True:
            body = {
                "filterGroups": [{"filters": filters}],
                "properties": properties,
                "limit": page_size,
            }
            if after:
                body["after"] = after
            data = self._post("/crm/v3/objects/contacts/search", body)
            if not data:
                break
            results.extend(data.get("results", []))
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break
        return results
