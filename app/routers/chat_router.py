# app/routers/chat_router.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from huggingface_hub.utils import experimental
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,update,func,desc
from datetime import datetime,timezone
from app.database.session import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.chat import ChatSession, ChatHistory
from app.schemas.chat_schema import (
    ChatRequest, ChatHistoryResponse, ChatHistoryItem,
    ChatSessionCreate, ChatSessionUpdate, ChatSessionResponse
)
from app.services.quota_service import QuotaService
from app.services.sensitive_filter import sensitive_filter
from app.services.answer_validator import answer_validator
from app.core.limiter import limiter
from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import QuotaExceededError, SensitiveWordError
import json
from app.services.rag_service import rag_service
from app.services.experiment_service import ExperimentService
import time

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["对话服务"])


# 进行会话
@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def chat_endpoint(
        request: Request,
        chat_req: ChatRequest,
        current_user:User =Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    logger.info(f"收到用户请求：{chat_req.message[:20]}...")

    redis_client = request.app.state.redis
    conversation_service = request.app.state.conversation_service
    if conversation_service is None:
        raise HTTPException(status_code=500,detail="对话服务未初始化")

    if sensitive_filter.contains_sensitive(chat_req.message):
        logger.warning(f"User {current_user.id} triggered sensitive word: {chat_req.message}")
        async def error_generate():
            error_msg = "输入包含敏感词汇，请修改后重试"
            yield f"data: {json.dumps({'content': error_msg},ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(error_generate(), media_type="text/event-stream;charset=utf-8")

    mock_messages = [{"role": "user", "content": chat_req.message}]
    quota_service = QuotaService(redis_client)
    if not await quota_service.check_and_consume(current_user.id, mock_messages):
        raise QuotaExceededError("今日对话额度已用完或单次对话成本超限")


    session_id = chat_req.session_id
    if session_id:
        stmt =select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
            ChatSession.is_deleted == False
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404,detail="会话不存在或无权限")
    else:
        new_session = ChatSession(
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            title="新会话"
        )
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        session_id=new_session.id

    user_history = ChatHistory(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        session_id=session_id,
        message=chat_req.message,
        response=""
    )
    db.add(user_history)
    await db.commit()
    await db.refresh(user_history)

    async def generate():
        start_time = time.time()
        full_response = ""
        citations = []
        answer_meta = {}

        experiment,group_name = await ExperimentService.get_active_experiment(db,current_user.id)
        retrieval_config = {
            "top_k":settings.TOP_K_RETRIEVAL,
            "use_hybrid": True,
            "threshold": settings.RELEVANCE_THRESHOLD
        }
        if experiment and group_name:
            group_config = experiment.group_configs.get(group_name,{})
            retrieval_config.update(group_config)
            logger.info(f"用户{current_user.id}分配至实验{experiment.name}组{group_name}")

        query_for_retrieval = chat_req.message
        if session_id:
            try:
                history_key = f"chat_history:{session_id}"
                raw_history = await redis_client.lrange(history_key, -6, -1)
                last_ai_content = ""
                for item in reversed(raw_history):
                    msg = json.loads(item)
                    if msg.get("type") == "ai":
                        last_ai_content = msg.get("content", "")
                        break

                pronoun_keywords = ["它", "这个", "那个", "这款", "其", "价格", "多少钱", "参数", "重量", "尺寸",
                                    "颜色", "功能", "售后"]
                if any(kw in chat_req.message for kw in pronoun_keywords) and last_ai_content:
                    import re
                    extracted = None
                    sku_match = re.search(r'SKU[：:]\s*([A-Z0-9-]+)', last_ai_content, re.IGNORECASE)
                    if sku_match:
                        extracted = sku_match.group(1)
                    else:
                        bold_match = re.search(r'\*\*([^*]+)\*\*', last_ai_content)
                        if bold_match:
                            extracted = bold_match.group(1).strip()
                        else:
                            prod_match = re.search(
                                r'([\u4e00-\u9fa5a-zA-Z0-9]+?(?:耳机|手环|投影仪|笔记本|电脑|手表|音箱))',
                                last_ai_content)
                            if prod_match:
                                extracted = prod_match.group(1)
                    if extracted:
                        query_for_retrieval = f"{extracted} {chat_req.message}"
                        logger.info(f"指代消解: '{chat_req.message}' → '{query_for_retrieval}'")
            except Exception as e:
                logger.warning(f"指代消解失败: {e}")

        docs_with_scores = await rag_service.retrieve_with_scores(
            query_for_retrieval,
            top_k=retrieval_config.get("top_k", settings.TOP_K_RETRIEVAL),
            filter={"tenant_id": current_user.tenant_id},
            use_hybrid=retrieval_config.get("use_hybrid", True)
        )
        logger.info(f"=== 检索调试 ===")
        logger.info(f"查询文本: {chat_req.message}")
        logger.info(f"租户ID: {current_user.tenant_id}")
        logger.info(
            f"检索配置: top_k={retrieval_config.get('top_k')}, use_hybrid={retrieval_config.get('use_hybrid')}, threshold={retrieval_config.get('threshold')}")
        logger.info(f"检索返回文档数: {len(docs_with_scores)}")
        for i, (doc, score) in enumerate(docs_with_scores[:5]):
            logger.info(f"  [{i}] 分数: {score:.4f} | 内容预览: {doc.page_content[:80].replace(chr(10), ' ')}")
            logger.info(
                f"元数据: tenant_id={doc.metadata.get('tenant_id')}, source={doc.metadata.get('source')}")

        relevant_docs = []
        for doc,score in docs_with_scores:
            if score >= retrieval_config.get("threshold", settings.RELEVANCE_THRESHOLD):
                relevant_docs.append((doc,score))

        if not relevant_docs:
            from app.services.feedback_service import BlindSpotService
            try:
                await BlindSpotService.record_query(db,current_user.tenant_id,chat_req.message)
            except Exception as e:
                logger.error(f"拒答盲区记录失败：{e}")

            refuse_msg = "抱歉，我暂时没有找到相关信息。您可以尝试提供具体的商品名称（如“无线降噪耳机”）或SKU编号，我会尽力为您查询。"
            user_history.response = refuse_msg
            await db.commit()
            yield f"data: {json.dumps({'content':refuse_msg},ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            yield f"data: {json.dumps({'type': 'history_id', 'id': user_history.id}, ensure_ascii=False)}\n\n"
            return

        context_parts = []
        for doc,score in relevant_docs:
            context_parts.append(doc.page_content)
            citations.append({
                "content": doc.page_content[:200]+"..." if len(doc.page_content) >200 else doc.page_content,
                "source": doc.metadata.get("source","未知来源"),
                "file_type": doc.metadata.get("file_type",""),
                "score": round(score,3),
                "metadata": {k: v for k,v in doc.metadata.items() if k in ["category","shop_id","product_id"]}
            })
        context = "\n".join(context_parts)

        price_stock_info = await answer_validator.check_price_stock(chat_req.message)
        if price_stock_info:
            context = context+"\n"+price_stock_info if context else price_stock_info
            answer_meta["price_stock_injected"] = True

        if context:
            enhanced_message = f"参考以下知识：\n{context}\n\n用户问题：{chat_req.message}"
        else:
            enhanced_message = chat_req.message

        try:
            async for chunk in conversation_service.chat_stream(
                str(session_id),
                enhanced_message,
                context=context,
                citations=citations
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk},ensure_ascii=False)}\n\n"

            validated_answer,validation_meta = answer_validator.validate_and_correct(
                full_response,
                chat_req.message,
                {"max_price": 10000}
            )
            answer_meta.update(validation_meta)
            final_answer = validated_answer

            refuse_keywords = ["无法回答", "没有相关信息", "未提及", "未提供", "超出知识范围", "无法提供"]
            if any(kw in final_answer for kw in refuse_keywords):
                from app.services.feedback_service import BlindSpotService
                await BlindSpotService.record_query(db, current_user.tenant_id, chat_req.message)
                logger.info(f"LLM回答中检测到拒答关键词，已记录盲区: {chat_req.message}")

            user_history.response = final_answer
            stmt = update(ChatSession).where(ChatSession.id == session_id).values(updated_at=datetime.now(timezone.utc))
            await db.execute(stmt)
            await db.commit()

            if experiment and group_name:
                latency_ms = int((time.time() - start_time) * 1000)
                await ExperimentService.log_experiment(
                    db,experiment.id,current_user.id,group_name,
                    chat_req.message,final_answer,session_id,user_history.id,
                    retrieval_config,citations,latency_ms
                )

            yield f"data: {json.dumps({'type': 'history_id', 'id': user_history.id}, ensure_ascii=False)}\n\n"

            if citations:
                yield f"data: {json.dumps({'type':'citations','data': citations},ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("Chat stream error")
            error_msg = f"系统错误：{str(e)}"
            user_history.response = error_msg
            await db.commit()
            #yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield f"data: {json.dumps({'error': error_msg},ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# 会话历史（包括被删除的）
@router.get("/chat/history",response_model=ChatHistoryResponse)
async def get_chat_history(
        session_id: int = None,
        skip: int = 0,
        limit: int = 20,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    if limit > 100:
        limit = 100

    stmt = select(ChatHistory).where(ChatHistory.user_id == current_user.id)

    if session_id:
        stmt =stmt.where(ChatHistory.session_id == session_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()
    stmt =stmt.order_by(desc(ChatHistory.id)).offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return ChatHistoryResponse(total=total, items=items)

# 查询用户自己的会话
@router.get("/chat/sessions")
async def get_chat_sessions(
    skip: int = 0,
    limit: int = 20,
    search:Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if limit > 50:
        limit = 50
    stmt = select(ChatSession).where(
            ChatSession.user_id == current_user.id,
            ChatSession.is_deleted == False
        )

    if search:
        stmt = stmt.where(ChatSession.title.contains(search))

    stmt = stmt.order_by(desc(ChatSession.updated_at)).offset(skip).limit(limit)
    result = await db.execute(stmt)
    sessions =result.scalars().all()
    return {"sessions": sessions}

# 创建新的会话
@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    session_create: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_session = ChatSession(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        title=session_create.title or "新会话"
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session
# 修改会话标题
@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: int,
    session_update: ChatSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
        ChatSession.is_deleted == False
    )
    result = await db.execute(stmt)
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=404, detail="会话不存在或无权修改")

    session_obj.title = session_update.title
    session_obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session_obj)
    return session_obj

# 删除会话
@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id
    )
    result = await db.execute(stmt)
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=404, detail="会话不存在或无权删除")

    session_obj.is_deleted = True
    session_obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "会话已删除"}
