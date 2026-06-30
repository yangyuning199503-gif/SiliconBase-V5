#!/usr/bin/env python3
"""
原子工具：键盘输入（支持组合键）
修复版：增加跨平台兼容
"""
import asyncio
import sys
import time

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger

# 跨平台兼容判断
IS_WINDOWS = sys.platform == "win32"

# 仅Windows系统导入win32相关库
if IS_WINDOWS:
    try:
        import win32api
        import win32clipboard
        import win32con
    except ImportError as e:
        logger.error(f"Windows依赖库导入失败: {e}，请安装 pywin32")
        win32api = None
        win32con = None
        win32clipboard = None
else:
    win32api = None
    win32con = None
    win32clipboard = None
    logger.warning("当前系统非Windows，键盘输入功能不可用")

VK_MAP = {
    "ctrl": win32con.VK_CONTROL if win32con else 0x11,
    "shift": win32con.VK_SHIFT if win32con else 0x10,
    "alt": win32con.VK_MENU if win32con else 0x12,
    "win": win32con.VK_LWIN if win32con else 0x5B,
    "tab": win32con.VK_TAB if win32con else 0x09,
    "enter": win32con.VK_RETURN if win32con else 0x0D,
    "esc": win32con.VK_ESCAPE if win32con else 0x1B,
    "backspace": win32con.VK_BACK if win32con else 0x08,
    "delete": win32con.VK_DELETE if win32con else 0x2E,
    "home": win32con.VK_HOME if win32con else 0x24,
    "end": win32con.VK_END if win32con else 0x23,
    "pageup": win32con.VK_PRIOR if win32con else 0x21,
    "pagedown": win32con.VK_NEXT if win32con else 0x22,
    "up": win32con.VK_UP if win32con else 0x26,
    "down": win32con.VK_DOWN if win32con else 0x28,
    "left": win32con.VK_LEFT if win32con else 0x25,
    "right": win32con.VK_RIGHT if win32con else 0x27,
    "f1": win32con.VK_F1 if win32con else 0x70,
    "f2": win32con.VK_F2 if win32con else 0x71,
    "f3": win32con.VK_F3 if win32con else 0x72,
    "f4": win32con.VK_F4 if win32con else 0x73,
    "f5": win32con.VK_F5 if win32con else 0x74,
    "f6": win32con.VK_F6 if win32con else 0x75,
    "f7": win32con.VK_F7 if win32con else 0x76,
    "f8": win32con.VK_F8 if win32con else 0x77,
    "f9": win32con.VK_F9 if win32con else 0x78,
    "f10": win32con.VK_F10 if win32con else 0x79,
    "f11": win32con.VK_F11 if win32con else 0x7A,
    "f12": win32con.VK_F12 if win32con else 0x7B,
    "space": win32con.VK_SPACE if win32con else 0x20,
    "capslock": win32con.VK_CAPITAL if win32con else 0x14,
}

def char_to_vk(ch: str):
    if 'a' <= ch <= 'z':
        return ord(ch.upper())
    if 'A' <= ch <= 'Z':
        return ord(ch)
    if '0' <= ch <= '9':
        return ord(ch)
    punct_map = {
        '.': 190, ',': 188, ';': 186, "'": 222,
        '[': 219, ']': 221, '\\': 220, '-': 189,
        '=': 187, '`': 192, '/': 191
    }
    return punct_map.get(ch)


def _send_key(vk: int, shift: bool = False):
    """发送单个按键，可选配合 Shift"""
    if shift:
        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    if shift:
        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)


class KeyboardInput(BaseTool):
    tool_id = "keyboard_input"
    name = "键盘输入"
    description = "模拟键盘输入文本或组合键。注意：本工具只向当前焦点窗口发送按键，不会自动切换窗口。输入前必须先调用window_focus聚焦目标，或直接使用window_action(type_text)自动完成聚焦+输入。"
    require_confirmation = True  # 高危操作需要确认
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要输入的文本内容"
            },
            "keys": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["ctrl", "shift", "alt", "win", "tab", "enter", "esc",
                             "backspace", "delete", "home", "end", "pageup", "pagedown",
                             "up", "down", "left", "right", "space", "f1", "f2", "f3",
                             "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]
                },
                "description": "特殊按键列表，常用: enter(回车), tab, esc, delete, space, 方向键等。示例: ['enter'] 按回车, ['ctrl', 'c'] 复制"
            }
        },
        "anyOf": [{"required": ["text"]}, {"required": ["keys"]}],
        "additionalProperties": False
    }

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步执行键盘输入 - 显式桥接到线程池

        win32api 调用本质上是同步的系统调用，无法真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        if not IS_WINDOWS or win32api is None:
            return {
                "success": False,
                "error_code": "NOT_SUPPORTED",
                "user_message": "当前操作系统不支持键盘输入功能，仅Windows可用",
                "data": None
            }

        try:
            # 支持同时提供 text 和 keys，按顺序执行：先输入文字，再按按键
            result_text = None
            result_keys = None

            if "text" in kwargs:
                result_text = self._input_text(kwargs["text"])
                if not result_text.get("success", False):
                    return result_text

            if "keys" in kwargs:
                result_keys = self._input_keys(kwargs["keys"])
                if not result_keys.get("success", False):
                    return result_keys

            if result_text is None and result_keys is None:
                return format_error(INVALID_PARAMS, detail="必须提供 text 或 keys")

            input_desc = []
            if result_text:
                input_desc.append(f"文字:{len(kwargs.get('text', ''))}字符")
            if result_keys:
                input_desc.append(f"按键:{kwargs.get('keys')}")
            return {
                "success": True,
                "error_code": None,
                "user_message": f"键盘输入成功 ({', '.join(input_desc)})",
                "data": {"text": result_text is not None, "keys": result_keys is not None}
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    def _input_text(self, text: str) -> dict:
        skipped_chars = []
        for ch in text:
            vk = char_to_vk(ch)
            if vk:
                # 大写字母需要配合 Shift
                _send_key(vk, shift=ch.isupper())
            elif ch == ' ':
                _send_key(win32con.VK_SPACE)
            else:
                # 其他字符（如中文）通过剪贴板粘贴；失败则跳过该字符
                paste_ok = self._paste_text(ch)
                if not paste_ok:
                    skipped_chars.append(ch)
            time.sleep(0.01)
        if skipped_chars:
            logger.warning(f"[KeyboardInput] 以下字符无法输入，已跳过: {skipped_chars}")
        return {"success": True, "skipped_chars": skipped_chars}

    def _paste_text(self, text: str) -> bool:
        """通过剪贴板粘贴单个字符，带重试与恢复；返回是否成功"""
        import pywintypes

        original = None
        for attempt in range(3):
            try:
                win32clipboard.OpenClipboard()
                try:
                    try:
                        original = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    except Exception:
                        original = None
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()

                # 发送 Ctrl+V
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

                # 恢复原始剪贴板内容
                time.sleep(0.05)
                try:
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        if original is not None:
                            win32clipboard.SetClipboardText(original, win32clipboard.CF_UNICODETEXT)
                    finally:
                        win32clipboard.CloseClipboard()
                except Exception as restore_err:
                    logger.debug(f"[KeyboardInput] 恢复剪贴板失败: {restore_err}")
                return True
            except pywintypes.error as e:
                logger.warning(f"[KeyboardInput] 剪贴板占用(尝试 {attempt + 1}/3): {e}")
                time.sleep(0.05 * (attempt + 1))
            except Exception as e:
                logger.warning(f"[KeyboardInput] 剪贴板粘贴异常: {e}")
                return False
        return False

    def _input_keys(self, keys: list) -> dict:
        down_keys = []
        for key in keys:
            key_lower = key.lower()
            if key_lower in VK_MAP:
                vk = VK_MAP[key_lower]
                win32api.keybd_event(vk, 0, 0, 0)
                down_keys.append(vk)
            elif len(key) == 1:
                vk = char_to_vk(key)
                if vk:
                    win32api.keybd_event(vk, 0, 0, 0)
                    down_keys.append(vk)
        for vk in reversed(down_keys):
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        return {"success": True}
