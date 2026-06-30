#!/usr/bin/env python3
"""
WorkModeManager 代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/mode/work_mode_manager.py
"""

from .mode.work_mode_manager import (
    WorkMode,
    WorkModeManager,
    get_work_mode_manager,
)

__all__ = ["WorkModeManager", "get_work_mode_manager", "WorkMode"]
