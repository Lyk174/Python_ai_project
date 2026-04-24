from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.auth.dependencies import require_roles
from app.database.session import get_db
from app.schemas.config_schema import SystemConfigCreate, SystemConfigUpdate, SystemConfigResponse
from app.services.config_service import ConfigService

router = APIRouter(prefix="/api/v1/admin/configs", tags=["系统配置"])

@router.post("/", response_model=SystemConfigResponse)
async def create_config(
    data: SystemConfigCreate,
    _=Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    return await ConfigService.create_config(db, data)

@router.get("/", response_model=List[SystemConfigResponse])
async def list_configs(
    tenant_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    _=Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    return await ConfigService.get_configs(db, tenant_id, skip, limit)

@router.get("/{config_id}", response_model=SystemConfigResponse)
async def get_config(
    config_id: int,
    _=Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    config = await ConfigService.get_config(db, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    return config

@router.patch("/{config_id}", response_model=SystemConfigResponse)
async def update_config(
    config_id: int,
    data: SystemConfigUpdate,
    _=Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    return await ConfigService.update_config(db, config_id, data)

@router.delete("/{config_id}")
async def delete_config(
    config_id: int,
    _=Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    await ConfigService.delete_config(db, config_id)
    return {"message": "配置已删除"}