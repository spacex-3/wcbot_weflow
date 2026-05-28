# New WeChat Bot

这个仓库包含两部分：

- `weflow-api-cli`：基于 WeFlow/WCDB 的微信聊天记录 HTTP API 与 WebSocket 实时推送服务。
- `0.wechat-gptbot-wcf-20260423bk`：微信机器人项目，已接入 `wechat_channel: weflow`，通过 WeFlow API 读取消息并用 OpenAI 兼容接口回复。

当前版本重点解决了 Windows 下新版 WeFlow/WCDB DLL 的宿主校验、动态监控管道、联系人显示名、以及微信引用消息对接问题。

## 功能

- HTTP API 查询会话、消息、联系人和单条消息。
- WebSocket 实时推送新消息，包含 `senderName` / `senderDisplayName`。
- Windows 自动使用 `.runtime/weflow.exe` 作为 WCDB 宿主进程，绕过新版 DLL 对 `node.exe` 的安全校验。
- 支持动态 monitor pipe 名称；管道不可用时自动切换轮询。
- Bot 支持引用消息：
  - 引用文本：把被引用文本和用户追问一起发给模型。
  - 引用图片：复用已解密图片缓存，或按时间戳兜底解密，再按 OpenAI `image_url` 多模态格式发给模型。
  - 引用链接/卡片：把标题、URL 和用户追问一起发给模型。
- 兼容 OpenAI 格式的 Chat Completions API。

## 目录结构

```text
.
├── src/                              # WeFlow API CLI TypeScript 源码
├── resources/                        # WCDB / runtime / key DLL 资源
├── scripts/weflow-host.mjs           # Windows 宿主进程启动器
├── test/                             # WeFlow API CLI 测试
├── 0.wechat-gptbot-wcf-20260423bk/   # 微信机器人项目
│   ├── channel/weflow.py             # WeFlow 通道
│   ├── channel/weflow_quote.py       # 引用消息上下文与图片处理
│   ├── common/
│   ├── bot/
│   └── tests/
├── .env.example                      # WeFlow API CLI 配置模板
├── package.json
└── README.md
```

## 配置

不要提交真实配置。仓库已忽略：

- `.env`
- `config.yaml`
- `config.json`
- `**/config.yaml`
- `**/config.json`
- `.mindfs/`
- 运行时生成的图片、日志和缓存文件

### WeFlow API CLI

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

主要配置：

| 配置项 | 说明 |
| --- | --- |
| `DB_PATH` | `xwechat_files` 目录 |
| `DECRYPT_KEY` | 微信数据库解密 key |
| `MY_WXID` | 当前 bot 登录的微信 ID |
| `HTTP_HOST` / `HTTP_PORT` | HTTP API 监听地址和端口，默认 `127.0.0.1:5031` |
| `WS_HOST` / `WS_PORT` | WebSocket 监听地址和端口，默认 `127.0.0.1:5032` |
| `RESOURCES_PATH` | DLL 资源目录，默认 `./resources` |

### Bot

在 `0.wechat-gptbot-wcf-20260423bk` 下复制模板：

```bash
cd 0.wechat-gptbot-wcf-20260423bk
cp config.template.yaml config.yaml
```

关键配置：

```yaml
wechat_channel: weflow
weflow_http_url: http://127.0.0.1:5031
weflow_ws_url: ws://127.0.0.1:5032
openai_api_base: https://your-openai-compatible-endpoint/v1
openai_api_key: YOUR_API_KEY
model: gpt-5.5
wechat_data_dir: C:\Users\YourName\xwechat_files\wxid_xxx_xxxx
image_xor_key: 31
image_aes_key: your_image_aes_key
```

`wechat_data_dir`、`image_xor_key`、`image_aes_key` 用于解密微信图片 `.dat` 文件；引用图片要能被模型识别，所用模型/API 也必须支持 OpenAI 兼容的视觉输入。

## 运行

安装 WeFlow API CLI 依赖：

```bash
npm install
```

启动 WeFlow API CLI：

```bash
npm run dev
```

生产运行：

```bash
npm run build
npm start
```

Windows 下 `npm run dev` 和 `npm start` 会通过 `scripts/weflow-host.mjs` 自动复制本机 Node 到 `.runtime/weflow.exe`，并用 `weflow.exe` 启动服务。这样可以通过新版 WCDB DLL 的宿主安全校验。

启动 bot：

```bash
cd 0.wechat-gptbot-wcf-20260423bk
pip install -r requirements.txt
python app.py
```

## HTTP API

健康检查：

```http
GET /health
GET /api/v1/health
```

会话列表：

```http
GET /api/v1/sessions?keyword=xxx&limit=100
```

消息列表：

```http
GET /api/v1/messages?talker=wxid_xxx&limit=100&offset=0&chatlab=1
```

单条消息，主要用于解析引用消息：

```http
GET /api/v1/message?talker=wxid_xxx&serverId=1234567890123456789
```

联系人：

```http
GET /api/v1/contacts?keyword=xxx&limit=1000
```

## WebSocket API

连接地址默认：

```text
ws://127.0.0.1:5032/ws
```

订阅全部会话：

```json
{ "type": "subscribe_all" }
```

订阅指定会话：

```json
{ "type": "subscribe", "sessions": ["wxid_xxx", "xxx@chatroom"] }
```

新消息推送示例：

```json
{
  "type": "new_message",
  "sessionId": "fantasysk",
  "message": {
    "sender": "fantasysk",
    "senderName": "Kayson",
    "senderDisplayName": "Kayson",
    "timestamp": 1779933453,
    "type": 25,
    "content": "[引用] 热量有多少",
    "referencedPlatformMessageId": "8123737055266740776",
    "platformMessageId": "6414109638618392825"
  },
  "timestamp": 1779904614677
}
```

常用消息类型：

| type | 含义 |
| --- | --- |
| `0` | 文本 |
| `1` | 图片 |
| `7` | 链接 |
| `25` | 引用 |
| `80` | 系统消息 |
| `99` | 其他 |

## 引用消息处理

Bot 收到 `type=25` 或带 `referencedPlatformMessageId` 的消息后，会：

1. 用 `/api/v1/message` 按 `serverId` 精确查询被引用消息。
2. 如果当前 WeFlow API 没有单条查询接口，则退回到 `/api/v1/messages` 最近消息里匹配。
3. 文本和链接引用会合并到 prompt。
4. 图片引用会优先命中最近已解密图片缓存；缓存未命中时再按消息时间戳和本地时区校正扫描 `.dat`。
5. 图片成功定位后，以 OpenAI `image_url` data URL 格式传给上游模型。

命中图片缓存时，bot 日志会出现：

```text
[WeFlowChannel] Using cached quoted image: ...
```

## 测试

WeFlow API CLI：

```bash
npm test
npm run build
```

Bot：

```bash
cd 0.wechat-gptbot-wcf-20260423bk
python3 -m unittest discover -s tests
python3 -m compileall channel/weflow.py channel/weflow_quote.py common/context.py common/session.py
```

## 注意事项

- 仅在 Windows 微信 4.x 数据库环境下完整验证。
- 本仓库包含 Windows x64 WCDB 运行资源；不要随意混用不同版本的 `resources` 和 DLL。
- 如果 bot 回复“看不到图片”，先看日志是否出现 `Using cached quoted image`。没有出现通常是图片未成功解密或缓存 ID 未命中。
- OpenAI 兼容接口必须支持多模态 `image_url`，否则引用图片只能作为文本占位处理。

## 致谢

- [WeFlow](https://github.com/hicccc77/WeFlow)
- 原 `wechat-gptbot-wcf` 项目
