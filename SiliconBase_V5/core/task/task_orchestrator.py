#!/usr/bin/env python3
"""
任务编排中枢 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
负责任务的编排和调度：
- 任务创建和管理
- 任务依赖解析
- 任务执行编排
- 自动任务调度

【使用示例】
    from core.task.task_orchestrator import task_orchestrator, AutoTask

    # 创建自动任务
    task = AutoTask(
        name="定时备份",
        action=lambda: backup_data(),
        schedule="0 2 * * *"  # 每天2点
    )
    task_orchestrator.schedule(task)
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('task_orchestrator')


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 运行中
    PAUSED = "paused"        # 暂停
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class AutoTask:
    """
    自动任务数据类

    定义一个可调度的任务，支持定时执行和依赖管理。
    """
    name: str
    action: Callable[[], Any]
    schedule: str | None = None  # cron表达式或时间间隔
    dependencies: list[str] = field(default_factory=list)
    max_retries: int = 3
    timeout: int = 300  # 秒

    # 运行时状态
    task_id: str = field(default_factory=lambda: f"auto_{uuid.uuid4().hex[:8]}")
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    last_run: float | None = None
    run_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "schedule": self.schedule,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "error_count": self.error_count
        }


class TaskOrchestrator:
    """
    任务编排中枢

    负责任务的调度、编排和管理：
    - 任务注册和调度
    - 依赖解析
    - 执行监控
    - 失败重试

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
        """初始化编排器"""
        if self._initialized:
            return
        self._initialized = True

        # 任务注册表: task_id -> AutoTask
        self._tasks: dict[str, AutoTask] = {}

        # 任务执行线程
        self._executor_threads: dict[str, threading.Thread] = {}

        # 调度器线程
        self._scheduler_thread: threading.Thread | None = None
        self._running = False

        # 锁
        self._tasks_lock = threading.RLock()
        self._stop_event = threading.Event()

        # 【Phase 2 补全】工具执行历史记录
        self._execution_history: dict[str, list[dict[str, Any]]] = {}

        logger.info("[TaskOrchestrator] 任务编排中枢初始化完成")

    def schedule(self, task: AutoTask) -> str:
        """
        调度任务

        Args:
            task: 自动任务

        Returns:
            任务ID
        """
        with self._tasks_lock:
            self._tasks[task.task_id] = task
            logger.info(f"[TaskOrchestrator] 任务已调度: {task.name} ({task.task_id})")

        return task.task_id

    def unschedule(self, task_id: str) -> bool:
        """
        取消调度任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                return False

            task = self._tasks.pop(task_id)
            task.status = TaskStatus.CANCELLED

            logger.info(f"[TaskOrchestrator] 任务已取消调度: {task.name}")
            return True

    def execute_task(self, task_id: str) -> bool:
        """
        立即执行任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[TaskOrchestrator] 任务不存在: {task_id}")
                return False

            # 检查依赖
            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    logger.warning(f"[TaskOrchestrator] 任务依赖未完成: {dep_id}")
                    return False

            task.status = TaskStatus.RUNNING

        # 在单独线程中执行
        def run_task():
            try:
                logger.info(f"[TaskOrchestrator] 开始执行任务: {task.name}")
                task.action()

                with self._tasks_lock:
                    task.status = TaskStatus.COMPLETED
                    task.last_run = time.time()
                    task.run_count += 1

                logger.info(f"[TaskOrchestrator] 任务执行成功: {task.name}")

            except Exception as e:
                with self._tasks_lock:
                    task.error_count += 1
                    if task.error_count >= task.max_retries:
                        task.status = TaskStatus.FAILED
                    else:
                        task.status = TaskStatus.PENDING

                logger.error(f"[TaskOrchestrator] 任务执行失败: {task.name}, 错误: {e}")

        thread = threading.Thread(target=run_task, name=f"Task-{task_id}")
        thread.daemon = True
        thread.start()

        with self._tasks_lock:
            self._executor_threads[task_id] = thread

        return True

    def pause_task(self, task_id: str) -> bool:
        """
        暂停任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            task.status = TaskStatus.PAUSED
            logger.info(f"[TaskOrchestrator] 任务已暂停: {task.name}")
            return True

    def resume_task(self, task_id: str) -> bool:
        """
        恢复任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            task.status = TaskStatus.PENDING
            logger.info(f"[TaskOrchestrator] 任务已恢复: {task.name}")
            return True

    def get_task(self, task_id: str) -> AutoTask | None:
        """
        获取任务

        Args:
            task_id: 任务ID

        Returns:
            任务对象或None
        """
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[AutoTask]:
        """
        获取所有任务

        Returns:
            任务列表
        """
        with self._tasks_lock:
            return list(self._tasks.values())

    def get_tasks_by_status(self, status: TaskStatus) -> list[AutoTask]:
        """
        按状态获取任务

        Args:
            status: 任务状态

        Returns:
            任务列表
        """
        with self._tasks_lock:
            return [t for t in self._tasks.values() if t.status == status]

    def record_tool_execution(
        self,
        task_id: str,
        tool_id: str,
        params: dict[str, Any],
        result: dict[str, Any]
    ) -> None:
        """
        记录工具执行历史

        【Phase 2 补全】IntentHandler 的 Stop Hooks 调用此方法记录每次工具调用。
        记录的内容包括：工具ID、参数、结果、时间戳、是否成功。
        """
        with self._tasks_lock:
            if task_id not in self._execution_history:
                self._execution_history[task_id] = []

            self._execution_history[task_id].append({
                "tool_id": tool_id,
                "params": params,
                "result": result,
                "timestamp": time.time(),
                "success": result.get("success", False),
            })

            logger.debug(
                "[TaskOrchestrator] 记录工具执行: task=%s tool=%s success=%s",
                task_id, tool_id, result.get("success", False)
            )

    def get_execution_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取指定任务的工具执行历史"""
        with self._tasks_lock:
            return list(self._execution_history.get(task_id, []))

    def clear_execution_history(self, task_id: str | None = None) -> None:
        """清空工具执行历史"""
        with self._tasks_lock:
            if task_id:
                self._execution_history.pop(task_id, None)
            else:
                self._execution_history.clear()

    def clear(self) -> None:
        """清空所有任务"""
        with self._tasks_lock:
            self._tasks.clear()
            self._executor_threads.clear()
            self._execution_history.clear()

        logger.info("[TaskOrchestrator] 所有任务已清空")


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

# 创建全局任务编排器实例
try:
    task_orchestrator = TaskOrchestrator()
except Exception as e:
    logger.error(f"[TaskOrchestrator] 创建实例失败: {e}")
    task_orchestrator = None


__all__ = [
    'TaskOrchestrator',
    'task_orchestrator',
    'AutoTask',
    'TaskStatus',
]
