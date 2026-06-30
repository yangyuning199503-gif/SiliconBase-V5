#!/usr/bin/env python3
"""
原子工具：打开网页
"""
import asyncio
import sys
import time
import webbrowser

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError:
        win32gui = win32con = win32process = win32api = None
else:
    win32gui = win32con = win32process = win32api = None

# 常见浏览器进程名
BROWSER_PROCESSES = ["chrome.exe", "firefox.exe", "msedge.exe", "iexplore.exe", "brave.exe", "opera.exe"]

class WebOpen(BaseTool):
    tool_id = "web_open"
    name = "打开网页"
    description = "在默认浏览器中打开URL，并自动聚焦浏览器窗口"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要打开的网址"},
            "focus": {"type": "boolean", "default": True, "description": "是否自动聚焦浏览器窗口"}
        },
        "required": ["url"]
    }

    def _execute(self, **kwargs):
        url = kwargs.get("url")
        focus = kwargs.get("focus", True)

        if not url:
            return format_error(INVALID_PARAMS, detail="url 不能为空")

        try:
            # 打开浏览器前获取当前窗口列表（用于对比找新窗口）
            existing_hwnds = set()
            if IS_WINDOWS and win32gui and focus:
                def enum_callback(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                        existing_hwnds.add(hwnd)
                    return True
                win32gui.EnumWindows(enum_callback, None)

            # 打开浏览器
            webbrowser.open(url)

            # 等待浏览器启动
            time.sleep(2.5)

            # 自动聚焦浏览器窗口
            hwnd = None
            if IS_WINDOWS and win32gui and focus:
                hwnd = self._find_and_focus_browser(existing_hwnds)

            user_msg = f"已在浏览器中打开 {url}"
            result_data = {"url": url}
            if hwnd:
                result_data["hwnd"] = hwnd
                result_data["focused"] = True
                user_msg += " 并已聚焦"

            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": result_data
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _find_and_focus_browser(self, existing_hwnds):
        """查找并聚焦浏览器窗口"""
        try:
            # 方法1：查找新出现的窗口
            new_hwnds = []
            def enum_callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd) and hwnd not in existing_hwnds:
                    title = win32gui.GetWindowText(hwnd)
                    if title and any(browser in title.lower() for browser in ["chrome", "firefox", "edge", "internet", "brave", "opera"]):
                        new_hwnds.append(hwnd)
                return True
            win32gui.EnumWindows(enum_callback, None)

            # 方法2：如果没有找到新窗口，查找已知浏览器进程
            if not new_hwnds:
                def enum_all(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if title:
                            # 检查进程名
                            try:
                                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
                                exe = win32process.GetModuleFileNameEx(handle, 0)
                                win32api.CloseHandle(handle)
                                exe_name = exe.lower().split("\\")[-1]
                                if exe_name in BROWSER_PROCESSES:
                                    new_hwnds.append(hwnd)
                            except Exception:
                                # Win32 API错误，可能是权限问题或进程已退出，继续处理下一个窗口
                                pass
                    return True
                win32gui.EnumWindows(enum_all, None)

            # 聚焦找到的第一个浏览器窗口
            if new_hwnds:
                hwnd = new_hwnds[0]
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return hwnd

        except Exception as e:
            print(f"[WebOpen] 聚焦窗口失败: {e}")

        return None
