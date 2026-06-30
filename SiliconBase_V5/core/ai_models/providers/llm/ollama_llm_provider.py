"""
Ollama LLM Provider适配器

将现有的OllamaProvider适配到ModelBus架构
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from core.ai_models.base import ModelCapabilities
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import InvokeException, ProviderUnavailableException
from core.ai_models.providers.llm.base_llm_provider import BaseLLMProvider, ModelNotFoundException
from core.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class OllamaLLMProvider(BaseLLMProvider):
    """
    Ollama LLM Provider适配器

    特性：
    - 支持本地Ollama服务
    - 支持流式输出
    - 支持视觉模型（如qwen3-vl, llava等）
    - 自动处理qwen3系列模型参数优化
    """

    # 支持视觉的模型列表
    VISION_MODELS = [
        "qwen3-vl", "qwen2-vl", "qwen-vl",
        "llava", "llava-next", "llama3.2-vision",
        "bakllava", "moondream"
    ]

    def __init__(self, config: ModelConfig):
        """
        初始化Ollama LLM Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)

        # 设置能力
        model_lower = config.model_name.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)

        self._capabilities = ModelCapabilities(
            streaming=True,
            vision=has_vision,
            audio_input=False,
            audio_output=False,
            function_calling=False,  # Ollama暂不支持标准函数调用
            max_context_length=32768,
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )

        self._inner_provider: OllamaProvider = None
        self._base_url = config.base_url or "http://localhost:11434"

        logger.info(f"[{self.__class__.__name__}] 实例创建: base_url={self._base_url}, model={config.model_name}")

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
            logger.info(f"[{self.__class__.__name__}] 初始化成功: base_url={self._base_url}")
            return True

        except ProviderUnavailableException:
            raise
        except Exception as e:
            error_msg = f"Ollama初始化失败: {e}"
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

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        执行聊天对话

        Args:
            messages: 消息列表
            **kwargs: 额外参数
                - temperature: 温度参数 (默认0.2)
                - max_tokens: 最大token数 (默认512)
                - top_p: top_p参数
                - top_k: top_k参数
                - model: 覆盖默认模型

        Returns:
            模型生成的文本响应

        Raises:
            ProviderUnavailableException: 连接失败或服务不可用
            ModelNotFoundException: 模型不存在
            InvokeException: 调用失败
        """
        self._ensure_initialized()

        # 合并extra_params中的参数
        call_kwargs = {**self.config.extra_params, **kwargs}

        try:
            # 调用内部provider的chat方法
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
            # 处理特定异常类型
            error_str = str(e).lower()

            if "404" in error_str or "not found" in error_str:
                logger.error(f"[{self.__class__.__name__}] 模型不存在: {self.config.model_name}")
                raise ModelNotFoundException(self.config.provider, self.config.model_name) from e

            elif "connection" in error_str or "connect" in error_str:
                logger.error(f"[{self.__class__.__name__}] 连接失败: {self._base_url}, error={e}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"无法连接到Ollama服务: {self._base_url}"
                ) from e

            elif "timeout" in error_str:
                logger.error(f"[{self.__class__.__name__}] 请求超时: timeout={self.config.timeout}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"Ollama请求超时({self.config.timeout}s)"
                ) from e

            else:
                logger.error(f"[{self.__class__.__name__}] 调用失败: {type(e).__name__}: {e}")
                raise InvokeException(
                    message=f"Ollama调用失败: {e}",
                    provider=self.config.provider
                ) from e

    async def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        执行流式聊天对话

        注意：当前OllamaProvider的同步实现不支持原生流式，
        这里模拟流式输出（按字符分段）

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Returns:
            异步文本迭代器
        """
        self._ensure_initialized()

        # 先获取完整响应，然后模拟流式输出
        # 在实际实现中，可以使用Ollama的stream API
        response = await self.chat(messages, **kwargs)

        # 模拟流式输出：按句子分割
        import re
        sentences = re.split(r'(?<=[。！？.!?])', response)

        for sentence in sentences:
            if sentence.strip():
                yield sentence
                # 小延迟模拟流式效果
                await asyncio.sleep(0.01)

    async def health_check(self) -> dict[str, Any]:
        """
        执行健康检查

        Returns:
            健康状态字典
        """
        import time
        start_time = time.time()

        try:
            # 检查服务可用性
            is_available = await self.is_available()
            latency_ms = (time.time() - start_time) * 1000

            # 获取可用模型列表
            available_models = []
            if is_available and self._inner_provider:
                try:
                    available_models = await self._run_sync_in_executor(
                        self._inner_provider.get_model_list
                    )
                except Exception as e:
                    logger.warning(f"[{self.__class__.__name__}] 获取模型列表失败: {e}")

            return {
                "healthy": is_available,
                "latency_ms": latency_ms,
                "message": "Ollama服务正常" if is_available else "Ollama服务不可用",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "base_url": self._base_url,
                    "initialized": self._initialized,
                    "available_models_count": len(available_models),
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
                    "provider": self.config.provider,
                    "base_url": self._base_url
                }
            }

    async def get_available_models(self) -> list[str]:
        """
        获取可用模型列表

        Returns:
            模型名称列表
        """
        self._ensure_initialized()

        try:
            return await self._run_sync_in_executor(self._inner_provider.get_model_list)
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 获取模型列表失败: {e}")
            return []


# 导入asyncio用于流式输出
