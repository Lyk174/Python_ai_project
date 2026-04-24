# app/schemas/user_schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class RoleInfo(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    id: int
    username: str
    email: str
    tenant_id: int
    tenant_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    roles: List[RoleInfo] = []
    created_at: datetime

    class Config:
        from_attributes = True

class UserListPage(BaseModel):
    total: int
    items: List[UserListResponse]