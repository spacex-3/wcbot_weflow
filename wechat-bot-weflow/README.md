# WeChat Bot WeFlow Edition

This is a WeFlow-backed fork of `wechat-gptbot-wcf`. It receives WeChat messages from the sibling `weflow-api-cli` service and replies through an OpenAI-compatible Chat Completions API. The old WCF / DLL injection flow is not required for this edition.

## Features

- Receive private and group messages through WeFlow API CLI WebSocket.
- Reply with any OpenAI-compatible chat model endpoint.
- Keep the original bot features such as prefixes, group mentions, session memory, plugins, and image generation.
- Handle quoted WeChat messages:
  - quoted text: sends the quoted text plus the user follow-up to the model;
  - quoted image: reuses decrypted image files and sends them as OpenAI `image_url` data URLs;
  - quoted link/card: fetches webpage text only when the user quotes the link/card and asks a question;
  - quoted chat record: parses forwarded text and links; image/video/audio entries are represented with placeholders.

## Requirements

1. Windows WeChat is logged in.
2. The sibling `weflow-api-cli` service is running:
   - `http://127.0.0.1:5031/health`
   - `ws://127.0.0.1:5032`
3. You have an OpenAI-compatible endpoint:
   - `openai_api_base: https://your-endpoint/v1`
   - `openai_api_key: YOUR_API_KEY`
   - `model: gpt-5.5`

Use the original WeFlow GUI first to obtain and verify the CLI fields `DB_PATH`, `DECRYPT_KEY`, and `MY_WXID`. See the parent [README.md](../README.md).

## Install

```bash
pip install -r requirements.txt
```

## Configure

Copy the template:

```bash
cp config.template.yaml config.yaml
```

Minimal config:

```yaml
wechat_channel: weflow
weflow_http_url: http://127.0.0.1:5031
weflow_ws_url: ws://127.0.0.1:5032

openai_api_base: https://your-openai-compatible-endpoint/v1
openai_api_key: YOUR_API_KEY
model: gpt-5.5

role_desc: You are a helpful assistant.
single_chat_prefix:
  - ''
  - '@bot'
chat_group_session_independent: true
```

To support quoted images, also configure WeChat image decryption:

```yaml
wechat_data_dir: C:\Users\YourName\xwechat_files\wxid_xxx_xxxx
image_xor_key: 31
image_aes_key: your_image_aes_key
```

Quoted webpage and chat-record controls:

```yaml
quoted_link_fetch_timeout: 10
quoted_link_fetch_max_chars: 12000
quoted_chat_record_link_fetch_limit: 3
quoted_chat_record_link_fetch_max_chars: 4000
assets_retention_days: 7
```

Notes:

- `quoted_link_fetch_*` controls quoted link/card webpage fetching.
- `quoted_chat_record_link_fetch_*` controls nested links inside quoted chat records.
- `assets_retention_days` controls runtime image cleanup. The default is 7 days; `0` disables cleanup.
- `config.yaml` contains secrets and should not be committed.

## Run

Recommended order:

1. Open and log in to Windows WeChat.
2. Start WeFlow API CLI in the parent directory:

```bash
npm run dev
```

3. Start the bot in this directory:

```bash
python app.py
```

Private chats are triggered by `single_chat_prefix`. Group chats usually require mentioning the bot.

## Test

```bash
python3 -m unittest discover -s tests
python3 -m compileall channel/weflow.py channel/weflow_quote.py channel/weflow_webpage.py utils/file_cleanup.py common/context.py common/session.py
```

## Notes

- Plain link/card messages do not trigger webpage fetching. Fetching runs only when the user quotes a link/card and asks a question.
- Some WeChat article pages require a WeChat-like browser environment. The code uses a WeChat browser User-Agent where possible, but not every page is guaranteed to be accessible.
- Quoted image support requires an upstream OpenAI-compatible vision model/API.
