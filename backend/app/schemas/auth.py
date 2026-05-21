from pydantic import BaseModel, Field

class UserRegisterRequest(BaseModel):
    """普通用户注册请求。"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)

class UserLoginRequest(BaseModel):
    """普通或管理员登录请求。"""
    username: str
    password: str

class TokenResponse(BaseModel):
    """登录成功后返回的访问令牌。"""
    access_token: str
    token_type: str = "bearer"
