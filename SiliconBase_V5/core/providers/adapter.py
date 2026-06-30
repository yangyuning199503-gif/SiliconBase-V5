#!/usr/bin/env python3
"""
旧Provider体系到新体系的适配器

提供向后兼容性，允许旧版AIProvider在新版ModelBus中运行。

使用方法:
    # 旧代码（仍然兼容）
    from core.providers import OllamaProvider
    provider = OllamaProvider(config)
    response = provider.chat(messages)

    # 新代码（推荐）
    from core.ai_models.providers.llm import OllamaLLMProvider
    from core.ai_models.config import ModelConfig

    config = ModelConfig(provider="ollama", model_name="llama2")
    provider = OllamaLLMProvider(config)
    await provider.initialize()
    response = await provider.invoke(messages)

迁移指南: https://docs.siliconbase.ai/migration/provider-v3
"""

import asyncio
import logging
import warnings
from collections.abc import AsyncIterator
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelCapabilities, ModelType
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import InvokeException, ProviderUnavailableException, ValidationException

logger = logging.getLogger(__name__)


class ProviderAdapter(BaseModelProvider):
    """
    旧版AIProvider到新版BaseModelProvider的适配器

    此适配器包装旧版Provider，使其可以在新版ModelBus中使用。
    提供了同步到异步的转换，以及API映射。

    Attributes:
        _legacy_provider: 被包装的旧版Provider实例
        _legacy_class: 旧版Provider类

    示例:
        # 包装旧版Provider
        from core.providers import OllamaProvider
        from core.providers.adapter import ProviderAdapter

        legacy_config = {"model": "llama2", "base_url": "http://localhost:11434"}
        adapter = ProviderAdapter(OllamaProvider, legacy_config)

        await adapter.initialize()
        response = await adapter.invoke("Hello, world!")
    """

    def __init__(self, legacy_provider_class, legacy_config: dict[str, Any]):
        """
        初始化适配器

        Args:
            legacy_provider_class: 旧版Provider类（继承自AIProvider）
            legacy_config: 旧版配置字典
        """
        warnings.warn(
            "ProviderAdapter is a migration tool. Please migrate to native BaseModelProvider implementations. "
            "See: https://docs.siliconbase.ai/migration/provider-v3",
            DeprecationWarning,
            stacklevel=2
        )

        # 转换旧配置到新配置格式
        model_config = self._convert_config(legacy_config)
        super().__init__(model_config)

        self._legacy_class = legacy_provider_class
        self._legacy_config = legacy_config
        self._legacy_provider = None

        logger.info(f"[{self.__class__.__name__}] 适配器创建: {legacy_provider_class.__name__}")

    def _convert_config(self, legacy_config: dict[str, Any]) -> ModelConfig:
        """
        将旧版配置转换为新版ModelConfig

        Args:
            legacy_config: 旧版配置字典

        Returns:
            ModelConfig: 新版配置对象
        """
        provider_name = legacy_config.get("provider", "unknown")
        model_name = legacy_config.get("model", legacy_config.get("model_name", "default"))
        base_url = legacy_config.get("base_url")
        api_key = legacy_config.get("api_key")
        timeout = legacy_config.get("timeout", 120)

        return ModelConfig(
            provider=provider_name,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            extra_params={k: v for k, v in legacy_config.items()
                         if k not in ["provider", "model", "model_name", "base_url", "api_key", "timeout"]}
        )

    @property
    def model_type(self) -> ModelType:
        """返回模型类型为LLM（默认）"""
        return ModelType.LLM

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        创建旧版Provider实例

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 在线程池中创建旧版Provider实例（避免阻塞）
            self._legacy_provider = await asyncio.to_thread(
                self._legacy_class, self._legacy_config
            )

            # 转换capabilities
            legacy_caps = self._legacy_provider.get_capabilities()
            self._capabilities = ModelCapabilities(
                streaming=getattr(legacy_caps, 'streaming', False),
                vision=getattr(legacy_caps, 'vision', False),
                function_calling=getattr(legacy_caps, 'function_calling', False),
                max_context_length=getattr(legacy_caps, 'max_context_length', 4096)
            )

            self._mark_initialized()
            logger.info(f"[{self.__class__.__name__}] 初始化完成")
            return True

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 初始化失败: {e}")
            raise ProviderUnavailableException(
                provider=self.config.provider,
                reason=f"适配器初始化失败: {e}"
            ) from e

    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: Provider是否可用
        """
        if not self._legacy_provider:
            return False

        # 优先使用原生异步 is_available_async
        if hasattr(self._legacy_provider, 'is_available_async') and callable(self._legacy_provider.is_available_async):
            return await self._legacy_provider.is_available_async()
        # 回退到线程池调用同步的is_available
        return await asyncio.to_thread(self._legacy_provider.is_available)

    async def invoke(
        self,
        input_data: str | dict | list,
        **kwargs
    ) -> str | AsyncIterator:
        """
        调用模型

        将新版invoke API适配到旧版chat/generate API

        Args:
            input_data: 输入数据（字符串、字典或消息列表）
            **kwargs: 额外参数

        Returns:
            模型输出字符串

        Raises:
            ProviderUnavailableException: Provider不可用
            InvokeException: 调用失败
        """
        self._ensure_initialized()

        try:
            # 标准化输入
            messages = self._normalize_input(input_data)

            # 优先使用原生异步 chat_async，避免线程池开销
            if hasattr(self._legacy_provider, 'chat_async') and callable(self._legacy_provider.chat_async):
                response = await self._legacy_provider.chat_async(messages, **kwargs)
            else:
                response = await asyncio.to_thread(
                    self._legacy_provider.chat, messages, **kwargs
                )

            if response is None:
                last_error = self._legacy_provider.get_last_error()
                raise InvokeException(
                    message="Provider返回空响应",
                    provider=self.config.provider,
                    original_error=Exception(last_error) if last_error else None
                )

            return response

        except Exception as e:
            if isinstance(e, InvokeException):
                raise
            logger.error(f"[{self.__class__.__name__}] 调用失败: {e}")
            raise InvokeException(
                message=f"调用失败: {e}",
                provider=self.config.provider,
                original_error=e
            ) from e

    def _normalize_input(self, input_data: str | list | dict) -> list[dict[str, str]]:
        """
        规范化输入数据为标准消息格式

        Args:
            input_data: 原始输入

        Returns:
            标准消息列表
        """
        if isinstance(input_data, str):
            return [{"role": "user", "content": input_data}]

        elif isinstance(input_data, list):
            normalized = []
            for i, msg in enumerate(input_data):
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if not isinstance(content, str):
                        content = str(content)
                    normalized.append({"role": role, "content": content})
                else:
                    raise ValueError(f"消息列表第{i}项格式错误: {type(msg)}")
            return normalized

        elif isinstance(input_data, dict):
            role = input_data.get("role", "user")
            content = input_data.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            return [{"role": role, "content": content}]

        else:
            raise ValidationException(
                message=f"不支持的输入类型: {type(input_data)}",
                field="input_data",
                value=str(input_data)
            )

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        import time
        start_time = time.time()

        try:
            is_available = await self.is_available()
            latency_ms = (time.time() - start_time) * 1000

            status = {
                "healthy": is_available,
                "latency_ms": latency_ms,
                "provider": self.config.provider,
                "model": self.config.model_name,
                "adapter": True,
                "initialized": self._initialized
            }

            if is_available:
                status["message"] = "Provider正常运行（通过适配器）"
            else:
                status["message"] = "Provider不可用"
                if self._legacy_provider:
                    last_error = self._legacy_provider.get_last_error()
                    if last_error:
                        status["last_error"] = last_error

            return status

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"[{self.__class__.__name__}] 健康检查失败: {e}")
            return {
                "healthy": False,
                "latency_ms": latency_ms,
                "message": f"健康检查异常: {e}",
                "error": str(e),
                "provider": self.config.provider
            }

    async def cleanup(self):
        """清理资源"""
        self._legacy_provider = None
        await super().cleanup()
        logger.info(f"[{self.__class__.__name__}] 适配器已清理")


def migrate_provider_config(legacy_config: dict[str, Any]) -> ModelConfig:
    """
    迁移旧版配置到新版配置格式

    这是一个辅助函数，帮助用户将旧版配置转换为新版格式。

    Args:
        legacy_config: 旧版配置字典

    Returns:
        ModelConfig: 新版配置对象

    示例:
        legacy_config = {
            "provider": "ollama",
            "model": "llama2",
            "base_url": "http://localhost:11434"
        }
        new_config = migrate_provider_config(legacy_config)
        provider = OllamaLLMProvider(new_config)
    """
    provider_name = legacy_config.get("provider", "unknown")
    model_name = legacy_config.get("model", legacy_config.get("model_name", "default"))
    base_url = legacy_config.get("base_url")
    api_key = legacy_config.get("api_key")
    timeout = legacy_config.get("timeout", 120)
    max_retries = legacy_config.get("max_retries", 2)

    logger.info(f"[migrate_provider_config] 迁移配置: {provider_name}/{model_name}")

    return ModelConfig(
        provider=provider_name,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        extra_params={k: v for k, v in legacy_config.items()
                     if k not in ["provider", "model", "model_name", "base_url", "api_key", "timeout", "max_retries"]}
    )
