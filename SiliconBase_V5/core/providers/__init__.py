#!/usr/bin/env python3
"""
AI Providers 包 - 多后端AI支持

[DEPRECATED] 此包将在v3.0中移除
请使用 core.ai_models.providers 替代

支持：Ollama、OpenAI、Anthropic、Azure OpenAI、DeepSeek、Kimi、通义千问、智谱GLM、豆包等

迁移指南:
    旧代码:
        from core.providers import AIProvider, OllamaProvider

    新代码:
        from core.ai_models.base import BaseModelProvider
        from core.ai_models.providers.llm import OllamaLLMProvider

文档: https://docs.siliconbase.ai/migration/provider-v3
"""

import warnings

# 在首次导入时发出包级别的废弃警告
warnings.warn(
    "core.providers is deprecated and will be removed in v3.0. "
    "Use core.ai_models.providers instead. "
    "See: https://docs.siliconbase.ai/migration/provider-v3",
    DeprecationWarning,
    stacklevel=2
)

# 基础类和异常（已添加废弃标记）
# 适配器（用于向后兼容）
from .adapter import ProviderAdapter, migrate_provider_config
from .ai_provider_factory import AIProviderFactory
from .anthropic_provider import AnthropicProvider
from .base import (
    AIProvider,
    ChatMessage,
    ProviderCapabilities,
    ProviderConfigError,
    ProviderError,
    ProviderNotAvailableError,
    VisionCapabilityMixin,
)
from .custom_provider import CustomProvider

# 具体Provider实现
from .ollama_provider import OllamaProvider
from .openai_compatible_provider import OpenAICompatibleProvider
from .openai_provider import OpenAIProvider

__all__ = [
    # 基础类（已废弃）
    'AIProvider',
    'ProviderCapabilities',
    'ChatMessage',
    'VisionCapabilityMixin',
    # 异常类（已废弃）
    'ProviderError',
    'ProviderNotAvailableError',
    'ProviderConfigError',
    # 适配器
    'ProviderAdapter',
    'migrate_provider_config',
    # Provider实现
    'OllamaProvider',
    'OpenAIProvider',
    'AnthropicProvider',
    'CustomProvider',
    'OpenAICompatibleProvider',
    'AIProviderFactory',
]

# 版本信息
__version__ = "2.0.0-deprecated"
__deprecated__ = True
__migration_guide__ = "https://docs.siliconbase.ai/migration/provider-v3"
