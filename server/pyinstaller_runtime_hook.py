"""PyInstaller 运行时钩子：把带原生 DLL 的包目录加入 DLL 搜索路径。

onnxruntime / ctranslate2 / curl_cffi 的 pyd 依赖同目录 DLL，
冻结环境下默认搜索路径找不到，需显式 add_dll_directory。
"""
import os
import sys

if getattr(sys, "frozen", False):
    meipass = sys._MEIPASS
    for sub in (
        os.path.join("onnxruntime", "capi"),
        os.path.join("ctranslate2"),
        os.path.join("curl_cffi"),
        os.path.join("curl_cffi", ".libs"),
        os.path.join("shapely", ".libs"),
        os.path.join("Shapely.libs"),
    ):
        d = os.path.join(meipass, sub)
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except (OSError, FileNotFoundError):
                pass
