"""
OpenAI兼容LLM Provider适配器

支持所有OpenAI API格式的服务商：
- DeepSeek
- Kimi (Moonshot)
- 通义千问
- 智谱GLM
- 火山引擎豆包
- LocalAI
- LM Studio
- 等
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from core.ai_models.base import ModelCapabilities
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ConfigurationException, InvokeException, ProviderUnavailableException
from core.ai_models.providers.llm.base_llm_provider import BaseLLMProvider, ModelNotFoundException
from core.providers.openai_compatible_provider import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleLLMProvider(BaseLLMProvider):
    """
    OpenAI兼容LLM Provider适配器

    通过配置base_url支持任意OpenAI API格式的服务。
    复用现有的OpenAICompatibleProvider核心逻辑。

    支持的服务商：
    - deepseek: DeepSeek AI
    - kimi: Moonshot Kimi
    - qwen: 通义千问
    - glm: 智谱GLM
    - doubao: 火山引擎豆包
    - localai: LocalAI
    - lmstudio: LM Studio
    """

    # 服务商配置映射
    PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
        "deepseek": {
            "name": "DeepSeek",
            "category": "cloud",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "vision": False,
            "function_calling": True,
            "max_context": 64000
        },
        "kimi": {
            "name": "Kimi (Moonshot)",
            "category": "cloud",
            "base_url": "https://api.moonshot.cn/v1",
            "default_model": "moonshot-v1-8k",
            "vision": False,
            "function_calling": True,
            "max_context": 128000
        },
        "qwen": {
            "name": "通义千问",
            "category": "cloud",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "default_model": "qwen-turbo",
            "vision": True,
            "function_calling": True,
            "max_context": 32000
        },
        "glm": {
            "name": "智谱GLM",
            "category": "cloud",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "default_model": "glm-4",
            "vision": True,
            "function_calling": True,
            "max_context": 32000
        },
        "doubao": {
            "name": "火山引擎（豆包）",
            "category": "cloud",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "default_model": "doubao-pro-32k",
            "vision": True,
            "function_calling": True,
            "max_context": 32000
        },
        "localai": {
            "name": "LocalAI",
            "category": "local",
            "base_url": "http://localhost:8080/v1",
            "default_model": "gpt-3.5-turbo",
            "vision": False,
            "function_calling": False,
            "max_context": 4096
        },
        "lmstudio": {
            "name": "LM Studio",
            "category": "local",
            "base_url": "http://localhost:1234/v1",
            "default_model": "local-model",
            "vision": False,
            "function_calling": False,
            "max_context": 4096
        },
    }

    def __init__(self, config: ModelConfig):
        """
        初始化OpenAI兼容LLM Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)

        if not OPENAI_AVAILABLE:
            error_msg = "请安装openai包: pip install openai>=1.0.0"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ConfigurationException(error_msg, "dependencies")

        # 获取服务商类型（从extra_params或provider名称）
        self._provider_type = config.extra_params.get("provider_type", config.provider)

        # 获取服务商配置
        provider_info = self.PROVIDER_CONFIGS.get(self._provider_type, {})

        # 确定base_url
        self._base_url = config.base_url or provider_info.get("base_url", "")

        # 确定模型名称
        self._model_name = config.model_name or provider_info.get("default_model", "gpt-3.5-turbo")

        # 设置能力
        model_lower = self._model_name.lower()
        vision_models = ["vl", "vision", "glm-4v", "qwen-vl"]
        has_vision = provider_info.get("vision", False) or any(vm in model_lower for vm in vision_models)

        self._capabilities = ModelCapabilities(
            streaming=True,
            vision=has_vision,
            audio_input=False,
            audio_output=False,
            function_calling=provider_info.get("function_calling", False),
            max_context_length=provider_info.get("max_context", 4096),
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )

        self._inner_provider: OpenAICompatibleProvider = None
        self._provider_info = provider_info

        logger.info(f"[{self.__class__.__name__}] 实例创建: provider={self._provider_type}, base_url={self._base_url}, model={self._model_name}")

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        Returns:
            bool: 初始化是否成功

        Raises:
            ProviderUnavailableException: 初始化失败
        """
        try:
            # 检查配置
            if not self._base_url:
                error_msg = "base_url未配置"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ConfigurationException(error_msg, "base_url")

            # 云端服务需要API密钥
            if self._provider_info.get("category") == "cloud" and not self.config.api_key:
                error_msg = f"{self._provider_info.get('name', self._provider_type)}需要API密钥"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ConfigurationException(error_msg, "api_key")

            # 创建内部OpenAICompatibleProvider实例
            inner_config = {
                "provider_type": self._provider_type,
                "base_url": self._base_url,
                "model": self._model_name,
                "api_key": self.config.api_key,
                "timeout": self.config.timeout
            }

            # 在线程池中创建
            self._inner_provider = await self._run_sync_in_executor(
                lambda: OpenAICompatibleProvider(config=inner_config)
            )

            # 检查服务可用性
            is_available = await self._run_sync_in_executor(self._inner_provider.is_available)

            if not is_available:
                error_msg = f"无法连接到服务: {self._base_url}"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            self._mark_initialized()
            logger.info(f"[{self.__class__.__name__}] 初始化成功: {self._provider_info.get('name', self._provider_type)}")
            return True

        except ConfigurationException:
            raise
        except ProviderUnavailableException:
            raise
        except Exception as e:
            error_msg = f"初始化失败: {e}"
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
                error_msg = "服务返回空响应"
                logger.error(f"[{self.__class__.__name__}] {error_msg}")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=error_msg
                )

            return response

        except Exception as e:
            # 处理OpenAI特定异常
            if OPENAI_AVAILABLE:
                if hasattr(openai, 'AuthenticationError') and isinstance(e, openai.AuthenticationError):
                    logger.error(f"[{self.__class__.__name__}] API密钥无效")
                    raise ProviderUnavailableException(
                        provider=self.config.provider,
                        reason="API密钥无效"
                    ) from e

                elif hasattr(openai, 'RateLimitError') and isinstance(e, openai.RateLimitError):
                    logger.error(f"[{self.__class__.__name__}] 速率限制")
                    raise ProviderUnavailableException(
                        provider=self.config.provider,
                        reason="请求过于频繁"
                    ) from e

                elif hasattr(openai, 'NotFoundError') and isinstance(e, openai.NotFoundError):
                    logger.error(f"[{self.__class__.__name__}] 模型不存在: {self._model_name}")
                    raise ModelNotFoundException(self.config.provider, self._model_name) from e

            if "timeout" in str(e).lower():
                logger.error(f"[{self.__class__.__name__}] 请求超时")
                raise ProviderUnavailableException(
                    provider=self.config.provider,
                    reason=f"请求超时({self.config.timeout}s)"
                ) from e

            logger.error(f"[{self.__class__.__name__}] 调用失败: {type(e).__name__}: {e}")
            raise InvokeException(
                message=f"调用失败: {e}",
                provider=self.config.provider
            ) from e

    async def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        执行流式聊天对话（真流式 - OpenAI兼容API原生stream支持）

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
            # OpenAICompatibleProvider 继承自 OpenAIProvider，共享 chat_stream_async
            stream = self._inner_provider.chat_stream_async(messages, **call_kwargs)
            async for chunk in stream:
                yield chunk

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 流式调用失败: {e}")
            raise InvokeException(
                message=f"OpenAI兼容流式调用失败: {e}",
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
                "message": "服务正常" if is_available else "服务不可用",
                "details": {
                    "provider": self.config.provider,
                    "provider_type": self._provider_type,
                    "provider_name": self._provider_info.get("name", self._provider_type),
                    "model": self._model_name,
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
                    "provider_type": self._provider_type
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
            # 返回预设模型列表
            preset = self._provider_info.get("models", [])
            if preset:
                return preset
            return [self._model_name]

    @classmethod
    def list_supported_providers(cls) -> list[str]:
        """
        列出所有支持的服务商类型

        Returns:
            服务商类型列表
        """
        return list(cls.PROVIDER_CONFIGS.keys())

    @classmethod
    def get_provider_info(cls, provider_type: str) -> dict[str, Any]:
        """
        获取服务商信息

        Args:
            provider_type: 服务商类型

        Returns:
            服务商信息字典
        """
        return cls.PROVIDER_CONFIGS.get(provider_type, {})
