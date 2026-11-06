"""免费翻译引擎适配层（配置文件驱动 + 熔断降级）。

统一接口: translate(text: str, source: str, target: str) -> str
语言代码使用有道风格: auto, zh-CHS, en, ja, ko, fr, ru, es, pt, de

配置文件 server/engines.json:
  {
    "chain": ["deepl_oneshot", "mymemory", "local_opus"],
    "cooldown_seconds": 300,
    "max_consecutive_failures": 3,
    "engines": { "<name>": {"enabled": true, ...引擎私有配置} }
  }
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time

import requests

log = logging.getLogger("depixpin.engines")

if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # server/

# 有道风格 -> 引擎风格映射
_MYMEMORY_LANG = {
    "zh-CHS": "zh-CN", "zh": "zh-CN", "en": "en", "ja": "ja", "ko": "ko",
    "fr": "fr", "ru": "ru", "es": "es", "pt": "pt", "de": "de",
}

_CONFIG_PATH = os.path.join(_base, "engines.json")
_config_cache: tuple[float, dict] = (0.0, {})
# 熔断状态: name -> {"fails": int, "cooldown_until": float}
_breaker: dict[str, dict] = {}


def _norm(code: str) -> str:
    code = (code or "auto").strip()
    return "zh-CHS" if code in ("zh-CHS", "zh", "zh-CN", "zh_TW", "zh-CHT") else code


class EngineError(Exception):
    pass


def _load_config() -> dict:
    global _config_cache
    mtime = os.path.getmtime(_CONFIG_PATH) if os.path.exists(_CONFIG_PATH) else 0.0
    if mtime != _config_cache[0]:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                _config_cache = (mtime, json.load(f))
        else:
            _config_cache = (mtime, _default_config())
    return _config_cache[1]


def _default_config() -> dict:
    return {
        "chain": ["deepl_oneshot", "mymemory", "local_opus"],
        "cooldown_seconds": 300,
        "max_consecutive_failures": 3,
        "engines": {
            "deepl_oneshot": {"enabled": True},
            "mymemory": {"enabled": True},
            "local_opus": {"enabled": False, "model_dir": "models", "pairs": ["en-zh", "zh-en"]},
        },
    }


def deepl_oneshot_translate(text: str, source: str, target: str, **_cfg) -> str:
    """DeepL oneshot 免费接口（Python 移植，见 deepl_web.py）。"""
    from .deepl_web import deepl_oneshot_translate as _t
    return _t(text, source, target)


def mymemory_translate(text: str, source: str, target: str, **_cfg) -> str:
    """MyMemory 免费接口，免注册兜底（匿名 ~5000 字符/天）。"""
    src = "Autodetect" if source == "auto" else _MYMEMORY_LANG.get(_norm(source), "en")
    dst = _MYMEMORY_LANG.get(_norm(target), "zh-CN")
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text[:500], "langpair": f"{src}|{dst}"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("responseStatus") != 200 or data.get("quotaFinished"):
        raise EngineError(f"mymemory error: {data.get('responseDetails')}")
    return data["responseData"]["translatedText"]


def local_opus_translate(text: str, source: str, target: str, **cfg) -> str:
    """本地 opus-mt 离线模型（懒加载，见 local_opus.py）。"""
    from .local_opus import local_opus_translate as _t
    return _t(text, source, target, **cfg)


# 引擎注册表: name -> (函数, 是否需要私有配置透传)
_REGISTRY = {
    "deepl_oneshot": deepl_oneshot_translate,
    "mymemory": mymemory_translate,
    "local_opus": local_opus_translate,
}


def _in_cooldown(name: str, cfg: dict) -> bool:
    state = _breaker.get(name)
    if not state:
        return False
    if time.time() < state["cooldown_until"]:
        return True
    # 冷却到期，自动恢复
    del _breaker[name]
    log.info("[breaker] %s cooldown expired, back in rotation", name)
    return False


def _record_failure(name: str, cfg: dict) -> None:
    state = _breaker.setdefault(name, {"fails": 0, "cooldown_until": 0.0})
    state["fails"] += 1
    if state["fails"] >= cfg.get("max_consecutive_failures", 3):
        state["cooldown_until"] = time.time() + cfg.get("cooldown_seconds", 300)
        log.warning("[breaker] %s entering %.0fs cooldown after %d consecutive failures",
                    name, cfg.get("cooldown_seconds", 300), state["fails"])


def _record_success(name: str) -> None:
    if name in _breaker:
        del _breaker[name]


# ---- 翻译结果持久缓存（sqlite）----
# 键 = source|target|text 的哈希；任何引擎成功都写入，重复内容（同类界面/游戏文本）
# 再次翻译时 0 毫秒返回，相当于"翻过的都走本地"。
_cache_lock = threading.Lock()
_cache_conn = None


def _cache_db():
    global _cache_conn
    if _cache_conn is None:
        import sqlite3
        if getattr(sys, "frozen", False):
            d = os.path.join(os.path.dirname(sys.executable), "cache")
        else:
            d = os.path.join(_base, "cache")
        os.makedirs(d, exist_ok=True)
        conn = sqlite3.connect(os.path.join(d, "translate.db"),
                               check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
        _cache_conn = conn
    return _cache_conn


def _cache_key(text: str, source: str, target: str) -> str:
    return hashlib.sha1(f"{source}|{target}|{text}".encode("utf-8")).hexdigest()


def translate(text: str, source: str = "auto", target: str = "zh-CHS") -> str:
    key = _cache_key(text, source, target)
    with _cache_lock:
        row = _cache_db().execute("SELECT v FROM t WHERE k=?", (key,)).fetchone()
    if row:
        return row[0]

    cfg = _load_config()
    chain = [n for n in cfg.get("chain", []) if n in _REGISTRY]
    errors = []
    for name in chain:
        engine_cfg = cfg.get("engines", {}).get(name, {})
        if not engine_cfg.get("enabled", True):
            continue
        if _in_cooldown(name, cfg):
            errors.append(f"{name}: cooling down")
            continue
        try:
            result = _REGISTRY[name](text, source, target, **engine_cfg).strip()
            if result:
                _record_success(name)
                log.info("[translate] engine=%s chars=%d %s->%s", name, len(text), source, target)
                with _cache_lock:
                    _cache_db().execute("INSERT OR REPLACE INTO t VALUES (?, ?)",
                                        (key, result))
                return result
            raise EngineError("empty result")
        except Exception as e:  # noqa: BLE001 - 引擎间降级
            errors.append(f"{name}: {e}")
            _record_failure(name, cfg)
    raise EngineError("all engines failed: " + "; ".join(errors))


if __name__ == "__main__":
    print(translate("Hello world, this is a fallback chain test."))
