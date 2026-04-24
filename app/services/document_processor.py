# app/services/document_processor.py
import re
import os
import tempfile
from typing import List, Dict, Any, Optional
from pathlib import Path

from langchain_community.document_loaders import (
    TextLoader,
    PyPDFLoader,
    Docx2txtLoader,
    UnstructuredExcelLoader,
    CSVLoader,
    UnstructuredMarkdownLoader,
)
from langchain_core.documents import Document

from app.core.logger import get_logger

logger = get_logger(__name__)

class DocumentProcessor:
    """支持多种格式的文档加载器"""

    SUPPORTED_EXTENSIONS = {
        ".txt": "text",
        ".pdf": "pdf",
        ".docx": "docx",
        ".xlsx": "excel",
        ".xls": "excel",
        ".csv": "csv",
        ".md": "markdown",
    }

    @staticmethod
    def split_by_markdown_headings(content: str, metadata: dict) -> List[Document]:
        """
        按 Markdown 三级标题（### ）切分文档，每个商品条目作为一个独立文档块。
        同时保留非标题开头的文本（如政策部分）作为一个独立块。
        """
        # 匹配 "### 数字. 商品名" 格式的标题
        pattern = r'(### \d+\. .+?)(?=\n### \d+\. |\n## |\Z)'
        matches = re.findall(pattern, content, re.DOTALL)

        docs = []
        for match in matches:
            doc = Document(page_content=match.strip(), metadata=metadata.copy())
            docs.append(doc)

        intro = re.split(r'### \d+\.', content, maxsplit=1)[0].strip()
        if intro:
            doc = Document(page_content=intro, metadata=metadata.copy())
            docs.append(doc)

        return docs

    @classmethod
    def get_loader(cls, file_path: str):
        """根据文件扩展名返回对应的 Loader"""
        ext = Path(file_path).suffix.lower()
        if ext == ".txt":
            return TextLoader(file_path, encoding="utf-8")
        elif ext == ".pdf":
            return PyPDFLoader(file_path)
        elif ext == ".docx":
            return Docx2txtLoader(file_path)
        elif ext in [".xlsx", ".xls"]:
            return UnstructuredExcelLoader(file_path, mode="elements")
        elif ext == ".csv":
            return CSVLoader(file_path, encoding="utf-8")
        elif ext == ".md":
            return UnstructuredMarkdownLoader(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

    @classmethod
    async def load_document(
            cls,
            file_content: bytes,
            filename: str,
            metadata: Optional[Dict[str, Any]] = None
    )->List[Document]:
        """从上传的文件内容加载文档，支持多种格式"""
        suffix = Path(filename).suffix.lower()

        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件格式：{suffix},支持：{list(cls.SUPPORTED_EXTENSIONS.keys())}")

        with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            if suffix in [".txt", ".md"]:
                content_str = file_content.decode("utf-8")
                base_metadata = {
                    "source": filename,
                    "file_type": cls.SUPPORTED_EXTENSIONS[suffix],
                }
                if metadata:
                    base_metadata.update(metadata)
                documents = cls.split_by_markdown_headings(content_str, base_metadata)
                logger.info(f"成功按标题切分文档 {filename}，共 {len(documents)} 个条目")
                return documents
            else:
                loader = cls.get_loader(tmp_path)
                documents = loader.load()
                base_metadata = {
                    "source": filename,
                    "file_type": cls.SUPPORTED_EXTENSIONS[suffix],
                }
                if metadata:
                    base_metadata.update(metadata)

                for doc in documents:
                    doc.metadata.update(base_metadata)

                logger.info(f"成功加载文档 {filename}，共 {len(documents)} 个片段")
                return documents
        except Exception as e:
            logger.error(f"加载文档失败 {filename}: {e}")
            raise
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @classmethod
    async def load_from_database(
            cls,
            query_result: List[Dict[str, Any]],
            content_field: str,
            metadata_fields: List[str],
    )->List[Document]:
        """从数据库查询结果构造文档对象"""
        documents = []
        for row in query_result:
            content = row.get(content_field,"")
            if not content:
                continue
            meta = {k: row[k] for k in metadata_fields if k in row}
            doc = Document(page_content=content, metadata=meta)
            documents.append(doc)
        return documents

    @classmethod
    def load_document_sync(cls, file_content: bytes, filename: str, metadata: Optional[Dict[str, Any]] = None) -> List[Document]:
        """同步版本，供 Celery 调用"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(cls.load_document(file_content, filename, metadata))

document_processor = DocumentProcessor()






