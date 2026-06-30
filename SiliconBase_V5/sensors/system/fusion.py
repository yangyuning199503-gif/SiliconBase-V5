#!/usr/bin/env python3
"""
四眼融合核心 - 窗口就绪状态机
"""
import time

import win32gui

from core.error_codes import PRE_001_WINDOW_TIMEOUT, format_error
from sensors.system.bus import bus


def is_window_ready(hwnd: int) -> bool:
    if not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsWindowVisible(hwnd):
        return False
    return win32gui.IsWindowEnabled(hwnd)


def find_window_by_process_name(process_name: str) -> int | None:
    recent = bus.get_latest(source="window", seconds=2.0)
    for d in recent:
        for win in d.content.get("windows", []):
            if win.get("process", "").lower() == process_name.lower():
                return win.get("hwnd")
    import win32api
    import win32con
    import win32gui
    import win32process
    hwnds = []
    def enum_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                                              False, pid)
                exe = win32process.GetModuleFileNameEx(handle, 0)
                win32api.CloseHandle(handle)
                if exe and exe.lower().endswith(process_name.lower()):
                    hwnds.append(hwnd)
            except Exception:
                pass
        return True
    win32gui.EnumWindows(enum_callback, None)
    return hwnds[0] if hwnds else None


def wait_for_window_ready(process_name: str, timeout: int = 5) -> dict:
    start = time.time()
    hwnd = None

    while time.time() - start < timeout:
        hwnd = find_window_by_process_name(process_name)
        if not hwnd:
            time.sleep(0.2)
            continue

        if is_window_ready(hwnd):
            return {
                "success": True,
                "hwnd": hwnd,
                "state": "窗口就绪",
                "error_code": "",
                "user_message": f"窗口已就绪 (hwnd={hwnd})"
            }
        else:
            pass
        time.sleep(0.2)

    return format_error(PRE_001_WINDOW_TIMEOUT, software=process_name)
