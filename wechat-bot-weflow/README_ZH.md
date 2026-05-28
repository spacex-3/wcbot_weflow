# WeChat Bot WeFlow 版

这是基于原 `wechat-gptbot-wcf` 改造的微信机器人版本，当前推荐通过上一级目录的 `weflow-api-cli` 接收微信消息，不再使用旧版 WCF / dll 注入流程。

## 能做什么

- 通过 WeFlow API CLI 的 WebSocket 接收私聊和群聊消息。
- 调用 OpenAI 兼容格式的 Chat Completions API 回复。
- 支持私聊前缀、群聊 @、多轮会话、插件、图片生成等原有能力。
- 支持微信引用消息：
  - 引用文本：把原文和追问一起发给模型。
  - 引用图片：复用已解密图片，按 OpenAI `image_url` 格式发给视觉模型。
  - 引用链接/卡片：只在用户引用链接并追问时下载网页正文。
  - 引用聊天记录：解析合并转发里的文本和链接；图片、视频、语音写入占位，不读取媒体。

## 前置条件

1. Windows 微信已登录。
2. 上一级目录的 `weflow-api-cli` 已启动，并能访问：
   - `http://127.0.0.1:5031/health`
   - `ws://127.0.0.1:5032`
3. 已准备一个 OpenAI 兼容接口，例如：
   - `openai_api_base: https://your-endpoint/v1`
   - `openai_api_key: YOUR_API_KEY`
   - `model: gpt-5.5`

WeFlow API CLI 的 `DB_PATH`、`DECRYPT_KEY`、`MY_WXID` 建议先用原版 WeFlow GUI 获取和确认，详见上一级目录的 [README.md](../README.md)。

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制模板：

```bash
cp config.template.yaml config.yaml
```

最小配置：

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
```

如需支持引用图片，还需要配置微信图片解密字段：

```yaml
wechat_data_dir: C:\Users\YourName\xwechat_files\wxid_xxx_xxxx
image_xor_key: 31
image_aes_key: your_image_aes_key
```

引用链接/聊天记录相关配置：

```yaml
quoted_link_fetch_timeout: 10
quoted_link_fetch_max_chars: 12000
quoted_chat_record_link_fetch_limit: 3
quoted_chat_record_link_fetch_max_chars: 4000
assets_retention_days: 7
```

说明：

- `quoted_link_fetch_*` 控制引用链接/卡片时的网页下载超时和正文长度。
- `quoted_chat_record_link_fetch_*` 控制引用聊天记录中嵌套链接的下载数量和正文长度。
- `assets_retention_days` 控制运行时图片文件清理，默认保留 7 天；设为 `0` 可关闭自动清理。
- `config.yaml` 是敏感文件，不要提交到公开仓库。

## 运行

建议运行顺序：

1. 打开并登录 Windows 微信。
2. 在上一级目录启动 WeFlow API CLI：

```bash
npm run dev
```

3. 在当前目录启动 bot：

```bash
python app.py
```

私聊按 `single_chat_prefix` 触发。群聊通常需要 @ bot。

## 测试

```bash
python3 -m unittest discover -s tests
python3 -m compileall channel/weflow.py channel/weflow_quote.py channel/weflow_webpage.py utils/file_cleanup.py common/context.py common/session.py
```

## 注意

- 普通发送链接/卡片不会下载网页，只有“引用链接/卡片并追问”才会下载网页正文。
- 微信公众号等页面可能需要微信环境；代码会尽量用微信浏览器 User-Agent 获取可读正文，但不是所有页面都保证可访问。
- 图片引用需要上游模型/API 支持 OpenAI 兼容的视觉输入。
