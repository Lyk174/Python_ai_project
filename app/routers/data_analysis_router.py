# app/routers/data_analysis_router.py
import os
import uuid
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.auth.dependencies import get_current_user, require_roles
from app.database.session import get_db
from app.models.user import User
from app.models.data_analysis import DataAnalysisTask
from app.models.query_task import QueryTask
from app.models.analysis_chart import AnalysisChart
from app.schemas.data_analysis_schema import QueryRequest
from app.services.celery_tasks import execute_data_analysis
from app.core.config import settings
from typing import List

router = APIRouter(prefix="/api/v1/data-analysis", tags=["数据分析"])

UPLOAD_DIR = "uploads/data_analysis"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(["tenant_admin", "super_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """上传 CSV/Excel 文件"""
    if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
        raise HTTPException(400, "仅支持 CSV 或 Excel 文件")

    file_id = uuid.uuid4().hex
    ext = os.path.splitext(file.filename)[1]
    save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    task = DataAnalysisTask(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        filename=file.filename,
        file_path=save_path,
        status="uploaded"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    return {"task_id": task.id, "filename": file.filename, "status": "uploaded"}


@router.get("/tasks")
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DataAnalysisTask).where(
        DataAnalysisTask.tenant_id == current_user.tenant_id,
        DataAnalysisTask.user_id == current_user.id
    ).order_by(DataAnalysisTask.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return [
        {
            "id": t.id,
            "filename": t.filename,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.post("/{analysis_task_id}/query")
async def run_query(
    analysis_task_id: int,
    req: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """对已上传的文件提交新的分析查询"""
    # 验证文件任务存在且属于当前用户
    stmt = select(DataAnalysisTask).where(
        DataAnalysisTask.id == analysis_task_id,
        DataAnalysisTask.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    analysis_task = result.scalar_one_or_none()
    if not analysis_task:
        raise HTTPException(404, "文件任务不存在")

    # 创建查询任务
    query_task = QueryTask(
        analysis_task_id=analysis_task_id,
        tenant_id=current_user.tenant_id,
        query_text=req.query,
        save_to_kb=req.save_to_kb,
        status="pending"
    )
    db.add(query_task)
    await db.commit()
    await db.refresh(query_task)

    # 提交 Celery 异步任务
    execute_data_analysis.delay(
        query_task_id=query_task.id,
        query=req.query,
        deepseek_api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
        save_to_kb=req.save_to_kb,
        tenant_id=current_user.tenant_id,
    )
    return {"query_task_id": query_task.id, "status": "pending"}


@router.get("/{analysis_task_id}/queries")
async def list_queries(
    analysis_task_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某个文件任务下的所有查询历史"""
    # 先验证文件任务权限
    stmt = select(DataAnalysisTask).where(
        DataAnalysisTask.id == analysis_task_id,
        DataAnalysisTask.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    analysis_task = result.scalar_one_or_none()
    if not analysis_task:
        raise HTTPException(404, "文件任务不存在")

    stmt = select(QueryTask).where(
        QueryTask.analysis_task_id == analysis_task_id
    ).order_by(QueryTask.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    queries = result.scalars().all()
    return [
        {
            "id": q.id,
            "query_text": q.query_text,
            "status": q.status,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        }
        for q in queries
    ]


@router.get("/query/{query_task_id}")
async def get_query_task(
    query_task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单次查询的完整详情（包含结果和图表）"""
    # 通过关联的文件任务验证租户权限
    stmt = select(QueryTask).join(DataAnalysisTask).where(
        QueryTask.id == query_task_id,
        DataAnalysisTask.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    query_task = result.scalar_one_or_none()
    if not query_task:
        raise HTTPException(404, "查询任务不存在")

    # 查询关联的图表
    chart_stmt = select(AnalysisChart).where(AnalysisChart.query_task_id == query_task_id).order_by(AnalysisChart.id)
    chart_result = await db.execute(chart_stmt)
    charts = chart_result.scalars().all()

    return {
        "id": query_task.id,
        "query_text": query_task.query_text,
        "generated_code": query_task.generated_code,
        "execution_result": query_task.execution_result,
        "status": query_task.status,
        "error_type": query_task.error_type,
        "error_detail": query_task.error_detail,
        "charts": [
            {
                "id": c.id,
                "chart_type": c.chart_type,
                "title": c.title,
                "image_base64": c.image_base64,
                "config": c.config
            }
            for c in charts
        ],
        "created_at": query_task.created_at.isoformat() if query_task.created_at else None,
    }


@router.delete("/query/{query_task_id}/kb-entry")
async def delete_query_kb_entry(
        query_task_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """删除指定查询任务存入知识库的文档"""
    # 权限验证：查询任务必须属于当前租户
    stmt = select(QueryTask).join(DataAnalysisTask).where(
        QueryTask.id == query_task_id,
        DataAnalysisTask.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    query_task = result.scalar_one_or_none()
    if not query_task:
        raise HTTPException(404, "查询任务不存在")

    if not query_task.save_to_kb:
        raise HTTPException(400, "该查询未存入知识库")

    # 调用 RAG 服务删除对应元数据过滤的文档
    from app.services.rag_service import rag_service
    filter_condition = {
        "type": "analysis_result",
        "query_task_id": query_task_id,
        "tenant_id": current_user.tenant_id
    }
    deleted_count = await rag_service.delete_documents(filter_condition)

    # 可选：更新数据库字段标记已删除
    query_task.save_to_kb = False
    await db.commit()

    return {"message": f"已从知识库移除", "deleted_count": deleted_count}