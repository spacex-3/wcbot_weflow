import base64
import html
import mimetypes
import os
import re
import time
from typing import Any


CHATLAB_REPLY_TYPE = 25


def extract_referenced_message_id(msg_data: dict[str, Any]) -> str | None:
    for key in (
        "referencedPlatformMessageId",
        "referencedMessageId",
        "referencedMsgId",
        "referencedServerId",
    ):
        value = msg_data.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def is_weflow_reply_message(weflow_type: Any, msg_data: dict[str, Any]) -> bool:
    try:
        if int(weflow_type) == CHATLAB_REPLY_TYPE:
            return True
    except (TypeError, ValueError):
        pass
    return extract_referenced_message_id(msg_data) is not None


def strip_weflow_reply_marker(text: str | None) -> str:
    value = (text or "").strip()
    while True:
        cleaned = re.sub(r"^\s*(?:\[引用\]|\[引用消息\]|引用[:：])\s*", "", value).strip()
        if cleaned == value:
            return cleaned
        value = cleaned


def cache_image_path(
    cache: dict[str, str],
    message_ids: list[Any],
    image_path: str | None,
    max_items: int = 200,
) -> None:
    if not image_path or not os.path.isfile(image_path):
        return

    for message_id in message_ids:
        normalized = str(message_id or "").strip()
        if not normalized or normalized == "0":
            continue
        cache[normalized] = image_path

    while len(cache) > max_items:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)


def get_cached_image_path(
    cache: dict[str, str],
    referenced_message: dict[str, Any],
    fallback_ids: list[Any] | None = None,
) -> str | None:
    message_ids = []
    for key in (
        "serverId",
        "platformMessageId",
        "referencedPlatformMessageId",
        "messageId",
        "id",
    ):
        message_id = str(referenced_message.get(key) or "").strip()
        if message_id:
            message_ids.append(message_id)

    for fallback_id in fallback_ids or []:
        message_id = str(fallback_id or "").strip()
        if message_id:
            message_ids.append(message_id)

    seen = set()
    for message_id in message_ids:
        if message_id in seen:
            continue
        seen.add(message_id)
        image_path = cache.get(message_id)
        if image_path and os.path.isfile(image_path):
            return image_path
        if image_path:
            cache.pop(message_id, None)
    return None


def candidate_image_timestamps(
    create_time: int,
    timezone_offset_seconds: int | None = None,
    now_seconds: int | None = None,
) -> list[int]:
    if create_time <= 0:
        return []

    if timezone_offset_seconds is None:
        timezone_offset_seconds = time.timezone

    candidates = [
        create_time,
        create_time + timezone_offset_seconds,
        create_time - timezone_offset_seconds,
    ]
    result = []
    for candidate in candidates:
        if candidate <= 0 or candidate in result:
            continue
        result.append(candidate)

    if now_seconds is not None:
        result.sort(key=lambda candidate: abs(candidate - now_seconds))
    return result


def build_quote_context(
    user_query: str,
    referenced_message: dict[str, Any] | None,
    image_path: str | None = None,
    webpage: dict[str, Any] | None = None,
) -> tuple[str, Any | None]:
    message = referenced_message or {}
    kind = _infer_referenced_kind(message)
    sender = _pick_first(message, "senderDisplayName", "senderName", "senderUsername", "sender")
    sender_hint = f"，发送者：{sender}" if sender else ""

    if kind == "image":
        prompt = (
            f"你正在回复一条微信引用消息。请同时参考被引用图片和用户追问，优先回答用户追问。\n\n"
            f"被引用消息（图片{sender_hint}）：\n"
            f"{_clean_text(message.get('parsedContent')) or '[图片]'}\n\n"
            f"用户追问：\n{(user_query or '').strip()}"
        )
        image_content = _build_image_content(prompt, image_path)
        return prompt, image_content

    if kind == "link":
        title = _extract_link_title(message)
        url = extract_link_url(message)
        summary = _clean_text(message.get("parsedContent"))
        page = webpage or {}
        page_title = _clean_text(page.get("title"))
        page_site_name = _clean_text(page.get("site_name"))
        page_content = _clean_text(page.get("content"))
        page_url = _clean_text(page.get("url")) or url
        page_error = _clean_text(page.get("error"))
        parts = []
        if title:
            parts.append(f"标题：{title}")
        if page_title and page_title != title:
            parts.append(f"网页标题：{page_title}")
        if page_site_name:
            parts.append(f"来源：{page_site_name}")
        if page_url:
            parts.append(f"URL：{page_url}")
        if summary and summary != title:
            parts.append(f"内容：{summary}")
        if page_content:
            parts.append(f"网页正文：\n{page_content}")
        elif page_error:
            parts.append(f"网页正文：下载失败（{page_error}）")
        if not parts:
            parts.append("[链接/卡片]")

        prompt = (
            f"你正在回复一条微信引用消息。请同时参考被引用链接/卡片和用户追问，优先回答用户追问。\n\n"
            f"被引用消息（链接/卡片{sender_hint}）：\n"
            f"{chr(10).join(parts)}\n\n"
            f"用户追问：\n{(user_query or '').strip()}"
        )
        return prompt, None

    quoted_text = _clean_text(message.get("parsedContent")) or _clean_text(message.get("rawContent")) or "[消息]"
    prompt = (
        f"你正在回复一条微信引用消息。请同时参考被引用文本和用户追问，优先回答用户追问。\n\n"
        f"被引用消息（文本{sender_hint}）：\n"
        f"{quoted_text}\n\n"
        f"用户追问：\n{(user_query or '').strip()}"
    )
    return prompt, None


def _infer_referenced_kind(message: dict[str, Any]) -> str:
    local_type = _to_int(message.get("localType", message.get("type")))
    xml_type = str(message.get("xmlType") or "").strip()
    parsed_content = _clean_text(message.get("parsedContent"))

    if local_type == 3 or parsed_content in ("[图片]", "[image]", "图片"):
        return "image"
    if extract_link_url(message):
        return "link"
    if local_type == 49 and xml_type in ("5", "49", ""):
        return "link"
    return "text"


def is_referenced_link_message(message: dict[str, Any]) -> bool:
    return _infer_referenced_kind(message) == "link"


def extract_link_url(message: dict[str, Any]) -> str:
    return _pick_first(message, "url", "linkUrl") or _extract_xml_value(
        str(message.get("rawContent") or message.get("content") or ""),
        "url",
    )


def _build_image_content(prompt: str, image_path: str | None) -> list[dict[str, Any]] | None:
    if not image_path or not os.path.isfile(image_path):
        return None

    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")

    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
    ]


def _extract_link_title(message: dict[str, Any]) -> str:
    raw_content = str(message.get("rawContent") or "")
    title = _extract_xml_value(raw_content, "title")
    if title:
        return title

    parsed_content = _clean_text(message.get("parsedContent"))
    return re.sub(r"^\[链接\]\s*", "", parsed_content).strip()


def _extract_xml_value(xml: str, tag_name: str) -> str:
    if not xml:
        return ""
    normalized = html.unescape(xml)
    match = re.search(fr"<{tag_name}>([\s\S]*?)</{tag_name}>", normalized, re.IGNORECASE)
    if not match:
        return ""
    return (
        match.group(1)
        .replace("<![CDATA[", "")
        .replace("]]>", "")
        .strip()
    )


def _pick_first(message: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = message.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return strip_weflow_reply_marker(text)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
