import time
from langchain_core.tools import tool

@tool(description="旅游出行季节注意事项。")
def travel_season_tips(city: str) -> str:
    # 获取当前时间并提取月份
    current_time = time.strftime("%Y-%m-%d-%H-%M")
    month_str = current_time.split("-")[1]
    month = int(month_str)

    if month in [12, 1, 2]:
        season = "冬季"
    elif month in [3, 4, 5]:
        season = "春季"
    elif month in [6, 7, 8]:
        season = "夏季"
    elif month in [9, 10, 11]:
        season = "秋季"
    else:
        season = "未知"

    # 定义各季节的通用旅行注意事项
    season_tips = {
        "春季": "春季气候多变，昼夜温差大，请携带轻便外套；花粉较多，过敏体质者需注意防护；雨水增多，记得携带雨具。",
        "夏季": "夏季炎热多雨，注意防晒防暑降温，携带遮阳帽、太阳镜和防晒霜；多喝水补充水分；随身携带雨具以防突发降雨。",
        "秋季": "秋季天气干燥，注意补水保湿；昼夜温差较大，适当增减衣物；是旅游黄金季节，但游客较多，需提前规划行程。",
        "冬季": "冬季寒冷干燥，务必携带保暖衣物；注意防滑，特别是雪后路面；室内外温差大，适时调整着装避免感冒。"
    }

    # 获取对应季节的提示
    tips = season_tips.get(season, "请根据目的地实际天气情况准备相应物品，注意旅途安全。")

    return f"当前时间为：{current_time}，城市{city}的季节为{season}，需要注意事项有{tips}。"

@tool(description="旅游出行安全注意事项。")
def travel_safe_tips():
    return ("1.一定要规划好出行路线，不要盲目出行。 "
            "2.出行前注意查看当地天气情况。 "
            "3.女生应随身携带防身物品。 "
            "4.一定要选择安全性高的酒店，请勿贪图小便宜。 "
            "5.不要随便给陌生人开门，住酒店应放好阻门器，防止坏人强行进入。 "
            "6.随身携带贵重物品，以防丢失。 "
            "7.及时关注疫情动态，避免前往疫情区旅游。 "
            "8.景区游玩请配合防控要求。 "
            "9.旅行中请佩戴口罩，勤洗手，少在密闭空间下活动。")