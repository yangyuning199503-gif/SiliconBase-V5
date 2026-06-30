#!/usr/bin/env python3
"""
空窗口管理实现 - 当平台窗口管理不可用时回退
"""

from typing import Any

from ..interfaces import IWindowManager, WindowInfo


class NullWindowManager(IWindowManager):
    """空窗口管理实现 - 所有方法返回空值或 False"""

    def is_available(self) -> bool:
        return False

    def list_windows(self) -> list[WindowInfo]:
        return []

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        return None

    def activate_window(self, window_id: Any) -> bool:
        return False

    def minimize_window(self, window_id: Any) -> bool:
        return False

    def maximize_window(self, window_id: Any) -> bool:
        return False

    def restore_window(self, window_id: Any) -> bool:
        return False

    def get_active_window(self) -> WindowInfo | None:
        return None

    def move_window(self, window_id: Any, x: int, y: int, width: int, height: int) -> bool:
        return False

    def close_window(self, window_id: Any) -> bool:
        return False
