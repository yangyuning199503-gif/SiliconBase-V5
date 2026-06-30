#!/usr/bin/env python3
"""
模型升级与接入模块 - Model Upgrade & Integration Module

提供多模型路由、成本控制和降级策略等高级功能。

主要组件：
- EnhancedModelRouter: 增强型模型路由器
- CostController: 成本控制器
- FallbackManager: 降级管理器
- ModelUpgradeOrchestrator: 模型升级编排器

使用示例：
    from core.model_upgrade import get_upgrade_orchestrator

    orchestrator = get_upgrade_orchestrator()
    result = await orchestrator.chat_with_smart_upgrade(
        message="帮我分析这个数据",
        task_type="analysis"
    )
"""

from .cost_controller import BudgetLimit, CostAlert, CostController
from .enhanced_router import EnhancedModelRouter, ModelCapability, RoutingStrategy
from .fallback_manager import FallbackChain, FallbackLevel, FallbackManager
from .orchestrator import ModelUpgradeOrchestrator

__all__ = [
    # 增强路由器
    "EnhancedModelRouter",
    "ModelCapability",
    "RoutingStrategy",

    # 成本控制器
    "CostController",
    "BudgetLimit",
    "CostAlert",

    # 降级管理器
    "FallbackManager",
    "FallbackChain",
    "FallbackLevel",

    # 编排器
    "ModelUpgradeOrchestrator",
    "get_upgrade_orchestrator",
]

# 全局单例
_orchestrator: "ModelUpgradeOrchestrator" = None


def get_upgrade_orchestrator() -> "ModelUpgradeOrchestrator":
    """获取模型升级编排器单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ModelUpgradeOrchestrator()
    return _orchestrator
