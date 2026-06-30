#!/usr/bin/env python3
"""
原子工具：激活窗口
"""
import win32api
import win32con
import win32gui
import win32process

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class WindowFocus(BaseTool):
    tool_id = "window_focus"
    name = "激活窗口"
    description = "将指定窗口置于前台。支持通过句柄(hwnd)、窗口标题(title_pattern)或进程名(process_name)查找。注意：标题为大小写不敏感子串匹配；音乐/视频类应用窗口标题常显示为歌曲名而非应用名，失败后改用process_name(如cloudmusic.exe)或先用window_get获取hwnd。"
    input_schema = {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer", "description": "窗口句柄（最优先使用）"},
            "title_pattern": {"type": "string", "description": "窗口标题关键词（支持模糊匹配）"},
            "window_title": {"type": "string", "description": "与title_pattern同义，兼容旧版调用"},
            "process_name": {"type": "string", "description": "进程名（可与其他条件组合使用）"}
        },
        "anyOf": [
            {"required": ["hwnd"]},
            {"required": ["title_pattern"]},
            {"required": ["window_title"]},
            {"required": ["process_name"]}
        ],
        "description": "窗口聚焦支持多条件组合，如同时传title_pattern和process_name可精确定位窗口"
    }

    async def _execute_async(self, **kwargs):
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute_sync(**kwargs))

    def _execute_sync(self, **kwargs):
        try:
            hwnd = kwargs.get("hwnd")
            title_pattern = kwargs.get("title_pattern")
            window_title = kwargs.get("window_title")
            process_name = kwargs.get("process_name")

            # 兼容 window_title 参数，如果提供了则用作 title_pattern
            if window_title is not None and title_pattern is None:
                title_pattern = window_title

            # 如果提供了hwnd，直接使用
            if hwnd and win32gui.IsWindow(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"窗口已聚焦 (hwnd: {hwnd})",
                    "data": {"hwnd": hwnd}
                }

            # 多条件组合查找
            found_hwnd = None
            def enum_callback(hwnd, _):
                nonlocal found_hwnd
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                title = win32gui.GetWindowText(hwnd)
                match = True

                # 标题匹配（模糊）
                if title_pattern and title_pattern.lower() not in title.lower():
                    match = False

                # 进程名匹配
                if process_name and match:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
                        exe = win32process.GetModuleFileNameEx(handle, 0)
                        win32api.CloseHandle(handle)
                        if not exe.lower().endswith(process_name.lower()):
                            match = False
                    except Exception:
                        match = False

                if match:
                    found_hwnd = hwnd
                    return False  # 停止枚举
                return True

            win32gui.EnumWindows(enum_callback, None)

            if not found_hwnd:
                return {"success": False, "error_code": "TOOL_ELEMENT_NOT_FOUND", "user_message": "未找到匹配的窗口，请检查窗口标题或进程名是否正确", "data": None}

            win32gui.ShowWindow(found_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(found_hwnd)
            return {
                "success": True,
                "error_code": None,
                "user_message": f"窗口已聚焦 (hwnd: {found_hwnd})",
                "data": {"hwnd": found_hwnd}
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)

    def _execute(self, **kwargs):
        return self._execute_sync(**kwargs)
