#!/usr/bin/env python3
"""
AI适配器代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/ai/ai_adapter.py
"""

from .ai.ai_adapter import (
    OllamaCompat,
    call_thinker,
    call_with_provider,
    call_with_scene,
    generate_code_async,
    get_current_provider,
    get_provider_info,
    refresh_provider,
    shutdown_executor,
    test_provider_config,
)

__all__ = [
    "call_thinker",
    "call_with_provider",
    "OllamaCompat",
    "get_current_provider",
    "refresh_provider",
    "get_provider_info",
    "test_provider_config",
    "call_with_scene",
    "shutdown_executor",
    "generate_code_async",
]
