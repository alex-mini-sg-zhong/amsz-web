from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from app.core.config import get_settings
from app.domain.exceptions import NonRetryableTaskError, RetryableTaskError


class PolymarketClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.polymarket_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.polymarket_request_timeout_seconds

    def list_events_keyset(
        self,
        *,
        limit: int,
        after_cursor: str | None = None,
        closed: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if after_cursor:
            params["after_cursor"] = after_cursor
        if closed is not None:
            params["closed"] = str(closed).lower()
        return self._request_json("/events/keyset", params)

    def get_event_by_id(self, event_id: str) -> dict[str, Any]:
        return self._request_json(f"/events/{event_id}")

    def _request_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            query = parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"

        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - exercised via monkeypatch/tests at service layer
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429 or exc.code >= 500:
                raise RetryableTaskError(
                    f"Polymarket request failed with status {exc.code}: {detail}",
                    error_code="POLYMARKET_UPSTREAM_RETRYABLE",
                ) from exc
            raise NonRetryableTaskError(
                f"Polymarket request failed with status {exc.code}: {detail}",
                error_code="POLYMARKET_UPSTREAM_INVALID",
            ) from exc
        except error.URLError as exc:  # pragma: no cover - network not used in tests
            raise RetryableTaskError(
                f"Polymarket request failed: {exc}",
                error_code="POLYMARKET_NETWORK_ERROR",
            ) from exc

        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        raise NonRetryableTaskError(
            "Polymarket response is not a JSON object",
            error_code="POLYMARKET_INVALID_RESPONSE",
        )
