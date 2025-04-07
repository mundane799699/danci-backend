from pydantic import BaseModel, EmailStr
from datetime import datetime

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

# 添加登录请求模型
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserSubscribeMailBase(BaseModel):
    email: str
    word_count: int
    send_time: str

class UserSubscribeMailCreate(UserSubscribeMailBase):
    pass

class UserSubscribeMail(UserSubscribeMailBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 