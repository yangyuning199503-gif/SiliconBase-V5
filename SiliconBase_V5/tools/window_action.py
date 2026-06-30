#!/usr/bin/env python3
"""
原子工具：窗口操作（高层封装）
根据窗口句柄，执行诸如点击文本、输入文本等操作。
"""
import time

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_ELEMENT_NOT_FOUND, format_error


class WindowAction(BaseTool):
    tool_id = "window_action"
    name = "窗口操作"
    description = "对指定窗口执行操作。click_text: OCR找文本并点击; type_text: 自动聚焦窗口后输入文本; get_ocr: 获取窗口内所有文本及坐标。需先通过window_get获取hwnd。输入前优先用本工具代替单独调用keyboard_input。"
    input_schema = {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer", "description": "窗口句柄，可通过window_get获取"},
            "action": {"type": "string", "enum": ["click_text", "type_text", "get_ocr"]},
            "text": {"type": "string", "description": "要点击的文本（click_text时）或要输入的文本（type_text时）"},
            "timeout": {"type": "integer", "default": 10, "description": "等待文本出现的最大秒数（click_text时）"}
        },
        "required": ["hwnd", "action"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        """异步执行：将同步 _execute 桥接到线程池，避免阻塞事件循环。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs):
        # 延迟导入，避免循环依赖
        from core.tool_manager import tool_manager

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断"
            }

        hwnd = kwargs.get("hwnd")
        action = kwargs.get("action")
        if not hwnd:
            return format_error(INVALID_PARAMS, detail="hwnd 不能为空")

        # 获取窗口区域
        rect_result = tool_manager.call_tool("window_rect", {"hwnd": hwnd}, source="window_action")
        if not rect_result.get("success"):
            return rect_result
        rect = rect_result["data"]
        left, top, width, height = rect["left"], rect["top"], rect["width"], rect["height"]

        # 获取窗口截图并进行OCR
        ocr_result = tool_manager.call_tool("screen_ocr", {
            "left": left, "top": top, "width": width, "height": height,
            "return_positions": True, "hwnd": hwnd
        }, source="window_action")
        if not ocr_result.get("success"):
            return ocr_result
        items = ocr_result["data"]["items"]

        if action == "get_ocr":
            return {
                "success": True,
                "error_code": None,
                "user_message": f"OCR识别完成，找到 {len(items)} 个文本块",
                "data": {"items": items}
            }

        elif action == "click_text":
            target_text = kwargs.get("text")
            if not target_text:
                return format_error(INVALID_PARAMS, detail="click_text 需要提供 text")
            timeout = kwargs.get("timeout", 10)
            start = time.time()
            while time.time() - start < timeout:
                # ===== 中断检查 =====
                if self.is_interrupted():
                    return {
                        "success": False,
                        "error_code": "INTERRUPTED",
                        "user_message": "操作被用户中断",
                        "data": None
                    }

                # 重新OCR以获取最新状态
                ocr_result = tool_manager.call_tool("screen_ocr", {
                    "left": left, "top": top, "width": width, "height": height,
                    "return_positions": True, "hwnd": hwnd
                }, source="window_action")
                if ocr_result.get("success"):
                    items = ocr_result["data"]["items"]
                    for item in items:
                        if target_text.lower() in item["text"].lower():
                            # 计算点击坐标（文本中心点）
                            click_x = item["left"] + (item["right"] - item["left"]) // 2
                            click_y = item["top"] + (item["bottom"] - item["top"]) // 2
                            # 转换为屏幕绝对坐标
                            screen_x = left + click_x
                            screen_y = top + click_y
                            # 调用鼠标点击
                            click_result = tool_manager.call_tool("mouse_click", {"x": screen_x, "y": screen_y}, source="window_action")
                            if not click_result.get("success"):
                                return click_result
                            return {
                                "success": True,
                                "error_code": None,
                                "user_message": f"点击文本 '{target_text}' 成功",
                                "data": {"message": f"点击文本 '{target_text}' 成功"}
                            }
                time.sleep(0.5)
            return format_error(TOOL_ELEMENT_NOT_FOUND, detail=f"未找到文本 '{target_text}'")

        elif action == "type_text":
            input_text = kwargs.get("text")
            if not input_text:
                return format_error(INVALID_PARAMS, detail="type_text 需要提供 text")
            # 确保窗口处于焦点
            focus_result = tool_manager.call_tool("window_focus", {"hwnd": hwnd}, source="window_action")
            if not focus_result.get("success"):
                return focus_result
            time.sleep(0.5)  # 等待焦点
            kb_result = tool_manager.call_tool("keyboard_input", {"text": input_text}, source="window_action")
            return kb_result

        else:
            return format_error(INVALID_PARAMS, detail=f"不支持的操作: {action}")
