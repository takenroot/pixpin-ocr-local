# PixPin 有道翻译协议实现笔记

> 版本：PixPin 3.5.5.1（2026-10-14 实测）
> 来源：PixPin.exe 字符串/符号侦察 + 本地伪 API 试错联调（ PixPin 日志 + 服务侧请求记录）

## 背景

PixPin 内置三个翻译引擎类（`TranslateEngine` 基类）：

| 类 | 端点 | 用途 |
|---|---|---|
| `TranslateEnginePix` | `https://api.pixpin.cn` `/api2/ai/translate/{text,image}`、`/api2/tr/translate/{text,image}` | 会员云 |
| `TranslateEngineYouDao` | `https://openapi.youdao.com/api`、`/ocrtransapi` | 自配 Key（本方案冒充对象） |
| `TranslateEngineBaidu` | `https://api.fanyi.baidu.com/api/trans/{vip/translate,sdk/picture}` | 自配 Key |

关键约束（程序内字符串原文）：

> *"Only image-to-image translation uses the custom API key. Image-to-text translation still uses the cloud service provided by PixPin."*

即：自配 Key 走图片翻译（ocrtransapi）；文本贴图/图片到文本模式走会员云。

## 文本翻译 `POST /api`

请求（application/x-www-form-urlencoded）：

| 字段 | 说明 |
|---|---|
| q | 待译文本 |
| from / to | 语言码（auto / zh-CHS / en / ...） |
| appKey / salt / sign / signType / curtime | 有道 v3 签名体系，**PixPin 不校验响应签名的对应关系，伪服务可全忽略** |

成功响应（PixPin 接受的最小集）：

```json
{ "errorCode": "0", "query": "...", "translation": ["..."], "l": "auto2zh-CHS" }
```

## 图片翻译 `POST /ocrtransapi`

请求字段：`type=1`（base64）、`q`=图片 base64、`from`、`to`、`render`（0/1）、`appKey/salt/sign/signType=v3/curtime`。

成功响应（实测 PixPin 解析的键名是 **snake_case**，官方文档是 camelCase——**必须双写**）：

```json
{
  "errorCode": "0",
  "orientation": "Up",
  "textAngle": "0",
  "lanFrom": "en", "lan_from": "en",
  "lanTo": "zh-CHS", "lan_to": "zh-CHS",
  "resRegions": [ ... ], "res_regions": [ ... ],
  "renderImage": "<base64>", "render_image": "<base64>"
}
```

`resRegions[]` / `res_regions[]` 元素：

```json
{
  "boundingBox": "x,y,w,h", "bounding_box": "x,y,w,h",
  "linesCount": 2, "lines_count": 2,
  "lineheight": 28, "linespace": 4,
  "context": "原文", "tranContent": "译文", "tran_content": "译文",
  "lines": [ { "words": [...], "text": "译文行", "textHeight": 28 } ]
}
```

## Key 验证流程

设置页点"验证"→ PixPin 生成一张内置图片 → POST `/ocrtransapi`（render=1）→ **检查响应含 `render_image`**（缺失时报错 `Json object does not contain render_image.`）→ 展示验证结果。验证只测图片翻译能力，不测 `/api`。

## 其他观察

- 请求走 Qt 网络栈（`QNetworkAccessManager`），Windows 下 TLS 用 OpenSSL（目录有 `libssl-1_1-x64.dll`），证书验证走**系统证书库** → 自签 CA 入 Root 即可（无证书固定）
- 翻译入口：贴图右键菜单（配置 Key 后出现）、快捷键 `Ctrl+Q`、贴图/截图标注工具栏（可在工具栏配置中加出）
- 设置页位置：设置 → **系统** → 向下滚动 → "翻译"区块（不在左侧导航里，3.5.5.1 易找不到）
- 错误码约定沿用有道：`0` 成功；本实现自定义 `411` 表示引擎链全部失败（借用官方"访问频率超限"码位）
