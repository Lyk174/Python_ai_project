# app/routers/user_router.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.auth.dependencies import get_current_user, require_roles
from app.database.session import get_db
from app.models.user import User
from app.schemas.user_schema import UserListPage
from app.schemas.admin_schema import UserRoleUpdate
from app.services.user_service import UserService
from app.schemas.user_schema import UserListResponse
from app.models.tenant import Tenant

router = APIRouter(prefix="/api/v1/users", tags=["用户管理"])

@router.get("", response_model=UserListPage)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant_id: Optional[int] = Query(None, description="超级管理员可按租户过滤"),
    search: Optional[str] = Query(None,description="用户名模糊搜索"),
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户列表：
    - 租户管理员：仅返回本租户用户
    - 超级管理员：可返回所有租户用户，支持 tenant_id 过滤
    """
    is_superuser = current_user.is_superuser
    query_tenant_id = current_user.tenant_id if not is_superuser else tenant_id

    users, total = await UserService.get_users(
        db,
        tenant_id=query_tenant_id,
        is_superuser=is_superuser,
        search=search,
        skip=skip,
        limit=limit,
    )

    # 收集所有涉及的租户 ID，批量获取租户名称
    tenant_ids = {u.tenant_id for u in users}
    tenant_map = {}
    if tenant_ids:
        stmt = select(Tenant).where(Tenant.id.in_(tenant_ids))
        result = await db.execute(stmt)
        tenants = result.scalars().all()
        tenant_map = {t.id: t.name for t in tenants}

    items = []
    for u in users:
        # 提取角色信息：从 UserRole 关系中找到关联的 Role
        role_list = []
        for ur in u.roles:
            if ur.role:
                role_list.append({"id": ur.role.id, "name": ur.role.name})
        # 手动构建字典，避免 Pydantic 直接处理 SQLAlchemy 关联对象
        user_dict = {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "tenant_id": u.tenant_id,
            "tenant_name": tenant_map.get(u.tenant_id),
            "is_active": u.is_active,
            "is_superuser": u.is_superuser,
            "roles": role_list,
            "created_at": u.created_at,
        }
        items.append(UserListResponse(**user_dict))

    return UserListPage(total=total, items=items)

@router.patch("/{user_id}/status", response_model=UserListResponse)
async def toggle_user_status(
    user_id: int,
    is_active: bool = Query(..., description="true 启用，false 禁用"),
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """启用或禁用用户"""
    updated_user = await UserService.set_user_status(db, user_id, is_active, current_user)

    # 获取租户名称
    tenant_name = None
    if updated_user.tenant_id:
        stmt = select(Tenant).where(Tenant.id == updated_user.tenant_id)
        result = await db.execute(stmt)
        tenant = result.scalar_one_or_none()
        tenant_name = tenant.name if tenant else None

    # 提取角色信息
    role_list = []
    for ur in updated_user.roles:
        if ur.role:
            role_list.append({"id": ur.role.id, "name": ur.role.name})

    user_dict = {
        "id": updated_user.id,
        "username": updated_user.username,
        "email": updated_user.email,
        "tenant_id": updated_user.tenant_id,
        "tenant_name": tenant_name,
        "is_active": updated_user.is_active,
        "is_superuser": updated_user.is_superuser,
        "roles": role_list,
        "created_at": updated_user.created_at,
    }
    return UserListResponse(**user_dict)

@router.patch("/{user_id}/roles", response_model=UserListResponse)
async def update_user_roles(
    user_id: int,
    data: UserRoleUpdate,
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """修改用户角色（仅管理员）"""
    updated_user = await UserService.update_user_roles(db, user_id, data.role_ids, current_user)

    # 获取租户名称
    tenant_name = None
    if updated_user.tenant_id:
        stmt = select(Tenant).where(Tenant.id == updated_user.tenant_id)
        result = await db.execute(stmt)
        tenant = result.scalar_one_or_none()
        tenant_name = tenant.name if tenant else None

    # 提取角色信息
    role_list = []
    for ur in updated_user.roles:
        if ur.role:
            role_list.append({"id": ur.role.id, "name": ur.role.name})

    user_dict = {
        "id": updated_user.id,
        "username": updated_user.username,
        "email": updated_user.email,
        "tenant_id": updated_user.tenant_id,
        "tenant_name": tenant_name,
        "is_active": updated_user.is_active,
        "is_superuser": updated_user.is_superuser,
        "roles": role_list,
        "created_at": updated_user.created_at,
    }
    return UserListResponse(**user_dict)

@router.get("/me/switchable-tenants")
async def get_switchable_tenants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前超级管理员可切换的租户列表"""
    if not current_user.is_superuser:
        return []
    stmt = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.id)
    result = await db.execute(stmt)
    tenants = result.scalars().all()
    return [{"id": t.id, "name": t.name} for t in tenants]