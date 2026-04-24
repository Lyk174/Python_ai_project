# 生成密码哈希的脚本
from passlib.context import CryptContext
import bcrypt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 生成 testuser 的密码哈希
password = "password123"
hashed_password = pwd_context.hash(password)
print(hashed_password)