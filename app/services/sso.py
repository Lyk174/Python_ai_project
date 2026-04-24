# app/services/sso.py
import httpx
from fastapi import HTTPException, status
from app.core.config import settings


class WeChatOAuth:
    @staticmethod
    def get_authorization_url() -> str:
        redirect_uri = settings.WECHAT_REDIRECT_URI
        # 测试号可以使用 snsapi_userinfo 直接获取用户信息
        url = (
            f"https://open.weixin.qq.com/connect/oauth2/authorize?"
            f"appid={settings.WECHAT_APP_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=snsapi_userinfo"
            f"&state=STATE#wechat_redirect"
        )
        return url
    @staticmethod
    async def get_user_info(code: str) -> dict:
        # 1. 获取 access_token
        async with httpx.AsyncClient() as client:
            token_url = "https://api.weixin.qq.com/sns/oauth2/access_token"
            token_params = {
                "appid": settings.WECHAT_APP_ID,
                "secret": settings.WECHAT_APP_SECRET,
                "code": code,
                "grant_type": "authorization_code"
            }
            token_resp = await client.get(token_url, params=token_params)
            token_data = token_resp.json()
            if "errcode" in token_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"微信授权失败: {token_data.get('errmsg',"未知错误")}"
                )
            access_token = token_data["access_token"]
            openid = token_data["openid"]

            # 2. 获取用户信息
            userinfo_url = "https://api.weixin.qq.com/sns/userinfo"
            userinfo_params = {
                "access_token": access_token,
                "openid": openid,
                "lang": "zh_CN"
            }
            userinfo_resp = await client.get(userinfo_url, params=userinfo_params)
            user_info = userinfo_resp.json()

            if "errcode" in user_info:
                raise HTTPException(
                    status_code=400,
                    detail=f"获取微信用户信息失败: {user_info.get('errmsg',"未知错误")}"
                )
            return {
                "openid": openid,
                "nickname": user_info.get("nickname", ""),
                "avatar": user_info.get("headimgurl", ""),
                "sex": user_info.get("sex", 0),
                "country": user_info.get("country", ""),
                "province": user_info.get("province", ""),
                "city": user_info.get("city", "")
            }

class DingTalkOAuth:
    @staticmethod
    def get_authorization_url() -> str:
        return f"https://login.dingtalk.com/oauth2/auth?redirect_uri={settings.DINGTALK_REDIRECT_URI}&response_type=code&client_id={settings.DINGTALK_APP_ID}&scope=openid&state=STATE"

    @staticmethod
    async def get_user_info(code: str) -> dict:
        async with httpx.AsyncClient() as client:
            # 获取 access_token
            token_resp = await client.post(
                "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
                json={
                    "clientId": settings.DINGTALK_APP_ID,
                    "clientSecret": settings.DINGTALK_APP_SECRET,
                    "code": code,
                    "grantType": "authorization_code"
                }
            )
            token_data = token_resp.json()
            if "code" in token_data and token_data["code"] != "0":
                raise HTTPException(status_code=400, detail=f"钉钉授权失败: {token_data}")
            access_token = token_data["accessToken"]

            # 获取用户信息
            user_resp = await client.get(
                "https://api.dingtalk.com/v1.0/contact/users/me",
                headers={"x-acs-dingtalk-access-token": access_token}
            )
            user_info = user_resp.json()
            if "code" in user_info and user_info["code"] != "0":
                raise HTTPException(status_code=400, detail=f"获取钉钉用户信息失败: {user_info}")
            return {
                "userid": user_info["unionid"],  # 使用 unionid 作为唯一标识
                "nickname": user_info.get("nick", ""),
                "avatar": user_info.get("avatarUrl", "")
            }




