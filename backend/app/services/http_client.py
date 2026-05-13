"""Shared HTTP helper with timeout and retry."""

from __future__ import annotations

import time
from typing import Any

import requests

from backend.app.config import settings


def request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    attempts = max(1, int(settings.REQUEST_RETRY_COUNT))
    delay = max(0.0, float(settings.REQUEST_RETRY_BACKOFF))
    for index in range(attempts):
        try:
            resp = requests.request(
                method,
                url,
                params=params,
                data=data,
                timeout=timeout or settings.REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if index + 1 < attempts:
                time.sleep(delay * (2**index))
    raise RuntimeError(str(last_exc) if last_exc else "request failed")
