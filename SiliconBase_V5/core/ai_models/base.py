"""
ModelBus基础模块

定义ModelBus的核心抽象基类和基础数据类型
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# 配置日志
logger = logging.getLogger(__name__)


class ModelType(Enum):
    """模型类型枚举"""
    LLM = auto()
    VISION = auto()
    AUDIO_ASR = auto()
    AUDIO_TTS = auto()
    AUDIO_ENHANCE = auto()
    EMBEDDING = auto()
    MULTIMODAL = auto()

    def __str__(self) -> str:
        return self.name


class ModelCapabilities:
    """模型能力描述类"""

    def __init__(
        self,
        streaming: bool = False,
        vision: bool = False,
        audio_input: bool = False,
        audio_output: bool = False,
        function_calling: bool = False,
        max_context_length: int = 4096,
        supports_batch: bool = False,
        supports_system_prompt: bool = True,
        supports_temperature: bool = True,
        supports_max_tokens: bool = True
    ):
        self.streaming: bool = streaming
        self.vision: bool = vision
        self.audio_input: bool = audio_input
        self.audio_output: bool = audio_output
        self.function_calling: bool = function_calling
        self.max_context_length: int = max_context_length
        self.supports_batch: bool = supports_batch
        self.supports_system_prompt: bool = supports_system_prompt
        self.supports_temperature: bool = supports_temperature
        self.supports_max_tokens: bool = supports_max_tokens

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "streaming": self.streaming,
            "vision": self.vision,
            "audio_input": self.audio_input,
            "audio_output": self.audio_output,
            "function_calling": self.function_calling,
            "max_context_length": self.max_context_length,
            "supports_batch": self.supports_batch,
            "supports_system_prompt": self.supports_system_prompt,
            "supports_temperature": self.supports_temperature,
            "supports_max_tokens": self.supports_max_tokens
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelCapabilities":
        """从字典创建"""
        return cls(**data)


@dataclass
class ModelConfig:
    """模型配置数据类"""
    provider: str
    model_name: str
    base_url: str | None = None
    api_key: str | None = None
    timeout: int = 120
    max_retries: int = 2
    retry_delay: float = 1.0
    extra_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证配置"""
        if not self.provider:
            error_msg = "ModelConfig.provider 不能为空"
            logger.error(f"[ModelConfig] 验证失败: {error_msg}")
            raise ValueError(error_msg)

        if not self.model_name:
            error_msg = "ModelConfig.model_name 不能为空"
            logger.error(f"[ModelConfig] 验证失败: {error_msg}")
            raise ValueError(error_msg)

        if self.timeout <= 0:
            error_msg = f"ModelConfig.timeout 必须大于0, 当前值: {self.timeout}"
            logger.error(f"[ModelConfig] 验证失败: {error_msg}")
            raise ValueError(error_msg)

        if self.max_retries < 0:
            error_msg = f"ModelConfig.max_retries 不能为负数, 当前值: {self.max_retries}"
            logger.error(f"[ModelConfig] 验证失败: {error_msg}")
            raise ValueError(error_msg)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（隐藏敏感信息）"""
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key": "***" if self.api_key else None,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "extra_params": self.extra_params
        }


class BaseModelProvider(ABC):
    """
    模型Provider抽象基类

    所有具体的Provider实现必须继承此类
    """

    def __init__(self, config: ModelConfig):
        """
        初始化Provider

        Args:
            config: 模型配置
        """
        if config is None:
            error_msg = "config 不能为None"
            logger.error(f"[{self.__class__.__name__}] 初始化失败: {error_msg}")
            raise ValueError(error_msg)

        self.config: ModelConfig = config
        self._capabilities: ModelCapabilities = ModelCapabilities()
        self._initialized: bool = False
        self._initialized_at: float | None = None

        logger.info(f"[{self.__class__.__name__}] 实例创建: provider={config.provider}, model={config.model_name}")

    @property
    @abstractmethod
    def model_type(self) -> ModelType:
        """
        返回模型类型

        Returns:
            ModelType: 此Provider支持的模型类型
        """
        pass

    @property
    def capabilities(self) -> ModelCapabilities:
        """
        获取模型能力

        Returns:
            ModelCapabilities: 模型能力描述
        """
        return self._capabilities

    @property
    def is_initialized(self) -> bool:
        """
        检查是否已初始化

        Returns:
            bool: 是否已完成初始化
        """
        return self._initialized

    @abstractmethod
    async def initialize(self) -> bool:
        """
        异步初始化Provider

        Returns:
            bool: 初始化是否成功

        Raises:
            Exception: 初始化失败时抛出异常
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: Provider是否可用
        """
        pass

    @abstractmethod
    async def invoke(
        self,
        input_data: str | dict | list,
        **kwargs
    ) -> str | dict | AsyncIterator:
        """
        调用模型

        Args:
            input_data: 输入数据，可以是字符串、字典或列表
            **kwargs: 额外参数

        Returns:
            模型输出，可能是字符串、字典或异步迭代器（流式输出）

        Raises:
            Exception: 调用失败时抛出异常
        """
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            Dict: 包含健康状态信息的字典
            {
                "healthy": bool,
                "latency_ms": float,
                "message": str,
                "details": Dict
            }
        """
        pass

    async def cleanup(self):
        """
        清理资源

        子类可以覆盖此方法以释放资源
        """
        logger.info(f"[{self.__class__.__name__}] 资源清理: provider={self.config.provider}")
        self._initialized = False
        self._initialized_at = None

    def _mark_initialized(self):
        """标记为已初始化"""
        self._initialized = True
        self._initialized_at = time.time()
        logger.info(f"[{self.__class__.__name__}] 初始化完成: provider={self.config.provider}")

    def _ensure_initialized(self):
        """
        确保已初始化

        Raises:
            RuntimeError: 如果未初始化则抛出
        """
        if not self._initialized:
            error_msg = f"Provider {self.config.provider} 尚未初始化"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise RuntimeError(error_msg)


@dataclass
class ProviderInfo:
    """Provider信息数据类"""
    provider_type: str
    model_type: ModelType
    provider_class: type
    description: str = ""
    version: str = "1.0.0"
    registered_at: float = field(default_factory=time.time)
