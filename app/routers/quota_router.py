# app/routers/quota_router.py
from fastapi import APIRouter, Depends,Request
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.quota_service import QuotaService
from app.schemas.quota_schema import QuotaInfo
from app.core.config import settings


router = APIRouter(prefix="/api/v1/quota", tags=["配额"])

@router.get("/me", response_model=QuotaInfo)
async def get_my_quota(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    redis_client =request.app.state.redis
    quota_service = QuotaService(redis_client)
    remaining = await quota_service.get_remaining_quota(current_user.id)
    return QuotaInfo(daily_remaining=remaining, max_per_conversation=settings.MAX_COST_PER_CONVERSATION)