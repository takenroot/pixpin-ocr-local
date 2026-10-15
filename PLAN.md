# dePixPin — 给 PixPin 注入免费翻译

> 目标 v2（2026-10-14 修订）：不改 PixPin 任何文件，通过**本地伪有道 API 服务**劫持其翻译请求，
> 让非会员也能在 PixPin 里使用翻译功能（贴图右键菜单 / Ctrl+Q），后端走免费翻译引擎。
> v1 的纯逆向分析目标降级为支撑手段（见 §2 侦察结论，已完成）。

---

## 1. 背景与目标

### 1.1 动机
PixPin 整体体验优秀，但翻译功能要会员（或自配百度/有道付费 API Key）。
希望**保留 PixPin 全部 UI/贴图/动效**，只把翻译内容源换成免费的。
用户已明确：首选"插件化注入"，退路才是用 eSearch 重做全套（已下载 eSearch 备用）。

### 1.2 方案概述（方案①：本地伪 API）

```
PixPin 贴图右键"翻译" / Ctrl+Q
    │  HTTPS openapi.youdao.com（自配 Key 模式，Key 随意填）
    ▼
hosts 劫持 → 127.0.0.1
    ▼
本地 HTTPS 服务（自签 CA，已入 Windows 信任库）
    ├─ POST /api         文本翻译（PixPin 验证 & 文本贴图用）
    └─ POST /ocrtransapi 图片翻译（截图/图像贴图用）
    ▼
免费翻译引擎：腾讯交互翻译 / DeepLX / （可扩展 GLM-4-Flash 等）
    ▼
图片翻译时：本地 OCR（RapidOCR）→ 逐行翻译 → 渲染回图
```

关键依据（均来自侦察，非猜测）：
- PixPin 翻译引擎类结构：`TranslateEngine{Pix,YouDao,Baidu}`，端点硬编码
- 端点：`https://openapi.youdao.com/api`、`/ocrtransapi`（均在 PixPin.exe 字符串中）
- 官方文档确认：配置翻译 API Key 后，**贴图右键菜单出现"翻译"项 + Ctrl+Q 快捷键**
- 官方文档确认：翻译模式可选「图片到图片」/「图片到文本」——自配 Key 也能出文本
- Qt 在 Windows 走系统证书库 → 自签 CA 入信任根即可拦截 HTTPS（Fiddler 同款原理）

### 1.3 合规边界（继承 v1，仍然有效）
- ✅ 只改本机 hosts、装本机自签 CA、跑本机服务 —— 不修改、不 patch PixPin 任何文件
- ❌ 不提取/复用会员密钥令牌，不绕过 PixAuth.dll，不分发破解
- ❌ 伪 API 只服务本机 PixPin，不对公网开放，不薅官方额度
- ⚠️ 仅用于个人学习研究；PixPin 更新导致协议变化时随时可停（回退 = 删 hosts 行 + 卸载 CA）

---

## 2. 侦察结论（v1 已完成，作为本方案的事实基础）

- PixPin = Qt5 原生应用（非 Electron），UI 为 QML/Widgets 混合
- OCR 纯本地：`model/` 下 Caffe 检测 + ONNX 识别 + 超分（与"离线 OCR"宣传一致）
- `plugins/` 仅为 Qt 运行时插件，**无业务插件机制** → 插件化只能走网络层劫持
- 会员锁边界：image-to-image 支持自配 Key（非会员可用）；部分 OCR 能力（如 QR 类型）会员专属
- 配置文件：`%LOCALAPPDATA%\PixPin\Config\PixPinConfig.json`，格式 `{"键":{"t":时间戳,"v":值}}`
- 翻译设置入口：PixPin 设置 → 系统 → 翻译（APP ID + Secret key + 验证按钮）

---

## 3. 本地环境状态

| 依赖 | 状态 |
|---|---|
| Node.js v24.21.0 / JDK 17/21 / Python 3.14 | ✅ |
| 本项目服务栈 | Python：FastAPI/Flask + Pillow + RapidOCR + requests |
| openssl（Git Bash 自带） | ✅ 用于 CA/证书签发 |
| Ghidra / REA / 抓包工具 | 暂缓（协议细节优先靠"伪造响应试错"定位，必要时再上抓包） |

---

## 4. 执行阶段（状态：B/C/D 已完成 ✅，E 进行中）

### Phase B：本地伪有道 API 服务（✅ 完成）
- `server/app.py`：Flask 实现 `/api` + `/ocrtransapi` + `/healthz`，支持 HTTP 调试 / HTTPS 生产
- 协议试错结论（findings/protocol.md）：PixPin 解析 **snake_case** 键，`render_image` 为验证硬性要求，响应需双写两套键名
- RapidOCR + Pillow 渲染回图已验证；OCR 与模型零外联

### Phase C：TLS 劫持层（✅ 完成）
- openssl 自签 CA（`certs/depixpin-ca.crt`）+ 叶子证书（SAN=openapi.youdao.com）
- hosts 已劫持；CA 已入 Root；curl-schannel 需 `--ssl-no-revoke`（Qt/OpenSSL 后端无此问题，实测 PixPin 无感）

### Phase D：PixPin 联调（✅ 完成）
- 验证通过（发图到 /ocrtransapi + 检查 render_image）；多次真实翻译成功
- 发现：设置页翻译区块在「系统」页**向下滚动**处；entry 为右键菜单 + Ctrl+Q

### Phase E：加固与交付（✅ 完成）
- E1 ✅ 引擎配置化（engines.json 热加载）+ 熔断降级（连失败 3 次冷却 300s）
- E1 ✅ 本地离线引擎 local_opus（opus-mt CT2 int8，中英双向 78MB×2， transformers tokenizer 无 torch 运行）
- E2 ✅ PyInstaller 便携包（4 轮修复：VC 运行库遮蔽 / 冻结路径 / session0 挂死 / CT2 int token，见 findings/packaging.md）
- E2 ✅ install/uninstall v2（hosts + CA + 任务计划程序自启 + 自测）
- E2 ✅ SYSTEM 任务托管 exe 走真实劫持域名全链路验证通过

## 5. 最终交付物

```
E:\Project\depixpin\
├── README.md                 # 原理 + 安装/卸载/配置/FAQ
├── PLAN.md                   # 本文件
├── findings\
│   ├── protocol.md           # PixPin 有道协议逆向笔记（snake_case/render_image 等）
│   └── packaging.md          # 打包踩坑记录
├── tools\install.bat         # 一键安装（自启注册）
├── tools\uninstall.bat       # 一键卸载
└── server\
    ├── app.py                # 伪有道 API 服务
    ├── engines/              # deepl_web / mymemory / local_opus + 熔断降级
    ├── ocr_render.py         # RapidOCR + 渲染
    ├── models/               # ct2-opus-mt-en-zh / ct2-opus-mt-zh-en（161MB）
    ├── certs/                # 自签 CA + 叶子证书（CA 私钥仅开发机）
    └── dist\depixpin\        # ★ 便携包成品（拷此文件夹到其他设备即可）
```

## 6. 已知限制

- DeepL 引擎依赖其 iOS 客户端协议常量（`deepl_web.py` 中版本号），DeepL 大版本更新后可能失效
  → 表现为该引擎熔断降级到后备引擎；修复 = 从 DeepLX 源码同步常量重新打包
- local_opus 仅中英互译；其余语言对需自行转换模型（findings/packaging.md 有方法）
- 仅支持 Windows（PixPin 本身只有 Windows/macOS；本方案依赖 Windows 证书库与任务计划程序）
- 与 Watt Toolkit 共存实测无碍，但如其更新实现占用 127.0.0.1:443 精确绑定则需协商端口

---

## 5. 目录规划

```
E:\Project\depixpin\
├── PLAN.md            ← 本文件
├── server\            # 伪有道 API 服务（Python）
│   ├── app.py         # HTTP/HTTPS 入口，/api + /ocrtransapi
│   ├── engines\       # 免费翻译引擎适配层
│   ├── ocr\           # RapidOCR 封装 + 渲染
│   └── certs\         # CA 与服务器证书（私钥不入库）
├── findings\          # 协议格式、试错记录
├── captures\          # （备用）抓包记录
└── tools\             # hosts 修改/回退脚本
```

## 6. 风险与回退

| 风险 | 应对 |
|---|---|
| PixPin 升级换协议/格式 | 响应格式集中在渲染层，改一处即可；最坏回退删 hosts + 卸载 CA |
| PixPin 证书固定（pinning） | 侦察未见迹象（Qt 默认走系统库）；若失败则改用代理注入方案重评 |
| 免费引擎失效/限流 | 适配层多引擎互备，新增引擎只需实现 `translate(text, src, dst)` |
| 有道"图片到文本"模式客户端校验 | Phase D 联调时实测；若客户端强制云模式，则文本形态由 OCR+引擎在伪服务内自行拼装 |
