"""Low-level helpers used by tool wrappers."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from backend.app.config import settings
from backend.app.services.http_client import request_json

AMAP_API_KEY = settings.AMAP_API_KEY


@lru_cache(maxsize=512)
def _geocode_first(address: str) -> Optional[dict[str, Any]]:
    address = (address or "").strip()
    if not address:
        return None
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/geocode/geo",
        params={"key": AMAP_API_KEY, "address": address, "output": "JSON"},
    )
    if data.get("status") != "1" or not data.get("geocodes"):
        return None
    return data["geocodes"][0]


def geocode_lonlat(address: str) -> Optional[str]:
    geo = _geocode_first(address)
    return str(geo["location"]) if geo else None


def geocode_address(address: str) -> str:
    geo = _geocode_first(address)
    if not geo:
        return f"[错误] 未找到 '{address}'"
    lonlat = geo["location"].split(",")
    return f"[位置] {geo['formatted_address']}\n经度:{lonlat[0]} 纬度:{lonlat[1]}"


def nearby_places(location: str, radius: int = 1000) -> str:
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/place/around",
        params={
            "key": AMAP_API_KEY,
            "location": location,
            "radius": radius,
            "sortrule": "distance",
            "output": "JSON",
        },
    )
    if data.get("status") != "1":
        return f"[错误] 周边检索失败: {data.get('info', '未知错误')}"

    pois = data.get("pois", [])
    if not pois:
        return "附近暂无可推荐地点"

    formatted = []
    for p in pois[:5]:
        formatted.append(f"- {p.get('name', '未知地点')}（{p.get('distance', '?')}米）")
    return "\n".join(formatted)


_city_codes_cache: Optional[tuple[tuple[str, str], ...]] = None
CSV_PATH = str(Path(__file__).resolve().parent.parent / "data" / "city_code.csv")


def load_city_codes(csv_path: str = CSV_PATH) -> tuple[tuple[str, str], ...]:
    global _city_codes_cache
    if _city_codes_cache is None:
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                _city_codes_cache = tuple(
                    (
                        str(row.get("城市代码") or "").strip(),
                        str(row.get("城市名称") or "").strip(),
                    )
                    for row in reader
                    if row.get("城市代码") and row.get("城市名称")
                )
        except FileNotFoundError:
            _city_codes_cache = (
                ("101010100", "北京"),
                ("101020100", "上海"),
                ("101280101", "广州"),
                ("101280601", "深圳"),
            )

    return _city_codes_cache


def find_city_code(city_name: str) -> str:
    return _find_city_code_cached((city_name or "").strip())


@lru_cache(maxsize=512)
def _find_city_code_cached(city_name: str) -> str:
    city_codes = load_city_codes()
    for code, csv_city in city_codes:
        if csv_city == city_name:
            return code

    for code, csv_city in city_codes:
        if csv_city.startswith(city_name) or csv_city.endswith(city_name) or city_name in csv_city:
            return code
        if city_name.startswith(csv_city) or city_name.endswith(csv_city) or csv_city in city_name:
            return code

    return city_name
