#!/usr/bin/env python3
"""
原子工具：OCR文字识别（需安装 easyocr）
【P1-001优化】延迟加载 + 支持配置切换后端
"""
import asyncio
import os

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import DEPENDENCY_MISSING, FILE_NOT_FOUND, INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error


class OCRText(BaseTool):
    """
    OCR文字识别工具 - 支持多后端配置

    配置方式：修改 config/vision.yaml 中的 ocr 部分
    """
    tool_id = "ocr_text"
    name = "OCR识别"
    description = "从图像文件中提取文字（支持 easyocr/vision_agent 后端，可配置）"
    input_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "图像文件路径"}
        },
        "required": ["image_path"]
    }

    _reader = None
    _reader_initialized = False
    _reader_error = None
    _current_backend = None

    def _get_reader(self):
        """延迟初始化 OCR reader"""
        # 检查是否需要切换后端
        ocr_config = config.get("ocr", {})
        default_engine = ocr_config.get("default_engine", "easyocr")

        # 如果后端变化，重置 reader
        if self._current_backend != default_engine:
            self.__class__._reader = None
            self.__class__._reader_initialized = False
            self.__class__._reader_error = None
            self.__class__._current_backend = default_engine

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
            raise RuntimeError(self._reader_error) from e
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

            self.__class__._reader = VisionAgentOCRWrapper(provider, model)
            self.__class__._reader_initialized = True
            self.__class__._current_backend = "vision_agent"
            return self._reader
        except Exception as e:
            self.__class__._reader_error = str(e)
            self.__class__._reader_initialized = True
            raise RuntimeError(f"Vision Agent OCR 初始化失败: {e}") from e

    def _execute(self, **kwargs) -> dict:
        path = kwargs.get("image_path")
        if not path:
            return format_error(INVALID_PARAMS, detail="缺少 image_path 参数")

        if not os.path.exists(path):
            return format_error(FILE_NOT_FOUND, path=path)

        try:
            reader = self._get_reader()
            result = reader.readtext(path, detail=0)
            text = "\n".join(result)
            return {
                "success": True,
                "error_code": None,
                "user_message": f"OCR识别完成，共 {len(text)} 字符",
                "data": {
                    "text": text,
                    "source": self._current_backend or "easyocr"
                }
            }
        except RuntimeError as e:
            return format_error(DEPENDENCY_MISSING, package="ocr", detail=str(e))
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class VisionAgentOCRWrapper:
    """Vision Agent OCR 包装器"""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        from core.providers.ai_provider_factory import AIProviderFactory
        self._provider = AIProviderFactory.get_provider(provider)

    def readtext(self, image_path: str, detail: int = 0):
        """读取图片中的文字"""
        import base64
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": image_b64}},
                    {"type": "text", "text": "请识别图片中的所有文字，只返回文字内容，不要其他解释。"}
                ]
            }
        ]

        response = self._provider.chat(messages, model=self.model)
        text = response.get("content", "")
        return [[None, text, 0.9]]  # 模拟 easyocr 返回格式
