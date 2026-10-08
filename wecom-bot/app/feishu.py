"""飞书多维表格同步：血压/体检记录写入用户的 Bitable（可选功能）"""
import logging
import os
import threading
import time
from datetime import datetime

import requests

from .config import (FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BITABLE_APP_TOKEN,
                     FEISHU_BP_TABLE_ID, FEISHU_CHECKUP_TABLE_ID)

log = logging.getLogger(__name__)

API = "https://open.feishu.cn/open-apis"
_lock = threading.Lock()
_token = {"value": "", "expire_at": 0}


def enabled() -> bool:
    return bool(FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_BITABLE_APP_TOKEN)


def _tenant_token() -> str:
    with _lock:
        if _token["value"] and time.time() < _token["expire_at"]:
            return _token["value"]
        r = requests.post(
            f"{API}/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10).json()
        if r.get("code"):
            raise RuntimeError(f"获取 tenant_access_token 失败: {r}")
        _token["value"] = r["tenant_access_token"]
        _token["expire_at"] = time.time() + r.get("expire", 7200) - 300
        return _token["value"]


_fields_cache = {"names": set(), "time": 0}


def _table_field_names(table_id: str) -> set:
    """表格现有字段名（缓存10分钟）。用户改表格结构时不至于同步失败"""
    with _lock:
        if _fields_cache["names"] and time.time() - _fields_cache["time"] < 600:
            return _fields_cache["names"]
    try:
        r = requests.get(
            f"{API}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}/tables/{table_id}/fields",
            headers={"Authorization": f"Bearer {_tenant_token()}"}, timeout=10).json()
        names = {f["field_name"] for f in (r.get("data") or {}).get("items") or []}
        if names:
            _fields_cache["names"] = names
            _fields_cache["time"] = time.time()
        return names
    except Exception:
        log.exception("查询多维表格字段失败")
        return set()


def _create_record(table_id: str, fields: dict) -> str:
    """新建记录，返回 record_id（失败抛异常）"""
    names = _table_field_names(table_id)
    if names:
        fields = {k: v for k, v in fields.items() if k in names}
    r = requests.post(
        f"{API}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}/tables/{table_id}/records",
        headers={"Authorization": f"Bearer {_tenant_token()}"},
        json={"fields": fields}, timeout=10).json()
    if r.get("code"):
        raise RuntimeError(f"写多维表格失败: {r}")
    return (r.get("data") or {}).get("record", {}).get("record_id", "")


def _update_record(table_id: str, record_id: str, fields: dict) -> None:
    names = _table_field_names(table_id)
    if names:
        fields = {k: v for k, v in fields.items() if k in names}
    r = requests.put(
        f"{API}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers={"Authorization": f"Bearer {_tenant_token()}"},
        json={"fields": fields}, timeout=10).json()
    if r.get("code"):
        raise RuntimeError(f"更新多维表格失败: {r}")


def _delete_record(table_id: str, record_id: str) -> None:
    r = requests.delete(
        f"{API}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers={"Authorization": f"Bearer {_tenant_token()}"}, timeout=10).json()
    if r.get("code"):
        raise RuntimeError(f"删除多维表格记录失败: {r}")


def find_bp_record_id(measured_at_ms: int) -> str:
    """按测量时间在血压表最近的记录里找 record_id（±2分钟），找不到返回空串"""
    try:
        r = requests.post(
            f"{API}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}/tables/{FEISHU_BP_TABLE_ID}/records/search",
            headers={"Authorization": f"Bearer {_tenant_token()}"},
            json={"sort": [{"field_name": "测量日期时间", "desc": True}], "page_size": 50},
            timeout=10).json()
        if r.get("code"):
            raise RuntimeError(f"查询多维表格失败: {r}")
        for rec in (r.get("data") or {}).get("items") or []:
            v = (rec.get("fields") or {}).get("测量日期时间")
            if isinstance(v, list):
                v = v[0] if v else None
            if isinstance(v, (int, float)) and abs(v - measured_at_ms) <= 120_000:
                return rec.get("record_id", "")
    except Exception:
        log.exception("按时间查找多维表格血压记录失败")
    return ""


def _upload_image(path: str) -> str:
    """上传图片到飞书（bitable 附件用），返回 file_token"""
    with open(path, "rb") as f:
        r = requests.post(
            f"{API}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {_tenant_token()}"},
            data={"file_name": os.path.basename(path), "parent_type": "bitable_image",
                  "parent_node": FEISHU_BITABLE_APP_TOKEN, "size": str(os.path.getsize(path))},
            files={"file": f}, timeout=60).json()
    if r.get("code"):
        raise RuntimeError(f"上传图片失败: {r}")
    return r["data"]["file_token"]


def sync_bp(member: str, systolic: int, diastolic: int, heart_rate,
            measured_at: str, n_today: int, image_path: str = "",
            assessment: str = "") -> str:
    """血压记录同步到多维表格；失败只记日志不影响主流程（本地 SQLite 已保存）
    返回新建行的 record_id（同步失败返回空串，供本地留档，修正时可直接定位）
    字段：测量日期时间/高压(mmHg)/低压(mmHg)/压差(mmHg)/心率/血压图片/医疗助手分析"""
    if not enabled() or not FEISHU_BP_TABLE_ID:
        return ""
    ts = datetime.strptime(measured_at[:16], "%Y-%m-%d %H:%M")
    fields = {
        "测量日期时间": int(ts.timestamp() * 1000),
        "高压（mmHg）": systolic,
        "低压（mmHg）": diastolic,
        "压差（mmHg）": systolic - diastolic,
    }
    if heart_rate:
        fields["心率"] = heart_rate
    if assessment:
        fields["医疗助手分析"] = assessment
    try:
        rid = ""
        if image_path and os.path.exists(image_path):
            fields["血压图片"] = [{"file_token": _upload_image(image_path)}]
        rid = _create_record(FEISHU_BP_TABLE_ID, fields)
        log.info("血压已同步飞书多维表格")
        return rid
    except Exception:
        log.exception("飞书血压同步失败（本地已保存，不影响记录）")
        return ""


def upsert_bp(measured_at_old: str, systolic: int, diastolic: int, heart_rate,
              measured_at: str, image_path: str = "", assessment: str = "",
              rid_hint: str = "") -> bool:
    """修正已同步的血压记录：优先用本地留档的行 id 定位，其次按旧测量时间查找；
    找不到（如当初同步失败）就按修正后的完整数据补建一条"""
    if not enabled() or not FEISHU_BP_TABLE_ID:
        return False
    ts = datetime.strptime(measured_at[:16], "%Y-%m-%d %H:%M")
    fields = {
        "测量日期时间": int(ts.timestamp() * 1000),
        "高压（mmHg）": systolic,
        "低压（mmHg）": diastolic,
        "压差（mmHg）": systolic - diastolic,
    }
    if heart_rate:
        fields["心率"] = heart_rate
    if assessment:
        fields["医疗助手分析"] = assessment
    try:
        old_ts = datetime.strptime(measured_at_old[:16], "%Y-%m-%d %H:%M")
        rid = rid_hint or find_bp_record_id(int(old_ts.timestamp() * 1000))
        if rid:
            _update_record(FEISHU_BP_TABLE_ID, rid, fields)
            log.info("血压修正已同步飞书多维表格")
        else:
            if image_path and os.path.exists(image_path):
                fields["血压图片"] = [{"file_token": _upload_image(image_path)}]
            _create_record(FEISHU_BP_TABLE_ID, fields)
            log.info("多维表格未找到原记录，已按修正值补建一条")
        return True
    except Exception:
        log.exception("飞书血压修正同步失败")
        return False


def delete_bp(measured_at_old: str, rid_hint: str = "") -> bool:
    """删除多维表格里的血压记录；远端本就没有（如未配置/未同步）视为成功"""
    if not enabled() or not FEISHU_BP_TABLE_ID:
        return False
    try:
        old_ts = datetime.strptime(measured_at_old[:16], "%Y-%m-%d %H:%M")
        rid = rid_hint or find_bp_record_id(int(old_ts.timestamp() * 1000))
        if not rid:
            log.warning("多维表格未找到待删除的血压记录（可能当初未同步），跳过远端删除")
            return True
        _delete_record(FEISHU_BP_TABLE_ID, rid)
        log.info("多维表格血压记录已删除")
        return True
    except Exception:
        log.exception("飞书血压删除同步失败")
        return False


def sync_checkup(member: str, checkup_date: str, summary: str,
                 items: list = None, image_path: str = "") -> None:
    if not enabled() or not FEISHU_CHECKUP_TABLE_ID:
        return
    fields = {"成员": member, "摘要": summary or ""}
    try:
        if checkup_date:
            ts = datetime.strptime(checkup_date[:10], "%Y-%m-%d")
            fields["体检日期"] = int(ts.timestamp() * 1000)
    except ValueError:
        pass
    if items:
        kv = [f"{i.get('name')}: {i.get('value')}" + (f"（{i['flag']}）" if i.get("flag") else "")
              for i in items if i.get("name") and i.get("value")]
        if kv:
            fields["关键指标"] = "\n".join(kv[:15])
    try:
        if image_path and os.path.exists(image_path):
            fields["报告图片"] = [{"file_token": _upload_image(image_path)}]
        _create_record(FEISHU_CHECKUP_TABLE_ID, fields)
        log.info("体检已同步飞书多维表格")
    except Exception:
        log.exception("飞书体检同步失败（本地已保存，不影响记录）")


def sync_weight(member: str, weight_kg: float, measured_at: str) -> None:
    if not enabled() or not FEISHU_WEIGHT_TABLE_ID:
        return
    try:
        ts = datetime.strptime(measured_at[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        ts = datetime.now()
    try:
        _create_record(FEISHU_WEIGHT_TABLE_ID, {
            "成员": member,
            "测量日期时间": int(ts.timestamp() * 1000),
            "体重kg": weight_kg,
        })
        log.info("体重已同步飞书多维表格")
    except Exception:
        log.exception("飞书体重同步失败（本地已保存，不影响记录）")
