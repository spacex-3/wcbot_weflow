import unittest

from channel.weflow_webpage import fetch_webpage_text


class FakeResponse:
    def __init__(self, text, status_code=200, headers=None, url="https://mp.weixin.qq.com/s/abc"):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.url = url
        self.encoding = None
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class WeFlowWebpageTest(unittest.TestCase):
    def test_fetch_wechat_article_extracts_title_account_and_content(self):
        html = """
        <html>
          <head><title>fallback title</title></head>
          <body>
            <h1 id="activity-name">热门微信公众号文章</h1>
            <span id="js_name">公众号名称</span>
            <div id="js_content">
              <p>第一段正文。</p>
              <script>console.log("hidden")</script>
              <p>第二段正文。</p>
            </div>
          </body>
        </html>
        """

        result = fetch_webpage_text(
            "https://mp.weixin.qq.com/s/abc",
            request_get=lambda *args, **kwargs: FakeResponse(html),
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["title"], "热门微信公众号文章")
        self.assertEqual(result["site_name"], "公众号名称")
        self.assertIn("第一段正文。", result["content"])
        self.assertIn("第二段正文。", result["content"])
        self.assertNotIn("console.log", result["content"])

    def test_fetch_regular_page_extracts_article_text_and_truncates(self):
        html = """
        <html>
          <head><meta property="og:title" content="普通网页标题"></head>
          <body><article><p>abcdef</p><p>ghijkl</p></article></body>
        </html>
        """

        result = fetch_webpage_text(
            "https://example.com/post",
            max_chars=8,
            request_get=lambda *args, **kwargs: FakeResponse(html, url="https://example.com/post"),
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["title"], "普通网页标题")
        self.assertEqual(result["content"], "abcdefgh...")

    def test_fetch_regular_page_keeps_media_placeholders_in_reading_order(self):
        html = """
        <html>
          <body>
            <article>
              <p>第一段。</p>
              <figure>
                <img alt="善款明细截图" src="a.jpg">
                <figcaption>截图说明。</figcaption>
              </figure>
              <p>第二段。</p>
              <video src="clip.mp4"></video>
              <p>第三段。</p>
            </article>
          </body>
        </html>
        """

        result = fetch_webpage_text(
            "https://example.com/post",
            request_get=lambda *args, **kwargs: FakeResponse(html, url="https://example.com/post"),
        )

        self.assertIsNone(result["error"])
        self.assertEqual(
            result["content"],
            "第一段。\n[图片暂不读取：善款明细截图]\n截图说明。\n第二段。\n[视频暂不读取]\n第三段。",
        )

    def test_fetch_collapses_consecutive_images_and_filters_common_ui_noise(self):
        html = """
        <html>
          <body>
            <article>
              <p>明细如下。</p>
              <p>滑动查看</p>
              <img src="one.jpg">
              <img src="two.jpg">
              <picture><source srcset="three.webp"><img src="three.jpg"></picture>
              <p>滑动查看</p>
              <p>赞</p>
              <p>在看</p>
              <p>剩余善款为64589.42元。</p>
            </article>
          </body>
        </html>
        """

        result = fetch_webpage_text(
            "https://example.com/post",
            request_get=lambda *args, **kwargs: FakeResponse(html, url="https://example.com/post"),
        )

        self.assertIsNone(result["error"])
        self.assertEqual(
            result["content"],
            "明细如下。\n[连续图片暂不读取 x3]\n剩余善款为64589.42元。",
        )

    def test_fetch_rejects_non_http_url_without_request(self):
        called = []

        result = fetch_webpage_text(
            "file:///etc/passwd",
            request_get=lambda *args, **kwargs: called.append(True),
        )

        self.assertEqual(result["error"], "unsupported url scheme")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
