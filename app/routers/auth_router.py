# app/routers/auth_router.py - 登录路由
from datetime import timedelta, datetime, timezone
from fastapi.responses import JSONResponse
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.auth.dependencies import get_current_user
from app.models import Tenant
from app.schemas.auth_schema import (
    UserCreate, UserLogin, Token,
    UserResponse, MFASetupResponse, UserProfileUpdate,
    PasswordUpdate, ForgotPasswordRequest, ResetPasswordRequest, LogoutRequest,
)
from app.database.session import get_db
from app.auth.security import (authenticate_user,
create_access_token, create_refresh_token, decode_token,
create_user_async,update_user_profile,change_password
)
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logger import get_logger
from app.services.mfa import MFAService
from app.services.sso import WeChatOAuth, DingTalkOAuth
from app.services.invite_service import InviteService
from app.services.sensitive_filter import sensitive_filter
from app.models.user import User, get_password_hash
from app.models.role import UserRole
from app.models.refresh_token import RefreshToken
from urllib.parse import quote
import random
import string
from app.services.email_service import email_service

logger =get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth",tags=["认证"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# 用户注册
@router.post("/register")
@limiter.limit("5/minute")
async def register(
        request: Request,
        user_data:UserCreate,
        invite_code:str = None,
        db: AsyncSession = Depends(get_db)
):
    if not invite_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请提供邀请码"
        )
    # 敏感词检查（用户名/邮箱）
    if sensitive_filter.contains_sensitive(user_data.username) or sensitive_filter.contains_sensitive(user_data.email):
        raise HTTPException(status_code=400, detail="用户名或邮箱包含敏感词")

    tenant_id,role_id = await InviteService.validate_code_async(db,invite_code)
    user = await create_user_async(db,user_data,tenant_id,role_id)
    await InviteService.mark_used_async(db,invite_code)

    access_token = create_access_token(data={"sub":user.username})
    refresh_token = create_refresh_token(data={"sub":user.username})

    refresh_obj =RefreshToken(
        user_id=user.id,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc)+timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_obj)
    await db.commit()

    logger.info(f"用户注册成功：{user.username},租户ID：{tenant_id}")
    return JSONResponse(content={"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"})


# 用户登录
@router.post("/login")
@limiter.limit("10/minute")
async def login(
        request: Request,
        user_credentials: UserLogin,
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"尝试登录:{user_credentials.username_or_email}")

    user = await authenticate_user(db, user_credentials.username_or_email, user_credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if user.hashed_password and (
        user.hashed_password.startswith("$2a$") or user.hashed_password.startswith("$2b$")
    ):
        user.hashed_password = get_password_hash(user_credentials.password)
        await db.commit()
        logger.info(f"用户 {user.username} 密码哈希已升级为 Argon2")

    # 提取 MFA 验证码
    mfa_code = user_credentials.mfa_code

    if user.is_mfa_enabled:
        if not mfa_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="需要MFA验证码",
                headers={"X-MFA-Required": "true"}
            )
        if not MFAService.verify_code(user.mfa_secret, mfa_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA验证码错误"
            )

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token(data={"sub": user.username})
    refresh_obj = RefreshToken(
        user_id=user.id,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_obj)
    await db.commit()
    logger.info(f"登录成功:{user.username}")
    return JSONResponse(content={"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"})

# 刷新Token
@router.post("/refresh")
async def refresh_token(
        request: Request,
        refresh_token:str,
        db: AsyncSession = Depends(get_db)
):
    token_data = decode_token(refresh_token,expected_type="refresh")
    stmt = select(User).where(User.username == token_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )
    stmt = select(RefreshToken).where(
        RefreshToken.token == refresh_token,
        RefreshToken.user_id == user.id,
        RefreshToken.revoked == 0,
        RefreshToken.expires_at > datetime.now(timezone.utc)
    )
    result = await db.execute(stmt)
    stored_token = result.scalar_one_or_none()
    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token无效或已过期"
        )

    new_access = create_access_token(data={"sub":user.username})
    new_refresh = create_refresh_token(data={"sub":user.username})

    stored_token.revoked = 1
    new_refresh_obj = RefreshToken(
        user_id=user.id,
        token=new_refresh,
        expires_at=datetime.now(timezone.utc)+timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(new_refresh_obj)
    await db.commit()
    return JSONResponse(content={"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"})

# 退出登录
@router.post("/logout")
async def logout(
        data: LogoutRequest,
        current_user:User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    stmt = update(RefreshToken).where(
        RefreshToken.token == data.refresh_token,
        RefreshToken.user_id == current_user.id,
    ).values(revoked = 1)
    await db.execute(stmt)
    await db.commit()
    return {"message":"已退出登录"}

# MFA 设置
@router.post("/mfa/setup",response_model=MFASetupResponse)
async def setup_mfa(
        current_code:str =None,
        current_user:User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    if current_user.is_mfa_enabled:
        if not current_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA已启用，请提供 current_code 参数以重置"
            )
        if not MFAService.verify_code(current_user.mfa_secret,current_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前 MFA 验证码错误，无法重置"
            )
    secret = MFAService.generate_secret()
    uri = MFAService.get_totp_uri(secret,current_user.email)
    qrcode_b64 = MFAService.get_qrcode_base64(uri)

    current_user.mfa_secret = secret
    await db.commit()
    return {"secret":secret,"qrcode_base64":qrcode_b64}

@router.post("/mfa/verify")
async def verify_mfa(
        code:str,
        current_user:User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    if not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先调用/mfa/setup"
        )
    if MFAService.verify_code(current_user.mfa_secret,code):
        current_user.is_mfa_enabled = True
        await db.commit()
        return {"message":"MFA启用成功"}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="验证码错误"
    )
@router.post("/mfa/disable")
async def disable_mfa(
        password: str = None,
        code:str = None,
        current_user:User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    if not current_user.is_mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA未启用"
        )
    if password and current_user.verify_password(password):
        current_user.is_mfa_enabled = False
        current_user.mfa_secret = None
        await db.commit()
        return {"message":"MFA已禁用"}

    if code and current_user.mfa_secret and MFAService.verify_code(current_user.mfa_secret,code):
        current_user.is_mfa_enabled = False
        current_user.mfa_secret = None
        await db.commit()
        return {"message":"MFA已禁用"}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="验证码错误"
    )
# SSO微信
@router.get("/oauth/wechat")
async def wechat_login(invite_code:str = None):
    redirect_uri = settings.WECHAT_REDIRECT_URI

    # 如果前端传入了邀请码，就把它拼接到回调地址中
    if invite_code:
        # 判断 redirect_uri 中是否已有查询参数
        separator = '&' if '?' in redirect_uri else '?'
        redirect_uri = f"{redirect_uri}{separator}invite_code={invite_code}"

    # 对完整的回调地址进行 URL 编码
    encoded_redirect_uri = quote(redirect_uri, safe='')

    # 生成最终的微信授权 URL
    authorization_url = (
        f"https://open.weixin.qq.com/connect/oauth2/authorize?"
        f"appid={settings.WECHAT_APP_ID}"
        f"&redirect_uri={encoded_redirect_uri}"
        f"&response_type=code"
        f"&scope=snsapi_userinfo"
        f"&state=STATE#wechat_redirect"
    )

    return {"authorization_url": authorization_url}

@router.get("/oauth/wechat/callback")
async def wechat_callback(
        request: Request,
        code: str,
        invite_code: str = None,
        db: AsyncSession = Depends(get_db),
):
    wechat_user = await WeChatOAuth.get_user_info(code)
    openid = wechat_user["openid"]
    nickname = wechat_user.get("nickname","")
    stmt = select(User).where(User.wechat_openid == openid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        if not invite_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="首次登录请提供邀请码"
            )
        tenant_id,role_id = await InviteService.validate_code_async(db, invite_code)
        base_username = nickname if nickname else f"wx_{openid[:8]}"
        username = base_username
        counter =1
        while True:
            stmt = select(User).where(User.username == username)
            result = await db.execute(stmt)
            if not result.scalar_one_or_none():
                break
            username = f"{base_username}_{counter}"
            counter +=1

        email = f"{openid}@wechat.local"

        new_user = User(
            username=username,
            email=email,
            wechat_openid=openid,
            tenant_id=tenant_id,
            is_active=True,
            hashed_password=None
        )
        db.add(new_user)
        await db.flush()

        user_role = UserRole(user_id=new_user.id,role_id=role_id,tenant_id=tenant_id)
        db.add(user_role)

        await InviteService.mark_used_async(db, invite_code)

        await db.commit()
        await db.refresh(new_user)
        user=new_user

    access_token = create_access_token(data={"sub":user.username})
    refresh_token = create_refresh_token(data={"sub":user.username})

    refresh_obj = RefreshToken(
        user_id=user.id,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc)+timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_obj)
    await db.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email
        }
    }

# SSO 钉钉
@router.get("/oauth/dingtalk")
async def dingtalk_login():
    url = DingTalkOAuth.get_authorization_url()
    return {"authorization_url": url}

@router.get("/oauth/dingtalk/callback")
async def dingtalk_callback(
        request: Request,
        code: str,
        invite_code: str = None,
        db: AsyncSession = Depends(get_db),
):
    user_info = await DingTalkOAuth.get_user_info(code)
    openid = user_info["userid"]
    stmt = select(User).where(User.dingtalk_openid == openid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        if not invite_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="首次登录请提供邀请码"
            )
        tenant_id,role_id = await InviteService.validate_code_async(db, invite_code)

        new_user = User(
            username=f"wx_{openid[:8]}",
            email=f"{openid}@dingtalk.local",
            dingtalk_openid=openid,
            tenant_id=tenant_id,
            is_active=True,
        )
        db.add(new_user)
        await db.flush()
        user_role = UserRole(user_id=new_user.id,role_id=role_id,tenant_id=tenant_id)
        db.add(user_role)
        await InviteService.mark_used_async(db, invite_code)
        await db.commit()
        await db.refresh(new_user)
        user=new_user

    access_token =create_access_token(data={"sub":user.username})
    refresh_token = create_refresh_token(data={"sub":user.username})
    refresh_obj = RefreshToken(
        user_id=user.id,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc)+timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_obj)
    await db.commit()
    return {"access_token":access_token,"refresh_token":refresh_token,"token_type":"bearer"}
# 获取当前用户信息
@router.get("/me",response_model=UserResponse)
async def read_users_me(
    current_user: User =Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_name = None
    if current_user.tenant_id:
        stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
        result = await db.execute(stmt)
        tenant = result.scalar_one_or_none()
        tenant_name = tenant.name if tenant else None

    roles =[]
    for ur in current_user.roles:
        if ur.role:
            roles.append({"id":ur.role.id,"name":ur.role.name})

    # 构建响应数据
    user_data = {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "tenant_id": current_user.tenant_id,
        "tenant_name": tenant_name,
        "roles": roles,
        "created_at": current_user.created_at,
    }
    return UserResponse(**user_data)

# 更新个人资料（用户名/邮箱）
@router.patch("/me/profile", response_model=UserResponse)
async def update_my_profile(
    data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新当前用户的用户名或邮箱（需原密码）"""
    user = await update_user_profile(db, current_user, data)
    return user

# 修改密码
@router.post("/me/password")
async def update_my_password(
    data: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """修改当前用户密码"""
    await change_password(db, current_user, data)
    return {"message": "密码修改成功"}

# 生成6位数字验证码
def generate_verification_code() -> str:
    return ''.join(random.choices(string.digits, k=6))

@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    redis_client=request.app.state.redis
    """
    发送密码重置验证码到邮箱
    """
    # 检查邮箱是否存在
    stmt = select(User).where(User.email == data.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        # 出于安全考虑，不暴露邮箱不存在，统一返回成功
        logger.info(f"密码重置请求：邮箱 {data.email} 不存在")
        return {"message": "如果该邮箱已注册，验证码将发送至您的邮箱"}

    tenant_id = user.tenant_id
    # 生成验证码
    code = generate_verification_code()
    # 存入 Redis，有效期 10 分钟
    key = f"pwd_reset:{data.email}"
    await redis_client.setex(key, 600, code)

    # 发送邮件
    try:
        await email_service.send_verification_code(db,tenant_id,data.email, code)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"验证码邮件发送失败: {e}")
        raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

    logger.info(f"密码重置验证码已发送至 {data.email}(租户:{tenant_id})")
    return {"message": "如果该邮箱已注册，验证码将发送至您的邮箱"}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    redis_client=request.app.state.redis
    """
    验证验证码并重置密码
    """
    # 验证验证码
    key = f"pwd_reset:{data.email}"
    stored_code = await redis_client.get(key)
    if not stored_code or stored_code != data.code:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # 查找用户
    stmt = select(User).where(User.email == data.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")

    # 更新密码
    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()

    # 删除验证码（防止重复使用）
    await redis_client.delete(key)

    # 可选：撤销该用户所有 Refresh Token（强制重新登录）
    stmt = update(RefreshToken).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked == 0
    ).values(revoked=1)
    await db.execute(stmt)
    await db.commit()

    logger.info(f"用户 {user.username} 密码已重置")
    return {"message": "密码重置成功，请使用新密码登录"}

@router.get("/me/bindings")
async def get_bindings(current_user: User = Depends(get_current_user)):
    """获取第三方账号绑定状态"""
    return {
        "wechat": bool(current_user.wechat_openid),
        "dingtalk": bool(current_user.dingtalk_openid),
    }

@router.post("/me/bindings/wechat")
async def bind_wechat(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """绑定微信账号"""
    if current_user.wechat_openid:
        raise HTTPException(status_code=400, detail="已绑定微信，请先解绑")

    wechat_user = await WeChatOAuth.get_user_info(code)
    openid = wechat_user["openid"]

    # 检查 openid 是否已被其他账号绑定
    stmt = select(User).where(User.wechat_openid == openid)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该微信已绑定其他账号")

    current_user.wechat_openid = openid
    await db.commit()
    logger.info(f"用户 {current_user.username} 绑定微信成功")
    return {"message": "微信绑定成功"}


@router.delete("/me/bindings/wechat")
async def unbind_wechat(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """解绑微信账号"""
    if not current_user.wechat_openid:
        raise HTTPException(status_code=400, detail="未绑定微信")

    current_user.wechat_openid = None
    await db.commit()
    logger.info(f"用户 {current_user.username} 解绑微信")
    return {"message": "微信解绑成功"}

@router.post("/me/bindings/dingtalk")
async def bind_dingtalk(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """绑定钉钉账号"""
    if current_user.dingtalk_openid:
        raise HTTPException(status_code=400, detail="已绑定钉钉，请先解绑")

    user_info = await DingTalkOAuth.get_user_info(code)
    openid = user_info["userid"]

    stmt = select(User).where(User.dingtalk_openid == openid)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该钉钉已绑定其他账号")

    current_user.dingtalk_openid = openid
    await db.commit()
    logger.info(f"用户 {current_user.username} 绑定钉钉成功")
    return {"message": "钉钉绑定成功"}


@router.delete("/me/bindings/dingtalk")
async def unbind_dingtalk(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """解绑钉钉账号"""
    if not current_user.dingtalk_openid:
        raise HTTPException(status_code=400, detail="未绑定钉钉")

    current_user.dingtalk_openid = None
    await db.commit()
    logger.info(f"用户 {current_user.username} 解绑钉钉")
    return {"message": "钉钉解绑成功"}