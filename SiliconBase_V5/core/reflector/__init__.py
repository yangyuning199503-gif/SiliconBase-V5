#!/usr/bin/env python3
"""
Reflector 模块 - SiliconBase V5
反思系统 - 贝叶斯反思引擎

功能：
- 反思执行过程
- 提取策略模式
- 贝叶斯信念更新
- 反思质量评估
"""

from .reflector import (
    ReflectionLevel,
    ReflectionTrigger,
    Reflector,
    assess_reflection_quality,
    extract_pattern_from_success,
    get_belief_confidence,
    get_reflection_context,
    get_reflector,
    get_strategy_recommendation,
    get_task_strategy_advice,
    quick_reflect,
    reflect_after_success,
    reflect_before_action,
    reflect_multi_dimension,
)

__all__ = [
    'Reflector',
    'get_reflector',
    'get_reflection_context',
    'get_belief_confidence',
    'get_strategy_recommendation',
    'ReflectionLevel',
    'ReflectionTrigger',
    'quick_reflect',
    'get_task_strategy_advice',
    'extract_pattern_from_success',
    'reflect_after_success',
    'reflect_multi_dimension',
    'reflect_before_action',
    'assess_reflection_quality',
]
