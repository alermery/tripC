from datetime import datetime

from pydantic import BaseModel

class ChatHistoryItem(BaseModel):
    id: int
    agent: str
    conversation_id: str
    conversation_started_at: datetime
    query: str
    reply: str
    created_at: datetime