"""dePixPin 伪有道 API 服务。

冒充 openapi.youdao.com，接收 PixPin 的翻译请求，后端走免费引擎。
两个端点:
  POST /api          文本翻译（PixPin 验证 Key & 文本贴图用）
  POST /ocrtransapi  图片翻译（截图/图像贴图用）

开发模式默认跑明文 HTTP（127.0.0.1:8443），生产由 run.py 包一层 HTTPS(443)。
"""
from __future__ import annotations

import base64
import logging
import os
import sys
import time

from flask import Flask, jsonify, request

from engines import EngineError, translate
import ocr_render

# 冻结（PyInstaller）时：资源（证书/配置/模型）在 _internal 内，日志写程序目录旁
if getattr(sys, "frozen", False):
    _base_dir = os.path.dirname(sys.executable)   # 日志等可写文件
    _res_dir = sys._MEIPASS                        # 只读资源
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _res_dir = _base_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# 静默/系统服务模式下 stdout 不可见，同步写日志文件便于排错
_log_dir = os.path.join(_base_dir, "logs")
try:
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = logging.FileHandler(os.path.join(_log_dir, "server.log"), encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_file_handler)
except OSError:
    pass
log = logging.getLogger("depixpin")

app = Flask(__name__)

# 有道错误码: 0 成功, 108 appKey 无效, 202 签名错误 ...
ERR_OK = "0"
ERR_ENGINE = "411"  # 411 访问频率超限, 借用表示引擎侧失败


def _resp_text(query: str, source: str, target: str, translation: str | None, error: str = ERR_OK):
    body = {"errorCode": error, "query": query, "l": f"{source}2{target}"}
    if translation is not None:
        body["translation"] = [translation]
    return jsonify(body)


@app.post("/api")
def text_translate():
    """有道文本翻译 v1: q/from/to/appKey/salt/sign/signType/curtime。"""
    q = (request.form.get("q") or "").strip()
    source = request.form.get("from") or "auto"
    target = request.form.get("to") or "zh-CHS"
    log.info("[/api] %s -> %s, %d chars", source, target, len(q))
    if not q:
        return _resp_text(q, source, target, None, error="102")  # 102 不支持的语言
    try:
        result = translate(q, source, target)
    except EngineError as e:
        log.error("[/api] engines failed: %s", e)
        return _resp_text(q, source, target, None, error=ERR_ENGINE)
    return _resp_text(q, source, target, result)


@app.post("/ocrtransapi")
def image_translate():
    """有道图片翻译: type=1&q=base64&from&to&render&..."""
    q = request.form.get("q") or ""
    source = request.form.get("from") or "auto"
    target = request.form.get("to") or "zh-CHS"
    want_render = (request.form.get("render") or "1") == "1"
    log.info("[/ocrtransapi] %s -> %s, render=%s, b64=%d chars", source, target, want_render, len(q))
    try:
        img_bytes = base64.b64decode(q)
    except Exception:  # noqa: BLE001
        return jsonify({"errorCode": "103"})  # 103 翻译文本过长 -> 借用表示图片解码失败
    try:
        t0 = time.time()
        img, lines, detected = ocr_render.ocr_lines(img_bytes)
        src = detected if source == "auto" else source
        ocr_render.translate_lines(lines, src, target)
        regions = ocr_render.group_regions(lines)
        log.info("[/ocrtransapi] OCR %d lines / %d regions in %.1fs", len(lines), len(regions), time.time() - t0)
    except Exception as e:  # noqa: BLE001
        log.exception("[/ocrtransapi] pipeline failed")
        return jsonify({"errorCode": ERR_ENGINE, "msg": str(e)})

    res_regions = []
    for r in regions:
        rx, ry, rw, rh = r.box
        context = " ".join(l.text for l in r.lines)
        tran = " ".join(l.translation for l in r.lines)
        line_heights = [l.box[3] for l in r.lines]
        entry = {
            "boundingBox": f"{rx},{ry},{rw},{rh}",
            "linesCount": len(r.lines),
            "lineheight": int(sum(line_heights) / len(line_heights)),
            "linespace": 4,
            "context": context,
            "tranContent": tran,
        }
        if want_render:
            entry["lines"] = [
                {
                    "words": [{"word": l.text, "wordType": 0, "wordBg": f"{l.box[0]},{l.box[1]},{l.box[2]},{l.box[3]}"}],
                    "text": l.translation or l.text,
                    "textHeight": l.box[3],
                }
                for l in r.lines
            ]
        res_regions.append(entry)

    body = {
        "errorCode": ERR_OK,
        "orientation": "Up",
        "textAngle": "0",
        "lanFrom": src,
        "lanTo": target,
        "resRegions": res_regions,
    }
    if want_render:
        rendered = ocr_render.render_translated(img, lines)
        image_b64 = ocr_render.to_base64(rendered)
        body["renderImage"] = image_b64
    # PixPin 的解析器查 snake_case 键（验证时报 "does not contain render_image"），双写两套
    def _snake(name: str) -> str:
        out = []
        for i, ch in enumerate(name):
            if ch.isupper() and i > 0:
                out.append("_")
            out.append(ch.lower())
        return "".join(out)

    body["lan_from"], body["lan_to"] = body["lanFrom"], body["lanTo"]
    body["res_regions"] = [
        {**{(_snake(k) if k != "lines" else k): v for k, v in r.items()},
         **r}
        for r in body["resRegions"]
    ]
    if "renderImage" in body:
        body["render_image"] = body["renderImage"]
    return jsonify(body)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    try:
        port = 8443
        ssl_context = None
        args = sys.argv[1:]
        if "--https" in args:
            args.remove("--https")
            port = 443
            cert_dir = os.path.join(_res_dir, "certs")
            ssl_context = (os.path.join(cert_dir, "youdao.crt"), os.path.join(cert_dir, "youdao.key"))
        elif args:
            port = int(args[0])
        scheme = "HTTPS" if ssl_context else "HTTP"
        log.info("depixpin fake-youodao server on 127.0.0.1:%d (%s)", port, scheme)
        app.run(host="127.0.0.1", port=port, threaded=True, ssl_context=ssl_context)
    except Exception:
        # 窗口程序（console=False）在 session 0 下未捕获异常会弹不可见对话框挂死进程
        log.exception("fatal: server exited")
        sys.exit(1)
