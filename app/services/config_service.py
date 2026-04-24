# app/services/config_service.py
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import Optional, List,Dict
from app.core.config import settings as app_settings
from app.core.logger import get_logger
from app.models.system_config import SystemConfig
from app.schemas.config_schema import SystemConfigCreate, SystemConfigUpdate
from fastapi import HTTPException, status

logger = get_logger(__name__)

class ConfigService:

    _cache:Dict[str,str] = {}
    _cache_ttl = 60

    @staticmethod
    async def create_config(db: AsyncSession, data: SystemConfigCreate) -> SystemConfig:
        stmt = select(SystemConfig).where(
            SystemConfig.tenant_id == data.tenant_id,
            SystemConfig.config_key == data.config_key
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="配置键已存在")
        config = SystemConfig(**data.dict())
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def get_config(db: AsyncSession, config_id: int) -> Optional[SystemConfig]:
        stmt = select(SystemConfig).where(SystemConfig.id == config_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_configs(db: AsyncSession, tenant_id: Optional[int] = None, skip: int = 0, limit: int = 100) -> List[SystemConfig]:
        stmt = select(SystemConfig)
        if tenant_id is not None:
            stmt = stmt.where(SystemConfig.tenant_id == tenant_id)
        stmt = stmt.offset(skip).limit(limit).order_by(SystemConfig.id)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def update_config(db: AsyncSession, config_id: int, data: SystemConfigUpdate) -> SystemConfig:
        config = await ConfigService.get_config(db, config_id)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        update_data = data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)
        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def delete_config(db: AsyncSession, config_id: int) -> bool:
        config = await ConfigService.get_config(db, config_id)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        await db.delete(config)
        await db.commit()
        return True

    @classmethod
    async def get_value(cls,db: AsyncSession, tenant_id: int, key: str, default: str = None) -> str:

        cache_key = f"{tenant_id}:{key}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        stmt = select(SystemConfig).where(
            SystemConfig.tenant_id == tenant_id,
            SystemConfig.config_key == key
        )

        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        value = config.config_value if config else default
        if value is not None:
            cls._cache[cache_key] = value
            asyncio.create_task(cls._expire_cache(cache_key))
        return value

    @classmethod
    async def _expire_cache(cls, cache_key: str):
        await asyncio.sleep(cls._cache_ttl)
        cls._cache.pop(cache_key, None)
