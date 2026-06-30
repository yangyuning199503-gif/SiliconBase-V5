#!/usr/bin/env python3
"""
事件总线 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供系统级的事件发布/订阅机制：
- 事件发布和订阅
- 异步事件处理
- 事件优先级管理
- 处理器注册和注销

【使用示例】
    from core.sync.event_bus import event_bus, EventHandler, EventPriority

    # 订阅事件
    @event_bus.on("task.completed")
    def on_task_completed(event):
        print(f"任务完成: {event.data}")

    # 发布事件
    event_bus.emit("task.completed", {"task_id": "123"})
"""

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from queue import Queue
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('event_bus')


class EventPriority(Enum):
    """事件优先级枚举"""
    CRITICAL = 0    # 关键
    HIGH = 1        # 高
    NORMAL = 2      # 普通
    LOW = 3         # 低
    BACKGROUND = 4  # 后台


@dataclass
class Event:
    """事件数据类"""
    name: str
    data: Any
    timestamp: float
    source: str = ""
    priority: EventPriority = EventPriority.NORMAL
    trace_id: str = ""  # 【P1-1】信息闭环追踪ID


class EventHandler:
    """
    事件处理器包装类

    包装事件处理函数，支持优先级和过滤条件。
    """

    def __init__(self, handler: Callable, priority: EventPriority = EventPriority.NORMAL,
                 filter_func: Callable = None):
        self.handler = handler
        self.priority = priority
        self.filter_func = filter_func

    def can_handle(self, event: Event) -> bool:
        """检查是否可以处理事件"""
        if self.filter_func is None:
            return True
        return self.filter_func(event)

    def __call__(self, event: Event):
        """调用处理器"""
        return self.handler(event)


class EventBus:
    """
    事件总线

    提供系统级的事件发布/订阅机制。
    支持同步和异步事件处理，带优先级管理。

    单例模式实现。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化事件总线"""
        if self._initialized:
            return
        self._initialized = True

        # 处理器注册表: event_name -> List[EventHandler]
        self._handlers: dict[str, list[EventHandler]] = {}

        # 通配符处理器（处理所有事件）
        self._wildcard_handlers: list[EventHandler] = []

        # 异步事件队列
        self._async_queue: Queue = Queue()

        # 处理线程
        self._worker_thread: threading.Thread | None = None
        self._running = False

        # 锁
        self._handlers_lock = threading.RLock()
        self._stop_event = threading.Event()

        # 统计
        self._stats = {
            "published": 0,
            "handled": 0,
            "errors": 0
        }

        logger.info("[EventBus] 事件总线初始化完成")

    def on(self, event_name: str, priority: EventPriority = EventPriority.NORMAL,
           filter_func: Callable = None):
        """
        装饰器：订阅事件

        Args:
            event_name: 事件名称
            priority: 处理优先级
            filter_func: 过滤函数

        Returns:
            装饰器函数
        """
        def decorator(handler: Callable):
            self.subscribe(event_name, handler, priority, filter_func)
            return handler
        return decorator

    def on_all(self, handler: Callable,
               priority: EventPriority = EventPriority.NORMAL,
               filter_func: Callable = None) -> None:
        """订阅所有事件（通配符）"""
        event_handler = EventHandler(handler, priority, filter_func)
        with self._handlers_lock:
            # 去重：避免同一 handler 被重复订阅
            for existing in self._wildcard_handlers:
                if existing.handler is handler:
                    return
            self._wildcard_handlers.append(event_handler)
            self._wildcard_handlers.sort(key=lambda h: h.priority.value)
        logger.info("[EventBus] 通配符事件订阅已注册")

    def subscribe(self, event_name: str, handler: Callable,
                  priority: EventPriority = EventPriority.NORMAL,
                  filter_func: Callable = None) -> None:
        """
        订阅事件

        Args:
            event_name: 事件名称
            handler: 处理函数
            priority: 优先级
            filter_func: 过滤函数
        """
        with self._handlers_lock:
            if event_name not in self._handlers:
                self._handlers[event_name] = []

            event_handler = EventHandler(handler, priority, filter_func)
            self._handlers[event_name].append(event_handler)

            # 按优先级排序
            self._handlers[event_name].sort(key=lambda h: h.priority.value)

            logger.debug(f"[EventBus] 订阅事件: {event_name}")

    def unsubscribe(self, event_name: str, handler: Callable) -> bool:
        """
        取消订阅

        Args:
            event_name: 事件名称
            handler: 处理函数

        Returns:
            是否成功
        """
        with self._handlers_lock:
            if event_name not in self._handlers:
                return False

            handlers = self._handlers[event_name]
            original_count = len(handlers)
            self._handlers[event_name] = [h for h in handlers if h.handler != handler]

            return len(self._handlers[event_name]) < original_count

    def emit(self, event_name: str, data: Any = None, source: str = "", trace_id: str = "") -> None:
        """
        发布事件（同步处理）

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件源
            trace_id: 信息闭环追踪ID（为空时自动从上下文获取）
        """
        # 【P1-1】自动从上下文获取 trace_id
        if not trace_id:
            try:
                from core.traceability import get_trace_id
                trace_id = get_trace_id()
            except Exception:
                pass

        event = Event(
            name=event_name,
            data=data,
            timestamp=time.time(),
            source=source,
            priority=EventPriority.NORMAL,
            trace_id=trace_id
        )

        # 【P1-1】记录到 trace 索引
        if trace_id:
            try:
                from core.traceability import record_event
                record_event(trace_id, event_name, data)
            except Exception:
                pass

        self._stats["published"] += 1
        self._process_event(event)

    def emit_async(self, event_name: str, data: Any = None, source: str = "",
                   priority: EventPriority = EventPriority.NORMAL, trace_id: str = "") -> None:
        """
        异步发布事件

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件源
            priority: 优先级
            trace_id: 信息闭环追踪ID（为空时自动从上下文获取）
        """
        # 【P1-1】自动从上下文获取 trace_id
        if not trace_id:
            try:
                from core.traceability import get_trace_id
                trace_id = get_trace_id()
            except Exception:
                pass

        if not self._running:
            self.start()

        event = Event(
            name=event_name,
            data=data,
            timestamp=time.time(),
            source=source,
            priority=priority,
            trace_id=trace_id
        )

        # 【P1-1】记录到 trace 索引
        if trace_id:
            try:
                from core.traceability import record_event
                record_event(trace_id, event_name, data)
            except Exception:
                pass

        self._async_queue.put(event)
        self._stats["published"] += 1

    def _process_event(self, event: Event) -> None:
        """处理事件"""
        handlers = []

        with self._handlers_lock:
            # 获取特定事件处理器（复制列表，避免遍历时被其他线程修改）
            event_handlers = list(self._handlers.get(event.name, []))
            handlers.extend([h for h in event_handlers if h.can_handle(event)])

            # 获取通配符处理器（复制列表）
            wildcard_handlers = list(self._wildcard_handlers)
            handlers.extend([h for h in wildcard_handlers if h.can_handle(event)])

        # 执行处理器
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()

                        def _on_handler_done(t):
                            exc = t.exception()
                            if exc:
                                self._stats["errors"] += 1
                                logger.error(f"[EventBus] 异步事件处理器失败: {event.name}, 错误: {exc}")

                        _task = loop.create_task(result)
                        _task.add_done_callback(_on_handler_done)
                    except RuntimeError:
                        # 没有 running loop，在新线程中运行
                        import threading
                        def run_coro(coro):
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(coro)
                            except Exception as e:
                                self._stats["errors"] += 1
                                logger.error(f"[EventBus] 事件处理失败(无loop): {event.name}, 错误: {e}")
                            finally:
                                loop.close()
                        threading.Thread(target=run_coro, args=(result,), daemon=True).start()
                self._stats["handled"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"[EventBus] 事件处理失败: {event.name}, 错误: {e}")

    def start(self) -> None:
        """启动异步处理"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        logger.info("[EventBus] 异步事件处理已启动")

    def stop(self) -> None:
        """停止异步处理"""
        self._running = False
        self._stop_event.set()

        if self._worker_thread:
            self._worker_thread.join(timeout=5)

        logger.info("[EventBus] 异步事件处理已停止")

    def _worker_loop(self) -> None:
        """工作线程循环"""
        while self._running and not self._stop_event.is_set():
            try:
                event = self._async_queue.get(timeout=1)
                self._process_event(event)
            except Exception:
                pass  # 超时继续循环

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()

    def clear(self) -> None:
        """清空所有处理器"""
        with self._handlers_lock:
            self._handlers.clear()
            self._wildcard_handlers.clear()

        # 清空队列
        while not self._async_queue.empty():
            try:
                self._async_queue.get_nowait()
            except Exception:
                break

        logger.info("[EventBus] 所有处理器已清空")


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

# 创建全局事件总线实例
try:
    event_bus = EventBus()
except Exception as e:
    logger.error(f"[EventBus] 创建实例失败: {e}")
    event_bus = None


# 订阅思维线程事件
if event_bus is not None:
    def _on_consciousness_thought(event: Event):
        raw_data = event.data
        if not isinstance(raw_data, dict):
            return
        thought = raw_data.get("thought", "")
        action = raw_data.get("action")
        if action:
            logger.info(f"[Consciousness] 思维线程提议行动: {action[:100]}...")
        else:
            logger.debug(f"[Consciousness] 思维线程产生想法: {thought[:100]}...")

    event_bus.subscribe("consciousness:thought_generated", _on_consciousness_thought)


__all__ = [
    'EventBus',
    'event_bus',
    'EventHandler',
    'EventPriority',
    'Event',
]
