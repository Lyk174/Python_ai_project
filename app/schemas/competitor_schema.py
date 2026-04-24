# app/schemas/competitor_schema.py
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from app.models.competitor_analysis import AnalysisStatus


class AnalysisRequest(BaseModel):
    url: Optional[str] = Field(None, description="公司官网 URL")
    description: Optional[str] = Field(None, description="公司描述（5-6 词）")
    search_engine: str = Field("perplexity", description="搜索引擎：perplexity 或 exa")


class AnalysisResponse(BaseModel):
    task_id: int
    status: AnalysisStatus
    message: str = "任务已提交，请稍后查询结果"


class TaskStatusResponse(BaseModel):
    id: int
    status: AnalysisStatus
    progress_message: Optional[str] = None
    competitor_urls: Optional[List[str]] = None
    extracted_data: Optional[List[Any]] = None
    analysis_report: Optional[str] = None
    error_detail: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True