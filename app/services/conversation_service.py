# app/services/conversation_service.py
from typing import AsyncGenerator, List,Dict,Optional
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from redis.asyncio import Redis
from app.core.config import settings
from app.core.logger import get_logger
import json

logger = get_logger(__name__)

class RedisChatMessageHistory:
    """自定义 Redis 存储，避免 LangChain 默认内存泄漏"""
    def __init__(self, session_id: str, redis_client: Redis, ttl: int = 3600):
        self.session_id = session_id
        self.redis = redis_client
        self.ttl = ttl
        self.key = f"chat_history:{session_id}"

    async def add_message(self, message) -> None:
        data = json.dumps({
            "type": message.type,
            "content": message.content,
        })
        await self.redis.rpush(self.key, data)
        await self.redis.expire(self.key, self.ttl)

    async def get_messages(self) -> List:
        raw = await self.redis.lrange(self.key, 0, -1)
        messages = []
        for item in raw:
            msg = json.loads(item)
            if msg["type"] == "human":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["type"] == "ai":
                messages.append(AIMessage(content=msg["content"]))
        return messages

    async def clear(self) -> None:
        await self.redis.delete(self.key)

class ConversationService:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.llm = ChatOpenAI(
            api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.MODEL_NAME,
            temperature=0.7,
            max_tokens=settings.MAX_TOKENS,
            timeout=settings.TIMEOUT,
            max_retries=settings.MAX_RETRIES,
        )

    def _get_history(self, session_id: str) -> RedisChatMessageHistory:
        return RedisChatMessageHistory(session_id, self.redis)

    def _escape_braces(self, text: str) -> str:
        """转义花括号，避免被 LangChain 误认为变量占位符"""
        return text.replace("{", "{{").replace("}", "}}")

    async def chat_stream(
            self,
            session_id: str,
            user_input: str,
            context: Optional[str] = None,
            citations: Optional[List[Dict]] = None,
    ) -> AsyncGenerator[str, None]:
        history = self._get_history(session_id)
        past_messages = await history.get_messages()

        # 注意：系统提示可能也包含花括号，虽目前没有，但以防万一也转义
        system_prompt = self._escape_braces(
            "你是电商问答助手，请专业友好地回答问题。"
            "重要：如果用户使用“它”、“这个”、“那个”等指代词，你必须结合对话历史来确定所指的具体商品。"
            "如果参考知识中包含相关信息，请直接引用；如果没有，请明确告知用户。"
        )
        messages = [("system", system_prompt)]

        for msg in past_messages:
            if isinstance(msg, HumanMessage):
                messages.append(("human", self._escape_braces(msg.content)))
            elif isinstance(msg, AIMessage):
                messages.append(("ai", self._escape_braces(msg.content)))

        safe_user_input = self._escape_braces(user_input)
        if context:
            safe_context = self._escape_braces(context)
            user_message = f"参考以下知识：\n{safe_context}\n\n用户问题：{safe_user_input}"
        else:
            user_message = safe_user_input

        messages.append(("human", user_message))

        prompt = ChatPromptTemplate.from_messages(messages)
        chain = prompt | self.llm

        # 存储原始内容到历史，而非转义后的内容
        await history.add_message(HumanMessage(content=user_input))

        full_response = ""
        async for chunk in chain.astream({}):
            if chunk.content:
                full_response += chunk.content
                yield chunk.content

        await history.add_message(AIMessage(content=full_response))


conversation_service = None

def init_conversation_service(redis_client: Redis):
    global conversation_service
    conversation_service = ConversationService(redis_client)