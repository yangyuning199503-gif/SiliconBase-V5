#!/usr/bin/env python3
"""
空屏幕捕获实现 - 当 MSS 不可用时的回退
"""

from typing import Any

from ..interfaces import IScreenCapture, Screenshot


class NullScreenCapture(IScreenCapture):
    """空屏幕捕获实现 - 所有方法返回空值"""

    def is_available(self) -> bool:
        return False

    def capture_fullscreen(self) -> Screenshot:
        raise NotImplementedError("屏幕捕获在当前平台不可用")

    def capture_region(self, left: int, top: int, width: int, height: int) -> Screenshot:
        raise NotImplementedError("屏幕捕获在当前平台不可用")

    def capture_window(self, window_id: Any) -> Screenshot | None:
        return None

    def get_screen_size(self) -> tuple[int, int]:
        return (1920, 1080)  # 返回默认值

    def list_monitors(self) -> list[dict[str, Any]]:
        return []
