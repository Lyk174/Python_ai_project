# app/schemas/quota_schema.py
from pydantic import BaseModel

class QuotaInfo(BaseModel):
    daily_remaining: float
    max_per_conversation: float