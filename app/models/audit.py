# app/models/audit.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, BigInteger
from sqlalchemy.sql import func
from app.database.base import Base

class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True,index=True)
    user_id = Column(Integer, ForeignKey('users.id'),nullable=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'),nullable=True)
    action = Column(String(50),nullable=False)
    details = Column(Text,nullable=True)
    ip_address = Column(String(50),nullable=True)
    user_agent = Column(Text,nullable=True)
    timestamp = Column(DateTime(timezone=True),server_default=func.now())