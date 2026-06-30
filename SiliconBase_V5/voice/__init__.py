#!/usr/bin/env python3
"""
语音模块入口
导出核心类和函数，方便外部导入

ModelBus适配版本 - 修复代理2
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ========== 保留原有导入以兼容旧代码 ==========
try:
    from .interface import VoiceInterface
    _ORIGINAL_INTERFACE_AVAILABLE = True
except ImportError as e:
    VoiceInterface = None
    _ORIGINAL_INTERFACE_AVAILABLE = False
    logger.info(f"[Voice] 原有VoiceInterface未启用: {e}")

try:
    from .voice_assistant import VoiceAssistant, get_voice_assistant
except ImportError as e:
    VoiceAssistant = None
    get_voice_assistant = None
    logger.info(f"[Voice] VoiceAssistant未启用: {e}")

# ========== 新增ModelBus适配版本 ==========
try:
    from .voice_interface_modelbus import VoiceInterfaceModelBus
    _MODELBUS_INTERFACE_AVAILABLE = True
except ImportError as e:
    VoiceInterfaceModelBus = None
    _MODELBUS_INTERFACE_AVAILABLE = False
    logger.warning(f"[Voice] ModelBus适配版本导入失败: {e}")

# 导入ModelBus适配器
try:
    from .model_bus_adapter import VoiceModelBusAdapter, get_voice_adapter, init_voice_adapter
    _MODELBUS_ADAPTER_AVAILABLE = True
except ImportError as e:
    VoiceModelBusAdapter = None
    get_voice_adapter = None
    init_voice_adapter = None
    _MODELBUS_ADAPTER_AVAILABLE = False
    logger.warning(f"[Voice] ModelBus适配器导入失败: {e}")

# ========== 配置选择器 ==========

def get_voice_interface(config: dict[str, Any] = None, force_modelbus: bool = False):
    """
    获取语音接口实例

    根据配置返回合适的实现：
    - 如果启用ModelBus且适配版本可用，返回VoiceInterfaceModelBus
    - 否则返回原有的VoiceInterface

    Args:
        config: 配置字典
        force_modelbus: 是否强制使用ModelBus版本（用于测试）

    Returns:
        VoiceInterface实例（原有或ModelBus版本）

    Raises:
        ImportError: 没有可用的VoiceInterface实现
    """
    config = config or {}

    # 检查是否启用ModelBus
    use_modelbus = force_modelbus or config.get("model_bus", {}).get("enabled", False)
    use_modelbus = use_modelbus or config.get("voice", {}).get("use_modelbus", False)

    if use_modelbus and _MODELBUS_INTERFACE_AVAILABLE:
        logger.info("[Voice] 使用ModelBus适配版本: VoiceInterfaceModelBus")
        return VoiceInterfaceModelBus(config)

    # 回退到原有实现
    if _ORIGINAL_INTERFACE_AVAILABLE and VoiceInterface is not None:
        logger.info("[Voice] 使用原有实现: VoiceInterface")
        return VoiceInterface()

    # 都没有可用
    raise ImportError(
        "没有可用的VoiceInterface实现。"
        "请确保 voice.interface 或 voice.voice_interface_modelbus 可以正常导入。"
    )


def create_voice_interface(
    interface_type: str = "auto",
    config: dict[str, Any] = None
) -> Any:
    """
    创建语音接口实例（显式版本）

    Args:
        interface_type: 接口类型
            - "auto": 自动选择
            - "original": 原有实现
            - "modelbus": ModelBus适配版本
        config: 配置字典

    Returns:
        语音接口实例
    """
    config = config or {}

    if interface_type == "modelbus":
        if not _MODELBUS_INTERFACE_AVAILABLE:
            raise ImportError("ModelBus适配版本不可用")
        return VoiceInterfaceModelBus(config)

    elif interface_type == "original":
        if not _ORIGINAL_INTERFACE_AVAILABLE:
            raise ImportError("原有VoiceInterface不可用")
        return VoiceInterface()

    else:  # auto
        return get_voice_interface(config)


# ========== 向后兼容的快捷函数 ==========

def get_interface(config: dict[str, Any] = None):
    """
    向后兼容的快捷函数

    等价于 get_voice_interface(config)
    """
    return get_voice_interface(config)


# ========== 导出列表 ==========

__all__ = [
    # 原有接口
    "VoiceInterface",
    "VoiceAssistant",
    "get_voice_assistant",

    # ModelBus适配版本
    "VoiceInterfaceModelBus",
    "VoiceModelBusAdapter",
    "get_voice_adapter",
    "init_voice_adapter",

    # 工厂函数
    "get_voice_interface",
    "create_voice_interface",
    "get_interface",
]

# ========== 模块初始化日志 ==========

def _log_module_status():
    """记录模块状态"""
    logger.debug("[Voice] 模块加载状态:")
    logger.debug(f"  - 原有VoiceInterface: {'可用' if _ORIGINAL_INTERFACE_AVAILABLE else '不可用'}")
    logger.debug(f"  - ModelBus适配版本: {'可用' if _MODELBUS_INTERFACE_AVAILABLE else '不可用'}")
    logger.debug(f"  - ModelBus适配器: {'可用' if _MODELBUS_ADAPTER_AVAILABLE else '不可用'}")

_log_module_status()
