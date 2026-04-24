# app/schemas/admin_schema
from pydantic import BaseModel, Field, field_validator
from typing import Optional,List
from datetime import datetime

from setuptools.command.setopt import option_base


class InviteCodeCreate(BaseModel):
    tenant_id: Optional[int] = None  # 超级管理员可指定，租户管理员自动使用自己的租户
    role_id: int
    max_uses: int = 1
    expire_days: int = 7

class RoleAssign(BaseModel):
    user_id: int
    role_id: int

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="租户名称")
    description: Optional[str] = Field(None, max_length=255, description="租户描述")

class TenantResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: Optional[bool]=Field(None,description="租户状态，True=启用")
    created_at: datetime
    updated_at: Optional[datetime]

    @field_validator('is_active',mode='before')
    @classmethod
    def coerce_none_to_false(cls,v):
        if v is None:
            return False
        return v

    class Config:
        from_attributes = True

class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

class UserRoleUpdate(BaseModel):
    role_ids: List[int] = Field(..., description="角色ID列表")