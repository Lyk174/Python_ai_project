# app/models/competitor_analysis
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Enum
from sqlalchemy.sql import func
from app.database.base import Base
import enum

class AnalysisStatus(str, enum.Enum):
    PENDING = "pending"
    FETCHING_URLS = "fetching_urls"
    CRAWLING = "crawling"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"

class CompetitorAnalysisTask(Base):
    __tablename__ = "competitor_analysis_tasks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    input_url = Column(String(500), nullable=True)
    input_description = Column(Text, nullable=True)

    status = Column(Enum(AnalysisStatus), default=AnalysisStatus.PENDING)
    progress_message = Column(String(255), nullable=True)

    competitor_urls = Column(JSON, nullable=True)      # 发现的竞品 URL 列表
    extracted_data = Column(JSON, nullable=True)       # 爬取的结构化数据
    analysis_report = Column(Text, nullable=True)      # 最终分析报告

    error_detail = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())