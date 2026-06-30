#!/usr/bin/env python3
"""
core.cognition - 认知层统一接口
===============================

功能域：感知、意识、元认知、生命体征

统一调用方式:
    from core.cognition import get_self_perception, get_consciousness

    # 获取生命体征
    perception = get_self_perception()
    vitals = perception.get_vital_signs()

    # 启动意识线程
    consciousness = get_consciousness(user_id="user_123")
    await consciousness.start()
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .consciousness import ConsciousnessService
    from .self_perception import SelfPerception
    from .silicon_life import SiliconLifeConsciousness

# =============================================================================
# 单例缓存
# =============================================================================

_self_perception_instance: Optional["SelfPerception"] = None
_consciousness_instances: dict[str, "ConsciousnessService"] = {}
_silicon_life_instances: dict[str, "SiliconLifeConsciousness"] = {}

# =============================================================================
# 工厂函数
# =============================================================================

def get_self_perception() -> "SelfPerception":
    """
    获取自我感知管理器（全局单例）

    功能:
        - 生命体征监测（CPU、内存、磁盘、运行时间）
        - 情绪状态计算（能量、好奇心、满足感、焦虑）
        - 存在感表达
        - 自我介绍生成

    Returns:
        SelfPerception: 自我感知管理器实例
    """
    global _self_perception_instance
    if _self_perception_instance is None:
        from .self_perception import SelfPerception
        _self_perception_instance = SelfPerception()
    return _self_perception_instance


def get_consciousness(user_id: str = "default") -> "ConsciousnessService":
    """
    获取意识服务（按用户实例化）

    Args:
        user_id: 用户唯一标识，默认为"default"

    Returns:
        ConsciousnessService: 意识服务实例
    """
    if user_id not in _consciousness_instances:
        from .consciousness import ConsciousnessService
        _consciousness_instances[user_id] = ConsciousnessService(user_id=user_id)
    return _consciousness_instances[user_id]


def get_silicon_life(user_id: str = "default") -> "SiliconLifeConsciousness":
    """
    获取硅基生命核心（按用户实例化）

    Args:
        user_id: 用户唯一标识，默认为"default"

    Returns:
        SiliconLifeConsciousness: 硅基生命核心实例
    """
    if user_id not in _silicon_life_instances:
        from .silicon_life import SiliconLifeConsciousness
        _silicon_life_instances[user_id] = SiliconLifeConsciousness(user_id=user_id)
    return _silicon_life_instances[user_id]


# =============================================================================
# 导出列表
# =============================================================================

__all__ = [
    "get_self_perception",
    "get_consciousness",
    "get_silicon_life",
]
