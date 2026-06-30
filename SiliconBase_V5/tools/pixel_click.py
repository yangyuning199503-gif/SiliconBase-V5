# tools/pixel_click.py
# !/usr/bin/env python3
"""
智能像素点击工具 - 基于颜色定位的点击操作
支持：颜色定位点击、相对偏移点击、颜色验证点击
"""

import pyautogui

from core.base_tool import BaseTool
from core.error_codes import TOOL_ELEMENT_NOT_FOUND, TOOL_EXECUTION_ERROR, format_error, format_success


class PixelClick(BaseTool):
    tool_id = "pixel_click"
    name = "像素级智能点击"
    description = "基于颜色定位的智能点击工具。可以通过颜色查找目标位置后点击，支持偏移点击和点击前颜色验证。"
    version = "1.0.0"
    timeout = 15
    require_confirmation = False  # 相对安全，不需要确认

    input_schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["position", "color", "color_verify"],
                "default": "position",
                "description": "点击模式：position直接坐标, color通过颜色查找, color_verify验证后点击"
            },
            "x": {"type": "integer", "description": "X坐标（position模式）"},
            "y": {"type": "integer", "description": "Y坐标（position模式）"},
            "region": {
                "type": "object",
                "description": "颜色查找区域（color模式）",
                "properties": {
                    "left": {"type": "integer"},
                    "top": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"}
                }
            },
            "target_color": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "目标颜色RGB（color模式）"
            },
            "offset": {
                "type": "object",
                "default": {"x": 0, "y": 0},
                "description": "点击偏移量（相对于找到的位置）",
                "properties": {
                    "x": {"type": "integer", "default": 0},
                    "y": {"type": "integer", "default": 0}
                }
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "default": "left"
            },
            "clicks": {
                "type": "integer",
                "default": 1,
                "minimum": 1,
                "maximum": 10
            },
            "interval": {
                "type": "number",
                "default": 0.0,
                "description": "多次点击间隔（秒）"
            },
            "tolerance": {
                "type": "integer",
                "default": 5,
                "description": "颜色容差（color模式）"
            },
            "verify_color": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "点击前验证的颜色（color_verify模式）"
            }
        },
        "required": ["mode"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        """异步执行：将同步 _execute 桥接到线程池，避免阻塞事件循环。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        mode = kwargs["mode"]

        try:
            if mode == "position":
                return self._click_position(kwargs)
            elif mode == "color":
                return self._click_by_color(kwargs)
            elif mode == "color_verify":
                return self._click_with_verify(kwargs)
            else:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"未知模式: {mode}")

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    def _click_position(self, kwargs: dict) -> dict:
        """直接坐标点击"""
        x = kwargs.get("x")
        y = kwargs.get("y")
        if x is None or y is None:
            return format_error(TOOL_EXECUTION_ERROR, detail="position模式需要x和y坐标")

        offset = kwargs.get("offset", {"x": 0, "y": 0})
        final_x = x + offset["x"]
        final_y = y + offset["y"]

        pyautogui.click(
            x=final_x,
            y=final_y,
            button=kwargs.get("button", "left"),
            clicks=kwargs.get("clicks", 1),
            interval=kwargs.get("interval", 0)
        )

        return format_success({
            "clicked_at": (final_x, final_y),
            "original_pos": (x, y),
            "offset": offset,
            "button": kwargs.get("button", "left")
        }, msg=f"已点击 ({final_x}, {final_y})")

    def _click_by_color(self, kwargs: dict) -> dict:
        """通过颜色查找后点击"""
        from tools.pixel_color import PixelColor

        region = kwargs.get("region")
        target_color = kwargs.get("target_color")

        if not region or not target_color:
            return format_error(TOOL_EXECUTION_ERROR, detail="color模式需要region和target_color")

        # 使用PixelColor查找颜色
        finder = PixelColor()
        result = finder.run(
            action="find",
            region=region,
            color=target_color,
            tolerance=kwargs.get("tolerance", 5)
        )

        if not result.get("success") or not result["data"].get("found"):
            return format_error(TOOL_ELEMENT_NOT_FOUND,
                                detail=f"未找到颜色 RGB{target_color} 在区域 {region}")

        # 获取第一个匹配点
        match = result["data"]["first_match"]
        base_x, base_y = match["x"], match["y"]

        # 应用偏移
        offset = kwargs.get("offset", {"x": 0, "y": 0})
        final_x = base_x + offset["x"]
        final_y = base_y + offset["y"]

        # 执行点击
        pyautogui.click(
            x=final_x,
            y=final_y,
            button=kwargs.get("button", "left"),
            clicks=kwargs.get("clicks", 1),
            interval=kwargs.get("interval", 0)
        )

        return format_success({
            "clicked_at": (final_x, final_y),
            "found_at": (base_x, base_y),
            "offset": offset,
            "color_matched": target_color,
            "match_confidence": "high" if kwargs.get("tolerance", 5) < 10 else "medium",
            "total_matches": result["data"]["match_count"]
        }, msg=f"通过颜色定位点击成功，位置({final_x}, {final_y})，共找到{result['data']['match_count']}个匹配")

    def _click_with_verify(self, kwargs: dict) -> dict:
        """验证颜色后点击（防误触）"""
        x = kwargs.get("x")
        y = kwargs.get("y")
        verify_color = kwargs.get("verify_color")

        if None in [x, y, verify_color]:
            return format_error(TOOL_EXECUTION_ERROR,
                                detail="color_verify模式需要x, y和verify_color")

        # 验证当前颜色
        current = pyautogui.pixel(x, y)
        current_rgb = (current.red, current.green, current.blue)
        target_rgb = tuple(verify_color)

        tolerance = kwargs.get("tolerance", 5)
        diff = sum(abs(a - b) for a, b in zip(current_rgb, target_rgb, strict=False))

        if diff > tolerance * 3:
            return format_error(TOOL_ELEMENT_NOT_FOUND,
                                detail=f"颜色验证失败：期望RGB{target_rgb}，实际RGB{current_rgb}，差异{diff}")

        # 验证通过，执行点击
        offset = kwargs.get("offset", {"x": 0, "y": 0})
        final_x = x + offset["x"]
        final_y = y + offset["y"]

        pyautogui.click(
            x=final_x,
            y=final_y,
            button=kwargs.get("button", "left"),
            clicks=kwargs.get("clicks", 1)
        )

        return format_success({
            "clicked_at": (final_x, final_y),
            "verified_color": current_rgb,
            "color_diff": diff,
            "verification_passed": True
        }, msg=f"颜色验证通过，已点击 ({final_x}, {final_y})")
