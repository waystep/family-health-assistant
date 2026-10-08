"""分析引擎：血压分级（中国高血压指南）、趋势预警、回复文案、周报。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Member, Reading


def bp_category(systolic: float, diastolic: float) -> tuple[str, str]:
    """返回 (等级标签, 说明)。依据中国高血压防治指南分级。"""
    if systolic < 90 or diastolic < 60:
        return "偏低", "血压偏低，注意观察有无头晕乏力"
    if systolic >= 180 or diastolic >= 110:
        return "3级高血压", "血压重度升高，建议尽快就医"
    if systolic >= 160 or diastolic >= 100:
        return "2级高血压", "中度升高，建议近期咨询医生调整方案"
    if systolic >= 140 or diastolic >= 90:
        return "1级高血压", "达到高血压诊断线，注意休息复测"
    if systolic >= 120 or diastolic >= 80:
        return "正常高值", "处于正常偏高区间，建议清淡饮食、规律作息"
    return "正常", "血压正常，继续保持"


def week_stats(session: Session, member_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    week_ago = now - timedelta(days=7)
    bps = session.scalars(
        select(Reading).where(
            Reading.member_id == member_id,
            Reading.kind == "bp",
            Reading.measured_at >= week_ago,
        ).order_by(Reading.measured_at)
    ).all()
    elevated = [r for r in bps if r.systolic >= 140 or r.diastolic >= 90]
    # 连续超标天数（按自然日去重，从最近往前）
    days = sorted({r.measured_at.date() for r in elevated}, reverse=True)
    streak = 0
    for i, day in enumerate(days):
        if i == 0 or (days[i - 1] - day).days == 1:
            streak += 1
        else:
            break
    return {
        "count": len(bps),
        "elevated": len(elevated),
        "streak_days": streak,
        "latest": bps[-1] if bps else None,
    }


def build_reply(parsed_rows: list[dict], session: Session, now: datetime | None = None) -> str:
    """parsed_rows: [{member_name, kind, values..., measured_at, assumptions}]"""
    now = now or datetime.now()
    lines = []
    for row in parsed_rows:
        ts = row["measured_at"].strftime("%m-%d %H:%M") if row["measured_at"] else now.strftime("%m-%d %H:%M")
        if row["kind"] == "bp":
            sys_, dia = row["systolic"], row["diastolic"]
            label, advice = bp_category(sys_, dia)
            line = f"✅ {row['member_name']} {ts} 血压 {sys_:g}/{dia:g} mmHg"
            if row.get("heart_rate"):
                line += f" 心率 {row['heart_rate']:g}"
            line += f"\n{'' if label == '正常' else '⚠️ '}{label}｜{advice}"
            if label.startswith(("1", "2", "3")) or label == "偏低":
                stats = week_stats(session, row["member_id"], now)
                if stats["elevated"] > 1:
                    line += f"\n📈 本周第 {stats['elevated']} 次超标"
                if stats["streak_days"] >= 3:
                    line += f"，已连续 {stats['streak_days']} 天，建议就医咨询"
        else:
            line = f"✅ {row['member_name']} {ts} 体重 {row['weight_kg']:g} kg"
            if row.get("body_fat_pct"):
                line += f" 体脂 {row['body_fat_pct']:g}%"
            delta = weight_change(session, row["member_id"], row["weight_kg"], now)
            if delta is not None:
                arrow = "↑" if delta > 0 else "↓"
                line += f"（较上周 {arrow}{abs(delta):.1f}kg）"
        for note in row.get("assumptions", []):
            line += f"\nℹ️ {note}"
        lines.append(line)
    return "\n────────\n".join(lines)


def weight_change(session: Session, member_id: int, current_kg: float, now: datetime) -> float | None:
    week_ago = now - timedelta(days=7)
    ref = session.scalars(
        select(Reading).where(
            Reading.member_id == member_id,
            Reading.kind == "weight",
            Reading.measured_at >= week_ago - timedelta(days=1),
            Reading.measured_at < now - timedelta(days=6),
        ).order_by(Reading.measured_at.desc())
    ).first()
    return round(current_kg - ref.weight_kg, 1) if ref else None


HELP_TEXT = (
    "没看懂这条消息😅 请按类似格式发送：\n"
    "· 外婆 血压145/92 心率78\n"
    "· 妈妈 体重65.5公斤（或130斤）\n"
    "· 昨天早上 血压 135/85\n"
    "也可以直接拍血压计/体脂秤的照片发我"
)


def weekly_report(session: Session, member: Member, now: datetime | None = None) -> str:
    now = now or datetime.now()
    week_ago = now - timedelta(days=7)
    readings = session.scalars(
        select(Reading).where(
            Reading.member_id == member.id,
            Reading.measured_at >= week_ago,
        ).order_by(Reading.measured_at)
    ).all()
    bps = [r for r in readings if r.kind == "bp"]
    weights = [r for r in readings if r.kind == "weight"]
    lines = [f"📋 {member.name} 健康周报（{week_ago.strftime('%m-%d')} ~ {now.strftime('%m-%d')}）"]
    if bps:
        sys_avg = sum(r.systolic for r in bps) / len(bps)
        dia_avg = sum(r.diastolic for r in bps) / len(bps)
        peak = max(bps, key=lambda r: r.systolic + r.diastolic)
        elevated = [r for r in bps if r.systolic >= 140 or r.diastolic >= 90]
        label, _ = bp_category(sys_avg, dia_avg)
        lines.append(f"· 血压测量 {len(bps)} 次，平均 {sys_avg:.0f}/{dia_avg:.0f}（{label}）")
        lines.append(f"· 最高一次 {peak.systolic:g}/{peak.diastolic:g}（{peak.measured_at.strftime('%m-%d %H:%M')}）")
        lines.append(f"· 超标（≥140/90）{len(elevated)} 次" + (f"，集中于{elevated[-1].measured_at.strftime('%m-%d')}前后" if elevated else ""))
    else:
        lines.append("· 本周没有血压记录，建议每天早晚各测一次")
    if weights:
        change = weights[-1].weight_kg - weights[0].weight_kg
        lines.append(f"· 体重 {weights[-1].weight_kg:g}kg，本周{'↑' if change > 0 else '↓'}{abs(change):.1f}kg")
    lines.append("—— 数据来自家庭健康助手，仅供参考，不构成医疗建议")
    return "\n".join(lines)
