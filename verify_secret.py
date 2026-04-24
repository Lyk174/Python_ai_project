import pyotp
import time

# 1. 你的密钥
secret_key = "SL2F4XLMMACY2LKNKWYVAHWOUTSDHE27"

# 2. 创建 TOTP 对象
totp = pyotp.TOTP(secret_key)

# 3. 生成当前的 6 位验证码
current_code = totp.now()

print(f"当前时间: {time.strftime('%H:%M:%S')}")
print(f"生成的验证码: {current_code}")