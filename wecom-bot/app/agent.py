"""医疗健康智能体"阿福"：日常监测数据分析 + 趋势预警 + 主动推送。
规则引擎按高血压等慢病指南硬编码（防幻觉），大模型只负责把统计结果讲成人话。"""
import logging
from datetime import datetime, timedelta

from . import db, vision, wecom_api
from .config import DEFAULT_MEMBER, MEMBER_PROFILE, WECOM_NOTIFY_USER

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是家庭健康监测助手"阿福"，服务对象是：{profile}。
你熟悉高血压、冠心病、糖尿病（三高）及脑卒中（脑梗）二级预防知识，负责分析日常监测数据并判断趋势。
参考标准：
- 血压理想 <120/80；有脑梗史的高血压患者一般控制目标 <140/90，且在医生指导下尽量平稳达标
- ≥160/100 需尽快复诊调整；≥180/120 属高血压急症风险，应尽快就医
- 老年脑梗患者同样警惕低血压（<90/60 或伴头晕乏力），可能提示灌注不足或降压过度
- 脉压差（收缩压-舒张压）正常 30-50mmHg；持续 ≥60 提示动脉僵硬度增加，是卒中/冠心病复发风险的独立预测指标
- 血压波动大（日间忽高忽低）对脑梗患者危害大，趋势比单次数值重要
- 静息心率持续 <50 或 >100 需关注；心悸/脉律不齐需排查房颤（卒中危险因素）
- 一周体重增加 >2kg 可能提示水钠潴留（心功能），需就诊评估
输出纯文本、分四节，每节简短：
【整体评估】四级之一：正常 / 注意 / 建议就诊 / 尽快就医
【数据解读】用数据说话，指出趋势（含脉压差与波动情况）
【建议】具体可执行（是否就医、监测频次、生活方式）
【提醒】本分析仅供健康管理参考，不能替代医生诊断
语气平稳，不制造恐慌，不过度诊断；数据不足时如实说明。"""


def _avg(vals):
    return round(sum(vals) / len(vals)) if vals else None


def _consecutive_high_days(rows, days=3):
    """连续 days 天内出现 ≥140/90 的天数"""
    dates = sorted({r["measured_at"][:10] for r in rows
                    if (r["systolic"] or 0) >= 140 or (r["diastolic"] or 0) >= 90})
    if len(dates) < days:
        return 0
    run = 1
    for a, b in zip(dates, dates[1:]):
        run = run + 1 if (datetime.strptime(b, "%Y-%m-%d") -
                          datetime.strptime(a, "%Y-%m-%d")).days == 1 else 1
    return run


def _build_stats(member=DEFAULT_MEMBER):
    bp14 = db.bp_recent_days(member, 14)
    week = [r for r in bp14 if r["measured_at"] >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
    prev = [r for r in bp14 if r["measured_at"] < (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
    stats = {"reading_count_7d": len(week)}
    if week:
        pp = [r["systolic"] - r["diastolic"] for r in week]
        stats.update({
            "avg_sys_7d": _avg([r["systolic"] for r in week]),
            "avg_dia_7d": _avg([r["diastolic"] for r in week]),
            "avg_hr_7d": _avg([r["heart_rate"] for r in week if r["heart_rate"]]),
            "max_sys_7d": max(r["systolic"] for r in week),
            "max_dia_7d": max(r["diastolic"] for r in week),
            "high_count_7d": sum(1 for r in week if r["systolic"] >= 140 or r["diastolic"] >= 90),
            "crisis": any(r["systolic"] >= 180 or r["diastolic"] >= 120 for r in week),
            "consec_high_days": _consecutive_high_days(week),
            "avg_pp_7d": _avg(pp),
            "max_pp_7d": max(pp),
            "wide_pp_count": sum(1 for p in pp if p >= 60),
            "low_bp_count": sum(1 for r in week if r["systolic"] < 90 or r["diastolic"] < 60),
        })
    if prev and len(prev) >= 2:
        stats["avg_sys_prev7d"] = _avg([r["systolic"] for r in prev])
        stats["avg_dia_prev7d"] = _avg([r["diastolic"] for r in prev])
    w7 = db.weight_recent_days(member, 7)
    wprev = db.weight_prev_days(member, 7)
    if w7:
        stats["weight_latest"] = w7[-1]["weight_kg"]
        if wprev:
            stats["weight_delta_7d"] = round(w7[-1]["weight_kg"] - wprev[-1]["weight_kg"], 1)
    ck = db.checkups(member, limit=1)
    if ck:
        stats["latest_checkup"] = f"{ck[0]['checkup_date'] or '日期未记录'}：{ck[0]['summary']}"
    return stats


def _rule_level(s):
    """规则引擎分级：比大模型可靠，级别以规则为准"""
    if s.get("crisis"):
        return "尽快就医", "近期出现 ≥180/120 的读数（高血压急症风险）"
    if s.get("reading_count_7d", 0) < 3:
        return "数据不足", "近7天有效测量不足3次"
    if s.get("low_bp_count"):
        return "注意", f"{s['low_bp_count']}次读数低于 90/60，需警惕灌注不足或降压过度（脑梗史患者尤其要紧）"
    if s.get("avg_sys_7d") and s["avg_sys_7d"] >= 160 or s.get("avg_dia_7d") and s["avg_dia_7d"] >= 100:
        return "建议就诊", "近7天平均血压 ≥160/100"
    if s.get("consec_high_days", 0) >= 3:
        return "建议就诊", f"连续{s['consec_high_days']}天出现 ≥140/90 的读数"
    if s.get("avg_sys_7d") and s["avg_sys_7d"] >= 140 or s.get("avg_dia_7d") and s["avg_dia_7d"] >= 90:
        return "注意", "近7天平均血压达到 140/90 以上"
    if s.get("avg_pp_7d") and s["avg_pp_7d"] >= 60:
        return "注意", f"近7天平均脉压差 {s['avg_pp_7d']}mmHg（≥60 提示动脉僵硬化，卒中风险升高）"
    trend = ""
    if s.get("avg_sys_prev7d"):
        d = s["avg_sys_7d"] - s["avg_sys_prev7d"]
        if d >= 10:
            return "注意", f"收缩压7天均值较上周上升{d}mmHg"
        trend = f"较上周{'上升' if d > 0 else '下降' if d < 0 else '持平'}{abs(d)}mmHg" if d != 0 else "与上周持平"
    if s.get("weight_delta_7d") is not None and s["weight_delta_7d"] >= 2:
        return "注意", f"一周体重增加{s['weight_delta_7d']}kg，需警惕水钠潴留"
    return "正常", trend or "各项指标在控制目标内"


def _stats_text(s):
    lines = []
    for k, label in [("reading_count_7d", "近7天测量次数"), ("avg_sys_7d", "收缩压7天均值"),
                     ("avg_dia_7d", "舒张压7天均值"), ("avg_hr_7d", "心率7天均值"),
                     ("max_sys_7d", "收缩压最高"), ("max_dia_7d", "舒张压最高"),
                     ("high_count_7d", "≥140/90次数"), ("consec_high_days", "连续超标天数"),
                     ("avg_pp_7d", "脉压差7天均值"), ("max_pp_7d", "脉压差最大"),
                     ("wide_pp_count", "脉压差≥60次数"), ("low_bp_count", "低血压(<90/60)次数"),
                     ("avg_sys_prev7d", "收缩压上周均值"), ("avg_dia_prev7d", "舒张压上周均值"),
                     ("weight_latest", "最新体重kg"), ("weight_delta_7d", "体重周变化kg")]:
        if s.get(k) is not None:
            lines.append(f"- {label}: {s[k]}")
    if s.get("crisis"):
        lines.append("- ⚠️ 出现过 ≥180/120 的读数")
    if s.get("latest_checkup"):
        lines.append(f"- 最近体检: {s['latest_checkup']}")
    return "\n".join(lines) or "（无数据）"


ASSESS_PROMPT = """你是家庭健康监测助手"阿福"，服务对象：{profile}。
针对本次这一条血压读数，写给医生的辅助判读，1-2句话、不超过60字：
聚焦本次读数是否达标（对照 <140/90）、压差是否正常（30-50）、有无异常信号、是否需要复诊。
不展开历史趋势长篇分析，只输出判读正文，不要标题和免责声明。"""


def record_assessment(systolic, diastolic, heart_rate, measured_at, stats):
    """单条血压记录的医院辅助判读（写入多维表格对应行）"""
    from .config import LLM_TEXT_MODEL
    user = (f"本次读数：{measured_at} {systolic}/{diastolic} mmHg，心率{heart_rate or '未知'}次/分\n"
            f"近期统计：\n{_stats_text(stats)}")
    note = vision._chat(LLM_TEXT_MODEL, [
        {"role": "system", "content": ASSESS_PROMPT.format(profile=MEMBER_PROFILE)},
        {"role": "user", "content": user}], temperature=0.2)
    return note.strip()[:300]


def generate_report(display="妈妈"):
    """生成健康监测报告（纯文本），不发送。display 仅用于展示，数据库查询固定用 DEFAULT_MEMBER"""
    stats = _build_stats()
    level, reason = _rule_level(stats)
    from .config import LLM_TEXT_MODEL
    user_msg = (f"监测对象：{display}\n规则引擎初判：{level}（{reason}）\n"
                f"近14天统计数据：\n{_stats_text(stats)}\n"
                "请按系统要求输出分析报告；整体评估级别以规则引擎初判为准，不得低于该级别。")
    try:
        report = vision._chat(LLM_TEXT_MODEL, [
            {"role": "system", "content": SYSTEM_PROMPT.format(profile=MEMBER_PROFILE)},
            {"role": "user", "content": user_msg}], temperature=0.3)
    except Exception:
        log.exception("大模型分析失败，使用规则引擎结果")
        report = f"【整体评估】{level}\n【原因】{reason}\n（大模型分析暂不可用）"
    return f"📋 妈妈的健康监测日报（{datetime.now():%m-%d %H:%M}）\n\n{report[:1500]}"


def run_daily_check(dry=False):
    """每日定时任务：生成报告并推送给全家"""
    report = generate_report()
    log.info("每日健康检查完成，级别线索见报告")
    if not dry:
        wecom_api.notify_family(report)
    return report


def run_weekly_report(dry=False):
    """每周任务：健康报告 + 近14天血压趋势图"""
    from . import chart as chart_mod
    from .config import LLM_TEXT_MODEL
    text = generate_report()
    chart_path = None
    try:
        chart_path = chart_mod.render_bp_trend(14)
    except Exception:
        log.exception("趋势图生成失败")
    if not dry:
        wecom_api.notify_family("📈 本周血压趋势报告\n\n" + text, image_path=chart_path)
    return text, chart_path


def seconds_until_next_run(hhmm="21:30"):
    import time as _t
    hh, mm = map(int, hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (_t.mktime(target.timetuple()) - _t.mktime(now.timetuple()))


def seconds_until_next_weekly(weekday=6, hhmm="20:30"):
    import time as _t
    hh, mm = map(int, hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    days_ahead = (weekday - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return _t.mktime(target.timetuple()) - _t.mktime(now.timetuple())
