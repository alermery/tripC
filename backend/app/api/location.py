"""
定位接口。
基于高德逆地理编码将经纬度转换为结构化地址和城市名，并使用 LRU 缓存降低重复调用。
"""

from functools import lru_cache
from fastapi import APIRouter, HTTPException, Query

from backend.app.config import settings
from backend.app.services.http_client import request_json

router = APIRouter(prefix="/location", tags=["location"])


@lru_cache(maxsize=512)
def _reverse_by_rounded_coord(lat_round: float, lon_round: float) -> dict[str, str]:
    # 坐标规整到 4 位小数后缓存，兼顾精度与调用成本。
    params = {
        "key": settings.AMAP_API_KEY,
        "location": f"{lon_round},{lat_round}",
        "extensions": "all",
        "output": "JSON",
    }
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/geocode/regeo",
        params=params,
    )
    if data.get("status") != "1":
        raise ValueError(data.get("info", "未知错误"))

    regeo = data.get("regeocode", {})
    comp = regeo.get("addressComponent", {})
    city = comp.get("city") or comp.get("province") or "未知城市"
    return {
        "address": regeo.get("formatted_address", "未知地址"),
        "city": city,
    }


@router.get("/reverse")
def reverse_geocode(
    latitude: float = Query(..., description="纬度"),
    longitude: float = Query(..., description="经度"),
) -> dict[str, str]:
    """返回当前位置的格式化地址和城市名。"""
    if not settings.AMAP_API_KEY:
        raise HTTPException(status_code=500, detail="未配置 AMAP_API_KEY")

    try:
        lat_round = round(latitude, 4)
        lon_round = round(longitude, 4)
        data = _reverse_by_rounded_coord(lat_round, lon_round)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"逆地理请求失败: {exc}") from exc
    return data
