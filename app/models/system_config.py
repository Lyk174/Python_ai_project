# app/models/system_config.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database.base import Base

class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)  # 0 表示全局配置
    config_key = Column(String(100), nullable=False)
    config_value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    is_encrypted = Column(Boolean, default=False)  # 敏感信息如密码标记为加密存储（实际应用中可加密）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())