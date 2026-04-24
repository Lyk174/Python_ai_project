from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SystemConfigCreate(BaseModel):
    tenant_id: Optional[int] = 0  # 0 表示全局，其他数字表示租户专用
    config_key: str
    config_value: str
    description: Optional[str] = None
    is_encrypted: bool = False

class SystemConfigUpdate(BaseModel):
    config_value: Optional[str] = None
    description: Optional[str] = None
    is_encrypted: Optional[bool] = None

class SystemConfigResponse(BaseModel):
    id: int
    tenant_id: int
    config_key: str
    config_value: str
    description: Optional[str]
    is_encrypted: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True