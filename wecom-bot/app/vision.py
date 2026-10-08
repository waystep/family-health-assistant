"""多模态大模型识别：照片分类 + 结构化提取；文本分析"""
import base64
import io
import json
import logging
import re

import requests

from .config import (LLM_API_KEY, LLM_BASE_URL, LLM_TEXT_MODEL, LLM_VISION_FALLBACK,
                     LLM_VISION_MODEL)

log = logging.getLogger(__name__)


def _b64_image(content: bytes) -> str:
    return base64.b64encode(content).decode()


def _enlarged_b64(image_path: str, factor: int = 2) -> str:
    """整图放大：屏幕角落的小字（如心率）在整图里容易糊，放大后可读性更好；
    整图版不依赖裁剪坐标，照片旋转/倾斜时仍能读到"""
    from PIL import Image
    with open(image_path, "rb") as f:
        img = Image.open(io.BytesIO(f.read())).convert("RGB")
    bigger = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)
    buf = io.BytesIO()
    bigger.save(buf, format="JPEG", quality=90)
    return _b64_image(buf.getvalue())


def _norm_int(v, lo=None, hi=None):
    """模型可能把数字输出成 "72"、72.0、"72次/分"，统一成 int；非法或越界返回 None"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float):
        v = int(round(v))
    elif isinstance(v, str):
        m = re.search(r"\d{1,3}", v)
        v = int(m.group()) if m else None
    if not isinstance(v, int):
        return None
    if lo is not None and not (lo <= v <= hi):
        return None
    return v

BP_PROMPT = """你是家庭健康助手。看这张照片，判断它属于哪类并提取数据，只输出一个 JSON 对象：
1) 电子血压计/血压读数照片：
{"type":"bp","systolic":收缩压,"diastolic":舒张压,"heart_rate":心率或null,"measured_at":"测量时间 YYYY-MM-DD HH:MM，照片没有则填null"}
读数要点：
- 拍摄角度可能旋转/倾斜：先在脑内把屏幕转正再读
- 高压和低压是两组大数字；心率（脉搏）数字较小，通常在大数字下方或心形图标旁——重点看放大图里的小数字，找到了就填，确实没有才填null
- TIME/CLOCK 附近是时间；mmHg 彩色刻度条上的 120/140/180 是分级刻度，都不是血压读数
2) 体检报告/化验单照片：
{"type":"checkup","report_date":"报告日期或null","summary":"一句话总结这张报告的关键结论","items":[{"name":"项目名","value":"结果","flag":"正常/偏高/偏低/异常或null"}]}
3) 其他照片：
{"type":"unknown","desc":"简述照片内容"}
只输出 JSON，不要多余文字。数值必须是数字。"""

ANALYZE_PROMPT = """你是一名健康管理顾问。以下是{member}近{days}天的血压记录和最近的体检摘要。
血压记录（时间 收缩压/舒张压 心率）：
{bp}
体检记录：
{checkup}
请用中文输出简明分析：1) 血压控制情况（对照 <140/90 标准，高血压患者<130/80 更理想）；2) 趋势与规律（早晚差异、异常值）；3) 需要留意的信号；4) 2-3条具体建议。语气平和，结尾提醒"仅供参考，具体请遵医嘱"。不要使用 Markdown 标题符号。"""

PULSE_PROMPT = """这是血压计屏幕的照片（可能是局部放大裁剪，也可能整体旋转/倾斜，读数前先在脑内把屏幕转正）。请找出心率/脉搏数字（通常在心形图标♥旁或血压大数字下方，比血压数字小，一般是两位数）。
注意：TIME/CLOCK 旁的时间、mmHg 彩色刻度条上的数字都不是心率。确实找不到才填null。
只输出一个 JSON：{"heart_rate": 数字或null}"""


def _chat(model: str, messages: list, temperature: float = 0.1) -> str:
    r = requests.post(
        f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={"model": model, "messages": messages, "temperature": temperature},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _chat_vision(messages: list, temperature: float = 0.1) -> str:
    """视觉调用：主模型失败（余额不足/限流等）自动回落备用模型"""
    last_err = None
    for m in dict.fromkeys([LLM_VISION_MODEL, LLM_VISION_FALLBACK]):
        try:
            return _chat(m, messages, temperature)
        except (requests.HTTPError, requests.RequestException, KeyError) as e:
            log.warning("视觉模型 %s 调用失败，尝试备用: %s", m, e)
            last_err = e
    raise last_err


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group()) if m else {}


def _crop_for_pulse(image_path: str) -> str:
    """裁出屏幕所在的中上区域并放大3倍，专门用于读心率小数字"""
    from PIL import Image
    with open(image_path, "rb") as f:
        img = Image.open(io.BytesIO(f.read())).convert("RGB")
    w, h = img.size
    box = (int(w * 0.10), int(h * 0.05), int(w * 0.90), int(h * 0.80))
    crop = img.crop(box)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=92)
    return _b64_image(buf.getvalue())


def _read_pulse(image_path: str, mode: str = "crop"):
    """第二段识别：放大图里专门找心率。crop=裁出屏幕区域放大3倍（更快更清晰），
    full=整图放大2倍（照片旋转/倾斜时固定裁剪坐标会失准，用整图兜底）"""
    b64 = _crop_for_pulse(image_path) if mode == "crop" else _enlarged_b64(image_path, 2)
    content = _chat_vision([{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": PULSE_PROMPT},
        ],
    }])
    log.info("心率二次识别(%s): %s", mode, content)
    data = _parse_json(content)
    return _norm_int(data.get("heart_rate"), 30, 220)


def recognize_image(image_path: str) -> dict:
    """识别一张照片，返回结构化结果。单原图读大数字最稳，心率靠二次放大识别"""
    with open(image_path, "rb") as f:
        b64 = _b64_image(f.read())
    resp = _chat_vision([{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": BP_PROMPT},
    ]}])
    log.info("识别结果: %s", resp)
    result = _parse_json(resp)
    if result.get("type") == "bp":
        # 模型输出可能是 "145"、145.0 等形态，统一归一化并做生理范围校验
        result["systolic"] = _norm_int(result.get("systolic"), 50, 300)
        result["diastolic"] = _norm_int(result.get("diastolic"), 20, 200)
        result["heart_rate"] = _norm_int(result.get("heart_rate"), 30, 220)
        if not result.get("heart_rate"):
            # 心率漏读兜底：先裁剪放大找屏幕小字，不行再整图放大（应对旋转/倾斜）
            for mode in ("crop", "full"):
                try:
                    hr = _read_pulse(image_path, mode)
                except Exception:
                    log.exception("心率二次识别失败（%s），跳过", mode)
                    hr = None
                if hr:
                    result["heart_rate"] = hr
                    result["heart_rate_source"] = f"vision_{mode}"
                    break
    return result


def analyze_period(member: str, days: int, bp_rows: list, checkup_rows: list) -> str:
    bp_lines = "\n".join(
        f"{r['measured_at'][:16]} {r['systolic']}/{r['diastolic']} 心率{r['heart_rate'] or '-'}"
        for r in bp_rows) or "（无记录）"
    ck_lines = "\n".join(
        f"[{r['checkup_date']}] {r['summary']}" for r in checkup_rows) or "（无记录）"
    prompt = ANALYZE_PROMPT.format(member=member, days=days, bp=bp_lines, checkup=ck_lines)
    return _chat(LLM_TEXT_MODEL, [{"role": "user", "content": prompt}], temperature=0.3)
