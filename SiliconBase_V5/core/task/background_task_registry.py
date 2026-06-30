#!/usr/bin/env python3
"""
后台任务注册表 - 防止野任务（fire-and-forget）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

设计原则：
- 所有长期运行的后台任务必须通过 register() 注册
- 提供 cancel_all() / wait_all() / health_check() 接口
- 自动捕获异常并记录，防止静默失败
- 使用 asyncio.Lock 保证线程安全

使用示例：
    registry = BackgroundTaskRegistry("trading")
    task = await registry.register("monitor_loop", self._monitor_loop())
    # ... 稍后 ...
    await registry.cancel_all(timeout=10.0)
"""

import asyncio
import contextlib
import time
import traceback
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from core.diagnostic import safe_create_task
from core.logger import logger


@dataclass
class TaskHealth:
    """任务健康状态"""
    name: str
    done: bool
    cancelled: bool
    running: bool
    exception: str | None = None
    registered_at: float = field(default_factory=time.time)


class BackgroundTaskRegistry:
    """
    后台任务注册表

    治理目标：消灭所有 fire-and-forget safe_create_task(), name="async_task") 调用。
    所有后台任务必须在此注册，获得名称、监控、优雅关闭能力。
    """

    def __init__(self, name: str = "default"):
        self._name = name
        self._tasks: dict[str, asyncio.Task] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        name: str,
        coro: Coroutine,
        *,
        on_exception: Callable[[str, Exception], None] | None = None
    ) -> asyncio.Task:
        """
        注册一个后台任务

        Args:
            name: 任务名称（唯一标识）
            coro: 协程对象（不是协程函数！）
            on_exception: 异常回调，签名 (name, exc) -> None

        Returns:
            asyncio.Task: 已注册的任务对象

        Raises:
            ValueError: 如果 name 为空
        """
        if not name:
            raise ValueError("任务名称不能为空")

        old_task = None
        async with self._lock:
            # 如果同名任务已存在且未完成，先标记取消（在锁外等待）
            if name in self._tasks:
                old_task = self._tasks[name]
                if not old_task.done():
                    old_task.cancel()
                    logger.warning(
                        f"[{self._name}] 取消旧任务 '{name}' 并重新注册"
                    )

            task = asyncio.create_task(
                self._wrap_coro(name, coro, on_exception)
            )
            self._tasks[name] = task
            self._metadata[name] = {
                "registered_at": time.time(),
                "cancelled_by": None,
            }
            logger.info(f"[{self._name}] 任务 '{name}' 已注册")

        # 【Fix】在锁外等待旧任务完成，避免与 _wrap_coro 的 finally 块死锁
        if old_task is not None and not old_task.done():
            try:
                await old_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(
                    f"[{self._name}] 旧任务 '{name}' 取消时异常: {e}"
                )

        return task

    async def _wrap_coro(
        self,
        name: str,
        coro: Coroutine,
        on_exception: Callable[[str, Exception], None] | None = None
    ):
        """包装协程：捕获异常 + 清理注册表"""
        try:
            return await coro
        except asyncio.CancelledError:
            logger.info(f"[{self._name}] 任务 '{name}' 已取消")
            raise
        except Exception as e:
            logger.error(
                f"[{self._name}] 任务 '{name}' 异常: {e}\n{traceback.format_exc()}"
            )
            if on_exception:
                try:
                    on_exception(name, e)
                except Exception as cb_err:
                    logger.error(
                        f"[{self._name}] 任务 '{name}' 异常回调失败: {cb_err}"
                    )
            raise
        finally:
            async with self._lock:
                self._tasks.pop(name, None)
                self._metadata.pop(name, None)

    async def cancel(self, name: str, timeout: float = 5.0) -> bool:
        """取消指定任务并等待完成"""
        async with self._lock:
            task = self._tasks.get(name)
            if task is None:
                return False
            if task.done():
                return True
            task.cancel()
            self._metadata[name]["cancelled_by"] = "registry.cancel"

        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[{self._name}] 任务 '{name}' 取消超时")
            return False
        except asyncio.CancelledError:
            pass
        return True

    async def cancel_all(self, timeout: float = 10.0) -> dict[str, bool]:
        """
        取消所有任务并等待完成

        Args:
            timeout: 每个任务的等待超时（秒）

        Returns:
            Dict[str, bool]: 各任务取消结果
        """
        async with self._lock:
            pending_tasks = {
                name: task for name, task in self._tasks.items()
                if not task.done()
            }
            for name, task in pending_tasks.items():
                task.cancel()
                self._metadata[name]["cancelled_by"] = "registry.cancel_all"

        results = {}
        for name, task in pending_tasks.items():
            try:
                await asyncio.wait_for(task, timeout=timeout)
                results[name] = True
            except asyncio.TimeoutError:
                logger.warning(f"[{self._name}] 任务 '{name}' 取消超时")
                results[name] = False
            except asyncio.CancelledError:
                results[name] = True
            except Exception as e:
                logger.error(f"[{self._name}] 任务 '{name}' 取消时异常: {e}")
                results[name] = False

        logger.info(f"[{self._name}] 取消全部任务完成: {results}")
        return results

    def health_check(self) -> dict[str, TaskHealth]:
        """返回所有任务健康状态"""
        result = {}
        for name, task in self._tasks.items():
            exc = None
            if task.done() and not task.cancelled():
                try:
                    task.exception()
                except Exception as e:
                    exc = str(e)

            result[name] = TaskHealth(
                name=name,
                done=task.done(),
                cancelled=task.cancelled(),
                running=not task.done(),
                exception=exc,
                registered_at=self._metadata.get(name, {}).get("registered_at", 0),
            )
        return result

    def get_task(self, name: str) -> asyncio.Task | None:
        """获取指定任务"""
        return self._tasks.get(name)

    def is_running(self, name: str) -> bool:
        """检查指定任务是否仍在运行"""
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def __len__(self) -> int:
        """返回当前注册的任务数"""
        return len(self._tasks)

    def __contains__(self, name: str) -> bool:
        """检查是否包含指定任务"""
        return name in self._tasks

    def __repr__(self) -> str:
        running = sum(1 for t in self._tasks.values() if not t.done())
        return f"<BackgroundTaskRegistry '{self._name}' tasks={len(self._tasks)} running={running}>"


# ═══════════════════════════════════════════════════════════════
# 便捷函数：快速包装 fire-and-forget create_task
# ═══════════════════════════════════════════════════════════════

def create_tracked_task(
    coro: Coroutine,
    *,
    name: str | None = None,
    registry: BackgroundTaskRegistry | None = None,
    on_exception: Callable[[str, Exception], None] | None = None
) -> asyncio.Task:
    """
    创建一个有追踪的任务（推荐替代裸 create_task）

    如果没有提供 registry，则退化为带异常捕获的 create_task，
    但至少不会静默丢失异常。
    """
    task_name = name or f"tracked_{id(coro)}"

    async def _wrapper():
        try:
            return await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                f"[TrackedTask] '{task_name}' 异常: {e}\n{traceback.format_exc()}"
            )
            if on_exception:
                with contextlib.suppress(Exception):
                    on_exception(task_name, e)
            raise

    task = safe_create_task(_wrapper(), name=task_name)

    if registry is not None:
        # 如果提供了注册表，在任务完成后自动清理
        def _on_done(t: asyncio.Task):
            if t.done() and not t.cancelled():
                try:
                    t.exception()
                except Exception as exc:
                    logger.error(f"[TrackedTask] '{task_name}' 未处理异常: {exc}")
        task.add_done_callback(_on_done)

    return task
