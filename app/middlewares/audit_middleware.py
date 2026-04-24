# app/middlewares/audit_middleware.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.services.celery_tasks import log_audit_task
from app.auth.security import decode_token
from app.core.logger import get_logger

logger = get_logger(__name__)

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 仅记录需要审计的路径
        audit_paths = ["/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/chat/sessions", "/api/v1/admin"]

        if not any(request.url.path.startswith(p) for p in audit_paths):
            return await call_next(request)

        # 提取用户信息（从token）
        auth_header = request.headers.get("Authorization")
        user_id = None
        tenant_id = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                token_data = decode_token(token, expected_type="access")
                user_id = token_data.username  # 临时存 username
            except Exception as e:
                logger.warning(f"Failed to decode token in audit: {e}")
        response =await call_next(request)
            # 异步记录（Celery 任务）
        log_audit_task.delay(
            user_id=user_id,
            tenant_id=tenant_id,
            action=f"{request.method}_{request.url.path}",
            details={"status_code": response.status_code},
            ip=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        return response