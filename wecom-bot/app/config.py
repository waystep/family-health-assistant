import os

from dotenv import load_dotenv

# 只读本目录的 .env，避免向上搜索误读旧项目配置
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE, ".env"))

# 企业微信自建应用
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = int(os.getenv("WECOM_AGENT_ID") or 0)
WECOM_CORP_SECRET = os.getenv("WECOM_CORP_SECRET", "")
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")

# 大模型（OpenAI 兼容接口，智谱示例: https://open.bigmodel.cn/api/paas/v4）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# 视觉模型：照片识别用；文本分析模型：阶段分析用
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "glm-5.3-flash")
LLM_VISION_FALLBACK = os.getenv("LLM_VISION_FALLBACK", "glm-4v-flash")
LLM_TEXT_MODEL = os.getenv("LLM_TEXT_MODEL", "glm-4-flash")

# 存储与文件
DB_PATH = os.getenv("DB_PATH", os.path.join(_BASE, "data", "health.db"))
IMAGE_DIR = os.path.join(_BASE, "data", "images")

# 家庭成员：母亲(血压/住院/体检主记录人) + 本人(体检)
MEMBERS = {"m": "妈妈", "i": "我"}
DEFAULT_MEMBER = "m"

# 飞书多维表格（可选：填了就把每条记录实时同步过去）
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_BITABLE_APP_TOKEN = os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
FEISHU_BP_TABLE_ID = os.getenv("FEISHU_BP_TABLE_ID", "")
FEISHU_CHECKUP_TABLE_ID = os.getenv("FEISHU_CHECKUP_TABLE_ID", "")
FEISHU_WEIGHT_TABLE_ID = os.getenv("FEISHU_WEIGHT_TABLE_ID", "")

# 健康日报：推送给谁（企微成员 userid，多人用逗号分隔）、每天几点跑
WECOM_NOTIFY_USER = os.getenv("WECOM_NOTIFY_USER", "TanJiaWei")
WECOM_NOTIFY_USERS = [u.strip() for u in os.getenv(
    "WECOM_NOTIFY_USERS", WECOM_NOTIFY_USER).split(",") if u.strip()]
DAILY_CHECK_TIME = os.getenv("DAILY_CHECK_TIME", "21:30")
# 周报：0=周一 … 6=周日
WEEKLY_REPORT_WEEKDAY = int(os.getenv("WEEKLY_REPORT_WEEKDAY", "6"))
WEEKLY_REPORT_TIME = os.getenv("WEEKLY_REPORT_TIME", "20:30")
# 家庭群机器人 webhook（企微客户群/群机器人地址，留空则仅逐人推送）
FAMILY_GROUP_WEBHOOK = os.getenv("FAMILY_GROUP_WEBHOOK", "")
# 企微内部群聊 ID（appchat 建群后获得；家人需装企业微信APP查看群消息）
FAMILY_CHAT_ID = os.getenv("FAMILY_CHAT_ID", "")
# 监测对象画像（用于医疗分析的背景信息，可按实际修改）
MEMBER_PROFILE = os.getenv("MEMBER_PROFILE", "老年女性，高血压病史多年，规律服药，每日监测血压")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8901"))
