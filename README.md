# WCBot WeFlow

这个仓库把两部分放在一起：

- `weflow-api-cli`：基于 WeFlow/WCDB 的微信聊天记录 HTTP API 和 WebSocket 实时推送服务。
- `wechat-bot-weflow`：微信机器人，使用 `wechat_channel: weflow` 从 WeFlow API 接收消息，再调用 OpenAI 兼容接口回复。

## 主要能力

- HTTP API 查询会话、消息、联系人和单条消息。
- WebSocket 实时推送新消息，包含发送者 ID、昵称和显示名。
- Windows 下自动用 `.runtime/weflow.exe` 作为 WCDB 宿主进程，适配新版 WCDB DLL 的宿主校验。
- Bot 支持引用文本、图片、链接/卡片、合并转发聊天记录。
- 引用链接/卡片时，本地先下载网页正文，再把网页内容和用户追问一起发给模型。
- 引用聊天记录时，解析合并转发里的文本和链接；图片、视频、语音只写入占位，不请求媒体内容。

## 目录结构

```text
.
├── src/                    # WeFlow API CLI TypeScript 源码
├── resources/              # WCDB / runtime / key DLL 资源
├── scripts/weflow-host.mjs # Windows 宿主进程启动器
├── test/                   # WeFlow API CLI 测试
├── wechat-bot-weflow/      # 微信机器人
├── .env.example            # WeFlow API CLI 配置模板
├── package.json
└── README.md
```

## 先用原版 WeFlow 获取配置

第一次部署建议先下载并运行原版 WeFlow GUI（原项目：[hicccc77/WeFlow](https://github.com/hicccc77/WeFlow)）：

1. 在 Windows 上安装并启动原版 WeFlow。
2. 登录同一个微信账号，确认原版 WeFlow 能正常读取聊天记录。
3. 从原版 WeFlow 的配置或界面里确认 CLI 需要的字段：
   - `DB_PATH`：`xwechat_files` 目录，例如 `C:\Users\YourName\xwechat_files`
   - `DECRYPT_KEY`：微信数据库解密 key
   - `MY_WXID`：当前登录微信的 wxid
4. 再把这些值填入本项目的 `.env`。

如果原版 WeFlow 都无法读取聊天记录，先解决原版 WeFlow 的数据库路径、解密 key、微信账号匹配问题，再启动本 CLI。

## 配置 WeFlow API CLI

复制模板：

```bash
cp .env.example .env
```

填写核心字段：

```env
DB_PATH=C:\Users\YourName\xwechat_files
DECRYPT_KEY=your_decrypt_key
MY_WXID=wxid_xxx
HTTP_HOST=127.0.0.1
HTTP_PORT=5031
WS_HOST=127.0.0.1
WS_PORT=5032
RESOURCES_PATH=./resources
```

安装依赖并启动：

```bash
npm install
npm run dev
```

生产运行：

```bash
npm run build
npm start
```

Windows 下 `npm run dev` 和 `npm start` 会通过 `scripts/weflow-host.mjs` 自动复制本机 Node 到 `.runtime/weflow.exe`，再用 `weflow.exe` 启动服务。

## 配置 WeChat Bot

进入 bot 目录并复制模板：

```bash
cd wechat-bot-weflow
cp config.template.yaml config.yaml
```

最小配置示例：

```yaml
wechat_channel: weflow
weflow_http_url: http://127.0.0.1:5031
weflow_ws_url: ws://127.0.0.1:5032

openai_api_base: https://your-openai-compatible-endpoint/v1
openai_api_key: YOUR_API_KEY
model: gpt-5.5

role_desc: 你是一个人工智能助手。
single_chat_prefix:
  - ''
  - '@bot'
chat_group_session_independent: true

wechat_data_dir: C:\Users\YourName\xwechat_files\wxid_xxx_xxxx
image_xor_key: 31
image_aes_key: your_image_aes_key
quoted_link_fetch_timeout: 10
quoted_link_fetch_max_chars: 12000
quoted_chat_record_link_fetch_limit: 3
quoted_chat_record_link_fetch_max_chars: 4000
assets_retention_days: 7
```

说明：

- `weflow_http_url` / `weflow_ws_url` 指向上面启动的 WeFlow API CLI。
- `wechat_data_dir`、`image_xor_key`、`image_aes_key` 用于解密微信图片 `.dat` 文件。只用文本和链接引用时可以先不配置图片解密。
- `quoted_link_fetch_*` 控制引用链接/卡片时的网页下载。
- `quoted_chat_record_link_fetch_*` 控制引用聊天记录里嵌套链接的下载数量和正文长度。
- `assets_retention_days` 控制运行时图片文件保留天数，默认 7 天；设为 `0` 可关闭自动清理。

启动 bot：

```bash
pip install -r requirements.txt
python app.py
```

运行顺序建议：

1. 先打开并登录 Windows 微信。
2. 启动 WeFlow API CLI：`npm run dev`
3. 启动 bot：`python app.py`
4. 私聊按 `single_chat_prefix` 触发；群聊需要 @ bot。

## 引用消息处理

Bot 收到 `type=25` 或带 `referencedPlatformMessageId` 的消息后，会：

1. 用 `/api/v1/message` 按 `serverId` 查询被引用消息。
2. 查不到时退回 `/api/v1/messages` 最近消息匹配。
3. 文本引用：把被引用文本和用户追问合并到 prompt。
4. 图片引用：优先复用已解密图片缓存；成功后按 OpenAI `image_url` data URL 格式发给上游模型。
5. 链接/卡片引用：下载网页正文，把标题、URL、网页内容和用户追问一起发给模型。
6. 聊天记录引用：解析 `recorditem` 中的文本和链接；图片、视频、语音只写入 `[图片暂不读取]` 等占位。

普通发送链接/卡片不会触发网页下载，只有“引用链接/卡片并追问”才触发。

## HTTP API

```http
GET /health
GET /api/v1/health
GET /api/v1/sessions?keyword=xxx&limit=100
GET /api/v1/messages?talker=wxid_xxx&limit=100&offset=0&chatlab=1
GET /api/v1/message?talker=wxid_xxx&serverId=1234567890123456789
GET /api/v1/contacts?keyword=xxx&limit=1000
```

## WebSocket API

默认地址：

```text
ws://127.0.0.1:5032
```

订阅全部会话：

```json
{ "type": "subscribe_all" }
```

订阅指定会话：

```json
{ "type": "subscribe", "sessions": ["wxid_xxx", "xxx@chatroom"] }
```

## 测试

WeFlow API CLI：

```bash
npm test
npm run build
```

Bot：

```bash
cd wechat-bot-weflow
python3 -m unittest discover -s tests
python3 -m compileall channel/weflow.py channel/weflow_quote.py channel/weflow_webpage.py utils/file_cleanup.py common/context.py common/session.py
```

## 隐私和公开仓库注意事项

不要提交真实配置。仓库已忽略：

- `.env`
- `config.yaml`
- `config.json`
- `.mindfs/`
- `__pycache__/`
- 运行时生成的图片、日志和缓存文件

公开仓库保留模板文件：

- `.env.example`
- `wechat-bot-weflow/config.template.yaml`

## 致谢

- [WeFlow](https://github.com/hicccc77/WeFlow)
- 原 `wechat-gptbot-wcf` 项目
