#!/usr/bin/env python3
"""
感知上下文触发器 - 带智能节制机制
防止频繁打扰用户
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

from core.logger import logger


class ContextType(Enum):
    """上下文类型"""
    APP_OPENED = "app_opened"
    FILE_OPENED = "file_opened"
    WINDOW_FOCUSED = "window_focused"
    PROCESS_STARTED = "process_started"
    IDLE_DETECTED = "idle_detected"
    PATTERN_DETECTED = "pattern_detected"


@dataclass
class ContextEvent:
    """上下文事件"""
    type: ContextType
    timestamp: float
    source: str
    keywords: list[str]
    raw_data: dict
    session_group: str = ""  # 会话分组，同组事件合并

    def to_prompt(self) -> str:
        if self.type == ContextType.WINDOW_FOCUSED:
            app = self.raw_data.get("app_name", "某个应用")
            return f"用户正在使用{app}"
        elif self.type == ContextType.IDLE_DETECTED:
            duration = self.raw_data.get("idle_seconds", 0)
            return f"用户空闲了{int(duration/60)}分钟"
        return "用户正在使用电脑"


class SessionTracker:
    """
    会话跟踪器
    解决"打开A又打开B又打开C"的频繁触发问题
    """

    def __init__(self, session_timeout: int = 300):
        """
        Args:
            session_timeout: 会话超时时间（秒），默认5分钟
        """
        self._session_timeout = session_timeout
        self._current_session: dict | None = None
        self._session_start_time: float = 0
        self._session_events: set[str] = set()  # 本会话已触发的事件类型
        self._lock = threading.Lock()

    def start_new_session(self, trigger_event: ContextEvent):
        """开始新会话"""
        with self._lock:
            self._current_session = {
                "start_time": time.time(),
                "trigger": trigger_event,
                "events": []
            }
            self._session_start_time = time.time()
            self._session_events.clear()

    def should_allow_event(self, event: ContextEvent) -> bool:
        """
        检查是否应该允许事件触发

        规则：
        1. 新会话（超时或事件类型完全不同）→ 允许
        2. 同一会话内，同类事件 → 拒绝（防刷屏）
        3. 同一会话内，不同类型 → 收集但不立即触发（延迟合并）
        """
        with self._lock:
            now = time.time()

            # 检查会话是否过期
            if self._current_session is None or \
               (now - self._session_start_time) > self._session_timeout:
                # 会话过期，开始新会话
                self.start_new_session(event)
                return True

            # 生成事件标识
            event_signature = f"{event.type.value}:{event.session_group}"

            # 检查本会话是否已触发过同类事件
            if event_signature in self._session_events:
                logger.debug(f"[SessionTracker] 同会话内重复事件被拒绝: {event_signature}")
                return False

            # 允许触发，并记录
            self._session_events.add(event_signature)
            self._current_session["events"].append(event)
            return True

    def get_session_summary(self) -> str | None:
        """获取当前会话的摘要（用于合并多个事件）"""
        with self._lock:
            if not self._current_session or len(self._current_session["events"]) < 2:
                return None

            events = self._current_session["events"]
            apps = [e.raw_data.get("app_name", "") for e in events if e.type == ContextType.WINDOW_FOCUSED]

            if len(apps) >= 3:
                return f"用户在多个应用间切换：{' → '.join(apps[-3:])}"
            return None

    def end_session(self):
        """结束当前会话"""
        with self._lock:
            self._current_session = None
            self._session_events.clear()


class ContextTriggerEngine:
    """上下文触发引擎 - 智能节制版"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._session_tracker = SessionTracker(session_timeout=300)  # 5分钟会话

        # 应用分类映射（用于会话分组）
        self._app_groups = {
            "办公": ["excel", "word", "powerpoint", "wps", "document"],
            "开发": ["vscode", "pycharm", "idea", "sublime", "chrome"],
            "娱乐": ["steam", "game", "video", "music", "player"],
            "通讯": ["wechat", "qq", "slack", "teams", "zoom"],
        }

        # 已说过的话（防重复）
        self._recent_messages: deque = deque(maxlen=20)  # 最近20条

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("[ContextTrigger] 触发引擎已启动（智能节制版）")

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        while self._running:
            try:
                self._check_window_change()
                self._check_idle()
            except Exception as e:
                logger.error(f"[ContextTrigger] 监测异常: {e}")
            time.sleep(3)  # 3秒检查一次（降低频率）

    def _check_window_change(self):
        """检查窗口变化 - 带会话节制"""
        try:
            from sensors.system.window_monitor import window_monitor
            current_window = window_monitor.get_active_window()

            if not current_window:
                return

            window_title = current_window.get("title", "")
            window_class = current_window.get("class", "").lower()
            app_name = self._extract_app_name(window_title, window_class)

            # 确定会话分组
            session_group = self._get_app_group(app_name)

            # 创建事件
            event = ContextEvent(
                type=ContextType.WINDOW_FOCUSED,
                timestamp=time.time(),
                source="window_monitor",
                keywords=self._extract_keywords(window_title),
                raw_data={
                    "window_title": window_title,
                    "window_class": window_class,
                    "app_name": app_name
                },
                session_group=session_group
            )

            # 会话级节制检查
            if not self._session_tracker.should_allow_event(event):
                return

            # 检查是否有合并摘要（用户频繁切换应用）
            summary = self._session_tracker.get_session_summary()
            if summary:
                # 生成合并事件
                event.raw_data["summary"] = summary
                event.raw_data["is_merged"] = True

            self._send_to_weak_connection(event)

        except Exception as e:
            logger.debug(f"检查窗口变化失败: {e}")

    def _check_idle(self):
        """检查用户空闲"""
        try:
            from core.global_state import last_user_input_time
            idle_time = time.time() - last_user_input_time

            # 空闲10分钟才触发（避免太频繁）
            if idle_time > 600:
                event = ContextEvent(
                    type=ContextType.IDLE_DETECTED,
                    timestamp=time.time(),
                    source="global_state",
                    keywords=["空闲", "休息"],
                    raw_data={"idle_seconds": idle_time},
                    session_group="idle"
                )

                # 空闲事件也需要会话节制
                if self._session_tracker.should_allow_event(event):
                    self._send_to_weak_connection(event)

        except Exception as e:
            logger.debug(f"检查空闲失败: {e}")

    def _extract_app_name(self, title: str, window_class: str) -> str:
        """提取应用名称"""
        class_to_app = {
            "excel": "Excel",
            "winword": "Word",
            "powerpnt": "PowerPoint",
            "chrome": "Chrome",
            "code": "VSCode",
        }

        for key, name in class_to_app.items():
            if key in window_class or key in title.lower():
                return name

        return title.split("-")[-1].strip() if "-" in title else "应用"

    def _get_app_group(self, app_name: str) -> str:
        """获取应用分组"""
        app_lower = app_name.lower()
        for group, apps in self._app_groups.items():
            if any(a in app_lower for a in apps):
                return group
        return "其他"

    def _extract_keywords(self, text: str) -> list[str]:
        """提取关键词"""
        text_lower = text.lower()
        keywords = []

        keyword_map = {
            "报表": ["报表", "统计", "数据", "分析", "excel"],
            "代码": ["代码", "编程", "开发", "调试", "python"],
            "文档": ["文档", "写作", "编辑", "word"],
            "表格": ["表格", "数据录入"],
            "会议": ["会议", "zoom", "teams", "腾讯会议"],
        }

        for category, words in keyword_map.items():
            if any(w in text_lower for w in words):
                keywords.append(category)

        return keywords

    def _send_to_weak_connection(self, event: ContextEvent):
        """发送给弱连接引擎"""
        try:
            from core.weak_connection import get_weak_connection_engine
            weak_engine = get_weak_connection_engine()
            weak_engine.on_context_event(event)
        except Exception as e:
            logger.error(f"发送给弱连接失败: {e}")


def get_context_trigger_engine() -> ContextTriggerEngine:
    """获取触发引擎实例"""
    if not hasattr(get_context_trigger_engine, "_instance"):
        get_context_trigger_engine._instance = ContextTriggerEngine()
    return get_context_trigger_engine._instance


# 全局触发引擎实例
context_triggers = get_context_trigger_engine()

# 向后兼容的类名别名
ContextTriggers = ContextTriggerEngine
