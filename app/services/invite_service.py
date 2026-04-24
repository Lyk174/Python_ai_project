# app/services/invite_service.py
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.invite import InvitationCode
from fastapi import HTTPException, status

class InviteService:
    @staticmethod
    async def generate_code_async(db: AsyncSession, tenant_id: int, role_id: int, created_by: int, max_uses: int = 1, expire_days: int = 7) -> str:
        """生成邀请码"""
        code = secrets.token_urlsafe(16)
        expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
        invite = InvitationCode(
            code=code,
            tenant_id=tenant_id,
            role_id=role_id,
            created_by=created_by,
            max_uses=max_uses,
            expires_at=expires_at
        )
        db.add(invite)
        await db.commit()
        return code

    @staticmethod
    async def validate_code_async(db: AsyncSession, code: str) -> tuple[int, int]:
        """验证邀请码，返回 (tenant_id, role_id)"""
        stmt = select(InvitationCode).where(
            InvitationCode.code == code,
            InvitationCode.is_active == True,
            InvitationCode.expires_at > datetime.now(timezone.utc),
            InvitationCode.used_count < InvitationCode.max_uses
        )
        result = await db.execute(stmt)
        invite = result.scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=400, detail="邀请码无效或已过期")
        return invite.tenant_id, invite.role_id

    @staticmethod
    async def mark_used_async(db: AsyncSession, code: str):
        """增加使用次数"""
        stmt = select(InvitationCode).where(InvitationCode.code == code)
        result = await db.execute(stmt)
        invite = result.scalar_one_or_none()
        if invite:
            invite.used_count += 1
            if invite.used_count >= invite.max_uses:
                invite.is_active = False
            await db.commit()