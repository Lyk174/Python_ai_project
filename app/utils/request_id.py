# app/utils/request_id.py
from typing import Optional
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

def get_request_id() -> Optional[str]:
    rid = request_id_var.get()
    return rid if rid else None

def set_request_id(rid: str):
    request_id_var.set(rid)