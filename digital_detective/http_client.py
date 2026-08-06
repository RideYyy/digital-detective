"""Rate-limited HTTP access shared by API and scraping providers."""

from __future__ import annotations

import email.utils
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import requests


class DataSourceError(RuntimeError):
    """A public data source could not return a usable response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RetryPolicy:
    attempts: int = 3
    timeout: float = 12.0
    min_interval: float = 1.0
    max_delay: float = 30.0


class HttpClient:
    """HTTP client with per-host pacing and bounded retries.

    HTTP 429 honors Retry-After. Temporary 5xx responses and connection
    failures use exponential backoff. A descriptive User-Agent is always sent.
    """

    def __init__(
        self,
        user_agent: str,
        policy: RetryPolicy | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or RetryPolicy()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}

    def _pace(self, url: str) -> None:
        host = urlsplit(url).netloc.casefold()
        previous = self._last_request.get(host)
        now = self._clock()
        if previous is not None:
            wait = self.policy.min_interval - (now - previous)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _retry_delay(self, response: requests.Response | None, attempt: int) -> float:
        if response is not None:
            header = response.headers.get("Retry-After")
            if header:
                try:
                    return min(float(header), self.policy.max_delay)
                except ValueError:
                    parsed = email.utils.parsedate_to_datetime(header)
                    if parsed:
                        return min(max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds()), self.policy.max_delay)
        return min(2.0**attempt, self.policy.max_delay)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(self.policy.attempts):
            self._pace(url)
            response: requests.Response | None = None
            try:
                response = self.session.get(url, timeout=self.policy.timeout, **kwargs)
                last_status = response.status_code
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt + 1 < self.policy.attempts:
                        self._sleep(self._retry_delay(response, attempt))
                        continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if response is not None and 400 <= response.status_code < 500 and response.status_code != 429:
                    break
                if attempt + 1 < self.policy.attempts:
                    self._sleep(self._retry_delay(response, attempt))
        raise DataSourceError(
            f"Request failed for {urlsplit(url).netloc}: {last_error}",
            status_code=last_status,
        ) from last_error

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.get(url, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataSourceError(f"Invalid JSON returned by {urlsplit(url).netloc}") from exc
        if not isinstance(payload, dict):
            raise DataSourceError(f"Unexpected JSON returned by {urlsplit(url).netloc}")
        return payload
