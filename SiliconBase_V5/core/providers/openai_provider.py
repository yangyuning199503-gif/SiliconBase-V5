#!/usr/bin/env python3
"""
OpenAI Provider - 支持OpenAI API和兼容API
"""

import os
from typing import Any

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from core.logger import logger

from .base import (
    AIProvider,
    ProviderCapabilities,
    ProviderConfigError,
    ProviderNotAvailableError,
    VisionCapabilityMixin,
)


class OpenAIProvider(AIProvider, VisionCapabilityMixin):
    """OpenAI后端实现 - 支持GPT-4V等视觉模型"""

    # 支持视觉的模型列表
    VISION_MODELS = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision",
        "gpt-4-1106-vision-preview", "gpt-4-0125-preview",
    ]

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)

        if not OPENAI_AVAILABLE:
            raise ImportError("请安装openai包: pip install openai>=1.0.0")

        # 优先从环境变量读取
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "gpt-4o")
        self.timeout = config.get("timeout", 30)

        try:
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )
            self.async_client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )
        except Exception as e:
            logger.error(f"[OpenAIProvider] 客户端创建失败: {e}")
            raise ProviderConfigError(f"OpenAI客户端创建失败: {e}") from e

    def get_capabilities(self) -> ProviderCapabilities:
        """返回OpenAI Provider的能力声明"""
        # 检查当前模型是否支持视觉
        model_lower = self.model.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)

        return ProviderCapabilities(
            streaming=True,
            vision=has_vision,  # 根据模型决定是否支持视觉
            function_calling=True,  # OpenAI支持函数调用
            max_context_length=128000 if "gpt-4" in model_lower else 16385
        )

    def validate_config(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "api_key不能为空，请设置OPENAI_API_KEY环境变量"
        if not self.model:
            return False, "model不能为空"
        return True, ""

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        try:
            params = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 1024),
                "top_p": kwargs.get("top_p", 1.0),
            }
            params = {k: v for k, v in params.items() if v is not None}

            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content

        except openai.AuthenticationError as e:
            self._set_error(f"API key无效: {e}")
            raise ProviderNotAvailableError("API key无效") from e
        except openai.RateLimitError as e:
            self._set_error(f"速率限制: {e}")
            raise ProviderNotAvailableError("请求过于频繁") from e
        except Exception as e:
            self._set_error(str(e))
            logger.error(f"[OpenAIProvider] 调用失败: {e}")
            raise

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        try:
            params = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 1024),
                "top_p": kwargs.get("top_p", 1.0),
            }
            params = {k: v for k, v in params.items() if v is not None}

            response = await self.async_client.chat.completions.create(**params)
            return response.choices[0].message.content

        except openai.AuthenticationError as e:
            self._set_error(f"API key无效: {e}")
            raise ProviderNotAvailableError("API key无效") from e
        except openai.RateLimitError as e:
            self._set_error(f"速率限制: {e}")
            raise ProviderNotAvailableError("请求过于频繁") from e
        except Exception as e:
            self._set_error(str(e))
            logger.error(f"[OpenAIProvider] 异步调用失败: {e}")
            raise

    async def chat_stream_async(self, messages: list[dict[str, str]], **kwargs):
        """真流式聊天对话 - 使用OpenAI原生stream=True"""
        try:
            params = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 1024),
                "top_p": kwargs.get("top_p", 1.0),
                "stream": True,
            }
            params = {k: v for k, v in params.items() if v is not None}

            stream = await self.async_client.chat.completions.create(**params)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except openai.AuthenticationError as e:
            self._set_error(f"API key无效: {e}")
            raise ProviderNotAvailableError("API key无效") from e
        except openai.RateLimitError as e:
            self._set_error(f"速率限制: {e}")
            raise ProviderNotAvailableError("请求过于频繁") from e
        except Exception as e:
            self._set_error(str(e))
            logger.error(f"[OpenAIProvider] 流式调用失败: {e}")
            raise

    def is_available(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception as e:
            logger.warning(f"[OpenAIProvider] 服务可用性检查失败: {e}")
            return False

    def get_model_list(self) -> list[str]:
        try:
            models = self.client.models.list()
            return [m.id for m in models.data if "gpt" in m.id.lower()]
        except Exception as e:
            logger.error(f"[OpenAIProvider] 获取模型列表失败: {e}")
            return [self.model]

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "openai",
            "base_url": self.base_url,
            "model": self.model,
            "api_key_masked": self._mask_api_key(self.api_key) if self.api_key else None,
            "vision_capable": self.get_capabilities().vision,
        }
