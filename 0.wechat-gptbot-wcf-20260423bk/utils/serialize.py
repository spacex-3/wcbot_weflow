import os
import time
import json
import re
import requests
from urllib.parse import urljoin, urlparse
from config import conf
from channel.message import Message
from utils.log import logger
from utils.const import MessageType
from utils.gen import gen_id
from lxml import etree


def serialize_img(image_url: str) -> str:
    return serialize_file(image_url, "png")


def serialize_video(video_url: str) -> str:
    return serialize_file(video_url, "mp4")


def _is_windows_abs_path(path: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", path or ""))


def _get_media_api_base(api_base: str = "") -> str:
    if api_base:
        return api_base
    config = conf() or {}
    return config.get("create_image_api_base", "") or config.get("openai_api_base", "")


def _looks_like_root_relative_url(path: str) -> bool:
    if not isinstance(path, str):
        return False
    if path.startswith("//"):
        return True
    if not path.startswith("/"):
        return False
    return any(
        (
            "?" in path,
            "#" in path,
            path.startswith("/p/"),
            path.startswith("/images/"),
            path.startswith("/img/"),
            path.startswith("/media/"),
        )
    )


def normalize_media_url(file_url: str, api_base: str = "") -> str:
    if not isinstance(file_url, str):
        return file_url
    file_url = file_url.strip()
    if not file_url or file_url.startswith("base64://"):
        return file_url
    if os.path.exists(file_url) or _is_windows_abs_path(file_url):
        return file_url

    parsed = urlparse(file_url)
    if parsed.scheme in ("http", "https"):
        return file_url

    if file_url.startswith(("./", "../")):
        return file_url

    base_url = _get_media_api_base(api_base)
    if base_url and _looks_like_root_relative_url(file_url):
        return urljoin(f"{base_url.rstrip('/')}/", file_url)
    return file_url


def should_download_remote_media(file_ref: str, api_base: str = "") -> bool:
    normalized = normalize_media_url(file_ref, api_base)
    if not isinstance(normalized, str) or not normalized:
        return False
    if normalized.startswith("base64://"):
        return False
    if os.path.exists(normalized) or _is_windows_abs_path(normalized):
        return False
    parsed = urlparse(normalized)
    return parsed.scheme in ("http", "https")


def serialize_file(file_url: str, suffix: str) -> str:
    try:
        normalized_url = normalize_media_url(file_url)
        if not should_download_remote_media(normalized_url):
            return normalized_url

        # download file
        path = os.path.abspath("./assets")
        os.makedirs(path, exist_ok=True)
        file_name = int(time.time() * 1000)
        file_path = os.path.join(path, f"{file_name}.{suffix}")
        response = requests.get(normalized_url, stream=True, timeout=120)
        response.raise_for_status()  # Raise exception if invalid response

        with open(file_path, "wb+") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
            f.close()
        return os.path.abspath(file_path)
    except Exception as e:
        logger.error(f"[Download File Error]: {e}")


def serialize_text(text: str, msg: Message) -> str:
    msg_type = MessageType.AT_MSG.value if msg.is_group else MessageType.TXT_MSG.value
    msg = {
        "id": gen_id(),
        "type": msg_type,
        "roomid": msg.room_id or "null",
        "wxid": msg.sender_id or "null",
        "content": text,
        "nickname": msg.sender_name or "null",
        "ext": "null",
    }
    return json.dumps(msg)

def xml_to_dict(xml, from_str=False):
    if from_str:
        xml = etree.fromstring(xml)
    result = {}
    for attr, value in xml.attrib.items():
        result[attr] = value
    children = list(xml)
    if children:
        result[xml.tag] = {}
        for child in children:
            result[xml.tag].update(xml_to_dict(child))
    else:
        result[xml.tag] = xml.text
    return result

def get_value(obj, key, def_value=None):
    keys = f'{key}'.split('.')
    result = obj
    for k in keys:
        if result is None:
            return None
        if isinstance(result, (str, int)):
            return def_value
        if isinstance(result, dict):
            result = result.get(k, def_value)
        elif isinstance(result, (list, tuple)):
            try:
                result = result[int(k)]
            except Exception:
                result = def_value
    return result
