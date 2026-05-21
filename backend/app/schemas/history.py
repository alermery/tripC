from datetime import datetime

from pydantic import BaseModel

class ChatHistoryItem(BaseModel):
    """前端历史会话列表的单条记录。"""
    id: int
    agent: str
    conversation_id: str
    conversation_started_at: datetime
    query: str
    reply: str
    created_at: datetime
