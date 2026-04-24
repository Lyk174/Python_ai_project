# app/schemas/auth_schema.py - 定义数据模型
from pydantic import BaseModel,EmailStr,Field
from pydantic.functional_validators import field_validator
from typing import Optional,List
from datetime import datetime

from app.schemas.user_schema import RoleInfo


class UserBase(BaseModel):
    username: str = Field(...,min_length=3,max_length=50,description="用户名")
    email: EmailStr = Field(...,description="邮箱地址")

class UserCreate(UserBase):
    password: str = Field(...,min_length=6,description="密码")

    @field_validator('password')
    @classmethod
    def check_password(cls,v):
        if len(v) < 6:
            raise ValueError('密码长度至少6位')
        if not any(c.isdigit() for c in v):
            raise ValueError('密码必须包含数字')
        if not any(c.isalnum() for c in v):
            raise ValueError('密码必须包含字母')
        return v

class UserLogin(BaseModel):
    username_or_email: str = Field(...,description="用户名或邮箱")
    password: str = Field(...,description="密码")
    mfa_code: Optional[str] = None

class RoleInfo(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True

class UserResponse(UserBase):
    id: int
    is_active: bool
    is_superuser: bool
    tenant_id: int
    tenant_name: Optional[str]=None
    roles:List[RoleInfo] = []
    created_at: datetime

    class Config:
        from_attributes =True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None

class MFASetupResponse(BaseModel):
    secret: str
    qrcode_base64: str

class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    current_password: Optional[str] = Field(None, description="修改密码或敏感信息时需提供原密码")

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

    @field_validator('new_password')
    @classmethod
    def check_password_strength(cls, v):
        if not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
            raise ValueError('密码必须包含字母和数字')
        return v

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, description="6位数字验证码")
    new_password: str = Field(..., min_length=6)

    @field_validator('new_password')
    @classmethod
    def check_password_strength(cls, v):
        if not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
            raise ValueError('密码必须包含字母和数字')
        return v

class LogoutRequest(BaseModel):
    refresh_token: str


