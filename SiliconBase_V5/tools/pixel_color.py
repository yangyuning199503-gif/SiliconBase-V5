# tools/pixel_color.py
#!/usr/bin/env python3
"""
像素颜色工具 - 视觉AI的辅助组件（线程安全版本）

【架构定位】
此工具是 visual_understand 的辅助工具，用于：
1. 精确颜色获取（单点/区域）- 轻量级，不竞争AI资源
2. 作为AI视觉分析的补充 - AI看"是什么"，此工具测"颜色值"

【蓝屏修复】
- _find_color和_analyze_region使用safe_screenshot_to_numpy
- 消除MSS多实例冲突

【使用建议】
- 需要颜色精确值时使用此工具
- 需要理解屏幕内容时使用 visual_understand
- 两者互补，不竞争
"""
import asyncio
import time

import numpy as np
import pyautogui

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, TOOL_TIMEOUT, format_error, format_success
from core.vision.dpi import get_screen_scale_factor
from core.vision.safe_screenshot import safe_screenshot_to_numpy


class PixelColor(BaseTool):
    tool_id = "pixel_color"
    name = "像素颜色操作"
    description = "【视觉AI辅助】精确颜色获取和匹配。用于获取指定坐标的精确RGB值，是visual_understand的补充工具。如需AI理解屏幕内容，请使用visual_understand。"
    version = "2.0.0-threadsafe"
    timeout = 30

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "match", "wait", "find", "analyze", "assist_vision"],
                "description": "操作类型：get获取颜色, match匹配颜色, wait等待变化, find查找颜色, analyze区域分析, assist_vision辅助视觉AI"
            },
            "x": {"type": "integer", "description": "X坐标（get/match时需要）"},
            "y": {"type": "integer", "description": "Y坐标（get/match时需要）"},
            "color": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 255},
                "minItems": 3,
                "maxItems": 3,
                "description": "目标RGB颜色值 [R, G, B]"
            },
            "region": {
                "type": "object",
                "description": "操作区域（find/analyze时需要）",
                "properties": {
                    "left": {"type": "integer"},
                    "top": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"}
                }
            },
            "tolerance": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "maximum": 255,
                "description": "颜色容差（0-255），越大匹配越宽松"
            },
            "timeout": {
                "type": "number",
                "default": 10,
                "description": "等待超时时间（秒），仅wait操作"
            },
            "interval": {
                "type": "number",
                "default": 0.1,
                "description": "检测间隔（秒），仅wait操作"
            },
            "visual_context": {
                "type": "object",
                "description": "视觉AI提供的上下文（assist_vision时使用）"
            }
        },
        "required": ["action"]
    }

    def _execute(self, **kwargs) -> dict:
        action = kwargs["action"]

        try:
            if action == "get":
                return self._get_color(kwargs.get("x"), kwargs.get("y"))
            elif action == "match":
                return self._match_color(
                    kwargs.get("x"), kwargs.get("y"),
                    kwargs.get("color"), kwargs.get("tolerance", 0)
                )
            elif action == "wait":
                return self._wait_color(
                    kwargs.get("x"), kwargs.get("y"),
                    kwargs.get("color"), kwargs.get("tolerance", 0),
                    kwargs.get("timeout", 10), kwargs.get("interval", 0.1)
                )
            elif action == "find":
                return self._find_color(
                    kwargs.get("region"), kwargs.get("color"),
                    kwargs.get("tolerance", 0)
                )
            elif action == "analyze":
                return self._analyze_region(kwargs.get("region"))
            elif action == "assist_vision":
                return self._assist_vision(kwargs.get("visual_context", {}))
            else:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"未知操作: {action}")

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _get_color(self, x: int, y: int) -> dict:
        """获取指定坐标的颜色 - 使用pyautogui（轻量，不占用MSS）"""
        if x is None or y is None:
            return format_error(TOOL_EXECUTION_ERROR, detail="get操作需要x和y坐标")

        # 使用PyAutoGUI获取颜色（最轻量，不创建MSS实例）
        color = pyautogui.pixel(x, y)
        rgb = (color.red, color.green, color.blue)

        # 获取周围像素用于上下文
        neighbors = self._get_neighbor_colors(x, y)

        return format_success({
            "position": (x, y),
            "rgb": rgb,
            "hex": "#{:02x}{:02x}{:02x}".format(*rgb),
            "neighbors": neighbors
        }, msg=f"位置({x}, {y})的颜色: RGB{rgb}")

    def _match_color(self, x: int, y: int, target_color: list[int], tolerance: int) -> dict:
        """匹配指定坐标的颜色 - 使用pyautogui"""
        if None in [x, y, target_color]:
            return format_error(TOOL_EXECUTION_ERROR, detail="match操作需要x, y和color")

        actual_color = pyautogui.pixel(x, y)
        actual_rgb = (actual_color.red, actual_color.green, actual_color.blue)
        target_tuple = tuple(target_color)

        # 计算色差
        diff = sum(abs(a - b) for a, b in zip(actual_rgb, target_tuple, strict=False))
        max_diff = tolerance * 3
        matched = diff <= max_diff

        return format_success({
            "matched": matched,
            "target": target_tuple,
            "actual": actual_rgb,
            "difference": diff,
            "tolerance": tolerance,
            "position": (x, y)
        }, msg=f"颜色{'匹配' if matched else '不匹配'} | 目标{target_tuple} 实际{actual_rgb}")

    def _wait_color(self, x: int, y: int, target_color: list[int],
                    tolerance: int, timeout: float, interval: float) -> dict:
        """等待指定位置变为目标颜色 - 使用pyautogui轮询"""
        if None in [x, y, target_color]:
            return format_error(TOOL_EXECUTION_ERROR, detail="wait操作需要x, y和color")

        start_time = time.time()
        target_tuple = tuple(target_color)
        check_count = 0

        while time.time() - start_time < timeout:
            if self.is_interrupted():
                return format_error(TOOL_EXECUTION_ERROR, detail="操作被中断")

            current = pyautogui.pixel(x, y)
            current_rgb = (current.red, current.green, current.blue)
            check_count += 1

            # 检查是否匹配
            diff = sum(abs(a - b) for a, b in zip(current_rgb, target_tuple, strict=False))
            if diff <= tolerance * 3:
                elapsed = time.time() - start_time
                return format_success({
                    "success": True,
                    "final_color": current_rgb,
                    "wait_time": round(elapsed, 2),
                    "checks": check_count,
                    "position": (x, y)
                }, msg=f"颜色变化检测成功，耗时{elapsed:.2f}秒")

            time.sleep(interval)

        # 超时
        final = pyautogui.pixel(x, y)
        return format_error(TOOL_TIMEOUT,
                            detail=f"等待颜色变化超时({timeout}秒)，最终颜色: RGB{(final.red, final.green, final.blue)}")

    def _find_color(self, region: dict, target_color: list[int], tolerance: int) -> dict:
        """在区域内查找指定颜色 - 【蓝屏修复】使用safe_screenshot_to_numpy"""
        if not region or not target_color:
            return format_error(TOOL_EXECUTION_ERROR, detail="find操作需要region和color")

        # 【蓝屏修复】使用线程安全截图
        img_array = safe_screenshot_to_numpy(
            region={
                "left": region["left"],
                "top": region["top"],
                "width": region["width"],
                "height": region["height"]
            }
        )

        if img_array is None:
            return format_error(TOOL_EXECUTION_ERROR, detail="截图失败，无法查找颜色")

        # 向量化搜索
        target = np.array(target_color)

        if tolerance == 0:
            # 精确匹配
            mask = np.all(img_array == target, axis=2)
        else:
            # 容差匹配
            diff = np.abs(img_array.astype(int) - target)
            mask = np.all(diff <= tolerance, axis=2)

        # 获取匹配位置
        matches = np.argwhere(mask)

        if len(matches) == 0:
            return format_success({
                "found": False,
                "matches": [],
                "total_checked": img_array.shape[0] * img_array.shape[1]
            }, msg="未找到匹配颜色")

        # 转换为绝对坐标（物理下标 → 逻辑坐标）
        scale = get_screen_scale_factor()
        results = []
        for y, x in matches[:10]:  # 最多返回10个
            abs_x = region["left"] + int(x / scale)
            abs_y = region["top"] + int(y / scale)
            results.append({"x": int(abs_x), "y": int(abs_y), "rel": (int(x / scale), int(y / scale))})

        return format_success({
            "found": True,
            "match_count": len(matches),
            "matches": results,
            "first_match": results[0] if results else None,
            "region": region
        }, msg=f"找到 {len(matches)} 个匹配点，首个位置: ({results[0]['x']}, {results[0]['y']})")

    def _analyze_region(self, region: dict) -> dict:
        """分析区域颜色统计信息 - 【蓝屏修复】使用safe_screenshot_to_numpy"""
        if not region:
            return format_error(TOOL_EXECUTION_ERROR, detail="analyze操作需要region")

        # 【蓝屏修复】使用线程安全截图
        img_array = safe_screenshot_to_numpy(
            region={
                "left": region["left"],
                "top": region["top"],
                "width": region["width"],
                "height": region["height"]
            }
        )

        if img_array is None:
            return format_error(TOOL_EXECUTION_ERROR, detail="截图失败，无法分析区域")

        # 统计信息
        mean_color = img_array.mean(axis=(0, 1)).astype(int).tolist()
        std_color = img_array.std(axis=(0, 1)).astype(int).tolist()

        # 简化直方图（每通道分4档）
        histograms = []
        for i in range(3):
            hist, _ = np.histogram(img_array[:, :, i], bins=4, range=(0, 256))
            histograms.append(hist.tolist())

        # 检测主要颜色（使用无SciPy实现）
        try:
            from core.color_utils import dominant_colors_kmeans
            pixels = img_array.reshape(-1, 3)
            centroids = dominant_colors_kmeans(pixels, k=min(5, len(pixels)))
            dominant_colors = [list(map(int, c)) for c in centroids]
        except Exception:
            # 如果color_utils不可用，使用简单均值
            dominant_colors = [mean_color]

        return format_success({
            "mean_rgb": mean_color,
            "std_rgb": std_color,
            "dominant_colors": dominant_colors,
            "brightness": int(sum(mean_color) / 3),
            "color_variance": int(sum(std_color)),
            "histograms": {
                "red": histograms[0],
                "green": histograms[1],
                "blue": histograms[2]
            }
        }, msg=f"区域分析完成，平均颜色RGB{mean_color}，主导颜色{len(dominant_colors)}种")

    def _assist_vision(self, visual_context: dict) -> dict:
        """
        辅助视觉AI分析

        当visual_understand识别出某个UI元素后，
        可用此功能获取该元素的精确颜色信息。

        Args:
            visual_context: {
                "element_type": "button|text|icon",
                "position": {"x": int, "y": int},
                "description": str  # AI的描述
            }
        """
        position = visual_context.get("position", {})
        x = position.get("x")
        y = position.get("y")

        if x is None or y is None:
            return format_error(TOOL_EXECUTION_ERROR, detail="assist_vision需要position包含x和y")

        # 获取该位置的精确颜色
        color_result = self._get_color(x, y)

        if not color_result.get("success"):
            return color_result

        # 添加AI上下文
        data = color_result.get("data", {})
        data["visual_context"] = {
            "original_description": visual_context.get("description", ""),
            "element_type": visual_context.get("element_type", "unknown"),
            "note": "此颜色数据辅助visual_understand的识别结果"
        }

        return format_success(data, msg=f"视觉AI辅助分析完成 | 位置({x}, {y}) | 颜色RGB{data.get('rgb')}")

    def _get_neighbor_colors(self, x: int, y: int, radius: int = 1) -> list[dict]:
        """获取周围像素颜色 - 使用pyautogui"""
        neighbors = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                try:
                    nx, ny = x + dx, y + dy
                    c = pyautogui.pixel(nx, ny)
                    neighbors.append({
                        "offset": (dx, dy),
                        "rgb": (c.red, c.green, c.blue),
                        "pos": (nx, ny)
                    })
                except Exception:
                    pass
        return neighbors
