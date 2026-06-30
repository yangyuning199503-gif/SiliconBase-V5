#!/usr/bin/env python3
"""
Consciousness 代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/consciousness/Consciousness.py
"""

from .consciousness.Consciousness import (
    Consciousness,
    ConsciousnessFactory,
    ConsciousnessService,
    clear_all_user_consciousness,
    get_active_consciousness_users,
    get_consciousness,
    get_consciousness_manager,
    get_consciousness_service,
    remove_consciousness,
)

__all__ = [
    "Consciousness",
    "ConsciousnessService",
    "remove_consciousness",
    "clear_all_user_consciousness",
    "get_consciousness",
    "get_consciousness_manager",
    "get_active_consciousness_users",
    "get_consciousness_service",
    "ConsciousnessFactory",
]
