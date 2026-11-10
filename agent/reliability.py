"""Reliable, journalled wrappers for external HTTP and LLM calls."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from support import journal

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
DELAYS = (0.5, 1.0)


def _path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or url


def _status_from_exception(exc: Exception) -> int | str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if status is not None else type(exc).__name__


def read_with_retry(url: str, params: dict | None = None,
                    headers: dict | None = None):
    """GET JSON with a five-second timeout and up to three attempts."""
    safe_params = dict(params or {})
    for attempt in range(1, 4):
        started = time.monotonic()
        try:
            response = requests.get(url, params=safe_params,
                                    headers=headers or {}, timeout=5)
            took = time.monotonic() - started
            journal.log_call("GET", _path(url), safe_params,
                             response.status_code, attempt, took)
            if response.ok:
                try:
                    return response.json()
                except ValueError:
                    return None
            if response.status_code != 429 and response.status_code < 500:
                return None
        except (requests.Timeout, requests.ConnectionError) as exc:
            took = time.monotonic() - started
            journal.log_call("GET", _path(url), safe_params,
                             "no_response", attempt, took)
        if attempt < 3:
            time.sleep(DELAYS[attempt - 1])
    return None


def write_with_check(url: str, payload: dict, request_id: str | None,
                     headers: dict | None = None):
    """POST JSON, retrying only when an idempotency key is present."""
    body = dict(payload)
    if request_id:
        body["request_id"] = request_id
    attempts = 3 if request_id else 1
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            response = requests.post(url, json=body, headers=headers or {},
                                     timeout=5)
            took = time.monotonic() - started
            journal.log_call("POST", _path(url), body,
                             response.status_code, attempt, took)
            if response.ok:
                try:
                    return response.json()
                except ValueError:
                    return None
            if response.status_code != 429 and response.status_code < 500:
                return None
        except (requests.Timeout, requests.ConnectionError) as exc:
            took = time.monotonic() - started
            journal.log_call("POST", _path(url), body,
                             "no_response", attempt, took)
        if attempt < attempts:
            time.sleep(DELAYS[attempt - 1])
    return None


def llm_with_retry(call):
    """Run a zero-argument LLM call, retrying rate limits and disconnects."""
    for attempt in range(1, 4):
        started = time.monotonic()
        try:
            result = call()
            journal.log_call("POST", "/chat/completions", {}, 200, attempt,
                             time.monotonic() - started)
            return result
        except Exception as exc:  # SDK exception classes vary by version.
            status = _status_from_exception(exc)
            journal.log_call("POST", "/chat/completions", {}, status, attempt,
                             time.monotonic() - started)
            retryable = status == 429 or isinstance(
                exc, (requests.Timeout, requests.ConnectionError)
            ) or status in {"APIConnectionError", "APITimeoutError", "RateLimitError"}
            if not retryable or attempt == 3:
                return None
            time.sleep(DELAYS[attempt - 1])
    return None
