# app/schemas/chat_schema.py
from pydantic import BaseModel,Field
from typing import Optional,List,Dict,Any
from datetime import datetime


class ChatHistoryItem(BaseModel):
    id:int
    session_id:int
    message:str
    response:str
    created_at:datetime

    class Config:
        from_attributes = True

class ChatHistoryResponse(BaseModel):
    total:int
    items:List[ChatHistoryItem]

class ChatMessage(BaseModel):
    role:str
    content : str

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户当前输入的消息")
    stream: bool = Field(default=True, description="是否启用流式输出")
    session_id: Optional[int] = Field(None, description="会话 ID，为空则创建新会话")
    history: Optional[List[ChatMessage]] = Field(
        None,
        description="前端传入的对话历史（可选）。若提供，则后端不从数据库加载历史。"
    )

class ChatResponse(BaseModel):
    role:str ="assistant"
    content : str
    model: Optional[str] = None

class ChatSessionCreate(BaseModel):
    title: Optional[str] ="新会话"


class ChatSessionUpdate(BaseModel):
    title: str

class ChatSessionResponse(BaseModel):
    id:int
    user_id: int
    title: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

