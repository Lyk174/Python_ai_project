# app/models/user.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
# from passlib.context import CryptContext
from app.database.base import Base
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
# 原 bcrypt 哈希
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
#
# class User(Base):
#     __tablename__ = "users"
#
#     id = Column(Integer, primary_key = True,index = True)
#     username = Column(String(50),unique=True,index=True,nullable = False)
#     email = Column(String(100),unique=True,index=True,nullable = False)
#     hashed_password = Column(String(255),nullable = True)
#     is_active = Column(Boolean,default=True)
#     is_superuser = Column(Boolean,default=False)
#
#     tenant_id = Column(Integer,ForeignKey("tenants.id"),nullable = False)
#
#     is_mfa_enabled = Column(Boolean,default=False)
#     mfa_secret = Column(String(32),nullable = True)
#
#     wechat_openid = Column(String(100),unique=True,nullable = True)
#     dingtalk_openid = Column(String(100),unique=True,nullable = True)
#
#     created_at = Column(DateTime(timezone=True),server_default=func.now())
#     updated_at = Column(DateTime(timezone=True),onupdate=func.now())
#
#     tenant = relationship("Tenant",backref="users")
#     roles = relationship("UserRole",back_populates="user",cascade="all, delete-orphan")
#     sessions = relationship("ChatSession",back_populates="user",cascade="all, delete-orphan")
#     chat_histories = relationship("ChatHistory",back_populates="user",cascade="all, delete-orphan")
#
#     def verify_password(self,plain_password:str) -> bool:
#         if not self.hashed_password:
#             return False
#         return pwd_context.verify(plain_password, self.hashed_password)
#
# def get_password_hash(password:str) -> str:
#     return pwd_context.hash(password)

ph = PasswordHasher(
    time_cost=2,
    memory_cost=102400,
    parallelism=8,
    hash_len=32,
    salt_len=16,
)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key = True,index = True)
    username = Column(String(50),unique=True,index=True,nullable = False)
    email = Column(String(100),unique=True,index=True,nullable = False)
    hashed_password = Column(String(255),nullable = True)
    is_active = Column(Boolean,default=True)
    is_superuser = Column(Boolean,default=False)

    tenant_id = Column(Integer,ForeignKey("tenants.id"),nullable = False)

    is_mfa_enabled = Column(Boolean,default=False)
    mfa_secret = Column(String(32),nullable = True)

    wechat_openid = Column(String(100),unique=True,nullable = True)
    dingtalk_openid = Column(String(100),unique=True,nullable = True)

    created_at = Column(DateTime(timezone=True),server_default=func.now())
    updated_at = Column(DateTime(timezone=True),onupdate=func.now())

    tenant = relationship("Tenant",backref="users")
    roles = relationship("UserRole",back_populates="user",cascade="all, delete-orphan")
    sessions = relationship("ChatSession",back_populates="user",cascade="all, delete-orphan")
    chat_histories = relationship("ChatHistory",back_populates="user",cascade="all, delete-orphan")

    def verify_password(self,plain_password:str) -> bool:
        if not self.hashed_password:
            return False
        return verify_password(plain_password, self.hashed_password)

def get_password_hash(password: str) -> str:
    return ph.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """兼容旧的 bcrypt 哈希"""
    if hashed_password.startswith("$2a$") or hashed_password.startswith("$2b$"):
        import bcrypt
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    try:
        ph.verify(hashed_password,plain_password)
        return True
    except VerificationError:
        return False











