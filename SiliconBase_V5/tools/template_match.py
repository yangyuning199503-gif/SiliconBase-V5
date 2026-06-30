#!/usr/bin/env python3
"""
原子工具：模板匹配
使用OpenCV进行图像模板匹配（BSD协议，无版权风险）

功能：
- 在屏幕上查找指定图片模板
- 返回匹配位置和相似度
- 支持多尺度匹配（适应不同分辨率）

适用场景：
- 点击特定图标（保存为模板后匹配）
- 检测UI元素是否存在
- 游戏中识别特定元素
"""

import asyncio

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    cv2 = None  # type: ignore[assignment]
    CV2_AVAILABLE = False
from pathlib import Path

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_ELEMENT_NOT_FOUND, TOOL_EXECUTION_ERROR, format_error
from core.vision.safe_screenshot import safe_screenshot_to_numpy


class TemplateMatch(BaseTool):
    """
    模板匹配工具 - 基于OpenCV（BSD协议，无版权风险）
    """
    tool_id = "template_match"
    name = "模板匹配"
    description = "在屏幕上查找指定图片模板，返回匹配位置（基于OpenCV，无版权风险）"
    input_schema = {
        "type": "object",
        "properties": {
            "template_path": {
                "type": "string",
                "description": "模板图片路径（如 templates/wechat_icon.png）"
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "搜索区域 [left, top, width, height]，不传则全屏"
            },
            "threshold": {
                "type": "number",
                "minimum": 0.1,
                "maximum": 1.0,
                "default": 0.8,
                "description": "匹配阈值（0-1），越高越严格"
            },
            "multi_scale": {
                "type": "boolean",
                "default": True,
                "description": "是否多尺度匹配（适应不同大小）"
            },
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "最大返回结果数"
            }
        },
        "required": ["template_path"]
    }

    def _execute(self, **kwargs) -> dict:
        template_path = kwargs.get("template_path")
        region = kwargs.get("region")
        threshold = kwargs.get("threshold", 0.8)
        multi_scale = kwargs.get("multi_scale", True)
        max_results = kwargs.get("max_results", 5)

        if not template_path:
            return format_error(INVALID_PARAMS, detail="template_path 不能为空")

        if not CV2_AVAILABLE:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail="OpenCV (cv2) 未安装，模板匹配功能不可用"
            )

        # 检查模板文件
        template_file = Path(template_path)
        if not template_file.is_absolute():
            # 相对于 templates/ 目录
            template_file = Path("templates") / template_path

        if not template_file.exists():
            return format_error(
                TOOL_ELEMENT_NOT_FOUND,
                detail=f"模板文件不存在: {template_file}"
            )

        try:
            # 读取模板图片
            template = cv2.imread(str(template_file))
            if template is None:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail="无法读取模板图片"
                )

            # 转换为灰度图（提高匹配速度和准确度）
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            template_h, template_w = template_gray.shape[:2]

            # 截图 - 【蓝屏修复】使用线程安全截图
            if region:
                monitor_region = {
                    "left": region[0],
                    "top": region[1],
                    "width": region[2],
                    "height": region[3]
                }
                img_rgb = safe_screenshot_to_numpy(monitor=1, region=monitor_region)
            else:
                img_rgb = safe_screenshot_to_numpy(monitor=1)

            if img_rgb is None:
                return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")

            # 转换为OpenCV格式（RGB->BGR->Gray）
            img = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 执行匹配
            if multi_scale:
                matches = self._match_multi_scale(
                    img_gray, template_gray, threshold, max_results
                )
            else:
                matches = self._match_single_scale(
                    img_gray, template_gray, threshold, max_results
                )

            if not matches:
                return format_error(
                    TOOL_ELEMENT_NOT_FOUND,
                    detail=f"未找到匹配模板（阈值: {threshold}）"
                )

            # 转换为绝对坐标 - 【蓝屏修复】使用固定偏移避免未定义变量
            offset_x = region[0] if region else 0
            offset_y = region[1] if region else 0

            results = []
            for match in matches:
                results.append({
                    "x": int(offset_x + match["x"]),
                    "y": int(offset_y + match["y"]),
                    "width": int(match["width"]),
                    "height": int(match["height"]),
                    "confidence": round(match["confidence"], 3),
                    "center": {
                        "x": int(offset_x + match["x"] + match["width"] // 2),
                        "y": int(offset_y + match["y"] + match["height"] // 2)
                    }
                })

            best = results[0]
            return {
                "success": True,
                "error_code": None,
                "user_message": f"找到 {len(results)} 个匹配，最佳位置: ({best['center']['x']}, {best['center']['y']})，置信度: {best['confidence']}",
                "data": {
                    "found": True,
                    "match_count": len(results),
                    "matches": results,
                    "best_match": best
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"模板匹配失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _match_single_scale(self, image: np.ndarray, template: np.ndarray,
                           threshold: float, max_results: int) -> list[dict]:
        """单尺度匹配"""
        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)

        # 获取所有匹配位置
        locations = np.where(result >= threshold)
        scores = result[locations]

        # 按分数排序
        matches = []
        for y, x, score in zip(locations[0], locations[1], scores, strict=False):
            matches.append({
                "x": int(x),
                "y": int(y),
                "width": template.shape[1],
                "height": template.shape[0],
                "confidence": float(score)
            })

        # 按置信度排序，取前N个
        matches.sort(key=lambda m: m["confidence"], reverse=True)
        return matches[:max_results]

    def _match_multi_scale(self, image: np.ndarray, template: np.ndarray,
                          threshold: float, max_results: int) -> list[dict]:
        """多尺度匹配（适应不同大小）"""
        best_matches = []
        best_confidence = 0
        best_scale = 1.0

        # 尝试不同缩放比例
        for scale in [0.5, 0.75, 1.0, 1.25, 1.5]:
            # 缩放模板
            resized = cv2.resize(template, None, fx=scale, fy=scale)

            # 确保模板不大于图像
            if resized.shape[0] > image.shape[0] or resized.shape[1] > image.shape[1]:
                continue

            # 匹配
            result = cv2.matchTemplate(image, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_confidence and max_val >= threshold:
                best_confidence = max_val
                best_scale = scale
                best_matches = [{
                    "x": max_loc[0],
                    "y": max_loc[1],
                    "width": resized.shape[1],
                    "height": resized.shape[0],
                    "confidence": float(max_val),
                    "scale": scale
                }]

        # 如果找到匹配，再找其他相近位置
        if best_matches:
            resized = cv2.resize(template, None, fx=best_scale, fy=best_scale)
            result = cv2.matchTemplate(image, resized, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            matches = []
            for y, x in zip(locations[0], locations[1], strict=False):
                score = result[y, x]
                matches.append({
                    "x": int(x),
                    "y": int(y),
                    "width": resized.shape[1],
                    "height": resized.shape[0],
                    "confidence": float(score)
                })

            matches.sort(key=lambda m: m["confidence"], reverse=True)
            return matches[:max_results]

        return []
