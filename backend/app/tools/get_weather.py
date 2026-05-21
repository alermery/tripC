from langchain_core.tools import tool
from backend.app.config import settings
from backend.app.tools import NoTool
from backend.app.services.http_client import request_json

QWEATHER_API_KEY = settings.QWEATHER_API_KEY
QWEATHER_HOST = settings.QWEATHER_HOST

@tool(description=(
        "和风 7 日预报：返回 1～7 天逐日天气。days 必须与用户行程天数一致（如「五日游」「玩 5 天」传 5）；"
        "用户未提天数时可传 7。城市用中文名。"
    ),
)
def qweather_forecast(city: str = "北京", days: int = 7) -> str:
    """调用和风天气接口，返回指定城市最多 7 天预报。"""
    if not QWEATHER_API_KEY:
        return "[错误] 配置错误：请设置 QWEATHER_API_KEY"

    nd = max(1, min(int(days), 7))

    location_code = NoTool.find_city_code(city)
    url = f"https://{QWEATHER_HOST}/v7/weather/7d"
    params = {"key": QWEATHER_API_KEY, "location": location_code}

    try:
        data = request_json("GET", url, params=params)

        if data.get("code") == "200":
            daily = data["daily"][:nd]
            forecast = f"**{city} {nd}天天气预报**（数据来源：和风天气）\n\n"

            for day in daily:
                date = day['fxDate']
                # 白天天气和温度。
                text_day = day['textDay']
                temp_max = day['tempMax']
                temp_min = day['tempMin']
                # 夜间天气。
                text_night = day['textNight']
                # 湿度、紫外线、降水概率。
                humidity = day.get('humidity', '—')
                uv_index = day.get('uvIndex', '—')
                precip = day.get('precip', '0')  # 降水量，单位为 mm。
                # 风向风力（白天）。
                wind_dir = day.get('windDirDay', '—')
                wind_scale = day.get('windScaleDay', '—')
                # 日出日落。
                sunrise = day.get('sunrise', '—')
                sunset = day.get('sunset', '—')

                forecast += (
                    f" {date}\n"
                    f" 白天：{text_day} {temp_max}°C / 夜间：{text_night} {temp_min}°C\n"
                    f" 湿度：{humidity}%  | 紫外线：{uv_index} | 降水：{precip}mm\n"
                    f" 风向：{wind_dir} {wind_scale}级\n"
                    f" 日出 {sunrise} 日落 {sunset}\n\n"
                )
            return forecast
        else:
            return f"[错误] 预报错误 [{data.get('code')}]: {data.get('message')}"

    except Exception as e:
        return f"[错误] 请求失败: {str(e)}"
