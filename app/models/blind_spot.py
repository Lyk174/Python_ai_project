# app/models/blind_spot.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database.base import Base


class BlindSpotQuery(Base):
    __tablename__ = "blind_spot_queries"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    query_text = Column(Text, nullable=False)
    normalized_query = Column(String(500), nullable=False, index=True)  # 标准化后的查询词
    occurrence_count = Column(Integer, default=1)
    last_occurred_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_resolved = Column(Boolean, default=False)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())