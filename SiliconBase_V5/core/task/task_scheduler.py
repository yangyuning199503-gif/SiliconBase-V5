#!/usr/bin/env python3
"""
大纲长任务调度器 - Task Scheduler (Async)

这才是真正的大纲"长任务"：AI设置的定时任务，如"每小时检查邮件"
特点：
- 不进入ReAct循环(run_agent_loop)
- 直接执行工具调用
- 支持cron表达式或间隔时间
- 由AI创建/查看/删除

与可暂停任务(Pausable Task)的区别：
- 可暂停任务: ReAct循环内可暂停/恢复的任务，使用PausableTaskManager管理
- 大纲长任务: AI设置的定时任务，不进入循环，使用TaskScheduler管理

作者: SiliconBase V5 AI Agent
日期: 2026-03-04
【2026-06-01 迁移】全面 asyncio 化
"""

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.diagnostic import safe_create_task

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False

import contextlib

from core.logger import logger


class ScheduledTaskStatus(Enum):
    """定时任务状态枚举"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    PAUSED = "paused"            # 已暂停
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 执行失败
    CANCELLED = "cancelled"      # 已取消


class ScheduledTaskType(Enum):
    """定时任务类型枚举"""
    INTERVAL = "interval"        # 间隔触发（每N秒/分钟/小时）
    CRON = "cron"                # Cron表达式触发
    ONCE = "once"                # 一次性任务（指定时间）


@dataclass
class ScheduledTask:
    """
    大纲长任务（定时任务）数据类

    这是AI设置的定时任务，不进入ReAct循环，直接执行工具调用。
    """
    task_id: str                                    # 任务ID
    name: str                                       # 任务名称
    description: str                                # 任务描述
    created_by: str                                 # 创建者（AI/用户）

    # 触发配置
    task_type: ScheduledTaskType                    # 任务类型
    cron_expression: str | None = None           # Cron表达式（如 "0 * * * *" 每小时）
    interval_seconds: int | None = None          # 间隔秒数
    scheduled_time: datetime | None = None       # 一次性任务的执行时间

    # 执行配置
    tool_name: str | None = None                 # 要调用的工具名称
    tool_params: dict[str, Any] = field(default_factory=dict)  # 工具参数

    # 状态管理
    status: ScheduledTaskStatus = ScheduledTaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None
    next_run_at: float | None = None
    run_count: int = 0
    max_run_count: int | None = None             # 最大执行次数（None表示无限）

    # 错误处理
    last_error: str | None = None
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3               # 连续失败3次后暂停

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def should_run(self) -> bool:
        """检查任务是否应该执行"""
        if self.status not in [ScheduledTaskStatus.PENDING, ScheduledTaskStatus.RUNNING]:
            return False

        if self.max_run_count is not None and self.run_count >= self.max_run_count:
            return False

        if self.consecutive_failures >= self.max_consecutive_failures:
            return False

        if self.next_run_at is None:
            return False

        return time.time() >= self.next_run_at

    def calculate_next_run(self) -> float | None:
        """计算下次执行时间"""
        now = time.time()

        if self.task_type == ScheduledTaskType.ONCE:
            # 一次性任务
            if self.scheduled_time:
                return self.scheduled_time.timestamp()
            return None

        elif self.task_type == ScheduledTaskType.INTERVAL:
            # 间隔任务
            if self.interval_seconds:
                if self.last_run_at:
                    return self.last_run_at + self.interval_seconds
                return now + self.interval_seconds
            return None

        elif self.task_type == ScheduledTaskType.CRON:
            # Cron任务
            if self.cron_expression:
                try:
                    itr = croniter(self.cron_expression, datetime.fromtimestamp(now))
                    next_time = itr.get_next(datetime)
                    return next_time.timestamp()
                except Exception as e:
                    logger.error(f"[TaskScheduler] Cron解析失败: {e}")
                    return None
            return None

        return None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "task_type": self.task_type.value,
            "cron_expression": self.cron_expression,
            "interval_seconds": self.interval_seconds,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
            "max_run_count": self.max_run_count,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
        }


class TaskScheduler:
    """
    大纲长任务调度器

    管理AI设置的定时任务，特点：
    - 不进入ReAct循环
    - 直接执行工具调用
    - 支持cron和间隔触发

    使用示例：
        scheduler = TaskScheduler()

        # 创建每小时检查邮件的任务
        task = await scheduler.create_interval_task(
            name="检查邮件",
            interval_seconds=3600,
            tool_name="check_email",
            tool_params={}
        )

        # 启动调度器
        await scheduler.start()
    """

    # 配置参数
    CHECK_INTERVAL = 5          # 每5秒检查一次任务
    MAX_TASK_HISTORY = 100      # 最大历史记录数

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._task_history: list[dict[str, Any]] = []
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

        # 执行器回调（用于实际执行工具调用）
        self._executor: Callable[[str, dict[str, Any]], Any] | None = None

    def set_executor(self, executor: Callable[[str, dict[str, Any]], Any]):
        """
        设置任务执行器

        Args:
            executor: 函数(tool_name, tool_params) -> result
        """
        self._executor = executor

    def set_execute_callback(self, callback: Callable[[ScheduledTask], Any]):
        """
        设置任务执行回调（兼容API）

        此方法是 set_executor 的别名，用于向后兼容 cloud_api.py 中的调用。
        实际执行时会将 ScheduledTask 对象传递给回调函数。

        Args:
            callback: 函数(scheduled_task) -> result
        """
        # 包装回调函数，使其兼容 executor 的接口
        def executor_wrapper(tool_name: str, tool_params: dict[str, Any]):
            # 创建一个临时的 ScheduledTask 对象用于回调
            temp_task = ScheduledTask(
                task_id=f"callback_{int(time.time())}",
                name=tool_name,
                description="Callback task",
                created_by="system",
                task_type=ScheduledTaskType.ONCE,
                tool_name=tool_name,
                tool_params=tool_params
            )
            return callback(temp_task)

        self._executor = executor_wrapper

    # =============================================================================
    # 任务创建API（供AI使用）
    # =============================================================================

    async def create_interval_task(
        self,
        name: str,
        interval_seconds: int,
        tool_name: str,
        tool_params: dict[str, Any] = None,
        description: str = "",
        max_run_count: int | None = None,
        created_by: str = "ai"
    ) -> ScheduledTask:
        """
        创建间隔触发任务

        Args:
            name: 任务名称
            interval_seconds: 间隔秒数
            tool_name: 要调用的工具名称
            tool_params: 工具参数
            description: 任务描述
            max_run_count: 最大执行次数（None表示无限）
            created_by: 创建者

        Returns:
            ScheduledTask: 创建的任务

        示例：
            # 每10分钟检查一次系统状态
            task = await scheduler.create_interval_task(
                name="系统状态检查",
                interval_seconds=600,
                tool_name="system_check",
                tool_params={"check_memory": True, "check_disk": True}
            )
        """
        task_id = f"scheduled_{int(time.time())}_{hash(name) % 10000}"

        task = ScheduledTask(
            task_id=task_id,
            name=name,
            description=description or f"每{interval_seconds}秒执行一次",
            created_by=created_by,
            task_type=ScheduledTaskType.INTERVAL,
            interval_seconds=interval_seconds,
            tool_name=tool_name,
            tool_params=tool_params or {},
            max_run_count=max_run_count,
            next_run_at=time.time() + interval_seconds  # 第一次执行
        )

        async with self._lock:
            self._tasks[task_id] = task
            await self._add_task_history({
                "task_id": task_id,
                "action": "created",
                "task_type": "interval",
                "timestamp": time.time()
            })

        logger.info(f"[TaskScheduler] 创建间隔任务: {name} (ID: {task_id}), 间隔: {interval_seconds}秒")
        return task

    async def create_cron_task(
        self,
        name: str,
        cron_expression: str,
        tool_name: str,
        tool_params: dict[str, Any] = None,
        description: str = "",
        max_run_count: int | None = None,
        created_by: str = "ai"
    ) -> ScheduledTask:
        """
        创建Cron表达式任务

        Args:
            name: 任务名称
            cron_expression: Cron表达式（如 "0 9 * * *" 每天9点）
            tool_name: 要调用的工具名称
            tool_params: 工具参数
            description: 任务描述
            max_run_count: 最大执行次数
            created_by: 创建者

        Returns:
            ScheduledTask: 创建的任务

        示例：
            # 每天早上9点检查邮件
            task = await scheduler.create_cron_task(
                name="每日邮件检查",
                cron_expression="0 9 * * *",
                tool_name="check_email",
                tool_params={"folder": "inbox"}
            )

            # 每小时执行一次数据备份
            task = await scheduler.create_cron_task(
                name="定时备份",
                cron_expression="0 * * * *",
                tool_name="backup_data"
            )
        """
        # 验证cron表达式
        try:
            itr = croniter(cron_expression, datetime.now())
            next_run = itr.get_next(datetime)
        except Exception as e:
            raise ValueError(f"无效的Cron表达式: {cron_expression}") from e

        task_id = f"scheduled_{int(time.time())}_{hash(name) % 10000}"

        task = ScheduledTask(
            task_id=task_id,
            name=name,
            description=description or f"Cron: {cron_expression}",
            created_by=created_by,
            task_type=ScheduledTaskType.CRON,
            cron_expression=cron_expression,
            tool_name=tool_name,
            tool_params=tool_params or {},
            max_run_count=max_run_count,
            next_run_at=next_run.timestamp()
        )

        async with self._lock:
            self._tasks[task_id] = task
            await self._add_task_history({
                "task_id": task_id,
                "action": "created",
                "task_type": "cron",
                "cron": cron_expression,
                "timestamp": time.time()
            })

        logger.info(f"[TaskScheduler] 创建Cron任务: {name} (ID: {task_id}), Cron: {cron_expression}")
        return task

    async def create_once_task(
        self,
        name: str,
        scheduled_time: datetime | str,
        tool_name: str,
        tool_params: dict[str, Any] = None,
        description: str = "",
        created_by: str = "ai"
    ) -> ScheduledTask:
        """
        创建一次性任务

        Args:
            name: 任务名称
            scheduled_time: 执行时间（datetime对象或ISO格式字符串）
            tool_name: 要调用的工具名称
            tool_params: 工具参数
            description: 任务描述
            created_by: 创建者

        Returns:
            ScheduledTask: 创建的任务

        示例：
            # 15分钟后提醒开会
            from datetime import datetime, timedelta
            task = await scheduler.create_once_task(
                name="会议提醒",
                scheduled_time=datetime.now() + timedelta(minutes=15),
                tool_name="send_notification",
                tool_params={"message": "会议即将开始"}
            )
        """
        if isinstance(scheduled_time, str):
            scheduled_time = datetime.fromisoformat(scheduled_time)

        task_id = f"scheduled_{int(time.time())}_{hash(name) % 10000}"

        task = ScheduledTask(
            task_id=task_id,
            name=name,
            description=description or f"执行时间: {scheduled_time.isoformat()}",
            created_by=created_by,
            task_type=ScheduledTaskType.ONCE,
            scheduled_time=scheduled_time,
            tool_name=tool_name,
            tool_params=tool_params or {},
            max_run_count=1,
            next_run_at=scheduled_time.timestamp()
        )

        async with self._lock:
            self._tasks[task_id] = task
            await self._add_task_history({
                "task_id": task_id,
                "action": "created",
                "task_type": "once",
                "timestamp": time.time()
            })

        logger.info(f"[TaskScheduler] 创建一次性任务: {name} (ID: {task_id}), 时间: {scheduled_time}")
        return task

    # =============================================================================
    # 任务管理API
    # =============================================================================

    async def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            if task.status == ScheduledTaskStatus.RUNNING:
                task.status = ScheduledTaskStatus.PAUSED
                await self._add_task_history({
                    "task_id": task_id,
                    "action": "paused",
                    "timestamp": time.time()
                })
                logger.info(f"[TaskScheduler] 任务已暂停: {task_id}")
                return True
        return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            if task.status == ScheduledTaskStatus.PAUSED:
                task.status = ScheduledTaskStatus.PENDING
                # 重新计算下次执行时间
                task.next_run_at = task.calculate_next_run()
                await self._add_task_history({
                    "task_id": task_id,
                    "action": "resumed",
                    "timestamp": time.time()
                })
                logger.info(f"[TaskScheduler] 任务已恢复: {task_id}")
                return True
        return False

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.status = ScheduledTaskStatus.CANCELLED
            await self._add_task_history({
                "task_id": task_id,
                "action": "cancelled",
                "timestamp": time.time()
            })
            logger.info(f"[TaskScheduler] 任务已取消: {task_id}")
            return True

    async def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            del self._tasks[task_id]
            await self._add_task_history({
                "task_id": task_id,
                "action": "deleted",
                "timestamp": time.time()
            })
            logger.info(f"[TaskScheduler] 任务已删除: {task_id}")
            return True

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """获取任务信息"""
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(self, status: ScheduledTaskStatus | None = None) -> list[ScheduledTask]:
        """
        列出所有任务

        Args:
            status: 按状态过滤（None表示不过滤）

        Returns:
            List[ScheduledTask]: 任务列表
        """
        async with self._lock:
            tasks = list(self._tasks.values())
            if status:
                tasks = [t for t in tasks if t.status == status]
            return tasks

    async def list_all_tasks(self) -> list[dict[str, Any]]:
        """列出所有任务（字典格式）"""
        async with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    async def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        async with self._lock:
            total = len(self._tasks)
            status_counts = {}
            for task in self._tasks.values():
                status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1

            return {
                "total_tasks": total,
                "status_distribution": status_counts,
                "history_count": len(self._task_history),
                "is_running": self._running
            }

    async def get_upcoming_tasks(self, limit: int = 10) -> list[ScheduledTask]:
        """获取即将执行的任务"""
        async with self._lock:
            pending = [
                t for t in self._tasks.values()
                if t.status in [ScheduledTaskStatus.PENDING, ScheduledTaskStatus.RUNNING]
                and t.next_run_at is not None
            ]
            pending.sort(key=lambda t: t.next_run_at)
            return pending[:limit]

    # =============================================================================
    # 调度器控制
    # =============================================================================

    async def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("[TaskScheduler] 调度器已在运行")
            return

        self._running = True
        self._stop_event.clear()
        self._scheduler_task = safe_create_task(self._scheduler_loop(), name="_scheduler_loop")
        logger.info("[TaskScheduler] 调度器已启动")

    async def stop(self):
        """停止调度器"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        logger.info("[TaskScheduler] 调度器已停止")

    async def _scheduler_loop(self):
        """调度器主循环（asyncio 版本）"""
        while self._running:
            try:
                await self._check_and_execute_tasks()
            except Exception as e:
                logger.error(f"[TaskScheduler] 调度循环异常: {e}")

            # 等待下一次检查（可被 stop_event 提前唤醒）
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.CHECK_INTERVAL)

    async def _check_and_execute_tasks(self):
        """检查并执行任务"""
        tasks_to_run = []

        # 找出需要执行的任务
        async with self._lock:
            for task in self._tasks.values():
                if task.should_run():
                    tasks_to_run.append(task)

        # 执行任务（在锁外执行，避免阻塞）
        for task in tasks_to_run:
            await self._execute_task(task)

    async def _execute_task(self, task: ScheduledTask):
        """执行单个任务（async 版本，阻塞调用使用 asyncio.to_thread）"""
        task.status = ScheduledTaskStatus.RUNNING
        task.last_run_at = time.time()
        task.run_count += 1

        logger.info(f"[TaskScheduler] 执行任务: {task.name} (ID: {task.task_id})")

        try:
            # 执行工具调用
            if self._executor and task.tool_name:
                result = await asyncio.to_thread(self._executor, task.tool_name, task.tool_params)
                task.consecutive_failures = 0
                task.last_error = None

                await self._add_task_history({
                    "task_id": task.task_id,
                    "action": "executed",
                    "timestamp": time.time(),
                    "success": True,
                    "result": str(result)[:200]  # 截断结果
                })

                logger.info(f"[TaskScheduler] 任务执行成功: {task.name}")
            else:
                if not self._executor:
                    raise RuntimeError("未设置任务执行器")
                if not task.tool_name:
                    raise ValueError("任务未配置工具名称")

        except Exception as e:
            task.consecutive_failures += 1
            task.last_error = str(e)

            await self._add_task_history({
                "task_id": task.task_id,
                "action": "executed",
                "timestamp": time.time(),
                "success": False,
                "error": str(e)
            })

            logger.error(f"[TaskScheduler] 任务执行失败: {task.name}, 错误: {e}")

        # 更新任务状态
        if task.task_type == ScheduledTaskType.ONCE:
            # 一次性任务完成后标记为完成
            task.status = ScheduledTaskStatus.COMPLETED
        elif task.consecutive_failures >= task.max_consecutive_failures:
            # 连续失败次数过多，暂停任务
            task.status = ScheduledTaskStatus.PAUSED
            logger.warning(f"[TaskScheduler] 任务连续失败{task.consecutive_failures}次，已暂停: {task.name}")
        else:
            # 计算下次执行时间
            task.next_run_at = task.calculate_next_run()
            task.status = ScheduledTaskStatus.PENDING if task.next_run_at else ScheduledTaskStatus.COMPLETED

    async def _add_task_history(self, entry: dict[str, Any]):
        """添加任务历史记录"""
        self._task_history.append(entry)
        # 【内存泄漏修复】限制历史记录大小
        if len(self._task_history) > self.MAX_TASK_HISTORY:
            self._task_history = self._task_history[-self.MAX_TASK_HISTORY:]


# =============================================================================
# 全局实例
# =============================================================================
_task_scheduler: TaskScheduler | None = None


def get_task_scheduler() -> TaskScheduler:
    """获取全局任务调度器实例"""
    global _task_scheduler
    if _task_scheduler is None:
        _task_scheduler = TaskScheduler()
    return _task_scheduler


def create_task_scheduler() -> TaskScheduler:
    """创建新的任务调度器实例"""
    return TaskScheduler()


# =============================================================================
# 便捷函数（供AI直接调用）
# =============================================================================

async def schedule_interval_task(
    name: str,
    interval_seconds: int,
    tool_name: str,
    tool_params: dict[str, Any] = None,
    description: str = ""
) -> str:
    """
    创建间隔任务（便捷函数）

    Returns:
        str: 任务ID
    """
    scheduler = get_task_scheduler()
    task = await scheduler.create_interval_task(
        name=name,
        interval_seconds=interval_seconds,
        tool_name=tool_name,
        tool_params=tool_params,
        description=description
    )
    return task.task_id


async def schedule_cron_task(
    name: str,
    cron_expression: str,
    tool_name: str,
    tool_params: dict[str, Any] = None,
    description: str = ""
) -> str:
    """
    创建Cron任务（便捷函数）

    Returns:
        str: 任务ID
    """
    scheduler = get_task_scheduler()
    task = await scheduler.create_cron_task(
        name=name,
        cron_expression=cron_expression,
        tool_name=tool_name,
        tool_params=tool_params,
        description=description
    )
    return task.task_id


async def cancel_scheduled_task(task_id: str) -> bool:
    """取消定时任务（便捷函数）"""
    scheduler = get_task_scheduler()
    return await scheduler.cancel_task(task_id)


async def list_scheduled_tasks() -> list[dict[str, Any]]:
    """列出所有定时任务（便捷函数）"""
    scheduler = get_task_scheduler()
    return await scheduler.list_all_tasks()


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件（task_scheduler.py）是 SiliconBase V5 系统的"大纲长任务调度器"核心模块。
# 这才是真正的大纲"长任务"：AI设置的定时任务，不进入ReAct循环。
#
# 【概念区分】
# 1. 可暂停任务(Pausable Task): long_running_manager.py管理
#    - ReAct循环内可暂停/恢复的任务
#    - 如：复杂多步骤任务需要暂停确认理解
#
# 2. 大纲长任务(Scheduled Task): task_scheduler.py管理（本模块）
#    - AI设置的定时任务
#    - 不进入ReAct循环，直接执行工具调用
#    - 如：每小时检查邮件、每天备份数据
#
# 【核心类说明】
# 1. ScheduledTask(dataclass): 定时任务数据类
#    - 包含任务ID、名称、描述、触发配置、执行配置、状态管理
#    - 支持interval、cron、once三种类型
#
# 2. TaskScheduler: 任务调度器主类
#    - 管理所有定时任务
#    - 提供任务创建、暂停、恢复、取消、删除API
#    - asyncio Task 定时检查并执行任务
#
# 【触发类型】
# 1. INTERVAL: 间隔触发
#    - 参数: interval_seconds
#    - 示例: 每600秒(10分钟)执行一次
#
# 2. CRON: Cron表达式触发
#    - 参数: cron_expression
#    - 示例: "0 9 * * *" 每天9点
#    - 示例: "0 */2 * * *" 每2小时
#
# 3. ONCE: 一次性任务
#    - 参数: scheduled_time
#    - 示例: 15分钟后执行一次
#
# 【使用场景】
# - AI设置定期任务（如每小时检查邮件）
# - 定时数据备份
# - 定期系统状态检查
# - 一次性延时任务（如15分钟后提醒）
#
# 【注意事项】
# 1. 需要安装依赖: croniter (用于解析cron表达式)
# 2. 需要设置执行器(set_executor)才能实际执行工具调用
# 3. 任务执行不进入ReAct循环，直接调用工具
# 4. 最大历史记录数限制为100条，防止内存泄漏
#
# 【API示例】
# # 创建任务
# task_id = await schedule_interval_task("检查邮件", 3600, "check_email")
# task_id = await schedule_cron_task("每日备份", "0 2 * * *", "backup_data")
#
# # 管理任务
# await cancel_scheduled_task(task_id)
# tasks = await list_scheduled_tasks()
#
# # 完整控制
# scheduler = get_task_scheduler()
# scheduler.set_executor(my_tool_executor)
# await scheduler.start()
#
# =============================================================================

# =============================================================================
# 统一任务调度器 - Unified Task Scheduler (P1-005)
# =============================================================================
#
# 【新增】UnifiedTaskScheduler - 合并大纲长任务和可暂停任务的统一调度器
# 解决 task_scheduler.py 与 ai_task_scheduler.py 两个调度器并存的问题
#

@dataclass
class PausableTask:
    """
    可暂停任务数据类

    支持暂停/恢复/停止，进入ReAct循环的任务
    """
    task_id: str                                    # 任务ID
    user_id: str                                    # 用户ID
    task_name: str                                  # 任务名称
    config: dict[str, Any] = field(default_factory=dict)  # 任务配置
    status: str = "running"                         # running, paused, stopped
    created_at: datetime | None = None           # 创建时间
    paused_at: datetime | None = None            # 暂停时间
    resumed_at: datetime | None = None           # 恢复时间
    stopped_at: datetime | None = None           # 停止时间
    ai_confirmation: str | None = None           # AI确认理解内容
    progress: dict[str, Any] = field(default_factory=dict)  # 任务进度

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_name": self.task_name,
            "config": self.config,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "resumed_at": self.resumed_at.isoformat() if self.resumed_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "ai_confirmation": self.ai_confirmation,
            "progress": self.progress,
        }


@dataclass
class UnifiedScheduledTask:
    """
    统一调度任务数据类（大纲长任务）

    AI设置的定时任务，不进入ReAct循环，直接执行工具调用
    """
    task_id: str                                    # 任务ID
    user_id: str                                    # 用户ID
    task_name: str                                  # 任务名称
    trigger_type: str                               # 'interval' | 'cron' | 'once'
    description: str | None = None               # 任务描述（AI创建时使用）
    trigger_config: dict[str, Any] = field(default_factory=dict)  # 触发器配置
    tool_name: str | None = None                 # 工具名称
    tool_params: dict[str, Any] = field(default_factory=dict)     # 工具参数
    created_at: datetime | None = None           # 创建时间
    status: str = "pending"                         # pending, running, paused, completed, failed
    last_execution: dict[str, Any] | None = None # 上次执行结果
    run_count: int = 0                              # 执行次数

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_name": self.task_name,
            "description": self.description,
            "trigger_type": self.trigger_type,
            "trigger_config": self.trigger_config,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "last_execution": self.last_execution,
            "run_count": self.run_count,
        }


class UnifiedTaskScheduler:
    """
    统一任务调度器 (P1-005)

    合并大纲长任务（定时任务）和可暂停任务的管理

    支持:
    - 大纲长任务（定时任务，不进入ReAct循环）
    - 可暂停任务（进入ReAct循环）
    - AI创建和管理任务
    """

    def __init__(self):
        self._scheduled_tasks: dict[str, UnifiedScheduledTask] = {}   # 定时任务
        self._pausable_tasks: dict[str, PausableTask] = {}              # 可暂停任务
        self._lock = asyncio.Lock()

        # 初始化APScheduler（如果可用）
        if APSCHEDULER_AVAILABLE:
            self._scheduler = BackgroundScheduler()
            self._scheduler.start()
            logger.info("[UnifiedTaskScheduler] APScheduler已启动")
        else:
            self._scheduler = None
            logger.warning("[UnifiedTaskScheduler] APScheduler不可用，使用备用方案")

        # 执行器回调
        self._executor: Callable[[str, dict[str, Any], str], Any] | None = None

    def set_executor(self, executor: Callable[[str, dict[str, Any], str], Any]):
        """
        设置任务执行器

        Args:
            executor: 函数(tool_name, tool_params, user_id) -> result
        """
        self._executor = executor

    # ========== 大纲长任务（定时任务）==========

    async def create_scheduled_task(
        self,
        user_id: str,
        task_name: str,
        trigger_type: str,  # 'interval' | 'cron' | 'once'
        trigger_config: dict,
        tool_name: str,
        tool_params: dict,
        description: str | None = None
    ) -> str:
        """
        创建大纲长任务（定时任务，不进入ReAct循环）
        大纲：AI设置的定时任务，不进入循环

        Args:
            user_id: 用户ID
            task_name: 任务名称
            trigger_type: 触发类型 ('interval' | 'cron' | 'once')
            trigger_config: 触发配置
            tool_name: 工具名称
            tool_params: 工具参数
            description: 任务描述（可选）

        Returns:
            str: 任务ID
        """
        task_id = f"sched_{uuid.uuid4().hex[:8]}"

        async with self._lock:
            task = UnifiedScheduledTask(
                task_id=task_id,
                user_id=user_id,
                task_name=task_name,
                description=description,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                tool_name=tool_name,
                tool_params=tool_params,
                created_at=datetime.now()
            )
            self._scheduled_tasks[task_id] = task

            # 添加到APScheduler（如果可用）
            if self._scheduler:
                try:
                    if trigger_type == 'interval':
                        seconds = trigger_config.get('seconds', 3600)
                        await asyncio.to_thread(
                            self._scheduler.add_job,
                            self._execute_scheduled_task,
                            'interval',
                            seconds=seconds,
                            args=[task_id],
                            id=task_id,
                            replace_existing=True
                        )
                    elif trigger_type == 'cron':
                        hour = trigger_config.get('hour', 0)
                        minute = trigger_config.get('minute', 0)
                        await asyncio.to_thread(
                            self._scheduler.add_job,
                            self._execute_scheduled_task,
                            'cron',
                            hour=hour,
                            minute=minute,
                            args=[task_id],
                            id=task_id,
                            replace_existing=True
                        )
                    elif trigger_type == 'once':
                        # 一次性任务使用date触发器
                        run_date = trigger_config.get('run_date')
                        if run_date:
                            await asyncio.to_thread(
                                self._scheduler.add_job,
                                self._execute_scheduled_task,
                                'date',
                                run_date=run_date,
                                args=[task_id],
                                id=task_id,
                                replace_existing=True
                            )
                except Exception as e:
                    logger.error(f"[UnifiedTaskScheduler] 添加定时任务失败: {e}")

            logger.info(f"[UnifiedTaskScheduler] 创建定时任务: {task_name} (ID: {task_id})")
            return task_id

    async def cancel_scheduled_task(self, user_id: str, task_id: str) -> bool:
        """
        取消定时任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功取消
        """
        async with self._lock:
            task = self._scheduled_tasks.get(task_id)
            if task and task.user_id == user_id:
                # 从APScheduler移除
                if self._scheduler:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(self._scheduler.remove_job, task_id)
                # 从本地存储移除
                del self._scheduled_tasks[task_id]
                logger.info(f"[UnifiedTaskScheduler] 取消定时任务: {task_id}")
                return True
            return False

    async def get_scheduled_task(self, user_id: str, task_id: str) -> UnifiedScheduledTask | None:
        """
        获取定时任务详情

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            UnifiedScheduledTask: 任务对象
        """
        async with self._lock:
            task = self._scheduled_tasks.get(task_id)
            if task and task.user_id == user_id:
                return task
            return None

    async def get_scheduled_tasks(self, user_id: str) -> list[UnifiedScheduledTask]:
        """
        获取用户的所有定时任务

        Args:
            user_id: 用户ID

        Returns:
            List[UnifiedScheduledTask]: 任务列表
        """
        async with self._lock:
            return [t for t in self._scheduled_tasks.values() if t.user_id == user_id]

    async def pause_scheduled_task(self, user_id: str, task_id: str) -> bool:
        """
        暂停定时任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功暂停
        """
        async with self._lock:
            task = self._scheduled_tasks.get(task_id)
            if task and task.user_id == user_id:
                task.status = 'paused'
                # 暂停APScheduler中的任务
                if self._scheduler:
                    try:
                        await asyncio.to_thread(self._scheduler.pause_job, task_id)
                    except Exception as e:
                        logger.warning(f"[UnifiedTaskScheduler] 暂停任务失败: {e}")
                return True
            return False

    async def resume_scheduled_task(self, user_id: str, task_id: str) -> bool:
        """
        恢复定时任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功恢复
        """
        async with self._lock:
            task = self._scheduled_tasks.get(task_id)
            if task and task.user_id == user_id:
                task.status = 'pending'
                # 恢复APScheduler中的任务
                if self._scheduler:
                    try:
                        await asyncio.to_thread(self._scheduler.resume_job, task_id)
                    except Exception as e:
                        logger.warning(f"[UnifiedTaskScheduler] 恢复任务失败: {e}")
                return True
            return False

    # ========== 可暂停任务 ==========

    async def create_pausable_task(
        self,
        user_id: str,
        task_name: str,
        task_config: dict
    ) -> str:
        """
        创建可暂停任务（进入ReAct循环）
        支持暂停/恢复/停止

        Args:
            user_id: 用户ID
            task_name: 任务名称
            task_config: 任务配置

        Returns:
            str: 任务ID
        """
        task_id = f"pause_{uuid.uuid4().hex[:8]}"

        async with self._lock:
            task = PausableTask(
                task_id=task_id,
                user_id=user_id,
                task_name=task_name,
                config=task_config,
                status='running',
                created_at=datetime.now()
            )
            self._pausable_tasks[task_id] = task
            logger.info(f"[UnifiedTaskScheduler] 创建可暂停任务: {task_name} (ID: {task_id})")
            return task_id

    async def pause_task(self, user_id: str, task_id: str) -> bool:
        """
        暂停任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功暂停
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                task.status = 'paused'
                task.paused_at = datetime.now()
                logger.info(f"[UnifiedTaskScheduler] 暂停任务: {task_id}")
                return True
            return False

    async def resume_task(self, user_id: str, task_id: str, ai_confirmation: str = "") -> bool:
        """
        恢复任务（需AI确认理解）
        大纲第5条规则：必须AI确认百分百理解需求后才能恢复

        Args:
            user_id: 用户ID
            task_id: 任务ID
            ai_confirmation: AI确认理解内容（至少20字符）

        Returns:
            bool: 是否成功恢复

        Raises:
            ValueError: 如果AI确认内容太短
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                # 检查AI确认
                if len(ai_confirmation) < 20:
                    raise ValueError("AI确认理解内容太短（至少20字符）")

                task.status = 'running'
                task.ai_confirmation = ai_confirmation
                task.resumed_at = datetime.now()
                logger.info(f"[UnifiedTaskScheduler] 恢复任务: {task_id}")
                return True
            return False

    async def stop_task(self, user_id: str, task_id: str) -> bool:
        """
        停止任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功停止
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                task.status = 'stopped'
                task.stopped_at = datetime.now()
                logger.info(f"[UnifiedTaskScheduler] 停止任务: {task_id}")
                return True
            return False

    async def update_task_progress(self, user_id: str, task_id: str, progress: dict[str, Any]) -> bool:
        """
        更新任务进度

        Args:
            user_id: 用户ID
            task_id: 任务ID
            progress: 进度信息

        Returns:
            bool: 是否成功更新
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                task.progress.update(progress)
                return True
            return False

    async def get_pausable_task(self, user_id: str, task_id: str) -> PausableTask | None:
        """
        获取可暂停任务详情

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            PausableTask: 任务对象
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                return task
            return None

    async def get_pausable_tasks(self, user_id: str) -> list[PausableTask]:
        """
        获取用户的可暂停任务

        Args:
            user_id: 用户ID

        Returns:
            List[PausableTask]: 任务列表
        """
        async with self._lock:
            return [t for t in self._pausable_tasks.values() if t.user_id == user_id]

    async def delete_pausable_task(self, user_id: str, task_id: str) -> bool:
        """
        删除可暂停任务

        Args:
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功删除
        """
        async with self._lock:
            task = self._pausable_tasks.get(task_id)
            if task and task.user_id == user_id:
                del self._pausable_tasks[task_id]
                logger.info(f"[UnifiedTaskScheduler] 删除可暂停任务: {task_id}")
                return True
            return False

    # ========== 统一查询 ==========

    async def get_all_tasks(self, user_id: str) -> dict[str, list]:
        """
        获取用户的所有任务（两种类型）

        Args:
            user_id: 用户ID

        Returns:
            Dict: 包含scheduled和pausable两个键的字典
        """
        return {
            "scheduled": await self.get_scheduled_tasks(user_id),
            "pausable": await self.get_pausable_tasks(user_id)
        }

    async def get_task_statistics(self, user_id: str) -> dict[str, Any]:
        """
        获取用户任务统计信息

        Args:
            user_id: 用户ID

        Returns:
            Dict: 统计信息
        """
        scheduled = await self.get_scheduled_tasks(user_id)
        pausable = await self.get_pausable_tasks(user_id)

        return {
            "total_scheduled": len(scheduled),
            "total_pausable": len(pausable),
            "scheduled_by_status": {
                "pending": len([t for t in scheduled if t.status == "pending"]),
                "running": len([t for t in scheduled if t.status == "running"]),
                "paused": len([t for t in scheduled if t.status == "paused"]),
                "completed": len([t for t in scheduled if t.status == "completed"]),
                "failed": len([t for t in scheduled if t.status == "failed"]),
            },
            "pausable_by_status": {
                "running": len([t for t in pausable if t.status == "running"]),
                "paused": len([t for t in pausable if t.status == "paused"]),
                "stopped": len([t for t in pausable if t.status == "stopped"]),
            }
        }

    # ========== 内部执行方法 ==========

    def _execute_scheduled_task(self, task_id: str):
        """
        执行定时任务（APScheduler 同步回调桥接）

        Args:
            task_id: 任务ID
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_execute_scheduled_task(task_id))
        except RuntimeError:
            asyncio.run(self._async_execute_scheduled_task(task_id))

    async def _async_execute_scheduled_task(self, task_id: str):
        """
        异步执行定时任务（实际逻辑）

        Args:
            task_id: 任务ID
        """
        async with self._lock:
            task = self._scheduled_tasks.get(task_id)
            if not task:
                logger.warning(f"[UnifiedTaskScheduler] 任务不存在: {task_id}")
                return

            if task.status == 'paused':
                logger.info(f"[UnifiedTaskScheduler] 任务已暂停，跳过执行: {task_id}")
                return

            task.status = 'running'
            task.run_count += 1

        # 执行工具调用（不进入ReAct循环）
        try:
            if self._executor and task.tool_name:
                result = await asyncio.to_thread(
                    self._executor, task.tool_name, task.tool_params, task.user_id
                )

                # 【游戏化】定时任务执行经验值奖励
                await asyncio.to_thread(self._run_gamification_for_task, task)

                task.last_execution = {
                    "timestamp": datetime.now().isoformat(),
                    "result": str(result)[:500]  # 截断结果
                }
                task.status = 'pending' if task.trigger_type != 'once' else 'completed'
                logger.info(f"[UnifiedTaskScheduler] 任务执行成功: {task.task_name}")
            else:
                error_msg = "未设置任务执行器或工具名称"
                task.last_execution = {
                    "timestamp": datetime.now().isoformat(),
                    "error": error_msg
                }
                task.status = 'failed'
                logger.error(f"[UnifiedTaskScheduler] 任务执行失败: {task.task_name}, 错误: {error_msg}")

        except Exception as e:
            task.last_execution = {
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
            task.status = 'failed'
            logger.error(f"[UnifiedTaskScheduler] 任务执行失败: {task.task_name}, 错误: {e}")

    def _run_gamification_for_task(self, task: UnifiedScheduledTask):
        """同步执行游戏化逻辑（在线程池中运行）"""
        try:
            import time

            from api.gamification_api import _calculate_level, _load_gamification_data, _save_gamification_data

            user_id = task.user_id or "default_user"

            # 加载数据
            data = _load_gamification_data()
            if user_id not in data:
                data[user_id] = {
                    "level": 1, "xp": 0, "total_xp_earned": 0,
                    "tools_used": {}, "categories_unlocked": [],
                    "achievements": [], "created_at": time.time(),
                    "last_active": time.time()
                }

            user_data = data[user_id]

            # 定时任务基础经验值
            xp_earned = 15

            # 更新经验值
            old_level = _calculate_level(user_data["xp"])
            user_data["xp"] += xp_earned
            user_data["total_xp_earned"] += xp_earned
            user_data["last_active"] = time.time()
            new_level = _calculate_level(user_data["xp"])

            # 保存数据
            _save_gamification_data(data)

            # 发送事件
            from core.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            sync.emit_event("xp_earned", user_id, {
                "xp_earned": xp_earned,
                "source": "scheduled_task",
                "task_name": task.task_name,
                "total_xp": user_data["xp"],
                "level_up": new_level > old_level,
                "new_level": new_level if new_level > old_level else None
            })

            if new_level > old_level:
                sync.emit_event("level_up", user_id, {
                    "old_level": old_level,
                    "new_level": new_level
                })

            logger.info(f"[Gamification] 定时任务执行，用户 {user_id} 获得 {xp_earned} XP")

        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] [Gamification] 记录定时任务经验值失败: {e}")

    def shutdown(self):
        """关闭调度器"""
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
                logger.info("[UnifiedTaskScheduler] 调度器已关闭")
            except Exception as e:
                logger.error(f"[UnifiedTaskScheduler] 关闭调度器失败: {e}")


# 统一调度器单例实例
_unified_scheduler: UnifiedTaskScheduler | None = None


def get_unified_scheduler() -> UnifiedTaskScheduler:
    """
    获取统一调度器单例

    Returns:
        UnifiedTaskScheduler: 统一调度器实例
    """
    global _unified_scheduler
    if _unified_scheduler is None:
        _unified_scheduler = UnifiedTaskScheduler()
    return _unified_scheduler


def create_unified_scheduler() -> UnifiedTaskScheduler:
    """
    创建新的统一调度器实例（非单例）

    Returns:
        UnifiedTaskScheduler: 新的调度器实例
    """
    return UnifiedTaskScheduler()


# =============================================================================
# 统一调度器便捷函数
# =============================================================================

async def schedule_task(
    user_id: str,
    task_name: str,
    trigger_type: str,
    trigger_config: dict,
    tool_name: str,
    tool_params: dict = None
) -> str:
    """
    创建定时任务（便捷函数）

    Args:
        user_id: 用户ID
        task_name: 任务名称
        trigger_type: 触发类型 ('interval' | 'cron' | 'once')
        trigger_config: 触发配置
        tool_name: 工具名称
        tool_params: 工具参数

    Returns:
        str: 任务ID
    """
    scheduler = get_unified_scheduler()
    return await scheduler.create_scheduled_task(
        user_id=user_id,
        task_name=task_name,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        tool_name=tool_name,
        tool_params=tool_params or {}
    )


async def cancel_task(user_id: str, task_id: str) -> bool:
    """
    取消任务（便捷函数）
    自动判断任务类型并取消

    Args:
        user_id: 用户ID
        task_id: 任务ID

    Returns:
        bool: 是否成功取消
    """
    scheduler = get_unified_scheduler()

    # 尝试取消定时任务
    if task_id.startswith("sched_"):
        return await scheduler.cancel_scheduled_task(user_id, task_id)

    # 尝试取消可暂停任务
    if task_id.startswith("pause_"):
        return await scheduler.stop_task(user_id, task_id)

    return False


async def list_user_tasks(user_id: str) -> dict[str, list]:
    """
    列出用户所有任务（便捷函数）

    Args:
        user_id: 用户ID

    Returns:
        Dict: 包含所有任务的字典
    """
    scheduler = get_unified_scheduler()
    return await scheduler.get_all_tasks(user_id)


# =============================================================================
# 统一调度器总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件（task_scheduler.py）现在包含 SiliconBase V5 系统的统一任务调度器。
# P1-005修复：合并 task_scheduler.py 和 ai_task_scheduler.py
#
# 【统一调度器设计】
# UnifiedTaskScheduler 合并了两种任务类型：
# 1. 大纲长任务（定时任务）: 不进入ReAct循环，直接执行工具调用
# 2. 可暂停任务: 进入ReAct循环，支持暂停/恢复/停止
#
# 【核心类说明】
# 1. PausableTask(dataclass): 可暂停任务数据类
#    - 支持暂停/恢复/停止状态管理
#    - 需要AI确认理解后才能恢复
#
# 2. UnifiedScheduledTask(dataclass): 统一调度任务数据类
#    - 大纲长任务的统一表示
#    - 支持interval、cron、once三种触发类型
#
# 3. UnifiedTaskScheduler: 统一调度器主类
#    - 管理所有类型任务
#    - 使用APScheduler作为底层调度引擎
#    - 提供完整的任务CRUD操作
#
# 【向后兼容】
# - TaskScheduler 类仍然保留，用于向后兼容
# - ai_task_scheduler.py 已标记弃用，委托给 UnifiedTaskScheduler
# - 原有的便捷函数仍然可用（已升级为 async）
#
# 【使用示例】
# # 获取统一调度器
# scheduler = get_unified_scheduler()
#
# # 创建定时任务
# task_id = await scheduler.create_scheduled_task(
#     user_id="user_001",
#     task_name="每小时检查邮件",
#     trigger_type="interval",
#     trigger_config={"seconds": 3600},
#     tool_name="check_email",
#     tool_params={}
# )
#
# # 创建可暂停任务
# task_id = await scheduler.create_pausable_task(
#     user_id="user_001",
#     task_name="数据分析任务",
#     task_config={"steps": [...]}
# )
#
# # 暂停和恢复
# await scheduler.pause_task(user_id, task_id)
# await scheduler.resume_task(user_id, task_id, "我已理解任务需求，将继续执行...")
#
# =============================================================================
