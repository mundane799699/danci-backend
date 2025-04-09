from pydantic import BaseModel, EmailStr
from datetime import datetime, date

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
    word_id: int
    sent_at: datetime
    send_date: str
    created_at: datetime
    updated_at: datetime
    word: Word | None = None  # 关联的单词信息

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