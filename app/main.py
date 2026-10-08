"""家庭健康助手入口：python -m uvicorn app.main:app --port 8900"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .database import SessionLocal, init_db
from .models import Member, Outbox
from .routers import api, web
from .services import analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")


def _enqueue(text: str) -> None:
    db = SessionLocal()
    try:
        db.add(Outbox(target_chat=config.TARGET_CHAT, text=text))
        db.commit()
    finally:
        db.close()


def reminder_job() -> None:
    now = datetime.now(TZ)
    db = SessionLocal()
    try:
        names = [m.name for m in _enabled_members(db)]
    finally:
        db.close()
    who = "、".join(names) if names else "家人"
    _enqueue(f"⏰ 测量提醒（{now.strftime('%H:%M')}）：请给 {who} 测量血压/体重，测完直接发我：外婆 血压145/92")


def _enabled_members(db):
    from sqlalchemy import select

    return db.scalars(select(Member).where(Member.enabled == 1)).all()


def weekly_job() -> None:
    db = SessionLocal()
    try:
        for m in _enabled_members(db):
            _enqueue(analysis.weekly_report(db, m, datetime.now(TZ).replace(tzinfo=None)))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=str(TZ))
    for t in config.REMINDER_TIMES:
        hh, mm = t.split(":")
        scheduler.add_job(reminder_job, "cron", hour=int(hh), minute=int(mm), id=f"remind-{t}")
    rh, rm = config.REPORT_TIME.split(":")
    scheduler.add_job(weekly_job, "cron", day_of_week=config.REPORT_WEEKDAY,
                      hour=int(rh), minute=int(rm), id="weekly")
    scheduler.start()
    log.info("定时任务: 提醒%s 周报周%s %s", config.REMINDER_TIMES, config.REPORT_WEEKDAY, config.REPORT_TIME)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="家庭健康助手", lifespan=lifespan)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["dt"] = lambda v: v.strftime("%m-%d %H:%M") if v else "-"
app.state.templates = templates
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.middleware("http")
async def db_middleware(request: Request, call_next):
    session = SessionLocal()
    request.state.db = session
    try:
        return await call_next(request)
    finally:
        session.close()


app.include_router(web.router)
app.include_router(api.router)
