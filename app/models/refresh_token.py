# app/models/refresh_token.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database.base import Base

class RefreshToken(Base):
    __tablename__ = 'refresh_tokens'

    id = Column(Integer,primary_key=True,index=True)
    user_id = Column(Integer,ForeignKey('users.id'),nullable=False)
    token = Column(String(255),unique=True,nullable=False)
    expires_at = Column(DateTime,nullable=False)
    revoked = Column(Integer,default=0)
    created_at = Column(DateTime(timezone=True),server_default=func.now())
