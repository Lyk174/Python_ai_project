# app/services/mfa.py
import pyotp
import qrcode
from io import BytesIO
import base64
from app.core.config import settings


class MFAService:
    @staticmethod
    def generate_secret() ->str:
        # 生成TOTP密钥
        return pyotp.random_base32()

    @staticmethod
    def get_totp_uri(secret:str,email:str) -> str:
        # 生成 otpauth URI，用于二维码
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name=settings.MFA_ISSUER_NAME,
        )

    @staticmethod
    def get_qrcode_base64(uri:str) -> str:
        # 生成二维码的 base64图片
        qr = qrcode.make(uri)
        buffered = BytesIO()
        qr.save(buffered,format='PNG')
        return base64.b64encode(buffered.getvalue()).decode()

    @staticmethod
    def verify_code(secret:str,code:str) -> bool:
        #验证 TOTP 码
        totp = pyotp.TOTP(secret)
        return totp.verify(code)



