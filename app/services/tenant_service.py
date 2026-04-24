# app/services/tenant_service.py
from typing import Optional,List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis
from app.models.tenant import Tenant
from app.schemas.admin_schema import TenantCreate,TenantUpdate
from fastapi import HTTPException, status

class TenantService:
    @staticmethod
    async def create_tenant(db: AsyncSession, data: TenantCreate) -> Tenant:
        # 检查重名
        stmt = select(Tenant).where(Tenant.name == data.name)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="租户名称已存在")
        tenant = Tenant(name=data.name, description=data.description, is_active=True)
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        return tenant

    @staticmethod
    async def get_tenants(db: AsyncSession, skip: int = 0, limit: int = 50, active_only: bool = False) -> List[Tenant]:
        stmt = select(Tenant)
        if active_only:
            stmt = stmt.where(Tenant.is_active == True)
        stmt = stmt.offset(skip).limit(limit).order_by(Tenant.id)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_tenant(db: AsyncSession, tenant_id: int) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_tenant(
        db: AsyncSession,
        tenant_id: int,
        data: TenantUpdate,
        redis_client: Optional[Redis] = None,
    ) -> Tenant:
        tenant = await TenantService.get_tenant(db, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="租户不存在")
        update_data = data.dict(exclude_unset=True)
        if "name" in update_data:
            # 检查新名称是否与其他租户冲突
            stmt = select(Tenant).where(Tenant.name == update_data["name"], Tenant.id != tenant_id)
            result = await db.execute(stmt)
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="租户名称已被使用")
        for field, value in update_data.items():
            setattr(tenant, field, value)
        await db.commit()
        await db.refresh(tenant)

        if redis_client:
            await redis_client.delete(f"tenant:{tenant_id}")
        return tenant

    @staticmethod
    async def delete_tenant(
        db: AsyncSession,
        tenant_id: int,
        redis_client: Optional[Redis] = None,
    ) -> bool:
        tenant = await TenantService.get_tenant(db, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="租户不存在")
        # 注意：级联删除需由数据库外键处理，或手动清理关联数据
        await db.delete(tenant)
        await db.commit()

        if redis_client:
            await redis_client.delete(f"tenant:{tenant_id}")
        return True