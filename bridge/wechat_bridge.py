"""微信桥：wxauto UI 自动化，连接微信客户端与健康网关。

仅在 Windows + 微信桌面版（已登录）环境运行：
    pip install wxauto requests
    python wechat_bridge.py

职责：
1. 监听 .env 里 MONITOR_CHATS 配置的会话新消息 → POST /api/ingest
2. 把网关回复 SendMsg 回原会话
3. 轮询 /api/outbox，把提醒/周报发到 TARGET_CHAT

注意：wxauto 依赖微信客户端窗口，请保持电脑不锁屏、不休眠。
不同 wxauto 版本 API 略有差异，若报错请对照已安装版本的文档微调。
"""

import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

GATEWAY = f"http://127.0.0.1:{os.environ.get('PORT', '8900')}"
TOKEN = os.environ.get("GATEWAY_TOKEN", "change-me-please")
MONITOR_CHATS = [c.strip() for c in os.environ.get("MONITOR_CHATS", "文件传输助手").split(",") if c.strip()]
TARGET_CHAT = os.environ.get("TARGET_CHAT", "文件传输助手")
POLL_SECONDS = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")
session = requests.Session()
session.headers["X-Token"] = TOKEN


def ingest(chat: str, sender: str, text: str, image_b64: str = "") -> str | None:
    try:
        r = session.post(f"{GATEWAY}/api/ingest", json={
            "text": text, "image_b64": image_b64, "chat": chat, "sender": sender,
        }, timeout=30)
        return r.json().get("reply")
    except Exception as e:
        log.error("网关调用失败: %s", e)
        return None


def drain_outbox(wx) -> None:
    try:
        r = session.get(f"{GATEWAY}/api/outbox", timeout=10)
        for msg in r.json().get("messages", []):
            try:
                wx.SendMsg(msg["text"], who=msg["target_chat"] or TARGET_CHAT)
                log.info("已发送队列消息 #%s → %s", msg["id"], msg["target_chat"])
            except Exception as e:
                log.error("队列消息发送失败 #%s: %s", msg["id"], e)
    except Exception as e:
        log.error("拉取队列失败: %s", e)


def main() -> None:
    from wxauto import WeChat

    wx = WeChat()
    log.info("微信已连接，监听会话: %s", MONITOR_CHATS)
    for chat in MONITOR_CHATS:
        wx.AddListenChat(who=chat)

    last_outbox = 0.0
    while True:
        try:
            msgs = wx.GetListenMessage()
            for chat, mlist in (msgs or {}).items():
                for m in mlist:
                    # type=friend 为对方消息，self 为自己发出的（跳过避免循环）
                    if getattr(m, "type", "") != "friend":
                        continue
                    content = (getattr(m, "content", "") or "").strip()
                    info = getattr(m, "info", [])
                    sender = info[0] if isinstance(info, list) and info else chat
                    if not content:
                        continue
                    log.info("收到 [%s] %s: %s", chat, sender, content[:80])
                    reply = ingest(str(chat), str(sender), content)
                    if reply:
                        chat.SendMsg(reply)
                        log.info("已回复: %s", reply[:60].replace("\n", " "))
        except Exception as e:
            log.error("监听循环异常: %s", e)

        if time.time() - last_outbox > 30:  # 每30秒拉一次提醒/周报队列
            drain_outbox(wx)
            last_outbox = time.time()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
