"""
OpenAI LLM Provider适配器

将现有的OpenAIProvider适配到ModelBus架构
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    openai = None

from core.ai_models.base import ModelCapabilities
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ConfigurationException, InvokeException, ProviderUnavailableException
from core.ai_models.providers.llm.base_llm_provider import BaseLLMProvider, ModelNotFoundException
from core.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenAILLMProvider(BaseLLMProvider):
    """
    OpenAI LLM Provider适配器

    特性：
    - 支持OpenAI官方API
    - 支持GPT-4/GPT-3.5系列模型
    - 支持流式输出
    - 支持函数调用
    - 支持视觉模型（GPT-4V等）
    """

    # 支持视觉的模型列表
    VISION_MODELS = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision",
        "gpt-4-1106-vision-preview", "gpt-4-0125-preview",
    ]

    def __init__(self, config: ModelConfig):
        """
        初始化OpenAI LLM Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)

        if not OPENAI_AVAILABLE:
            error_msg = "请安装openai包: pip install openai>=1.0.0"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ConfigurationException(error_msg, "dependencies")

        # 设置能力
        model_lower = config.model_name.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)
        is_gpt4 = "gpt-4" in model_lower

        self._capabilities = ModelCapabilities(
            streaming=True,
            vision=has_vision,
            audio_input=False,
            audio_output=False,
            function_calling=True,  # OpenAI支持函数调用
            max_context_length=128000 if is_gpt4 else 16385,
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )

        self._inner_provider: OpenAIProvider = None
        self._base_url = config.base_url or "https://api.openai.com/v1"

        logger.info(f"[{self.__class__.__name__}] 实例创建: base_url={self._base_url}, model={config.model_name}")

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
            # 创建内部OpenAIProvider实例
            inner_config = {
                "base_url": self._base_url,
                "model": self.config.model_name,
                "api_key": self.config.api_key,
                "timeout": self.config.timeout
            }

            # 在线程池中创建（因为可能涉及网络验证）
            self._inner_provider = await self._run_sync_in_executor(
                lambda: OpenAIProvider(inner_config)
            )

            # 检查服务可用性
            is_available = await self._run_sync_in_executor(self._inner_provider.is_available)

            if not is_available:
                error_msg = f"无法连接到OpenAI服务: {self._base_url}"
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
            error_msg = f"OpenAI初始化失败: {e}"
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
                - top_p: top_p参数
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
                error_msg = "OpenAI返回空响应"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            return response

        except Exception as e:
            # 处理OpenAI特定异常
            if OPENAI_AVAILABLE and hasattr(openai, 'AuthenticationError') and isinstance(e, openai.AuthenticationError):
                logger.error(f"[{self.__class__.__name__}] API密钥无效")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason="API密钥无效，请检查OPENAI_API_KEY"
                ) from e

            elif OPENAI_AVAILABLE and hasattr(openai, 'RateLimitError') and isinstance(e, openai.RateLimitError):
                logger.error(f"[{self.__class__.__name__}] 速率限制")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason="请求过于频繁，请稍后重试"
                ) from e

            elif OPENAI_AVAILABLE and hasattr(openai, 'NotFoundError') and isinstance(e, openai.NotFoundError):
                logger.error(f"[{self.__class__.__name__}] 模型不存在: {self.config.model_name}")
                raise ModelNotFoundException(self.config.provider, self.config.model_name) from e

            elif "timeout" in str(e).lower():
                logger.error(f"[{self.__class__.__name__}] 请求超时: timeout={self.config.timeout}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"OpenAI请求超时({self.config.timeout}s)"
                ) from e

            else:
                logger.error(f"[{self.__class__.__name__}] 调用失败: {type(e).__name__}: {e}")
                raise InvokeException(
                    message=f"OpenAI调用失败: {e}",
                    provider=self.config.provider
                ) from e

    async def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        执行流式聊天对话（真流式 - 使用OpenAI原生stream=True）

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Returns:
            异步文本迭代器
        """
        self._ensure_initialized()

        call_kwargs = {**self.config.extra_params, **kwargs}

        try:
            # 真流式：直接 yield 底层异步流式结果
            stream = self._inner_provider.chat_stream_async(messages, **call_kwargs)
            async for chunk in stream:
                yield chunk

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 流式调用失败: {e}")
            raise InvokeException(
                message=f"OpenAI流式调用失败: {e}",
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
                "message": "OpenAI服务正常" if is_available else "OpenAI服务不可用",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "base_url": self._base_url,
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
            return [self.config.model_name]
