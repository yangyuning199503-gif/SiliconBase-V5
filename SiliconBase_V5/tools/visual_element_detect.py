#!/usr/bin/env python3
"""
原子工具：视觉元素检测（Visual Grounding）
基于视觉模型直接分析截图像素，识别 UI 元素并返回像素坐标。
与 visual_understand 的区别：后者描述"是什么"，此工具定位"在哪"。

技术原理：
- 在截图上叠加半透明坐标网格线作为视觉参考
- 要求模型以结构化 JSON 返回元素名称、类型、中心坐标
- 支持归一化坐标（0-1000）自动换算为实际像素
"""
import asyncio
import base64
import io
import json
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.providers.ai_provider_factory import AIProviderFactory

# 复用 visual_understand 的 GPU 保护机制
VISION_MODEL_TIMEOUT = 45
VISION_MAX_RETRIES = 1
_vision_gpu_semaphore = threading.Semaphore(1)


class VisualElementDetect(BaseTool):
    """
    视觉元素检测工具 - 让 AI "看到" UI 元素的像素坐标
    """
    tool_id = "visual_element_detect"
    tool_owner = "system"
    name = "视觉元素检测"
    description = (
        "使用视觉模型分析屏幕截图，识别所有可见的UI元素（按钮、输入框、链接、图标、菜单等），"
        "返回每个元素的名称、类型、中心像素坐标(x,y)。"
        "适用于网页、游戏、自绘界面等无法通过UI自动化获取元素的场景。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "要查找的元素描述，如'播放按钮'、'搜索输入框'。为空则返回所有可见元素"
            },
            "image_source": {
                "type": "string",
                "default": "screenshot",
                "description": "图片来源：screenshot（截图）或 path（文件路径）"
            },
            "image_path": {
                "type": "string",
                "description": "图片路径（当image_source为path时）"
            },
            "draw_grid": {
                "type": "boolean",
                "default": True,
                "description": "是否在截图上绘制坐标网格线辅助模型定位（推荐开启）"
            }
        }
    }

    @property
    def MODEL(self):
        """从配置读取视觉模型"""
        model = config.get("ai.vision.model")
        if model:
            return model
        model = config.get("ai.vision.model") or config.get("ai.vision_model")
        if model:
            return model
        default_backend = config.get("ai.vision.default_backend", "ollama-vision")
        model = config.get(f"ai.vision.backends.{default_backend}.model")
        if model:
            return model
        model = config.get("model_name")
        if model and "vl" in model.lower():
            return model
        raise Exception(
            "视觉模型未配置。请在 config/global.yaml 中设置: ai.vision.model: qwen3-vl:2b"
        )

    def _execute(self, **kwargs) -> dict:
        """同步入口 - 受 GPU 并发锁保护"""
        acquired = _vision_gpu_semaphore.acquire(timeout=VISION_MODEL_TIMEOUT)
        if not acquired:
            return format_error(TOOL_EXECUTION_ERROR, detail="视觉模型正忙，请稍后再试")
        try:
            return self._do_detect(**kwargs)
        finally:
            _vision_gpu_semaphore.release()

    async def _execute_async(self, **kwargs) -> dict:
        """异步入口 - 通过线程池桥接获取 GPU 锁，防止与同步路径竞争"""
        loop = asyncio.get_running_loop()
        acquired = await loop.run_in_executor(
            None, _vision_gpu_semaphore.acquire, True, VISION_MODEL_TIMEOUT
        )
        if not acquired:
            return format_error(TOOL_EXECUTION_ERROR, detail="视觉模型正忙，请稍后再试")
        try:
            # 同步逻辑在线程池中执行，避免阻塞事件循环
            return await loop.run_in_executor(None, lambda: self._do_detect(**kwargs))
        finally:
            _vision_gpu_semaphore.release()

    def _do_detect(self, **kwargs) -> dict:
        target = kwargs.get("target", "")
        image_source = kwargs.get("image_source", "screenshot")
        image_path = kwargs.get("image_path", "")
        draw_grid = kwargs.get("draw_grid", True)

        # 获取图像
        import gc
        if image_source == "screenshot":
            img, width, height = self._capture_screenshot()
        elif image_source == "path":
            if not image_path:
                return format_error(INVALID_PARAMS, detail="image_path 不能为空")
            with Image.open(image_path) as _img:
                img = _img.copy()
                width, height = img.size
        else:
            with Image.open(io.BytesIO(base64.b64decode(image_source))) as _img:
                img = _img.copy()
                width, height = img.size

        # 【P0修复】图像完整性验证
        if width <= 0 or height <= 0 or width > 10000 or height > 10000:
            if hasattr(img, 'close'):
                img.close()
            del img
            gc.collect()
            return format_error(TOOL_EXECUTION_ERROR, detail=f"图像尺寸异常: {width}x{height}")

        # 可选：在截图上绘制网格线，帮助模型建立坐标系概念
        if draw_grid:
            img = self._draw_coordinate_grid(img)

        image_b64 = self._pil_to_base64(img)

        # 构建坐标识别 prompt
        question = self._build_prompt(target, width, height)

        # 调用视觉模型
        response = self._call_vision_model(image_b64, question)
        if not response:
            return format_error(TOOL_EXECUTION_ERROR, detail="视觉模型返回空响应")

        # 解析模型返回的 JSON/坐标
        elements = self._parse_response(response, width, height)

        # 生成人类可读的摘要
        summary_lines = [f"屏幕尺寸: {width}x{height} | 识别到 {len(elements)} 个UI元素"]
        for el in elements[:15]:
            label = el.get("name") or el.get("label") or "未命名"
            x, y = el.get("x", 0), el.get("y", 0)
            el_type = el.get("type", "unknown")
            summary_lines.append(f"  [{el_type}] {label} -> 坐标({x}, {y})")
        if len(elements) > 15:
            summary_lines.append(f"  ... 还有 {len(elements) - 15} 个元素")

        summary = "\n".join(summary_lines)

        # 【P0修复】释放PIL图像
        img.close()
        del img
        gc.collect()

        return {
            "success": True,
            "user_message": summary,
            "data": {
                "screen_width": width,
                "screen_height": height,
                "element_count": len(elements),
                "elements": elements,
                "raw_response": response,
                "summary": summary
            }
        }

    def _capture_screenshot(self) -> tuple:
        """截图并返回 PIL Image + 尺寸"""
        import gc

        from core.vision.safe_screenshot import safe_screenshot_to_pil
        img = safe_screenshot_to_pil(monitor=1)
        if img is None:
            raise RuntimeError("截图失败")

        # 【P0修复】图像完整性验证
        if img.width <= 0 or img.height <= 0 or img.width > 10000 or img.height > 10000:
            img.close()
            del img
            gc.collect()
            raise RuntimeError(f"截图尺寸异常: {img.width}x{img.height}")

        return img, img.width, img.height

    def _draw_coordinate_grid(self, img: Image.Image, step: int = 100) -> Image.Image:
        """
        在截图上绘制半透明网格线和坐标标记，帮助视觉模型建立坐标概念。
        不影响实际像素坐标换算（网格是辅助线）。
        """
        draw = ImageDraw.Draw(img, 'RGBA')
        width, height = img.size

        # 绘制垂直线（每 step 像素一条）
        for x in range(step, width, step):
            draw.line([(x, 0), (x, height)], fill=(255, 0, 0, 40), width=1)
            # 顶部标注 x 值（每 200px 标一个，避免太密）
            if x % 200 == 0:
                draw.text((x + 2, 2), str(x), fill=(255, 0, 0, 120))

        # 绘制水平线
        for y in range(step, height, step):
            draw.line([(0, y), (width, y)], fill=(0, 255, 0, 40), width=1)
            if y % 200 == 0:
                draw.text((2, y + 2), str(y), fill=(0, 255, 0, 120))

        # 在四角标注坐标系说明
        hint = "Coords: TL(0,0)"
        draw.text((5, height - 20), hint, fill=(255, 255, 255, 180))

        return img

    def _pil_to_base64(self, img: Image.Image) -> str:
        buffer = io.BytesIO()
        try:
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()
        finally:
            buffer.close()

    def _build_prompt(self, target: str, width: int, height: int) -> str:
        """构建坐标识别专用 prompt"""
        base = (
            f"这是一张 {width}x{height} 像素的屏幕截图。"
            "截图上有红色垂直网格线和绿色水平网格线作为坐标参考，"
            "左上角是原点 (0,0)，右下角是最大值。\n\n"
        )

        if target:
            base += (
                f"请找到与 '{target}' 相关的所有 UI 元素（按钮、输入框、图标、链接等）。\n"
                f"对每个元素，返回它的名称、类型、中心像素坐标(x,y)。\n"
            )
        else:
            base += (
                "请识别截图中所有可见的可交互 UI 元素，包括：\n"
                "- 按钮（如'播放'、'登录'、'确认'）\n"
                "- 输入框/搜索框\n"
                "- 链接/标签\n"
                "- 图标/菜单项\n"
                "- 下拉框/复选框\n\n"
                "对每个元素，返回：名称、类型、中心像素坐标(x,y)。\n"
            )

        base += (
            "\n坐标必须是截图的绝对像素坐标（不是归一化值）。\n"
            "使用以下严格的 JSON 数组格式返回，不要添加任何解释文字：\n"
            "```json\n"
            "[\n"
            '  {"name": "播放", "type": "button", "x": 520, "y": 680},\n'
            '  {"name": "搜索框", "type": "input", "x": 400, "y": 120},\n'
            '  {"name": "设置", "type": "icon", "x": 1200, "y": 50}\n'
            "]\n"
            "```\n"
            "如果某个元素没有可见文字，name 可以描述其外观（如'齿轮图标'）。"
            "只返回截图中确实可见的元素，不要猜测。"
        )
        return base

    def _call_vision_model(self, image_b64: str, question: str) -> str:
        """调用视觉模型"""
        provider = AIProviderFactory.get_current_provider()
        if not provider.is_available():
            raise RuntimeError("AI Provider 不可用")

        provider_config = provider.get_config()
        provider_type = provider_config.get("provider", "unknown")
        model = self.MODEL

        # 构建消息
        if provider_type.lower() == "ollama":
            messages = [
                {
                    "role": "user",
                    "content": question,
                    "images": [image_b64]
                }
            ]
        else:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                    ]
                }
            ]

        response = provider.chat(messages, model=model, max_tokens=1024, timeout=60)
        return response or ""

    def _parse_response(self, response: str, width: int, height: int) -> list:
        """解析模型返回的 JSON 坐标"""
        elements = []

        # 尝试提取 JSON 代码块
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接找方括号数组
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
            json_str = json_match.group(0) if json_match else response

        try:
            data = json.loads(json_str)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    el = {
                        "name": item.get("name", ""),
                        "type": item.get("type", item.get("element_type", "unknown")),
                        "x": self._normalize_coordinate(item.get("x", 0), width),
                        "y": self._normalize_coordinate(item.get("y", 0), height),
                        "label": item.get("label", item.get("text", ""))
                    }
                    elements.append(el)
            elif isinstance(data, dict):
                # 有些模型可能返回 {"elements": [...]}
                arr = data.get("elements", data.get("items", data.get("results", [])))
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    elements.append({
                        "name": item.get("name", ""),
                        "type": item.get("type", "unknown"),
                        "x": self._normalize_coordinate(item.get("x", 0), width),
                        "y": self._normalize_coordinate(item.get("y", 0), height),
                        "label": item.get("label", "")
                    })
        except json.JSONDecodeError:
            # 如果 JSON 解析失败，尝试正则提取坐标
            elements = self._fallback_parse(response)

        return elements

    def _normalize_coordinate(self, value, max_dim: int) -> int:
        """将坐标归一化：如果值在 0-1 之间，换算为像素；如果在 0-100 之间但远小于 max_dim，也换算"""
        if isinstance(value, str):
            value = value.strip().replace("px", "").replace(" ", "")
            try:
                value = float(value)
            except ValueError:
                return 0

        if isinstance(value, (int, float)):
            # 如果值很小（0-1.0），认为是归一化比例
            if 0 <= value <= 1.0 and max_dim > 100:
                return int(value * max_dim)
            # 如果值在 0-100 且 max_dim 很大，也可能是百分比
            if 0 < value <= 100 and max_dim > 1000 and value < max_dim / 10:
                return int(value / 100 * max_dim)
            return int(value)
        return 0

    def _fallback_parse(self, response: str) -> list:
        """JSON 解析失败时的降级方案：用正则提取坐标对"""
        elements = []
        # 匹配模式：名称...坐标(x,y) 或 x=123, y=456
        pattern = re.compile(
            r'([\u4e00-\u9fa5\w\s]{1,20})[^\d]*?\(?\s*x\s*[=:]\s*(\d+)[,\s]+y\s*[=:]\s*(\d+)\s*\)?',
            re.IGNORECASE
        )
        for match in pattern.finditer(response):
            name = match.group(1).strip()
            x = int(match.group(2))
            y = int(match.group(3))
            elements.append({"name": name, "type": "unknown", "x": x, "y": y, "label": ""})
        return elements


# 兼容别名
VisualElementDetectTool = VisualElementDetect
