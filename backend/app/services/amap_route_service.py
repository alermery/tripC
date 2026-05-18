"""
高德驾车路径规划。
地理编码 + 路线折线，供 REST API 与 LangChain 工具复用。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any
from backend.app.config import settings
from backend.app.services.http_client import request_json

_COORD_RE = re.compile(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$")
_GEOCODE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="amap-geocode")

def _require_key() -> str:
    key = settings.AMAP_API_KEY
    if not key:
        raise ValueError("未配置 AMAP_API_KEY")
    return key

# 将地址或「经度,纬度」解析为 (lng, lat, 展示名)。
@lru_cache(maxsize=512)
def resolve_location(text: str) -> tuple[float, float, str]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("地点不能为空")

    m = _COORD_RE.match(raw)
    if m:
        lng, lat = float(m.group(1)), float(m.group(2))
        return lng, lat, f"{lng},{lat}"

    key = _require_key()
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/geocode/geo",
        params={"key": key, "address": raw, "output": "JSON"},
        timeout=15,
    )
    if data.get("status") != "1" or not data.get("geocodes"):
        raise ValueError(f"无法解析地点：{raw}（{data.get('info', '未知错误')}）")

    geo = data["geocodes"][0]
    lonlat = geo["location"].split(",")
    lng, lat = float(lonlat[0]), float(lonlat[1])
    name = geo.get("formatted_address") or raw
    return lng, lat, name

def _points_from_polyline_string(pl: str) -> list[list[float]]:
    pts: list[list[float]] = []
    for seg in (pl or "").split(";"):
        seg = seg.strip()
        if not seg or "," not in seg:
            continue
        try:
            lng_s, lat_s = seg.split(",", 1)
            pts.append([float(lng_s), float(lat_s)])
        except ValueError:
            continue
    return pts

def _parse_route_polylines(route: dict[str, Any]) -> list[list[float]]:
    points: list[list[float]] = []
    for step in route.get("steps") or []:
        pl = step.get("polyline") or ""
        points.extend(_points_from_polyline_string(pl))
    if points:
        return points
    # 部分返回在 path 层级带整段 polyline
    top = route.get("polyline")
    if isinstance(top, str) and top.strip():
        return _points_from_polyline_string(top)
    return []

# 调用高德驾车路径规划，返回前端可用的折线与概要。
def compute_driving_route(origin: str, destination: str, strategy: str = "0",) -> dict[str, Any]:
    if origin == destination:
        olng, olat, oname = resolve_location(origin)
        dlng, dlat, dname = olng, olat, oname
    else:
        origin_future = _GEOCODE_POOL.submit(resolve_location, origin)
        destination_future = _GEOCODE_POOL.submit(resolve_location, destination)
        olng, olat, oname = origin_future.result()
        dlng, dlat, dname = destination_future.result()

    key = _require_key()
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/direction/driving",
        params={
            "key": key,
            "origin": f"{olng},{olat}",
            "destination": f"{dlng},{dlat}",
            "strategy": str(strategy or "0"),
            "extensions": "all",
            "output": "JSON",
        },
        timeout=20,
    )
    if data.get("status") != "1":
        raise ValueError(data.get("info") or "路径规划失败")

    route_block = data.get("route") or {}
    routes = route_block.get("routes") or route_block.get("paths") or []
    if not routes:
        raise ValueError("未返回任何路线")

    route0 = routes[0]
    poly = _parse_route_polylines(route0)
    if not poly:
        raise ValueError("路线无坐标数据")

    dist = int(route0.get("distance", 0) or 0)
    dur = int(route0.get("duration", 0) or 0)

    return {
        "origin": {"lng": olng, "lat": olat, "name": oname},
        "destination": {"lng": dlng, "lat": dlat, "name": dname},
        "distance_m": dist,
        "duration_s": dur,
        "polyline": poly,
        "strategy": str(strategy or "0"),
    }

# 供 LangChain 工具返回可读文本。
def driving_route_as_text(start: str, end: str, strategy: str = "0") -> str:
    try:
        r = compute_driving_route(start, end, strategy)
        km = r["distance_m"] / 1000
        mins = r["duration_s"] // 60
        return (
            f"**市内驾车路线**：{r['origin']['name']} → {r['destination']['name']}\n"
            f"约 **{km:.1f} km**，预计 **{mins} 分钟**（高德 Web 服务驾车规划）。"
        )
    except ValueError as e:
        return f"[错误] {e}"
    except Exception as e:
        return f"[错误] 路线规划异常：{e}"
