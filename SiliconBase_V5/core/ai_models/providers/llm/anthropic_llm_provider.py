"""
Anthropic Claude LLM Provider适配器

将现有的AnthropicProvider适配到ModelBus架构
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

from core.ai_models.base import ModelCapabilities
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ConfigurationException, InvokeException, ProviderUnavailableException
from core.ai_models.providers.llm.base_llm_provider import BaseLLMProvider, ModelNotFoundException
from core.providers.anthropic_provider import AnthropicProvider

logger = logging.getLogger(__name__)


class AnthropicLLMProvider(BaseLLMProvider):
    """
    Anthropic Claude LLM Provider适配器

    特性：
    - 支持Claude 3系列模型
    - 支持流式输出
    - 支持函数调用
    - 支持视觉模型（Claude 3 Opus/Sonnet/Haiku）
    - 大上下文窗口（最高200K tokens）
    """

    # 支持视觉的模型列表（所有Claude 3系列都支持视觉）
    VISION_MODELS = [
        "claude-3", "claude-3-5"
    ]

    def __init__(self, config: ModelConfig):
        """
        初始化Anthropic LLM Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)

        if not ANTHROPIC_AVAILABLE:
            error_msg = "请安装anthropic包: pip install anthropic"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ConfigurationException(error_msg, "dependencies")

        # 设置能力
        model_lower = config.model_name.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)
        is_opus = "opus" in model_lower

        self._capabilities = ModelCapabilities(
            streaming=True,
            vision=has_vision,
            audio_input=False,
            audio_output=False,
            function_calling=True,  # Claude 3支持函数调用
            max_context_length=200000 if is_opus else 180000,
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )

        self._inner_provider: AnthropicProvider = None

        logger.info(f"[{self.__class__.__name__}] 实例创建: model={config.model_name}")

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        Returns:
            bool: 初始化是否成功

        Raises:
            ProviderUnavailableException: 初始化失败
            ConfigurationException: 配置错误
        """
        try:
            # 检查API密钥
            if not self.config.api_key:
                error_msg = "Anthropic API密钥未配置，请设置ANTHROPIC_API_KEY"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ConfigurationException(error_msg, "api_key")

            # 创建内部AnthropicProvider实例
            inner_config = {
                "model": self.config.model_name,
                "api_key": self.config.api_key,
                "timeout": self.config.timeout
            }

            # 在线程池中创建
            self._inner_provider = await self._run_sync_in_executor(
                lambda: AnthropicProvider(inner_config)
            )

            # 检查服务可用性
            is_available = await self._run_sync_in_executor(self._inner_provider.is_available)

            if not is_available:
                error_msg = "无法连接到Anthropic服务，请检查API密钥"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            self._mark_initialized()
            logger.info(f"[{self.__class__.__name__}] 初始化成功")
            return True

        except ConfigurationException:
            raise
        except ProviderUnavailableException:
            raise
        except Exception as e:
            error_msg = f"Anthropic初始化失败: {e}"
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
                - temperature: 温度参数 (默认0.7)
                - max_tokens: 最大token数 (默认1024)
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
                error_msg = "Anthropic返回空响应"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            return response

        except Exception as e:
            # 处理Anthropic特定异常
            if ANTHROPIC_AVAILABLE and hasattr(anthropic, 'AuthenticationError') and isinstance(e, anthropic.AuthenticationError):
                logger.error(f"[{self.__class__.__name__}] API密钥无效")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason="API密钥无效，请检查ANTHROPIC_API_KEY"
                ) from e

            elif ANTHROPIC_AVAILABLE and hasattr(anthropic, 'RateLimitError') and isinstance(e, anthropic.RateLimitError):
                logger.error(f"[{self.__class__.__name__}] 速率限制")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason="请求过于频繁，请稍后重试"
                ) from e

            elif "not_found" in str(e).lower() or "model" in str(e).lower():
                logger.error(f"[{self.__class__.__name__}] 模型不存在: {self.config.model_name}")
                raise ModelNotFoundException(self.config.provider, self.config.model_name) from e

            elif "timeout" in str(e).lower():
                logger.error(f"[{self.__class__.__name__}] 请求超时: timeout={self.config.timeout}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"Anthropic请求超时({self.config.timeout}s)"
                ) from e

            else:
                logger.error(f"[{self.__class__.__name__}] 调用失败: {type(e).__name__}: {e}")
                raise InvokeException(
                    message=f"Anthropic调用失败: {e}",
                    provider=self.config.provider
                ) from e

    async def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        执行流式聊天对话

        注意：当前使用内部provider的同步实现，模拟流式输出。

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Returns:
            异步文本迭代器
        """
        self._ensure_initialized()

        # 先获取完整响应，然后模拟流式输出
        response = await self.chat(messages, **kwargs)

        # 模拟流式输出：按句子分割
        import re
        sentences = re.split(r'(?<=[。！？.!?\n])', response)

        for sentence in sentences:
            if sentence.strip():
                yield sentence
                await asyncio.sleep(0.02)

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
                "message": "Anthropic服务正常" if is_available else "Anthropic服务不可用",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "initialized": self._initialized,
                    "available_models_count": len(available_models),
                    "api_key_configured": bool(self.config.api_key),
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
            return [
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-3-5-sonnet-20240620"
            ]
