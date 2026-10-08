"""配置：从项目根目录 .env 读取。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "change-me-please")
PORT = int(os.environ.get("PORT", "8900"))

MONITOR_CHATS = [c.strip() for c in os.environ.get("MONITOR_CHATS", "文件传输助手").split(",") if c.strip()]
TARGET_CHAT = os.environ.get("TARGET_CHAT", "文件传输助手")

REMINDER_TIMES = [t.strip() for t in os.environ.get("REMINDER_TIMES", "").split(",") if t.strip()]
REPORT_WEEKDAY = int(os.environ.get("REPORT_WEEKDAY", "6"))  # 0=周一 .. 6=周日
REPORT_TIME = os.environ.get("REPORT_TIME", "20:30")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_VISION_MODEL = os.environ.get("LLM_VISION_MODEL", "")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def llm_enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_MODEL)


def vision_enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_VISION_MODEL)
