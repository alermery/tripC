"""
应用主入口。
负责创建 FastAPI 应用、挂载路由、配置跨域策略，并在启动时完成基础表初始化与轻量迁移。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from backend.app import models as _models
from backend.app.api.auth import router as auth_router
from backend.app.api.history import router as history_router
from backend.app.api.location import router as location_router
from backend.app.api.rag_admin import router as rag_admin_router
from backend.app.api.ws import router as ws_router
from backend.app.config import settings
from backend.app.db import Base, SessionLocal, engine
from backend.app.models.user import User
from backend.app.security import hash_password

# 通过副作用导入注册全部 ORM 模型，避免 create_all 时漏表。
_ = _models

if not settings.JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY 未配置，服务拒绝启动")

cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]

app = FastAPI(
    title="XiaoC Assistant API",
    version="0.1.0",
    description="小C助手后端服务。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """提供最小健康检查，不访问数据库。"""
    return {"status": "ok"}


def _bootstrap_admin_user() -> None:
    """根据环境变量同步管理员账号。"""
    pwd = (settings.ADMIN_PASSWORD or "").strip()
    if not pwd:
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        if not user:
            db.add(
                User(
                    username=settings.ADMIN_USERNAME,
                    password_hash=hash_password(pwd),
                    is_admin=True,
                )
            )
        else:
            user.is_admin = True
            user.password_hash = hash_password(pwd)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def init_pg_tables() -> None:
    """在启动阶段补齐表结构与开发环境迁移。"""
    if settings.APP_ENV != "production":
        Base.metadata.create_all(bind=engine)

    existing_tables = set(inspect(engine).get_table_names())

    if "users" in existing_tables:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
                )
            )

    if settings.APP_ENV != "production" and "chat_messages" in existing_tables:
        # 这里只保留幂等的轻量迁移，避免开发环境反复启动时报错。
        dev_migrations = [
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(64)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_started_at TIMESTAMP",
            "UPDATE chat_messages SET conversation_id = ('legacy_' || id::text) WHERE conversation_id IS NULL",
            "UPDATE chat_messages SET conversation_started_at = created_at WHERE conversation_started_at IS NULL",
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_conversation_id ON chat_messages (conversation_id)",
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_user_created_at ON chat_messages (user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_user_agent_created_at ON chat_messages (user_id, agent, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_user_agent_conv_created_at ON chat_messages (user_id, agent, conversation_id, created_at DESC)",
        ]
        with engine.begin() as conn:
            for sql in dev_migrations:
                conn.execute(text(sql))

    _bootstrap_admin_user()


app.include_router(auth_router)
app.include_router(history_router)
app.include_router(location_router)
app.include_router(rag_admin_router)
app.include_router(ws_router)
