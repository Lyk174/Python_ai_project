# app/services/audit_service.py
from sqlalchemy.orm import Session
from app.models.audit import AuditLog
from starlette.requests import Request
import json

class AuditService:
    @staticmethod
    def log(
        db: Session,
        user_id: int = None,
        tenant_id: int = None,
        action: str = None,
        details: dict = None,
        request: Request = None
    ):
        if not action:
            return
        ip = request.client.host if request else None
        ua = request.headers.get("user-agent") if request else None
        details_str = json.dumps(details, ensure_ascii=False) if details else None
        log_entry = AuditLog(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            details=details_str,
            ip_address=ip,
            user_agent=ua
        )
        db.add(log_entry)
        db.commit()