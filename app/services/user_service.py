# app/services/user_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.models.user import User
from app.models.role import Role, UserRole
from fastapi import HTTPException, status

class UserService:
    @staticmethod
    async def get_users(
        db: AsyncSession,
        tenant_id: Optional[int] = None,
        is_superuser: bool = False,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[User], int]:
        """
        获取用户列表，支持按租户过滤，并预加载角色信息
        """
        # 预加载 roles -> role 关系
        stmt = select(User).options(selectinload(User.roles).selectinload(UserRole.role))
        count_stmt = select(func.count(User.id))

        if not is_superuser:
            stmt = stmt.where(User.tenant_id == tenant_id)
            count_stmt = count_stmt.where(User.tenant_id == tenant_id)
        elif tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)
            count_stmt = count_stmt.where(User.tenant_id == tenant_id)
        if search:
            stmt = stmt.where(User.username.contains(search))
            count_stmt = count_stmt.where(User.username.contains(search))

        total_result = await db.execute(count_stmt)
        total = total_result.scalar()

        stmt = stmt.offset(skip).limit(limit).order_by(User.id)
        result = await db.execute(stmt)
        users = result.scalars().all()
        return users, total

    @staticmethod
    async def set_user_status(
            db: AsyncSession,
            user_id: int,
            is_active: bool,
            current_user: User
    ) -> User:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if not current_user.is_superuser:
            if target_user.tenant_id != current_user.tenant_id:
                raise HTTPException(status_code=403, detail="无权操作其他租户用户")
            if target_user.is_superuser:
                raise HTTPException(status_code=403, detail="无权修改超级管理员状态")
            if target_user.id == current_user.id:
                raise HTTPException(status_code=403, detail="不能禁用自己")

        target_user.is_active = is_active
        await db.commit()

        # 重新查询，预加载 roles 关系
        stmt = select(User).options(selectinload(User.roles).selectinload(UserRole.role)).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def update_user_roles(
            db: AsyncSession,
            user_id: int,
            role_ids: List[int],
            current_user: User
    ) -> User:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if not current_user.is_superuser:
            if target_user.tenant_id != current_user.tenant_id:
                raise HTTPException(status_code=403, detail="无权操作其他租户用户")
            if target_user.is_superuser:
                raise HTTPException(status_code=403, detail="无权修改超级管理员角色")

        stmt = select(Role).where(Role.id.in_(role_ids))
        result = await db.execute(stmt)
        existing_roles = result.scalars().all()
        if len(existing_roles) != len(role_ids):
            raise HTTPException(status_code=400, detail="部分角色ID不存在")

        if not current_user.is_superuser:
            super_admin_role = next((r for r in existing_roles if r.name == "super_admin"), None)
            if super_admin_role:
                raise HTTPException(status_code=403, detail="无权分配超级管理员角色")

        # 删除旧角色
        stmt = select(UserRole).where(UserRole.user_id == user_id)
        result = await db.execute(stmt)
        old_roles = result.scalars().all()
        for ur in old_roles:
            await db.delete(ur)

        # 添加新角色
        for role_id in role_ids:
            user_role = UserRole(
                user_id=user_id,
                role_id=role_id,
                tenant_id=target_user.tenant_id
            )
            db.add(user_role)

        await db.commit()

        # 重新查询，预加载 roles 关系
        stmt = select(User).options(selectinload(User.roles).selectinload(UserRole.role)).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one()