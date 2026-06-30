#!/usr/bin/env python3
"""
中断处理器 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供任务中断检测和处理功能：
- 中断信号管理
- 任务中断检测
- 中断回调注册
- 线程安全实现

【使用示例】
    from core.agent.interrupt_handler import interrupt_handler

    # 检查任务是否被中断
    if interrupt_handler.is_interrupted(task_id):
        print("任务已被中断")
"""

import asyncio
import threading
from collections.abc import Callable
from enum import Enum

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('interrupt_handler')


class InterruptStatus(Enum):
    """中断状态枚举"""
    RUNNING = "running"      # 正常运行
    PAUSED = "paused"        # 暂停
    INTERRUPTED = "interrupted"  # 已中断
    CANCELLED = "cancelled"  # 已取消


class InterruptHandler:
    """
    中断处理器

    管理任务的中断状态，支持：
    - 标记任务中断
    - 检查中断状态
    - 注册中断回调
    - 批量中断管理

    单例模式实现，确保全局状态一致。
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
        """初始化中断处理器"""
        if self._initialized:
            return
        self._initialized = True

        # 任务中断状态: task_id -> InterruptStatus
        self._interrupt_status: dict[str, InterruptStatus] = {}

        # 中断回调: task_id -> List[Callable]
        self._callbacks: dict[str, list[Callable]] = {}

        # 全局中断标志
        self._global_interrupt = False

        # Phase 7.1 新增：任务关联的 asyncio.Task 追踪
        self._task_futures: dict[str, list[asyncio.Task]] = {}
        self._futures_lock = threading.Lock()

        # 线程锁
        self._status_lock = threading.RLock()
        self._callback_lock = threading.RLock()

        logger.info("[InterruptHandler] 中断处理器初始化完成")

    def interrupt(self, task_id: str, reason: str = "") -> bool:
        """
        中断指定任务

        Args:
            task_id: 任务ID
            reason: 中断原因

        Returns:
            是否成功标记中断
        """
        with self._status_lock:
            if task_id not in self._interrupt_status:
                logger.warning(f"[InterruptHandler] 任务不存在: {task_id}")
                return False

            self._interrupt_status[task_id] = InterruptStatus.INTERRUPTED
            logger.info(f"[InterruptHandler] 任务已中断: {task_id}, 原因: {reason}")

        # 触发回调
        self._trigger_callbacks(task_id, "interrupted", reason)
        return True

    def cancel(self, task_id: str, reason: str = "") -> bool:
        """
        取消指定任务

        Args:
            task_id: 任务ID
            reason: 取消原因

        Returns:
            是否成功标记取消
        """
        with self._status_lock:
            self._interrupt_status[task_id] = InterruptStatus.CANCELLED
            logger.info(f"[InterruptHandler] 任务已取消: {task_id}, 原因: {reason}")

        # 触发回调
        self._trigger_callbacks(task_id, "cancelled", reason)
        return True

    def register_task(self, task_id: str, asyncio_task: asyncio.Task = None):
        """注册任务到中断处理器（Phase 7.1 增强版）

        Args:
            task_id: 任务ID
            asyncio_task: 可选的 asyncio.Task，中断时会被取消
        """
        with self._status_lock:
            self._interrupt_status[task_id] = InterruptStatus.RUNNING
            logger.debug(f"[InterruptHandler] 注册任务: {task_id}")

        if asyncio_task is not None:
            with self._futures_lock:
                if task_id not in self._task_futures:
                    self._task_futures[task_id] = []
                self._task_futures[task_id].append(asyncio_task)

    def unregister_task(self, task_id: str, asyncio_task: asyncio.Task = None):
        """注销任务（Phase 7.1 增强版）

        Args:
            task_id: 任务ID
            asyncio_task: 可选的 asyncio.Task，注销时移除
        """
        with self._status_lock:
            self._interrupt_status.pop(task_id, None)

        with self._callback_lock:
            self._callbacks.pop(task_id, None)

        if asyncio_task is not None:
            with self._futures_lock:
                if task_id in self._task_futures:
                    self._task_futures[task_id] = [
                        t for t in self._task_futures[task_id] if t != asyncio_task
                    ]
        else:
            with self._futures_lock:
                self._task_futures.pop(task_id, None)

        logger.debug(f"[InterruptHandler] 注销任务: {task_id}")

    async def cancel_all_futures(self, task_id: str) -> bool:
        """
        取消任务的所有关联 future（Phase 7.1 真正取消语义）

        1. 取消与该任务关联的所有 asyncio.Task
        2. 同时调用原有的 cancel 逻辑

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消至少一个 future 或标记取消
        """
        with self._futures_lock:
            tasks = self._task_futures.get(task_id, [])
            cancelled = False
            for task in tasks:
                if not task.done():
                    task.cancel()
                    cancelled = True
            # 清理已注销的任务列表
            if task_id in self._task_futures:
                del self._task_futures[task_id]

        # 同时调用原有的 cancel 逻辑
        self.cancel(task_id, reason="cancel_all_futures")

        if cancelled:
            logger.info(f"[InterruptHandler] 已取消任务 {task_id} 的关联 future")
        return True

    async def handle_interrupt(self, reason: str, task_id: str) -> bool:
        """
        处理中断请求的完整链路（Phase 7.1）

        1. 设置中断标志
        2. 取消关联 future
        3. 触发 on_interrupt Hook

        Args:
            reason: 中断原因
            task_id: 任务ID

        Returns:
            是否成功处理
        """
        # 1. 设置中断标志
        result = self.interrupt(task_id, reason=reason)
        # 2. 取消关联 future
        await self.cancel_all_futures(task_id)
        # 3. 触发 Hook（不阻塞主流程）
        try:
            from core.agent.agent_loop_hooks import agent_loop_hooks
            await agent_loop_hooks.execute_async('on_interrupt', None, task_id=task_id, reason=reason)
        except Exception as e:
            logger.warning(f"[InterruptHandler] on_interrupt Hook 触发失败: {e}")
        return result

    def pause(self, task_id: str) -> bool:
        """
        暂停指定任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功标记暂停
        """
        with self._status_lock:
            if task_id not in self._interrupt_status:
                return False

            self._interrupt_status[task_id] = InterruptStatus.PAUSED
            logger.info(f"[InterruptHandler] 任务已暂停: {task_id}")

        self._trigger_callbacks(task_id, "paused", "")
        return True

    def resume(self, task_id: str) -> bool:
        """
        恢复指定任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功恢复
        """
        with self._status_lock:
            if task_id not in self._interrupt_status:
                return False

            self._interrupt_status[task_id] = InterruptStatus.RUNNING
            logger.info(f"[InterruptHandler] 任务已恢复: {task_id}")

        self._trigger_callbacks(task_id, "resumed", "")
        return True

    def is_interrupted(self, task_id: str) -> bool:
        """
        检查任务是否被中断

        Args:
            task_id: 任务ID

        Returns:
            是否被中断
        """
        # 全局中断检查
        if self._global_interrupt:
            return True

        with self._status_lock:
            status = self._interrupt_status.get(task_id)
            return status in [InterruptStatus.INTERRUPTED, InterruptStatus.CANCELLED]

    def is_paused(self, task_id: str) -> bool:
        """
        检查任务是否暂停

        Args:
            task_id: 任务ID

        Returns:
            是否暂停
        """
        with self._status_lock:
            status = self._interrupt_status.get(task_id)
            return status == InterruptStatus.PAUSED

    def is_running(self, task_id: str) -> bool:
        """
        检查任务是否运行中

        Args:
            task_id: 任务ID

        Returns:
            是否运行中
        """
        with self._status_lock:
            status = self._interrupt_status.get(task_id)
            return status == InterruptStatus.RUNNING

    def register_callback(self, task_id: str, callback: Callable[[str, str, str], None]) -> None:
        """
        注册中断回调

        Args:
            task_id: 任务ID
            callback: 回调函数(task_id, event, reason)
        """
        with self._callback_lock:
            if task_id not in self._callbacks:
                self._callbacks[task_id] = []
            self._callbacks[task_id].append(callback)

    def _trigger_callbacks(self, task_id: str, event: str, reason: str) -> None:
        """触发回调"""
        with self._callback_lock:
            callbacks = self._callbacks.get(task_id, []).copy()

        for callback in callbacks:
            try:
                callback(task_id, event, reason)
            except Exception as e:
                logger.warning(f"[InterruptHandler] 回调执行失败: {e}")

    def set_global_interrupt(self, interrupted: bool = True) -> None:
        """
        设置全局中断标志

        Args:
            interrupted: 是否中断
        """
        self._global_interrupt = interrupted
        if interrupted:
            logger.warning("[InterruptHandler] 全局中断标志已设置")
        else:
            logger.info("[InterruptHandler] 全局中断标志已清除")

    def get_status(self, task_id: str) -> str | None:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            状态字符串或None
        """
        with self._status_lock:
            status = self._interrupt_status.get(task_id)
            return status.value if status else None

    def get_all_status(self) -> dict[str, str]:
        """
        获取所有任务状态

        Returns:
            task_id -> status 字典
        """
        with self._status_lock:
            return {k: v.value for k, v in self._interrupt_status.items()}

    def clear(self) -> None:
        """清空所有状态"""
        with self._status_lock:
            self._interrupt_status.clear()

        with self._callback_lock:
            self._callbacks.clear()

        self._global_interrupt = False
        logger.info("[InterruptHandler] 所有状态已清空")


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

# 创建全局中断处理器实例
try:
    interrupt_handler = InterruptHandler()
except Exception as e:
    logger.error(f"[InterruptHandler] 创建实例失败: {e}")
    interrupt_handler = None


__all__ = [
    'InterruptHandler',
    'interrupt_handler',
    'InterruptStatus',
]
