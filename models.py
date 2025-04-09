from sqlalchemy import Boolean, Column, Integer, String, DateTime, text, Text, Date
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = {
        'comment': '用户表'
    }

    id = Column(Integer, primary_key=True, index=True, comment='用户ID')
    username = Column(String(50), index=True, comment='用户名')
    email = Column(String(100), unique=True, index=True, comment='邮箱')
    hashed_password = Column(String(100), comment='加密后的密码')
    is_active = Column(Boolean, default=True, comment='是否激活')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间')

class UserSubscribeMail(Base):
    __tablename__ = "user_subscribe_mail"
    __table_args__ = {
        'comment': '用户订阅邮箱表'
    }

    id = Column(Integer, primary_key=True, index=True, comment='设置ID')
    user_id = Column(Integer, unique=True, comment='用户ID')
    email = Column(String(100), unique=True, comment='订阅邮箱地址')
    word_count = Column(Integer, default=5, comment='每封邮件的单词数量')
    send_time = Column(String(5), default='09:00', comment='邮件发送时间，格式为HH:MM')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间')

class Word(Base):
    __tablename__ = "words"
    __table_args__ = {
        'comment': '单词表'
    }

    id = Column(Integer, primary_key=True, index=True, comment='单词ID')
    word = Column(String(100), unique=True, nullable=False, comment='单词')
    content = Column(Text, nullable=False, comment='单词详细内容')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间')

class WordEmailHistory(Base):
    __tablename__ = "word_email_history"
    __table_args__ = {
        'comment': '单词邮件发送历史表'
    }

    id = Column(Integer, primary_key=True, index=True, comment='历史记录ID')
    user_id = Column(Integer, comment='用户ID')
    word_id = Column(Integer, comment='单词ID')
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), comment='发送时间')
    send_date = Column(String(10), default=func.date(func.now()), comment='发送日期')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间') 