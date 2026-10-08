"""入口：python run.py"""
import logging
import threading
import time

from flask import Flask, request

from app import handlers
from app.config import (DAILY_CHECK_TIME, HOST, PORT, WECOM_CORP_ID,
                        WECOM_ENCODING_AES_KEY, WECOM_TOKEN,
                        WEEKLY_REPORT_TIME, WEEKLY_REPORT_WEEKDAY)
from app.db import init_db
from app.wecom_crypto import WeComCrypto

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

crypto = WeComCrypto(WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID)
app = Flask(__name__)


def _daily_check_loop():
    """每天 DAILY_CHECK_TIME 跑一次健康日报并推送"""
    from app import agent
    log = logging.getLogger("daily-check")
    while True:
        try:
            report = agent.run_daily_check()
            log.info("健康日报已推送: %s", report[:60].replace("\n", " "))
        except Exception:
            log.exception("健康日报执行失败")
        time.sleep(agent.seconds_until_next_run(DAILY_CHECK_TIME))


def _weekly_report_loop():
    """每周 WEEKLY_REPORT_TIME（默认周日 20:30）推送周报+趋势图"""
    from app import agent
    log = logging.getLogger("weekly-report")
    while True:
        try:
            text, chart = agent.run_weekly_report()
            log.info("周报已推送: %s", text[:60].replace("\n", " "))
        except Exception:
            log.exception("周报执行失败")
        time.sleep(agent.seconds_until_next_weekly(WEEKLY_REPORT_WEEKDAY, WEEKLY_REPORT_TIME))


def start_background_jobs():
    threading.Thread(target=_daily_check_loop, daemon=True).start()
    threading.Thread(target=_weekly_report_loop, daemon=True).start()


@app.route("/wecom/callback", methods=["GET"])
def verify():
    """企业微信后台配置回调 URL 时的验证"""
    try:
        plain = crypto.verify_url(
            request.args.get("msg_signature", ""),
            request.args.get("timestamp", ""),
            request.args.get("nonce", ""),
            request.args.get("echostr", ""),
        )
        return plain
    except Exception:
        logging.getLogger(__name__).exception("URL 验证失败")
        return "fail", 400


@app.route("/wecom/callback", methods=["POST"])
def callback():
    try:
        msg = crypto.decrypt_message(
            request.args.get("msg_signature", ""),
            request.args.get("timestamp", ""),
            request.args.get("nonce", ""),
            request.get_data(),
        )
        handlers.handle_message(msg)
    except Exception:
        logging.getLogger(__name__).exception("回调处理异常")
    # 5 秒内必须响应，实际处理在后台线程
    return "ok"


if __name__ == "__main__":
    init_db()
    start_background_jobs()
    app.run(host=HOST, port=PORT)
