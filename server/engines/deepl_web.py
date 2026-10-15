"""DeepL oneshot 免费接口（Python 移植自 DeepLX v1.3.x 的逆向协议）。

端点/请求体规格来自 DeepLX 源码 translate/translate.go：
  POST https://oneshot-free.www.deepl.com/v1/translate
  伪装 DeepL iOS 客户端（TLS 指纹 + UA + app_information 必须一致）。
匿名额度：单次请求 text 数组总长度 ≤ 1500 个 UTF-16 码元，超长自动分批。
"""
from __future__ import annotations

import json
import uuid

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # 开发环境兜底
    cffi_requests = None
    import requests as _fallback_requests

_ONESHOT_URL = "https://oneshot-free.www.deepl.com/v1/translate"

# iOS 客户端画像（DeepLX 源码中的常量；DeepL 发版后需跟随更新，否则 429）
_IOS_APP_VERSION = "26.52"
_IOS_APP_BUILD = "5443737"
_IOS_OS_VERSION = "26.0"
_CFNETWORK = "3826.600.41"
_DARWIN = "25.0.0"
_UA = f"DeepL/{_IOS_APP_VERSION} CFNetwork/{_CFNETWORK} Darwin/{_DARWIN}"

_TARGET_LANG = {
    "zh-CHS": "zh-Hans", "zh": "zh-Hans", "zh-CHT": "zh-Hant",
    "en": "en-US", "en-US": "en-US", "en-GB": "en-GB",
    "ja": "ja", "ko": "ko", "fr": "fr", "ru": "ru", "es": "es",
    "pt": "pt-BR", "de": "de", "ar": "ar", "id": "id", "vi": "vi", "it": "it",
}
_SOURCE_LANG = {**_TARGET_LANG, "en": "en", "pt": "pt",
                "zh-CHS": "zh", "zh": "zh", "zh-CHT": "zh"}

_MAX_UNITS = 1500  # UTF-16 码元上限

_instance_id = str(uuid.uuid4())
_session_id = str(uuid.uuid4())
_client = None


def _get_client():
    global _client
    if _client is None:
        if cffi_requests is not None:
            # curl_cffi 无 iOS URLSession 指纹，用 Apple Network(safari) 近似
            _client = cffi_requests.Session(impersonate="safari")
        else:
            _client = _fallback_requests.Session()
        _client.headers.update({
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            _client.get("https://www.deepl.com/translator", timeout=5)
        except Exception:  # noqa: BLE001 - cookie 预热是尽力而为
            pass
    return _client


def _utf16_len(text: str) -> int:
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": "None",
        "User-Agent": _UA,
        "x-app-os-version": _IOS_OS_VERSION,
        "x-app-instance-id": _instance_id,
        "x-app-session-id": _session_id,
    }


def _body(texts: list[str], source: str, target: str) -> dict:
    body = {
        "text": texts,
        "target_lang": _TARGET_LANG.get(target, "zh-Hans"),
        "usage_type": "translate",
        "app_information": {
            "os": "iOS",
            "os_version": _IOS_OS_VERSION,
            "app_version": _IOS_APP_VERSION,
            "app_build": _IOS_APP_BUILD,
            "instance_id": _instance_id,
        },
    }
    src = _SOURCE_LANG.get(source) if source != "auto" else None
    if src:
        body["source_lang"] = src
    return body


def _batch(texts: list[str]) -> list[list[str]]:
    """按 1500 UTF-16 码元上限分批。"""
    batches, cur, total = [], [], 0
    for t in texts:
        n = _utf16_len(t)
        if cur and total + n > _MAX_UNITS:
            batches.append(cur)
            cur, total = [], 0
        cur.append(t)
        total += n
    if cur:
        batches.append(cur)
    return batches


def deepl_oneshot_translate(text: str, source: str, target: str) -> str:
    """source/target 使用有道风格代码（auto/zh-CHS/en/...）。"""
    paragraphs = text.split("\n")
    client = _get_client()
    out: list[str] = []
    for batch in _batch(paragraphs):
        r = client.post(_ONESHOT_URL, headers=_headers(),
                        data=json.dumps(_body(batch, source, target)), timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"deepl oneshot HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        translations = data.get("translations") or []
        if len(translations) != len(batch):
            raise RuntimeError(f"deepl oneshot misaligned: {data}")
        out.extend(t.get("text", "") for t in translations)
    # 对齐回原始段落数（空段落未发送，需要回填）
    result: list[str] = []
    idx = 0
    for p in paragraphs:
        if p.strip():
            result.append(out[idx])
            idx += 1
        else:
            result.append(p)
    return "\n".join(result)


if __name__ == "__main__":
    print(deepl_oneshot_translate("Hello world, this is a test of the translation pipeline.", "en", "zh-CHS"))
