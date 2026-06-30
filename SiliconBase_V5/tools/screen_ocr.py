#!/usr/bin/env python3
"""
原子工具：屏幕区域文字识别
【P1-001优化】延迟加载 + 支持配置切换后端
"""

import asyncio
import threading

from core.base_tool import BaseTool

from core.config import config
from core.vision.dpi import logical_to_physical, physical_to_logical
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger

# 【蓝屏修复】使用safe_screenshot替代mss


class ScreenOCR(BaseTool):
    """
    屏幕区域文字识别工具 - 支持多后端配置

    配置方式：修改 config/vision.yaml 中的 ocr 部分
    """
    tool_id = "screen_ocr"
    name = "屏幕区域文字识别"
    description = (
        "截取屏幕指定区域，识别其中的文字。"
        "支持 easyocr/vision_agent 后端，可通过 config/vision.yaml 配置切换"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "left": {"type": "integer", "minimum": 0},
            "top": {"type": "integer", "minimum": 0},
            "width": {"type": "integer", "minimum": 10},
            "height": {"type": "integer", "minimum": 10},
            "region": {
                "oneOf": [
                    {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                    {"type": "object", "properties": {
                        "left": {"type": "integer", "minimum": 0},
                        "top": {"type": "integer", "minimum": 0},
                        "width": {"type": "integer", "minimum": 10},
                        "height": {"type": "integer", "minimum": 10}
                    }, "required": ["left", "top", "width", "height"]}
                ]
            },
            "return_positions": {"type": "boolean", "default": False},
            "hwnd": {"type": "integer", "description": "可选，目标窗口句柄，用于 DPI 缩放"}
        },
        "anyOf": [
            {"required": ["left", "top", "width", "height"]},
            {"required": ["region"]}
        ]
    }

    _reader = None
    _reader_initialized = False
    _reader_error = None
    _easyocr_missing = False  # 【P0修复】标记 easyocr 是否缺失，避免反复初始化
    _current_backend = None
    _reader_lock = threading.Lock()  # 【蓝屏修复】防止多线程重复初始化 EasyOCR GPU 模型

    def _get_reader(self):
        """延迟初始化 OCR reader（支持配置热切换）"""
        ocr_config = config.get("ocr", {})
        default_engine = ocr_config.get("default_engine", "easyocr")

        # 如果后端变化，在锁外重置状态标记
        if self._current_backend != default_engine:
            with self._reader_lock:
                self.__class__._reader = None
                self.__class__._reader_initialized = False
                self.__class__._reader_error = None
                self.__class__._current_backend = default_engine

        if self._reader_initialized:
            if self._easyocr_missing:
                # 依赖缺失时直接返回 None，由调用方决定如何降级
                return None
            if self._reader_error:
                raise RuntimeError(f"OCR 初始化失败: {self._reader_error}")
            return self._reader

        # 【蓝屏修复】加锁防止多线程同时初始化 EasyOCR（尤其是 GPU 模式会重复加载 CUDA 模型）
        with self._reader_lock:
            # 双重检查：其他线程可能已在等待期间完成初始化
            if self._reader_initialized:
                if self._reader_error:
                    raise RuntimeError(f"OCR 初始化失败: {self._reader_error}")
                return self._reader

            # 根据配置选择后端
            if default_engine == "easyocr":
                return self._init_easyocr()
            elif default_engine == "vision_agent":
                return self._init_vision_agent()
            else:
                raise RuntimeError(f"不支持的 OCR 后端: {default_engine}")

    def _init_easyocr(self):
        """初始化 EasyOCR"""
        try:
            import easyocr
            ocr_config = config.get("ocr", {})
            engine_config = ocr_config.get("engines", {}).get("easyocr", {})
            languages = engine_config.get("languages", ["ch_sim", "en"])
            gpu = engine_config.get("gpu", False)

            self.__class__._reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
            self.__class__._reader_initialized = True
            self.__class__._current_backend = "easyocr"
            return self._reader
        except ImportError as e:
            self.__class__._reader_error = f"easyocr 未安装: {e}"
            self.__class__._reader_initialized = True
            self.__class__._easyocr_missing = True
            logger.warning(f"[ScreenOCR] easyocr 未安装，OCR 功能将不可用: {e}")
            return None
        except Exception as e:
            self.__class__._reader_error = str(e)
            self.__class__._reader_initialized = True
            raise RuntimeError(f"EasyOCR 初始化失败: {e}") from e

    def _init_vision_agent(self):
        """初始化 Vision Agent 作为 OCR 后端"""
        try:
            ocr_config = config.get("ocr", {})
            engine_config = ocr_config.get("engines", {}).get("vision_agent", {})
            provider = engine_config.get("provider", "ollama")
            model = engine_config.get("model")
            if not model:
                model = config.get("ai.vision.model")
            if not model:
                model = config.get("ai.vision.model") or config.get("ai.vision_model")
            if not model:
                default_backend = config.get("ai.vision.default_backend", "ollama-vision")
                model = config.get(f"ai.vision.backends.{default_backend}.model")
            if not model:
                model = "qwen3-vl:2b"

            self.__class__._reader = VisionAgentScreenOCR(provider, model)
            self.__class__._reader_initialized = True
            self.__class__._current_backend = "vision_agent"
            return self._reader
        except Exception as e:
            self.__class__._reader_error = str(e)
            self.__class__._reader_initialized = True
            raise RuntimeError(f"Vision Agent OCR 初始化失败: {e}") from e

    async def _execute_async(self, **kwargs):
        """
        异步执行屏幕OCR - 显式桥接到线程池

        OCR 推理（easyocr.Reader.readtext）是 CPU 密集型操作，无法真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs):
        # 检查中断
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "操作被用户中断",
                "data": None
            }

        # 【蓝屏修复】截图功能由safe_screenshot提供

        # 提取区域坐标
        left = kwargs.get("left")
        top = kwargs.get("top")
        width = kwargs.get("width")
        height = kwargs.get("height")
        region = kwargs.get("region")

        if region is not None:
            if isinstance(region, (list, tuple)) and len(region) == 4:
                left, top, width, height = region
            elif isinstance(region, dict):
                left = region.get("left")
                top = region.get("top")
                width = region.get("width")
                height = region.get("height")
            else:
                return format_error(INVALID_PARAMS, detail="region 格式错误")

        if None in (left, top, width, height):
            return format_error(INVALID_PARAMS, detail="缺少必要的坐标参数")

        return_positions = kwargs.get("return_positions", False)
        kwargs.get("hwnd")

        # DPI 缩放：逻辑坐标 → 物理像素（截图用）
        physical_region = logical_to_physical({
            "left": left,
            "top": top,
            "width": width,
            "height": height
        })
        scaled_left = physical_region["left"]
        scaled_top = physical_region["top"]
        scaled_width = physical_region["width"]
        scaled_height = physical_region["height"]

        try:
            reader = self._get_reader()
        except RuntimeError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"OCR 初始化失败: {e}")

        try:
            # 【P0终极修复】支持外部传入 numpy 数组，避免重复截图
            image_data = kwargs.get("image_data")
            if image_data is not None:
                img_rgb = image_data
            else:
                # 【蓝屏修复】使用线程安全截图
                import gc

                from core.vision.safe_screenshot import safe_screenshot_to_numpy
                monitor_region = {"left": scaled_left, "top": scaled_top,
                                 "width": scaled_width, "height": scaled_height}
                img_rgb = safe_screenshot_to_numpy(monitor=1, region=monitor_region)
                if img_rgb is None:
                    return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")

            # 【P0修复】图像完整性验证
            if img_rgb.size == 0 or img_rgb.shape[0] <= 0 or img_rgb.shape[1] <= 0:
                if image_data is None:
                    import gc
                    gc.collect()
                return format_error(TOOL_EXECUTION_ERROR, detail="截图数据异常")

            if self.is_interrupted():
                if image_data is None:
                    import gc
                    gc.collect()
                return {"success": False, "error_code": "INTERRUPTED", "user_message": "操作被用户中断", "data": None}

            result = reader.readtext(img_rgb, detail=1 if return_positions else 0, paragraph=False)

            # 【P0修复】释放numpy数组，强制垃圾回收
            if image_data is None:
                del img_rgb
                import gc
                gc.collect()

            if return_positions:
                items = []
                for (bbox, text, confidence) in result:
                    x1, y1 = bbox[0]
                    x2, y2 = bbox[2]
                    # DPI 缩放：物理像素 → 逻辑坐标（返回结果用）
                    logical_bbox = physical_to_logical({
                        "left": int(x1),
                        "top": int(y1),
                        "width": int(x2 - x1),
                        "height": int(y2 - y1)
                    })
                    log_x1 = logical_bbox["left"]
                    log_y1 = logical_bbox["top"]
                    log_x2 = log_x1 + logical_bbox["width"]
                    log_y2 = log_y1 + logical_bbox["height"]
                    items.append({
                        "text": text,
                        "left": log_x1,
                        "top": log_y1,
                        "right": log_x2,
                        "bottom": log_y2,
                        "confidence": confidence
                    })
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"OCR识别完成，找到 {len(items)} 个文本块",
                    "data": {"items": items, "source": self._current_backend}
                }
            else:
                text = " ".join([item[1] for item in result]).strip()
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"OCR识别完成: {text[:50]}...",
                    "data": {"text": text, "source": self._current_backend}
                }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))


class VisionAgentScreenOCR:
    """Vision Agent Screen OCR 包装器"""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        from core.providers.ai_provider_factory import AIProviderFactory
        self._provider = AIProviderFactory.get_provider(provider)

    def readtext(self, image_array, detail: int = 0, paragraph: bool = False):
        """读取图片中的文字"""
        import base64
        import gc
        import io

        from PIL import Image

        # numpy 数组转 base64
        img = Image.fromarray(image_array)
        try:
            buffer = io.BytesIO()
            try:
                img.save(buffer, format="PNG")
                image_b64 = base64.b64encode(buffer.getvalue()).decode()
            finally:
                buffer.close()
        finally:
            img.close()
            del img
            gc.collect()

        prompt = "请识别图片中的所有文字"
        if detail == 0:
            prompt += "，只返回文字内容，不要其他解释。"
        else:
            prompt += "，返回每个文字的位置和置信度。格式: [{\"text\": \"...\", \"bbox\": [x1,y1,x2,y2], \"confidence\": 0.9}]"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": image_b64}},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

        response = self._provider.chat(messages, model=self.model)
        text = response.get("content", "")

        if detail == 0:
            return [[None, text, 0.9]]
        else:
            # 尝试解析 JSON 格式，失败则返回简单格式
            return [[None, text, 0.9]]
