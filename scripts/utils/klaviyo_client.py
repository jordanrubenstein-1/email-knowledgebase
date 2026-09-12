"""Klaviyo REST API client wrapper.

Handles auth, pagination, rate limiting, and metric ID discovery.
All methods return plain Python dicts/lists — no business logic here.

Auth: Klaviyo-API-Key {private_key} header + revision: 2024-10-15
Base URL: https://a.klaviyo.com/api (same for all accounts)
Rate limit: 700 requests/minute
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_API_VERSION = "2024-10-15"
RATE_LIMIT_PER_MINUTE = 700

# Standard email metric names in Klaviyo (exact names as returned by /api/metrics/)
METRIC_NAMES = {
    "Received Email",
    "Opened Email",
    "Clicked Email",
    "Unsubscribed from Email Marketing",  # NOT "Unsubscribed" — that's a different metric
    "Bounced Email",
    "Marked Email as Spam",
}


def _aggregate_by_flow_message(results: list[dict]) -> dict[str, dict]:
    """Aggregate flow analytics result rows into a flow_message_id -> summary dict."""
    by_msg: dict[str, dict] = {}
    for row in results:
        gkeys = row.get("groupings") or row.get("grouping_keys") or {}
        mid = gkeys.get("flow_message_id") or row.get("flow_message_id")
        if not mid:
            continue
        if mid not in by_msg:
            by_msg[mid] = {
                "total_sends": 0, "total_delivered": 0, "total_opens": 0,
                "total_clicks": 0, "unique_opens": 0, "unique_clicks": 0,
                "open_rate": 0.0, "click_rate": 0.0,
                "total_open_rate": 0.0, "total_click_rate": 0.0,
                "total_unsubscribes": 0, "total_bounces": 0,
            }
        a = by_msg[mid]
        s = row.get("statistics", {})
        a["total_opens"] += int(s.get("opens", 0) or 0)
        a["total_clicks"] += int(s.get("clicks", 0) or 0)
        a["unique_opens"] += int(s.get("opens_unique", 0) or 0)
        a["unique_clicks"] += int(s.get("clicks_unique", 0) or 0)
        a["total_sends"] += int(s.get("recipients", 0) or 0)
        a["total_delivered"] += int(s.get("delivered", 0) or 0)
        a["total_unsubscribes"] += int(s.get("unsubscribes", 0) or 0)
        a["total_bounces"] += int(s.get("bounced", 0) or 0)

    for mid, a in by_msg.items():
        sends = a["total_sends"]
        a["open_rate"]        = round(a["unique_opens"] / sends, 4) if sends else 0.0
        a["click_rate"]       = round(a["unique_clicks"] / sends, 4) if sends else 0.0
        a["total_open_rate"]  = round(a["total_opens"] / sends, 4) if sends else 0.0
        a["total_click_rate"] = round(a["total_clicks"] / sends, 4) if sends else 0.0
        if not a["total_delivered"]:
            a["total_delivered"] = sends

    return by_msg


def _aggregate_by_campaign(results: list[dict]) -> dict[str, dict]:
    """Aggregate a flat list of analytics result rows into a campaign_id -> summary dict.

    Handles both 'groupings' (timeframe queries) and 'grouping_keys' (filtered queries)
    field names returned by different Klaviyo API call patterns.
    """
    by_campaign: dict[str, dict] = {}
    for row in results:
        # API uses 'groupings' for timeframe queries, 'grouping_keys' for filtered queries
        gkeys = row.get("groupings") or row.get("grouping_keys") or {}
        cid = gkeys.get("campaign_id") or row.get("campaign_id")
        if not cid:
            continue
        if cid not in by_campaign:
            by_campaign[cid] = {
                "total_sends": 0, "total_delivered": 0, "total_opens": 0,
                "total_clicks": 0, "unique_opens": 0, "unique_clicks": 0,
                "open_rate": 0.0, "click_rate": 0.0,
                "total_open_rate": 0.0, "total_click_rate": 0.0,
                "total_unsubscribes": 0, "total_bounces": 0,
            }
        a = by_campaign[cid]
        s = row.get("statistics", {})
        a["total_opens"] += int(s.get("opens", 0) or 0)
        a["total_clicks"] += int(s.get("clicks", 0) or 0)
        a["unique_opens"] += int(s.get("opens_unique", 0) or 0)
        a["unique_clicks"] += int(s.get("clicks_unique", 0) or 0)
        a["total_sends"] += int(s.get("recipients", 0) or 0)
        a["total_delivered"] += int(s.get("delivered", 0) or 0)
        a["total_unsubscribes"] += int(s.get("unsubscribes", 0) or 0)
        a["total_bounces"] += int(s.get("bounced", 0) or 0)

    for cid, a in by_campaign.items():
        sends = a["total_sends"]
        a["open_rate"]        = round(a["unique_opens"] / sends, 4) if sends else 0.0
        a["click_rate"]       = round(a["unique_clicks"] / sends, 4) if sends else 0.0
        a["total_open_rate"]  = round(a["total_opens"] / sends, 4) if sends else 0.0
        a["total_click_rate"] = round(a["total_clicks"] / sends, 4) if sends else 0.0
        if not a["total_delivered"]:
            a["total_delivered"] = sends

    return by_campaign


class RateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, max_calls: int, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            # Drop calls older than the window
            cutoff = now - self.period
            self._calls = [t for t in self._calls if t > cutoff]
            if len(self._calls) >= self.max_calls:
                sleep_for = self._calls[0] + self.period - now
                if sleep_for > 0:
                    time.sleep(sleep_for)
                now = time.monotonic()
                self._calls = [t for t in self._calls if t > now - self.period]
            self._calls.append(time.monotonic())


class KlaviyoClient:
    """Thin API wrapper for Klaviyo REST API v2024-10-15."""

    def __init__(self, api_key: str, brand: str):
        self.api_key = api_key
        self.brand = brand
        self._rate_limiter = RateLimiter(max_calls=RATE_LIMIT_PER_MINUTE)
        self._metric_cache: dict[str, str] = {}  # metric name -> metric ID
        self._placed_order_metric_id: str | None = None  # required for campaign-values-reports
        self._segment_cache: dict[str, str] = {}  # name (lowercased) -> list/segment ID

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Klaviyo-API-Key {self.api_key}",
            "revision": KLAVIYO_API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, url: str, params: dict | None = None, retries: int = 5) -> dict | None:
        """GET request with 429/5xx retry + exponential backoff."""
        self._rate_limiter.acquire()
        # If it's a full URL (pagination cursor), use as-is; otherwise prepend base
        if not url.startswith("http"):
            url = f"{KLAVIYO_BASE_URL}/{url.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] server error {resp.status_code}, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] GET {url} failed: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def _post(self, endpoint: str, body: dict, retries: int = 5) -> dict | None:
        """POST request with retry (retries on 429/5xx; returns None immediately on 4xx)."""
        self._rate_limiter.acquire()
        url = f"{KLAVIYO_BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if 400 <= resp.status_code < 500:
                    # Client error — don't retry; caller can adjust and retry
                    try:
                        err = resp.json()
                    except Exception:
                        err = resp.text[:300]
                    print(f"  [klaviyo] POST {endpoint} {resp.status_code}: {err}")
                    return None
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] POST {url} failed: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def _post_no_content(self, endpoint: str, body: dict, retries: int = 5) -> bool:
        """POST for endpoints that return 202/204 with an empty body (e.g. bulk
        subscription jobs). Mirrors _post's retry logic but reports success from
        the status code instead of parsing a JSON body."""
        self._rate_limiter.acquire()
        url = f"{KLAVIYO_BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if 400 <= resp.status_code < 500:
                    try:
                        err = resp.json()
                    except Exception:
                        err = resp.text[:300]
                    print(f"  [klaviyo] POST {endpoint} {resp.status_code}: {err}")
                    return False
                resp.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] POST {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def _delete(self, endpoint: str, body: dict, retries: int = 5) -> bool:
        """DELETE request with a JSON body (used for list relationship removal)."""
        self._rate_limiter.acquire()
        url = f"{KLAVIYO_BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(retries):
            try:
                resp = requests.delete(url, headers=self._headers(), json=body, timeout=30)
                if resp.status_code == 429 or resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if 400 <= resp.status_code < 500:
                    print(f"  [klaviyo] DELETE {endpoint} {resp.status_code}: {resp.text[:300]}")
                    return False
                resp.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] DELETE {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def _paginate(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages following Klaviyo cursor pagination (data.links.next)."""
        results: list[dict] = []
        # First page: use endpoint; subsequent pages: use full cursor URL
        next_url: str | None = endpoint
        is_first = True
        while next_url:
            if is_first:
                data = self._get(next_url, params=params)
                is_first = False
            else:
                data = self._get(next_url)  # cursor URL already has params baked in
            if not data:
                break
            results.extend(data.get("data", []))
            next_url = (data.get("links") or {}).get("next")
        return results

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    def get_campaigns(self, channel: str = "email") -> list[dict]:
        """List all sent campaigns for the given channel.

        Note: messages.channel filter is required by Klaviyo API.
        Valid sort fields: id, name, -id, scheduled_at, -scheduled_at,
                           created_at, -created_at, updated_at, -updated_at
        """
        params = {
            "filter": f"equals(messages.channel,'{channel}'),equals(status,'Sent')",
            "fields[campaign]": "name,status,send_time,scheduled_at,created_at,updated_at",
            "sort": "-created_at",
        }
        return self._paginate("/campaigns/", params)

    def get_campaign_messages(self, campaign_id: str) -> list[dict]:
        """Get all message variants for a campaign, with HTML via included template.

        Returns messages with an extra '_html' key injected from the linked template.
        Subject and preview_text are in attributes.content dict (not top-level).
        Message display name is in attributes.label (not attributes.name).
        """
        data = self._get(
            f"/campaigns/{campaign_id}/campaign-messages/",
            params={
                "fields[campaign-message]": "label,channel,content,send_times,created_at,updated_at",
                "fields[template]": "html",
                "include": "template",
            },
        )
        if not data:
            return []

        # Build template ID -> HTML lookup from included array
        template_html: dict[str, str] = {}
        for inc in data.get("included", []):
            if inc.get("type") == "template":
                html = inc.get("attributes", {}).get("html", "")
                if html:
                    template_html[inc["id"]] = html

        # Inject HTML into each message as '_html' key
        messages = data.get("data", [])
        for msg in messages:
            tmpl_id = (
                (msg.get("relationships") or {})
                .get("template") or {}
            )
            tmpl_id = (tmpl_id.get("data") or {}).get("id")
            if tmpl_id and tmpl_id in template_html:
                msg["_html"] = template_html[tmpl_id]
            else:
                msg["_html"] = ""

        return messages

    def get_campaign_message_html(self, message_id: str) -> str | None:
        """Get HTML for a single campaign message via its linked template."""
        data = self._get(
            f"/campaign-messages/{message_id}/",
            params={
                "fields[template]": "html",
                "include": "template",
            },
        )
        if not data:
            return None

        for inc in data.get("included", []):
            if inc.get("type") == "template":
                html = inc.get("attributes", {}).get("html", "")
                if html:
                    return html
        return None

    # ------------------------------------------------------------------
    # Flows (= Braze Canvases / Triggered Journeys)
    # ------------------------------------------------------------------

    def get_flows(self) -> list[dict]:
        """List all flows."""
        params = {
            "fields[flow]": "name,status,created,updated,trigger_type",
            "sort": "-created",
        }
        return self._paginate("/flows/", params)

    def get_flow_actions(self, flow_id: str) -> list[dict]:
        """Get all actions for a flow (SEND_EMAIL, SEND_SMS, TIME_DELAY, branches, etc).

        Unfiltered — callers should filter by attributes.action_type for the
        action types they care about (matches the pattern already used by
        get_flow_email_timing below).
        """
        params = {
            "fields[flow-action]": "action_type,status,created,updated",
        }
        data = self._get(f"/flows/{flow_id}/flow-actions/", params=params)
        if not data:
            return []
        return data.get("data", [])

    def get_flow_email_timing(self, flow_id: str) -> list[int]:
        """Return cumulative delay in seconds for each SEND_EMAIL step in a flow.

        Fetches all action nodes (SEND_EMAIL + TIME_DELAY + branches), sorts by
        created timestamp (which reflects sequence order), and accumulates delay
        seconds from TIME_DELAY nodes before each SEND_EMAIL. Returns a list where
        index 0 = T1's cumulative delay, index 1 = T2's, etc.

        Note: For branching flows the sort order groups branch actions by the time
        they were created; parallel branch emails at the same delay share a timing
        value. This is sufficient for FigJam label generation.
        """
        all_actions = self._paginate(
            f"/flows/{flow_id}/flow-actions/",
            params={"fields[flow-action]": "action_type,status,created,settings"},
        )
        all_actions.sort(key=lambda x: x["attributes"].get("created", ""))

        cumulative = 0
        timings: list[int] = []
        for action in all_actions:
            attrs = action.get("attributes", {})
            atype = attrs.get("action_type", "")
            settings = attrs.get("settings") or {}
            if atype == "TIME_DELAY":
                cumulative += settings.get("delay_seconds", 0)
            elif atype == "SEND_EMAIL":
                timings.append(cumulative)
        return timings

    @staticmethod
    def format_delay_label(seconds: int) -> str:
        """Convert a cumulative delay in seconds to a human-readable label.

        Examples: 0 → "Day 0", 3600 → "1h", 86400 → "Day 1", 90000 → "Day 1 · 1h".
        """
        if seconds == 0:
            return "Day 0"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        parts = []
        if days:
            parts.append(f"Day {days}")
        if hours:
            parts.append(f"{hours}h")
        elif mins and not days:
            parts.append(f"{mins}m")
        return " · ".join(parts)

    def get_flow_action_messages(self, flow_action_id: str) -> list[dict]:
        """Get messages for a flow action, fetching template HTML separately."""
        data = self._get(
            f"/flow-actions/{flow_action_id}/flow-messages/",
            params={"fields[flow-message]": "name,content,created,updated"},
        )
        if not data:
            return []

        messages = data.get("data", [])
        for msg in messages:
            tmpl_id = (
                (msg.get("relationships") or {})
                .get("template", {})
                .get("data", {})
                .get("id")
            )
            # Fetch template HTML separately (include=template not supported here)
            msg["_html"] = self.get_template(tmpl_id) or "" if tmpl_id else ""

        return messages

    def get_flow_message_html(self, flow_message_id: str) -> str | None:
        """Get HTML for a flow message via its linked template."""
        data = self._get(
            f"/flow-messages/{flow_message_id}/",
            params={"fields[template]": "html", "include": "template"},
        )
        if not data:
            return None

        for inc in data.get("included", []):
            if inc.get("type") == "template":
                html = inc.get("attributes", {}).get("html", "")
                if html:
                    return html
        return None

    def get_template(self, template_id: str) -> str | None:
        """Get HTML from a Klaviyo template."""
        data = self._get(
            f"/templates/{template_id}/",
            params={"fields[template]": "html"},
        )
        if not data:
            return None
        return data.get("data", {}).get("attributes", {}).get("html")

    # ------------------------------------------------------------------
    # Metrics & Analytics
    # ------------------------------------------------------------------

    def discover_metric_ids(self) -> dict[str, str]:
        """Find and cache metric IDs for standard email events + Placed Order.

        Returns mapping of metric name -> metric ID, e.g.:
            {"Received Email": "abc123", "Opened Email": "def456", ...}

        Also caches self._placed_order_metric_id (required for campaign-values-reports).
        """
        if self._metric_cache:
            return self._metric_cache

        # Fetch all metrics (no filter — 'contains' filter not supported by Klaviyo API)
        # Accounts typically have ~100-200 metrics; fetching all is fast and reliable
        all_metrics = self._paginate("/metrics/")

        look_for = METRIC_NAMES | {"Placed Order"}
        for metric in all_metrics:
            name = metric.get("attributes", {}).get("name", "")
            if name in look_for:
                self._metric_cache[name] = metric["id"]

        self._placed_order_metric_id = self._metric_cache.get("Placed Order")

        missing = METRIC_NAMES - set(self._metric_cache.keys())
        if missing:
            print(f"  [klaviyo:{self.brand}] Warning: metric IDs not found for: {missing}")
        if not self._placed_order_metric_id:
            # Use any available metric ID as a fallback (required field but doesn't affect basic stats)
            fallback = next((v for k, v in self._metric_cache.items() if v and k != "Placed Order"), None)
            if not fallback and all_metrics:
                # No known metric names matched — use the very first metric returned
                fallback = all_metrics[0].get("id")
                print(f"  [klaviyo:{self.brand}] No known metrics found — using first available metric as fallback")
            self._placed_order_metric_id = fallback
            if fallback:
                print(f"  [klaviyo:{self.brand}] 'Placed Order' metric not found — using fallback for analytics")

        return self._metric_cache

    def _get_metric_id(self, metric_name: str) -> str | None:
        """Resolve any metric name to its ID, not just the standard set
        discover_metric_ids() caches. Klaviyo's /metrics/ endpoint has no
        name filter, so the first miss fetches (and fully caches) every
        metric in the account; later lookups are free."""
        if metric_name in self._metric_cache:
            return self._metric_cache[metric_name]
        all_metrics = self._paginate("/metrics/")
        for metric in all_metrics:
            name = metric.get("attributes", {}).get("name", "")
            if name:
                self._metric_cache.setdefault(name, metric["id"])
        return self._metric_cache.get(metric_name)

    def get_daily_counts(self, metric_name: str, weeks: int = 5) -> list[dict]:
        """Day-bucketed event counts for `metric_name` over the trailing
        `weeks` weeks, via the Query Metric Aggregates endpoint
        (interval=day, measurements=[count]).

        Always excludes the current UTC day — it's necessarily a partial
        count (whatever fraction has landed so far), same rationale as the
        equivalent exclusion in scripts/utils/anomaly_detector.py for the
        Braze datashare. Confirmed live: a same-day bucket read mid-day
        showed ~1/3 of a normal day's volume purely because the day wasn't
        over yet.

        Returns a list of {"day": date, "cnt": int}, sorted ascending by
        day. Returns [] if the metric name isn't found in this account.
        """
        metric_id = self._get_metric_id(metric_name)
        if not metric_id:
            return []

        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(weeks=weeks)
        body = {
            "data": {
                "type": "metric-aggregate",
                "attributes": {
                    "metric_id": metric_id,
                    "measurements": ["count"],
                    "filter": [
                        f"greater-or-equal(datetime,{start.strftime('%Y-%m-%dT%H:%M:%S')})",
                        f"less-than(datetime,{end.strftime('%Y-%m-%dT%H:%M:%S')})",
                    ],
                    "interval": "day",
                    "timezone": "UTC",
                },
            }
        }
        resp = self._post("metric-aggregates", body)
        if not resp:
            return []

        attrs = resp["data"]["attributes"]
        dates = attrs.get("dates", [])
        series = attrs.get("data") or []
        counts = series[0]["measurements"]["count"] if series else []

        today = datetime.now(timezone.utc).date()
        result = []
        for date_str, cnt in zip(dates, counts):
            day = datetime.fromisoformat(date_str).date()
            if day < today:
                result.append({"day": day, "cnt": int(cnt)})
        return result

    def _empty_analytics(self) -> dict[str, Any]:
        """Return a zeroed performance_summary dict."""
        return {
            "total_sends": 0,
            "total_delivered": 0,
            "total_opens": 0,
            "total_clicks": 0,
            "unique_opens": 0,
            "unique_clicks": 0,
            "open_rate": 0.0,
            "click_rate": 0.0,
            "total_open_rate": 0.0,
            "total_click_rate": 0.0,
            "total_unsubscribes": 0,
            "total_bounces": 0,
        }

    def get_campaign_analytics_report(
        self,
        campaign_id: str,
        start_date: str = "2024-07-01",
        channel: str = "email",
    ) -> dict[str, Any]:
        """Fetch campaign performance via Klaviyo's campaign-values-reports endpoint.

        Args:
            campaign_id: Klaviyo campaign ID (not message ID)
            start_date: Earliest date to include, "YYYY-MM-DD" (default 2024-07-01)
            channel: "email" or "sms" — controls which statistics are requested

        Returns:
            Dict compatible with performance_summary YAML schema.
        """
        from datetime import datetime, timezone

        if not self._placed_order_metric_id:
            return self._empty_analytics()

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if channel == "sms":
            stats_full    = ["clicks", "clicks_unique", "recipients", "unsubscribes", "delivered"]
            stats_minimal = ["clicks", "clicks_unique", "recipients", "unsubscribes"]
        else:
            # Try with extended stats first; fall back to known-good minimal set if 400
            stats_full    = ["opens", "clicks", "opens_unique", "clicks_unique",
                             "recipients", "unsubscribes", "delivered", "bounced",
                             "spam_complaints"]
            stats_minimal = ["opens", "clicks", "opens_unique", "clicks_unique",
                             "recipients", "unsubscribes"]

        def _build_body(stats: list[str]) -> dict:
            return {
                "data": {
                    "type": "campaign-values-report",
                    "attributes": {
                        "statistics": stats,
                        "timeframe": {
                            "start": f"{start_date}T00:00:00+00:00",
                            "end": f"{end_date}T23:59:59+00:00",
                        },
                        "conversion_metric_id": self._placed_order_metric_id,
                        "filter": f'equals(campaign_id,"{campaign_id}")',
                    },
                }
            }

        result = self._post("/campaign-values-reports/", _build_body(stats_full))
        if result is None:
            # Extended stats may include invalid fields — retry with minimal set
            result = self._post("/campaign-values-reports/", _build_body(stats_minimal))

        if not result:
            return self._empty_analytics()

        # Response: data.attributes.results[] each has a "statistics" dict
        results = result.get("data", {}).get("attributes", {}).get("results", [])
        if not results:
            return self._empty_analytics()

        opens = clicks = unique_opens = unique_clicks = 0
        recipients = unsubscribes = delivered = bounced = 0
        for row in results:
            stats = row.get("statistics", {})
            opens += int(stats.get("opens", 0) or 0)
            clicks += int(stats.get("clicks", 0) or 0)
            unique_opens += int(stats.get("opens_unique", 0) or 0)
            unique_clicks += int(stats.get("clicks_unique", 0) or 0)
            recipients += int(stats.get("recipients", 0) or 0)
            unsubscribes += int(stats.get("unsubscribes", 0) or 0)
            delivered += int(stats.get("delivered", 0) or 0)
            bounced += int(stats.get("bounced", 0) or 0)

        sends = recipients
        return {
            "total_sends": sends,
            "total_delivered": delivered if delivered else sends,  # fall back to recipients
            "total_opens": opens,
            "total_clicks": clicks,
            "unique_opens": unique_opens,
            "unique_clicks": unique_clicks,
            "open_rate": round(unique_opens / sends, 4) if sends else 0.0,
            "click_rate": round(unique_clicks / sends, 4) if sends else 0.0,
            "total_open_rate": round(opens / sends, 4) if sends else 0.0,
            "total_click_rate": round(clicks / sends, 4) if sends else 0.0,
            "total_unsubscribes": unsubscribes,
            "total_bounces": bounced,
        }

    def get_all_campaign_analytics(
        self,
        start_date: str = "2024-07-01",
        end_date: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch analytics for ALL campaigns in a date range using timeframe queries.

        Unlike get_campaign_analytics_batch(), this sends NO campaign_id filter — Klaviyo
        returns metrics for every campaign sent in the window. Typically 1–2 API calls per
        year, vs ~22–44 batch calls. Dramatically more quota-efficient.

        Klaviyo enforces a 1-year max timeframe per request. Ranges exceeding 1 year are
        automatically split into annual windows and results are merged.

        Args:
            start_date: Start of range, "YYYY-MM-DD" (default: "2024-07-01")
            end_date: End of range, "YYYY-MM-DD" (default: today)

        Returns:
            Dict mapping campaign_id -> performance_summary dict (same shape as batch method).
        """
        from datetime import datetime, timezone, timedelta, date

        if not self._placed_order_metric_id:
            print(f"  [klaviyo:{self.brand}] No metric ID — cannot fetch analytics")
            return {}

        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Split the range into ≤1-year windows (Klaviyo API limit)
        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)
        windows: list[tuple[date, date]] = []
        window_start = start_dt
        while window_start < end_dt:
            # Advance by just under 1 year (364 days to stay safely under the limit)
            window_end = min(window_start + timedelta(days=364), end_dt)
            windows.append((window_start, window_end))
            window_start = window_end + timedelta(days=1)

        all_results: list[dict] = []

        for win_start, win_end in windows:
            print(f"  [klaviyo:{self.brand}] Querying window {win_start} to {win_end}...")
            window_results = self._fetch_analytics_window(
                str(win_start), str(win_end)
            )
            all_results.extend(window_results)

        print(f"  [klaviyo:{self.brand}] Total rows fetched: {len(all_results)}")
        return _aggregate_by_campaign(all_results)

    def _fetch_analytics_window(self, start_date: str, end_date: str) -> list[dict]:
        """Fetch all paginated result rows for a single timeframe window (≤1 year)."""
        body = {
            "data": {
                "type": "campaign-values-report",
                "attributes": {
                    "statistics": [
                        "opens", "clicks", "opens_unique", "clicks_unique",
                        "recipients", "unsubscribes", "delivered", "bounced",
                    ],
                    "timeframe": {
                        "start": f"{start_date}T00:00:00+00:00",
                        "end": f"{end_date}T23:59:59+00:00",
                    },
                    "conversion_metric_id": self._placed_order_metric_id,
                    # No "filter" field — returns ALL campaigns in the timeframe
                },
            }
        }

        all_results: list[dict] = []
        page_cursor: str | None = None
        page_num = 0
        url = f"{KLAVIYO_BASE_URL}/campaign-values-reports/"

        while True:
            page_num += 1
            params = {"page[cursor]": page_cursor} if page_cursor else None

            self._rate_limiter.acquire()
            result = None
            for attempt in range(5):
                try:
                    resp = requests.post(
                        url,
                        headers=self._headers(),
                        json=body,
                        params=params,
                        timeout=60,
                    )
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else 2 ** attempt
                        print(f"  [klaviyo:{self.brand}] rate limited (page {page_num}), waiting {wait:.0f}s...")
                        time.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        time.sleep(2 ** attempt)
                        continue
                    if 400 <= resp.status_code < 500:
                        try:
                            err = resp.json()
                        except Exception:
                            err = resp.text[:300]
                        print(f"  [klaviyo:{self.brand}] analytics error {resp.status_code}: {err}")
                        return all_results
                    resp.raise_for_status()
                    result = resp.json()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == 4:
                        print(f"  [klaviyo:{self.brand}] analytics request failed: {e}")
                        return all_results
                    time.sleep(2 ** attempt)

            if result is None:
                break

            attrs = result.get("data", {}).get("attributes", {})
            page_results = attrs.get("results", [])
            all_results.extend(page_results)

            page_cursor = attrs.get("page_cursor")
            print(f"    page {page_num}: {len(page_results)} rows ({len(all_results)} running total)")

            if not page_cursor:
                break

        return all_results

    def get_campaign_analytics_batch(
        self,
        campaign_ids: list[str],
        start_date: str = "2024-07-01",
        debug: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Fetch analytics for multiple campaigns in a single API call.

        Uses `any(campaign_id,[...])` filter to batch many campaigns into one request,
        dramatically reducing API quota consumption vs one-call-per-campaign.

        Args:
            campaign_ids: List of Klaviyo campaign IDs (up to ~100 per call is safe)
            start_date: Earliest date to include, "YYYY-MM-DD" (default 2024-07-01)
            debug: Print raw API response to inspect response structure

        Returns:
            Dict mapping campaign_id -> performance_summary dict.
            Campaigns with no data return zeroed analytics.
        """
        from datetime import datetime, timezone

        if not campaign_ids:
            return {}

        if not self._placed_order_metric_id:
            return {cid: self._empty_analytics() for cid in campaign_ids}

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ids_joined = '","'.join(campaign_ids)
        filter_str = f'any(campaign_id,["{ids_joined}"])'

        body = {
            "data": {
                "type": "campaign-values-report",
                "attributes": {
                    "statistics": [
                        "opens", "clicks", "opens_unique", "clicks_unique",
                        "recipients", "unsubscribes", "delivered", "bounced",
                    ],
                    "timeframe": {
                        "start": f"{start_date}T00:00:00+00:00",
                        "end": f"{end_date}T23:59:59+00:00",
                    },
                    "conversion_metric_id": self._placed_order_metric_id,
                    "filter": filter_str,
                }
            }
        }

        result = self._post("/campaign-values-reports/", body)

        if debug:
            import json
            print("[debug] batch response (first 3000 chars):")
            print(json.dumps(result, indent=2, default=str)[:3000] if result else "None")

        by_campaign: dict[str, dict[str, Any]] = {cid: self._empty_analytics() for cid in campaign_ids}

        if not result:
            return by_campaign

        results = result.get("data", {}).get("attributes", {}).get("results", [])
        for row in results:
            # grouping_keys is the standard Klaviyo field; fall back to top-level campaign_id
            gkeys = row.get("grouping_keys") or {}
            cid = gkeys.get("campaign_id") or row.get("campaign_id")
            if not cid or cid not in by_campaign:
                if debug and cid:
                    print(f"[debug] unrecognized campaign_id in response: {cid}")
                continue

            s = row.get("statistics", {})
            a = by_campaign[cid]
            a["total_opens"] += int(s.get("opens", 0) or 0)
            a["total_clicks"] += int(s.get("clicks", 0) or 0)
            a["unique_opens"] += int(s.get("opens_unique", 0) or 0)
            a["unique_clicks"] += int(s.get("clicks_unique", 0) or 0)
            a["total_sends"] += int(s.get("recipients", 0) or 0)
            a["total_delivered"] += int(s.get("delivered", 0) or 0)
            a["total_unsubscribes"] += int(s.get("unsubscribes", 0) or 0)
            a["total_bounces"] += int(s.get("bounced", 0) or 0)

        # Compute derived rates
        for cid, a in by_campaign.items():
            sends = a["total_sends"]
            a["open_rate"]        = round(a["unique_opens"] / sends, 4) if sends else 0.0
            a["click_rate"]       = round(a["unique_clicks"] / sends, 4) if sends else 0.0
            a["total_open_rate"]  = round(a["total_opens"] / sends, 4) if sends else 0.0
            a["total_click_rate"] = round(a["total_clicks"] / sends, 4) if sends else 0.0
            if not a["total_delivered"]:
                a["total_delivered"] = sends  # fallback

        return by_campaign

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def get_events(
        self,
        metric_id: str,
        limit: int = 20,
        sort: str = "-datetime",
    ) -> list[dict]:
        """Fetch individual event records for a metric, including full properties.

        Returns up to `limit` events, most recent first by default.
        Each record has: id, attributes.datetime, attributes.properties,
        attributes.event_properties (Klaviyo v2024-10-15 field name).
        """
        params = {
            "filter": f"equals(metric_id,\"{metric_id}\")",
            "fields[event]": "datetime,event_properties",
            "sort": sort,
            "page[size]": min(limit, 200),
        }
        results: list[dict] = []
        next_url: str | None = "/events/"
        is_first = True
        while next_url and len(results) < limit:
            if is_first:
                data = self._get(next_url, params=params)
                is_first = False
            else:
                data = self._get(next_url)
            if not data:
                break
            results.extend(data.get("data", []))
            next_url = (data.get("links") or {}).get("next")
        return results[:limit]

    # ------------------------------------------------------------------
    # Lists / Segments (read)
    # ------------------------------------------------------------------

    def find_list_or_segment_by_name(self, name: str) -> str | None:
        """Return the Klaviyo ID for a list or segment matching `name` (case-insensitive).

        Searches /api/lists/ first, then /api/segments/. Result is cached.
        Returns None if not found.
        """
        key = name.lower()
        if key in self._segment_cache:
            return self._segment_cache[key]

        for endpoint, field_key in (("/lists/", "list"), ("/segments/", "segment")):
            items = self._paginate(
                endpoint,
                params={f"fields[{field_key}]": "name"},
            )
            for item in items:
                item_name = (item.get("attributes") or {}).get("name", "")
                if item_name.lower() == key:
                    self._segment_cache[key] = item["id"]
                    return item["id"]

        return None

    def create_segment(self, name: str, condition_groups: list[dict]) -> str | None:
        """Create a new Klaviyo segment. `condition_groups` are OR'd together
        (conditions within a single group are AND'd) — same shape as the
        `definition.condition_groups` returned by GET /segments/{id}. Returns
        the new segment's ID, or None on failure.
        """
        body = {
            "data": {
                "type": "segment",
                "attributes": {
                    "name": name,
                    "definition": {"condition_groups": condition_groups},
                },
            }
        }
        result = self._post("/segments/", body)
        if not result:
            return None
        segment_id = result["data"]["id"]
        self._segment_cache[name.lower()] = segment_id
        return segment_id

    def get_list_member_emails(self, list_id: str) -> dict[str, str]:
        """Return {lowercased email: profile_id} for every current member of a list."""
        profiles = self._paginate(f"/lists/{list_id}/profiles/", params={"fields[profile]": "email"})
        members: dict[str, str] = {}
        for p in profiles:
            email = (p.get("attributes") or {}).get("email")
            if email:
                members[email.lower()] = p["id"]
        return members

    def get_segment_member_emails(self, segment_id: str) -> dict[str, str]:
        """Return {lowercased email: profile_id} for every current member of a segment.

        Mirrors get_list_member_emails but paginates /segments/{id}/profiles/ —
        segment membership is computed dynamically by Klaviyo, so this reflects
        live membership at call time.
        """
        profiles = self._paginate(f"/segments/{segment_id}/profiles/", params={"fields[profile]": "email"})
        members: dict[str, str] = {}
        for p in profiles:
            email = (p.get("attributes") or {}).get("email")
            if email:
                members[email.lower()] = p["id"]
        return members

    def bulk_import_profiles_to_list(self, list_id: str, profiles: list[dict], chunk_size: int = 5000) -> int:
        """Create/update profiles and add them to `list_id` via a bulk import job.

        `profiles` items: {"email": ..., "first_name": ..., "last_name": ...}.
        Returns the number of profiles submitted (job processing is async on Klaviyo's side).
        """
        submitted = 0
        for i in range(0, len(profiles), chunk_size):
            chunk = profiles[i:i + chunk_size]
            body = {
                "data": {
                    "type": "profile-bulk-import-job",
                    "attributes": {
                        "profiles": {
                            "data": [
                                {
                                    "type": "profile",
                                    "attributes": {
                                        "email": p["email"],
                                        "first_name": p.get("first_name") or "",
                                        "last_name": p.get("last_name") or "",
                                    },
                                }
                                for p in chunk
                            ]
                        }
                    },
                    "relationships": {
                        "lists": {
                            "data": [{"type": "list", "id": list_id}]
                        }
                    },
                }
            }
            result = self._post("/profile-bulk-import-jobs/", body)
            if result:
                submitted += len(chunk)
        return submitted

    def remove_profiles_from_list(self, list_id: str, profile_ids: list[str], chunk_size: int = 100) -> int:
        """Remove profiles from a list's membership (does not delete the profiles themselves)."""
        removed = 0
        for i in range(0, len(profile_ids), chunk_size):
            chunk = profile_ids[i:i + chunk_size]
            body = {"data": [{"type": "profile", "id": pid} for pid in chunk]}
            if self._delete(f"/lists/{list_id}/relationships/profiles/", body):
                removed += len(chunk)
        return removed

    @staticmethod
    def _extract_email_marketing_consent(subscriptions: dict | None) -> str:
        """Reduce a profile's `subscriptions` object to a single email-marketing
        consent state: 'SUBSCRIBED', 'UNSUBSCRIBED', or 'NEVER_SUBSCRIBED'.

        A global email suppression whose reason is an explicit opt-out
        (UNSUBSCRIBE / USER_SUPPRESSED) is treated as 'UNSUBSCRIBED' even if the
        raw consent string says otherwise, so we never re-subscribe someone who
        opted out.
        """
        if not subscriptions:
            return "NEVER_SUBSCRIBED"
        marketing = ((subscriptions.get("email") or {}).get("marketing")) or {}
        for supp in (marketing.get("suppression") or []):
            if (supp.get("reason") or "").upper() in ("UNSUBSCRIBE", "USER_SUPPRESSED"):
                return "UNSUBSCRIBED"
        return marketing.get("consent") or "NEVER_SUBSCRIBED"

    def get_email_marketing_consent(self, emails: list[str], chunk_size: int = 45) -> dict[str, str]:
        """Return {lowercased email: consent} for every input email that already
        exists as a profile. `consent` is one of 'SUBSCRIBED', 'UNSUBSCRIBED',
        'NEVER_SUBSCRIBED'. Emails with no matching profile are omitted — the
        caller should treat a missing email as a brand-new (never-subscribed)
        profile.
        """
        out: dict[str, str] = {}
        emails = [e for e in emails if e]
        for i in range(0, len(emails), chunk_size):
            chunk = emails[i:i + chunk_size]
            quoted = ",".join('"' + e.replace('"', "") + '"' for e in chunk)
            params = {
                "filter": f"any(email,[{quoted}])",
                "additional-fields[profile]": "subscriptions",
                "page[size]": 100,
            }
            for p in self._paginate("profiles/", params=params):
                attrs = p.get("attributes") or {}
                email = (attrs.get("email") or "").lower()
                if not email:
                    continue
                out[email] = self._extract_email_marketing_consent(attrs.get("subscriptions"))
        return out

    def bulk_subscribe_profiles_to_list(
        self,
        list_id: str,
        profiles: list[dict],
        custom_source: str = "HubSpot Trade sync",
        chunk_size: int = 100,
    ) -> int:
        """Set email-marketing consent = SUBSCRIBED for `profiles` on `list_id`.

        `profiles` items need at least {"email": ...}. On a single opt-in list
        this takes effect immediately (no confirmation email). This does NOT
        filter by prior consent — the caller must only pass profiles it intends
        to subscribe (see get_email_marketing_consent). Returns count submitted.
        """
        submitted = 0
        for i in range(0, len(profiles), chunk_size):
            chunk = profiles[i:i + chunk_size]
            body = {
                "data": {
                    "type": "profile-subscription-bulk-create-job",
                    "attributes": {
                        "custom_source": custom_source,
                        "profiles": {
                            "data": [
                                {
                                    "type": "profile",
                                    "attributes": {
                                        "email": p["email"],
                                        "subscriptions": {
                                            "email": {"marketing": {"consent": "SUBSCRIBED"}}
                                        },
                                    },
                                }
                                for p in chunk
                            ]
                        },
                    },
                    "relationships": {
                        "list": {"data": {"type": "list", "id": list_id}}
                    },
                }
            }
            if self._post_no_content("profile-subscription-bulk-create-jobs/", body):
                submitted += len(chunk)
        return submitted

    # ------------------------------------------------------------------
    # Campaigns (write)
    # ------------------------------------------------------------------

    def create_campaign(
        self,
        name: str,
        channel: str,
        included_ids: list[str],
        excluded_ids: list[str] | None = None,
        use_smart_sending: bool = False,
    ) -> str | None:
        """Create a Draft campaign with no send strategy (unscheduled).

        Args:
            name: Campaign name.
            channel: "sms" or "email".
            included_ids: List of Klaviyo list/segment IDs to include in the audience.
            excluded_ids: List of Klaviyo list/segment IDs to exclude. Defaults to [].
            use_smart_sending: Whether to enable smart sending. Defaults to True.

        Returns:
            New campaign ID string, or None on failure.
        """
        body = {
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": name,
                    "audiences": {
                        "included": included_ids,
                        "excluded": excluded_ids or [],
                    },
                    "send_options": {
                        "use_smart_sending": use_smart_sending,
                    },
                    "campaign-messages": {
                        "data": [
                            {
                                "type": "campaign-message",
                                "attributes": {
                                    "channel": channel,
                                    "label": name,
                                },
                            }
                        ]
                    },
                },
            }
        }
        result = self._post("/campaigns/", body)
        if not result:
            return None
        return (result.get("data") or {}).get("id")

    def clone_campaign(self, campaign_id: str) -> str | None:
        """Clone an existing campaign, preserving its template (including drag-and-drop).

        Returns the new campaign ID, or None on failure.
        """
        result = self._post(
            "/campaign-clone/",
            {"data": {"type": "campaign", "id": campaign_id}},
        )
        if not result:
            return None
        return (result.get("data") or {}).get("id")

    def update_campaign(
        self,
        campaign_id: str,
        name: str | None = None,
        included_ids: list[str] | None = None,
        excluded_ids: list[str] | None = None,
        retries: int = 5,
    ) -> bool:
        """PATCH a campaign's name and/or audience.

        Returns True on success.
        """
        attrs: dict = {}
        if name is not None:
            attrs["name"] = name
        if included_ids is not None or excluded_ids is not None:
            attrs["audiences"] = {
                "included": included_ids or [],
                "excluded": excluded_ids or [],
            }
        if not attrs:
            return True

        url = f"{KLAVIYO_BASE_URL}/campaigns/{campaign_id}/"
        payload = {
            "data": {
                "type": "campaign",
                "id": campaign_id,
                "attributes": attrs,
            }
        }
        self._rate_limiter.acquire()
        for attempt in range(retries):
            try:
                resp = requests.patch(url, headers=self._headers(), json=payload, timeout=30)
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code not in (200, 204):
                    print(f"  [klaviyo] PATCH campaign {campaign_id}: {resp.status_code} {resp.text[:300]}")
                    return False
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] PATCH {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def update_campaign_message_body(self, message_id: str, body_text: str, retries: int = 5) -> bool:
        """PATCH the body of an existing campaign message.

        Returns True on success.
        """
        url = f"{KLAVIYO_BASE_URL}/campaign-messages/{message_id}/"
        payload = {
            "data": {
                "type": "campaign-message",
                "id": message_id,
                "attributes": {
                    "content": {
                        "body": body_text,
                    },
                },
            }
        }
        self._rate_limiter.acquire()
        for attempt in range(retries):
            try:
                resp = requests.patch(url, headers=self._headers(), json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code not in (200, 204):
                    print(f"  [klaviyo] PATCH campaign-message {message_id}: {resp.status_code} {resp.text[:300]}")
                    return False
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] PATCH {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def find_image_by_name(self, name: str) -> str | None:
        """Look up an existing image in the Klaviyo library by exact name.

        Paginates through images (newest first via cursor) and matches by name.
        Returns the image_url of the first match, or None.
        """
        url = f"{KLAVIYO_BASE_URL}/images/"
        # Paginate up to 5 pages (100 images) — recently uploaded will be near the top
        for _ in range(5):
            self._rate_limiter.acquire()
            try:
                resp = requests.get(url, headers=self._headers(), timeout=15)
                if resp.status_code != 200:
                    return None
                body = resp.json()
                for item in body.get("data", []):
                    attrs = item.get("attributes") or {}
                    if attrs.get("name") == name:
                        img_url = attrs.get("image_url")
                        if img_url:
                            return img_url
                next_url = (body.get("links") or {}).get("next")
                if not next_url:
                    break
                url = next_url
            except Exception:
                break
        return None

    def upload_image_from_file(self, path: str, name: str) -> str | None:
        """Upload a local image file to Klaviyo's image library.

        Checks for an existing image with the same name first to avoid
        re-uploading (and hitting rate limits) when the file was already uploaded.

        Returns:
            Hosted image URL string (data.attributes.image_url), or None on failure.
        """
        existing = self.find_image_by_name(name)
        if existing:
            print(f"  [klaviyo] reusing existing image: {name}")
            return existing

        import mimetypes
        url = f"{KLAVIYO_BASE_URL}/images/"
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        self._rate_limiter.acquire()
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    url,
                    headers={k: v for k, v in self._headers().items() if k != "Content-Type"},
                    files={"file": (name, f, mime)},
                    timeout=60,
                )
            if resp.status_code in (200, 201):
                return (resp.json().get("data") or {}).get("attributes", {}).get("image_url")
            print(f"  [klaviyo] image upload failed ({resp.status_code}): {resp.text[:200]}")
            return None
        except Exception as e:
            print(f"  [klaviyo] image upload error: {e}")
            return None

    def create_email_template(self, name: str, html: str) -> str | None:
        """Create a Klaviyo email template with the given HTML body.

        Returns:
            New template ID string, or None on failure.
        """
        result = self._post(
            "/templates/",
            {
                "data": {
                    "type": "template",
                    "attributes": {
                        "name": name,
                        "html": html,
                        "editor_type": "CODE",
                    },
                }
            },
        )
        if not result:
            return None
        return (result.get("data") or {}).get("id")

    def assign_template_to_campaign_message(
        self, message_id: str, template_id: str, retries: int = 5
    ) -> bool:
        """Assign an existing template to a campaign message.

        Klaviyo clones the template internally and links the clone to the message.
        Returns True on success.
        """
        url = f"{KLAVIYO_BASE_URL}/campaign-message-assign-template/"
        payload = {
            "data": {
                "type": "campaign-message",
                "id": message_id,
                "relationships": {
                    "template": {
                        "data": {"type": "template", "id": template_id}
                    },
                },
            }
        }
        self._rate_limiter.acquire()
        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code not in (200, 201, 204):
                    print(f"  [klaviyo] assign-template {message_id}: {resp.status_code} {resp.text[:300]}")
                    return False
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] POST {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def update_campaign_message_content(
        self, message_id: str, content: dict, retries: int = 5
    ) -> bool:
        """PATCH email campaign message metadata fields (subject, preview_text,
        from_email, from_label, reply_to_email). Does NOT set the HTML body —
        use create_email_template + assign_template_to_campaign_message for that.

        Args:
            message_id: Klaviyo campaign message ID.
            content: Dict of content fields to update, e.g.
                {"subject": "...", "preview_text": "...",
                 "from_email": "...", "from_label": "...", "reply_to_email": "..."}

        Returns:
            True on success.
        """
        url = f"{KLAVIYO_BASE_URL}/campaign-messages/{message_id}/"
        payload = {
            "data": {
                "type": "campaign-message",
                "id": message_id,
                "attributes": {
                    "content": content,
                },
            }
        }
        self._rate_limiter.acquire()
        for attempt in range(retries):
            try:
                resp = requests.patch(url, headers=self._headers(), json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code not in (200, 204):
                    print(f"  [klaviyo] PATCH campaign-message content {message_id}: {resp.status_code} {resp.text[:300]}")
                    return False
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] PATCH {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def update_campaign_message_options(
        self, message_id: str, render_options: dict, retries: int = 5
    ) -> bool:
        """PATCH render_options on an existing campaign message.

        Args:
            message_id: Klaviyo campaign message ID.
            render_options: Dict of render option fields to update, e.g.
                {"add_opt_out_language": False, "shorten_links": True}

        Returns:
            True on success.
        """
        url = f"{KLAVIYO_BASE_URL}/campaign-messages/{message_id}/"
        payload = {
            "data": {
                "type": "campaign-message",
                "id": message_id,
                "attributes": {
                    "render_options": render_options,
                },
            }
        }
        self._rate_limiter.acquire()
        for attempt in range(retries):
            try:
                resp = requests.patch(url, headers=self._headers(), json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  [klaviyo] rate limited (attempt {attempt + 1}/{retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code not in (200, 204):
                    print(f"  [klaviyo] PATCH campaign-message options {message_id}: {resp.status_code} {resp.text[:300]}")
                    return False
                return True
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"  [klaviyo] PATCH {url} failed: {e}")
                    return False
                time.sleep(2 ** attempt)
        return False

    def get_all_flow_analytics(
        self,
        start_date: str = "2019-01-01",
        end_date: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch analytics for ALL flow messages in a date range.

        Uses /flow-values-reports/ endpoint grouped by flow_message_id.
        Klaviyo enforces a 1-year max timeframe; ranges exceeding 1 year are
        split into annual windows automatically.

        Args:
            start_date: Start of range "YYYY-MM-DD" (default: "2019-01-01" to catch all flows)
            end_date: End of range "YYYY-MM-DD" (default: today)

        Returns:
            Dict mapping flow_message_id -> performance_summary dict.
        """
        from datetime import datetime, timezone, timedelta, date

        if not self._placed_order_metric_id:
            print(f"  [klaviyo:{self.brand}] No metric ID — cannot fetch flow analytics")
            return {}

        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)
        windows: list[tuple[date, date]] = []
        window_start = start_dt
        while window_start < end_dt:
            window_end = min(window_start + timedelta(days=364), end_dt)
            windows.append((window_start, window_end))
            window_start = window_end + timedelta(days=1)

        all_results: list[dict] = []
        for win_start, win_end in windows:
            print(f"  [klaviyo:{self.brand}] Querying flow window {win_start} to {win_end}...")
            window_results = self._fetch_flow_analytics_window(str(win_start), str(win_end))
            all_results.extend(window_results)

        print(f"  [klaviyo:{self.brand}] Total flow rows fetched: {len(all_results)}")
        return _aggregate_by_flow_message(all_results)

    def _fetch_flow_analytics_window(self, start_date: str, end_date: str) -> list[dict]:
        """Fetch all paginated result rows for one flow analytics window (≤1 year)."""
        body = {
            "data": {
                "type": "flow-values-report",
                "attributes": {
                    "statistics": [
                        "opens", "clicks", "opens_unique", "clicks_unique",
                        "recipients", "unsubscribes", "delivered", "bounced",
                    ],
                    "timeframe": {
                        "start": f"{start_date}T00:00:00+00:00",
                        "end": f"{end_date}T23:59:59+00:00",
                    },
                    "conversion_metric_id": self._placed_order_metric_id,
                },
            }
        }

        all_results: list[dict] = []
        page_cursor: str | None = None
        page_num = 0
        url = f"{KLAVIYO_BASE_URL}/flow-values-reports/"

        while True:
            page_num += 1
            params = {"page[cursor]": page_cursor} if page_cursor else None

            self._rate_limiter.acquire()
            result = None
            for attempt in range(5):
                try:
                    resp = requests.post(
                        url,
                        headers=self._headers(),
                        json=body,
                        params=params,
                        timeout=60,
                    )
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else 2 ** attempt
                        print(f"  [klaviyo:{self.brand}] rate limited (page {page_num}), waiting {wait:.0f}s...")
                        time.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        time.sleep(2 ** attempt)
                        continue
                    if 400 <= resp.status_code < 500:
                        try:
                            err = resp.json()
                        except Exception:
                            err = resp.text[:300]
                        print(f"  [klaviyo:{self.brand}] flow analytics error {resp.status_code}: {err}")
                        return all_results
                    resp.raise_for_status()
                    result = resp.json()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == 4:
                        print(f"  [klaviyo:{self.brand}] flow analytics request failed: {e}")
                        return all_results
                    time.sleep(2 ** attempt)

            if result is None:
                break

            attrs = result.get("data", {}).get("attributes", {})
            page_results = attrs.get("results", [])
            all_results.extend(page_results)

            page_cursor = attrs.get("page_cursor")
            print(f"    page {page_num}: {len(page_results)} rows ({len(all_results)} running total)")

            if not page_cursor:
                break

        return all_results
