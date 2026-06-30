#!/usr/bin/env python3
"""
AsyncToolGateway - 统一异步执行网关
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
V5/V6 融合重构 Phase 4 核心基础设施。

职责：
1. 同步函数桥接：在线程池中执行阻塞调用，支持取消和超时
2. 异步函数包装：为原生 async 函数提供统一的取消检查和超时控制
3. 统一收口：所有异步执行（无论 sync/async 底层）都经过本网关

设计原则：
1. 所有工具异步执行统一走网关，获得取消追踪和超时保护
2. 复用 ExecutorManager 的分类线程池，不独立建池
3. 内建协作式取消机制（不强制杀线程/协程，但执行完成后检查 flag）
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from core.agent.phase_context import PhaseContext
from core.agent.phase_registry import register_phase
from core.logger import logger
from core.utils.executors import ExecutorManager


class AsyncToolGateway:
    """
    异步执行网关：统一桥接同步阻塞调用，并包装原生 async 调用。
    """

    def __init__(self):
        # 复用 ExecutorManager 的工具执行隔离池
        self._executor = ExecutorManager.get_executor("tool")
        self._cancel_flags: dict[str, threading.Event] = {}

    @property
    def max_workers(self) -> int:
        return ExecutorManager.TOOL_MAX_WORKERS

    async def execute(
        self,
        task_id: str,
        fn: Callable,
        *args,
        timeout: float | None = 30.0,
        **kwargs
    ) -> Any:
        """
        执行异步函数，提供协作式取消和超时控制。

        [Phase 2] 已删除 run_in_executor 同步桥接。只接受原生 async 函数。
        如果传入同步函数，将抛出 TypeError 强制要求异步化。

        Args:
            task_id: 任务标识，用于取消追踪。
            fn: 待执行的异步函数。
            *args, **kwargs: 传递给 fn 的参数。
            timeout: 超时秒数，None 表示不超时。

        Returns:
            fn 的返回值。

        Raises:
            TypeError: 如果 fn 不是 async 函数。
            asyncio.CancelledError: 如果该 task_id 被请求取消。
            asyncio.TimeoutError: 如果执行超时。
            Exception: fn 执行期间抛出的原始异常。
        """
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(
                f"[AsyncToolGateway] execute() 只接受 async 函数，"
                f"{getattr(fn, '__name__', fn)} 不是协程函数。"
                f"请将工具改为原生 async 实现。"
            )
        # 统一走 execute_async 实现
        return await self.execute_async(task_id, fn, *args, timeout=timeout, **kwargs)

    async def execute_async(
        self,
        task_id: str,
        async_fn: Callable[..., Awaitable],
        *args,
        timeout: float | None = 30.0,
        **kwargs
    ) -> Any:
        """
        包装原生 async 函数，提供统一的取消检查和超时控制。

        [Phase 2] 已删除同步桥接，只接受原生 async 函数。

        Args:
            task_id: 任务标识，用于取消追踪。
            async_fn: 待执行的异步函数。
            *args, **kwargs: 传递给 async_fn 的参数。
            timeout: 超时秒数，None 表示不超时。

        Returns:
            async_fn 的返回值。

        Raises:
            TypeError: 如果 async_fn 不是 async 函数。
            asyncio.CancelledError: 如果该 task_id 被请求取消。
            asyncio.TimeoutError: 如果执行超时。
        """
        if not task_id:
            raise ValueError("task_id 不能为空")

        if not asyncio.iscoroutinefunction(async_fn):
            raise TypeError(
                f"[AsyncToolGateway] execute_async() 只接受 async 函数，"
                f"{getattr(async_fn, '__name__', async_fn)} 不是协程函数。"
                f"请将工具改为原生 async 实现。"
            )

        cancel_event = threading.Event()
        self._cancel_flags[task_id] = cancel_event

        async def _wrapped() -> Any:
            try:
                result = await async_fn(*args, **kwargs)
            except Exception:
                self._cancel_flags.pop(task_id, None)
                raise

            if cancel_event.is_set():
                self._cancel_flags.pop(task_id, None)
                raise asyncio.CancelledError(
                    f"Task {task_id} was cancelled during execution"
                )

            self._cancel_flags.pop(task_id, None)
            return result

        try:
            coro = _wrapped()
            if timeout is not None:
                return await asyncio.wait_for(coro, timeout=timeout)
            return await coro
        except asyncio.TimeoutError:
            cancel_event.set()
            self._cancel_flags.pop(task_id, None)
            logger.warning(f"[AsyncToolGateway] Task {task_id} timeout ({timeout}s)")
            raise
        except Exception:
            self._cancel_flags.pop(task_id, None)
            raise

    def request_cancel(self, task_id: str) -> bool:
        """
        请求取消指定任务。

        注意：Python 无法强制中断正在运行的线程/协程。本方法设置协作式取消标志，
        当 fn/async_fn 执行完毕后，_wrapped 会检查该标志并抛出 CancelledError。
        对于极长耗时的阻塞调用（如应用启动等待 30 秒），仍然无法立即中断，
        但至少可以防止取消后的结果污染 working_memory 和 state。

        Args:
            task_id: 要取消的任务 ID。

        Returns:
            True 如果成功找到并标记了任务；False 如果任务已完成或不存在。
        """
        event = self._cancel_flags.get(task_id)
        if event:
            event.set()
            logger.info(f"[AsyncToolGateway] Cancel requested for task: {task_id}")
            return True
        return False

    def is_active(self, task_id: str) -> bool:
        """检查指定任务是否仍在执行中。"""
        return task_id in self._cancel_flags

    def active_count(self) -> int:
        """返回当前活跃的任务数。"""
        return len(self._cancel_flags)


# 全局单例
async_gateway = AsyncToolGateway()


async def tool_execution_phase(ctx: PhaseContext):
    """阶段包装：从 phase_ctx 取参，调用 async_gateway.execute_async

    [Phase 2] 已统一为 execute_async，只接受原生 async 函数。
    """
    tool_fn = ctx.get("tool_fn")
    if tool_fn is None:
        raise ValueError("tool_execution_phase: tool_fn 不能为空")
    return await async_gateway.execute_async(
        ctx.get("task_id", ""),
        tool_fn,
        *ctx.get("tool_args", []),
        timeout=ctx.get("tool_timeout", 30.0),
        **ctx.get("tool_kwargs", {}),
    )


register_phase("tool_execution", tool_execution_phase, order=3)
