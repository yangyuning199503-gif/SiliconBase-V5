"""
ModelBus类型定义模块

提供统一的类型别名和响应类型定义
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 通用类型别名
ModelInput = str | dict[str, Any] | list[dict[str, Any]]
ModelOutput = str | dict[str, Any] | AsyncIterator[str]
ProviderType = str
SlotId = str


class ResponseStatus(Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    ERROR = "error"
    STREAMING = "streaming"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


@dataclass
class UsageInfo:
    """Token使用信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens


@dataclass
class ModelResponse:
    """统一的模型响应类型"""
    content: str | dict[str, Any] | AsyncIterator[str]
    status: ResponseStatus = ResponseStatus.SUCCESS
    model: str | None = None
    provider: str | None = None
    usage: UsageInfo | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)

    def is_success(self) -> bool:
        """检查响应是否成功"""
        return self.status == ResponseStatus.SUCCESS

    def is_streaming(self) -> bool:
        """检查是否为流式响应"""
        return self.status == ResponseStatus.STREAMING


@dataclass
class HealthStatus:
    """健康检查状态"""
    healthy: bool
    provider: str
    model_type: str
    latency_ms: float = 0.0
    message: str = ""
    last_check: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvokeMetrics:
    """调用指标"""
    slot_id: str
    start_time: float
    end_time: float | None = None
    success: bool = False
    error_type: str | None = None

    @property
    def latency_ms(self) -> float:
        """计算延迟（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000


# 回调函数类型
PreInvokeCallback = Callable[[SlotId, ModelInput], Awaitable[ModelInput]]
PostInvokeCallback = Callable[[SlotId, ModelResponse], Awaitable[ModelResponse]]
ErrorCallback = Callable[[SlotId, Exception], Awaitable[None]]


# Provider工厂函数类型
ProviderFactory = Callable[[Any], Awaitable[Any]]
