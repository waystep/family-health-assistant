"""消息处理：图片 → 识别入库；文本 → 查询/分析命令"""
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta

from .config import DEFAULT_MEMBER, IMAGE_DIR, MEMBERS, WECOM_NOTIFY_USERS
from . import agent, db, feishu, seven_seg, vision, wecom_api

log = logging.getLogger(__name__)

HELP = """家庭健康助手"阿福"，支持：
· 发血压计照片 → 自动识别并记录（每天早/中/晚各一次）
· 发体检报告照片 → 自动提取关键指标存档
· 识别错了？发「修正 血压138/85 心率76」→ 改最近一条记录（可只改其中一项）
· 发「修正 昨天心率76」「修正 8:15 心率76」→ 改指定的那条记录
· 发「修正 时间7点50」→ 改最近一条记录的测量时间
· 发「撤销」→ 删除最近一条血压记录
· 发送「体重 62.5」→ 记录体重（公斤，可带"斤"）
· 发送「今日」→ 查看今天的血压记录
· 发送「本周」→ 查看最近7天血压
· 发送「分析」→ 阿福生成近14天健康监测报告
· 每天 21:30 自动推送健康日报，异常趋势会提醒就医
· 发送「帮助」→ 显示本说明"""


def handle_message(msg: dict) -> None:
    """异步处理消息（回调需 5 秒内响应，识别耗时放在线程里）"""
    threading.Thread(target=_process, args=(msg,), daemon=True).start()


def _process(msg: dict) -> None:
    try:
        # 回调 JSON 里成员标识是 FromUserName；支持「妈妈/我」切换归属
        user = msg.get("FromUserName", "")
        log.info("收到消息: type=%s from=%s", msg.get("MsgType"), user)
        if msg.get("MsgType") == "image":
            _handle_image(msg, user)
        elif msg.get("MsgType") == "text":
            _handle_text(msg, user)
    except Exception:
        log.exception("处理消息失败")
        try:
            wecom_api.send_text(user, "处理出错了，请稍后重试或换个角度重新拍照。")
        except Exception:
            pass


def _handle_image(msg: dict, user: str) -> None:
    os.makedirs(IMAGE_DIR, exist_ok=True)
    path = os.path.join(IMAGE_DIR, f"{datetime.now():%Y%m%d}_{uuid.uuid4().hex[:8]}.jpg")
    wecom_api.download_media(msg["MediaId"], path)
    result = vision.recognize_image(path)
    rtype = result.get("type", "unknown")

    if rtype == "bp":
        member = DEFAULT_MEMBER  # 血压默认记妈妈
        if result.get("systolic") and result.get("diastolic"):
            # 七段码确定性识别：既交叉验证血压，也在视觉模型漏读心率时兜底
            try:
                ocr = seven_seg.read_blood_pressure(path)
            except Exception:
                log.exception("七段码识别异常")
                ocr = None
            if ocr:
                log.info("七段码读数: %s", ocr)
                if not result.get("heart_rate") and ocr.get("heart_rate"):
                    result["heart_rate"] = ocr["heart_rate"]
                    result["heart_rate_source"] = "seven_seg"
                    log.info("心率由七段码兜底: %s", result["heart_rate"])
            # 血压计显示的时间不可信（时钟可能没电了跑偏）：仅接受 [90天前, 明天] 内的值
            ts = result.get("measured_at")
            try:
                dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")
                now = datetime.now()
                if not (now - timedelta(days=90) <= dt <= now + timedelta(days=1)):
                    ts = None
            except (ValueError, TypeError):
                ts = None
            if not ts:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            rowid = db.insert_bp(member, int(result["systolic"]), int(result["diastolic"]),
                                 result.get("heart_rate"), ts, path, result)
            n = len(db.bp_today(member))
            if result.get("heart_rate"):
                hr = f"，心率 {result['heart_rate']}"
                fix_hint = ""
            else:
                hr = "，心率未读出"
                fix_hint = "\n💡 心率没识别到？回复「修正 心率XX」补记；数值有误发「修正 血压A/B 心率XX」。"
            tip = ""
            if int(result["systolic"]) >= 140 or int(result["diastolic"]) >= 90:
                tip = "\n⚠️ 偏高，如持续偏高请联系医生。"
            # 七段码交叉验证：两次读数不一致时提醒人工核对（照片反光/角度大时可能出现）
            if ocr and (abs(ocr["systolic"] - int(result["systolic"])) > 5 or
                        abs(ocr["diastolic"] - int(result["diastolic"])) > 5):
                tip += (f"\n⚠️ 两种识别结果不一致（另一读数 {ocr['systolic']}/{ocr['diastolic']}），"
                        f"请对照血压计屏幕核实，可用「修正」命令更正。")
            # 医院辅助判读：结合本次读数与近14天趋势生成，写入多维表格同行
            assessment = ""
            try:
                assessment = agent.record_assessment(
                    int(result["systolic"]), int(result["diastolic"]),
                    result.get("heart_rate"), ts, agent._build_stats())
            except Exception:
                log.exception("辅助判读生成失败")
            wecom_api.send_text(
                user,
                f"✅ 已记录：{ts} 第{n}次测量\n血压 {result['systolic']}/{result['diastolic']}{hr}{tip}{fix_hint}\n"
                f"今天已记录 {n}/3 次。")
            rid = feishu.sync_bp("妈妈", int(result["systolic"]), int(result["diastolic"]),
                                 result.get("heart_rate"), ts, n, image_path=path,
                                 assessment=assessment)
            if rid:
                db.set_feishu_rid(rowid, rid)
            # 家庭通知：记录同步 + 异常即时提醒（发送者本人已收到回复，不重复推）
            family_text = f"📊 妈妈血压记录\n{ts}  {result['systolic']}/{result['diastolic']} mmHg"
            if result.get("heart_rate"):
                family_text += f"，心率 {result['heart_rate']} 次/分"
            if int(result["systolic"]) >= 180 or int(result["diastolic"]) >= 120:
                family_text += "\n🚨 血压达到急症水平（≥180/120），请尽快就医！"
            elif int(result["systolic"]) >= 160 or int(result["diastolic"]) >= 100:
                family_text += "\n🚨 血压明显偏高，建议尽快复诊调整用药"
            elif int(result["systolic"]) >= 140 or int(result["diastolic"]) >= 90:
                family_text += "\n⚠️ 超过 140/90 控制目标，请注意复测观察"
            wecom_api.notify_family(family_text, image_path=path, exclude=user,
                                    users=WECOM_NOTIFY_USERS)
        else:
            wecom_api.send_text(user, "没能从照片中读出血压数值，请正对屏幕重拍一张试试。")
    elif rtype == "checkup":
        member = DEFAULT_MEMBER
        summary = result.get("summary", "")
        db.insert_checkup(member, result.get("report_date"), summary,
                          result, path)
        wecom_api.send_text(user, f"✅ 已存档体检/报告记录\n日期：{result.get('report_date') or '未识别'}\n{summary}")
        feishu.sync_checkup("妈妈", result.get("report_date") or "", summary,
                            items=result.get("items") or [], image_path=path)
    else:
        wecom_api.send_text(user, f"这张照片不像血压计或体检报告（{result.get('desc', '')}），未记录。")


def _handle_weight(text: str, user: str) -> bool:
    """识别「体重 62.5」类文字消息，记录体重。返回是否处理"""
    import re
    m = re.search(r"(体重|称重)\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)\s*(公斤|kg|斤)?", text)
    if not m:
        return False
    val = float(m.group(2))
    if m.group(3) == "斤":
        val = round(val / 2, 1)
    if not (25 <= val <= 200):
        wecom_api.send_text(user, "这个体重数值不太合理，请确认后重新发送（例如：体重 62.5）。")
        return True
    member = DEFAULT_MEMBER
    prev = db.weight_recent_days(member, 365)
    db.insert_weight(member, val, datetime.now().strftime("%Y-%m-%d %H:%M"))
    delta = f"（较上次{'+' if val >= prev[-1]['weight_kg'] else ''}{round(val - prev[-1]['weight_kg'], 1)}kg）" if prev else ""
    wecom_api.send_text(user, f"✅ 已记录体重 {val}kg{delta}")
    feishu.sync_weight(member, val, datetime.now().strftime("%Y-%m-%d %H:%M"))
    return True


CORRECTION_USAGE = ("修正用法（默认作用于最近一条血压记录）：\n"
                    "·「修正 血压138/85」改血压\n"
                    "·「修正 心率76」补记/改心率\n"
                    "·「修正 血压138/85 心率76」一起改\n"
                    "·「修正 昨天心率76」「修正 8:15 心率76」改指定那条\n"
                    "·「修正 时间7点50」改测量时间\n"
                    "·「撤销」删除最近一条血压记录")


def _hm_minutes(ts: str) -> int:
    """'YYYY-MM-DD HH:MM' → 当天分钟数，用于挑最接近的记录"""
    h, m = ts[11:16].split(":")
    return int(h) * 60 + int(m)


def _handle_correction(text: str, user: str) -> bool:
    """识别「修正 …」「撤销」：直接修改/删除血压记录（本地 + 多维表格）。
    照片识别错了不用去多维表格手动改，对话里一句话即可自我校验。
    可用 昨天/前天/9-5、几点几分 选中具体那条记录。"""
    import re
    if re.fullmatch(r"(撤销|撤销刚才|删除刚才|删掉刚才|删除上一条|删掉上一条)", text):
        row = db.last_bp(DEFAULT_MEMBER)
        if not row:
            wecom_api.send_text(user, "暂没有可撤销的血压记录。")
            return True
        desc = f"{row['measured_at'][5:16]}  {row['systolic']}/{row['diastolic']}" \
               + (f"  心率{row['heart_rate']}" if row["heart_rate"] else "")
        db.delete_bp(row["id"])
        synced = feishu.delete_bp(row["measured_at"], row.get("feishu_rid") or "")
        note = "，多维表格已同步删除 ✅" if synced else "，⚠️ 多维表格未能删除，请稍后手动检查"
        wecom_api.send_text(user, f"🗑 已删除最近一条记录：{desc}{note}")
        return True

    # 触发修正：显式关键词，或明确表达"识别错了"+ 带数字的句子
    if not re.search(r"(修正|更正|纠正|改正)", text):
        if not (re.search(r"(错了|看错|识别错|记录错)", text) and re.search(r"\d{2,3}", text)):
            return False

    # 先按 日期（昨天/前天/月-日）和/或 时间（选当天最接近的那条）定位要改的记录
    now = datetime.now()
    day_prefix = None
    if "前天" in text:
        day_prefix = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    elif "昨天" in text:
        day_prefix = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    m_day = re.search(r"(\d{1,2})[-月](\d{1,2})[日号]?", text)
    if m_day and 1 <= int(m_day.group(1)) <= 12 and 1 <= int(m_day.group(2)) <= 31:
        mo, dy = int(m_day.group(1)), int(m_day.group(2))
        year = now.year if (mo, dy) <= (now.month, now.day) else now.year - 1
        day_prefix = f"{year}-{mo:02d}-{dy:02d}"
    sel_min = None
    m_t = re.search(r"(\d{1,2})[点:：]\s*(\d{1,2})?", text)
    if m_t and int(m_t.group(1)) < 24 and int(m_t.group(2) or 0) < 60:
        sel_min = int(m_t.group(1)) * 60 + int(m_t.group(2) or 0)
    if day_prefix:
        rows = db.bp_range(DEFAULT_MEMBER, day_prefix, day_prefix)
    elif sel_min is not None:
        rows = db.bp_today(DEFAULT_MEMBER)
    else:
        latest = db.last_bp(DEFAULT_MEMBER)
        rows = [latest] if latest else []
    if not rows:
        wecom_api.send_text(user, f"{day_prefix or '今天'}没有可修正的血压记录。")
        return True
    row = min(rows, key=lambda r: abs(_hm_minutes(r["measured_at"]) - sel_min)) \
        if sel_min is not None else rows[-1]

    changes, from_to = {}, []
    m = re.search(r"(\d{2,3})\s*[／/]\s*(\d{2,3})", text)
    if m:
        s, d = int(m.group(1)), int(m.group(2))
        if 50 <= s <= 300 and 20 <= d <= 200:
            changes["systolic"], changes["diastolic"] = s, d
            from_to.append(f"血压 {row['systolic']}/{row['diastolic']} → {s}/{d}")
    m = re.search(r"心率[是:：]?\s*(\d{2,3})", text)
    if m and 30 <= int(m.group(1)) <= 220:
        changes["heart_rate"] = int(m.group(1))
        old_hr = row["heart_rate"] or "（空）"
        from_to.append(f"心率 {old_hr} → {changes['heart_rate']}")
    # 带「时间」关键字才是改时间，否则时间只用来选中记录
    m = re.search(r"时间\s*(\d{1,2})[点:：]\s*(\d{1,2})?", text)
    if m and int(m.group(1)) < 24 and int(m.group(2) or 0) < 60:
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        changes["measured_at"] = f"{row['measured_at'][:11]}{hh:02d}:{mm:02d}"
        from_to.append(f"时间 {row['measured_at'][11:16]} → {hh:02d}:{mm:02d}")

    if not changes:
        wecom_api.send_text(user, "没看出要改成什么。\n" + CORRECTION_USAGE)
        return True

    history = {"at": datetime.now().isoformat(timespec="seconds"),
               "from": {k: row[k] for k in changes}, "to": dict(changes)}
    new_ts = changes.get("measured_at", row["measured_at"])
    db.update_bp(row["id"], changes, history)

    # 数值或时间变了就重新生成医疗辅助判读，保持多维表格同行内容一致
    assessment = ""
    try:
        assessment = agent.record_assessment(
            changes.get("systolic", row["systolic"]),
            changes.get("diastolic", row["diastolic"]),
            changes.get("heart_rate", row["heart_rate"]),
            new_ts, agent._build_stats())
    except Exception:
        log.exception("修正后辅助判读生成失败")
    synced = feishu.upsert_bp(row["measured_at"],
                              changes.get("systolic", row["systolic"]),
                              changes.get("diastolic", row["diastolic"]),
                              changes.get("heart_rate", row["heart_rate"]),
                              new_ts, image_path=row.get("image_path") or "",
                              assessment=assessment,
                              rid_hint=row.get("feishu_rid") or "")
    note = "多维表格已同步 ✅" if synced else "⚠️ 多维表格未能更新，请稍后手动检查"
    wecom_api.send_text(
        user,
        f"✏️ 已修正 {row['measured_at'][5:16]} 的记录\n" + "\n".join(from_to) + f"\n{note}")
    return True


def _handle_text(msg: dict, user: str) -> None:
    text = (msg.get("Content") or "").strip().lower()
    if text in ("帮助", "help", "menu"):
        wecom_api.send_text(user, HELP)
    elif text in ("今日", "今天"):
        rows = db.bp_today(DEFAULT_MEMBER)
        wecom_api.send_text(user, _fmt_bp(f"妈妈今日血压（{len(rows)}/3）", rows))
    elif text == "本周":
        rows = db.bp_recent_days(DEFAULT_MEMBER, 7)
        wecom_api.send_text(user, _fmt_bp("妈妈最近7天血压", rows))
    elif text == "分析":
        wecom_api.send_text(user, "阿福正在分析近14天数据，请稍等…")
        wecom_api.send_text(user, agent.generate_report())
    elif _handle_correction(text, user):
        pass
    elif _handle_weight(text, user):
        pass
    elif text in ("我", "妈妈"):
        wecom_api.send_text(user, "当前版本默认记录为「妈妈」，本人体检报告会一起存档。")
    else:
        wecom_api.send_text(user, "收到。发送「帮助」查看用法；血压请发照片，体重可发「体重 62.5」。")


def _fmt_bp(title: str, rows: list) -> str:
    if not rows:
        return f"{title}\n（暂无记录）"
    lines = [f"{r['measured_at'][5:16]}  {r['systolic']}/{r['diastolic']}"
             + (f"  心率{r['heart_rate']}" if r['heart_rate'] else "") for r in rows]
    sys_vals = [r["systolic"] for r in rows]
    dia_vals = [r["diastolic"] for r in rows]
    avg = f"均值 {sum(sys_vals)//len(sys_vals)}/{sum(dia_vals)//len(dia_vals)}"
    return f"{title}\n" + "\n".join(lines) + f"\n{avg}"
