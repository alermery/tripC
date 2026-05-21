"""地图工具：封装高德地理编码、路线规划、周边检索和定位。"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from backend.app.config import settings
from backend.app.services.amap_route_service import driving_route_as_text
from backend.app.services.http_client import request_json
from backend.app.tools import NoTool

AMAP_API_KEY = settings.AMAP_API_KEY
_ERR = "[错误] "


def _nearby_typed_places(
    location_label: str,
    location_coord: str,
    radius: int,
    types: str,
    type_keywords: tuple[str, ...],
    noun: str,
) -> str:
    """按 POI 类型搜索指定坐标附近的酒店或餐饮。"""
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/place/around",
        params={
            "key": AMAP_API_KEY,
            "location": location_coord,
            "radius": radius,
            "types": types,
            "output": "JSON",
        },
    )
    if data.get("status") != "1":
        return f"{_ERR}API调用失败: {data.get('info', '未知错误')}"
    places = data.get("pois", [])
    if not places:
        return f"{_ERR}{location_label}附近{radius}米内未找到相关{noun}。"
    rows: list[str] = []
    for p in places:
        if any(kw in p.get("type", "") for kw in type_keywords):
            rows.append(f"- {p['name']} ({p['distance']}米)\n   地址: {p['address']}\n")
    if not rows:
        return f"{_ERR}{location_label}附近{radius}米内未找到相关{noun}。"
    return f"在{location_label}附近{radius}米内的{noun}:\n" + "\n".join(rows[:10])


@tool(description="地址转坐标（地理编码）。")
def geocode_address(address: str) -> str:
    """把地址转换成坐标说明。"""
    return NoTool.geocode_address(address)


@tool(description="市内驾车路线规划：输入起点、终点地点名（或经纬度），返回距离、耗时摘要。")
def route_plan(start: str, end: str, strategy: str = "0") -> str:
    """规划两个地点之间的市内驾车路线。"""
    return driving_route_as_text(start, end, strategy)


@tool(description="搜索附近指定半径内的住宿服务用于用户参考，仅推荐前三位。")
def nearby_hotels(location: str, radius: int = 5000) -> str:
    """搜索地点附近的住宿服务。"""
    coord = NoTool.geocode_lonlat(location)
    if not coord:
        return NoTool.geocode_address(location)
    return _nearby_typed_places(
        location,
        coord,
        radius,
        "住宿服务|宾馆酒店|旅馆客栈|度假村",
        ("住宿服务", "宾馆酒店", "旅馆客栈", "度假村"),
        "酒店住宿",
    )


@tool(description="搜索附近指定半径内的餐饮服务用于用户参考，仅推荐前三位。")
def nearby_restaurants(location: str, radius: int = 5000) -> str:
    """搜索地点附近的餐饮服务。"""
    coord = NoTool.geocode_lonlat(location)
    if not coord:
        return NoTool.geocode_address(location)
    return _nearby_typed_places(
        location,
        coord,
        radius,
        "餐饮服务|中餐厅|外国餐厅|快餐厅|茶座|咖啡厅",
        ("餐饮服务", "中餐厅", "外国餐厅", "快餐厅", "茶座", "咖啡厅"),
        "餐饮场所",
    )


@tool(description="取用户当前位置（浏览器坐标/IP/高德定位）。")
def get_user_location(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    ip_address: Optional[str] = None,
) -> str:
    """根据浏览器坐标、IP 或默认值返回用户位置。"""
    if latitude and longitude:
        return reverse_geocode(latitude, longitude)
    if ip_address:
        return ip_geolocation(ip_address)
    return simulate_location()


def reverse_geocode(lat: float, lon: float) -> str:
    """把经纬度逆解析为地址，并附带周边地点。"""
    data = request_json(
        "GET",
        "https://restapi.amap.com/v3/geocode/regeo",
        params={
            "key": AMAP_API_KEY,
            "location": f"{lon},{lat}",
            "extensions": "all",
            "output": "JSON",
        },
        timeout=5,
    )
    if data.get("status") == "1":
        regeo = data["regeocode"]
        address = regeo["formatted_address"]
        city = regeo["addressComponent"]["city"]
        nearby = NoTool.nearby_places(f"{lon},{lat}", 1000)
        return (
            f"**当前位置：{address}**\n\n"
            f"城市：{city}\n"
            f"附近酒店：\n{nearby}\n\n"
            f"**建议**：查一下{city}天气和酒店详情？"
        )
    return f"{_ERR}坐标解析失败"


def ip_geolocation(ip: str) -> str:
    """通过 IP 地址粗略定位城市和坐标。"""
    try:
        data = request_json(
            "GET",
            f"http://ip-api.com/json/{ip}",
            params={"fields": "city,regionName,country,lat,lon,status"},
        )
        if data["status"] == "success":
            return (
                f"**IP定位：{data['city']}, {data['regionName']}**\n"
                f"坐标：{data['lat']}, {data['lon']}"
            )
    except Exception:
        pass
    return f"{_ERR}IP定位失败"


def simulate_location() -> str:
    """在没有真实定位时返回默认位置提示。"""
    return "**默认位置：北京市朝阳区**\n请授权浏览器定位获取精确位置"
