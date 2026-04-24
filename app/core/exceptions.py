# app/core/exceptions.py
from fastapi import HTTPException, status

class BusinessError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)

class QuotaExceededError(BusinessError):
    def __init__(self, detail: str = "配额超限"):
        super().__init__(detail=detail, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

class SensitiveWordError(BusinessError):
    def __init__(self, detail: str = "敏感词违规"):
        super().__init__(detail=detail, status_code=status.HTTP_400_BAD_REQUEST)