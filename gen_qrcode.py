import qrcode
import requests

# 1. 获取授权 URL（使用新的 appid）
resp = requests.get("http://localhost:8000/api/v1/auth/oauth/wechat?invite_code=ALTENTEfIOVCfB58cjNGRA")
url = resp.json()["authorization_url"]
print("授权链接:", url)

# 2. 生成二维码
qr = qrcode.make(url)
qr.save("wechat_login.png")
print("二维码已保存为 wechat_login.png，请用微信扫码")