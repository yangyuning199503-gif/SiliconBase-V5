#!/usr/bin/env python3
"""
AI Provider 抽象基类

[DEPRECATED] 此模块将在v3.0中移除
请使用 core.ai_models.base 和 core.ai_models.exceptions 替代
"""

import asyncio
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# =============================================================================
# 导入新体系的异常，保持兼容性
# =============================================================================
from core.ai_models.exceptions import ConfigurationException, ModelBusException, ProviderUnavailableException


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str
    content: str
    images: list[str] | None = None


@dataclass
class ProviderCapabilities:
    """Provider能力声明"""
    streaming: bool = True
    vision: bool = False  # 是否支持视觉
    function_calling: bool = False  # 是否支持函数调用
    max_context_length: int = 4096  # 最大上下文长度


# =============================================================================
# 旧异常类 - 继承新体系异常以保持兼容性
# =============================================================================

class ProviderError(ModelBusException):
    """
    [DEPRECATED] Provider异常基类

    请使用 ModelBusException 替代
    此类将在v3.0中移除
    """

    def __init__(self, message: str, **kwargs):
        warnings.warn(
            "ProviderError is deprecated. Use ModelBusException from core.ai_models.exceptions instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(message, error_code="DEPRECATED_PROVIDER_ERROR", **kwargs)


class ProviderNotAvailableError(ProviderUnavailableException):
    """
    [DEPRECATED] Provider不可用异常

    请使用 ProviderUnavailableException 替代
    此类将在v3.0中移除
    """

    def __init__(self, message: str = "Provider不可用", **kwargs):
        warnings.warn(
            "ProviderNotAvailableError is deprecated. Use ProviderUnavailableException from core.ai_models.exceptions instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(provider="unknown", reason=message, **kwargs)


class ProviderConfigError(ConfigurationException):
    """
    [DEPRECATED] Provider配置错误异常

    请使用 ConfigurationException 替代
    此类将在v3.0中移除
    """

    def __init__(self, message: str, **kwargs):
        warnings.warn(
            "ProviderConfigError is deprecated. Use ConfigurationException from core.ai_models.exceptions instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(message, **kwargs)


# =============================================================================
# AIProvider基类 - 标记为废弃
# =============================================================================

class AIProvider(ABC):
    """
    [DEPRECATED] AI后端统一接口

    此基类将在v3.0中移除。
    请使用 core.ai_models.base.BaseModelProvider 替代。

    迁移指南:
    1. 将继承从 AIProvider 改为 BaseModelProvider
    2. 将 chat() 方法改为 invoke() 方法
    3. 将 get_capabilities() 改为 capabilities 属性
    4. 将 is_available() 改为异步方法

    示例:
        # 旧代码
        class MyProvider(AIProvider):
            def chat(self, messages, **kwargs):
                return response

        # 新代码
        from core.ai_models.base import BaseModelProvider, ModelConfig

        class MyProvider(BaseModelProvider):
            async def invoke(self, input_data, **kwargs):
                return response
    """

    def __init__(self, config: dict[str, Any]):
        warnings.warn(
            "AIProvider is deprecated. Use BaseModelProvider from core.ai_models.base instead. "
            "See: https://docs.siliconbase.ai/migration/provider-v3",
            DeprecationWarning,
            stacklevel=2
        )
        self.config = config
        self._last_error = None

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """获取Provider能力声明"""
        pass

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """多轮对话"""
        pass

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """异步多轮对话（Phase 4 新增）

        默认桥接：子类如未实现，降级到同步 chat() 的线程池包装。
        但 Phase 4 要求所有高频 Provider 必须提供原生 async 实现。
        """
        return await asyncio.to_thread(self.chat, messages, **kwargs)

    def generate(self, prompt: str, **kwargs) -> str | None:
        """单次生成（默认调用chat实现）"""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    @abstractmethod
    def is_available(self) -> bool:
        """检查后端是否可用"""
        pass

    def get_model_list(self) -> list[str]:
        """获取可用模型列表（可选）"""
        return []

    @abstractmethod
    def get_config(self) -> dict[str, Any]:
        """返回当前配置（不含敏感信息）"""
        pass

    def validate_config(self) -> tuple[bool, str]:
        """验证配置是否有效"""
        return True, ""

    def get_last_error(self) -> str | None:
        """获取最后一次错误信息"""
        return self._last_error

    def _set_error(self, error: str):
        """设置错误信息"""
        self._last_error = error

    def _mask_api_key(self, key: str) -> str:
        """掩码显示API key - 默认实现"""
        if not key or len(key) <= 8:
            return "****"
        return key[:4] + "****" + key[-4:]


class VisionCapabilityMixin:
    """为Provider添加视觉处理能力的Mixin

    [DEPRECATED] 请使用 core.ai_models.providers.vision.base_vision_provider.VisionCapabilityMixin

    使用方法:
        class OllamaProvider(AIProvider, VisionCapabilityMixin):
            def get_capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(
                    streaming=True,
                    vision=True,  # 支持视觉
                    function_calling=False,
                    max_context_length=32768
                )
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "VisionCapabilityMixin from core.providers.base is deprecated. "
            "Use VisionCapabilityMixin from core.ai_models.providers.vision.base_vision_provider instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(*args, **kwargs)

    def prepare_vision_messages(self, text: str, image_b64: str, mime_type: str = "image/jpeg") -> list[dict]:
        """准备支持视觉的messages格式

        Args:
            text: 用户输入的文本
            image_b64: Base64编码的图片数据
            mime_type: 图片MIME类型，默认为image/jpeg

        Returns:
            符合OpenAI视觉API格式的messages列表
        """
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
            ]
        }]

    def prepare_vision_messages_multi(self, text: str, images_b64: list[str], mime_type: str = "image/jpeg") -> list[dict]:
        """准备支持多图视觉的messages格式

        Args:
            text: 用户输入的文本
            images_b64: Base64编码的图片数据列表
            mime_type: 图片MIME类型，默认为image/jpeg

        Returns:
            符合OpenAI视觉API格式的messages列表
        """
        content = [{"type": "text", "text": text}]
        for img_b64 in images_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}
            })
        return [{"role": "user", "content": content}]

    def supports_vision(self) -> bool:
        """检查当前Provider是否支持视觉能力"""
        # 获取ProviderCapabilities需要调用get_capabilities()
        # 这是一个抽象方法，子类必须实现
        capabilities = self.get_capabilities()
        return capabilities.vision

    def extract_image_from_message(self, message: dict[str, Any]) -> str | None:
        """从消息中提取图片Base64数据

        Args:
            message: 包含图片的消息字典

        Returns:
            Base64编码的图片数据，如果没有图片则返回None
        """
        content = message.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:image"):
                        # 提取base64部分
                        return url.split(";base64,")[-1]
        return None
