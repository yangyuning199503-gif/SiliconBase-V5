#!/usr/bin/env python3
"""
屏幕 DPI/缩放感知工具
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供 Windows 高 DPI 缩放比例获取和坐标转换。

设计原则：
- 只做坐标转换，不封装业务逻辑
- 截图入口统一接收"逻辑坐标"，内部转换为"物理像素"
- 返回的识别结果坐标统一为"逻辑坐标"，与鼠标/窗口操作一致
"""

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

# 缓存缩放比例，避免重复调用 Win32 API
_SCALE_FACTOR: float | None = None


def set_process_dpi_aware() -> None:
    """设置当前进程为 DPI 感知（每个进程只需一次）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Windows 8.1+ 推荐 PER_MONITOR_AWARENESS， older 用 SetProcessDPIAware
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PerMonitorV2
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        logger.debug(f"[DPI] 设置 DPI 感知失败: {e}")


# 保持向后兼容的旧名称
_ensure_dpi_aware = set_process_dpi_aware


def get_screen_scale_factor() -> float:
    """
    获取主屏幕的缩放比例。

    Returns:
        缩放比例，例如 1.0 表示 100%，1.5 表示 150%
    """
    global _SCALE_FACTOR
    if _SCALE_FACTOR is not None:
        return _SCALE_FACTOR

    if sys.platform != "win32":
        _SCALE_FACTOR = 1.0
        return _SCALE_FACTOR

    _ensure_dpi_aware()

    try:
        import ctypes
        from ctypes import wintypes

        shcore = ctypes.windll.shcore
        shcore.GetScaleFactorForMonitor.argtypes = [wintypes.HMONITOR, ctypes.POINTER(ctypes.c_uint)]
        shcore.GetScaleFactorForMonitor.restype = ctypes.HRESULT

        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR

        hwnd = user32.GetDesktopWindow()
        monitor = user32.MonitorFromWindow(hwnd, 1)  # MONITOR_DEFAULTTOPRIMARY
        scale = ctypes.c_uint(100)
        shcore.GetScaleFactorForMonitor(monitor, ctypes.byref(scale))
        _SCALE_FACTOR = scale.value / 100.0
    except Exception as e:
        logger.debug(f"[DPI] 获取缩放比例失败，回退到 1.0: {e}")
        _SCALE_FACTOR = 1.0

    return _SCALE_FACTOR


def logical_to_physical(region: dict[str, Any]) -> dict[str, Any]:
    """
    将逻辑坐标区域转换为物理像素区域（用于截图）。

    Args:
        region: {"left": int, "top": int, "width": int, "height": int}

    Returns:
        转换后的物理像素区域
    """
    scale = get_screen_scale_factor()
    if scale == 1.0:
        return region

    return {
        "left": int(region["left"] * scale),
        "top": int(region["top"] * scale),
        "width": int(region["width"] * scale),
        "height": int(region["height"] * scale),
    }


def physical_to_logical(region: dict[str, Any]) -> dict[str, Any]:
    """
    将物理像素区域转换为逻辑坐标区域（用于返回结果/鼠标操作）。

    Args:
        region: {"left": int, "top": int, "width": int, "height": int}

    Returns:
        转换后的逻辑坐标区域
    """
    scale = get_screen_scale_factor()
    if scale == 1.0:
        return region

    return {
        "left": int(region["left"] / scale),
        "top": int(region["top"] / scale),
        "width": int(region["width"] / scale),
        "height": int(region["height"] / scale),
    }


def scale_point(x: int, y: int, to_physical: bool = True) -> tuple[int, int]:
    """
    缩放单个坐标点。

    Args:
        x, y: 坐标
        to_physical: True 表示逻辑→物理，False 表示物理→逻辑

    Returns:
        缩放后的坐标
    """
    scale = get_screen_scale_factor()
    if scale == 1.0:
        return x, y
    if to_physical:
        return int(x * scale), int(y * scale)
    return int(x / scale), int(y / scale)
