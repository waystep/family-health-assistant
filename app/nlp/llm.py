"""大模型解析兜底（OpenAI 兼容接口，可配智谱/DeepSeek 等）。

未配置 LLM 时返回 None，系统退回纯规则模式，依然可用。
"""

from __future__ import annotations

import json
import logging
import re

from .. import config

log = logging.getLogger(__name__)

TEXT_PROMPT = """你是家庭健康助手的数据录入员。从消息中提取测量数据，只输出 JSON：
{"member_hint":"提到的成员称呼，没有则空串","systolic":0,"diastolic":0,"heart_rate":0,
"weight_kg":0,"weight_unit":"kg或jin","body_fat_pct":0,
"date_text":"今天/昨天/前天等，没有则空串","time_text":"早上8点等，没有则空串"}
没有的字段填 0 或空串。消息：{text}"""


def parse_with_llm(text: str) -> dict | None:
    if not config.llm_enabled():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": TEXT_PROMPT.format(text=text)}],
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:
        log.warning("LLM 文本解析失败: %s", e)
        return None


VISION_PROMPT = "识别图片中的健康测量数据（血压计/体脂秤/健康App截图）。只输出 JSON：" \
                '{"systolic":0,"diastolic":0,"heart_rate":0,"weight_kg":0,"weight_unit":"kg或jin","body_fat_pct":0}，' \
                "没有的字段填 0。注意体重单位：如显示 斤 请填 jin。"


def parse_image_with_llm(image_b64: str) -> dict | None:
    if not config.vision_enabled():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        resp = client.chat.completions.create(
            model=config.LLM_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:
        log.warning("LLM 图片解析失败: %s", e)
        return None
