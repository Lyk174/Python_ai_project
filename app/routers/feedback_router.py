# app/routers/feedback_router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.auth.dependencies import get_current_user, require_roles
from app.database.session import get_db
from app.models.user import User
from app.schemas.feedback_schema import (
    FeedbackCreate, FeedbackUpdate, FeedbackResponse,
    BlindSpotStats, BlindSpotListResponse
)
from app.services.feedback_service import FeedbackService, BlindSpotService
from app.services.rag_service import rag_service

router = APIRouter(prefix="/api/v1/feedback", tags=["反馈与评估"])


@router.post("", response_model=FeedbackResponse)
@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    data: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户提交点赞/点踩反馈"""
    # 可以在这里获取当时的检索快照（从缓存或数据库）
    retrieval_snapshot = None
    try:
        feedback = await FeedbackService.create_feedback(
            db, current_user.id, current_user.tenant_id, data, retrieval_snapshot
        )
        return feedback
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list", response_model=list[FeedbackResponse])
async def list_feedbacks(
    skip: int = 0,
    limit: int = 50,
    feedback_type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """管理员查看反馈列表"""
    items = await FeedbackService.list_feedbacks(
        db, current_user.tenant_id, skip, limit, feedback_type, status
    )
    return items


@router.patch("/{feedback_id}", response_model=FeedbackResponse)
async def update_feedback(
    feedback_id: int,
    data: FeedbackUpdate,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """管理员更新反馈状态/备注"""
    feedback = await FeedbackService.update_feedback(
        db, feedback_id, current_user.tenant_id, data
    )
    if not feedback:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return feedback


@router.get("/blind-spots", response_model=BlindSpotListResponse)
async def get_blind_spots(
    limit: int = 20,
    min_occurrence: int = 1,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """获取召回盲区列表（高频未命中问题）"""
    items = await BlindSpotService.get_top_blind_spots(
        db, current_user.tenant_id, limit, min_occurrence
    )
    stats = [
        BlindSpotStats(
            id=item.id,
            query_text=item.query_text,
            normalized_query=item.normalized_query,
            occurrence_count=item.occurrence_count,
            last_occurred_at=item.last_occurred_at,
        )
        for item in items
    ]
    return BlindSpotListResponse(total=len(stats), items=stats)


@router.post("/blind-spots/{spot_id}/resolve")
async def resolve_blind_spot(
    spot_id: int,
    note: Optional[str] = None,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """标记盲区问题已解决"""
    success = await BlindSpotService.mark_resolved(
        db, spot_id, current_user.tenant_id, note
    )
    if not success:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"message": "已标记为已解决"}