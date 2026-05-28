import json
import warnings
import websocket
import requests
import time
from datetime import datetime
from utils.log import logger
import os
import re
import threading
import queue
import base64
from bot.bot import Bot
from common.singleton import singleton
from config import conf
from utils.check import check_prefix, is_wx_account
from common.reply import ReplyType, Reply
from channel.message import Message
from utils.const import MessageType
from utils.serialize import serialize_video, serialize_img, should_download_remote_media
from plugins.manager import PluginManager
from common.context import ContextType, Context
from plugins.event import EventType, Event
from channel.channel import Channel
from channel.wechat_sender import WeChatSender
from channel.weflow_quote import (
    build_quote_context,
    cache_image_path,
    candidate_image_timestamps,
    extract_link_url,
    extract_referenced_message_id,
    get_cached_image_path,
    is_referenced_link_message,
    is_weflow_reply_message,
    strip_weflow_reply_marker,
)
from channel.weflow_webpage import fetch_webpage_text
from utils.file_cleanup import cleanup_old_files


@singleton
class WeFlowChannel(Channel):
    def __init__(self):
        warnings.filterwarnings("ignore")
        os.environ["TF_CPP_MIN_LOG_LEVEL"] = "1"

        self._http_url = conf().get("weflow_http_url", "http://127.0.0.1:5031")
        self._ws_url = conf().get("weflow_ws_url", "ws://127.0.0.1:5032")

        self.personal_info = self.get_personal_info()
        self.contacts = self.update_contacts()
        self.sender = WeChatSender()
        self.recent_image_paths = {}
        self.cleanup_assets()

        # Mapping WeFlow message types to wrest message types
        # 1: Text, 3: Image, 34: Voice, 43: Video, 47: Emoji, 49: AppMsg (Link/File), 10000: System
        self.type_mapping = {
            1: MessageType.RECV_TXT_MSG,
            3: MessageType.RECV_PIC_MSG,
            34: 34, # Voice - currently not perfectly mapped in wrest but we can pass it
            43: 43, # Video
            47: 47, # Emoji
            49: MessageType.RECV_FILE_MSG, # Often files or links
            25: MessageType.RECV_CITE_TXT, # ChatLab reply / quoted message
        }

        # UI Automation needs strict synchronous execution
        self.send_queue = queue.Queue()
        self.send_thread = threading.Thread(target=self._send_worker, daemon=True)
        self.send_thread.start()

    def _send_worker(self):
        """Worker thread to process all outgoing messages sequentially."""
        while True:
            try:
                task = self.send_queue.get()
                if task is None:
                    break

                reply, msg, target_name, wx_id = task
                logger.debug(f"[WeFlowChannel] Worker processing message for {target_name}")

                if reply.type == ReplyType.IMAGE or reply.type == ReplyType.VIDEO or reply.type == ReplyType.OFILE:
                    path = reply.content
                    temp_file_path = None

                    if reply.type == ReplyType.VIDEO and '://' in path and '.mp4' not in path:
                        path = serialize_video(path)
                        temp_file_path = path
                    elif reply.type == ReplyType.IMAGE:
                        if should_download_remote_media(path):
                            # Handle HTTP image urls
                            path = serialize_img(path)
                            temp_file_path = path
                        elif path.startswith('base64://') or (len(path) > 100 and not os.path.isfile(path) and not path.startswith('http')):
                            # Handle base64 image strings
                            try:
                                b64_str = path.replace('base64://', '')
                                file_name = int(time.time() * 1000)
                                save_path = os.path.abspath(f"./assets/{file_name}.png")
                                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                                with open(save_path, "wb") as f:
                                    f.write(base64.b64decode(b64_str))
                                path = save_path
                                temp_file_path = path
                            except Exception as e:
                                logger.error(f"[WeFlowChannel] Failed to decode base64 image: {e}")

                    self.sender.send_file(target_name, path)

                    # Clean up the temporary file if we created one
                    if temp_file_path and os.path.exists(temp_file_path):
                        # Give WeChat a moment to finish reading the file from clipboard before deleting
                        time.sleep(1.0)
                        try:
                            os.remove(temp_file_path)
                            logger.info(f"[WeFlowChannel] Deleted temporary file: {temp_file_path}")
                        except Exception as e:
                            logger.warning(f"[WeFlowChannel] Could not delete temp file {temp_file_path}: {e}")
                else:
                    text = reply.content
                    if msg.room_id and msg.sender_name:
                        self.sender.send_at_message(target_name, msg.sender_name, text)
                    else:
                        self.sender.send_message(target_name, text)

                # Small delay to let WeChat UI recover after sending before jumping to the next
                time.sleep(0.5)
                self.send_queue.task_done()
            except Exception as e:
                logger.error(f"[WeFlow Send Worker Error] {e}")

    def startup(self):
        logger.info("Connecting to WeFlow WebSocket...")
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            f"{self._ws_url}/ws",
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        self.ws.run_forever()

    def on_message(self, ws, message):
        try:
            raw_msg = json.loads(message)
            if raw_msg.get('type') == 'new_message':
                logger.info(f"[WeFlow RAW] {raw_msg}")
                # The payload looks like:
                # {"type":"new_message","sessionId":"fantasysk","message":{"sender":"fantasysk","timestamp":1772492051,"type":0,"content":"你好呢","platformMessageId":"8587347484366484879"},"timestamp":1772491947325}
                msg_data = raw_msg.get('message', {})
                session_id = raw_msg.get('sessionId', '')
                self.process_weflow_msg(msg_data, session_id)
        except Exception as e:
            logger.error(f"[WeFlowChannel] Error parsing message: {e}")

    def process_weflow_msg(self, msg_data, session_id):
        # WeFlow format: {"sender":"fantasysk","timestamp":1772492051,"type":0,"content":"你好呢"}

        sdid = msg_data.get('sender') # the actual person who sent it
        is_group = '@chatroom' in session_id
        rmid = session_id if is_group else ''

        weflow_type = msg_data.get('type')  # 0 seems to be text here
        content = msg_data.get('content', '')
        ts = msg_data.get('timestamp', int(time.time()))
        referenced_message_id = extract_referenced_message_id(msg_data)

        # Adjusting type mapping based on new observation (type: 0 for text)
        wrest_type = MessageType.RECV_TXT_MSG if weflow_type == 0 else self.type_mapping.get(weflow_type, weflow_type)
        if is_weflow_reply_message(weflow_type, msg_data):
            wrest_type = MessageType.RECV_CITE_TXT

        # WeFlow sometimes sends images as text type '0' with content '[图片]'
        if wrest_type == MessageType.RECV_TXT_MSG and content == "[图片]":
            wrest_type = MessageType.RECV_PIC_MSG

        msg_wxid = rmid if is_group else sdid

        payload_sender_name = (
            msg_data.get('senderName')
            or msg_data.get('senderDisplayName')
            or msg_data.get('displayName')
            or msg_data.get('accountName')
        )
        sender_name = payload_sender_name or (
            self.contacts.get(sdid, {}).get('name', sdid) if not rmid else self.get_group_member_name(rmid, sdid)
        )

        bot_wxid = conf().get("wechat_bot_wxid", "wxid_ocksk3cjcq5j22")
        bot_name = conf().get("wechat_bot_name", "pika")

        is_self_msg = (sdid == bot_wxid or sdid == self.personal_info.get('wx_id') or sender_name == bot_name)

        mapped_msg = {
            'wxid': msg_wxid,
            'id1': sdid,
            'id2': '',
            'sender_name': sender_name,
            'group_name': self.contacts.get(rmid, {}).get('name', '') if rmid else '',
            'time': datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            'type': wrest_type,
            'content': content,
            'is_self': is_self_msg,
            'platformMessageId': msg_data.get('platformMessageId'),
            'weflow_type': weflow_type,
        }
        if referenced_message_id:
            mapped_msg['refermsg'] = {
                'svrid': referenced_message_id,
                'content': '',
                'type': '',
            }

        if is_self_msg:
            logger.info(f"[WeFlowChannel] Ignoring self-sent message from {sender_name} / {sdid}")
            return

        if '<msg>' in content and '<appmsg' in content:
            if wrest_type == MessageType.RECV_FILE_MSG or wrest_type == MessageType.RECV_PIC_MSG:
                pass
            if "titile" in content or "title" in content:
                 pass

        if wrest_type == MessageType.RECV_PIC_MSG:
            try:
                # Use system clock (not WeFlow timestamp) because .dat file mtime
                # follows the Windows system clock, which can differ by ~2 minutes
                scan_ts = time.time()
                logger.info(f"[WeFlowChannel] Image message received, will scan dat files around system time {scan_ts:.0f}")
                # Decrypt image locally from WeChat .dat files
                image_path = self._decrypt_image_by_timestamp(scan_ts)
                if image_path:
                    mapped_msg['extra'] = image_path
                    cache_image_path(
                        self.recent_image_paths,
                        [msg_data.get('platformMessageId')],
                        image_path,
                    )
                    logger.info(f"[WeFlowChannel] Decrypted image: {image_path}")
                else:
                    logger.error(f"[WeFlowChannel] Could not find/decrypt image for scan_ts {scan_ts:.0f}")
            except Exception as e:
                logger.error(f"[WeFlowChannel] Error decrypting image: {e}")

        self.handle_message(mapped_msg)

    def get_group_member_name(self, rmid, sdid):
        """Fetch group member name"""
        try:
            res = requests.get(f"{self._http_url}/api/v1/contacts")
            # This is a simplification. WeFlow doesn't easily expose group alias in a simple endpoint without scraping or caching.
            # We'll rely on the default contacts list if possible, or fallback to sdid.
            return self.contacts.get(sdid, {}).get('name', sdid)
        except:
            return sdid

    def handle_message(self, raw_msg):
        if raw_msg.get('is_self'):
            logger.info("message sent by self, ignore")
            return

        msg = Message(raw_msg, self.personal_info, self)
        logger.info(f"message received: {msg}")
        e = PluginManager().emit(
            Event(EventType.DID_RECEIVE_MESSAGE, {"channel": self, "message": msg})
        )
        if e.is_bypass:
            return self.send(e.reply, e.message)

        if msg.type not in [MessageType.RECV_TXT_MSG, MessageType.RECV_CITE_TXT, MessageType.RECV_PIC_MSG]:
            return
        if not isinstance(msg.content, str):
            return

        # If it's a picture and not fully consumed by a plugin, do not send it to ChatGPT
        if msg.type == MessageType.RECV_PIC_MSG:
            return

        if e.message.is_group:
            self.handle_group(e.message)
        else:
            self.handle_single(e.message)

    def handle_group(self, msg: Message):
        session_independent = conf().get("chat_group_session_independent")
        context = Context()
        context.session_id = msg.sender_id if session_independent else msg.room_id
        if msg.is_at:
            query = strip_weflow_reply_marker(msg.content)
            query = query.replace(f"@{msg.receiver_name}", "", 1).strip()
            # Handle hidden zwsp (zero-width spaces) added by some clients
            query = query.replace("\u2005", "").strip()
            context.query = query
            create_image_prefix = conf().get("create_image_prefix")
            match_prefix = check_prefix(query, create_image_prefix)
            if match_prefix:
                context.type = ContextType.CREATE_IMAGE
            self.attach_quote_context(msg, context)
            self.handle_reply(msg, context)

    def handle_single(self, msg: Message):
        if not is_wx_account(msg.sender_id):
            logger.info("message sent by public/subscription account, ignore")
            return
        context = Context()
        context.session_id = msg.sender_id
        query = strip_weflow_reply_marker(msg.content)
        single_chat_prefix = conf().get("single_chat_prefix")
        if single_chat_prefix is not None and len(single_chat_prefix) > 0:
            match_chat_prefix = check_prefix(query, single_chat_prefix)
            if match_chat_prefix is not None:
                query = query.replace(match_chat_prefix, "", 1).strip()
            else:
                logger.info("your message is not start with single_chat_prefix, ignore")
                return
        context.query = query
        create_image_prefix = conf().get("create_image_prefix")
        match_image_prefix = check_prefix(query, create_image_prefix)
        if match_image_prefix:
            context.type = ContextType.CREATE_IMAGE
        self.attach_quote_context(msg, context)
        self.handle_reply(msg, context)

    def attach_quote_context(self, msg: Message, context: Context):
        if context.type != ContextType.CREATE_TEXT or not msg.refermsg:
            return

        referenced_message_id = str(msg.refermsg.get('svrid') or '').strip()
        if not referenced_message_id:
            return

        referenced_message = self.fetch_referenced_message(msg, referenced_message_id)
        if not referenced_message:
            referenced_message = {
                'serverId': referenced_message_id,
                'parsedContent': f'[未找到被引用消息 serverId={referenced_message_id}]',
                'localType': 1,
            }

        image_path = None
        if self.is_referenced_image_message(referenced_message):
            image_path = self.decrypt_referenced_image(referenced_message, referenced_message_id)
            if not image_path:
                logger.warning(f"[WeFlowChannel] Quoted image could not be decrypted: {referenced_message_id}")

        webpage = None
        if is_referenced_link_message(referenced_message):
            link_url = extract_link_url(referenced_message)
            if link_url:
                logger.info(f"[WeFlowChannel] Fetching quoted link content: {link_url}")
                webpage = fetch_webpage_text(
                    link_url,
                    timeout=self.get_int_config("quoted_link_fetch_timeout", 10),
                    max_chars=self.get_int_config("quoted_link_fetch_max_chars", 12000),
                )
                if webpage.get("error"):
                    logger.warning(f"[WeFlowChannel] Quoted link fetch failed: {webpage.get('error')}")

        prompt, message_content = build_quote_context(
            context.query,
            referenced_message,
            image_path=image_path,
            webpage=webpage,
        )
        context.query = prompt
        if message_content is not None:
            context.message_content = message_content
        logger.info(f"[WeFlowChannel] Attached quote context for referenced message {referenced_message_id}")

    def fetch_referenced_message(self, msg: Message, referenced_message_id: str):
        session_id = msg.room_id if msg.is_group else msg.sender_id
        if not session_id or not referenced_message_id:
            return None

        direct = self.fetch_referenced_message_direct(session_id, referenced_message_id)
        if direct:
            return direct

        try:
            res = requests.get(
                f"{self._http_url}/api/v1/messages",
                params={'talker': session_id, 'limit': 500, 'offset': 0},
                timeout=5,
            )
            if res.status_code != 200:
                logger.warning(f"[WeFlowChannel] Fetch messages failed: status={res.status_code}")
                return None

            data = res.json()
            messages = data.get('messages') or data.get('data') or []
            for item in messages:
                server_id = str(item.get('serverId') or item.get('platformMessageId') or '').strip()
                if server_id == referenced_message_id:
                    return item
        except Exception as e:
            logger.warning(f"[WeFlowChannel] Fetch referenced message failed: {e}")
        return None

    def cleanup_assets(self):
        retention_days = self.get_int_config("assets_retention_days", 7)
        if retention_days <= 0:
            return
        result = cleanup_old_files(
            os.path.abspath("./assets"),
            retention_days=retention_days,
            allowed_extensions={".jpg", ".jpeg", ".png", ".gif", ".webp"},
        )
        if result["removed"] or result["failed"]:
            logger.info(
                f"[WeFlowChannel] Assets cleanup: removed={result['removed']} failed={result['failed']}"
            )

    def get_int_config(self, key: str, default: int) -> int:
        try:
            return int(conf().get(key, default))
        except (TypeError, ValueError):
            return default

    def fetch_referenced_message_direct(self, session_id: str, referenced_message_id: str):
        try:
            res = requests.get(
                f"{self._http_url}/api/v1/message",
                params={'talker': session_id, 'serverId': referenced_message_id},
                timeout=5,
            )
            if res.status_code == 404:
                return None
            if res.status_code != 200:
                return None

            data = res.json()
            return data.get('message') or data.get('data')
        except Exception:
            return None

    def is_referenced_image_message(self, referenced_message: dict):
        try:
            local_type = int(referenced_message.get('localType') or referenced_message.get('type') or 0)
        except (TypeError, ValueError):
            local_type = 0
        parsed_content = str(referenced_message.get('parsedContent') or referenced_message.get('content') or '').strip()
        return local_type == MessageType.RECV_PIC_MSG or parsed_content == '[图片]'

    def decrypt_referenced_image(self, referenced_message: dict, referenced_message_id: str = ''):
        cached_path = get_cached_image_path(
            self.recent_image_paths,
            referenced_message,
            fallback_ids=[referenced_message_id],
        )
        if cached_path:
            logger.info(f"[WeFlowChannel] Using cached quoted image: {cached_path}")
            return cached_path

        try:
            create_time = int(referenced_message.get('createTime') or referenced_message.get('timestamp') or 0)
        except (TypeError, ValueError):
            create_time = 0
        if create_time <= 0:
            return None

        for candidate_ts in candidate_image_timestamps(create_time, now_seconds=int(time.time())):
            image_path = self._decrypt_image_by_timestamp(candidate_ts, tolerance=300)
            if image_path:
                cache_image_path(
                    self.recent_image_paths,
                    [
                        referenced_message.get('serverId'),
                        referenced_message.get('platformMessageId'),
                    ],
                    image_path,
                )
                return image_path
        return None

    def decorate_reply(self, reply: Reply, msg: Message) -> Reply:
        if reply.type == ReplyType.TEXT:
            group_chat_reply_prefix = conf().get("group_chat_reply_prefix", "")
            group_chat_reply_suffix = conf().get("group_chat_reply_suffix", "")
            single_chat_reply_prefix = conf().get("single_chat_reply_prefix", "")
            single_chat_reply_suffix = conf().get("single_chat_reply_suffix", "")
            reply_text = reply.content
            if msg.is_group:
                reply_text = (
                    group_chat_reply_prefix + reply_text + group_chat_reply_suffix
                )
            else:
                reply_text = (
                    single_chat_reply_prefix + reply_text + single_chat_reply_suffix
                )
            reply.content = reply_text
        return reply

    def handle_reply(self, msg: Message, context: Context):
        e1 = PluginManager().emit(
            Event(
                EventType.WILL_GENERATE_REPLY,
                {"channel": self, "message": msg, "context": context},
            )
        )
        if e1.is_bypass:
            return self.send(e1.reply, e1.message)

        rawReply = Bot().reply(e1.context)
        e2 = PluginManager().emit(
            Event(
                EventType.WILL_DECORATE_REPLY,
                {
                    "channel": self,
                    "message": e1.message,
                    "context": e1.context,
                    "reply": rawReply,
                },
            )
        )
        if e2.is_bypass:
            return self.send(e2.reply, e2.message)

        reply = self.decorate_reply(rawReply, msg)

        e3 = PluginManager().emit(
            Event(
                EventType.WILL_SEND_REPLY,
                {
                    "channel": self,
                    "message": e2.message,
                    "context": e2.context,
                    "reply": reply,
                },
            )
        )
        self.send(e3.reply, e3.message)

    def send(self, reply: Reply, msg: Message):
        if reply is None:
            return

        wx_id = msg.room_id if msg.is_group else msg.sender_id
        # WeChatSender uses natural names for locating chats via search or list
        target_name = msg._raw_msg.get('group_name', '') if msg.is_group else msg.sender_name

        # Fallback to ID if name is missing
        if not target_name:
            target_name = wx_id

        logger.info(f"[WeFlowChannel] QUEUING SEND TASK: target_name='{target_name}', wx_id='{wx_id}'")

        # Enqueue the send task to the worker thread to prevent UI automation collisions
        self.send_queue.put((reply, msg, target_name, wx_id))

    def send_txt(self, text, wx_id):
        """Backward compatibility for older plugins calling channel.send_txt directly"""
        reply = Reply(ReplyType.TEXT, text)
        msg_stub = type('obj', (object,), {'room_id': None, 'sender_id': wx_id, 'is_group': '@chatroom' in wx_id, '_raw_msg': {}, 'sender_name': wx_id})()
        self.send(reply, msg_stub)

    def send_img(self, url, wx_id):
        """Backward compatibility for older plugins calling channel.send_img directly"""
        reply = Reply(ReplyType.IMAGE, url)
        msg_stub = type('obj', (object,), {'room_id': None, 'sender_id': wx_id, 'is_group': '@chatroom' in wx_id, '_raw_msg': {}, 'sender_name': wx_id})()
        self.send(reply, msg_stub)

    def on_open(self, ws):
        logger.info("[WeFlow Websocket] connected")
        # Ensure we subscribe to all incoming messages upon connection
        ws.send(json.dumps({"type": "subscribe_all"}))
        logger.info("[WeFlow Websocket] sent subscribe_all payload")

    def on_close(self, ws, *args):
        logger.info(f"[WeFlow Websocket] disconnected {args}")

    def on_error(self, ws, error):
        logger.exception(f"[WeFlow Websocket] Error: {error}", exc_info=error)

    def get_personal_info(self):
        bot_wxid = conf().get("wechat_bot_wxid", "wxid_ocksk3cjcq5j22")
        bot_name = conf().get("wechat_bot_name", "pika")
        try:
            res = requests.get(f"{self._http_url}/api/v1/self")
            if res.status_code == 200:
                data = res.json().get('data', {})
                info = {
                    'wx_id': data.get('wxid', bot_wxid),
                    'wx_name': data.get('name', bot_name),
                    'home': ''
                }
                logger.info(f'WeFlow login info: {info}')
                return info
        except Exception as e:
            logger.warning(f"Could not fetch personal info: {e}")

        logger.info(f'WeFlow fallback login info from config: wxid={bot_wxid}, name={bot_name}')
        return {'wx_id': bot_wxid, 'wx_name': bot_name, 'home': ''}

    def update_contacts(self):
        self.contacts = {}
        try:
            res = requests.get(f"{self._http_url}/api/v1/contacts?limit=1000")
            if res.status_code == 200:
                data = res.json()
                contacts_list = data.get('contacts', []) or data.get('data', [])
                for v in contacts_list:
                    wxid = v.get('username', '') or v.get('wxid', '')
                    name = (
                        v.get('displayName', '')
                        or v.get('remark', '')
                        or v.get('nickname', '')
                        or v.get('name', '')
                        or wxid
                    )
                    if wxid:
                        self.contacts[wxid] = {'wxid': wxid, 'name': name}
                logger.info(f'Loaded {len(self.contacts)} WeFlow contacts')
        except Exception as e:
            logger.warning(f"Could not load contacts: {e}")

        return self.contacts
    def get_refer_extra(self, refermsg):
        # WeFlow API might lack get_refer_extra endpoints, return None for now
        return None

    # ===== WeChat .dat image decryption =====
    _DAT_SIG_V1 = bytes([0x07, 0x08, 0x56, 0x31, 0x08, 0x07])
    _DAT_SIG_V2 = bytes([0x07, 0x08, 0x56, 0x32, 0x08, 0x07])
    _DEFAULT_V1_AES_KEY = "cfcd208495d565ef"
    _IMAGE_SIGS = {
        b'\xff\xd8\xff': '.jpg',
        b'\x89PNG': '.png',
        b'GIF8': '.gif',
        b'BM': '.bmp',
    }

    def _decrypt_image_by_timestamp(self, msg_ts, tolerance=120):
        """Find and decrypt the WeChat .dat image file matching the given timestamp."""
        import struct
        data_dir = conf().get("wechat_data_dir", "")
        xor_key_raw = conf().get("image_xor_key", "0x1F")
        aes_key_str = conf().get("image_aes_key", "")

        if not data_dir:
            logger.error("[WeFlowChannel] wechat_data_dir not configured")
            return None

        # Parse XOR key (supports 0x1F or 31)
        if isinstance(xor_key_raw, str):
            xor_key_raw = xor_key_raw.strip()
            xor_key = int(xor_key_raw, 16) if xor_key_raw.lower().startswith('0x') else int(xor_key_raw)
        else:
            xor_key = int(xor_key_raw)

        attach_dir = os.path.join(data_dir, 'msg', 'attach')
        if not os.path.exists(attach_dir):
            logger.error(f"[WeFlowChannel] attach dir not found: {attach_dir}")
            return None

        # Wait for WeChat to finish writing the .dat file, then retry up to 3 times
        for attempt in range(3):
            time.sleep(3 if attempt == 0 else 3)  # 3s initial, 3s between retries

            # Scan for matching .dat files (skip thumbnails first)
            matches = []
            thumb_matches = []
            for root, dirs, files in os.walk(attach_dir):
                for f in files:
                    if not f.lower().endswith('.dat'):
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(fpath)
                        fsize = os.path.getsize(fpath)
                        if abs(mtime - msg_ts) <= tolerance:
                            fname_lower = f.lower()
                            base_no_ext = fname_lower[:-4]
                            if base_no_ext.endswith('_t') or base_no_ext.endswith('_thumb'):
                                thumb_matches.append((fpath, mtime, fsize))
                            elif fsize > 5000:
                                matches.append((fpath, mtime, fsize))
                    except Exception:
                        pass

            if matches:
                break
            logger.info(f"[WeFlowChannel] Attempt {attempt+1}/3: no full-size dat found, {len(thumb_matches)} thumbnails")

        # Fallback to thumbnails if no full-size image found
        if not matches:
            if thumb_matches:
                logger.warning(f"[WeFlowChannel] Using thumbnail as fallback")
                matches = thumb_matches
            else:
                logger.error(f"[WeFlowChannel] No .dat files within ±{tolerance}s of timestamp {msg_ts}")
                return None

        # Sort by closest timestamp, then prefer larger files (non-thumbnail)
        matches.sort(key=lambda x: (abs(x[1] - msg_ts), -x[2]))
        best_path = matches[0][0]
        logger.info(f"[WeFlowChannel] Found {len(matches)} matching dat files, best: {best_path} ({matches[0][2]} bytes)")

        # Decrypt
        try:
            with open(best_path, 'rb') as f:
                encrypted = f.read()

            decrypted = self._decrypt_dat(encrypted, xor_key, aes_key_str)
            ext = self._detect_image_ext(decrypted)

            # Save to assets directory
            save_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
            os.makedirs(save_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(best_path))[0]
            out_path = os.path.join(save_dir, f"{base_name}{ext}")

            with open(out_path, 'wb') as f:
                f.write(decrypted)

            logger.info(f"[WeFlowChannel] Decrypted image saved: {out_path} ({len(decrypted)} bytes)")
            return out_path
        except Exception as e:
            logger.error(f"[WeFlowChannel] Decrypt failed for {best_path}: {e}")
            return None

    def _decrypt_dat(self, data, xor_key, aes_key_str):
        """Auto-detect version and decrypt .dat file."""
        import struct
        version = self._get_dat_version(data)
        logger.info(f"[WeFlowChannel] dat version: V{version}")

        if version == 0:
            return bytes(b ^ xor_key for b in data)
        elif version == 1:
            key_bytes = self._DEFAULT_V1_AES_KEY.encode('ascii')[:16]
            return self._decrypt_dat_v4(data, xor_key, key_bytes)
        elif version == 2:
            if not aes_key_str or len(aes_key_str) < 16:
                raise ValueError("image_aes_key not configured or too short for V2")
            key_bytes = aes_key_str.encode('ascii')[:16]
            return self._decrypt_dat_v4(data, xor_key, key_bytes)
        else:
            return bytes(b ^ xor_key for b in data)

    def _get_dat_version(self, data):
        if len(data) < 6:
            return 0
        sig = data[:6]
        if sig == self._DAT_SIG_V1:
            return 1
        if sig == self._DAT_SIG_V2:
            return 2
        return 0

    def _decrypt_dat_v4(self, data, xor_key, aes_key_bytes):
        """V1/V2 AES-128-ECB + XOR hybrid decryption."""
        import struct
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        if len(data) < 0x0f:
            raise ValueError("File too small for V4 format")

        header = data[:0x0f]
        payload = data[0x0f:]

        aes_size = struct.unpack_from('<I', header, 6)[0]
        xor_size = struct.unpack_from('<I', header, 10)[0]

        # Align AES data to 16-byte blocks (PKCS7)
        remainder = ((aes_size % 16) + 16) % 16
        aligned_aes_size = aes_size + (16 - remainder)

        if aligned_aes_size > len(payload):
            raise ValueError(f"AES data length ({aligned_aes_size}) exceeds payload ({len(payload)})")

        # AES-128-ECB decrypt
        aes_data = payload[:aligned_aes_size]
        unpadded = b''
        if len(aes_data) > 0:
            cipher = Cipher(algorithms.AES(aes_key_bytes), modes.ECB(), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(aes_data) + decryptor.finalize()
            # PKCS7 unpad
            pad_len = decrypted[-1]
            if 0 < pad_len <= 16 and pad_len <= len(decrypted):
                if all(decrypted[i] == pad_len for i in range(len(decrypted) - pad_len, len(decrypted))):
                    decrypted = decrypted[:-pad_len]
            unpadded = decrypted

        # XOR remaining data
        remaining = payload[aligned_aes_size:]
        if xor_size > 0 and xor_size <= len(remaining):
            raw_length = len(remaining) - xor_size
            raw_data = remaining[:raw_length]
            xor_data = remaining[raw_length:]
            xored = bytes(b ^ xor_key for b in xor_data)
            return unpadded + raw_data + xored
        else:
            return unpadded + remaining

    def _detect_image_ext(self, data):
        for sig, ext in self._IMAGE_SIGS.items():
            if data[:len(sig)] == sig:
                return ext
        if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return '.webp'
        return '.jpg'

    def get_refer_image(self, refermsg, save_dir=None):
        return None
