# app/schemas/feedback_schema.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class FeedbackTypeEnum(str, Enum):
    thumbs_up = "thumbs_up"
    thumbs_down = "thumbs_down"
    report = "report"


class FeedbackStatusEnum(str, Enum):
    pending = "pending"
    reviewed = "reviewed"
    resolved = "resolved"
    ignored = "ignored"


class FeedbackCreate(BaseModel):
    chat_history_id: int
    feedback_type: FeedbackTypeEnum
    reason: Optional[str] = None


class FeedbackUpdate(BaseModel):
    status: Optional[FeedbackStatusEnum] = None
    admin_note: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    session_id: Optional[int]
    chat_history_id: Optional[int]
    feedback_type: FeedbackTypeEnum
    reason: Optional[str]
    admin_note: Optional[str]
    status: FeedbackStatusEnum
    query_text: str
    answer_text: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class BlindSpotStats(BaseModel):
    id:int
    query_text: str
    normalized_query: str
    occurrence_count: int
    last_occurred_at: datetime


class BlindSpotListResponse(BaseModel):
    total: int
    items: List[BlindSpotStats]