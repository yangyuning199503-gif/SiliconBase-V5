"""
Ollama Vision Provider适配器

使用Ollama支持视觉的模型进行图片理解和描述
"""

import logging
from typing import Any

from core.ai_models.base import ModelCapabilities
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import InvokeException, ProviderUnavailableException
from core.ai_models.providers.vision.base_vision_provider import BaseVisionProvider
from core.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class OllamaVisionProvider(BaseVisionProvider):
    """
    Ollama视觉模型Provider适配器

    支持模型：
    - qwen3-vl
    - qwen2-vl
    - llava
    - llava-next
    - llama3.2-vision
    - bakllava
    - moondream

    特性：
    - 本地部署，无需API密钥
    - 支持多图输入
    - 支持自定义提示词
    """

    # 支持视觉的模型列表
    VISION_MODELS = [
        "qwen3-vl", "qwen2-vl", "qwen-vl",
        "llava", "llava-next", "llama3.2-vision",
        "bakllava", "moondream"
    ]

    def __init__(self, config: ModelConfig):
        """
        初始化Ollama Vision Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)

        # 检查模型是否支持视觉
        model_lower = config.model_name.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)

        if not has_vision:
            logger.warning(
                f"[{self.__class__.__name__}] 模型 {config.model_name} "
                f"可能不支持视觉，支持的模型: {self.VISION_MODELS}"
            )

        # 设置能力
        self._capabilities = ModelCapabilities(
            streaming=False,
            vision=True,
            audio_input=False,
            audio_output=False,
            function_calling=False,
            max_context_length=32768,
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )

        self._inner_provider: OllamaProvider = None
        self._base_url = config.base_url or "http://localhost:11434"

        logger.info(
            f"[{self.__class__.__name__}] 实例创建: "
            f"base_url={self._base_url}, model={config.model_name}"
        )

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        Returns:
            bool: 初始化是否成功

        Raises:
            ProviderUnavailableException: 初始化失败
        """
        try:
            # 创建内部OllamaProvider实例
            inner_config = {
                "base_url": self._base_url,
                "model": self.config.model_name,
                "timeout": self.config.timeout,
                "retry_times": self.config.max_retries
            }

            self._inner_provider = OllamaProvider(inner_config)

            # 检查服务可用性
            is_available = await self._run_sync_in_executor(self._inner_provider.is_available)

            if not is_available:
                error_msg = f"无法连接到Ollama服务: {self._base_url}"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            self._mark_initialized()
            logger.info(f"[{self.__class__.__name__}] 初始化成功")
            return True

        except ProviderUnavailableException:
            raise
        except Exception as e:
            error_msg = f"Ollama Vision初始化失败: {e}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ProviderUnavailableException(
                provider=self.config.provider,
                reason=error_msg
            ) from e

    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: 是否可用
        """
        if not self._inner_provider:
            return False

        try:
            return await self._run_sync_in_executor(self._inner_provider.is_available)
        except Exception as e:
            logger.debug(f"[{self.__class__.__name__}] 可用性检查失败: {e}")
            return False

    async def describe(self, image_b64: str, text: str, **kwargs) -> str:
        """
        描述图片内容

        Ollama视觉API格式：
        {
            "model": "llava",
            "messages": [{
                "role": "user",
                "content": "描述图片",
                "images": ["base64_encoded_image"]
            }]
        }

        Args:
            image_b64: base64编码的图片
            text: 提示词/问题
            **kwargs: 额外参数
                - temperature: 温度参数
                - max_tokens: 最大token数
                - mime_type: 图片MIME类型（用于调试）

        Returns:
            图片描述文本

        Raises:
            ProviderUnavailableException: 服务不可用
            InvokeException: 调用失败
        """
        self._ensure_initialized()

        # 合并参数
        call_kwargs = {**self.config.extra_params, **kwargs}

        try:
            # 准备Ollama视觉格式的消息
            messages = [{
                "role": "user",
                "content": text,
                "images": [image_b64]
            }]

            # 调用内部provider
            response = await self._run_sync_in_executor(
                self._inner_provider.chat,
                messages,
                **call_kwargs
            )

            if response is None:
                error_msg = "Ollama返回空响应"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            return response

        except Exception as e:
            error_str = str(e).lower()

            if "404" in error_str or "not found" in error_str:
                logger.error(f"[{self.__class__.__name__}] 模型不存在: {self.config.model_name}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"模型 '{self.config.model_name}' 不存在，请运行: ollama pull {self.config.model_name}"
                ) from e

            elif "connection" in error_str or "connect" in error_str:
                logger.error(f"[{self.__class__.__name__}] 连接失败: {self._base_url}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"无法连接到Ollama服务: {self._base_url}"
                ) from e

            else:
                logger.error(f"[{self.__class__.__name__}] 调用失败: {type(e).__name__}: {e}")
                raise InvokeException(
                    message=f"视觉调用失败: {e}",
                    provider=self.config.provider
                ) from e

    async def describe_multi(
        self,
        images_b64: list[str],
        text: str,
        **kwargs
    ) -> str:
        """
        描述多张图片

        Args:
            images_b64: base64编码的图片列表
            text: 提示词/问题
            **kwargs: 额外参数

        Returns:
            图片描述文本
        """
        self._ensure_initialized()

        # Ollama支持单条消息中的多张图片
        messages = [{
            "role": "user",
            "content": text,
            "images": images_b64
        }]

        call_kwargs = {**self.config.extra_params, **kwargs}

        try:
            response = await self._run_sync_in_executor(
                self._inner_provider.chat,
                messages,
                **call_kwargs
            )

            if response is None:
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason="Ollama返回空响应"
                )

            return response

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 多图调用失败: {e}")
            raise InvokeException(
                message=f"多图视觉调用失败: {e}",
                provider=self.config.provider
            ) from e

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

            # 获取可用模型列表
            vision_models = []
            if is_available and self._inner_provider:
                try:
                    all_models = await self._run_sync_in_executor(
                        self._inner_provider.get_model_list
                    )
                    # 过滤视觉模型
                    vision_models = [
                        m for m in all_models
                        if any(vm in m.lower() for vm in self.VISION_MODELS)
                    ]
                except Exception as e:
                    logger.warning(f"[{self.__class__.__name__}] 获取模型列表失败: {e}")

            return {
                "healthy": is_available,
                "latency_ms": latency_ms,
                "message": "Ollama Vision服务正常" if is_available else "Ollama Vision服务不可用",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "base_url": self._base_url,
                    "initialized": self._initialized,
                    "vision_models_available": vision_models,
                    "capabilities": self._capabilities.to_dict()
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

    async def _run_sync_in_executor(self, func, *args, **kwargs):
        """
        在线程池中运行同步函数

        优先使用基类线程池，避免频繁创建/销毁线程池

        Args:
            func: 同步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果
        """
        import asyncio

        return await asyncio.to_thread(func, *args, **kwargs)
