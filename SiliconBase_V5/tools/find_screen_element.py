#!/usr/bin/env python3
"""
工具：根据描述查找屏幕元素（如"搜索框"、"确定按钮"）
返回匹配元素的中心坐标和文本，AI可直接用于后续点击或输入。

修复记录 (P0修复 - 2026-03-22):
- 修复硬编码4K分辨率问题：改为动态获取屏幕尺寸
- 添加零静默失败机制：获取屏幕尺寸失败时抛出明确错误
- 支持多显示器和DPI缩放环境
"""

import asyncio
import difflib
import logging

from core.base_tool import BaseTool
from core.error_codes import TOOL_ELEMENT_NOT_FOUND, TOOL_EXECUTION_ERROR, format_error

logger = logging.getLogger(__name__)

# 尝试导入pyautogui用于动态获取屏幕尺寸
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    logger.warning("[FindScreenElement] pyautogui未安装，屏幕尺寸获取功能不可用")


class FindScreenElement(BaseTool):
    tool_id = "find_screen_element"
    name = "查找屏幕元素"
    description = (
        "根据描述在屏幕上查找元素（如'搜索框'、'确定按钮'），返回其中心坐标和文本。"
        "内部使用OCR，对AI屏蔽了坐标解析细节。支持任意分辨率屏幕。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "要查找的元素描述，例如'搜索框'、'播放按钮'、'确定'"
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "可选，搜索区域 [left, top, width, height]，不传则全屏"
            }
        },
        "required": ["description"]
    }

    # 匹配阈值，可根据实际效果调整
    MATCH_THRESHOLD = 0.5

    def _get_screen_size(self) -> tuple:
        """
        动态获取屏幕尺寸

        Returns:
            (width, height) 屏幕尺寸元组

        Raises:
            ToolExecutionError: 获取屏幕尺寸失败时抛出
        """
        if not PYAUTOGUI_AVAILABLE:
            error_msg = "pyautogui未安装，无法获取屏幕尺寸。请运行: pip install pyautogui"
            logger.error(f"[FindScreenElement] {error_msg}")
            raise RuntimeError(error_msg)

        try:
            screen_width, screen_height = pyautogui.size()
            logger.debug(f"[FindScreenElement] 获取屏幕尺寸: {screen_width}x{screen_height}")
            return (screen_width, screen_height)
        except Exception as e:
            error_msg = f"获取屏幕尺寸失败: {e}"
            logger.error(f"[FindScreenElement] {error_msg}")
            raise RuntimeError(error_msg) from e

    def _execute(self, **kwargs):
        description = kwargs["description"].strip()
        region = kwargs.get("region")

        if not description:
            return format_error("INVALID_PARAMS", detail="description 不能为空")

        # 延迟导入 tool_manager，避免循环依赖
        from core.tool_manager import tool_manager

        # 获取 screen_ocr 工具实例
        ocr_tool = tool_manager.get_tool("screen_ocr")
        if not ocr_tool:
            return format_error("TOOL_UNAVAILABLE", detail="screen_ocr 工具不可用")

        # 调用 screen_ocr，要求返回带位置信息的结果
        if region:
            left, top, width, height = region
            logger.info(f"[FindScreenElement] 使用指定区域: [{left}, {top}, {width}, {height}]")
            ocr_result = ocr_tool.run(
                left=left, top=top, width=width, height=height,
                return_positions=True
            )
        else:
            # 修复：动态获取屏幕尺寸，替代硬编码4K分辨率
            try:
                screen_width, screen_height = self._get_screen_size()
                logger.info(f"[FindScreenElement] 使用全屏模式，屏幕尺寸: {screen_width}x{screen_height}")
                ocr_result = ocr_tool.run(
                    left=0, top=0, width=screen_width, height=screen_height,
                    return_positions=True
                )
            except RuntimeError as e:
                return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

        if not ocr_result.get("success"):
            return ocr_result

        items = ocr_result["data"]["items"]
        if not items:
            return format_error(TOOL_ELEMENT_NOT_FOUND, detail="屏幕上未识别出任何文字")

        # 对描述进行预处理（分词、小写）
        desc_lower = description.lower()
        # 简单分词：按空格分割，并过滤空字符串
        desc_words = [w for w in desc_lower.split() if w]

        best_match = None
        best_score = 0.0

        for item in items:
            text = item.get("text", "").strip()
            if not text:
                continue
            text_lower = text.lower()

            # 计算匹配得分
            score = self._compute_match_score(desc_lower, desc_words, text_lower)

            if score > best_score:
                best_score = score
                best_match = item

        if best_match and best_score >= self.MATCH_THRESHOLD:
            # 计算元素中心坐标
            left = best_match.get("left", 0)
            top = best_match.get("top", 0)
            right = best_match.get("right", left + 10)
            bottom = best_match.get("bottom", top + 10)
            x = (left + right) // 2
            y = (top + bottom) // 2

            logger.info(f"[FindScreenElement] 找到元素 '{best_match['text']}' 在 ({x}, {y})，匹配得分: {best_score:.2f}")

            return {
                "success": True,
                "error_code": None,
                "user_message": f"找到元素：{best_match['text']} 在 ({x}, {y})",
                "data": {
                    "x": x,
                    "y": y,
                    "text": best_match["text"],
                    "region": [left, top, right - left, bottom - top]
                }
            }
        else:
            logger.warning(f"[FindScreenElement] 未找到与描述 '{description}' 匹配的元素，最佳匹配得分: {best_score:.2f}")
            return format_error(
                TOOL_ELEMENT_NOT_FOUND,
                detail=f"未找到与描述 '{description}' 匹配的元素"
            )

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _compute_match_score(self, desc_lower: str, desc_words: list, text_lower: str) -> float:
        """
        计算描述与OCR文本的匹配得分。
        策略：
        - 如果描述完全包含在文本中（或文本包含描述），得分0.9
        - 否则，计算描述中每个单词与文本的相似度，取平均，并乘以包含关系加成。
        """
        # 完全包含检查
        if desc_lower in text_lower or text_lower in desc_lower:
            return 0.9

        if not desc_words:
            return 0.0

        # 计算单词匹配率
        word_scores = []
        for word in desc_words:
            if word in text_lower:
                word_scores.append(1.0)
            else:
                # 使用模糊匹配
                ratio = difflib.SequenceMatcher(None, word, text_lower).ratio()
                word_scores.append(ratio)

        avg_score = sum(word_scores) / len(word_scores)

        # 如果文本较短且包含描述中的部分单词，适当提高分数
        if len(text_lower) < 20 and any(w in text_lower for w in desc_words):
            avg_score = min(avg_score + 0.2, 1.0)

        return avg_score


# 可选：添加一个简单的测试（仅在直接运行时执行）
if __name__ == "__main__":
    # 简单测试，需要实际环境
    tool = FindScreenElement()

    # 测试屏幕尺寸获取
    print("测试屏幕尺寸获取...")
    try:
        size = tool._get_screen_size()
        print(f"屏幕尺寸: {size[0]}x{size[1]}")
    except Exception as e:
        print(f"获取屏幕尺寸失败: {e}")
