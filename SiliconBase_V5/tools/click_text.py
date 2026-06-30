#!/usr/bin/env python3
"""
原子工具：点击文本
在屏幕上查找指定文本并点击。
"""
import time

import pyautogui

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_ELEMENT_NOT_FOUND, TOOL_EXECUTION_ERROR, format_error


class ClickText(BaseTool):
    tool_id = "click_text"
    name = "点击文本"
    description = "在屏幕上查找指定文本并点击。适用于点击按钮、链接等。"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要点击的文本内容"},
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "可选，指定搜索区域 [left, top, width, height]"
            },
            "timeout": {"type": "integer", "default": 10, "description": "等待文本出现的最大秒数"}
        },
        "required": ["text"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        """异步执行：将同步 _execute 桥接到线程池，避免阻塞事件循环。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs):
        # 延迟导入避免循环
        from core.tool_manager import tool_manager

        text = kwargs.get("text")
        region = kwargs.get("region")
        timeout = kwargs.get("timeout", 10)

        if not text:
            return format_error(INVALID_PARAMS, detail="text 不能为空")

        ocr_tool = tool_manager.get_tool("screen_ocr")
        if not ocr_tool:
            return format_error(TOOL_EXECUTION_ERROR, detail="screen_ocr 工具不可用")

        start_time = time.time()
        while time.time() - start_time < timeout:
            # ===== 中断检查 =====
            if self.is_interrupted():
                return {
                    "success": False,
                    "error_code": "INTERRUPTED",
                    "user_message": "操作被用户中断",
                    "data": None
                }

            # 执行 OCR
            if region:
                left, top, width, height = region
                ocr_result = ocr_tool.run(left=left, top=top, width=width, height=height, return_positions=True)
            else:
                # 全屏 OCR（动态获取实际屏幕分辨率）
                screen_width, screen_height = pyautogui.size()
                ocr_result = ocr_tool.run(
                    left=0, top=0, width=screen_width, height=screen_height,
                    return_positions=True
                )

            if not ocr_result.get("success"):
                time.sleep(0.5)
                continue

            items = ocr_result["data"]["items"]
            for item in items:
                if text.lower() in item["text"].lower():
                    # 计算点击坐标
                    click_x = item["left"] + (item["right"] - item["left"]) // 2
                    click_y = item["top"] + (item["bottom"] - item["top"]) // 2
                    # 调用鼠标点击
                    click_tool = tool_manager.get_tool("mouse_click")
                    if not click_tool:
                        return format_error(TOOL_EXECUTION_ERROR, detail="mouse_click 工具不可用")
                    return click_tool.run(x=click_x, y=click_y)

            time.sleep(0.5)

        return format_error(TOOL_ELEMENT_NOT_FOUND, detail=f"未找到文本 '{text}'")
