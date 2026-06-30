#!/usr/bin/env python3
"""
工具管理器代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/tool/tool_manager.py
"""

from .tool.tool_manager import (
    ToolManager,
    tool_manager,
)

__all__ = [
    "tool_manager",
    "ToolManager",
]
