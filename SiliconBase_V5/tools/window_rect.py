#!/usr/bin/env python3
import asyncio

import win32gui

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class WindowRect(BaseTool):
    tool_id = "window_rect"
    name = "获取窗口区域"
    description = "获取指定窗口句柄的位置和大小"
    input_schema = {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer"}
        },
        "required": ["hwnd"]
    }

    def _execute(self, **kwargs):
        hwnd = kwargs["hwnd"]
        try:
            rect = win32gui.GetWindowRect(hwnd)
            return {
                "success": True,
                "error_code": None,
                "user_message": f"获取窗口区域成功 ({rect[2] - rect[0]}x{rect[3] - rect[1]})",
                "data": {
                    "left": rect[0],
                    "top": rect[1],
                    "right": rect[2],
                    "bottom": rect[3],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1]
                }
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
