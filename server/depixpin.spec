# -*- mode: python ; coding: utf-8 -*-
"""dePixPin 便携版打包配置：python -m PyInstaller server/depixpin.spec"""
import os

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

block_cipher = None

datas, binaries, hiddenimports = [], [], []
for pkg in ("rapidocr_onnxruntime", "cv2",
            "curl_cffi", "sentencepiece", "engines"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# onnxruntime/ctranslate2 只收原生库：collect_all 会把 onnxruntime.transformers、
# ctranslate2.converters 等工具子包一起收集，进而把 transformers 全家（+45MB）拖进包，
# 运行时只需要推理核心。
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("ctranslate2")
hiddenimports += [
    "onnxruntime", "onnxruntime.capi", "onnxruntime.capi._pybind_state",
    "onnxruntime.capi.onnxruntime_pybind11_state",
    "ctranslate2",
]

# 动态导入的引擎模块 + 配置/证书
hiddenimports += ["engines.deepl_web", "engines.local_opus"]
here = os.path.abspath(os.getcwd())
datas += [
    (os.path.join(here, "engines.json"), "."),
    (os.path.join(here, "certs", "youdao.crt"), "certs"),
    (os.path.join(here, "certs", "youdao.key"), "certs"),
    (os.path.join(here, "certs", "depixpin-ca.crt"), "certs"),
]
# 本地翻译模型不进便携包（161MB）：需要离线引擎时把 models/ 拷到 exe 同级目录，
# local_opus 会优先在 exe 旁查找。源码目录开发模式直接用 server/models/。

a = Analysis(
    ["app.py"],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyinstaller_runtime_hook.py"],
    excludes=("torch", "torchvision", "torchaudio", "tensorflow", "jax",
              "flax", "triton", "PyInstaller"),
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 剔除根目录旧版 VC++ 运行库（14.29），避免遮蔽系统新版（14.50+）导致
# onnxruntime DllMain 初始化失败；系统库在所有 Win10/11 上存在。
# 同时剔除 OpenCV 的 ffmpeg 视频解码插件（OCR 用不到，省 31MB）。
_SKIP_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in _SKIP_DLLS
              and not os.path.basename(b[0]).startswith("opencv_videoio_ffmpeg")]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="depixpin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_tracker=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="depixpin",
)
