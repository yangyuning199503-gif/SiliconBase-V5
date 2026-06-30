#!/usr/bin/env python3
"""
窗口监控 - 使用 Windows 事件钩子实现实时监听
如果钩子设置失败，自动回退到轮询模式
2026-02-21 修复：EnumWindows 回调添加异常处理和显式返回
"""
import ctypes
import threading
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process

from core.logger import logger
from core.sync.event_bus import event_bus
from sensors.system.bus import PerceptionData, bus

# 定义窗口事件回调函数类型
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                   wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

class WindowMonitor:
    _instance = None
    _creation_lock = threading.Lock()
    _thread = None
    _running = False
    _hook = None
    _hook_thread = None

    def __new__(cls):
        if cls._instance is None:
            with cls._creation_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_hook, daemon=True)
        self._thread.start()
        logger.info("窗口监控（事件钩子）已启动")

    def stop(self):
        self._running = False
        if self._hook:
            ctypes.windll.user32.UnhookWinEvent(self._hook)
            self._hook = None
        if self._thread:
            self._thread.join(timeout=2)

    def _win_event_proc(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        """窗口事件回调函数 - 添加异常保护和返回"""
        try:
            if not win32gui.IsWindow(hwnd):
                return  # 这里实际上是无返回值的回调，但不会崩溃
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            rect = win32gui.GetWindowRect(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                                              False, pid)
                exe_name = win32process.GetModuleFileNameEx(handle, 0)
                win32api.CloseHandle(handle)
            except Exception:
                exe_name = "未知"
            window_info = {
                "hwnd": hwnd,
                "title": title,
                "rect": rect,
                "pid": pid,
                "process": exe_name.split("\\")[-1] if exe_name else "",
                "visible": True,
                "enabled": win32gui.IsWindowEnabled(hwnd)
            }
            data = PerceptionData(
                source="window",
                timestamp=time.time(),
                confidence=0.95,
                content={"windows": [window_info]}
            )
            bus.publish(data)

            # 向event_bus发布窗口变化事件（用于弱连接）
            event_bus.emit("context:window_changed", {
                "type": "WINDOW_FOCUSED",
                "title": title,
                "app_name": exe_name.split("\\")[-1] if exe_name else "",
                "pid": pid,
                "keywords": self._extract_keywords(title)
            })
        except Exception as e:
            logger.error(f"窗口事件回调异常: {e}")
        # 注意：该回调由系统调用，无需返回值

    def _run_hook(self):
        """设置窗口事件钩子"""
        WinEventProc = WINEVENTPROC(self._win_event_proc)
        self._hook = ctypes.windll.user32.SetWinEventHook(
            win32con.EVENT_OBJECT_CREATE, win32con.EVENT_OBJECT_DESTROY,
            0, WinEventProc, 0, 0, win32con.WINEVENT_OUTOFCONTEXT
        )
        if not self._hook:
            logger.error("设置窗口事件钩子失败，回退到轮询模式")
            self._run_polling()
            return

        msg = wintypes.MSG()
        while self._running:
            ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret == -1:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        ctypes.windll.user32.UnhookWinEvent(self._hook)

    def _run_polling(self):
        """回退到轮询模式"""
        while self._running:
            try:
                windows = self._enum_windows()
                data = PerceptionData(
                    source="window",
                    timestamp=time.time(),
                    confidence=0.95,
                    content={"windows": windows[:20]}
                )
                bus.publish(data)
            except Exception as e:
                logger.error(f"窗口监控轮询异常: {e}")
            time.sleep(1)

    def _enum_windows(self):
        windows = []
        def callback(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "class": win32gui.GetClassName(hwnd),
                        })
            except Exception:
                pass
            return True  # 必须返回 True 继续枚举
        win32gui.EnumWindows(callback, None)
        return windows

    def _extract_keywords(self, title: str) -> list:
        """从窗口标题提取关键词"""
        keywords = []
        # 常见应用关键词映射
        app_keywords = {
            "chrome": ["浏览器", "网页", "搜索"],
            "edge": ["浏览器", "网页", "搜索"],
            "firefox": ["浏览器", "网页", "搜索"],
            "code": ["代码", "编程", "开发"],
            "visual studio": ["代码", "编程", "开发"],
            "word": ["文档", "写作", "办公"],
            "excel": ["表格", "数据", "办公"],
            "powerpoint": ["演示", "PPT", "办公"],
            "notion": ["笔记", "知识管理"],
            "obsidian": ["笔记", "知识管理"],
            "slack": ["沟通", "团队协作"],
            "teams": ["会议", "沟通", "协作"],
            "zoom": ["会议", "视频"],
            "discord": ["社交", "沟通"],
        }

        title_lower = title.lower()
        for app, keys in app_keywords.items():
            if app in title_lower:
                keywords.extend(keys)

        # 去重
        return list(set(keywords)) if keywords else ["通用应用"]

window_monitor = WindowMonitor()
