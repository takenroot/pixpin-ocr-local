"""本地 opus-mt 离线翻译引擎（CTranslate2 int8）。

两种模型目录布局:
  - hf_tok/ 存在: transformers 转换的模型，用 MarianTokenizer 分词
    （绕开 CT2 Windows 版 pybind 不接受 int token 的限制，片段经 vocab 映射回 id）
  - 否则: ct2-opus-mt-converter 转换的原始 Marian 模型，直接用 sentencepiece

engines.json 配置:
  "local_opus": {"enabled": false, "model_dir": "models", "pairs": ["en-zh", "zh-en"]}
"""
from __future__ import annotations

import json
import os
import sys

import ctranslate2

from . import EngineError

if getattr(sys, "frozen", False):
    _base_dir = sys._MEIPASS
else:
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # server/

# pair -> (translator, encode_fn, decode_fn)
_translators: dict = {}


def _resolve_pair(source: str, target: str, pairs: list[str]) -> str | None:
    def simp(code: str) -> str:
        c = code.strip().lower()
        if c.startswith("zh"):
            return "zh"
        return c.split("-")[0]
    s, t = simp(source), simp(target)
    if source == "auto":
        for p in pairs:
            if p.endswith(f"-{t}"):
                return p
        return None
    for p in pairs:
        a, b = p.split("-")
        if a == s and b == t:
            return p
    return None


def _load_hf_model(mdir: str):
    from transformers import MarianTokenizer  # 延迟导入，未启用零开销

    tok = MarianTokenizer.from_pretrained(os.path.join(mdir, "hf_tok"))
    with open(os.path.join(mdir, "shared_vocabulary.json"), encoding="utf-8") as f:
        vocab = json.load(f)
    rev = {p: i for i, p in enumerate(vocab)}

    def encode(text: str) -> list[str]:
        ids = tok.encode(text)
        tokens = tok.convert_ids_to_tokens(ids)
        if not all(x in rev for x in tokens):
            missing = [x for x in tokens if x not in rev][:3]
            raise EngineError(f"tokenizer/vocab mismatch: {missing}")
        return tokens

    def decode(tokens: list[str]) -> str:
        return tok.decode([rev[x] for x in tokens], skip_special_tokens=True)

    return encode, decode


def _load_spm_model(mdir: str):
    import sentencepiece as spm

    src_sp = spm.SentencePieceProcessor(model_file=os.path.join(mdir, "source.spm"))
    tgt_sp = spm.SentencePieceProcessor(model_file=os.path.join(mdir, "target.spm"))

    def encode(text: str) -> list[str]:
        return src_sp.encode(text, out_type=str)

    def decode(tokens: list[str]) -> str:
        return tgt_sp.decode(tokens)

    return encode, decode


def _get(pair: str, model_dir: str):
    if pair in _translators:
        return _translators[pair]
    mdir = os.path.join(_base_dir, model_dir, f"ct2-opus-mt-{pair}")
    if not os.path.isdir(mdir):
        raise EngineError(f"model not found: {mdir}（请在开发机转换后随包分发）")
    translator = ctranslate2.Translator(mdir, device="cpu")
    if os.path.isdir(os.path.join(mdir, "hf_tok")):
        encode, decode = _load_hf_model(mdir)
    else:
        encode, decode = _load_spm_model(mdir)
    _translators[pair] = (translator, encode, decode)
    return _translators[pair]


def local_opus_translate(text: str, source: str, target: str,
                         model_dir: str = "models",
                         pairs: list[str] | None = None, **_cfg) -> str:
    pairs = pairs or ["en-zh", "zh-en"]
    pair = _resolve_pair(source, target, pairs)
    if not pair:
        raise EngineError(f"local_opus 不支持 {source}->{target}，仅支持: {pairs}")
    translator, encode, decode = _get(pair, model_dir)

    paragraphs = text.split("\n")
    non_empty = [p for p in paragraphs if p.strip()]
    if not non_empty:
        return text
    tokenized = [encode(p) for p in non_empty]
    results = translator.translate_batch(tokenized, beam_size=4, max_decoding_length=512)
    translated = [decode(r.hypotheses[0]) for r in results]

    out, idx = [], 0
    for p in paragraphs:
        if p.strip():
            out.append(translated[idx])
            idx += 1
        else:
            out.append(p)
    return "\n".join(out)
