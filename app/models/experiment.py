# app/models/experiment.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Float, ForeignKey, Text
from sqlalchemy.sql import func
from app.database.base import Base


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)

    # 分流配置，例如 {"group_a": 50, "group_b": 50}
    traffic_split = Column(JSON, nullable=False)

    # 各组的参数配置
    group_configs = Column(JSON, nullable=False)
    # 示例: {
    #   "group_a": {"retrieval_k": 5, "hybrid_weight": 0.7, "threshold": 0.5},
    #   "group_b": {"retrieval_k": 10, "hybrid_weight": 0.5, "threshold": 0.3}
    # }

    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    group_name = Column(String(50), nullable=False)  # 分配到的组别
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())


class ExperimentLog(Base):
    __tablename__ = "experiment_logs"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    group_name = Column(String(50), nullable=False)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    chat_history_id = Column(Integer, ForeignKey("chat_histories.id"), nullable=True)

    query_text = Column(Text, nullable=False)
    retrieval_config = Column(JSON, nullable=True)  # 实际使用的检索参数
    retrieval_results = Column(JSON, nullable=True)  # 检索结果快照
    answer_text = Column(Text, nullable=False)
    latency_ms = Column(Integer, nullable=True)  # 响应延迟

    created_at = Column(DateTime(timezone=True), server_default=func.now())