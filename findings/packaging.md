# PyInstaller 打包踩坑记录（4 轮迭代）

> 环境：Windows 11 + Python 3.14 + onnxruntime 1.27 + ctranslate2 4.8 + PyInstaller 6.x
> 目的：下次重建便携包时不再重复踩坑

## 坑 1：onnxruntime `DLL 初始化例程失败`

症状：exe 内 `import onnxruntime` 报 `ImportError: DLL load failed ... 初始化例程失败`（开发环境正常）。

根因：PyInstaller 把 Python 自带的**旧版 VC++ 运行库**（msvcp140.dll 14.29）打进包根目录，
遮蔽了系统新版（14.50+），onnxruntime 的 DllMain 初始化失败。

解法：`depixpin.spec` 中在 COLLECT 前过滤掉根目录的 msvcp140.dll / vcruntime140.dll /
vcruntime140_1.dll（系统库在所有 Win10/11 上都有）。注意只滤根目录，numpy.libs 等
私有目录里哈希命名的副本保留无妨。

## 坑 2：冻结模式下证书路径错误

症状：HTTPS 模式 FileNotFoundError（certs/youdao.crt）。

根因：PyInstaller 6.x onedir 把 datas 放进 `_internal/`，`sys._MEIPASS` 指向它；
而 `sys.executable` 目录是其父级。读资源用 `_MEIPASS`，写日志用 exe 目录。

## 坑 3：窗口程序异常在 session 0 挂死

症状：SYSTEM 任务启动后端口 LISTENING 但连接超时，进程僵死。

根因：`console=False` 的窗口程序发生未捕获异常时弹错误对话框；session 0 无交互，
对话框永远等不到点击 → 进程挂死且无声无息（用户会话里能看到弹窗）。

解法：`app.py` 的 `__main__` 整体 try/except，记录日志后 `sys.exit(1)`。

## 坑 4：CTranslate2 Windows 版不接受 int token

症状：`translate_batch([[26, 9122, ...]])` 报 TypeError（pybind 只声明 list[list[str]]）。

解法：HF 转换的模型用 transformers `MarianTokenizer.convert_ids_to_tokens` 拿字符串 token，
经 `shared_vocabulary.json` 映射回 id 解码。transformers tokenizer 在无 torch 环境可用
（仅 tokenizers 功能），打包时 exclude torch 即可。

## 坑 5：opus-mt 的 spm 与 transformers vocab 不互通

`source.spm`（sentencepiece）编码出的 `▁Hello` 不在 transformers `vocab.json` 派生的
`shared_vocabulary.json` 里（Marian 词表用 `@@` 续词风格、无 `▁` 前缀）——
HF 格式的 opus-mt 模型必须用 MarianTokenizer，不能裸用 sentencepiece。
（ct2-opus-mt-converter 转换的原始 Marian 发布版则两者兼容。）

## 坑 6：collect_all 把 transformers 全家拖进包

`collect_all("onnxruntime")` 会收集 `onnxruntime.transformers` 优化工具子包，
其依赖 transformers（+45MB）；`collect_all("ctranslate2")` 同理（converters 子包）。
这两个包都只需 `collect_dynamic_libs()` 收原生库 + 显式 hiddenimports 推理核心，
最终包 686MB → 271MB（再去掉不随便携的 models 161MB）。

## 构建命令

```bash
pip install pyinstaller opencv-python-headless
cd server
python -m PyInstaller depixpin.spec --noconfirm
# 产物在 dist/depixpin/（约 271MB），把 tools/install.bat、tools/uninstall.bat、README.md 拷入根目录
```

验证清单：
- [ ] exe 裸跑（HTTP 8443）`/api` + `/ocrtransapi` 均 200
- [ ] exe --https（SYSTEM 任务）走 `https://openapi.youdao.com` 全链路 200
- [ ] 根目录无 msvcp140.dll / vcruntime140*.dll / opencv_videoio_ffmpeg*.dll
- [ ] _internal 无 transformers/ 目录
- [ ] _internal 内含 certs/ engines.json/
- [ ] 需要离线引擎时 models/ 放 exe 同级，local_opus 引擎链测试通过

## 2026-11-06：rapidocr 换新版（PP-OCRv6）打包的两个坑

1. **PyInstaller 隔离子进程崩溃**（`SubprocessDiedError: ... importing package 'sentencepiece'`）：
   新版 `rapidocr` 的可选依赖会把 matplotlib 及其 Qt 后端（PyQt5/PySide6/shiboken6）
   拉进依赖图。PyInstaller 在 Windows 上会起隔离子进程逐个 import 所有包以收集
   DLL 搜索路径，Qt 绑定被排到最前加载，随后 import sentencepiece 时子进程硬崩。
   解决：spec 的 excludes 里加 `matplotlib/PyQt5/PySide6/shiboken6/fontTools/contourpy/
   kiwisolver/cycler/python-dateutil`（运行时用不到，rapidocr 的可视化功能不调用）。
2. **打包期间服务没杀干净会 PermissionError**：COLLECT 要先删 dist/depixpin，
   服务进程占着 logs/server.log 就失败。重打包前必须 `taskkill //F //IM depixpin.exe`。

另注：`rapidocr`（新一代）与 `rapidocr_onnxruntime`（旧）是两个包，前者自带
PP-OCRv6 small 模型（det 9.5MB + rec 21MB，打进 _internal/rapidocr/models/），
无需运行时联网下载。
