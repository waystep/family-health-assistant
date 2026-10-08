"""血压趋势图生成（matplotlib，服务器需安装中文字体 fonts-noto-cjk）"""
import logging
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from . import db
from .config import DEFAULT_MEMBER

log = logging.getLogger(__name__)

CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "charts")


def _setup_cjk_font():
    for name in ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "PingFang SC", "Arial Unicode MS"]:
        try:
            if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
                plt.rcParams["font.sans-serif"] = [name]
                plt.rcParams["axes.unicode_minus"] = False
                return name
        except Exception:
            continue
    return None


def render_bp_trend(days: int = 14, member: str = DEFAULT_MEMBER,
                    display: str = "妈妈") -> str:
    """生成近 N 天血压趋势图 PNG，返回路径；数据不足返回 None。member 是数据库键"""
    rows = db.bp_recent_days(member, days)
    if len(rows) < 2:
        return None
    _setup_cjk_font()
    xs = [datetime.strptime(r["measured_at"][:16], "%Y-%m-%d %H:%M") for r in rows]
    sys_v = [r["systolic"] for r in rows]
    dia_v = [r["diastolic"] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=110)
    ax.plot(xs, sys_v, "o-", color="#d62728", label="收缩压（高压）", linewidth=1.8, markersize=4)
    ax.plot(xs, dia_v, "s-", color="#1f77b4", label="舒张压（低压）", linewidth=1.8, markersize=4)
    ax.axhline(140, color="#d62728", linestyle="--", alpha=0.5, linewidth=1)
    ax.axhline(90, color="#1f77b4", linestyle="--", alpha=0.5, linewidth=1)
    ax.text(xs[0], 141, "140", color="#d62728", fontsize=8, alpha=0.7)
    ax.text(xs[0], 91, "90", color="#1f77b4", fontsize=8, alpha=0.7)
    avg_s, avg_d = sum(sys_v) // len(sys_v), sum(dia_v) // len(dia_v)
    ax.set_title(f"{display}近{days}天血压趋势   均值 {avg_s}/{avg_d} mmHg   共{len(rows)}次测量", fontsize=12)
    ax.set_ylabel("mmHg")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()

    os.makedirs(CHART_DIR, exist_ok=True)
    out = os.path.join(CHART_DIR, f"bp_trend_{datetime.now():%Y%m%d_%H%M}.png")
    fig.savefig(out)
    plt.close(fig)
    return out
