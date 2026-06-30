#!/usr/bin/env python3
"""
并发任务调度器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于 asyncio.PriorityQueue + Semaphore 的并发调度组件。
设计意图：给主流程任务加优先级队列和并发控制，可被 MasterScheduler 直接复用。

【设计原则】
- 纯组件化：不强制单例，允许按需实例化
- 延迟启动：asyncio 对象在 start() 中创建，避免事件循环问题
- 异常隔离：单个任务失败不影响 worker 和其他任务
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.diagnostic import safe_create_task
from core.logger import logger


class TaskPriority(Enum):
    """任务优先级 (数值越小优先级越高)"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(order=False)
class ScheduledTask:
    """调度任务"""
    task_id: str
    task_type: str
    priority: TaskPriority
    payload: dict[str, Any]
    user_id: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    status: TaskStatus = TaskStatus.PENDING
    error: str | None = None
    result: Any = None

    def __lt__(self, other: "ScheduledTask") -> bool:
        """PriorityQueue 比较：数值越小优先级越高"""
        return self.priority.value < other.priority.value


class ConcurrentTaskScheduler:
    """
    并发任务调度器

    特性：
    - PriorityQueue 按优先级消费任务
    - Semaphore 控制最大并发数
    - 支持为不同 task_type 注册执行器
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._tasks: dict[str, ScheduledTask] = {}
        self._executors: dict[str, Callable] = {}
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._queue: asyncio.PriorityQueue | None = None
        self._semaphore: asyncio.Semaphore | None = None

    def register_executor(self, task_type: str, executor: Callable):
        """注册任务执行器"""
        self._executors[task_type] = executor
        logger.info(f"[ConcurrentTaskScheduler] 注册执行器: {task_type}")

    async def submit(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        user_id: str | None = None,
        task_id: str | None = None
    ) -> str:
        """提交任务到队列"""
        if not self._running or self._queue is None:
            raise RuntimeError("调度器未启动，请先调用 start()")

        tid = task_id or f"task_{uuid.uuid4().hex[:12]}"
        task = ScheduledTask(
            task_id=tid,
            task_type=task_type,
            priority=priority,
            payload=payload,
            user_id=user_id
        )
        self._tasks[tid] = task
        await self._queue.put(task)
        logger.info(
            f"[ConcurrentTaskScheduler] 提交任务: {tid} "
            f"(类型={task_type}, 优先级={priority.name})"
        )
        return tid

    async def start(self):
        """启动调度器（必须在事件循环中调用）"""
        if self._running:
            return

        self._queue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._running = True
        self._worker_task = safe_create_task(self._worker(), name="_worker")
        logger.info(
            f"[ConcurrentTaskScheduler] 已启动 (max_concurrent={self.max_concurrent})"
        )

    async def stop(self, timeout: float = 5.0):
        """停止调度器"""
        if not self._running:
            return

        self._running = False

        # 发送哨兵任务唤醒 worker
        if self._queue is not None:
            await self._queue.put(None)

        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=timeout)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._worker_task
            self._worker_task = None

        logger.info("[ConcurrentTaskScheduler] 已停止")

    async def _worker(self):
        """后台 worker：消费队列，控制并发"""
        logger.info("[ConcurrentTaskScheduler] Worker 开始运行")
        while self._running:
            try:
                task = await self._queue.get()
                if task is None:
                    break  # 收到停止哨兵

                safe_create_task(self._run_with_semaphore(task), name="_run_with_semaphore")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ConcurrentTaskScheduler] Worker 异常: {e}")
        logger.info("[ConcurrentTaskScheduler] Worker 已退出")

    async def _run_with_semaphore(self, task: ScheduledTask):
        """在信号量保护下执行任务"""
        if self._semaphore is None:
            return
        async with self._semaphore:
            await self._execute_task(task)

    async def _execute_task(self, task: ScheduledTask):
        """执行单个任务"""
        executor = self._executors.get(task.task_type)
        if not executor:
            task.status = TaskStatus.FAILED
            task.error = f"未找到执行器: {task.task_type}"
            logger.error(f"[ConcurrentTaskScheduler] {task.error}")
            return

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        try:
            logger.info(f"[ConcurrentTaskScheduler] 开始执行: {task.task_id}")
            task.result = await executor(task.payload)
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            logger.info(f"[ConcurrentTaskScheduler] 完成: {task.task_id}")
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            logger.error(f"[ConcurrentTaskScheduler] 失败: {task.task_id} - {e}")

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, user_id: str | None = None) -> list[ScheduledTask]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if user_id:
            tasks = [t for t in tasks if t.user_id == user_id]
        return tasks

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        total = len(self._tasks)
        by_status: dict[str, int] = {}
        for task in self._tasks.values():
            s = task.status.value
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "total_tasks": total,
            "by_status": by_status,
            "queue_size": self._queue.qsize() if self._queue else 0,
            "max_concurrent": self.max_concurrent,
            "running": self._running,
        }


# 向后兼容别名
TaskScheduler = ConcurrentTaskScheduler
