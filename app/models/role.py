# app/models/role.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database.base import Base

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True,index=True)
    name = Column(String(50),unique=True,nullable=False)
    description = Column(String(255))
    is_system = Column(Boolean,default=False)
    created_at = Column(DateTime(timezone=True),server_default=func.now())

class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True,index=True)
    user_id = Column(Integer, ForeignKey("users.id"),nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"),nullable=False)
    tenant_id = Column(Integer,ForeignKey("tenants.id"),nullable=False)
    created_at = Column(DateTime(timezone=True),server_default=func.now())

    user = relationship("User",back_populates="roles")
    role = relationship("Role")




