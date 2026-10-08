"""模拟微信发消息，测试网关（Mac/Windows 均可运行）：

    python bridge/test_client.py "外婆 血压145/92 心率78"
    python bridge/test_client.py "妈妈 体重130斤"
    python bridge/test_client.py --outbox   # 查看待发送队列
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

GATEWAY = f"http://127.0.0.1:{os.environ.get('PORT', '8900')}"
TOKEN = os.environ.get("GATEWAY_TOKEN", "change-me-please")


def main() -> None:
    if not sys.argv[1:]:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--outbox":
        r = requests.get(f"{GATEWAY}/api/outbox", headers={"X-Token": TOKEN}, timeout=10)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
        return
    r = requests.post(f"{GATEWAY}/api/ingest", json={
        "text": sys.argv[1], "chat": "测试", "sender": "test_client",
    }, headers={"X-Token": TOKEN}, timeout=30)
    data = r.json()
    print("回复：")
    print(data.get("reply"))
    if data.get("parsed"):
        print("\n入库：", json.dumps(data["parsed"], ensure_ascii=False))


if __name__ == "__main__":
    main()
