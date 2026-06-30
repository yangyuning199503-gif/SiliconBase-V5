#!/usr/bin/env python3
"""
状态协调器 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供系统状态协调功能：
- 跨模块状态同步
- 状态一致性维护
- 状态变更协调

【使用示例】
    from core.state_coordinator import state_coordinator

    # 协调状态变更
    state_coordinator.coordinate("system.mode", "maintenance")
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('state_coordinator')


class CoordinationStrategy(Enum):
    """协调策略枚举"""
    IMMEDIATE = "immediate"     # 立即同步
    DEFERRED = "deferred"       # 延迟同步
    BATCHED = "batched"         # 批量同步
    EVENTUAL = "eventual"       # 最终一致性


@dataclass
class StateChangeRequest:
    """状态变更请求数据类"""
    key: str
    new_value: Any
    old_value: Any
    source: str
    timestamp: float
    strategy: CoordinationStrategy


class StateCoordinator:
    """
    状态协调器

    协调跨模块的状态变更，确保一致性。

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
        """初始化状态协调器"""
        if self._initialized:
            return
        self._initialized = True

        # 协调器注册: key -> List[Callable]
        self._coordinators: dict[str, list[Callable]] = {}

        # 挂起的变更
        self._pending_changes: list[StateChangeRequest] = []

        # 批量处理线程
        self._batch_thread: threading.Thread | None = None
        self._running = False
        self._stop_event = threading.Event()

        # 锁
        self._lock = threading.RLock()

        logger.info("[StateCoordinator] 状态协调器初始化完成")

    def register_coordinator(self, key: str, callback: Callable[[str, Any, Any], bool]):
        """
        注册协调器

        Args:
            key: 状态键
            callback: 协调回调(key, old_value, new_value) -> 是否接受
        """
        with self._lock:
            if key not in self._coordinators:
                self._coordinators[key] = []
            self._coordinators[key].append(callback)
            logger.debug(f"[StateCoordinator] 注册协调器: {key}")

    def coordinate(self, key: str, new_value: Any, old_value: Any = None,
                   source: str = "", strategy: CoordinationStrategy = CoordinationStrategy.IMMEDIATE) -> bool:
        """
        协调状态变更

        Args:
            key: 状态键
            new_value: 新值
            old_value: 旧值
            source: 变更源
            strategy: 协调策略

        Returns:
            是否协调成功
        """
        request = StateChangeRequest(
            key=key,
            new_value=new_value,
            old_value=old_value,
            source=source,
            timestamp=time.time(),
            strategy=strategy
        )

        if strategy == CoordinationStrategy.IMMEDIATE:
            return self._process_change(request)
        else:
            self._queue_change(request)
            return True

    def _process_change(self, request: StateChangeRequest) -> bool:
        """处理状态变更"""
        with self._lock:
            coordinators = self._coordinators.get(request.key, [])

            # 征询所有协调器
            for coordinator in coordinators:
                try:
                    accepted = coordinator(request.key, request.old_value, request.new_value)
                    if not accepted:
                        logger.warning(f"[StateCoordinator] 变更被拒绝: {request.key}")
                        return False
                except Exception as e:
                    logger.error(f"[StateCoordinator] 协调器执行失败: {e}")
                    return False

            logger.debug(f"[StateCoordinator] 变更已协调: {request.key}")
            return True

    def _queue_change(self, request: StateChangeRequest):
        """将变更加入队列"""
        with self._lock:
            self._pending_changes.append(request)

    def start_batch_processor(self):
        """启动批量处理器"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._batch_thread = threading.Thread(target=self._batch_loop, daemon=True)
        self._batch_thread.start()
        logger.info("[StateCoordinator] 批量处理器已启动")

    def stop_batch_processor(self):
        """停止批量处理器"""
        self._running = False
        self._stop_event.set()

        if self._batch_thread:
            self._batch_thread.join(timeout=5)

        logger.info("[StateCoordinator] 批量处理器已停止")

    def _batch_loop(self):
        """批量处理循环"""
        while self._running and not self._stop_event.is_set():
            try:
                # 处理挂起的变更
                with self._lock:
                    changes = self._pending_changes.copy()
                    self._pending_changes.clear()

                for request in changes:
                    self._process_change(request)

                # 等待下一次循环
                self._stop_event.wait(timeout=1)

            except Exception as e:
                logger.error(f"[StateCoordinator] 批量处理异常: {e}")

    def synchronize(self, states: dict[str, Any], source: str = "") -> dict[str, bool]:
        """
        批量同步状态

        Args:
            states: 状态字典
            source: 变更源

        Returns:
            同步结果字典
        """
        results = {}

        for key, value in states.items():
            results[key] = self.coordinate(key, value, source=source)

        return results

    def get_pending_count(self) -> int:
        """获取挂起的变更数量"""
        with self._lock:
            return len(self._pending_changes)

    def clear(self) -> None:
        """清空协调器"""
        with self._lock:
            self._coordinators.clear()
            self._pending_changes.clear()
            logger.info("[StateCoordinator] 所有协调器已清空")


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

# 创建全局状态协调器实例
try:
    state_coordinator = StateCoordinator()
except Exception as e:
    logger.error(f"[StateCoordinator] 创建实例失败: {e}")
    state_coordinator = None


__all__ = [
    'StateCoordinator',
    'state_coordinator',
    'StateChangeRequest',
    'CoordinationStrategy',
]
