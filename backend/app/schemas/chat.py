from typing import Literal

# 须与前端所选智能体一致；不再支持 auto，由用户显式选择。
AgentType = Literal["weather", "map", "planner"]
