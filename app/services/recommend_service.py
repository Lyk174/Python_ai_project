# app/services/recommend_service.py
from app.services.llm_client import llm_service
from app.core.logger import get_logger

logger = get_logger(__name__)

class RecommendService:
    @staticmethod
    async def generate_recommendations(user_profile: dict, product_context: str) -> str:
        """基于用户画像和商品上下文生成个性化推荐"""
        prompt = f"用户画像：{user_profile}\n商品信息：{product_context}\n请生成个性化推荐："
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_complete(messages)
        return response

recommend_service = RecommendService()