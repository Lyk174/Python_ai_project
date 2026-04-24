# app/routers/experiment_router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.auth.dependencies import require_roles, get_current_user
from app.database.session import get_db
from app.models.user import User
from app.models.experiment import Experiment, ExperimentAssignment, ExperimentLog
from app.schemas.experiment_schema import (
    ExperimentCreate, ExperimentUpdate, ExperimentResponse,
    ExperimentLogResponse
)
from app.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/experiments", tags=["A/B测试"])


@router.post("", response_model=ExperimentResponse)
async def create_experiment(
    data: ExperimentCreate,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """创建新实验（仅超级管理员）"""
    exp = Experiment(
        name=data.name,
        description=data.description,
        traffic_split=data.traffic_split,
        group_configs=data.group_configs,
        start_time=data.start_time,
        end_time=data.end_time,
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    return exp


@router.get("", response_model=List[ExperimentResponse])
async def list_experiments(
    active_only: bool = False,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """列出所有实验"""
    from sqlalchemy import select
    stmt = select(Experiment)
    if active_only:
        stmt = stmt.where(Experiment.is_active == True)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/{exp_id}", response_model=ExperimentResponse)
async def update_experiment(
    exp_id: int,
    data: ExperimentUpdate,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """更新实验配置"""
    stmt = select(Experiment).where(Experiment.id == exp_id)
    result = await db.execute(stmt)
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(exp, key, value)
    await db.commit()
    await db.refresh(exp)
    return exp


@router.get("/logs", response_model=List[ExperimentLogResponse])
async def get_experiment_logs(
    experiment_id: Optional[int] = None,
    limit: int = 100,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """获取实验日志"""
    stmt = select(ExperimentLog)
    if experiment_id:
        stmt = stmt.where(ExperimentLog.experiment_id == experiment_id)
    stmt = stmt.order_by(ExperimentLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.delete("/{exp_id}")
async def delete_experiment(
    exp_id: int,
    current_user: User = Depends(require_roles(["super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """删除实验（仅超级管理员）"""
    # 查询实验是否存在
    stmt = select(Experiment).where(Experiment.id == exp_id)
    result = await db.execute(stmt)
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")

    # 删除关联的分配记录
    stmt = select(ExperimentAssignment).where(ExperimentAssignment.experiment_id == exp_id)
    result = await db.execute(stmt)
    assignments = result.scalars().all()
    for assign in assignments:
        await db.delete(assign)

    # 删除关联的日志
    stmt = select(ExperimentLog).where(ExperimentLog.experiment_id == exp_id)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    for log in logs:
        await db.delete(log)

    # 删除实验本身
    await db.delete(exp)
    await db.commit()

    logger.info(f"实验 {exp_id} 已被用户 {current_user.username} 删除")
    return {"message": f"实验 {exp_id} 已删除"}