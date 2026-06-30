#!/usr/bin/env python3
"""
SiliconBase V5 跨平台抽象层

提供统一的跨平台接口，使V5可以在Windows、macOS、Linux上运行。

使用方法:
    from core.platform_adapter import platform_factory

    # 获取进程管理器
    process_mgr = platform_factory.get_process_manager()

    # 获取屏幕捕获器
    screen_capture = platform_factory.get_screen_capture()

    # 获取窗口管理器
    window_mgr = platform_factory.get_window_manager()
"""

from .factory import PlatformFactory, platform_factory
from .interfaces import PlatformType
from .paths import PathResolver, get_default_resolver, resolve_btc_system_path

__all__ = [
    'PlatformFactory',
    'platform_factory',
    'PlatformType',
    'PathResolver',
    'resolve_btc_system_path',
    'get_default_resolver',
]
