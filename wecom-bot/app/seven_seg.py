"""确定性七段码数字识别：从血压计照片中精确读数。
流程：分块对比度拉伸(抗背光不均) → 自适应二值化 → 去偏斜 → 连通域分行 → 七段模板分类。
比多模态大模型稳定（LLM 对七段码屏多次读数会漂移），LLM 仅负责判断照片类型。"""
import logging

import numpy as np
from PIL import Image
from scipy import ndimage

log = logging.getLogger(__name__)

SEG_PATTERNS = {
    "0": "ABCDEF", "1": "BC", "2": "ABGED", "3": "ABGCD", "4": "FGBC",
    "5": "AFGCD", "6": "AFGEDC", "7": "ABC", "8": "ABCDEFG", "9": "ABCFGD",
}
PATTERN_TO_DIGIT = {v: k for k, v in SEG_PATTERNS.items()}


def _stretch_and_binarize(img: Image.Image) -> np.ndarray:
    """绿色屏提取 + 分块拉伸 + 自适应阈值 → True=数字笔画"""
    a = np.asarray(img.convert("RGB")).astype(float)
    G = a[:, :, 1]
    R, B = a[:, :, 0], a[:, :, 2]
    screen = (G - R > 25) & (G - B > 25) & (G > 70)
    ys, xs = np.where(screen)
    if len(ys) < 2000:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    # 屏幕外接框向外扩 8%，容纳背光变暗的边缘（如心率行）
    my, mx = (y1 - y0) * 0.08, (x1 - x0) * 0.08
    y0, y1 = max(0, int(y0 - my)), min(G.shape[0], int(y1 + my))
    x0, x1 = max(0, int(x0 - mx)), min(G.shape[1], int(x1 + mx))

    stretched = np.zeros_like(G)
    cells = 6
    for i in range(cells):
        for j in range(cells):
            ry0 = y0 + (y1 - y0) * i // cells
            ry1 = y0 + (y1 - y0) * (i + 1) // cells
            rx0 = x0 + (x1 - x0) * j // cells
            rx1 = x0 + (x1 - x0) * (j + 1) // cells
            reg = G[ry0:ry1, rx0:rx1]
            lo, hi = np.percentile(reg, 2), np.percentile(reg, 98)
            stretched[ry0:ry1, rx0:rx1] = np.clip((reg - lo) / max(hi - lo, 1) * 255, 0, 255)

    digit = np.zeros(G.shape, dtype=bool)
    for i in range(cells):
        for j in range(cells):
            ry0 = y0 + (y1 - y0) * i // cells
            ry1 = y0 + (y1 - y0) * (i + 1) // cells
            rx0 = x0 + (x1 - x0) * j // cells
            rx1 = x0 + (x1 - x0) * (j + 1) // cells
            sm = screen[ry0:ry1, rx0:rx1]
            if sm.sum() < 300:
                continue
            med = np.median(stretched[ry0:ry1, rx0:rx1][sm])
            digit[ry0:ry1, rx0:rx1] = sm & (stretched[ry0:ry1, rx0:rx1] < med - 28)

    lab, n = ndimage.label(digit)
    if n == 0:
        return None
    sizes = ndimage.sum(digit, lab, range(1, n + 1))
    return np.isin(lab, np.where(sizes > 60)[0] + 1)


def _glyph_tilt(glyph: np.ndarray) -> float:
    """字形笔画主轴相对竖直的偏角"""
    ys, xs = np.where(glyph)
    if len(ys) < 50:
        return 0.0
    cov = np.cov(np.stack([xs, ys]))
    evals, evecs = np.linalg.eigh(cov)
    axis = evecs[:, np.argmax(evals)]
    return float(np.degrees(np.arctan2(axis[0], axis[1])))


def _classify_glyph(glyph: np.ndarray):
    """单字形先自转正再按七段模板分类，返回 (字符, 置信度) 或 None"""
    h, w = glyph.shape
    if h < 14 or w < 5 or h / max(w, 1) < 1.1:
        return None
    tilt = _glyph_tilt(glyph)
    if abs(tilt) > 0.8:
        g = Image.fromarray(np.where(glyph, 0, 255).astype(np.uint8)).rotate(tilt, expand=True, fillcolor=255)
        glyph = np.asarray(g) < 128
        h, w = glyph.shape

    def on(x0, x1, y0, y1):
        reg = glyph[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        return reg.mean() > 0.30 if reg.size else False

    seg = {
        "A": on(0.28, 0.72, 0.02, 0.20), "B": on(0.76, 1.0, 0.12, 0.44),
        "C": on(0.76, 1.0, 0.56, 0.88), "D": on(0.28, 0.72, 0.80, 0.98),
        "E": on(0.0, 0.24, 0.56, 0.88), "F": on(0.0, 0.24, 0.12, 0.44),
        "G": on(0.28, 0.72, 0.42, 0.58),
    }
    pattern = "".join(s for s in "ABCDEFG" if seg[s])
    if pattern in PATTERN_TO_DIGIT:
        return PATTERN_TO_DIGIT[pattern], 1.0
    best, bd = None, 2
    for p, d in PATTERN_TO_DIGIT.items():
        dist = sum(1 for c in "ABCDEFG" if (c in p) != (c in pattern))
        if dist < bd:
            best, bd = d, dist
    return (best, 0.5) if bd <= 1 else (None, 0.0)


def _read_rows(binary: np.ndarray):
    """连通域 → 行分组 → 每行逐字分类 → [(行top, 行高, 数字串, 置信度), ...]"""
    lab, n = ndimage.label(binary)
    if n == 0:
        return []
    H, W = binary.shape
    glyphs = []
    for k, sl in enumerate(ndimage.find_objects(lab), 1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if h < 14 or w < 5 or h > H * 0.3 or w > W * 0.25:
            continue
        glyphs.append((sl[0].start, sl[0].stop, sl[1].start, sl[1].stop, h))
    if not glyphs:
        return []
    med_h = np.median([g[4] for g in glyphs])
    glyphs = [g for g in glyphs if g[4] > med_h * 0.45]
    glyphs.sort(key=lambda g: g[0])
    rows = []
    for g in glyphs:
        if rows and abs(g[0] - rows[-1][-1][0]) < g[4] * 0.5:
            rows[-1].append(g)
        else:
            rows.append([g])
    result = []
    for row in rows:
        row.sort(key=lambda g: g[2])
        hmax = max(g[4] for g in row)
        chars, conf = "", 0.0
        for g in row:
            r = _classify_glyph(binary[g[0]:g[1], g[2]:g[3]])
            if r and r[0]:
                chars += r[0]
                conf += r[1]
        if chars:
            result.append((row[0][0], hmax, chars, conf / len(row)))
    return result


def read_blood_pressure(image_path: str) -> dict:
    """主入口：{"systolic":int,"diastolic":int,"heart_rate":int|None} 或 None"""
    img = Image.open(image_path)
    best = None
    for rot in (0, 90, 180, 270):
        binary = _stretch_and_binarize(img.rotate(rot, expand=True))
        if binary is None:
            continue
        rows = [r for r in _read_rows(binary) if 2 <= len(r[2]) <= 3]
        if len(rows) < 2:
            continue
        rows = sorted(sorted(rows, key=lambda x: -x[1])[:3], key=lambda x: x[0])
        try:
            sys_v, dia_v = int(rows[0][2]), int(rows[1][2])
        except ValueError:
            continue
        if not (60 <= sys_v <= 260 and 30 <= dia_v <= 160):
            continue
        hr_v = int(rows[2][2]) if len(rows) == 3 and rows[2][2].isdigit() else None
        if hr_v is not None and not (30 <= hr_v <= 220):
            hr_v = None
        score = sum(r[3] for r in rows) + (0.5 if len(rows) == 3 else 0)
        cand = {"systolic": sys_v, "diastolic": dia_v, "heart_rate": hr_v}
        if best is None or score > best[0]:
            best = (score, cand)
    return best[1] if best else None
