# Image Generation URL Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 兼容非插件生图接口返回的相对图片 URL，同时保留现有绝对 URL、`b64_json`、本地文件路径能力。

**Architecture:** 在 bot 层补全相对图片 URL，在公共序列化层统一封装远程媒体 URL 识别与规范化逻辑，并在各个发送 channel 中使用统一规则判断是否需要下载。通过自动化测试锁定兼容行为，避免回归。

**Tech Stack:** Python 3、unittest、requests、urllib.parse

---

### Task 1: 为图片 URL 兼容新增失败测试

**Files:**
- Create: `tests/test_image_generation_url_compat.py`

- [ ] **Step 1: 写失败测试，覆盖相对 URL 与旧行为保留**

```python
import base64
import os
import tempfile
import unittest
from unittest.mock import patch

import config
from bot.chatgpt import ChatGPTBot
from common.reply import ReplyType
from utils.serialize import normalize_media_url, should_download_remote_media


class ImageGenerationUrlCompatTest(unittest.TestCase):
    def setUp(self):
        config.config = {
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "create_image_api_base": "http://192.168.1.26:8080/v1",
            "openai_api_base": "http://fallback.example/v1",
        }

    def test_normalize_relative_image_url(self):
        self.assertEqual(
            normalize_media_url("/p/img/abc", "http://192.168.1.26:8080/v1"),
            "http://192.168.1.26:8080/p/img/abc",
        )

    def test_keep_absolute_image_url(self):
        self.assertEqual(
            normalize_media_url("https://example.com/a.png", "http://192.168.1.26:8080/v1"),
            "https://example.com/a.png",
        )

    def test_local_file_is_not_remote_media(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            self.assertFalse(should_download_remote_media(tmp.name))

    def test_chatgpt_bot_returns_normalized_relative_url(self):
        bot = ChatGPTBot()
        reply = bot._handle_image_data({"url": "/p/img/abc?sig=1"})
        self.assertEqual(reply.type, ReplyType.IMAGE)
        self.assertEqual(
            reply.content,
            "http://192.168.1.26:8080/p/img/abc?sig=1",
        )

    def test_chatgpt_bot_keeps_b64_json_behavior(self):
        bot = ChatGPTBot()
        raw = base64.b64encode(b"fake-image-bytes").decode("utf-8")
        reply = bot._handle_image_data({"b64_json": raw})
        self.assertEqual(reply.type, ReplyType.IMAGE)
        self.assertTrue(os.path.exists(reply.content))
        os.remove(reply.content)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest discover -s tests -p 'test_image_generation_url_compat.py' -v`
Expected: FAIL，提示 `normalize_media_url` / `should_download_remote_media` 未定义或相对 URL 断言失败。

### Task 2: 实现公共媒体 URL 规范化能力

**Files:**
- Modify: `utils/serialize.py`
- Test: `tests/test_image_generation_url_compat.py`

- [ ] **Step 1: 在 `utils/serialize.py` 增加远程媒体识别与 URL 规范化函数**

```python
from urllib.parse import urljoin, urlparse
from config import conf


def normalize_media_url(file_url: str, api_base: str | None = None) -> str:
    ...


def should_download_remote_media(file_ref: str, api_base: str | None = None) -> bool:
    ...
```

- [ ] **Step 2: 让 `serialize_file()` 下载前先使用规范化后的 URL**

```python
normalized_url = normalize_media_url(file_url)
response = requests.get(normalized_url, stream=True)
```

- [ ] **Step 3: 运行测试确认第一批测试通过**

Run: `python3 -m unittest discover -s tests -p 'test_image_generation_url_compat.py' -v`
Expected: 与 `utils.serialize` 相关的测试 PASS。

### Task 3: 在 ChatGPTBot 中补全相对图片 URL

**Files:**
- Modify: `bot/chatgpt.py`
- Test: `tests/test_image_generation_url_compat.py`

- [ ] **Step 1: 为 `ChatGPTBot` 增加图片 URL 基础地址选择逻辑**

```python
def _get_image_api_base(self):
    return conf().get("create_image_api_base", "") or conf().get("openai_api_base", "")
```

- [ ] **Step 2: 在 `_handle_image_data()` 中规范化 `url` 字段**

```python
if image_data.get("url"):
    image_url = normalize_media_url(image_data["url"], self._get_image_api_base())
    return Reply(ReplyType.IMAGE, image_url)
```

- [ ] **Step 3: 运行测试确认 bot 侧行为通过**

Run: `python3 -m unittest discover -s tests -p 'test_image_generation_url_compat.py' -v`
Expected: bot 相关断言 PASS，`b64_json` 行为仍通过。

### Task 4: 在 channel 层补齐远程媒体判断

**Files:**
- Modify: `channel/weflow.py`
- Modify: `channel/wechat.py`
- Modify: `channel/wrest.py`
- Test: `tests/test_image_generation_url_compat.py`

- [ ] **Step 1: `weflow.py` 改为通过统一函数判断是否需要下载图片**

```python
from utils.serialize import serialize_img, serialize_video, should_download_remote_media

if reply.type == ReplyType.IMAGE:
    if should_download_remote_media(path):
        path = serialize_img(path)
```

- [ ] **Step 2: `wechat.py` 与 `wrest.py` 发送图片前统一下载远程图片**

```python
if reply.type == ReplyType.IMAGE:
    img_path = reply.content
    if should_download_remote_media(img_path):
        img_path = serialize_img(img_path)
```

- [ ] **Step 3: 再次运行测试，确认没有回归**

Run: `python3 -m unittest discover -s tests -p 'test_image_generation_url_compat.py' -v`
Expected: PASS。

### Task 5: 运行静态检查并人工验证关键路径

**Files:**
- Modify: none
- Test: `tests/test_image_generation_url_compat.py`

- [ ] **Step 1: 执行目标测试**

Run: `python3 -m unittest discover -s tests -p 'test_image_generation_url_compat.py' -v`
Expected: PASS。

- [ ] **Step 2: 执行语法检查**

Run: `python3 -m compileall bot channel utils tests`
Expected: Compile success，无语法错误。

- [ ] **Step 3: 总结人工回放路径**

Run: `printf '%s\n' 'create_image_api_base=/v1' 'response.url=/p/img/...' 'bot normalize -> absolute url' 'channel serialize -> local temp file'`
Expected: 输出兼容链路说明。
