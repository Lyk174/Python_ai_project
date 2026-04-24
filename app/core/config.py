# app/core/config.py
from pydantic_settings import BaseSettings,SettingsConfigDict
from pydantic import SecretStr, Field, field_validator
from typing import List
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",env_file_encoding="utf-8",extra="ignore")
    APP_NAME: str = "DeepSeek Chat Assistant"
    VERSION: str = "3.0.0"

    # LLM
    DEEPSEEK_API_KEY:SecretStr
    DEEPSEEK_BASE_URL : str = "https://api.deepseek.com"
    MODEL_NAME: str = "deepseek-chat"
    TIMEOUT: int = 60
    MAX_RETRIES: int = 3
    MAX_TOKENS: int = 2048
    MAX_CONTEXT_TOKENS: int = 16384
    # 数据库配置
    DATABASE_URL: str = "mysql+aiomysql://root:123456@localhost:3306/deepseek_chat_db"

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT认证配置
    SECRET_KEY: SecretStr
    ALGORITHM: str =  "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1000
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 限流
    RATE_LIMIT_CHAT: str = "3/minute"

    # 多租户
    DEFAULT_TENANT_NAME: str = "DefaultCompany"

    #SSO微信
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: SecretStr = ""
    WECHAT_REDIRECT_URI: str = ""

    #SSO钉钉
    DINGTALK_APP_ID: str = ""
    DINGTALK_APP_SECRET: SecretStr = ""
    DINGTALK_REDIRECT_URI: str = ""

    #MFA
    MFA_ISSUER_NAME: str = "DeepSeekChat"


    # 审计日志
    AUDIT_LOG_ENABLED: bool = True

    # 预算控制
    QUOTA_PER_USER_PER_DAY: float = 2.0
    MAX_COST_PER_CONVERSATION: float = 0.02
    TOKEN_PRICE_PER_1K: float = 0.001

    # 敏感词文件路径
    SENSITIVE_WORDS_FILE: str = "sensitive-words.txt"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # RAG 配置
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    TOP_K_RETRIEVAL: int = 5
    RELEVANCE_THRESHOLD: float = 0.5

    SMTP_HOST: str = "smtp.qq.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_SENDER: str = ""

    PERPLEXITY_API_KEY:str =""
    FIRECRAWL_API_KEY:str =""
    EXA_API_KEY:str =""

    @property
    def ALLOWED_HOSTS(self) -> List[str]:
        return ["*"]

    @field_validator("SENSITIVE_WORDS_FILE")
    @classmethod
    def validate_sensitive_file(cls, v:str) -> str:
        if not os.path.exists(v):
            with open(v,"w",encoding="utf-8") as f:
                f.write("")
        return v
settings = Settings()