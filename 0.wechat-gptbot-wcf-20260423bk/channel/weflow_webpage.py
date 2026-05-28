import html
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 MicroMessenger"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

MEDIA_PLACEHOLDERS = {
    "img": "图片",
    "image": "图片",
    "video": "视频",
    "audio": "音频",
    "iframe": "嵌入内容",
}

COMMON_UI_NOISE_LINES = {
    "滑动查看",
    "赞",
    "在看",
    "视频",
    "小程序",
    "去验证",
    "：",
    "，",
    "。",
}


def fetch_webpage_text(
    url: str,
    timeout: int = 10,
    max_chars: int = 12000,
    request_get=requests.get,
) -> dict[str, Any]:
    normalized_url = html.unescape(str(url or "").strip())
    result = {
        "url": normalized_url,
        "title": "",
        "site_name": "",
        "content": "",
        "error": None,
    }
    if not _is_http_url(normalized_url):
        result["error"] = "unsupported url scheme"
        return result

    try:
        response = request_get(
            normalized_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as e:
        result["error"] = f"download failed: {e}"
        return result

    content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
    if content_type and not any(part in content_type for part in ("text/", "html", "xml")):
        result["error"] = f"unsupported content type: {content_type}"
        return result

    if not getattr(response, "encoding", None):
        response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"

    soup = _parse_html(response.text)
    _remove_noise(soup)

    title = _first_text(
        soup.select_one("#activity-name"),
        soup.select_one("meta[property='og:title']"),
        soup.select_one("meta[name='twitter:title']"),
        soup.select_one("h1"),
        soup.title,
    )
    site_name = _first_text(
        soup.select_one("#js_name"),
        soup.select_one("meta[property='og:site_name']"),
    )

    content_node = (
        soup.select_one("#js_content")
        or soup.select_one("article")
        or soup.select_one("main")
        or soup.select_one("[role='main']")
        or soup.body
    )
    content = _extract_readable_text(content_node)
    if not content:
        description = _first_text(
            soup.select_one("meta[name='description']"),
            soup.select_one("meta[property='og:description']"),
        )
        content = description

    result["url"] = str(getattr(response, "url", None) or normalized_url)
    result["title"] = title
    result["site_name"] = site_name
    result["content"] = _truncate(content, max_chars)
    if _is_wechat_captcha_page(result["url"], result["content"]):
        result["content"] = ""
        result["error"] = "wechat captcha page"
        return result
    if not result["content"]:
        result["error"] = "empty webpage content"
    return result


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _parse_html(raw_html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(raw_html or "", "lxml")
    except Exception:
        return BeautifulSoup(raw_html or "", "html.parser")


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()


def _first_text(*nodes) -> str:
    for node in nodes:
        text = _node_text(node)
        if text:
            return text
    return ""


def _node_text(node) -> str:
    if node is None:
        return ""
    if getattr(node, "name", "") == "meta":
        text = node.get("content") or ""
    else:
        text = node.get_text("\n", strip=True)
    return _clean_text(text)


def _extract_readable_text(node) -> str:
    if node is None:
        return ""
    if not _has_media_descendant(node):
        return _filter_common_ui_noise(_node_text(node))

    lines = []

    def append_text(value: str) -> None:
        text = _clean_text(value)
        if not text:
            return
        for line in text.splitlines():
            normalized = line.strip()
            if normalized and not _is_common_ui_noise(normalized):
                lines.append(normalized)

    def walk(current) -> None:
        for child in list(getattr(current, "children", []) or []):
            if isinstance(child, NavigableString):
                append_text(str(child))
                continue

            tag_name = str(getattr(child, "name", "") or "").lower()
            if not tag_name:
                continue
            if tag_name in ("source", "track"):
                if _has_media_descendant(child):
                    walk(child)
                continue
            if tag_name in MEDIA_PLACEHOLDERS:
                placeholder = _media_placeholder(child, MEDIA_PLACEHOLDERS[tag_name])
                if placeholder:
                    lines.append(placeholder)
                continue
            if _has_media_descendant(child):
                walk(child)
                continue
            append_text(_node_text(child))

    walk(node)
    if not lines:
        return _filter_common_ui_noise(_node_text(node))
    return "\n".join(_collapse_media_placeholders(lines))


def _has_media_descendant(node) -> bool:
    try:
        return node.find(list(MEDIA_PLACEHOLDERS.keys())) is not None
    except Exception:
        return False


def _media_placeholder(node, kind: str) -> str:
    if kind == "图片" and _is_tiny_or_hidden_image(node):
        return ""

    label = _clean_text(
        node.get("alt")
        or node.get("title")
        or node.get("aria-label")
        or ""
    ).replace("\n", " ")
    if label:
        return f"[{kind}暂不读取：{label[:80]}]"
    return f"[{kind}暂不读取]"


def _is_tiny_or_hidden_image(node) -> bool:
    style = str(node.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
        return True
    try:
        width = int(str(node.get("width") or "0").strip("px"))
        height = int(str(node.get("height") or "0").strip("px"))
        return 0 < width <= 2 and 0 < height <= 2
    except (TypeError, ValueError):
        return False


def _collapse_media_placeholders(lines: list[str]) -> list[str]:
    collapsed = []
    pending_kind = None
    pending_lines = []

    def flush_pending() -> None:
        nonlocal pending_kind, pending_lines
        if not pending_lines:
            return
        if len(pending_lines) == 1:
            collapsed.append(pending_lines[0])
        else:
            collapsed.append(f"[连续{pending_kind}暂不读取 x{len(pending_lines)}]")
        pending_kind = None
        pending_lines = []

    for line in lines:
        media_kind = _placeholder_kind(line)
        if not media_kind:
            flush_pending()
            collapsed.append(line)
            continue
        if pending_kind and pending_kind != media_kind:
            flush_pending()
        pending_kind = media_kind
        pending_lines.append(line)

    flush_pending()
    return collapsed


def _placeholder_kind(line: str) -> str:
    for kind in MEDIA_PLACEHOLDERS.values():
        if line.startswith(f"[{kind}暂不读取"):
            return kind
    return ""


def _filter_common_ui_noise(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        normalized = line.strip()
        if normalized and not _is_common_ui_noise(normalized):
            lines.append(normalized)
    return "\n".join(lines)


def _is_common_ui_noise(line: str) -> bool:
    normalized = line.strip()
    return (
        normalized in COMMON_UI_NOISE_LINES
        or "轻点两下取消" in normalized
    )


def _clean_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    lines = [line.strip() for line in text.splitlines()]
    kept = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank and kept:
                kept.append("")
            previous_blank = True
            continue
        kept.append(line)
        previous_blank = False
    return "\n".join(kept).strip()


def _truncate(text: str, max_chars: int) -> str:
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = 12000
    if limit <= 0 or len(text) <= limit:
        return text
    compact_text = text.replace("\n", "")
    return compact_text[:limit].rstrip() + "..."


def _is_wechat_captcha_page(url: str, content: str) -> bool:
    text = str(content or "")
    return (
        "wappoc_appmsgcaptcha" in str(url or "")
        or ("环境异常" in text and "完成验证后即可继续访问" in text)
    )
