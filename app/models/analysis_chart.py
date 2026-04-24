# app/models/analysis_chart.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.database.base import Base

class AnalysisChart(Base):
    __tablename__ = "analysis_charts"

    id = Column(Integer, primary_key=True, index=True)
    query_task_id = Column(Integer, ForeignKey("query_tasks.id", ondelete="CASCADE"), nullable=False)
    chart_type = Column(String(50), nullable=True)  # bar, line, pie, etc.
    title = Column(String(255), nullable=True)
    config = Column(JSON, nullable=True)            # 完整图表配置
    image_base64 = Column(Text, nullable=False)     # Base64 图片

    created_at = Column(DateTime(timezone=True), server_default=func.now())