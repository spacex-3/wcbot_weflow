import base64
import os
import sys
import tempfile
import types
import unittest

if "yaml" not in sys.modules:
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *args, **kwargs: {}
    sys.modules["yaml"] = yaml_stub

import config
from channel.weflow_quote import (
    build_quote_context,
    cache_image_path,
    candidate_image_timestamps,
    extract_link_url,
    extract_referenced_message_id,
    get_cached_image_path,
    is_weflow_reply_message,
    strip_weflow_reply_marker,
)
from common.context import Context
from common.session import Session


class WeFlowQuoteContextTest(unittest.TestCase):
    def setUp(self):
        config.config = {
            "role_desc": "你是一个助手。",
            "session_expired_duration": 3600,
            "max_tokens": 4000,
        }
        Session.clear_all_session()

    def test_reply_message_detection_accepts_chatlab_reply_type_and_reference_id(self):
        self.assertTrue(is_weflow_reply_message(25, {}))
        self.assertTrue(
            is_weflow_reply_message(0, {"referencedPlatformMessageId": "2026828130733625346"})
        )
        self.assertFalse(is_weflow_reply_message(0, {}))

    def test_extract_referenced_message_id_accepts_weflow_payload_names(self):
        self.assertEqual(
            extract_referenced_message_id({"referencedPlatformMessageId": 2026828130733625346}),
            "2026828130733625346",
        )
        self.assertEqual(
            extract_referenced_message_id({"referencedMessageId": "123"}),
            "123",
        )

    def test_text_quote_builds_prompt_with_quoted_text_and_user_question(self):
        prompt, content = build_quote_context(
            "你觉得等于几？",
            {
                "serverId": "101",
                "senderUsername": "fantasysk",
                "parsedContent": "5+8=几",
                "localType": 1,
            },
        )

        self.assertIsNone(content)
        self.assertIn("被引用消息（文本", prompt)
        self.assertIn("5+8=几", prompt)
        self.assertIn("用户追问", prompt)
        self.assertIn("你觉得等于几？", prompt)

    def test_link_quote_includes_title_and_url_in_prompt(self):
        prompt, content = build_quote_context(
            "你觉得这是什么？",
            {
                "serverId": "102",
                "senderUsername": "gh_example",
                "parsedContent": "[链接] 热门公众号文章",
                "rawContent": "<msg><appmsg><title>热门公众号文章</title><url>https://mp.weixin.qq.com/s/abc</url><type>5</type></appmsg></msg>",
                "url": "https://mp.weixin.qq.com/s/abc",
                "localType": 49,
                "xmlType": "5",
            },
        )

        self.assertIsNone(content)
        self.assertIn("被引用消息（链接/卡片", prompt)
        self.assertIn("热门公众号文章", prompt)
        self.assertIn("https://mp.weixin.qq.com/s/abc", prompt)
        self.assertIn("你觉得这是什么？", prompt)

    def test_link_quote_includes_downloaded_webpage_content_in_prompt(self):
        prompt, content = build_quote_context(
            "你觉得这是什么？",
            {
                "serverId": "102",
                "senderUsername": "gh_example",
                "parsedContent": "[链接] 热门公众号文章",
                "rawContent": "<msg><appmsg><title>热门公众号文章</title><url>https://mp.weixin.qq.com/s/abc</url><type>5</type></appmsg></msg>",
                "localType": 49,
                "xmlType": "5",
            },
            webpage={
                "url": "https://mp.weixin.qq.com/s/abc",
                "title": "网页标题",
                "site_name": "公众号名称",
                "content": "这是下载后的网页正文。",
                "error": None,
            },
        )

        self.assertIsNone(content)
        self.assertIn("网页标题：网页标题", prompt)
        self.assertIn("来源：公众号名称", prompt)
        self.assertIn("URL：https://mp.weixin.qq.com/s/abc", prompt)
        self.assertIn("网页正文：\n这是下载后的网页正文。", prompt)
        self.assertIn("用户追问：\n你觉得这是什么？", prompt)

    def test_extract_link_url_reads_raw_xml_when_url_field_is_missing(self):
        self.assertEqual(
            extract_link_url(
                {
                    "rawContent": "<msg><appmsg><url><![CDATA[https://mp.weixin.qq.com/s/raw]]></url></appmsg></msg>",
                    "localType": 49,
                }
            ),
            "https://mp.weixin.qq.com/s/raw",
        )

    def test_image_quote_builds_openai_multimodal_content(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG\r\n\x1a\nfake")
            image_path = tmp.name
        try:
            prompt, content = build_quote_context(
                "你觉得这是什么？",
                {
                    "serverId": "103",
                    "senderUsername": "fantasysk",
                    "parsedContent": "[图片]",
                    "localType": 3,
                },
                image_path=image_path,
            )

            self.assertIn("被引用消息（图片", prompt)
            self.assertIsInstance(content, list)
            self.assertEqual(content[0]["type"], "text")
            self.assertEqual(content[0]["text"], prompt)
            self.assertEqual(content[1]["type"], "image_url")
            image_url = content[1]["image_url"]["url"]
            self.assertTrue(image_url.startswith("data:image/png;base64,"))
            self.assertEqual(
                base64.b64decode(image_url.split(",", 1)[1]),
                b"\x89PNG\r\n\x1a\nfake",
            )
        finally:
            os.remove(image_path)

    def test_session_uses_multimodal_content_when_present(self):
        context = Context()
        context.session_id = "fantasysk"
        context.query = "fallback text"
        context.message_content = [
            {"type": "text", "text": "question"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]

        session = Session.build_session_query(context)

        self.assertEqual(session[-1]["content"], context.message_content)

    def test_strip_weflow_reply_marker_before_prefix_matching(self):
        self.assertEqual(strip_weflow_reply_marker("[引用] @pika 你觉得呢？"), "@pika 你觉得呢？")
        self.assertEqual(strip_weflow_reply_marker("引用：@pika 你觉得呢？"), "@pika 你觉得呢？")

    def test_quoted_image_reuses_cached_decrypted_path_by_server_id(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake-image")
            image_path = tmp.name
        cache = {}
        try:
            cache_image_path(cache, ["8071034753819399707"], image_path)

            self.assertEqual(
                get_cached_image_path(cache, {"serverId": "8071034753819399707"}),
                image_path,
            )
        finally:
            os.remove(image_path)

    def test_quoted_image_cache_accepts_exact_referenced_id_when_http_id_differs(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake-image")
            image_path = tmp.name
        cache = {}
        try:
            cache_image_path(cache, ["8123737055266740776"], image_path)

            self.assertEqual(
                get_cached_image_path(
                    cache,
                    {"serverId": "8123737055266741000", "localType": 3},
                    fallback_ids=["8123737055266740776"],
                ),
                image_path,
            )
        finally:
            os.remove(image_path)

    def test_candidate_image_timestamps_include_weflow_local_epoch_correction(self):
        # WeFlow/DB createTime in the user's log is about +8h from the
        # Windows file mtime used by image .dat files.
        candidates = candidate_image_timestamps(
            1779932748,
            timezone_offset_seconds=-28800,
        )

        self.assertEqual(candidates[0], 1779932748)
        self.assertIn(1779903948, candidates)

    def test_candidate_image_timestamps_prioritize_corrected_time_when_it_matches_now(self):
        candidates = candidate_image_timestamps(
            1779932748,
            timezone_offset_seconds=-28800,
            now_seconds=1779903978,
        )

        self.assertEqual(candidates[0], 1779903948)


if __name__ == "__main__":
    unittest.main()
