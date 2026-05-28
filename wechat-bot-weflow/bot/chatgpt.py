import openai
import base64
import os
import time
import tempfile
import requests as http_requests
from config import conf
from utils.log import logger
from utils.serialize import normalize_media_url
from common.session import Session
from common.reply import Reply, ReplyType
from common.context import ContextType, Context


class ChatGPTBot:
    def __init__(self):
        openai.api_key = conf().get("openai_api_key")
        api_base = conf().get("openai_api_base")
        proxy = conf().get("proxy")
        if api_base:
            openai.api_base = api_base
        if proxy:
            openai.proxy = proxy
        self.name = self.__class__.__name__
        self.args = {
            "model": conf().get("model"),
            "temperature": conf().get("temperature"),
        }

    def reply(self, context: Context) -> Reply:
        query = context.query
        logger.info(f"[{self.name}] Query={query}")
        if context.type == ContextType.CREATE_IMAGE:
            return self.reply_img(query)
        else:
            session_id = context.session_id
            session = Session.build_session_query(context)
            response = self.reply_text(session)
            logger.info(f"[{self.name}] Response={response['content']}")
            if response["completion_tokens"] > 0:
                Session.save_session(
                    response["content"], session_id, response["total_tokens"]
                )
            return Reply(ReplyType.TEXT, response["content"])

    def reply_img(self, query) -> Reply:
        create_image_size = conf().get("create_image_size", "512x512")
        create_image_model = conf().get("create_image_model", "dall-e-3")
        create_image_style = conf().get("create_image_style", "vivid")
        create_image_quality = conf().get("create_image_quality", "standard")

        # 画图专用 API 配置（可选，留空则复用 openai_api_base / openai_api_key）
        image_api_base = conf().get("create_image_api_base", "")
        image_api_key = conf().get("create_image_api_key", "")

        try:
            if image_api_base:
                # 使用独立画图 API：直接发 HTTP 请求，绕开 openai SDK 兼容性问题
                return self._reply_img_via_requests(
                    query, image_api_base, image_api_key or openai.api_key,
                    create_image_model, create_image_size, create_image_style,
                    create_image_quality
                )
            else:
                # 使用 openai SDK（复用 openai_api_base）
                response = openai.Image.create(
                    prompt=query, model=create_image_model, n=1,
                    size=create_image_size, style=create_image_style,
                    quality=create_image_quality
                )
                return self._parse_image_response(response)
        except Exception as e:
            logger.error(f"[{self.name}] Create image failed: {e}")
            return Reply(ReplyType.TEXT, f"Image created failed: {e}")

    def _reply_img_via_requests(self, query, api_base, api_key, model, size, style, quality):
        """直接通过 HTTP 请求调用画图 API，兼容 Grok 等非 OpenAI 端点"""
        url = f"{api_base.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": query,
            "n": 1,
            "size": size,
            "style": style,
            "quality": quality,
        }
        logger.info(f"[{self.name}] Image API request to {url}, model={model}")
        resp = http_requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        image_data = data["data"][0]
        return self._handle_image_data(image_data)

    def _parse_image_response(self, response):
        """解析 openai SDK 返回的图片响应"""
        image_data = response["data"][0]
        return self._handle_image_data(image_data)

    def _handle_image_data(self, image_data):
        """处理图片数据，兼容 url 和 b64_json 两种格式"""
        if image_data.get("url"):
            raw_image_url = image_data["url"]
            image_url = normalize_media_url(raw_image_url, self._get_image_api_base())
            if image_url != raw_image_url:
                logger.info(f"[{self.name}] Normalized image URL from {raw_image_url} to {image_url}")
            else:
                logger.info(f"[{self.name}] Image URL={image_url}")
            return Reply(ReplyType.IMAGE, image_url)
        elif image_data.get("b64_json"):
            b64_data = image_data["b64_json"]
            img_bytes = base64.b64decode(b64_data)
            tmp_dir = tempfile.gettempdir()
            img_path = os.path.join(tmp_dir, f"wechat_bot_img_{int(time.time())}.png")
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            logger.info(f"[{self.name}] Image saved to {img_path}")
            return Reply(ReplyType.IMAGE, img_path)
        else:
            logger.warning(f"[{self.name}] Image response has no url or b64_json")
            return Reply(ReplyType.TEXT, "Image generation returned no image data")

    def reply_text(self, session):
        response = None
        try:
            response = openai.ChatCompletion.create(
                messages=session,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                **self.args,
            )
            usage = response.get('usage') or {}
            choice = response.choices[0] if response.choices else {}
            return {
                "total_tokens": usage.get('total_tokens'),
                "completion_tokens": usage.get('completion_tokens'),
                "content": choice.get('message', {}).get('content'),
            }
        except Exception as e:
            result = {"completion_tokens": 0, "content": "Please ask me again", "exception": e}
            if isinstance(e, openai.error.RateLimitError):
                logger.warn(f"[{self.name}] RateLimitError: {e}")
                result["content"] = "Ask too frequently, please try again in 20s"
            elif isinstance(e, openai.error.APIConnectionError):
                logger.warn(f"[{self.name}] APIConnectionError: {e}")
                result[
                    "content"
                ] = "I cannot connect the server, please check the network and try again"
            elif isinstance(e, openai.error.Timeout):
                logger.warn(f"[{self.name}] Timeout: {e}")
                result["content"] = "I didn't receive your message, please try again"
            elif isinstance(e, openai.error.APIError):
                logger.warn(f"[{self.name}] APIError: {e}")
            else:
                logger.exception(f"[{self.name}] Exception: {e}, Response: {response}")
        return result

    def _get_image_api_base(self):
        return conf().get("create_image_api_base", "") or conf().get("openai_api_base", "")
