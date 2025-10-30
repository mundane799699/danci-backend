from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr


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
    user_id: str | None = None


# 添加登录请求模型
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserSubscribeMailBase(BaseModel):
    email: str
    mail_type: str = "word"  # word or quote
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


# 单词模型
class Word(BaseModel):
    id: int
    word: str
    content: str

    class Config:
        from_attributes = True


# 单词分页响应模型
class WordPaginationResponse(BaseModel):
    words: list[Word]
    total_count: int
    has_more: bool
    current_page: int
    page_size: int


# 单词邮件发送历史模型
class WordEmailHistory(BaseModel):
    id: int
    user_id: int
    sent_at: datetime
    send_date: str
    created_at: datetime
    updated_at: datetime
    words: list[Word] = []  # 关联的单词列表

    class Config:
        from_attributes = True


# 单词邮件发送历史分页响应模型
class WordEmailHistoryPaginationResponse(BaseModel):
    histories: list[WordEmailHistory]
    total_count: int
    has_more: bool
    current_page: int
    page_size: int


# 按日期分组的单词邮件历史记录
class GroupedWordEmailHistory(BaseModel):
    send_date: str
    words: list[Word]

    class Config:
        from_attributes = True


# 按日期分组的单词邮件历史记录分页响应模型
class GroupedWordEmailHistoryPaginationResponse(BaseModel):
    grouped_histories: list[GroupedWordEmailHistory]
    total_count: int
    has_more: bool
    current_page: int
    page_size: int


# 小红书计算xs的请求体模型
class XhsCalculateXsRequest(BaseModel):
    api: str
    a1: str
    params: dict[str, Any] | None = None


# 小红书xs计算响应模型
class XhsCalculateXsResponse(BaseModel):
    xs: str
    success: bool = True
