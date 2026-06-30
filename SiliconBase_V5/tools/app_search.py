#!/usr/bin/env python3
"""
原子工具：应用内搜索
优先使用 UI 自动化定位搜索框和结果，失败时回退到 OCR。
"""
import time

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_ELEMENT_NOT_FOUND, format_error
from core.logger import logger


class AppSearch(BaseTool):
    tool_id = "app_search"
    name = "应用内搜索"
    description = "在指定窗口中搜索文本，并尝试点击第一个匹配结果。优先使用UI自动化，失败时回退到OCR。"
    input_schema = {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer", "description": "目标窗口句柄"},
            "search_text": {"type": "string", "description": "要搜索的文本"},
            "click_result": {"type": "boolean", "default": True, "description": "是否点击第一个搜索结果"}
        },
        "required": ["hwnd", "search_text"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        """异步包装：将同步 _execute 桥接到异步执行链路。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs):
        # 延迟导入 tool_manager 避免循环导入
        from core.tool_manager import tool_manager

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        hwnd = kwargs.get("hwnd")
        search_text = kwargs.get("search_text")
        click_result = kwargs.get("click_result", True)

        if not hwnd or not search_text:
            return format_error(INVALID_PARAMS, detail="需要 hwnd 和 search_text")

        # 优先使用 UI 自动化
        success, msg = self._search_with_uia(hwnd, search_text, click_result)
        if success:
            return {
                "success": True,
                "error_code": None,
                "user_message": msg,
                "data": {"message": msg}
            }

        # 回退到 OCR
        logger.warning("UI自动化搜索失败或不可用，回退到OCR")
        return self._search_with_ocr(hwnd, search_text, click_result, tool_manager)

    def _search_with_uia(self, hwnd, search_text, click_result):
        """使用 uiautomation 进行搜索（捕获 ImportError）"""
        try:
            import uiautomation as auto
        except ImportError:
            logger.debug("uiautomation 未安装，跳过 UI 自动化")
            return False, "uiautomation 未安装"

        # ===== 中断检查 =====
        if self.is_interrupted():
            return False, "操作被用户中断"

        try:
            window = auto.ControlFromHandle(hwnd)
            if not window.Exists(0, 0):
                return False, "窗口不存在或不可访问"

            # 查找 Edit 控件（输入框）
            edit = window.EditControl(searchDepth=5)
            if not edit.Exists(0, 0):
                return False, "未找到输入框"

            # 点击输入框并输入文本
            edit.Click()
            edit.SendKeys(search_text)
            time.sleep(0.5)

            # ===== 中断检查 =====
            if self.is_interrupted():
                return False, "操作被用户中断"

            # 查找搜索按钮（常见名称）
            search_btn = window.ButtonControl(Name='搜索') or window.ButtonControl(Name='Search') or window.ButtonControl(Name='查找')
            if search_btn.Exists(0, 0):
                search_btn.Click()
            else:
                # 否则按回车
                edit.SendKeys('{Enter}')
            time.sleep(1)

            # ===== 中断检查 =====
            if self.is_interrupted():
                return False, "操作被用户中断"

            if click_result:
                # 尝试点击第一个搜索结果
                result_control = window.Control(Name=search_text, searchDepth=5) or \
                                 window.TextControl(Name=search_text, searchDepth=5) or \
                                 window.ListItemControl(Name=search_text, searchDepth=5)
                if result_control.Exists(0, 0):
                    result_control.Click()
                    return True, f"已在窗口 {hwnd} 中搜索 '{search_text}' (UI自动化，并点击结果)"
                else:
                    return True, f"已在窗口 {hwnd} 中搜索 '{search_text}' (UI自动化，但未找到结果控件)"
            return True, f"已在窗口 {hwnd} 中搜索 '{search_text}' (UI自动化)"
        except Exception as e:
            logger.error(f"UI自动化搜索异常: {e}")
            return False, str(e)

    def _search_with_ocr(self, hwnd, search_text, click_result, tool_manager):
        """回退到 OCR 方式"""
        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        # 获取窗口区域
        rect_result = tool_manager.call_tool("window_rect", {"hwnd": hwnd}, source="app_search")
        if not rect_result.get("success"):
            return rect_result
        rect = rect_result["data"]
        left, top, width, height = rect["left"], rect["top"], rect["width"], rect["height"]

        # 1. 寻找搜索框（通过 OCR 找“搜索”或输入框的典型位置）
        ocr_result = tool_manager.call_tool("screen_ocr", {
            "left": left, "top": top, "width": width, "height": height,
            "return_positions": True, "hwnd": hwnd
        }, source="app_search")
        if not ocr_result.get("success"):
            return ocr_result
        items = ocr_result["data"]["items"]

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        search_box_keywords = ["搜索", "查找", "Search", "请输入"]
        search_box_rect = None
        for item in items:
            if any(kw in item["text"] for kw in search_box_keywords):
                search_box_rect = {
                    "left": item["left"], "top": item["top"],
                    "right": item["right"], "bottom": item["bottom"]
                }
                logger.info(f"找到搜索框: {item['text']} 在 {search_box_rect}")
                break

        if not search_box_rect:
            # 如果没有找到明确的关键词，默认点击窗口中央偏上区域
            search_box_rect = {
                "left": width // 4,
                "top": height // 8,
                "right": width * 3 // 4,
                "bottom": height // 4
            }
            logger.warning("未找到搜索框文本，使用默认区域")

        # 点击搜索框
        center_x = left + (search_box_rect["left"] + search_box_rect["right"]) // 2
        center_y = top + (search_box_rect["top"] + search_box_rect["bottom"]) // 2
        click_res = tool_manager.call_tool("mouse_click", {"x": center_x, "y": center_y}, source="app_search")
        if not click_res.get("success"):
            return click_res
        time.sleep(0.5)

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        # 输入搜索文本
        input_res = tool_manager.call_tool("keyboard_input", {"text": search_text}, source="app_search")
        if not input_res.get("success"):
            return input_res
        time.sleep(0.5)

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        # 按回车
        enter_res = tool_manager.call_tool("keyboard_input", {"keys": ["enter"]}, source="app_search")
        if not enter_res.get("success"):
            return enter_res
        time.sleep(1)

        # ===== 中断检查 =====
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        if click_result:
            # 重新 OCR 获取结果列表
            ocr_result = tool_manager.call_tool("screen_ocr", {
                "left": left, "top": top, "width": width, "height": height,
                "return_positions": True, "hwnd": hwnd
            }, source="app_search")
            if not ocr_result.get("success"):
                return ocr_result
            items = ocr_result["data"]["items"]
            target_item = None
            for item in items:
                if search_text.lower() in item["text"].lower():
                    target_item = item
                    break
            if not target_item:
                return format_error(TOOL_ELEMENT_NOT_FOUND, detail=f"未找到包含 '{search_text}' 的结果")
            center_x = left + (target_item["left"] + target_item["right"]) // 2
            center_y = top + (target_item["top"] + target_item["bottom"]) // 2
            click_res = tool_manager.call_tool("mouse_click", {"x": center_x, "y": center_y}, source="app_search")
            if not click_res.get("success"):
                return click_res

        user_msg = f"已在窗口 {hwnd} 中搜索 '{search_text}' (OCR回退)"
        return {
            "success": True,
            "error_code": None,
            "user_message": user_msg,
            "data": {"message": user_msg}
        }
