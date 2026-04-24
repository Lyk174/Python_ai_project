# app/routers/admin_router.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query,Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from starlette import status
from app.auth.dependencies import get_current_user, require_roles
from app.database.session import get_db
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role import Role, UserRole
from app.models.audit import AuditLog
from app.models.invite import InvitationCode
from app.services.invite_service import InviteService
from app.schemas.admin_schema import InviteCodeCreate, RoleAssign
from app.schemas.admin_schema import TenantCreate, TenantResponse, TenantUpdate
from app.services.tenant_service import TenantService


router = APIRouter(prefix="/api/v1/admin", tags=["管理"])

@router.post("/tenants", response_model=TenantResponse)
async def create_tenant(
    data: TenantCreate,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    tenant = await TenantService.create_tenant(db, data)
    return tenant

@router.get("/tenants", response_model=List[TenantResponse])
async def list_tenants(
    skip: int = 0,
    limit: int = 50,
    active_only: bool = False,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    """获取租户列表（仅超级管理员）"""
    tenants = await TenantService.get_tenants(db, skip, limit, active_only)
    return tenants

@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: int,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    """获取单个租户详情（仅超级管理员）"""
    tenant = await TenantService.get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")
    return tenant

@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    request: Request,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    """更新租户信息（仅超级管理员）"""
    redis_client = request.app.state.redis
    tenant = await TenantService.update_tenant(db, tenant_id, data,redis_client)
    return tenant

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: int,
    request: Request,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    """删除租户（仅超级管理员）"""
    redis_client = request.app.state.redis
    await TenantService.delete_tenant(db, tenant_id,redis_client)
    return {"message": f"租户 {tenant_id} 已删除"}

@router.post("/invite-code")
async def create_invite_code(
    data: InviteCodeCreate,
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    if current_user.is_superuser:
        if not data.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="超级管理员必须提供 tenant_id 参数"
            )
        tenant_id = data.tenant_id
    else:
        tenant_id = current_user.tenant_id
    code = await InviteService.generate_code_async(
        db, tenant_id, data.role_id, current_user.id,
        data.max_uses, data.expire_days
    )
    return {"invite_code": code}

@router.get("/audit-logs")
async def get_audit_logs(
    skip: int = 0,
    limit: int = 100,
    user_id: int = None,
    action: str = None,
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AuditLog)
    if not current_user.is_superuser:
        stmt = stmt.where(AuditLog.tenant_id == current_user.tenant_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.contains(action))
    total = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total_count = total.scalar()
    stmt = stmt.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return {"total": total_count, "items": logs}