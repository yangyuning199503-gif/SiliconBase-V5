"""AI 模块 - 包含 AI 客户端、适配器和 ModelBus 桥接"""

# 导出 ModelBus 桥接，方便外部统一导入
from core.ai.ai_model_bridge import (
    ModelBus,
    ModelConfig,
    ModelRegistry,
    ModelType,
    call_model_bus_sync,
    get_model_bus,
    get_model_bus_stats,
    init_model_bus,
    init_model_bus_async,
    is_model_bus_ready,
    list_registered_providers,
)

__all__ = [
    "init_model_bus",
    "init_model_bus_async",
    "get_model_bus",
    "is_model_bus_ready",
    "call_model_bus_sync",
    "get_model_bus_stats",
    "list_registered_providers",
    "ModelBus",
    "ModelRegistry",
    "ModelType",
    "ModelConfig",
]
