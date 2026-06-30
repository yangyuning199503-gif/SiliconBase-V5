#!/usr/bin/env python3
"""
Anthropic Claude Provider
"""

import os
from typing import Any

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from core.logger import logger

from .base import (
    AIProvider,
    ProviderCapabilities,
    ProviderConfigError,
    ProviderNotAvailableError,
    VisionCapabilityMixin,
)


class AnthropicProvider(AIProvider, VisionCapabilityMixin):
    """Anthropic Claude后端实现 - 支持Claude 3视觉能力"""

    # 支持视觉的模型列表（所有Claude 3系列都支持视觉）
    VISION_MODELS = [
        "claude-3", "claude-3-5"
    ]

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)

        if not ANTHROPIC_AVAILABLE:
            raise ImportError("请安装anthropic包: pip install anthropic")

        self.api_key = config.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
        self.model = config.get("model", "claude-3-opus-20240229")
        self.timeout = config.get("timeout", 30)

        try:
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=self.timeout
            )
            self.async_client = anthropic.AsyncAnthropic(
                api_key=self.api_key,
                timeout=self.timeout
            )
        except Exception as e:
            logger.error(f"[AnthropicProvider] 客户端创建失败: {e}")
            raise ProviderConfigError(f"Anthropic客户端创建失败: {e}") from e

    def get_capabilities(self) -> ProviderCapabilities:
        """返回Anthropic Provider的能力声明"""
        # 检查当前模型是否支持视觉（Claude 3系列都支持）
        model_lower = self.model.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)

        return ProviderCapabilities(
            streaming=True,
            vision=has_vision,  # Claude 3系列支持视觉
            function_calling=True,  # Claude 3支持函数调用
            max_context_length=200000 if "opus" in model_lower else 180000
        )

    def validate_config(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "api_key不能为空，请设置ANTHROPIC_API_KEY环境变量"
        if not self.model:
            return False, "model不能为空"
        return True, ""

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        try:
            # 分离system消息
            system_message = None
            chat_messages = []

            for msg in messages:
                if msg.get("role") == "system":
                    system_message = msg.get("content", "")
                else:
                    # 处理可能包含图片的消息
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # 视觉格式消息
                        chat_messages.append({
                            "role": msg.get("role", "user"),
                            "content": content
                        })
                    else:
                        chat_messages.append({
                            "role": msg.get("role", "user"),
                            "content": content
                        })

            params = {
                "model": kwargs.get("model", self.model),
                "messages": chat_messages,
                "max_tokens": kwargs.get("max_tokens", 1024),
                "temperature": kwargs.get("temperature", 0.7),
            }

            if system_message:
                params["system"] = system_message

            params = {k: v for k, v in params.items() if v is not None}

            response = self.client.messages.create(**params)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return content

        except anthropic.AuthenticationError as e:
            self._set_error(f"API key无效: {e}")
            raise ProviderNotAvailableError("API key无效") from e
        except Exception as e:
            self._set_error(str(e))
            logger.error(f"[AnthropicProvider] 调用失败: {e}")
            raise

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        try:
            # 分离system消息
            system_message = None
            chat_messages = []

            for msg in messages:
                if msg.get("role") == "system":
                    system_message = msg.get("content", "")
                else:
                    # 处理可能包含图片的消息
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # 视觉格式消息
                        chat_messages.append({
                            "role": msg.get("role", "user"),
                            "content": content
                        })
                    else:
                        chat_messages.append({
                            "role": msg.get("role", "user"),
                            "content": content
                        })

            params = {
                "model": kwargs.get("model", self.model),
                "messages": chat_messages,
                "max_tokens": kwargs.get("max_tokens", 1024),
                "temperature": kwargs.get("temperature", 0.7),
            }

            if system_message:
                params["system"] = system_message

            params = {k: v for k, v in params.items() if v is not None}

            response = await self.async_client.messages.create(**params)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return content

        except anthropic.AuthenticationError as e:
            self._set_error(f"API key无效: {e}")
            raise ProviderNotAvailableError("API key无效") from e
        except Exception as e:
            self._set_error(str(e))
            logger.error(f"[AnthropicProvider] 异步调用失败: {e}")
            raise

    def is_available(self) -> bool:
        """检查 Anthropic 服务是否可用"""
        if not self.api_key or self.api_key == "your-anthropic-api-key":
            return False
        try:
            # 尝试列出模型来验证连接
            self.client.models.list()
            return True
        except Exception as e:
            logger.debug(f"[AnthropicProvider] 可用性检查失败: {e}")
            return False

    def get_model_list(self) -> list[str]:
        return [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-3-5-sonnet-20240620"
        ]

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "anthropic",
            "model": self.model,
            "api_key_masked": self._mask_api_key(self.api_key) if self.api_key else None,
            "vision_capable": self.get_capabilities().vision,
        }

    # ========== 视觉能力特定方法 ==========

    def prepare_vision_messages(self, text: str, image_b64: str, mime_type: str = "image/jpeg") -> list[dict]:
        """
        为Anthropic准备支持视觉的messages格式

        Anthropic使用特定的视觉格式：
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "描述图片"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "base64_encoded_image"
                    }
                }
            ]
        }
        """
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_b64
                    }
                }
            ]
        }]
