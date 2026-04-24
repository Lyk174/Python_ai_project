# app/auth/dependencies.py - FastAPI依赖注入
import asyncio
import pickle
import uuid
from fastapi import Depends, HTTPException, status,Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from redis.asyncio import Redis
from app.core.config import settings
from app.auth.security import decode_token
from app.models.user import User
from app.models.tenant import Tenant
from app.database.session import get_db
from typing import List
from app.models.role import UserRole

security = HTTPBearer()

# 获取当前用户
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    token_data = decode_token(credentials.credentials,expected_type="access")
    stmt = select(User).options(
        selectinload(User.roles).selectinload(UserRole.role)
    ).where(User.username == token_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用"
        )
    return user

# Lua 脚本用于安全释放锁（仅当锁的值匹配时才删除）
RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def acquire_redis_lock(redis: Redis, lock_key: str, lock_value: str, ttl: int = 5) -> bool:
    """尝试获取分布式锁，返回是否成功"""
    return await redis.set(lock_key, lock_value, nx=True, ex=ttl)


async def release_redis_lock(redis: Redis, lock_key: str, lock_value: str) -> None:
    """释放分布式锁（仅当 value 匹配）"""
    await redis.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, lock_value)


async def get_current_tenant(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Tenant:
    redis: Redis = request.app.state.redis
    tenant_id = current_user.tenant_id
    cache_key = f"tenant:{tenant_id}"
    lock_key = f"tenant:lock:{tenant_id}"

    cached =await redis.get(cache_key)
    if cached:
        if  cached == b"__NULL__":
            raise HTTPException(status_code=403,detail="租户不存在或已停用")
        tenant = pickle.loads(cached)
        return await db.merge(tenant,load=False)

    lock_value = str(uuid.uuid4())
    lock_acquired = await acquire_redis_lock(redis, lock_key, lock_value)

    if lock_acquired:
        try:
            # 双重检查：获取锁后再次查询缓存
            cached = await redis.get(cache_key)
            if cached:
                if cached == b"__NULL__":
                    raise HTTPException(status_code=403, detail="租户不存在或已停用")
                tenant = pickle.loads(cached)
                return await db.merge(tenant, load=False)

            result = await db.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()

            if not tenant or not tenant.is_active:
                await redis.setex(cache_key, 60, b"__NULL__")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="租户不存在或已停用"
                )

            await redis.set(cache_key, pickle.dumps(tenant), ex=3600)
            return tenant
        finally:
            await release_redis_lock(redis, lock_key, lock_value)
    else:
        # 未获取到锁，等待一小段时间后重试读取缓存
        await asyncio.sleep(0.1)
        cached = await redis.get(cache_key)
        if cached:
            if cached == b"__NULL__":
                raise HTTPException(status_code=403, detail="租户不存在或已停用")
            tenant = pickle.loads(cached)
            return await db.merge(tenant, load=False)
        # 如果仍无缓存，则再次尝试（但为避免无限递归，直接查询数据库一次）
        result = await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            await redis.setex(cache_key, 60, b"__NULL__")
            raise HTTPException(status_code=403, detail="租户不存在或已停用")
        await redis.set(cache_key, pickle.dumps(tenant), ex=3600)
        return tenant

def require_roles(allowed_roles:List[str]):
    async def role_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        stmt = select(UserRole).where(UserRole.user_id == current_user.id).options(selectinload(UserRole.role))
        result = await db.execute(stmt)
        user_roles = result.scalars().all()
        role_names = [ur.role.name for ur in user_roles if ur.role]

        if "super_admin" in role_names:
            return current_user
        for role in allowed_roles:
            if role in role_names:
                return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )
    return role_checker



