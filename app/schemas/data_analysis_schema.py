#app/schemas/data_analysis_schema
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

class QueryRequest(BaseModel):
    query: str
    save_to_kb: bool = False

class TaskResponse(BaseModel):
    id: int
    filename: str
    query_text: Optional[str] = None
    generated_code: Optional[str] = None
    execution_result: Optional[Any] = None
    status: str   # 必须是 str，不是枚举
    error_detail: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True