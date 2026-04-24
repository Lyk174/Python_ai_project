# app/main
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import redis.asyncio as redis
from sqlalchemy.ext import asyncio
from app.services.rag_service import rag_service
from app.core.config import settings
from app.core.logger import get_logger
from app.core.limiter import limiter
from app.core.middleware import RequestIDMiddleware
from app.core.exceptions import QuotaExceededError, SensitiveWordError, BusinessError
from app.middlewares.audit_middleware import AuditMiddleware
from app.routers import (auth_router, chat_router, admin_router, rag_router, quota_router, feedback_router,
    experiment_router, user_router,config_router,competitor_router,data_analysis_router)
from app.services.conversation_service import ConversationService
import os
os.environ["HF_HUB_OFFLINE"] = "1"

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 Redis 连接
    retry_count = 0
    redis_client = None
    while retry_count < 3:
        try:
            redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                socket_timeout=3
            )
            await redis_client.ping()
            logger.info("Redis 连接成功")
            break
        except Exception as e:
            retry_count += 1
            logger.warning(f"Redis 连接失败 (尝试 {retry_count}/3): {e}")
            if retry_count >= 3:
                logger.error("无法连接 Redis，请检查 REDIS_URL 配置")
                raise
            await asyncio.sleep(2)

    # 将 Redis 客户端存储到 app.state 供其他模块使用
    app.state.redis = redis_client

    # 初始化对话服务（LangChain + Redis 存储）
    app.state.conversation_service=ConversationService(redis_client)
    logger.info("对话服务初始化完成")

    await rag_service.initialize()

    logger.info(f"LLM 客户端配置: {settings.MODEL_NAME}")
    logger.info("服务启动完成")

    yield

    # 关闭资源
    if redis_client:
        await redis_client.close()
        logger.info("Redis 连接已关闭")
    logger.info("服务已关闭")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="企业级电商问答助手",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# 自定义异常处理器
@app.exception_handler(QuotaExceededError)
async def quota_exception_handler(request: Request, exc: QuotaExceededError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "type": "quota_exceeded"})

@app.exception_handler(SensitiveWordError)
async def sensitive_exception_handler(request: Request, exc: SensitiveWordError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "type": "sensitive_word"})

@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "type": "business_error"})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"全局未捕获异常：{exc}")
    return JSONResponse(status_code=500,content={"detail":"服务器内部错误","type":type(exc).__name__})


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(rag_router)
app.include_router(quota_router)
app.include_router(feedback_router)
app.include_router(experiment_router)
app.include_router(user_router)
app.include_router(config_router)
app.include_router(competitor_router)
app.include_router(data_analysis_router)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
    }

# 根路径
@app.get("/")
async def root():
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "docs": "/docs",
        "health": "/health",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        log_level="debug" if settings.DEBUG else "info",
        reload=settings.DEBUG,
   )