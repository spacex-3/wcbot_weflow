import html
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 MicroMessenger"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_webpage_text(
    url: str,
    timeout: int = 10,
    max_chars: int = 12000,
    request_get=requests.get,
) -> dict[str, Any]:
    normalized_url = str(url or "").strip()
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
    content = _node_text(content_node)
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
