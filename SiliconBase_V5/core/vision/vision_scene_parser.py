#!/usr/bin/env python3
"""
vision_scene_parser.py —— 场景分层解析模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二阶段 · 类人视觉感知内核】

职责：利用 Windows API 枚举所有顶层窗口，为每个窗口分配唯一的 scene_id，
      并判断前景/背景层级。

这是模拟人眼"先看全局再看局部"的第一步：
    1. 桌面全局快照 → 枚举所有顶层窗口
    2. 为每个窗口分配场景ID
    3. 标注前景（当前操作目标）vs 背景（次要信息）

输出示例：
    [
        {"scene_id": "scene_01", "title": "网易云音乐", "process": "cloudmusic.exe",
         "rect": [100, 100, 800, 600], "z_order": 0, "is_foreground": True, "level": "前景"},
        {"scene_id": "scene_02", "title": "SiliconBase V5", "process": "chrome.exe",
         "rect": [50, 50, 1200, 800], "z_order": 1, "is_foreground": False, "level": "次前景"},
    ]
"""

import ctypes
from ctypes import wintypes
from typing import Any

user32 = ctypes.windll.user32


def _get_process_name(pid: int) -> str:
    """根据 PID 获取进程名"""
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return "unknown"


def parse_desktop_scenes() -> list[dict[str, Any]]:
    """
    解析桌面场景分层。

    使用 EnumWindows 按 Z-order 枚举所有可见顶层窗口，
    结合 GetForegroundWindow 判断前景窗口。

    Returns:
        场景列表，按层级排序（前景优先，其余保持 Z-order）：
        [
            {
                "scene_id": "scene_01",
                "title": "窗口标题",
                "process": "chrome.exe",
                "rect": [left, top, width, height],
                "z_order": 0,
                "is_foreground": True,
                "level": "前景",
            },
            ...
        ]
    """
    windows: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 10 or h <= 10:
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        windows.append({
            "hwnd": hwnd,
            "title": title,
            "process": _get_process_name(pid.value),
            "pid": pid.value,
            "rect": [rect.left, rect.top, w, h],
        })
        return True

    user32.EnumWindows(_enum_proc, 0)

    # 获取前台窗口句柄
    foreground_hwnd = user32.GetForegroundWindow()

    # 构建场景列表（EnumWindows 按 Z-order 从高到低返回）
    scenes = []
    for idx, win in enumerate(windows):
        is_fg = (win["hwnd"] == foreground_hwnd)
        level = "前景" if is_fg else ("次前景" if idx == 1 else "背景")
        scenes.append({
            "scene_id": f"scene_{idx + 1:02d}",
            "title": win["title"],
            "process": win["process"],
            "rect": win["rect"],
            "z_order": idx,
            "is_foreground": is_fg,
            "level": level,
        })

    # 前景优先，其余保持 Z-order
    scenes.sort(key=lambda s: (0 if s["is_foreground"] else 1, s["z_order"]))
    return scenes
