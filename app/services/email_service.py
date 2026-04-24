# app/services/email_service.py
import asyncio
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings
from app.core.logger import get_logger
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.config_service import ConfigService

logger = get_logger(__name__)

class EmailService:
    @staticmethod
    async def _get_smtp_config(db: AsyncSession, tenant_id: int) -> dict:
        """获取指定租户的 SMTP 配置，若未配置则回退全局（tenant_id=0）"""
        config_keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_SENDER"]
        config = {}
        for key in config_keys:
            # 先查租户专属，再查全局
            value = await ConfigService.get_value(db, tenant_id, key)
            if value is None:
                value = await ConfigService.get_value(db, 0, key)
            config[key.lower()] = value
        return config

    @staticmethod
    async def send_verification_code(db:AsyncSession,tenant_id:int, to_email: str, code: str):

        smtp_config = await EmailService._get_smtp_config(db, tenant_id)
        if not smtp_config.get("smtp_host") or not smtp_config.get("smtp_user"):
            raise RuntimeError("邮箱服务未配置，请联系管理员")

        """发送验证码邮件"""
        subject = "密码重置验证码 - 电商问答助手"
        body = f"""
        <html>
        <body>
            <h3>密码重置验证码</h3>
            <p>您的验证码是：<strong style="font-size:24px;">{code}</strong></p>
            <p>验证码有效期为 10 分钟，请勿泄露。</p>
            <p>如果非您本人操作，请忽略此邮件。</p>
        </body>
        </html>
        """
        msg = MIMEMultipart()
        msg["From"] = smtp_config["smtp_sender"] or smtp_config["smtp_user"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        port = int(smtp_config.get("smtp_port",587))
        host = smtp_config.get("smtp_host")
        user = smtp_config.get("smtp_user")
        password = smtp_config.get("smtp_password")

        use_tls = (port == 465)
        start_tls = (port == 587)

        try:
            async with aiosmtplib.SMTP(
                hostname=host,
                port=port,
                use_tls=use_tls,
                start_tls=start_tls,
            ) as smtp_client:
                await smtp_client.login(user,password)
                await smtp_client.send_message(msg)
            logger.info(f"验证码已发送至 {to_email} (租户:{tenant_id})")
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            raise

email_service = EmailService()