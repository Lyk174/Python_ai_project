# app/services/quota_service.py
import redis.asyncio as redis
from decimal import Decimal
from app.core.config import settings
from app.utils.token_counter import count_tokens
from typing import List, Dict

class QuotaService:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def check_and_consume(self, user_id: int, messages: List[Dict[str, str]]) -> bool:
        """
        检查用户单次对话预算是否超限，并扣除预算。
        返回 True 表示允许继续，False 表示超出预算。
        """
        # 计算本次对话总 token 数（包含历史消息和即将生成的回复估算）
        input_tokens = count_tokens(messages, model=settings.MODEL_NAME)
        # 预估输出 token（最多 MAX_TOKENS）
        output_tokens = settings.MAX_TOKENS
        total_tokens = input_tokens + output_tokens
        cost = Decimal(total_tokens) / 1000 * Decimal(settings.TOKEN_PRICE_PER_1K)

        if cost > Decimal(settings.MAX_COST_PER_CONVERSATION):
            return False

        # 检查每日额度（Redis 存储）
        daily_key = f"quota:daily:{user_id}"
        daily_used = await self.redis.get(daily_key)
        if daily_used is not None:
            # 如果是 bytes，先解码；若已是 str，则直接使用（兼容处理）
            if isinstance(daily_used, bytes):
                daily_used = daily_used.decode()
            daily_used = Decimal(daily_used)
        else:
            daily_used = Decimal(0)
        if daily_used + cost > Decimal(settings.QUOTA_PER_USER_PER_DAY):
            return False

        # 扣除预算（原子操作）
        await self.redis.incrbyfloat(daily_key, float(cost))
        await self.redis.expire(daily_key, 86400)
        return True

    async def get_remaining_quota(self, user_id: int) -> float:
        daily_key = f"quota:daily:{user_id}"
        used = await self.redis.get(daily_key)
        used = float(used) if used else 0.0
        return max(0.0, settings.QUOTA_PER_USER_PER_DAY - used)