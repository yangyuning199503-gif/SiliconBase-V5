#!/usr/bin/env python3
"""
感知数据总线 V5.0
环形队列，统一管理所有感知数据，提供订阅/查询接口
2026-02-16 修复：回调使用异步线程池执行，避免阻塞主线程
"""
import concurrent.futures
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from core.logger import logger


@dataclass
class PerceptionData:
    source: str
    timestamp: float
    confidence: float
    content: dict[str, Any]
    error: str | None = None


class PerceptionBus:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._queue = deque(maxlen=100)
        self._subscribers = []
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)  # 异步线程池
        self._lock = Lock()

    def publish(self, data: PerceptionData):
        with self._lock:
            self._queue.append(data)
        # 异步执行所有回调
        for callback in self._subscribers:
            try:
                self._executor.submit(self._run_callback, callback, data)
            except RuntimeError as e:
                # 线程池已关闭时 submit 会抛 RuntimeError；此处必须捕获，否则主线程直接崩溃
                print(f"[CRITICAL ERROR][PerceptionBus] 事件总线线程池已关闭，无法调度回调: {e}", file=sys.stderr)

        # 【P1-3】转发到 EventBus，让模块状态系统感知传感器数据
        try:
            from core.sync.event_bus import event_bus
            if event_bus is not None:
                event_bus.emit(
                    "perception.data",
                    {
                        "source": data.source,
                        "timestamp": data.timestamp,
                        "confidence": data.confidence,
                        "content": data.content,
                        "error": data.error,
                    },
                    source="sensors.system"
                )
        except Exception as e:
            # 转发失败记录日志，但不影响原 PerceptionBus 功能
            logger.warning(f"[PerceptionBus] EventBus 转发失败: {e}")

    def _run_callback(self, callback: Callable, data: PerceptionData):
        """执行单个回调，捕获异常。不再设500ms硬超时，避免数据被静默丢弃。"""
        try:
            callback(data)
        except Exception as e:
            logger.error(f"感知回调执行异常: {e}", exc_info=True)

    def subscribe(self, callback: Callable):
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable):
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def get_latest(self, source: str = None, seconds: float = 1.0) -> list[PerceptionData]:
        cutoff = time.time() - seconds
        with self._lock:
            result = []
            for d in reversed(self._queue):
                if d.timestamp >= cutoff:
                    if source is None or d.source == source:
                        result.append(d)
                else:
                    break
            return result

    def get_summary(self) -> str:
        recent = self.get_latest(seconds=2.0)
        active_windows = []
        top_processes = []
        for d in recent:
            if d.source == "window" and d.content.get("visible"):
                windows = d.content.get("windows", [])
                for w in windows[:3]:
                    active_windows.append(w.get("title", ""))
            if d.source == "process":
                top_processes.append(f"{d.content.get('name','')}({d.content.get('cpu','0')}%)")
        summary = f"活跃窗口: {', '.join(active_windows[:3]) or '无'}\n"
        summary += f"高CPU进程: {', '.join(top_processes[:5]) or '无'}"
        return summary

    def shutdown(self):
        """
        关闭感知总线，释放线程池资源

        应在应用退出时调用，防止线程池资源泄漏
        """
        if self._executor:
            self._executor.shutdown(wait=True)
            logger.info("[PerceptionBus] 线程池已关闭")


bus = PerceptionBus()
