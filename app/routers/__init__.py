# app/routers/__init__.py
from .auth_router import router as auth_router
from .chat_router import router as chat_router
from .admin_router import router as admin_router
from .rag_router import router as rag_router
from .quota_router import router as quota_router
from .feedback_router import router as feedback_router
from .experiment_router import router as experiment_router
from .user_router import router as user_router
from .config_router import router as config_router
from .competitor_router import router as competitor_router
from .data_analysis_router import router as data_analysis_router
__all__ = [
    "auth_router",
    "chat_router",
    "admin_router",
    "rag_router",
    "quota_router",
    "feedback_router",
    "experiment_router",
    "user_router",
    "config_router",
    "competitor_router",
    "data_analysis_router",
]