import asyncio
import time

import win32gui

from core.base_tool import BaseTool


class WaitForWindow(BaseTool):
    tool_id = "wait_for_window"
    name = "等待窗口"
    description = "等待指定标题的窗口出现（超时返回失败）"
    input_schema = {
        "type": "object",
        "properties": {
            "title_pattern": {"type": "string"},
            "timeout": {"type": "integer", "default": 10}
        },
        "required": ["title_pattern"]
    }

    def _execute(self, **kwargs):
        pattern = kwargs["title_pattern"].lower()
        timeout = kwargs.get("timeout", 10)
        start = time.time()
        while time.time() - start < timeout:
            # 检查中断
            if self.is_interrupted():
                return {"success": False, "error_code": "INTERRUPTED", "user_message": "操作被中断", "data": None}
            def enum_callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd) and pattern in win32gui.GetWindowText(hwnd).lower():
                    self.found_hwnd = hwnd
                    return False
                return True
            self.found_hwnd = None
            win32gui.EnumWindows(enum_callback, None)
            if self.found_hwnd:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"找到窗口，句柄: {self.found_hwnd}",
                    "data": {"hwnd": self.found_hwnd}
                }
            time.sleep(0.5)
        return {"success": False, "error_code": "TIMEOUT", "user_message": f"未找到包含 '{pattern}' 的窗口", "data": None}
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
