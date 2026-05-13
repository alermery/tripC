"""密码哈希与 JWT 编解码。

负责登录令牌签发、受保护路由的 `sub` 解析，以及管理员 `role` 字段写入。
"""

from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from backend.app.config import settings

# 统一密码哈希方案。
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    """对明文密码做单向哈希，仅保存哈希值。"""
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    """校验登录密码是否匹配数据库中的哈希。"""
    return pwd_context.verify(password, password_hash)

def create_access_token(subject: str, *, role: str | None = None) -> str:
    """签发访问令牌，`role` 仅在管理员登录时写入。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {"sub": subject, "exp": expire}
    if role:
        payload["role"] = role
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_token_payload(token: str) -> dict | None:
    """校验签名与过期时间，失败时返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

def decode_access_token(token: str) -> str | None:
    """从合法 JWT 中提取用户名。"""
    payload = decode_token_payload(token)
    if not payload:
        return None
    return payload.get("sub")
