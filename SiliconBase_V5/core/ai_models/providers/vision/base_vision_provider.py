"""
Vision Provider基类

定义所有视觉模型Provider的通用接口和行为
"""

import base64
import logging
from abc import abstractmethod
from pathlib import Path
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelType
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ValidationException

logger = logging.getLogger(__name__)


class BaseVisionProvider(BaseModelProvider):
    """
    视觉模型Provider基类

    所有视觉Provider适配器必须继承此类。
    支持图片理解和描述功能。
    """

    def __init__(self, config: ModelConfig):
        """
        初始化Vision Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)
        logger.info(f"[{self.__class__.__name__}] Vision Provider实例创建: model={config.model_name}")

    @property
    def model_type(self) -> ModelType:
        """返回模型类型为VISION"""
        return ModelType.VISION

    async def invoke(
        self,
        input_data: str | dict,
        **kwargs
    ) -> str:
        """
        统一调用接口

        输入格式：
        - Dict: {"image": base64_or_path, "text": prompt}
        - str: 仅文本（不推荐，视觉模型需要图片）

        Args:
            input_data: 输入数据
            **kwargs: 额外参数

        Returns:
            模型生成的图片描述文本

        Raises:
            ValidationException: 输入格式无效
            InvokeException: 调用失败
        """
        self._ensure_initialized()

        # 解析输入
        if isinstance(input_data, dict):
            image = input_data.get("image")
            text = input_data.get("text", "描述这张图片")
        elif isinstance(input_data, str):
            # 仅文本输入（不推荐）
            image = None
            text = input_data
        else:
            error_msg = f"不支持的输入类型: {type(input_data)}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ValidationException(error_msg, "input_data", str(input_data))

        if not image:
            error_msg = "视觉调用需要image参数"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ValidationException(error_msg, "image")

        # 处理图片路径或base64
        try:
            image_b64 = self._prepare_image(image)
        except Exception as e:
            error_msg = f"图片处理失败: {e}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ValidationException(error_msg, "image", str(image)[:100]) from e

        return await self.describe(image_b64, text, **kwargs)

    def _prepare_image(self, image: str | bytes) -> str:
        """
        准备图片数据为base64字符串

        Args:
            image: 图片路径、base64字符串或bytes

        Returns:
            base64编码的图片字符串

        Raises:
            ValidationException: 图片处理失败
        """
        if isinstance(image, bytes):
            # bytes直接编码
            return base64.b64encode(image).decode('utf-8')

        elif isinstance(image, str):
            # 检查是否是文件路径
            if len(image) < 500 and (Path(image).exists() or image.startswith('/') or image.startswith('\\')):
                # 可能是文件路径，尝试读取
                try:
                    path = Path(image)
                    if path.exists():
                        with open(path, 'rb') as f:
                            return base64.b64encode(f.read()).decode('utf-8')
                except Exception as e:
                    logger.warning(f"[{self.__class__.__name__}] 读取图片文件失败: {e}")
                    # 继续尝试作为base64处理

            # 检查是否是base64字符串（可能带有data uri前缀）
            if image.startswith('data:image'):
                # 提取base64部分
                if ';base64,' in image:
                    return image.split(';base64,')[-1]
                else:
                    raise ValidationException("无效的图片data URI格式", "image", image[:100])

            # 假设是纯base64字符串
            # 简单验证（base64字符串长度通常是4的倍数）
            stripped = image.replace('\n', '').replace('\r', '').replace(' ', '')
            if len(stripped) % 4 == 0:
                try:
                    # 尝试解码验证
                    base64.b64decode(stripped)
                    return stripped
                except Exception:
                    pass

            # 无法识别格式
            raise ValidationException(
                "无法识别图片格式，请提供文件路径或base64编码",
                "image",
                image[:100]
            )

        else:
            raise ValidationException(
                f"不支持的图片类型: {type(image)}",
                "image",
                str(type(image))
            )

    @abstractmethod
    async def describe(self, image_b64: str, text: str, **kwargs) -> str:
        """
        描述图片内容

        Args:
            image_b64: base64编码的图片
            text: 提示词/问题
            **kwargs: 额外参数

        Returns:
            图片描述文本

        Raises:
            ProviderUnavailableException: Provider不可用
            InvokeException: 调用失败
        """
        pass

    async def health_check(self) -> dict[str, Any]:
        """
        执行健康检查

        Returns:
            健康状态字典
        """
        import time


        start_time = time.time()

        try:
            is_available = await self.is_available()
            latency_ms = (time.time() - start_time) * 1000

            return {
                "healthy": is_available,
                "latency_ms": latency_ms,
                "message": "Vision Provider正常运行" if is_available else "Vision Provider不可用",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "initialized": self._initialized,
                    "capabilities": self._capabilities.to_dict() if hasattr(self._capabilities, 'to_dict') else {}
                }
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"[{self.__class__.__name__}] 健康检查失败: {e}")
            return {
                "healthy": False,
                "latency_ms": latency_ms,
                "message": f"健康检查异常: {e}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "provider": self.config.provider
                }
            }
