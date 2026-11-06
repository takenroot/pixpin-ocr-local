"""本地 OCR（RapidORX）+ 译文回图渲染。

图片翻译链路: 图片 -> OCR 行级框 -> 逐行翻译 -> 按原框渲染译文。
"""
from __future__ import annotations

import base64
import io
import statistics
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont, ImageOps

from engines import translate

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        from rapidocr import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def _run_ocr(ocr, img) -> list | None:
    """跑一版 OCR，统一返回 [(box, text, conf), ...] 或 None。"""
    out = ocr(img)
    if not out.txts:
        return None
    return list(zip(out.boxes, out.txts, out.scores))


@dataclass
class Line:
    box: tuple[int, int, int, int]          # x, y, w, h（正外接矩形）
    text: str
    translation: str = ""
    region: int = -1                          # 所属区域序号


@dataclass
class Region:
    box: tuple[int, int, int, int]
    lines: list[Line] = field(default_factory=list)


def _rect(points) -> tuple[int, int, int, int]:
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _ocr_prep(ocr, img_bytes: bytes):
    """首检出空时重试：短条图（如贴图/聊天条）补边到 300px + 暗底反色后重跑 OCR。
    只在右下补边，坐标系不变，检出的框可直接用于原图。"""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("L")
    except Exception:
        return None
    mean = sum(img.getdata()) / (img.width * img.height)
    if mean < 128:
        img = ImageOps.invert(img)
    w, h = img.size
    if h < 300 or w < 300:
        canvas = Image.new("L", (max(w, 300), max(h, 300)), img.getpixel((0, 0)))
        canvas.paste(img, (0, 0))
        img = canvas
    import numpy as np
    return _run_ocr(ocr, np.array(img))


def ocr_lines(img_bytes: bytes) -> tuple[Image.Image, list[Line], str]:
    """返回 (PIL图, 行列表, 检测到的源语言)。"""
    ocr = _get_ocr()
    result = _run_ocr(ocr, img_bytes)
    if not result:
        result = _ocr_prep(ocr, img_bytes)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    lines: list[Line] = []
    cjk = latin = 0
    if result:
        for box, text, _conf in result:
            x, y, w, h = _rect(box)
            if w < 3 or h < 3:
                continue
            lines.append(Line(box=(x, y, w, h), text=text.strip()))
            for ch in text:
                if "\u4e00" <= ch <= "\u9fff":
                    cjk += 1
                elif ch.isascii() and ch.isalpha():
                    latin += 1
    lines.sort(key=lambda l: (l.box[1], l.box[0]))
    detected = "zh-CHS" if cjk >= latin else "en"
    return img, lines, detected


def group_regions(lines: list[Line]) -> list[Region]:
    """把行按纵向邻近度聚成区域（模拟有道的 resRegions）。"""
    regions: list[Region] = []
    for line in lines:
        x, y, w, h = line.box
        placed = None
        for r in regions:
            rx, ry, rw, rh = r.box
            if abs(y - ry) <= max(h, rh) * 1.5:
                placed = r
                break
        if placed is None:
            placed = Region(box=line.box)
            regions.append(placed)
        placed.lines.append(line)
    # 重算区域框 + 排序
    for r in regions:
        xs = [l.box[0] for l in r.lines]
        ys = [l.box[1] for l in r.lines]
        xe = [l.box[0] + l.box[2] for l in r.lines]
        ye = [l.box[1] + l.box[3] for l in r.lines]
        r.box = (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))
        r.lines.sort(key=lambda l: l.box[1])
    regions.sort(key=lambda r: (r.box[1], r.box[0]))
    for i, r in enumerate(regions):
        for l in r.lines:
            l.region = i
    return regions


def translate_lines(lines: list[Line], source: str, target: str) -> None:
    # 先按行判定源语言分组（中英混排截图里逐行判语言比整图判更准）
    groups: dict[str, list[Line]] = {}
    for line in lines:
        s = source
        if s == "auto":
            cjk = sum(1 for ch in line.text if "\u4e00" <= ch <= "\u9fff")
            latin = sum(1 for ch in line.text if ch.isascii() and ch.isalpha())
            s = "zh-CHS" if cjk > latin else "en"
        groups.setdefault(s, []).append(line)
    for s, group in groups.items():
        _translate_group(group, s, target)


def _translate_group(lines: list[Line], source: str, target: str) -> None:
    """优先把整组行合并成一次翻译请求（省掉每行的网络往返）；
    行数对不上就回退逐行并行。"""
    joined = "\n".join(l.text for l in lines)
    if len(lines) > 1:
        try:
            out = translate(joined, source, target)
            parts = out.split("\n")
            if len(parts) == len(lines) and all(p.strip() for p in parts):
                for line, tr in zip(lines, parts):
                    line.translation = tr.strip()
                return
        except Exception:  # noqa: BLE001 - 批量失败走逐行
            pass
    _translate_parallel(lines, source, target)


def _translate_parallel(lines: list[Line], source: str, target: str) -> None:
    def _work(line: Line) -> None:
        try:
            line.translation = translate(line.text, source, target)
        except Exception as e:  # noqa: BLE001 - 单行失败不拖垮整体
            line.translation = f"[翻译失败: {e}]"

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(lines)))) as pool:
        list(pool.map(_work, lines))


_FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _bg_color(img: Image.Image, box) -> tuple[int, int, int]:
    """取文本框外圈像素的中位色作为底色。"""
    x, y, w, h = box
    W, H = img.size
    ring = 3
    pts = []
    for yy in range(max(0, y - ring), min(H, y + h + ring)):
        for xx in (x - ring, x + w + ring - 1):
            if 0 <= xx < W:
                pts.append(img.getpixel((xx, yy)))
    for xx in range(max(0, x - ring), min(W, x + w + ring)):
        for yy in (y - ring, y + h + ring - 1):
            if 0 <= yy < H:
                pts.append(img.getpixel((xx, yy)))
    if not pts:
        return (255, 255, 255)
    ch = [statistics.median(c[i] for c in pts) for i in range(3)]
    return tuple(int(v) for v in ch)


def _contrast(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (30, 30, 30) if lum > 140 else (235, 235, 235)


def _wrap(draw, text, font, max_w) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def render_translated(img: Image.Image, lines: list[Line], scale: float = 1.0) -> Image.Image:
    """把译文绘制到图上：原框打底 + 换行缩放的译文文字。

    scale: 译文区域相对原框的垂直膨胀系数（中文比英文短，给 1.15 更舒展）。
    """
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for line in lines:
        if not line.translation:
            continue
        x, y, w, h = line.box
        bg = _bg_color(img, line.box)
        nh = int(h * scale)
        ny = y - (nh - h) // 2
        draw.rectangle([x, ny, x + w, ny + nh], fill=bg)

        size = max(8, int(nh * 0.78))
        color = _contrast(bg)
        while size > 7:
            font = _font(size)
            wrapped = _wrap(draw, line.translation, font, w - 4)
            total_h = sum(font.size + 2 for _ in wrapped)
            if total_h <= nh - 2:
                break
            size -= 1
        font = _font(size)
        wrapped = _wrap(draw, line.translation, font, w - 4)
        ty = ny + max(0, (nh - (font.size + 2) * len(wrapped)) // 2)
        for seg in wrapped:
            draw.text((x + 2, ty), seg, font=font, fill=color)
            ty += font.size + 2
    return out


def to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
