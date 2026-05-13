"""Low-level helpers used by tool wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backend.app.config import settings
from backend.app.services.http_client import request_json

AMAP_API_KEY = settings.AMAP_API_KEY


def _geocode_first(address: str) -> Optional[dict[str, Any]]:
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


_city_codes_cache: Optional[pd.DataFrame] = None
CSV_PATH = str(Path(__file__).resolve().parent.parent / "data" / "city_code.csv")


def load_city_codes(csv_path: str = CSV_PATH) -> pd.DataFrame:
    global _city_codes_cache
    if _city_codes_cache is None:
        try:
            _city_codes_cache = pd.read_csv(csv_path)
        except FileNotFoundError:
            sample_data = {
                "城市代码": ["101010100", "101020100", "101280101", "101280601"],
                "城市名称": ["北京", "上海", "广州", "深圳"],
            }
            pd.DataFrame(sample_data).to_csv(csv_path, index=False)
            _city_codes_cache = pd.read_csv(csv_path)

    return _city_codes_cache


def find_city_code(city_name: str) -> str:
    df = load_city_codes()
    exact = df[df["城市名称"] == city_name]
    if not exact.empty:
        return str(exact.iloc[0]["城市代码"])

    for _, row in df.iterrows():
        csv_city = row["城市名称"]
        if csv_city.startswith(city_name) or csv_city.endswith(city_name) or city_name in csv_city:
            return str(row["城市代码"])
        if city_name.startswith(csv_city) or city_name.endswith(csv_city) or csv_city in city_name:
            return str(row["城市代码"])

    return city_name
