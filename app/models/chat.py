# app/models/chat.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database.base import Base

class ChatHistory(Base):
    __tablename__ = "chat_histories"

    id = Column(Integer, primary_key = True,index = True)
    user_id = Column(Integer,ForeignKey("users.id"),nullable = False)
    tenant_id = Column(Integer,ForeignKey("tenants.id"),nullable = False)
    session_id = Column(Integer,ForeignKey("chat_sessions.id"),nullable = False)
    message = Column(Text,nullable = False)
    response = Column(Text,nullable = False)
    created_at = Column(DateTime,default=lambda: datetime.now(timezone.utc))

    user = relationship("User",back_populates="chat_histories")
    session = relationship("ChatSession",back_populates="messages")

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key = True,index = True)
    user_id = Column(Integer,ForeignKey("users.id"),nullable = False)
    tenant_id = Column(Integer,ForeignKey("tenants.id"),nullable = False)
    title = Column(String(100),default="新会话")
    is_deleted = Column(Boolean,default=False)
    created_at = Column(DateTime,default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime,default=lambda: datetime.now(timezone.utc),onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User",back_populates="sessions")
    messages = relationship("ChatHistory",back_populates="session",cascade="all, delete-orphan")