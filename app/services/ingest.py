"""消息入口编排：去重 → 解析（规则优先，LLM 兜底）→ 入库 → 分析 → 回复。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Member, ProcessedMsg, Reading
from ..nlp import llm
from ..nlp.parser import Parsed, parse_text
from . import analysis

log = logging.getLogger(__name__)


def _members(db: Session) -> list[tuple[int, str, str]]:
    rows = db.scalars(select(Member).where(Member.enabled == 1)).all()
    return [(m.id, m.name, m.aliases) for m in rows]


def _resolve_member(db: Session, p: Parsed) -> tuple[int, str] | None:
    if p.member_id:
        return p.member_id, p.member_name
    # LLM 给出的称呼再做一次匹配
    if p.member_hint:
        from ..nlp.parser import _match_member

        hit = _match_member(p.member_hint, _members(db))
        if hit:
            return hit
    # 只有一个成员时默认归他
    members = _members(db)
    if len(members) == 1:
        return members[0][0], members[0][1]
    default = db.scalar(select(Member).where(Member.enabled == 1).order_by(Member.id).limit(1))
    if default:
        return default.id, default.name
    return None


def _save_rows(db: Session, p: Parsed, member_id: int, member_name: str, source: str, raw: str, chat: str, sender: str) -> list[dict]:
    rows: list[dict] = []
    if p.has_bp:
        r = Reading(
            member_id=member_id, kind="bp", systolic=p.systolic, diastolic=p.diastolic,
            heart_rate=p.heart_rate, measured_at=p.measured_at,
            source=source, raw_text=raw[:500], chat=chat, sender=sender,
        )
        db.add(r)
        rows.append({"member_id": member_id, "member_name": member_name, "kind": "bp",
                     "systolic": p.systolic, "diastolic": p.diastolic, "heart_rate": p.heart_rate,
                     "measured_at": p.measured_at, "assumptions": p.assumptions})
    if p.weight_kg > 0 or p.body_fat_pct > 0:
        r = Reading(
            member_id=member_id, kind="weight", weight_kg=p.weight_kg,
            body_fat_pct=p.body_fat_pct, measured_at=p.measured_at,
            source=source, raw_text=raw[:500], chat=chat, sender=sender,
        )
        db.add(r)
        rows.append({"member_id": member_id, "member_name": member_name, "kind": "weight",
                     "weight_kg": p.weight_kg, "body_fat_pct": p.body_fat_pct,
                     "measured_at": p.measured_at,
                     "assumptions": [a for a in p.assumptions if "体重" in a] + [a for a in p.assumptions if "体重" not in a]})
    return rows


def ingest_text(db: Session, text: str, chat: str = "", sender: str = "") -> dict:
    """文本消息入口。返回 {ok, reply, parsed}。"""
    now = datetime.now()
    fp = hashlib.sha1(f"{chat}|{sender}|{text}|{now.strftime('%Y%m%d%H')}".encode()).hexdigest()
    seen = db.scalar(select(ProcessedMsg).where(ProcessedMsg.fingerprint == fp))
    if seen:
        return {"ok": True, "duplicate": True, "reply": seen.reply, "parsed": []}

    p = parse_text(text, _members(db), now)
    if not p.has_anything:
        # 规则没认出来 → LLM 兜底
        data = llm.parse_with_llm(text)
        if data:
            p = _llm_dict_to_parsed(data, p)
    if not p.has_anything:
        return {"ok": False, "reply": analysis.HELP_TEXT, "parsed": []}

    member = _resolve_member(db, p)
    if not member:
        return {"ok": False, "reply": "请先在健康助手网页里添加家庭成员，并在消息里写明是谁的测量（如：外婆 血压145/90）", "parsed": []}
    member_id, member_name = member
    if not p.member_hint:
        p.assumptions.append(f"未指明成员，默认记给「{member_name}」")

    rows = _save_rows(db, p, member_id, member_name, "text", text, chat, sender)
    db.commit()
    reply = analysis.build_reply(rows, db, now)
    db.add(ProcessedMsg(fingerprint=fp, reply=reply))
    db.commit()
    return {"ok": True, "reply": reply, "parsed": [
        {k: (v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v)
         for k, v in row.items() if k != "assumptions"} for row in rows
    ]}


def ingest_image(db: Session, image_b64: str, chat: str = "", sender: str = "") -> dict:
    """照片/截图入口：血压计、体脂秤、健康App截图。"""
    now = datetime.now()
    data = llm.parse_image_with_llm(image_b64)
    if not data:
        return {"ok": False, "reply": "图片识别需要配置大模型（.env 里的 LLM_VISION_MODEL），或改用文字发送：外婆 血压145/92", "parsed": []}
    p = _llm_dict_to_parsed(data, parse_text("", _members(db), now))
    if not p.has_anything:
        return {"ok": False, "reply": "从图片里没认出测量数据，试着拍清楚数值区域再发一次？", "parsed": []}
    member = _resolve_member(db, p)
    if not member:
        return {"ok": False, "reply": "识别到了数据，但请告诉我是谁的（回复：外婆 血压145/92 这样的格式）", "parsed": []}
    member_id, member_name = member
    if not p.member_hint:
        p.assumptions.append(f"未指明成员，默认记给「{member_name}」")
    rows = _save_rows(db, p, member_id, member_name, "photo", "[图片]", chat, sender)
    db.commit()
    reply = analysis.build_reply(rows, db, now)
    return {"ok": True, "reply": reply, "parsed": []}


def _llm_dict_to_parsed(data: dict, base: Parsed) -> Parsed:
    """把 LLM 返回的 JSON 合并进 Parsed（LLM 结果优先，缺省沿用规则解析的时间等）。"""
    def num(key):
        try:
            v = float(data.get(key) or 0)
            return v if v > 0 else 0
        except (TypeError, ValueError):
            return 0

    p = base
    p.member_hint = (data.get("member_hint") or "").strip() or p.member_hint
    p.systolic = num("systolic")
    p.diastolic = num("diastolic")
    p.heart_rate = num("heart_rate")
    if p.systolic and not p.diastolic:
        p.systolic = 0  # LLM 只给了收缩压而没给舒张压时放弃，避免脏数据
    w, unit = num("weight_kg"), (data.get("weight_unit") or "").lower()
    if w:
        p.weight_kg = w * 0.5 if unit == "jin" else w
        if not unit and w >= 100:
            p.weight_kg = w * 0.5
            p.assumptions.append(f"体重{w:g}按斤换算为{w * 0.5:g}公斤")
    p.body_fat_pct = num("body_fat_pct")
    if p.has_anything and not p.assumptions:
        p.assumptions.append("由 AI 识别")
    return p
