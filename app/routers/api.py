"""JSON API：微信桥入口、消息队列、手动补录、周报。均需令牌。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from .. import config
from ..models import Member, Outbox, Reading
from ..services import analysis, ingest

router = APIRouter(prefix="/api")


def check_token(request: Request, x_token: str = Header(default="")) -> None:
    token = x_token or request.query_params.get("token", "")
    if token != config.GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="令牌无效")


class IngestBody(BaseModel):
    text: str = ""
    image_b64: str = ""
    chat: str = ""
    sender: str = ""


class ReadingBody(BaseModel):
    member_id: int
    kind: str = "bp"  # bp / weight
    systolic: float = 0
    diastolic: float = 0
    heart_rate: float = 0
    weight_kg: float = 0
    body_fat_pct: float = 0
    measured_at: str = ""  # YYYY-MM-DD HH:MM，留空=现在


class MemberBody(BaseModel):
    name: str
    aliases: str = ""
    relation: str = ""
    note: str = ""


@router.post("/ingest")
def api_ingest(body: IngestBody, request: Request, x_token: str = Header(default="")):
    check_token(request, x_token)
    db = request.state.db
    if body.image_b64:
        return ingest.ingest_image(db, body.image_b64, body.chat, body.sender)
    if body.text.strip():
        return ingest.ingest_text(db, body.text.strip(), body.chat, body.sender)
    return {"ok": False, "reply": "空消息", "parsed": []}


@router.get("/outbox")
def api_outbox(request: Request, x_token: str = Header(default="")):
    """微信桥轮询：取走待发消息并标记已发。"""
    check_token(request, x_token)
    db = request.state.db
    pending = db.scalars(select(Outbox).where(Outbox.sent_at.is_(None)).order_by(Outbox.id)).all()
    out = [{"id": m.id, "target_chat": m.target_chat, "text": m.text} for m in pending]
    now = datetime.now()
    for m in pending:
        m.sent_at = now
    db.commit()
    return {"messages": out}


@router.post("/readings")
def api_reading(body: ReadingBody, request: Request, x_token: str = Header(default="")):
    check_token(request, x_token)
    db = request.state.db
    member = db.get(Member, body.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    ts = datetime.strptime(body.measured_at, "%Y-%m-%d %H:%M") if body.measured_at else datetime.now()
    r = Reading(
        member_id=member.id, kind=body.kind,
        systolic=body.systolic, diastolic=body.diastolic, heart_rate=body.heart_rate,
        weight_kg=body.weight_kg, body_fat_pct=body.body_fat_pct,
        measured_at=ts, source="manual",
    )
    db.add(r)
    db.commit()
    return {"ok": True, "id": r.id}


@router.get("/members")
def api_members(request: Request, x_token: str = Header(default="")):
    check_token(request, x_token)
    rows = request.state.db.scalars(select(Member)).all()
    return {"members": [{"id": m.id, "name": m.name, "aliases": m.aliases,
                         "relation": m.relation} for m in rows]}


@router.post("/members")
def api_member_add(body: MemberBody, request: Request, x_token: str = Header(default="")):
    check_token(request, x_token)
    db = request.state.db
    if db.scalar(select(Member).where(Member.name == body.name)):
        raise HTTPException(status_code=400, detail="成员已存在")
    m = Member(name=body.name.strip(), aliases=body.aliases.strip(),
               relation=body.relation.strip(), note=body.note.strip())
    db.add(m)
    db.commit()
    return {"ok": True, "id": m.id}


@router.get("/report/weekly")
def api_report(request: Request, member_id: int = 0, x_token: str = Header(default="")):
    check_token(request, x_token)
    db = request.state.db
    member = db.get(Member, member_id) if member_id else db.scalars(select(Member)).first()
    if not member:
        return {"report": "还没有家庭成员"}
    return {"report": analysis.weekly_report(db, member)}
