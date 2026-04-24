# app/models/invite.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database.base import Base

class InvitationCode(Base):
    __tablename__ = 'invitation_codes'

    id = Column(Integer, primary_key=True,index=True)
    code = Column(String(32),unique=True,nullable=False)
    tenant_id = Column(Integer,ForeignKey('tenants.id'),nullable=False)
    role_id = Column(Integer,ForeignKey('roles.id'),nullable=False)
    created_by = Column(Integer,ForeignKey('users.id'),nullable=False)
    max_uses = Column(Integer,default=1)
    used_count = Column(Integer,default=0)
    expires_at = Column(DateTime,nullable=False)
    is_active = Column(Boolean,default=True)
    created_at = Column(DateTime(timezone=True),server_default=func.now())

