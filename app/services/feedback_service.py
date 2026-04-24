# app/services/feedback_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.models.feedback import UserFeedback, FeedbackType, FeedbackStatus
from app.models.blind_spot import BlindSpotQuery
from app.models.chat import ChatHistory
from app.schemas.feedback_schema import FeedbackCreate, FeedbackUpdate
from app.core.logger import get_logger

logger = get_logger(__name__)


class FeedbackService:
    @staticmethod
    async def create_feedback(
        db: AsyncSession,
        user_id: int,
        tenant_id: int,
        data: FeedbackCreate,
        retrieval_snapshot: Optional[Dict] = None,
    ) -> UserFeedback:
        # 获取对应的聊天记录
        stmt = select(ChatHistory).where(
            ChatHistory.id == data.chat_history_id,
            ChatHistory.user_id == user_id
        )
        result = await db.execute(stmt)
        chat_history = result.scalar_one_or_none()
        if not chat_history:
            raise ValueError("聊天记录不存在")

        feedback = UserFeedback(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=chat_history.session_id,
            chat_history_id=data.chat_history_id,
            feedback_type=data.feedback_type,
            reason=data.reason,
            query_text=chat_history.message,
            answer_text=chat_history.response,
            retrieval_snapshot=retrieval_snapshot,
        )
        db.add(feedback)
        await db.commit()
        await db.refresh(feedback)

        # 如果是负面反馈，记录到盲区探测（暂不自动处理，由定时任务分析）
        if data.feedback_type in [FeedbackType.THUMBS_DOWN, FeedbackType.REPORT]:
            await BlindSpotService.record_query(
                db, tenant_id, chat_history.message
            )

        logger.info(f"用户 {user_id} 提交反馈 {data.feedback_type}，记录ID: {feedback.id}")
        return feedback

    @staticmethod
    async def update_feedback(
        db: AsyncSession,
        feedback_id: int,
        tenant_id: int,
        data: FeedbackUpdate,
    ) -> Optional[UserFeedback]:
        stmt = select(UserFeedback).where(
            UserFeedback.id == feedback_id,
            UserFeedback.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        feedback = result.scalar_one_or_none()
        if not feedback:
            return None

        if data.status is not None:
            feedback.status = data.status
        if data.admin_note is not None:
            feedback.admin_note = data.admin_note

        await db.commit()
        await db.refresh(feedback)
        return feedback

    @staticmethod
    async def list_feedbacks(
        db: AsyncSession,
        tenant_id: int,
        skip: int = 0,
        limit: int = 50,
        feedback_type: Optional[FeedbackType] = None,
        status: Optional[FeedbackStatus] = None,
    ) -> List[UserFeedback]:
        stmt = select(UserFeedback).where(UserFeedback.tenant_id == tenant_id)
        if feedback_type:
            stmt = stmt.where(UserFeedback.feedback_type == feedback_type)
        if status:
            stmt = stmt.where(UserFeedback.status == status)
        stmt = stmt.order_by(UserFeedback.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()


class BlindSpotService:
    @staticmethod
    async def record_query(db: AsyncSession, tenant_id: int, query_text: str):
        """记录未命中或低质量查询"""
        normalized = query_text.strip().lower()
        logger.info(f"[盲区] 开始记录查询: tenant={tenant_id}, raw='{query_text}', normalized='{normalized}'")
        try:
            stmt = select(BlindSpotQuery).where(
                BlindSpotQuery.tenant_id == tenant_id,
                BlindSpotQuery.normalized_query == normalized,
                BlindSpotQuery.is_resolved == False
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.occurrence_count += 1
                existing.last_occurred_at = datetime.utcnow()
                logger.info(f"[盲区] 更新已有记录: id={existing.id}, 新计数={existing.occurrence_count}")
            else:
                new_entry = BlindSpotQuery(
                    tenant_id=tenant_id,
                    query_text=query_text,
                    normalized_query=normalized,
                    occurrence_count=1,
                )
                db.add(new_entry)
                await db.flush()  # 先刷新获取ID
                logger.info(f"[盲区] 新增记录: id={new_entry.id}, query='{query_text}'")
            await db.commit()
            logger.info(f"[盲区] 事务提交成功")
        except Exception as e:
            logger.error(f"[盲区] 记录失败: {e}", exc_info=True)
            await db.rollback()
            raise

    @staticmethod
    async def get_top_blind_spots(
        db: AsyncSession,
        tenant_id: int,
        limit: int = 20,
        min_occurrence: int = 1,
    ) -> List[BlindSpotQuery]:
        stmt = select(BlindSpotQuery).where(
            BlindSpotQuery.tenant_id == tenant_id,
            BlindSpotQuery.is_resolved == False,
            BlindSpotQuery.occurrence_count >= min_occurrence
        ).order_by(BlindSpotQuery.occurrence_count.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def mark_resolved(db: AsyncSession, blind_spot_id: int, tenant_id: int, note: str = None):
        stmt = select(BlindSpotQuery).where(
            BlindSpotQuery.id == blind_spot_id,
            BlindSpotQuery.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry:
            entry.is_resolved = True
            entry.resolution_note = note
            await db.commit()
            return True
        return False