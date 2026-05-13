"""聊天历史接口。

返回当前登录用户最近的会话消息，供前端按 conversation_id 恢复历史会话。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db import get_db
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User
from backend.app.schemas.history import ChatHistoryItem

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[ChatHistoryItem])
def get_my_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatHistoryItem]:
    # 限制最近 100 条，避免历史接口一次返回过大的回复正文。
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        ChatHistoryItem(
            id=item.id,
            agent=item.agent,
            conversation_id=item.conversation_id,
            conversation_started_at=item.conversation_started_at,
            query=item.query,
            reply=item.reply,
            created_at=item.created_at,
        )
        for item in rows
    ]
