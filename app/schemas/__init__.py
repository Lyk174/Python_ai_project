# app/schemas/__init__.py
from .auth_schema import (
    UserBase,
    UserCreate,
    UserLogin,
    UserResponse,
    Token,
    TokenData,
    MFASetupResponse,
    UserProfileUpdate,
    PasswordUpdate,
    LogoutRequest,
)
from .chat_schema import (
    ChatHistoryItem,
    ChatHistoryResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionUpdate,
    ChatSessionResponse,
)
from .admin_schema import (
    InviteCodeCreate,
    RoleAssign,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
    UserRoleUpdate,
)
from .quota_schema import (
    QuotaInfo,
)

from .user_schema import (
    UserListPage,
    UserListResponse,
)

from .rag_schema import (
    DocumentListResponse,
    DocumentListItem,
    DocumentResult,
    DocumentQueryResponse,
    DocumentUploadResponse,
    DocumentQueryRequest,
    DocumentDeleteRequest,
)


__all__ = [
    # auth
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "Token",
    "TokenData",
    "MFASetupResponse",
    "UserProfileUpdate",
    "PasswordUpdate",
    "LogoutRequest",
    # chat
    "ChatHistoryItem",
    "ChatHistoryResponse",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ChatSessionCreate",
    "ChatSessionUpdate",
    "ChatSessionResponse",
    # admin
    "InviteCodeCreate",
    "RoleAssign",
    "TenantCreate",
    "TenantResponse",
    "TenantUpdate",
    "UserRoleUpdate",
    # quota
    "QuotaInfo",
    # user
    "UserListPage",
    "UserListResponse",
    #rag
    "DocumentListResponse",
    "DocumentListItem",
    "DocumentResult",
    "DocumentQueryResponse",
    "DocumentUploadResponse",
    "DocumentQueryRequest",
    "DocumentDeleteRequest",
]