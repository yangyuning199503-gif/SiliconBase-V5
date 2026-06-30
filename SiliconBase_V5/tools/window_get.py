#!/usr/bin/env python3
"""
原子工具：查找窗口句柄
支持通过标题、类名、进程名查找窗口。
兼容常用参数名：window_title（映射到title_pattern），window_class（映射到class_name）
如果传入 action='list' 或 command='list'，返回所有可见窗口。
"""
import asyncio

import win32api
import win32con
import win32gui
import win32process

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class WindowGet(BaseTool):
    tool_id = "window_get"
    name = "查找窗口"
    description = "按标题/类名/进程名查找窗口句柄。支持参数：title_pattern, class_name, process_name，以及别名window_title, window_class。传入 action='list' 或 command='list' 可列出所有窗口。"
    input_schema = {
        "type": "object",
        "properties": {
            "title_pattern": {"type": "string"},
            "window_title": {"type": "string", "description": "与title_pattern同义"},
            "class_name": {"type": "string"},
            "window_class": {"type": "string", "description": "与class_name同义"},
            "process_name": {"type": "string"},
            "action": {"type": "string", "enum": ["list"], "description": "如果传入'list'，忽略其他参数，返回所有窗口"},
            "command": {"type": "string", "enum": ["list"], "description": "同action"}
        },
        "anyOf": [
            {"required": ["title_pattern"]},
            {"required": ["window_title"]},
            {"required": ["class_name"]},
            {"required": ["window_class"]},
            {"required": ["process_name"]},
            {"required": ["action"]},
            {"required": ["command"]}
        ],
        "description": "窗口查询支持多条件组合（AND匹配），如同时传title_pattern和process_name可精确定位窗口"
    }

    def _execute(self, **kwargs):
        try:
            # 检查是否请求列出所有窗口
            if kwargs.get("action") == "list" or kwargs.get("command") == "list":
                return self._list_all_windows()

            # 兼容别名
            title_pattern = kwargs.get("title_pattern") or kwargs.get("window_title")
            class_name = kwargs.get("class_name") or kwargs.get("window_class")
            process_name = kwargs.get("process_name")

            windows_info = []
            def enum_callback(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                match = True
                if title_pattern and title_pattern.lower() not in title.lower():
                    match = False
                if class_name and class_name.lower() != cls.lower():
                    match = False
                if process_name:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    try:
                        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                                                      False, pid)
                        exe = win32process.GetModuleFileNameEx(handle, 0)
                        win32api.CloseHandle(handle)
                        if not exe.lower().endswith(process_name.lower()):
                            match = False
                    except Exception:
                        match = False
                if match:
                    windows_info.append({
                        "hwnd": hwnd,
                        "title": title,
                        "class": cls
                    })
                return True
            win32gui.EnumWindows(enum_callback, None)
            # 限制返回数量，避免过大
            if len(windows_info) > 50:
                windows_info = windows_info[:50]
            return {
                "success": True,
                "error_code": None,
                "user_message": f"找到 {len(windows_info)} 个窗口",
                "data": {"windows": windows_info}
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _list_all_windows(self):
        """列出所有可见窗口（仅返回句柄和标题）"""
        windows = []
        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:  # 只返回有标题的窗口
                    windows.append({
                        "hwnd": hwnd,
                        "title": title
                    })
            return True
        win32gui.EnumWindows(enum_callback, None)
        return {
            "success": True,
            "error_code": None,
            "user_message": f"列出 {len(windows[:50])} 个窗口",
            "data": {"windows": windows[:50]}
        }
