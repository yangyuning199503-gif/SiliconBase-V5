"""
World Model 模块 - 硅基生命世界模型

提供对世界状态的预测和学习能力
"""

# 从代理模块导入主要接口，支持延迟加载和优雅降级
try:
    from core.world_model.world_model_proxy import (
        WorldModel,
        get_world_model,
        get_world_model_status,
        is_torch_available,
    )
    from core.world_model.world_model import (
        WorldModelManager,
        get_world_model_manager,
    )
except ImportError as e:
    # 如果代理模块也导入失败，提供最小化降级
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"[WorldModel] 模块导入失败: {e}")

    # 提供占位函数
    def get_world_model(*args, **kwargs):
        """降级实现 - 返回None表示世界模型不可用"""
        return None

    def get_world_model_status():
        """降级实现 - 返回不可用状态"""
        return {"available": False, "error": "Module import failed"}

    def is_torch_available():
        """降级实现 - 返回False"""
        return False

    def get_world_model_manager(*args, **kwargs):
        """降级实现 - 返回None表示世界模型管理器不可用"""
        return None

    WorldModel = None
    WorldModelManager = None

__all__ = [
    "get_world_model",
    "get_world_model_status",
    "WorldModel",
    "is_torch_available",
    "WorldModelManager",
    "get_world_model_manager",
]
