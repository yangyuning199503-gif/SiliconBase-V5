"""
SiliconBase V5 - ModelBus模型管理模块

该模块提供统一的模型管理接口，包括：
- ModelBus: 模型总线，管理所有模型槽位
- ModelRegistry: Provider注册表
- ModelBusConfigLoader: 配置加载器
- ModelType: 模型类型枚举
- ModelConfig: 模型配置类
- BaseModelProvider: Provider抽象基类
- 所有异常类
"""

from core.ai_models.base import BaseModelProvider, ModelCapabilities, ModelConfig, ModelType
from core.ai_models.bus import ModelBus
from core.ai_models.config_loader import ModelBusConfigLoader
from core.ai_models.exceptions import (
    AudioEnhancementException,
    AudioException,
    AudioFormatException,
    ConfigurationException,
    EmbeddingException,
    InvokeException,
    ModelBusException,
    ModelLoadException,
    MultimodalException,
    ProviderNotFoundException,
    ProviderUnavailableException,
    RecognitionException,
    RegistryException,
    SlotNotFoundException,
    SynthesisException,
    TimeoutException,
    ValidationException,
)
from core.ai_models.registry import ModelRegistry

__all__ = [
    # 基础类型
    "ModelType",
    "ModelCapabilities",
    "ModelConfig",
    "BaseModelProvider",
    # 核心组件
    "ModelBus",
    "ModelRegistry",
    "ModelBusConfigLoader",
    # 异常类
    "ModelBusException",
    "ProviderNotFoundException",
    "SlotNotFoundException",
    "ConfigurationException",
    "ProviderUnavailableException",
    "InvokeException",
    "ValidationException",
    "RegistryException",
    "TimeoutException",
    "AudioException",
    "ModelLoadException",
    "RecognitionException",
    "SynthesisException",
    "AudioFormatException",
    "AudioEnhancementException",
    "EmbeddingException",
    "MultimodalException",
]
