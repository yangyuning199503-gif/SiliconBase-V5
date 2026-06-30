#!/usr/bin/env python3
"""
原子工具：窗口OCR
根据窗口句柄，获取窗口内所有文本及其绝对坐标。
"""
import asyncio

import win32gui

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error


class WindowOCR(BaseTool):
    tool_id = "window_ocr"
    name = "窗口文字识别"
    description = "获取指定窗口内所有可见文本及其绝对坐标"
    input_schema = {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer", "description": "窗口句柄，可通过 window_get 获取"}
        },
        "required": ["hwnd"]
    }

    def _execute(self, **kwargs):
        # 延迟导入，避免循环
        from core.tool_manager import tool_manager

        hwnd = kwargs.get("hwnd")
        if not hwnd:
            return format_error(INVALID_PARAMS, detail="hwnd 不能为空")

        # 获取窗口区域
        try:
            rect = win32gui.GetWindowRect(hwnd)
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取窗口区域失败: {e}")
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top

        # 调用 screen_ocr 识别该区域
        ocr_tool = tool_manager.get_tool("screen_ocr")
        if not ocr_tool:
            return format_error(TOOL_EXECUTION_ERROR, detail="screen_ocr 工具不可用")

        result = ocr_tool.run(left=left, top=top, width=width, height=height, return_positions=True)
        if not result.get("success"):
            return result

        items = result["data"]["items"]
        # 将相对坐标转换为绝对坐标
        for item in items:
            item["absolute_left"] = left + item["left"]
            item["absolute_top"] = top + item["top"]
            item["absolute_right"] = left + item["right"]
            item["absolute_bottom"] = top + item["bottom"]

        return {
            "success": True,
            "error_code": None,
            "user_message": f"窗口OCR完成，识别到 {len(items)} 个文本元素",
            "data": {"items": items}
        }
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
