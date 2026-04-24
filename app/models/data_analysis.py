# app/models/data_analysis.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.database.base import Base

class DataAnalysisTask(Base):
    __tablename__ = "data_analysis_tasks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)  # 服务器存储路径
    table_name = Column(String(100), nullable=True)  # 导入的临时表名

    chart_config = Column(JSON, nullable=True)  # 图表配置（类型、标题、轴等）
    chart_image = Column(Text, nullable=True)  # Base64 编码的图表图片

    status = Column(String(50), default="pending")  # pending, running, completed, failed


    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())