#!/usr/bin/env python3
"""
PermissionUtils 代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/utils/permission_utils.py
"""

from .utils.permission_utils import (
    check_ai_memory_permission,
    check_memory_permission,
    get_safe_creator,
    is_creator_valid,
    validate_creator_field,
)

__all__ = [
    "check_memory_permission",
    "check_ai_memory_permission",
    "validate_creator_field",
    "is_creator_valid",
    "get_safe_creator",
]
