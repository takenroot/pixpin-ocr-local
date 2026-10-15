# -*- mode: python ; coding: utf-8 -*-
"""dePixPin 便携版打包配置：python -m PyInstaller server/depixpin.spec"""
import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas, binaries, hiddenimports = [], [], []
for pkg in ("rapidocr_onnxruntime", "onnxruntime", "cv2", "ctranslate2",
            "curl_cffi", "sentencepiece", "transformers", "sacremoses", "engines"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 动态导入的引擎模块 + 配置/证书
hiddenimports += ["engines.deepl_web", "engines.local_opus"]
here = os.path.abspath(os.getcwd())
datas += [
    (os.path.join(here, "engines.json"), "."),
    (os.path.join(here, "certs", "youdao.crt"), "certs"),
    (os.path.join(here, "certs", "youdao.key"), "certs"),
    (os.path.join(here, "certs", "depixpin-ca.crt"), "certs"),
]
# 本地翻译模型（可选分发）
models_dir = os.path.join(here, "models")
if os.path.isdir(models_dir):
    datas.append((models_dir, "models"))

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
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")]

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
