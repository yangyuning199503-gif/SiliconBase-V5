#!/usr/bin/env python3
"""
基于 MSS 的跨平台屏幕捕获实现

MSS 支持 Windows、macOS、Linux，使用原生 API:
- Windows: GDI
- macOS: Quartz
- Linux: X11/XRandR
"""

import io
from typing import Any

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import contextlib

from ..interfaces import IScreenCapture, Screenshot


class MSSScreenCapture(IScreenCapture):
    """基于 MSS 的屏幕捕获器"""

    def __init__(self):
        self._mss = None
        self._initialized = False

        if MSS_AVAILABLE:
            try:
                self._mss = mss.mss()
                self._initialized = True
            except Exception as e:
                print(f"[MSSScreenCapture] MSS 初始化失败: {e}")

    def is_available(self) -> bool:
        """检查截图功能是否可用"""
        return self._initialized and MSS_AVAILABLE

    def _ensure_initialized(self):
        """确保 MSS 已初始化"""
        if not self._initialized:
            raise RuntimeError("MSS 未初始化，屏幕捕获不可用")

    def capture_fullscreen(self) -> Screenshot:
        """捕获全屏"""
        self._ensure_initialized()

        # 获取主显示器
        monitor = self._mss.monitors[1]  # 索引 1 是主显示器，0 是所有显示器
        return self.capture_region(
            monitor["left"],
            monitor["top"],
            monitor["width"],
            monitor["height"]
        )

    def capture_region(self, left: int, top: int, width: int, height: int) -> Screenshot:
        """捕获指定区域"""
        self._ensure_initialized()

        # 定义区域
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height
        }

        # 截图
        screenshot = self._mss.grab(monitor)

        # 转换为 PNG 字节
        if PIL_AVAILABLE:
            # 使用 PIL 转换
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            data = buffer.getvalue()
        else:
            # 使用 MSS 内置转换
            data = self._mss.shot(output=None)  # 返回字节

        return Screenshot(
            data=data,
            width=width,
            height=height,
            format="png"
        )

    def capture_window(self, window_id: Any) -> Screenshot | None:
        """
        捕获指定窗口

        注意: MSS 不直接支持窗口捕获，需要通过窗口管理器获取窗口位置
        """
        # MSS 本身不支持窗口捕获，需要配合窗口管理器
        # 这里返回 None，实际使用时需要通过窗口管理器获取窗口位置再截图
        print("[MSSScreenCapture] capture_window 需要通过窗口管理器配合实现")
        return None

    def get_screen_size(self) -> tuple[int, int]:
        """获取主屏幕尺寸"""
        self._ensure_initialized()

        monitor = self._mss.monitors[1]  # 主显示器
        return (monitor["width"], monitor["height"])

    def list_monitors(self) -> list[dict[str, Any]]:
        """获取所有显示器信息"""
        self._ensure_initialized()

        monitors = []
        for i, monitor in enumerate(self._mss.monitors):
            monitors.append({
                "id": i,
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"],
                "is_primary": i == 1  # 索引 1 通常为主显示器
            })

        return monitors

    def __del__(self):
        """清理资源"""
        if self._mss:
            with contextlib.suppress(BaseException):
                self._mss.close()
