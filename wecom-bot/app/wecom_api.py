"""企业微信自建应用 API：access_token 缓存、媒体下载/上传、主动发消息、家庭群 webhook"""
import base64
import hashlib
import logging
import threading
import time

import requests

from .config import FAMILY_CHAT_ID, FAMILY_GROUP_WEBHOOK, WECOM_AGENT_ID, WECOM_CORP_ID, WECOM_CORP_SECRET

log = logging.getLogger(__name__)

_token_lock = threading.Lock()
_token_cache = {"value": "", "expire_at": 0}

API = "https://qyapi.weixin.qq.com/cgi-bin"


def _access_token() -> str:
    with _token_lock:
        if _token_cache["value"] and time.time() < _token_cache["expire_at"]:
            return _token_cache["value"]
        r = requests.get(
            f"{API}/gettoken",
            params={"corpid": WECOM_CORP_ID, "corpsecret": WECOM_CORP_SECRET},
            timeout=10,
        ).json()
        if r.get("errcode"):
            raise RuntimeError(f"获取 access_token 失败: {r}")
        _token_cache["value"] = r["access_token"]
        _token_cache["expire_at"] = time.time() + r.get("expires_in", 7200) - 300
        return _token_cache["value"]


def download_media(media_id: str, save_path: str) -> str:
    """下载图片/文件媒体到本地，返回路径"""
    r = requests.get(
        f"{API}/media/get",
        params={"access_token": _access_token(), "media_id": media_id},
        timeout=60,
    )
    if r.headers.get("Content-Type", "").startswith("application/json"):
        raise RuntimeError(f"下载媒体失败: {r.json()}")
    with open(save_path, "wb") as f:
        f.write(r.content)
    return save_path


def send_text(user: str, content: str) -> None:
    """给指定成员主动推送文本消息"""
    r = requests.post(
        f"{API}/message/send",
        params={"access_token": _access_token()},
        json={
            "touser": user,
            "msgtype": "text",
            "agentid": WECOM_AGENT_ID,
            "text": {"content": content},
        },
        timeout=10,
    ).json()
    if r.get("errcode"):
        log.error("发送消息失败: %s", r)


def upload_media_image(path: str) -> str:
    """上传临时图片素材（用于应用图片消息），返回 media_id"""
    with open(path, "rb") as f:
        r = requests.post(
            f"{API}/media/upload",
            params={"access_token": _access_token(), "type": "image"},
            files={"media": f}, timeout=60).json()
    if r.get("errcode"):
        raise RuntimeError(f"上传素材失败: {r}")
    return r["media_id"]


def send_image(user: str, path: str) -> None:
    media_id = upload_media_image(path)
    r = requests.post(
        f"{API}/message/send",
        params={"access_token": _access_token()},
        json={
            "touser": user,
            "msgtype": "image",
            "agentid": WECOM_AGENT_ID,
            "image": {"media_id": media_id},
        },
        timeout=10,
    ).json()
    if r.get("errcode"):
        log.error("发送图片失败: %s", r)


def _post_group_webhook(payload: dict) -> None:
    if not FAMILY_GROUP_WEBHOOK:
        return
    try:
        r = requests.post(FAMILY_GROUP_WEBHOOK, json=payload, timeout=10).json()
        if r.get("errcode"):
            log.error("家庭群 webhook 推送失败: %s", r)
    except Exception:
        log.exception("家庭群 webhook 请求异常")


def _appchat_send(msgtype: str, payload: dict) -> None:
    if not FAMILY_CHAT_ID:
        return
    try:
        body = {"chatid": FAMILY_CHAT_ID, "msgtype": msgtype, **payload}
        r = requests.post(f"{API}/appchat/send", params={"access_token": _access_token()},
                          json=body, timeout=10).json()
        if r.get("errcode"):
            log.error("家庭群(appchat)推送失败: %s", r)
    except Exception:
        log.exception("家庭群(appchat)请求异常")


def notify_family(text: str, image_path: str = None, exclude: str = None,
                  users=None) -> None:
    """家庭通知：逐人推送应用消息 + 内部群 appchat + 群机器人 webhook（配置了才发）
    exclude 用于排除发送者本人（已收到过回复，避免重复）"""
    for u in (users if users is not None else []):
        if exclude and u == exclude:
            continue
        try:
            if image_path:
                send_image(u, image_path)
            send_text(u, text)
        except Exception:
            log.exception("推送家庭通知失败: %s", u)
    if FAMILY_CHAT_ID:
        media_id = None
        if image_path:
            try:
                media_id = upload_media_image(image_path)
                _appchat_send("image", {"image": {"media_id": media_id}})
            except Exception:
                log.exception("家庭群图片推送失败")
        _appchat_send("text", {"text": {"content": text}})
    if FAMILY_GROUP_WEBHOOK:
        if image_path:
            with open(image_path, "rb") as f:
                data = f.read()
            _post_group_webhook({"msgtype": "image", "image": {
                "base64": base64.b64encode(data).decode(),
                "md5": hashlib.md5(data).hexdigest()}})
        _post_group_webhook({"msgtype": "text", "text": {"content": text}})
