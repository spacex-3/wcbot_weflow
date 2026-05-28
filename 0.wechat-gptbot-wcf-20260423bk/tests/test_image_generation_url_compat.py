import sys
import types

if "yaml" not in sys.modules:
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *args, **kwargs: {}
    sys.modules["yaml"] = yaml_stub

if "lxml" not in sys.modules:
    lxml_stub = types.ModuleType("lxml")
    lxml_stub.etree = types.SimpleNamespace(fromstring=lambda *args, **kwargs: None)
    sys.modules["lxml"] = lxml_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.api_key = None
    openai_stub.api_base = None
    openai_stub.proxy = None
    openai_stub.Image = types.SimpleNamespace(create=lambda **kwargs: {"data": []})
    openai_stub.ChatCompletion = types.SimpleNamespace(create=lambda **kwargs: None)
    openai_stub.error = types.SimpleNamespace(
        RateLimitError=Exception,
        APIConnectionError=Exception,
        Timeout=Exception,
        APIError=Exception,
    )
    sys.modules["openai"] = openai_stub

import base64
import os
import tempfile
import unittest

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
            normalize_media_url(
                "https://example.com/a.png", "http://192.168.1.26:8080/v1"
            ),
            "https://example.com/a.png",
        )

    def test_local_file_is_not_remote_media(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            self.assertFalse(should_download_remote_media(tmp.name))

    def test_unix_absolute_missing_path_is_not_rewritten(self):
        missing_path = "/tmp/not-exists.png"
        self.assertEqual(normalize_media_url(missing_path), missing_path)
        self.assertFalse(should_download_remote_media(missing_path))

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


if __name__ == "__main__":
    unittest.main()
