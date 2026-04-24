# app/services/llm_client.py
import openai
from app.core.config import settings
from app.core.logger import get_logger
from typing import List,Dict,AsyncGenerator
import json

logger = get_logger(__name__)

class LLMService:
    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.TIMEOUT,
            max_retries=settings.MAX_RETRIES,
        )

    def build_system_prompt(self,context_type="general"):
        """构建系统提示词"""
        system_prompts = {
            "general": (
                "你是大规模语言模型。"
                "你能够回答问题、创作文字，例如写故事、写公文、写邮件、写剧本、逻辑推理、编程等，还能表达观点，玩游戏等。"
                "请始终提供准确、有益且安全的信息。"
            ),
            "creative": (
                "你是一位富有创造力的语言专家。"
                "你擅长写作、头脑风暴和创意发散。"
                "请充分发挥想象力，为用户提供新颖、有趣的想法和内容。"
            ),
            "technical": (
                "你是一位技术专家。"
                "你精通各种编程语言、框架和技术概念。"
                "请提供清晰、准确的技术解释和解决方案。"
            ),
            "helpful": (
                "你是一位乐于助人的助手。"
                "你的目标是帮助用户解决问题，提供有用的建议和支持。"
                "请保持友好、耐心和专业。"
            )
        }
        return system_prompts.get(context_type,system_prompts["general"])

    def optimize_context_window(self,messages: List[Dict[str,str]],max_tokens:int = 12000):

        current_length =sum(len(msg.get("content","")) for msg in messages)

        if current_length <= max_tokens:
            return messages

        optimized_messages = []
        remaining_tokens = max_tokens

        if messages and messages[0]["role"] == "system":
            system_msg = messages[0]
            optimized_messages.append(system_msg)
            remaining_tokens -= len(system_msg.get("content",""))

        for msg in reversed(messages[1:]):
            msg_tokens = len(msg.get("content",""))
            if msg_tokens <= remaining_tokens:
                optimized_messages.insert(1,msg)
                remaining_tokens -= msg_tokens
            else:
                break

        return optimized_messages

    async def chat_complete(self,messages:list) -> str:
        response =await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            stream=False,
        )
        return response.choices[0].message.content

    async def chat_stream(self,messages: List[Dict[str,str]]) -> AsyncGenerator[str,None]:
        logger.info(f"开始调用LLM，消息数：{len(messages)}")
        try:

            stream =await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                stream=True,
                temperature =0.7,
                max_tokens=settings.MAX_TOKENS,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            logger.info("DeepSeek 回答完成")

        except Exception as e:
            logger.error(f"LLM 调用失败：{str(e)}")
            yield f"data: {json.dumps({'error': f'[系统错误] {str(e)}'})}\n\n"

llm_service = LLMService()