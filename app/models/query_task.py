# app/models/query_task.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON,Boolean
from sqlalchemy.sql import func
from app.database.base import Base


class QueryTask(Base):
    __tablename__ = "query_tasks"

    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("data_analysis_tasks.id", ondelete="CASCADE"), nullable=False)

    tenant_id = Column(Integer, nullable=False,index=True)
    save_to_kb = Column(Boolean, default=False)

    query_text = Column(Text, nullable=False)  # 用户输入的自然语言
    generated_code = Column(Text, nullable=True)  # LLM生成的Pandas代码
    execution_result = Column(JSON, nullable=True)  # 代码执行结果（表格数据）

    status = Column(String(50), default="pending")  # pending, running, completed, failed
    error_type = Column(String(50), nullable=True)  # syntax_error, runtime_error等
    error_detail = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())