# app/routers/competitor_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.dependencies import get_current_user, require_roles
from app.database.session import get_db
from app.models.user import User
from app.models.competitor_analysis import CompetitorAnalysisTask, AnalysisStatus
from app.schemas.competitor_schema import AnalysisRequest, AnalysisResponse, TaskStatusResponse
from app.services.celery_tasks import run_competitor_analysis
from app.core.config import settings

router = APIRouter(prefix="/api/v1/competitor", tags=["竞品分析"])


@router.post("/analyze", response_model=AnalysisResponse)
async def start_analysis(
    data: AnalysisRequest,
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """启动竞品分析任务（仅租户管理员及以上）"""
    if not data.url and not data.description:
        raise HTTPException(status_code=400, detail="请提供 URL 或描述")

    # 创建任务记录
    task = CompetitorAnalysisTask(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        input_url=data.url,
        input_description=data.description,
        status=AnalysisStatus.PENDING
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 准备 API Keys
    deepseek_key = settings.DEEPSEEK_API_KEY.get_secret_value()
    firecrawl_key = settings.FIRECRAWL_API_KEY
    perplexity_key = settings.PERPLEXITY_API_KEY if data.search_engine == "perplexity" else None
    exa_key = settings.EXA_API_KEY if data.search_engine == "exa" else None

    # 提交 Celery 异步任务
    run_competitor_analysis.delay(
        task_id=task.id,
        deepseek_api_key=deepseek_key,
        firecrawl_api_key=firecrawl_key,
        search_engine=data.search_engine,
        perplexity_api_key=perplexity_key,
        exa_api_key=exa_key
    )

    return AnalysisResponse(task_id=task.id, status=task.status)

@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询分析任务状态"""
    stmt = select(CompetitorAnalysisTask).where(
        CompetitorAnalysisTask.id == task_id,
        CompetitorAnalysisTask.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks", response_model=list[TaskStatusResponse])
async def list_my_tasks(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的分析任务列表"""
    stmt = select(CompetitorAnalysisTask).where(
        CompetitorAnalysisTask.tenant_id == current_user.tenant_id,
        CompetitorAnalysisTask.user_id == current_user.id
    ).order_by(CompetitorAnalysisTask.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()