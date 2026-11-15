"""用 refresh token 换取只读 access token；不保存账户密码。"""
import requests
from . import config


def access_token():
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_REFRESH_TOKEN):
        raise RuntimeError("Google 未授权：请先运行 local_agent/get_google_token.py")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "refresh_token": config.GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token"}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def get(url, params=None):
    r = requests.get(url, params=params, timeout=30,
                     headers={"Authorization": f"Bearer {access_token()}"})
    r.raise_for_status()
    return r.json()
