# wechat_sender.py - 微信消息发送脚本 (UI 自动化方案)
# 适用于 Windows 7 + 微信 PC 版 4.0+

import uiautomation as auto
import time
import sys
import os
import re
import struct
import ctypes
from ctypes import wintypes
import pyperclip


class WeChatSender:
    def __init__(self):
        self.window = None
        self._find_window()

    def _normalize_name(self, name: str) -> str:
        if not name:
            return ""
        # 去掉常见噪音：换行、未读数提示等
        return str(name).replace("\n", " ").strip()

    def _normalize_chat_title(self, name: str) -> str:
        """标准化聊天标题：去掉群人数后缀，如 马一龙交流群(4) -> 马一龙交流群"""
        n = self._normalize_name(name)
        if not n:
            return ""
        # 去掉末尾 (数字) 或 （数字）
        n = re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", n)
        return n.strip()

    def _same_chat(self, a: str, b: str) -> bool:
        na = self._normalize_chat_title(a)
        nb = self._normalize_chat_title(b)
        if not na or not nb:
            return False
        return na == nb

    def _find_window(self):
        """定位微信主窗口"""
        # 微信 4.0+ 使用 mmui::MainWindow 类名
        self.window = auto.WindowControl(
            ClassName='mmui::MainWindow',
            Name='微信'
        )

        if not self.window.Exists(maxSearchSeconds=2):
            raise Exception("微信窗口未找到，请确保微信已登录且窗口在前台")

        print("✓ 已找到微信窗口")

    def activate_window(self):
        """激活微信窗口到前台"""
        try:
            self.window.SwitchToThisWindow()
            time.sleep(0.2)
        except:
            pass

    def paste_text(self, text: str) -> bool:
        """使用剪贴板粘贴文本（比 SendKeys 快得多）"""
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            auto.SendKeys('{Ctrl}v')
            time.sleep(0.1)
            return True
        except Exception as e:
            print(f"粘贴失败: {e}")
            return False

    def paste_file(self, file_path: str) -> bool:
        """使用 CF_HDROP 剪贴板格式粘贴文件 (方案B)

        将文件路径以 DROPFILES 结构写入系统剪贴板,
        然后 Ctrl+V 触发微信的文件粘贴处理。
        仅适用于 Windows。
        """
        try:
            file_path = os.path.abspath(file_path)
            if not os.path.exists(file_path):
                print(f"✗ 文件不存在: {file_path}")
                return False

            CF_HDROP = 15
            GMEM_MOVEABLE = 0x0002
            GMEM_ZEROINIT = 0x0040

            # DROPFILES 结构 (20 字节):
            #   pFiles: DWORD = 20  (文件列表偏移量 = 结构体大小)
            #   pt:     POINT = (0, 0)
            #   fNC:    BOOL  = 0
            #   fWide:  BOOL  = 1  (UTF-16)
            header = struct.pack('Iiiii', 20, 0, 0, 0, 1)

            # 文件列表: 空终止的宽字符路径 + 额外空终止符
            file_list = (file_path + '\0\0').encode('utf-16-le')
            data = header + file_list

            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            # ── 显式声明 argtypes/restype (修复 64 位 Python 溢出) ──
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p

            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p

            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int

            kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
            kernel32.GlobalFree.restype = ctypes.c_void_p

            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int

            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = ctypes.c_int

            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p

            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int
            # ── 声明结束 ──

            # 分配全局内存
            hMem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
            if not hMem:
                print("✗ GlobalAlloc 失败")
                return False

            pMem = kernel32.GlobalLock(hMem)
            if not pMem:
                kernel32.GlobalFree(hMem)
                return False

            ctypes.memmove(pMem, data, len(data))
            kernel32.GlobalUnlock(hMem)

            # 写入剪贴板
            if not user32.OpenClipboard(None):
                kernel32.GlobalFree(hMem)
                return False

            user32.EmptyClipboard()
            result = user32.SetClipboardData(CF_HDROP, hMem)
            user32.CloseClipboard()

            if not result:
                kernel32.GlobalFree(hMem)
                print("✗ SetClipboardData 失败")
                return False
            # 成功后系统接管 hMem, 不可 GlobalFree

            # 触发粘贴
            time.sleep(0.05)
            auto.SendKeys('{Ctrl}v')
            time.sleep(0.3)
            return True

        except Exception as e:
            print(f"✗ 文件粘贴失败: {e}")
            return False

    def focus_control(self, control) -> bool:
        """优先无点击聚焦，失败再回退 PostMessage 点击（不移动光标）"""
        try:
            self.activate_window()
            try:
                control.SetFocus()
                time.sleep(0.05)
                return True
            except:
                pass
            # 回退: PostMessage 点击 (不移动光标)
            if self._post_click(control):
                time.sleep(0.08)
                return True
            # 最终兜底: 物理点击 (会移动光标)
            try:
                control.Click()
                time.sleep(0.08)
                return True
            except:
                return False
        except:
            return False

    def _post_click(self, control) -> bool:
        """向控件位置发送点击消息 (PostMessage), 不移动鼠标光标

        通过向窗口 HWND 发送 WM_LBUTTONDOWN/UP 消息实现,
        mmui 自绘控件内部会按坐标命中测试, 效果等同物理点击。
        """
        try:
            rect = control.BoundingRectangle
            if not rect or rect.left >= rect.right or rect.top >= rect.bottom:
                return False

            screen_x = (rect.left + rect.right) // 2
            screen_y = (rect.top + rect.bottom) // 2

            # 优先控件自身 HWND, 否则用主窗口 HWND
            hwnd = control.NativeWindowHandle or self.window.NativeWindowHandle
            if not hwnd:
                return False

            user32 = ctypes.windll.user32

            # 64 位安全声明
            user32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
            user32.ScreenToClient.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                            wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL

            # 屏幕坐标 → 客户区坐标
            point = wintypes.POINT(screen_x, screen_y)
            user32.ScreenToClient(hwnd, ctypes.byref(point))

            lparam = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)

            WM_LBUTTONDOWN = 0x0201
            WM_LBUTTONUP = 0x0202
            MK_LBUTTON = 0x0001

            user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            time.sleep(0.05)
            user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
            return True

        except Exception as e:
            print(f"_post_click 异常: {e}")
            return False

    def _press_enter(self):
        """通过 keybd_event 发送 Enter 键 (含 scan code, 比 SendKeys 更接近物理键盘)

        auto.SendKeys('{Enter}') 使用 SendInput 但可能不带 scan code,
        某些自绘控件 (如微信 @ 弹窗) 只响应带 scan code 的键盘事件。
        """
        VK_RETURN = 0x0D
        SCAN_RETURN = 0x1C
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_RETURN, SCAN_RETURN, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_RETURN, SCAN_RETURN, KEYEVENTF_KEYUP, 0)

    def get_current_chat_name(self) -> str:
        """获取当前聊天窗口的联系人/群聊名称（带短重试）"""
        for _ in range(3):
            try:
                header = self.window.TextControl(FoundIndex=1)
                if header.Exists(maxSearchSeconds=0.2):
                    name = self._normalize_name(header.Name)
                    if name and name != "微信":
                        return name

                title = self.window.Control(ClassName='mmui::Title')
                if title and title.Exists(maxSearchSeconds=0.2):
                    n = self._normalize_name(title.Name)
                    if n and n != "微信":
                        return n
            except:
                pass
            time.sleep(0.08)
        return ""

    def open_chat_from_list(self, contact: str) -> bool:
        """优先从左侧会话列表点击联系人（首屏）"""
        try:
            target = self._normalize_name(contact)

            # 先直接找“会话”列表（你的环境里已验证存在）
            chat_list = self.window.ListControl(Name='会话')
            if not chat_list.Exists(maxSearchSeconds=0.5):
                # 兜底：不按名字找第一个 ListControl
                chat_list = self.window.ListControl(FoundIndex=1)
                if not chat_list.Exists(maxSearchSeconds=0.5):
                    print("会话列表控件未找到")
                    return False

            self.focus_control(chat_list)
            time.sleep(0.08)

            # 连续两轮抓取（应对 Qt 刷新延迟）
            for round_idx in range(2):
                items = []
                try:
                    items = chat_list.GetChildren()
                except:
                    items = []

                # 只保留 ListItemControl
                list_items = []
                for it in items:
                    try:
                        if it.ControlTypeName == 'ListItemControl':
                            list_items.append(it)
                    except:
                        pass

                scored = []
                for it in list_items:
                    try:
                        name = self._normalize_name(it.Name)
                    except:
                        name = ""
                    if not name:
                        continue

                    # 微信会话项 Name 通常是: "昵称 预览 时间"
                    score = 0
                    if name == target:
                        score = 120
                    elif name.startswith(target):
                        score = 100
                    elif f"{target} " in name:
                        score = 80
                    elif target in name:
                        score = 60

                    if score > 0:
                        scored.append((score, it, name))

                if scored:
                    scored.sort(key=lambda x: x[0], reverse=True)
                    # 尝试前2个候选点击验证
                    for score, picked, picked_name in scored[:2]:
                        # PostMessage 点击, 不移动光标
                        if not self._post_click(picked):
                            # 兜底: 物理点击
                            self.focus_control(picked)
                            try:
                                picked.Click()
                            except:
                                pass
                        time.sleep(0.22)

                        now = self.get_current_chat_name()
                        if self._same_chat(now, target) or (target and target in now):
                            return True

                    now = self.get_current_chat_name()
                    print(f"列表候选点击后仍未切换，当前: [{now}]，目标: [{target}]")
                    return False

                if round_idx == 0:
                    time.sleep(0.2)

            return False

        except Exception as e:
            print(f"open_chat_from_list 异常: {e}")
            return False

    def search_and_open_chat(self, contact: str) -> bool:
        """通过搜索框切换会话"""
        try:
            search_box = self.window.EditControl(Name='搜索')
            if not search_box.Exists(maxSearchSeconds=1):
                print("✗ 未找到搜索框")
                return False
            if not self.focus_control(search_box):
                print("✗ 无法聚焦搜索框")
                return False
            time.sleep(0.1)
            auto.SendKeys('{Ctrl}a')
            auto.SendKeys('{Delete}')
            time.sleep(0.06)
            auto.SendKeys(contact)
            time.sleep(0.35)
            auto.SendKeys('{Enter}')
            time.sleep(0.25)
            switched = self.get_current_chat_name()
            ok = self._same_chat(switched, contact) or (contact in switched)
            if not ok:
                print(f"✗ 搜索切换失败: 当前[{switched}] 目标[{contact}]")
            return ok
        except Exception as e:
            print(f"search_and_open_chat 异常: {e}")
            return False

    def ensure_target_chat(self, contact: str) -> bool:
        """确保切到目标会话：当前会话 -> 列表 -> 搜索（带重试）"""
        current = self.get_current_chat_name()
        if self._same_chat(current, contact):
            return True

        if self.open_chat_from_list(contact):
            return True

        # 搜索兜底（两次机会）
        for i in range(2):
            if self.search_and_open_chat(contact):
                return True
            if i == 0:
                time.sleep(0.2)

        return False

    def startup_self_check(self) -> bool:
        """启动自检：窗口/会话列表/搜索框/输入框"""
        ok = True
        try:
            if not self.window or not self.window.Exists(maxSearchSeconds=0.5):
                print("[自检] 微信主窗口: 失败")
                return False
            print("[自检] 微信主窗口: OK")

            chat_list = self.window.ListControl(Name='会话')
            if chat_list.Exists(maxSearchSeconds=0.3):
                print("[自检] 会话列表控件: OK")
            else:
                print("[自检] 会话列表控件: 未找到(将依赖搜索兜底)")

            search_box = self.window.EditControl(Name='搜索')
            if search_box.Exists(maxSearchSeconds=0.3):
                print("[自检] 搜索框: OK")
            else:
                print("[自检] 搜索框: 失败")
                ok = False

            input_box = self.window.EditControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=0.3):
                input_box = self.window.DocumentControl(FoundIndex=1)
            if input_box.Exists(maxSearchSeconds=0.3):
                print("[自检] 消息输入框定位: OK")
            else:
                print("[自检] 消息输入框定位: 失败")
                ok = False
        except Exception as e:
            print(f"[自检] 异常: {e}")
            ok = False
        return ok

    def send_in_current_chat(self, message: str) -> bool:
        """在当前会话窗口发送消息（不做会话切换）"""
        try:
            input_box = self.window.EditControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                input_box = self.window.DocumentControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                print("✗ 未找到消息输入框")
                return False

            if not self.focus_control(input_box):
                print("✗ 无法聚焦消息输入框")
                return False
            time.sleep(0.05)

            send_ok = self.paste_text(message)
            if not send_ok:
                try:
                    auto.SendKeys(message)
                    send_ok = True
                except:
                    send_ok = False

            if not send_ok:
                if not self._post_click(input_box):
                    input_box.Click()
                time.sleep(0.08)
                if not self.paste_text(message):
                    auto.SendKeys(message)

            time.sleep(0.1)
            auto.SendKeys('{Enter}')
            return True
        except Exception as e:
            print(f"✗ 当前会话发送失败: {e}")
            return False

    def send_file_in_current_chat(self, file_path: str, paste_wait: float = 0.6) -> bool:
        """在当前会话窗口发送文件 (CF_HDROP 粘贴方式)

        Args:
            file_path: 文件绝对路径 (图片/视频)
            paste_wait: 粘贴后等待预览加载的秒数
        """
        try:
            if not os.path.exists(file_path):
                print(f"✗ 文件不存在: {file_path}")
                return False

            # 聚焦消息输入框
            input_box = self.window.EditControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                input_box = self.window.DocumentControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                print("✗ 未找到消息输入框")
                return False

            if not self.focus_control(input_box):
                print("✗ 无法聚焦消息输入框")
                return False
            time.sleep(0.1)

            # CF_HDROP 粘贴
            if not self.paste_file(file_path):
                return False

            # 等待微信加载预览
            time.sleep(paste_wait)

            # 发送
            auto.SendKeys('{Enter}')
            time.sleep(0.3)
            print(f"✓ 文件已发送: {os.path.basename(file_path)}")
            return True

        except Exception as e:
            print(f"✗ 文件发送失败: {e}")
            return False

    def _at_wait(self, base: float = 0.12, retry: bool = True) -> None:
        """短等待 + 可选一次补偿 (用于 @mention 流程加速)"""
        time.sleep(base)
        if retry:
            time.sleep(base)

    def send_at_text_in_current_chat(self, who: str, message: str) -> bool:
        """在当前群聊窗口发送带原生 @mention 的消息

        流程: 聚焦输入框 → @ 触发弹窗 → 剪贴板粘贴名字过滤 → Enter 选择 → 正文 → 发送
        微信 PC 中输入 @ 会弹出群成员选择框, 选中后微信自动插入蓝色原生 @mention.
        用剪贴板粘贴名字而非 SendKeys, 避免 IME 候选框干扰 @ 弹窗。

        Args:
            who: 被 @ 的人昵称 (群内显示名)
            message: 消息正文
        """
        try:
            input_box = self.window.EditControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                input_box = self.window.DocumentControl(FoundIndex=1)
            if not input_box.Exists(maxSearchSeconds=1):
                print("✗ 未找到消息输入框")
                return False

            if not self.focus_control(input_box):
                print("✗ 无法聚焦消息输入框")
                return False
            time.sleep(0.05)

            # 1. 键入 @ 触发群成员弹窗 (必须键盘输入, 粘贴不可靠)
            auto.SendKeys('@')
            self._at_wait(0.12)

            # 2. 剪贴板粘贴名字过滤弹窗
            pyperclip.copy(who)
            auto.SendKeys('{Ctrl}v')
            self._at_wait(0.12)

            # 3. Enter 选中 (keybd_event + scan code)
            self._press_enter()
            time.sleep(0.12)

            # 3b. 安全优先：默认跳过第2次 Enter，避免“@单独发送”
            # 仅当未来能明确检测到候选弹窗仍在时再启用补偿。

            # 4. 正文统一剪贴板粘贴 (避免 IME/SendKeys 差异)
            pyperclip.copy(message)
            auto.SendKeys('{Ctrl}v')
            time.sleep(0.08)

            # 5. 发送前轻校验：避免空发/仅@发送
            draft_text = ''
            try:
                draft_text = input_box.GetValuePattern().Value or ''
            except:
                try:
                    draft_text = input_box.Name or ''
                except:
                    draft_text = ''

            draft_text = draft_text.strip()
            if not draft_text:
                print("✗ @mention 发送取消：输入框为空")
                return False

            # 去掉一个 @mention 后若无正文，视为仅@消息，取消发送
            tail = re.sub(r'^@\S+[\s\u2005\u00a0]*', '', draft_text).strip()
            if not tail:
                print("✗ @mention 发送取消：检测到仅@无正文")
                return False

            # 6. 发送
            auto.SendKeys('{Enter}')
            print(f"✓ @{who} 消息已发送")
            return True

        except Exception as e:
            print(f"✗ @mention 发送失败: {e}")
            return False

    def send_at_message(self, contact: str, who: str, message: str) -> bool:
        """发送带原生 @mention 的消息给群聊 (含会话切换安全路径)

        Args:
            contact: 群聊名称
            who: 被 @ 的人昵称 (群内显示名)
            message: 消息正文
        """
        try:
            self.activate_window()

            if not self.ensure_target_chat(contact):
                print(f"✗ 无法切换到目标会话 [{contact}]，取消 @mention 发送")
                return False

            return self.send_at_text_in_current_chat(who, message)

        except Exception as e:
            print(f"✗ @mention 发送失败: {e}")
            return False

    def send_message(self, contact: str, message: str) -> bool:
        """
        发送消息给指定联系人

        Args:
            contact: 联系人/群聊名称（备注名或昵称）
            message: 要发送的消息内容

        Returns:
            bool: 发送是否成功
        """
        try:
            # 确保窗口在前台
            self.activate_window()

            # 先确保切到目标会话；切不到就直接失败，避免发错窗口
            if not self.ensure_target_chat(contact):
                print(f"✗ 无法切换到目标会话 [{contact}]，取消发送")
                return False

            if not self.send_in_current_chat(message):
                return False

            print(f"✓ 消息已发送给 [{contact}]: {message[:30]}...")
            return True

        except Exception as e:
            print(f"✗ 发送失败: {e}")
            return False

    def send_file(self, contact: str, file_path: str) -> bool:
        """发送文件给指定联系人 (含会话切换安全路径)

        流程: ensure_target_chat → 切换失败不发送 → send_file_in_current_chat
        """
        try:
            self.activate_window()

            if not self.ensure_target_chat(contact):
                print(f"✗ 无法切换到目标会话 [{contact}]，取消文件发送")
                return False

            return self.send_file_in_current_chat(file_path)

        except Exception as e:
            print(f"✗ 文件发送失败: {e}")
            return False

    def send_to_file_helper(self, message: str) -> bool:
        """快捷发送给文件传输助手（测试用）"""
        return self.send_message("文件传输助手", message)


def main():
    """命令行测试"""
    if len(sys.argv) < 3:
        print("用法: python wechat_sender.py <联系人> <消息>")
        print("示例: python wechat_sender.py 文件传输助手 测试消息")
        sys.exit(1)

    contact = sys.argv[1]
    message = sys.argv[2]

    try:
        sender = WeChatSender()
        success = sender.send_message(contact, message)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
