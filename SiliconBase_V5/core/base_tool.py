#!/usr/bin/env python3
"""
BaseTool 代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/tool/base_tool.py
"""

from .tool.base_tool import BaseTool

__all__ = ["BaseTool"]
