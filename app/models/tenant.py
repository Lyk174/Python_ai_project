# app/models/tenant.py
from sqlalchemy import Column,Integer,String,DateTime,Boolean
from sqlalchemy.sql import func
from app.database.base import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer,primary_key=True,index=True)
    name = Column(String(100),nullable=False,unique=True)
    description = Column(String(255))
    is_active = Column(Boolean,default=True)
    created_at = Column(DateTime(timezone=True),server_default=func.now())
    updated_at = Column(DateTime(timezone=True),onupdate=func.now())