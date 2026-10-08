"""页面路由：总览 / 记录 / 成员 / 周报。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Member, Reading
from ..services import analysis

router = APIRouter()


def _member_cards(db: Session) -> list[dict]:
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    cards = []
    for m in db.scalars(select(Member).where(Member.enabled == 1).order_by(Member.id)).all():
        latest_bp = db.scalars(
            select(Reading).where(Reading.member_id == m.id, Reading.kind == "bp")
            .order_by(Reading.measured_at.desc()).limit(1)
        ).first()
        latest_wt = db.scalars(
            select(Reading).where(Reading.member_id == m.id, Reading.kind == "weight")
            .order_by(Reading.measured_at.desc()).limit(1)
        ).first()
        week_bps = db.scalars(
            select(Reading).where(Reading.member_id == m.id, Reading.kind == "bp",
                                  Reading.measured_at >= week_ago)
        ).all()
        elevated = len([r for r in week_bps if r.systolic >= 140 or r.diastolic >= 90])
        card = {"member": m, "bp": latest_bp, "weight": latest_wt,
                "week_count": len(week_bps), "week_elevated": elevated}
        if latest_bp:
            card["label"], card["advice"] = analysis.bp_category(latest_bp.systolic, latest_bp.diastolic)
        cards.append(card)
    return cards


@router.get("/")
def dashboard(request: Request):
    db: Session = request.state.db
    cards = _member_cards(db)
    selected_id = int(request.query_params.get("member") or 0) or (cards[0]["member"].id if cards else 0)
    series_bp, series_wt = [], []
    if selected_id:
        month_ago = datetime.now() - timedelta(days=30)
        rows = db.scalars(
            select(Reading).where(Reading.member_id == selected_id, Reading.measured_at >= month_ago)
            .order_by(Reading.measured_at)
        ).all()
        series_bp = [{"t": r.measured_at.strftime("%m-%d %H:%M"), "sys": r.systolic,
                      "dia": r.diastolic, "hr": r.heart_rate} for r in rows if r.kind == "bp"]
        series_wt = [{"t": r.measured_at.strftime("%m-%d %H:%M"), "kg": r.weight_kg}
                     for r in rows if r.kind == "weight"]
    recent = db.scalars(select(Reading).order_by(Reading.measured_at.desc()).limit(20)).all()
    week_ago = datetime.now() - timedelta(days=7)
    warnings = [
        r for r in db.scalars(
            select(Reading).where(Reading.kind == "bp", Reading.measured_at >= week_ago)
            .order_by(Reading.measured_at.desc())
        ).all()
        if r.systolic >= 140 or r.diastolic >= 90
    ]
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", {
        "page": "dashboard", "cards": cards, "members": db.scalars(select(Member)).all(),
        "selected_id": selected_id, "series_bp": series_bp, "series_wt": series_wt,
        "recent": recent, "warnings": warnings,
    })


@router.get("/readings")
def readings_page(request: Request):
    db: Session = request.state.db
    readings = db.scalars(select(Reading).order_by(Reading.measured_at.desc()).limit(100)).all()
    members = db.scalars(select(Member).order_by(Member.id)).all()
    return request.app.state.templates.TemplateResponse(request, "readings.html", {
        "page": "readings", "readings": readings, "members": members,
        "now": datetime.now().strftime("%Y-%m-%dT%H:%M"),
    })


@router.post("/readings")
def add_reading(request: Request, member_id: int = Form(...), kind: str = Form("bp"),
                systolic: float = Form(0), diastolic: float = Form(0), heart_rate: float = Form(0),
                weight_kg: float = Form(0), body_fat_pct: float = Form(0), measured_at: str = Form("")):
    db: Session = request.state.db
    ts = datetime.fromisoformat(measured_at) if measured_at else datetime.now()
    db.add(Reading(member_id=member_id, kind=kind, systolic=systolic, diastolic=diastolic,
                   heart_rate=heart_rate, weight_kg=weight_kg, body_fat_pct=body_fat_pct,
                   measured_at=ts, source="manual"))
    db.commit()
    return RedirectResponse("/readings?msg=已补录", status_code=303)


@router.post("/readings/{rid}/delete")
def delete_reading(request: Request, rid: int):
    db: Session = request.state.db
    r = db.get(Reading, rid)
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse("/readings?msg=已删除", status_code=303)


@router.get("/members")
def members_page(request: Request):
    db: Session = request.state.db
    members = db.scalars(select(Member).order_by(Member.id)).all()
    return request.app.state.templates.TemplateResponse(request, "members.html", {
        "page": "members", "members": members,
    })


@router.post("/members")
def add_member(request: Request, name: str = Form(...), aliases: str = Form(""),
               relation: str = Form(""), note: str = Form("")):
    db: Session = request.state.db
    db.add(Member(name=name.strip(), aliases=aliases.strip(), relation=relation.strip(), note=note.strip()))
    db.commit()
    return RedirectResponse("/members?msg=成员已添加", status_code=303)


@router.post("/members/{mid}/delete")
def delete_member(request: Request, mid: int):
    db: Session = request.state.db
    m = db.get(Member, mid)
    if m:
        db.delete(m)  # 级联删除测量记录
        db.commit()
    return RedirectResponse("/members?msg=已删除", status_code=303)


@router.get("/report")
def report_page(request: Request):
    db: Session = request.state.db
    members = db.scalars(select(Member)).all()
    member_id = int(request.query_params.get("member") or 0) or (members[0].id if members else 0)
    report = ""
    if member_id:
        member = db.get(Member, member_id)
        if member:
            report = analysis.weekly_report(db, member)
    return request.app.state.templates.TemplateResponse(request, "report.html", {
        "page": "report", "members": members, "member_id": member_id, "report": report,
    })
