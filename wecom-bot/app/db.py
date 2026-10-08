"""SQLite 存储：血压 / 体检 / 住院记录"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS blood_pressure (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                systolic INTEGER,
                diastolic INTEGER,
                heart_rate INTEGER,
                measured_at TEXT NOT NULL,       -- 测量时间 ISO
                image_path TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                checkup_date TEXT,
                summary TEXT,
                details_json TEXT,
                source_path TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hospitalization (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                hospital TEXT,
                admit_date TEXT,
                discharge_date TEXT,
                diagnosis TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS weight (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                measured_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # 旧库迁移：记录多维表格行 id，修正/删除时可直接定位远端记录
        cols = {r[1] for r in c.execute("PRAGMA table_info(blood_pressure)")}
        if "feishu_rid" not in cols:
            c.execute("ALTER TABLE blood_pressure ADD COLUMN feishu_rid TEXT")


def insert_bp(member: str, systolic: int, diastolic: int, heart_rate,
              measured_at: str, image_path: str, raw: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO blood_pressure(member, systolic, diastolic, heart_rate,"
            " measured_at, image_path, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (member, systolic, diastolic, heart_rate, measured_at,
             image_path, json.dumps(raw, ensure_ascii=False), datetime.now().isoformat()),
        )
        return cur.lastrowid


def last_bp(member: str):
    """最近一条血压记录（对话修正/撤销用），无记录返回 None"""
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM blood_pressure WHERE member=? "
            "ORDER BY measured_at DESC, id DESC LIMIT 1", (member,)).fetchone()
    return dict(r) if r else None


def set_feishu_rid(record_id: int, rid: str) -> None:
    """记录该条血压对应的多维表格行 id"""
    with _conn() as c:
        c.execute("UPDATE blood_pressure SET feishu_rid=? WHERE id=?", (rid, record_id))


def update_bp(record_id: int, changes: dict, history: dict) -> None:
    """按 id 更新血压记录（changes: 列名->新值），并把本次修正记入 raw_json 留痕"""
    with _conn() as c:
        row = c.execute("SELECT raw_json FROM blood_pressure WHERE id=?",
                        (record_id,)).fetchone()
        raw = {}
        if row and row["raw_json"]:
            try:
                raw = json.loads(row["raw_json"])
            except ValueError:
                raw = {}
        raw.setdefault("corrections", []).append(history)
        sets = ", ".join(f"{k}=?" for k in changes)
        c.execute(
            f"UPDATE blood_pressure SET {sets}, raw_json=? WHERE id=?",
            (*changes.values(), json.dumps(raw, ensure_ascii=False), record_id))


def delete_bp(record_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM blood_pressure WHERE id=?", (record_id,))


def insert_checkup(member: str, checkup_date: str, summary: str,
                   details: dict, source_path: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO checkup(member, checkup_date, summary, details_json,"
            " source_path, created_at) VALUES (?,?,?,?,?,?)",
            (member, checkup_date, summary, json.dumps(details, ensure_ascii=False),
             source_path, datetime.now().isoformat()),
        )
        return cur.lastrowid


def bp_today(member: str) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    return bp_range(member, today, today)


def bp_range(member: str, start: str, end: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM blood_pressure WHERE member=? AND substr(measured_at,1,10) "
            "BETWEEN ? AND ? ORDER BY measured_at", (member, start, end)).fetchall()
    return [dict(r) for r in rows]


def bp_recent_days(member: str, days: int = 30) -> list:
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return bp_range(member, start, "2099-12-31")


def checkups(member: str, limit: int = 5) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM checkup WHERE member=? ORDER BY checkup_date DESC LIMIT ?",
            (member, limit)).fetchall()
    return [dict(r) for r in rows]


def insert_weight(member: str, weight_kg: float, measured_at: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO weight(member, weight_kg, measured_at, created_at) VALUES (?,?,?,?)",
            (member, weight_kg, measured_at, datetime.now().isoformat()))
        return cur.lastrowid


def weight_recent_days(member: str, days: int) -> list:
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM weight WHERE member=? AND substr(measured_at,1,10) >= ? "
            "ORDER BY measured_at", (member, start)).fetchall()
    return [dict(r) for r in rows]


def weight_prev_days(member: str, days: int) -> list:
    """上一个 days 区间（用于对比周变化）"""
    end = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM weight WHERE member=? AND substr(measured_at,1,10) >= ? "
            "AND substr(measured_at,1,10) <= ? ORDER BY measured_at",
            (member, start, end)).fetchall()
    return [dict(r) for r in rows]
