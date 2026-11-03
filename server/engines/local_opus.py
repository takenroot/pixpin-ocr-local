"""本地 opus-mt 离线翻译引擎（CTranslate2 int8，纯 sentencepiece，无 transformers）。

分词约定（与 transformers MarianTokenizer 输出对齐）:
  编码 = sentencepiece(source.spm) + ['</s>']
  解码 = target.spm.decode_pieces 后 '▁'→空格
（Marian 源序列必须带 eos，缺失会导致输出退化——第 1 版踩过坑，见 findings/packaging.md）

模型目录: <model_dir>/ct2-opus-mt-<pair>/，内含 CT2 转换产物 + source.spm/target.spm
（spm 放在 hf_tok/ 子目录亦可，两种布局都识别）。
模型不随便携包分发，需要离线引擎时把 models/ 文件夹拷到 exe 同级目录。

engines.json 配置:
  "local_opus": {"enabled": true, "model_dir": "models", "pairs": ["en-zh", "zh-en"]}
"""
from __future__ import annotations

import os
import sys

import ctranslate2
import sentencepiece as spm

from . import EngineError

if getattr(sys, "frozen", False):
    _res_dir = sys._MEIPASS
    _exe_dir = os.path.dirname(sys.executable)
else:
    _res_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # server/
    _exe_dir = _res_dir

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


def _find_spm(mdir: str, name: str) -> str:
    for cand in (os.path.join(mdir, "hf_tok", name), os.path.join(mdir, name)):
        if os.path.isfile(cand):
            return cand
    raise EngineError(f"模型文件缺失: {mdir}/{name}")


def _get(pair: str, model_dir: str):
    if pair in _translators:
        return _translators[pair]
    # 优先 exe 旁（models/ 可后拷），其次包内资源目录
    for base in {_exe_dir, _res_dir}:
        mdir = os.path.join(base, model_dir, f"ct2-opus-mt-{pair}")
        if os.path.isdir(mdir):
            break
    else:
        raise EngineError(
            f"model not found: {model_dir}/ct2-opus-mt-{pair} "
            f"（离线引擎需将 models/ 文件夹拷到程序同级目录，或关闭 local_opus）"
        )
    translator = ctranslate2.Translator(mdir, device="cpu")
    src_sp = spm.SentencePieceProcessor(model_file=_find_spm(mdir, "source.spm"))
    tgt_sp = spm.SentencePieceProcessor(model_file=_find_spm(mdir, "target.spm"))

    def encode(text: str) -> list[str]:
        return src_sp.encode(text, out_type=str) + ["</s>"]

    def decode(tokens: list[str]) -> str:
        return tgt_sp.decode_pieces(tokens).replace("▁", " ").strip()

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
