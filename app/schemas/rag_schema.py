# app/schemas/rag_schema.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class DocumentUploadResponse(BaseModel):
    status: str  # processing, completed, failed
    task_id: Optional[str] = None
    filename: str
    chunks_created: Optional[int] = None
    message: str


class DocumentQueryRequest(BaseModel):
    query: str = Field(..., description="查询文本")
    top_k: int = Field(5, ge=1, le=20, description="返回结果数量")
    category: Optional[str] = Field(None, description="类目过滤")
    shop_id: Optional[str] = Field(None, description="店铺ID过滤")
    product_id: Optional[str] = Field(None, description="商品ID过滤")
    tags: Optional[List[str]] = Field(None, description="标签列表（满足任一）")


class DocumentResult(BaseModel):
    content: str
    metadata: Dict[str, Any]


class DocumentQueryResponse(BaseModel):
    query: str
    results: List[DocumentResult]
    count: int


class DocumentDeleteRequest(BaseModel):
    filter: Dict[str, Any] = Field(default_factory=dict, description="Chroma where 过滤条件")

class DocumentListItem(BaseModel):
    source: str           # 文件名
    file_type: str        # 文件类型
    chunk_count: int      # 分块数量
    uploaded_at: Optional[str] = None  # 首次上传时间
    metadata: Dict[str, Any] = {}       # 包含 tenant_id, category, shop_id, product_id 等

class DocumentListResponse(BaseModel):
    total: int
    items: List[DocumentListItem]