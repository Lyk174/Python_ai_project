# app/services/experiment_service.py
import hashlib
import random
from typing import Optional, Dict, Any, List,Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timezone

from app.models.experiment import Experiment, ExperimentAssignment, ExperimentLog
from app.core.logger import get_logger

logger = get_logger(__name__)


class ExperimentService:
    @staticmethod
    async def get_active_experiment(db: AsyncSession, user_id: int) -> Tuple[Optional[Experiment],Optional[str]]:
        """获取用户当前所处的活跃实验"""
        now = datetime.now(timezone.utc)
        stmt = select(Experiment).where(
            Experiment.is_active == True,
            and_(
                Experiment.start_time.is_(None) | (Experiment.start_time <= now),
                Experiment.end_time.is_(None) | (Experiment.end_time >= now)
            )
        )
        result = await db.execute(stmt)
        experiments = result.scalars().all()
        for exp in experiments:
            # 检查是否已分配
            assign_stmt = select(ExperimentAssignment).where(
                ExperimentAssignment.experiment_id == exp.id,
                ExperimentAssignment.user_id == user_id
            )
            assign_result = await db.execute(assign_stmt)
            assignment = assign_result.scalar_one_or_none()
            if assignment:
                return exp, assignment.group_name
            # 未分配则按流量比例分配
            assigned_group = ExperimentService._assign_group(exp, user_id)
            if assigned_group:
                new_assign = ExperimentAssignment(
                    experiment_id=exp.id,
                    user_id=user_id,
                    group_name=assigned_group
                )
                db.add(new_assign)
                await db.commit()
                return exp, assigned_group
        return None, None

    @staticmethod
    def _assign_group(experiment: Experiment, user_id: int) -> Optional[str]:
        """基于用户ID哈希分配组别"""
        traffic_split = experiment.traffic_split
        total = sum(traffic_split.values())
        if total == 0:
            return None
        hash_val = int(hashlib.md5(str(user_id).encode()).hexdigest(), 16) % total
        cumulative = 0
        for group, weight in traffic_split.items():
            cumulative += weight
            if hash_val < cumulative:
                return group
        return None

    @staticmethod
    async def log_experiment(
        db: AsyncSession,
        experiment_id: int,
        user_id: int,
        group_name: str,
        query: str,
        answer: str,
        session_id: Optional[int],
        chat_history_id: Optional[int],
        retrieval_config: Dict,
        retrieval_results: List,
        latency_ms: int,
    ):
        log_entry = ExperimentLog(
            experiment_id=experiment_id,
            user_id=user_id,
            group_name=group_name,
            session_id=session_id,
            chat_history_id=chat_history_id,
            query_text=query,
            answer_text=answer,
            retrieval_config=retrieval_config,
            retrieval_results=retrieval_results,
            latency_ms=latency_ms,
        )
        db.add(log_entry)
        await db.commit()