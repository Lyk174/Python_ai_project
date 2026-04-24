# app/models/feedback.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base import Base
import enum


class FeedbackType(str, enum.Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    REPORT = "report"


class FeedbackStatus(str, enum.Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class UserFeedback(Base):
    __tablename__ = "user_feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    chat_history_id = Column(Integer, ForeignKey("chat_histories.id"), nullable=True)

    feedback_type = Column(Enum(FeedbackType), nullable=False)
    reason = Column(Text, nullable=True)  # 用户填写的具体原因
    admin_note = Column(Text, nullable=True)  # 管理员备注
    status = Column(Enum(FeedbackStatus), default=FeedbackStatus.PENDING)

    # 存储当时的检索结果快照（用于分析）
    retrieval_snapshot = Column(JSON, nullable=True)
    query_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", backref="feedbacks")
    session = relationship("ChatSession", backref="feedbacks")
    chat_history = relationship("ChatHistory", backref="feedbacks")