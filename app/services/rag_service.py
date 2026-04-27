import re
import jieba
import os
import uuid
import pickle
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from app.core.config import settings as app_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class BM25Retriever:
    STOP_WORDS = {
        "的", "了", "是", "在", "和", "与", "或", "及", "有", "也", "就", "都",
        "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "哪",
        "什么", "怎么", "如何", "多少", "为什么", "一个", "一种", "这个", "那个"
    }

    def __init__(self):
        self.documents: List[Document] = []
        self.corpus: List[List[str]] = []
        self.bm25: Optional[BM25Okapi] = None
        self.doc_id_to_index: Dict[str, int] = {}
        self.is_built = False

    def _tokenize(self, text: str) -> List[str]:
        words = list(jieba.cut(text))
        filtered = []
        for w in words:
            w = w.strip()
            if not w:
                continue
            if len(w) == 1 and re.match(r'^[\u4e00-\u9fa5]$', w):
                continue
            if w in self.STOP_WORDS:
                continue
            filtered.append(w)
        return filtered if filtered else words

    def add_documents(self, documents: List[Document]):
        for doc in documents:
            doc_id = doc.metadata.get("id")
            if not doc_id:
                doc_id = str(uuid.uuid4())
                doc.metadata["id"] = doc_id
            if doc_id not in self.doc_id_to_index:
                self.documents.append(doc)
                self.corpus.append(self._tokenize(doc.page_content))
                self.doc_id_to_index[doc_id] = len(self.documents) - 1
        self._rebuild_index()

    def _rebuild_index(self):
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
            self.is_built = True
        else:
            self.bm25 = None
            self.is_built = False

    def remove_documents(self, filter: Dict[str, Any]):
        indices_to_remove = []
        for idx, doc in enumerate(self.documents):
            match = True
            for k, v in filter.items():
                if k not in doc.metadata or doc.metadata[k] != v:
                    match = False
                    break
            if match:
                indices_to_remove.append(idx)
        if not indices_to_remove:
            return
        for idx in sorted(indices_to_remove, reverse=True):
            doc_id = self.documents[idx].metadata.get("id")
            del self.documents[idx]
            del self.corpus[idx]
            if doc_id in self.doc_id_to_index:
                del self.doc_id_to_index[doc_id]
        self.doc_id_to_index = {doc.metadata["id"]: i for i, doc in enumerate(self.documents)}
        self._rebuild_index()

    def search(self, query: str, top_k: int = 5, filter: Optional[Dict[str, Any]] = None) -> List[Tuple[Document, float]]:
        if not self.is_built or not self.bm25:
            return []
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        candidates = []
        max_score = max(scores) if len(scores) > 0 else 1.0
        for idx, doc in enumerate(self.documents):
            if filter:
                match = True
                for k, v in filter.items():
                    if isinstance(v, dict) and "$in" in v:
                        if doc.metadata.get(k) not in v["$in"]:
                            match = False
                            break
                    elif doc.metadata.get(k) != v:
                        match = False
                        break
                if not match:
                    continue
            normalized_score = scores[idx] / max_score if max_score > 0 else 0.0
            candidates.append((doc, normalized_score))
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    def save(self, path: str):
        data = {"documents": self.documents, "corpus": self.corpus}
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.documents = data["documents"]
        self.corpus = data["corpus"]
        self.doc_id_to_index = {doc.metadata["id"]: i for i, doc in enumerate(self.documents)}
        self._rebuild_index()
        logger.info(f"从{path}加载了{len(self.documents)}个文档到 BM25 索引")


class RAGService:
    def __init__(self):
        self.vectorstore: Optional[Chroma] = None
        self.bm25_retriever = BM25Retriever()
        self.is_ready = False
        self.embedding_model = None
        self.bm25_index_path = Path(app_settings.CHROMA_PERSIST_DIR) / "bm25_index.pkl"
        self._client: Optional[chromadb.HttpClient] = None

    # ---------- 检索增强辅助 ----------
    def _query_expansion(self, query: str) -> List[str]:
        words = jieba.lcut(query)
        keywords = [w for w in words if w not in BM25Retriever.STOP_WORDS and len(w) > 1]
        if len(keywords) <= 1:
            return [query]
        return [query, " ".join(keywords)]

    def _keyword_boost(self, query: str, docs: List[Tuple[Document, float]]) -> List[Tuple[Document, float]]:
        if not docs:
            return docs
        query_terms = list(jieba.cut(query))
        query_terms = [t.strip() for t in query_terms if t.strip() and t not in BM25Retriever.STOP_WORDS]
        if not query_terms:
            return docs
        boosted = []
        for doc, score in docs:
            hit_count = sum(doc.page_content.count(term) for term in query_terms)
            boost = min(0.25, hit_count * 0.05)
            boosted.append((doc, score + boost))
        boosted.sort(key=lambda x: x[1], reverse=True)
        return boosted

    def _rerank_by_relevance(self, query: str, docs: List[Tuple[Document, float]], top_k: int) -> List[Tuple[Document, float]]:
        if not docs:
            return docs
        query_terms = jieba.lcut(query)
        query_terms = [t for t in query_terms if t.strip() and t not in BM25Retriever.STOP_WORDS]
        reranked = []
        for doc, original_score in docs:
            content = doc.page_content
            final_score = original_score
            length = len(content)
            if 300 <= length <= 800:
                final_score += 0.05
            elif length < 100:
                final_score -= 0.1
            first_hits = sum(1 for term in query_terms if term in content[:200])
            final_score += first_hits * 0.03
            title = doc.metadata.get("title", "") or doc.metadata.get("source", "")
            if title:
                title_hits = sum(1 for term in query_terms if term in title)
                final_score += title_hits * 0.05
            if doc.metadata.get("type") == "analysis_result":
                final_score += 0.02
            reranked.append((doc, final_score))
        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]

    # ---------- 初始化 ----------
    async def initialize(self):
        persist_dir = app_settings.CHROMA_PERSIST_DIR
        os.makedirs(persist_dir, exist_ok=True)

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        local_model_path = "/root/.cache/huggingface/hub/models--BAAI--bge-small-zh/snapshots"
        self.embedding_model = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )

        self._client = chromadb.HttpClient(
            host="chroma",
            port=8000,
            settings=Settings(anonymized_telemetry=False)
        )
        # 初始化 vectorstore
        self.vectorstore = Chroma(
            client=self._client,
            collection_name="knowledge_base",
            embedding_function=self.embedding_model
        )

        self.bm25_retriever.load(str(self.bm25_index_path))
        self.is_ready = True
        logger.info("RAG 服务（HTTP Chroma）初始化完成")

    # ✅ 关键：每次检索前重建 vectorstore 以获取最新集合视图
    async def _refresh_collection(self):
        if self._client and self.embedding_model:
            try:
                self.vectorstore = Chroma(
                    client=self._client,
                    collection_name="knowledge_base",
                    embedding_function=self.embedding_model
                )
                logger.debug("Chroma vectorstore 已刷新（重建实例）")
            except Exception as e:
                logger.warning(f"刷新 vectorstore 失败: {e}")

    async def force_refresh(self):
        """供旧路由调用，执行实际刷新"""
        await self._refresh_collection()

    # ---------- 文档管理 ----------
    async def add_documents(
            self,
            documents: List[Document],
            metadata: Dict[str, Any] = None
    ) -> int:
        if not self.is_ready:
            await self.initialize()

        # 🔁 重新加载 BM25 索引，防止覆盖主进程的删除操作
        self.bm25_retriever.load(str(self.bm25_index_path))

        if metadata:
            for doc in documents:
                doc.metadata.update(metadata)

        for doc in documents:
            if "id" not in doc.metadata:
                doc.metadata["id"] = str(uuid.uuid4())
            doc.metadata["indexed_at"] = datetime.now(timezone.utc).isoformat()

        # 分块逻辑保持不变
        if metadata and metadata.get("file_type") in ["csv", "excel"]:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=0, separators=["\n"],keep_separator=True)
        else:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=100,
                separators=["\n## ", "\n### ", "\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
            )
        chunks = text_splitter.split_documents(documents)

        self.vectorstore.add_documents(chunks)
        self.bm25_retriever.add_documents(chunks)
        self.bm25_retriever.save(str(self.bm25_index_path))  # 保存最新状态
        logger.info(f"已添加 {len(chunks)} 个文档块")
        return len(chunks)

    def add_documents_sync(self, documents: List[Document], metadata: Dict[str, Any] = None) -> int:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.add_documents(documents, metadata))
        finally:
            loop.close()

    # ---------- 混合检索核心 ----------
    async def hybrid_search_with_scores(
        self, query: str, top_k: int = None, filter: Dict[str, Any] = None,
        vector_weight: float = 0.5, bm25_weight: float = 0.5, use_rerank: bool = True
    ) -> List[Tuple[Document, float]]:
        if not self.is_ready:
            await self.initialize()

        # 🔁 每次检索前刷新集合与 BM25
        await self._refresh_collection()
        self.bm25_retriever.load(str(self.bm25_index_path))

        top_k = top_k or app_settings.TOP_K_RETRIEVAL
        query_variants = self._query_expansion(query)
        doc_scores: Dict[str, Tuple[Document, float]] = {}

        for q in query_variants:
            vector_docs = self.vectorstore.similarity_search_with_relevance_scores(q, k=top_k * 3, filter=filter)
            bm25_candidates = self.bm25_retriever.search(q, top_k=top_k * 3, filter=filter)

            for doc, score in vector_docs:
                doc_id = doc.metadata.get("id")
                if not doc_id:
                    continue
                weighted_score = score * vector_weight
                if doc_id in doc_scores:
                    if weighted_score > doc_scores[doc_id][1]:
                        doc_scores[doc_id] = (doc, weighted_score)
                else:
                    doc_scores[doc_id] = (doc, weighted_score)

            for doc, score in bm25_candidates:
                doc_id = doc.metadata.get("id")
                if not doc_id:
                    continue
                weighted_score = score * bm25_weight
                if doc_id in doc_scores:
                    if weighted_score > doc_scores[doc_id][1]:
                        doc_scores[doc_id] = (doc, weighted_score)
                else:
                    doc_scores[doc_id] = (doc, weighted_score)

        sorted_items = sorted(doc_scores.values(), key=lambda x: x[1], reverse=True)
        sorted_items = self._keyword_boost(query, sorted_items)
        if use_rerank:
            sorted_items = self._rerank_by_relevance(query, sorted_items, top_k)
        return sorted_items[:top_k]

    async def retrieve_with_scores(self, query: str, top_k: int = None, filter: Dict[str, Any] = None,
                                   use_hybrid: bool = True, use_rerank: bool = True) -> List[Tuple[Document, float]]:
        if use_hybrid:
            return await self.hybrid_search_with_scores(query, top_k, filter, use_rerank=use_rerank)
        else:
            await self._refresh_collection()
            self.bm25_retriever.load(str(self.bm25_index_path))
            top_k = top_k or app_settings.TOP_K_RETRIEVAL
            vector_docs = self.vectorstore.similarity_search_with_relevance_scores(query, k=top_k, filter=filter)
            result = self._keyword_boost(query, vector_docs)
            if use_rerank:
                result = self._rerank_by_relevance(query, result, top_k)
            return result

    async def retrieve_relevant(self, query: str, top_k: int = None, filter: Dict[str, Any] = None,
                                use_hybrid: bool = True) -> List[Document]:
        docs_with_scores = await self.retrieve_with_scores(query, top_k, filter, use_hybrid)
        return [doc for doc, _ in docs_with_scores]

    async def retrieve_relevant_as_string(self, query: str, top_k: int = None, filter: Dict[str, Any] = None,
                                          use_hybrid: bool = True) -> str:
        docs = await self.retrieve_relevant(query, top_k, filter, use_hybrid)
        if not docs:
            return ""
        return "\n".join([doc.page_content for doc in docs])

    # ---------- 辅助方法 ----------
    def _normalize_filter(self, filter: Dict[str, Any]) -> Dict[str, Any]:
        if not filter:
            return {}
        if any(k.startswith('$') for k in filter.keys()):
            return filter
        return {"$and": [{k: {"$eq": v}} for k, v in filter.items()]}

    async def delete_documents(self, filter: Dict[str, Any]) -> int:
        if not self.is_ready:
            await self.initialize()
        try:
            normalized_filter = filter.copy()
            if not any(k.startswith("$") for k in normalized_filter.keys()):
                chroma_filter = {"$and": [{k: {"$eq": v}} for k, v in normalized_filter.items()]}
            else:
                chroma_filter = normalized_filter

            collection = self.vectorstore._collection
            existing = collection.get(where=chroma_filter, include=["metadatas"])
            ids_to_delete = existing.get("ids", [])
            deleted_count = len(ids_to_delete)
            if deleted_count > 0:
                collection.delete(ids=ids_to_delete)
                self.bm25_retriever.remove_documents(normalized_filter)
                self.bm25_retriever.save(str(self.bm25_index_path))
                logger.info(f"成功删除 {deleted_count} 个文档块")
            else:
                logger.warning(f"未找到匹配的文档")
            return deleted_count
        except Exception as e:
            logger.exception(f"删除失败: {e}")
            return 0

    def delete_documents_sync(self, filter: Dict[str, Any]) -> int:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.delete_documents(filter))
        finally:
            loop.close()

    async def update_document_metadata(self, doc_id: str, new_metadata: Dict[str, Any]) -> bool:
        try:
            self.vectorstore._collection.update(ids=[doc_id], metadata=[new_metadata])
            return True
        except Exception as e:
            logger.error(f"更新元数据失败: {e}")
            return False

    async def list_documents(self, tenant_id: int, skip: int = 0, limit: int = 50,
                             filter_meta: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], int]:
        if not self.is_ready:
            await self.initialize()
        collection = self.vectorstore._collection
        where = {"tenant_id": tenant_id}
        if filter_meta:
            where = self._normalize_filter({**filter_meta, "tenant_id": tenant_id})
        result = collection.get(where=where, include=["metadatas"])
        metadatas = result.get("metadatas", [])
        doc_map = {}
        for meta in metadatas:
            source = meta.get("source", "未知文件")
            if source not in doc_map:
                doc_map[source] = {
                    "source": source,
                    "file_type": meta.get("file_type", "unknown"),
                    "chunk_count": 1,
                    "uploaded_at": meta.get("indexed_at"),
                    "metadata": {k: v for k, v in meta.items()
                                 if k in ["category", "shop_id", "product_id", "tags", "tenant_id", "uploaded_by", "type"]}
                }
            else:
                doc_map[source]["chunk_count"] += 1
        items = list(doc_map.values())
        total = len(items)
        items = items[skip:skip + limit]
        return items, total


rag_service = RAGService()