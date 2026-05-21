"""
统一的 HTTP 请求封装。
负责为第三方接口调用补齐超时、重试和统一 JSON 解析逻辑，减少各工具重复实现。
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from backend.app.config import settings

_SESSION_LOCK = threading.Lock()
_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    """返回进程内复用的 HTTP session。"""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=32, pool_maxsize=64)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            _SESSION = session
        return _SESSION


def request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """发送请求并返回 JSON 结果。

    当第三方接口偶发超时或连接失败时，按配置进行有限次重试。
    """
    last_exc: Exception | None = None
    attempts = max(1, int(settings.REQUEST_RETRY_COUNT))
    delay = max(0.0, float(settings.REQUEST_RETRY_BACKOFF))
    for index in range(attempts):
        try:
            resp = _get_session().request(
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
