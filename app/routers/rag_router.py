#rag_router.py
import os
import tempfile
from typing import Optional
import json
from fastapi import APIRouter, Depends, UploadFile, File,Form,HTTPException,BackgroundTasks
from app.auth.dependencies import require_roles,get_current_user
from app.services.rag_service import rag_service
from app.models.user import User
from app.services.document_processor import document_processor
from app.services.celery_tasks import index_document_task
from app.schemas.rag_schema import (
    DocumentUploadResponse,
    DocumentQueryRequest,
    DocumentQueryResponse,
    DocumentDeleteRequest,
    DocumentListItem,
    DocumentListResponse,
)
from app.database.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/rag", tags=["知识库"])

@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    category: Optional[str] = None,
    shop_id: Optional[str] = None,
    product_id: Optional[str] = None,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """
    获取已上传文档列表（仅本租户）
    支持按 category, shop_id, product_id 过滤
    """
    filter_meta = {}
    if category:
        filter_meta["category"] = category
    if shop_id:
        filter_meta["shop_id"] = shop_id
    if product_id:
        filter_meta["product_id"] = product_id

    items, total = await rag_service.list_documents(
        tenant_id=current_user.tenant_id,
        skip=skip,
        limit=limit,
        filter_meta=filter_meta or None
    )
    return DocumentListResponse(
        total=total,
        items=[DocumentListItem(**item) for item in items]
    )

@router.post("/upload",response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None, description="类目"),
    shop_id: Optional[str] = Form(None, description="店铺ID"),
    product_id: Optional[str] = Form(None, description="商品ID"),
    tags: Optional[str] = Form(None, description="标签，JSON数组字符串"),
    use_async: bool = Form(True, description="是否使用异步处理"),
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
):
    """上传文档到知识库，支持多种格式，并附带元数据"""
    allowed_extensions = [".txt", ".pdf", ".docx", ".xlsx", ".xls", ".csv", ".md"]
    filename = file.filename
    if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，支持: {allowed_extensions}"
        )
    # 读取文件内容
    content = await file.read()

    # 构建元数据
    metadata = {
        "tenant_id": current_user.tenant_id,
        "uploaded_by": current_user.id,
    }
    if category:
        metadata["category"] = category
    if shop_id:
        metadata["shop_id"] = shop_id
    if product_id:
        metadata["product_id"] = product_id
    if tags:
        try:
            metadata["tags"] = json.loads(tags)
        except:
            metadata["tags"] = [t.strip() for t in tags.split(",")]

    if use_async:
        # 提交 Celery 异步任务
        task = index_document_task.delay(content, filename, metadata)
        return DocumentUploadResponse(
            status="processing",
            task_id=task.id,
            filename=filename,
            message="文档已提交处理，请稍后查询状态"
        )
    else:
        # 同步处理（仅用于小文件测试）
        try:
            docs = await document_processor.load_document(content, filename, metadata)
            chunk_count = await rag_service.add_documents(docs, metadata)
            return DocumentUploadResponse(
                status="completed",
                filename=filename,
                chunks_created=chunk_count,
                message=f"成功索引 {chunk_count} 个文档块"
            )
        except Exception as e:
            logger.error(f"文档处理失败: {e}")
            raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")

@router.post("/query", response_model=DocumentQueryResponse)
async def query_knowledge_base(
    request: DocumentQueryRequest,
    current_user: User = Depends(get_current_user),
):
    """
    检索知识库，支持元数据过滤
    """
    # 构建过滤条件（自动加入租户隔离）
    filter_dict = {"tenant_id": current_user.tenant_id}
    if request.category:
        filter_dict["category"] = request.category
    if request.shop_id:
        filter_dict["shop_id"] = request.shop_id
    if request.product_id:
        filter_dict["product_id"] = request.product_id
    if request.tags:
        # Chroma 的 where 支持 $in 操作符
        filter_dict["tags"] = {"$in": request.tags}

    docs = await rag_service.retrieve_relevant(
        query=request.query,
        top_k=request.top_k,
        filter=filter_dict
    )

    results = []
    for doc in docs:
        results.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
        })

    return DocumentQueryResponse(
        query=request.query,
        results=results,
        count=len(results)
    )


@router.delete("/documents")
async def delete_documents(
    request: DocumentDeleteRequest,
    current_user: User = Depends(require_roles(["super_admin", "tenant_admin"])),
):
    """
    根据过滤条件删除文档（仅限本租户）
    """
    filter_dict = request.filter or {}
    # 强制加入租户隔离，防止越权删除
    filter_dict["tenant_id"] = current_user.tenant_id

    count = await rag_service.delete_documents(filter_dict)
    await rag_service.force_refresh()
    return {"message": f"已删除 {count} 条匹配的文档", "filter": filter_dict}


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """
    查询异步索引任务状态
    """
    from celery.result import AsyncResult
    from app.services.celery_tasks import celery_app

    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    }