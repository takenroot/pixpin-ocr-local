# dePixPin — 给 PixPin 注入免费翻译

让 PixPin 的非会员用户**免费使用截图/贴图翻译**：不改 PixPin 一个文件，通过本地伪 API 服务劫持其翻译请求，后端走免费翻译引擎（DeepL 免费接口 / MyMemory / 本地离线模型，自动降级互备）。

> 仅限个人学习研究使用。不绕过会员鉴权、不薅官方翻译额度；`uninstall.bat` 一键完全回退。

---

## 原理（怎么做到的）

PixPin 的翻译功能对非会员开放了一条官方通道：**自配有道/百度 API Key**。程序内部翻译引擎是硬编码的三选一（`TranslateEngine{Pix, YouDao, Baidu}`），会员与非会员的区别只是密钥来源不同——协议本身是有道/百度的公开 API。

于是只要做三件事，就能让 PixPin 的翻译请求改道到我们自己手里：

```
┌─────────────┐   HTTPS openapi.youdao.com   ┌──────────────────────────┐
│   PixPin    │ ───────────────────────────► │  hosts 劫持 → 127.0.0.1   │
│ (自配Key模式)│                              │  自签CA证书(已入系统信任库) │
└─────────────┘                              └────────────┬─────────────┘
                                                          ▼
                                              ┌──────────────────────┐
                                              │  depixpin 本地服务 :443 │
                                              │  完整实现有道 API 协议:  │
                                              │   POST /api          │──► 引擎链(自动降级)
                                              │   POST /ocrtransapi  │──► RapidOCR + 渲染
                                              └──────────────────────┘
```

1. **伪造**：`depixpin.exe` 完整实现有道 `/api`（文本）和 `/ocrtransapi`（图片）协议，签名验证直接忽略，Key 随便填
2. **劫持**：hosts 把 `openapi.youdao.com` 指到 127.0.0.1；自签 CA 装进 Windows 信任根，Qt（走系统证书库）就会信任我们的证书，HTTPS 无感接管
3. **翻译**：文本进引擎链；图片先本地 OCR（RapidOCR），逐行翻译后渲染回原图
4. **容错**：引擎链按 `engines.json` 顺序执行，某引擎连失败 3 次自动熔断 5 分钟，依次降级：

   | 引擎 | 说明 | 需要联网 |
   |---|---|---|
   | `deepl_oneshot` | DeepL 免费接口（iOS 客户端协议移植），质量最佳 | ✅ |
   | `mymemory` | MyMemory 免费接口，质量一般 | ✅ |
   | `local_opus` | opus-mt 本地模型（CTranslate2 int8，78MB×2），完全离线 | ❌ |

   PixPin 侧验证通过的表现 = 翻译一个 "Hello" 成功；此后贴图右键出现"翻译"，快捷键 `Ctrl+Q`。

### 逆向中试错得出的协议要点（详见 findings/protocol.md）

- PixPin 验证 Key 是发一张图到 `/ocrtransapi` 并检查响应里的 **`render_image`**（snake_case！）字段
- 响应需同时带 camelCase 与 snake_case 两套键名
- 图片到图片模式由 PixPin 直接用响应中的渲染图；图片到文本模式用 `res_regions[].tran_content`

---

## 安装（每台 Windows 设备）

**前提**：已安装 PixPin。

1. 解压/拷贝整个 `depixpin` 文件夹到任意位置（如 `D:\tools\depixpin`）
2. 右键 **`install.bat` → 以管理员身份运行**（自动：备份并修改 hosts → 安装根证书 → 注册开机自启任务 → 启动服务并自测）
3. 打开 PixPin → 设置 → 系统 → **向下滚动找到"翻译"** → 翻译服务选"有道翻译"
4. **APP ID 和密钥随便填**（如 `depixpin` / `depixpin`），点**验证** → 应提示成功
5. 使用：贴图右键 → 翻译，或选中贴图按 `Ctrl+Q`；截图工具栏也有翻译入口

服务以 SYSTEM 权限开机自启（任务计划程序），不登录也在跑。日志在 `logs\server.log`。

### 卸载

右键 **`uninstall.bat` → 以管理员身份运行**：删除自启任务、移除 hosts 记录、卸载根证书。PixPin 恢复原状。

---

## 配置（`engines.json`）

```json
{
  "chain": ["deepl_oneshot", "mymemory", "local_opus"],
  "cooldown_seconds": 300,
  "max_consecutive_failures": 3,
  "engines": {
    "deepl_oneshot": { "enabled": true },
    "mymemory":      { "enabled": true },
    "local_opus":    { "enabled": true, "model_dir": "models", "pairs": ["en-zh", "zh-en"] }
  }
}
```

- 调整 `chain` 顺序即调整优先级；`enabled: false` 停用某引擎
- 新增语言对：开发机用 `ct2-opus-mt-converter` 转换模型放进 `models/ct2-opus-mt-<a>-<b>/`，在 `pairs` 里登记
- 修改即时生效（按文件修改时间热加载），无需重启服务

## FAQ

**验证失败？**
先看 `logs\server.log`：没有任何请求记录 → hosts/服务问题（重跑 install.bat）；有记录但报错 → 看错误内容。

**Windows Defender 报 hosts 被修改？**
预期行为（`PossibleHostsFileHijack`），这是我们自己改的，允许即可。

**装了 Watt Toolkit（Steam++）会冲突吗？**
实测不冲突。它监听 `0.0.0.0:443`，我们监听 `127.0.0.1:443`，精确绑定优先。

**翻译第一次很慢？**
`local_opus` 首次调用需加载模型（几秒）；RapidOCR 首次运行初始化推理引擎。之后正常。

**DeepL 引擎失效？**
DeepL 升级 iOS 客户端后协议常量可能过期（表现：该引擎连续失败自动熔断，降级到后备引擎）。更新 `server/engines/deepl_web.py` 中的 `_IOS_APP_VERSION` 等常量后重新打包，或直接从 DeepLX 项目源码同步。

**多台电脑使用？**
整个 `depixpin` 文件夹拷贝过去跑一遍 install.bat 即可（证书和域名都是通用的）。
需要离线翻译兜底的话，把 `models/` 文件夹一并拷到 `depixpin.exe` 同级目录。
项目根目录另备有 `depixpin-models.zip`（144MB，压缩好的模型包，解压即是 models/）。

## 项目结构

```
depixpin/
├── install.bat / uninstall.bat   # 一键安装/卸载
├── depixpin.exe                  # 服务本体（PyInstaller 打包，内嵌 Python）
├── _internal/                    # 运行时（证书/配置/日志）
├── models/                       # 可选：离线翻译模型（161MB，不随便携包）
│                                  #   需要断网兜底时，把 models/ 拷到 depixpin.exe 同级目录
├── server/                       # 源码（开发用）
│   ├── app.py                    #   伪有道 API 服务
│   ├── engines/                  #   引擎链：deepl_web / mymemory / local_opus
│   ├── ocr_render.py             #   RapidOCR + 译文回图渲染
│   └── depixpin.spec             #   PyInstaller 配置
└── findings/protocol.md          # PixPin 有道协议逆向笔记
```

## 合规声明

- 仅分析/修改**本机**软件行为用于互操作性研究，不修改、不 patch PixPin 任何文件
- 伪 API 只监听 127.0.0.1，仅服务本机，不薅有道/百度官方翻译额度
- 不提取、不复用 PixPin 会员密钥，不绕过其鉴权体系
- 随时可用 uninstall.bat 完全回退，不留痕迹
