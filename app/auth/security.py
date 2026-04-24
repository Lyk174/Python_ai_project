# app/auth/security.py - 安全工具
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
# from passlib.context import CryptContext
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.user import User, get_password_hash,verify_password
from app.models.role import UserRole
from app.schemas.auth_schema import UserCreate, TokenData,UserProfileUpdate,PasswordUpdate

# pwd_context =CryptContext(schemes=["bcrypt"],deprecated="auto")
#
# def verify_password(plain_password:str, hashed_password:str) -> bool:
#     return pwd_context.verify(plain_password, hashed_password)

# 通过用户名或邮箱获取用户
async def get_user_by_username_or_email(db:AsyncSession,username_or_email:str) -> Optional[User]:
    stmt = select(User).where(User.username==username_or_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user
    stmt = select(User).where(User.email==username_or_email)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def authenticate_user(db:AsyncSession,username_or_email:str, password:str) -> Optional[User]:

    user = await get_user_by_username_or_email(db, username_or_email)
    if not user or not user.verify_password(password):
        return None
    return user

# 创建新用户
async def create_user_async(db:AsyncSession,user_data:UserCreate,tenant_id:int,role_id:int =None) -> User:
    stmt = select(User).where(
        (User.username==user_data.username) | (User.email==user_data.email)
    )
    result = await db.execute(stmt)

    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail ="用户名或邮箱已存在"
        )
    hashed_pw =get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_pw,
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(db_user)
    await db.flush()

    if role_id:
        user_role = UserRole(user_id=db_user.id,role_id=role_id,tenant_id=tenant_id)
        db.add(user_role)
    await db.commit()
    await db.refresh(db_user)
    return db_user


# 创建访问令牌
def create_access_token(data:dict,expire_delta:Optional[timedelta] =None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expire_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))

    to_encode.update({"exp":expire,"type":"access"})
    return jwt.encode(to_encode,settings.SECRET_KEY.get_secret_value(),algorithm=settings.ALGORITHM)

def create_refresh_token(data:dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp":expire,"type":"refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY.get_secret_value(), algorithm=settings.ALGORITHM)

# 验证令牌
def decode_token(token:str,expected_type:str ="access") -> TokenData:
    try:
        payload = jwt.decode(token,settings.SECRET_KEY.get_secret_value(),algorithms=[settings.ALGORITHM])
        if payload.get("type") != expected_type:
            raise JWTError
        username:str = payload.get("sub")
        if username is None:
            raise JWTError
        return TokenData(username=username)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def update_user_profile(
    db: AsyncSession,
    user: User,
    data: UserProfileUpdate
) -> User:
    # 如果需要修改敏感信息，验证原密码
    if (data.username or data.email) and not data.current_password:
        raise HTTPException(status_code=400, detail="修改用户名或邮箱需提供原密码")
    if data.current_password and not user.verify_password(data.current_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    # 检查用户名唯一性
    if data.username and data.username != user.username:
        stmt = select(User).where(User.username == data.username)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="用户名已被使用")
        user.username = data.username

    # 检查邮箱唯一性
    if data.email and data.email != user.email:
        stmt = select(User).where(User.email == data.email)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已被注册")
        user.email = data.email

    await db.commit()
    await db.refresh(user)
    return user

async def change_password(
    db: AsyncSession,
    user: User,
    data: PasswordUpdate
) -> None:
    if not user.verify_password(data.current_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
