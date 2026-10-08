"""规则解析器：把中文口语化消息解析成结构化测量数据。

无需大模型即可工作。识别：
- 成员：按成员名/别名匹配（缺失时由调用方决定默认成员或追问）
- 血压：145/92、高压145低压92、收缩压145 舒张压92
- 心率：心率78
- 体重：体重65.5公斤、体重130斤（无单位时 ≥100 视为斤，其余视为公斤）
- 时间：今天/昨天/前天 + 早上/中午/下午/晚上/凌晨，默认此刻
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

HOUR_WORDS = {"凌晨": 5, "早上": 8, "上午": 9, "中午": 12, "下午": 15, "傍晚": 18, "晚上": 20, "夜里": 21}
DAY_WORDS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}


@dataclass
class Parsed:
    member_id: int = 0             # 规则命中成员后的 id
    member_name: str = ""
    member_hint: str = ""          # 消息中提到的成员称呼（可能未经匹配）
    systolic: float = 0
    diastolic: float = 0
    heart_rate: float = 0
    weight_kg: float = 0
    body_fat_pct: float = 0
    measured_at: datetime = field(default_factory=datetime.now)
    assumptions: list[str] = field(default_factory=list)  # 向用户说明的换算假设

    @property
    def has_bp(self) -> bool:
        return self.systolic > 0 and self.diastolic > 0

    @property
    def has_anything(self) -> bool:
        return self.has_bp or self.heart_rate > 0 or self.weight_kg > 0 or self.body_fat_pct > 0


def _match_member(text: str, members: list[tuple[int, str, str]]) -> tuple[int, str] | None:
    """members: [(id, name, aliases)]，按名称/别名子串匹配，返回 (id, 显示名)。"""
    for mid, name, aliases in members:
        for candidate in [name, *[a.strip() for a in aliases.split(",") if a.strip()]]:
            if candidate and candidate in text:
                return mid, name
    return None


def _parse_time(text: str, now: datetime) -> tuple[datetime, list[str]]:
    notes: list[str] = []
    result = now
    for word, delta in DAY_WORDS.items():
        if word in text:
            result = now - timedelta(days=delta)
            break
    for word, hour in HOUR_WORDS.items():
        if word in text:
            result = result.replace(hour=hour, minute=0, second=0, microsecond=0)
            break
    m = re.search(r"(\d{1,2})[点时:：](\d{1,2})?分?", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= hour <= 23:
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if result > now:
        result = now  # 不允许未来的时间
        notes.append("时间按当前时刻记录")
    return result, notes


def parse_text(text: str, members: list[tuple[int, str, str]], now: datetime | None = None) -> Parsed:
    now = now or datetime.now()
    p = Parsed()
    t = text.replace("，", " ").replace("。", " ").replace("？", " ")

    hit = _match_member(text, members)
    if hit:
        p.member_id, p.member_name = hit
        p.member_hint = hit[1]

    # 血压：145/92、145／92
    m = re.search(r"(\d{2,3})\s*[/／]\s*(\d{2,3})", t)
    # 高压145 低压92 / 收缩压145 舒张压92
    m_high = re.search(r"(?:高压|收缩压)\s*(\d{2,3})", t)
    m_low = re.search(r"(?:低压|舒张压)\s*(\d{2,3})", t)
    if m_high and m_low:
        p.systolic, p.diastolic = float(m_high.group(1)), float(m_low.group(1))
    elif m:
        sys_, dia = float(m.group(1)), float(m.group(2))
        if 60 <= sys_ <= 260 and 40 <= dia <= 180 and sys_ > dia:
            p.systolic, p.diastolic = sys_, dia
        else:
            p.systolic = p.diastolic = 0
    # "血压145" 单值（视为收缩压，需低压时追问）
    if not p.has_bp:
        m_single = re.search(r"血压\s*(?:是|为)?\s*(\d{2,3})", t)
        if m_single and not (m_high or m_low or m):
            p.systolic = float(m_single.group(1))

    m_hr = re.search(r"心率\s*(?:是|为)?\s*(\d{2,3})", t)
    if m_hr and 30 <= int(m_hr.group(1)) <= 220:
        p.heart_rate = float(m_hr.group(1))

    m_wt = re.search(r"体重\s*(?:是|为)?\s*(\d{2,3}(?:\.\d)?)\s*(公斤|千克|kg|斤|市斤)?", t, re.I)
    if m_wt:
        val = float(m_wt.group(1))
        unit = (m_wt.group(2) or "").lower()
        if unit in ("斤", "市斤"):
            p.weight_kg = val * 0.5
        elif unit in ("公斤", "千克", "kg"):
            p.weight_kg = val
        else:
            if val >= 100:
                p.weight_kg = val * 0.5
                p.assumptions.append(f"体重{val:g}按斤换算为{val * 0.5:g}公斤")
            else:
                p.weight_kg = val
                p.assumptions.append(f"体重按{val:g}公斤记录（如为斤请带单位重发）")

    m_bf = re.search(r"体脂\s*(?:率)?\s*(?:是|为)?\s*(\d{1,2}(?:\.\d)?)\s*%?", t)
    if m_bf:
        p.body_fat_pct = float(m_bf.group(1))

    p.measured_at, time_notes = _parse_time(text, now)
    p.assumptions.extend(time_notes)
    return p
