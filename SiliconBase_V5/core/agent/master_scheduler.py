#!/usr/bin/env python3
"""
主AI调度器 - MasterScheduler
SiliconBase V5 核心调度枢纽

【Phase 1 改造】融合 ConcurrentTaskScheduler 的优先级队列 + Semaphore 并发控制
- 任务不再裸奔进 AgentLoop，而是先进队列排队
- 并发上限 5，防止系统被压垮
- 每个任务有状态机和取消事件
- 连续失败自动熔断冷却

调用方无需修改：dispatch() 保持原有接口，内部通过 future 等待 worker 执行完成。
"""

import asyncio
import contextlib
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger
from core.orchestration.task_scheduler import ConcurrentTaskScheduler, TaskPriority
from core.task.task_queue import Task


class DispatchType(Enum):
    DIRECT = "direct"
    SUBAGENT = "subagent"
    COMMANDER = "commander"
    LONG_TASK = "long_task"
    UNKNOWN = "unknown"


class TaskState(Enum):
    """任务状态机"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MasterSchedulerError(Exception):
    """主调度器错误 - 必须被上层捕获"""
    pass


@dataclass
class DispatchDecision:
    dispatch_type: DispatchType
    target: str = ""
    reason: str = ""
    subtasks: list[dict] = field(default_factory=list)


@dataclass
class MasterSchedulerResult:
    success: bool
    final_answer: str = ""
    working_memory: Any | None = None
    error: str = ""
    dispatch_type: DispatchType = DispatchType.UNKNOWN
    subagent_results: list[Any] = field(default_factory=list)


@dataclass
class TaskInfo:
    """队列中的任务信息"""
    task_id: str
    priority: int
    state: TaskState
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    result: MasterSchedulerResult | None = None
    error_count: int = 0


class MasterScheduler:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # ═══════════════════════════════════════════════════════════════
        # 【Phase 1 改造】使用 ConcurrentTaskScheduler 作为底层队列与执行器
        # ═══════════════════════════════════════════════════════════════
        self._scheduler = ConcurrentTaskScheduler(max_concurrent=5)
        self._scheduler.register_executor("master", self._on_scheduler_execute)

        self._task_infos: dict[str, TaskInfo] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

        # 熔断器：连续失败计数和冷却时间
        self._consecutive_failures = 0
        self._circuit_breaker_triggered = False
        self._cooldown_until = 0.0
        self._failure_threshold = 3
        self._cooldown_seconds = 30.0

        logger.info("[MasterScheduler] 主调度器初始化完成（基于 ConcurrentTaskScheduler）")

    # ═══════════════════════════════════════════════════════════════
    # 生命周期管理
    # ═══════════════════════════════════════════════════════════════

    async def start(self):
        """启动后台调度 worker"""
        if not self._scheduler._running:
            await self._scheduler.start()
            self._loop = asyncio.get_running_loop()
            logger.info("[MasterScheduler] 后台调度 worker 已启动（ConcurrentTaskScheduler）")

    async def stop(self):
        """停止后台调度 worker"""
        await self._scheduler.stop()
        if self._scheduler._worker_task:
            try:
                await asyncio.wait_for(self._scheduler._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._scheduler._worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._scheduler._worker_task
        logger.info("[MasterScheduler] 后台调度 worker 已停止（ConcurrentTaskScheduler）")

    # ═══════════════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════════════

    async def dispatch(
        self,
        user_request: str,
        task: Task,
        chat_history: list[dict[str, Any]] | None = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance=None,
        mode: str = "daily",
        user_id: str | None = None,
        db_session_id: str | None = None,
        context_flag: str | None = None
    ) -> MasterSchedulerResult:
        """
        唯一调度入口。失败时记录ERROR日志并返回明确错误，绝不静默。

        如果 worker 已启动：任务提交到队列，通过 future 等待执行完成。
        如果 worker 未启动：直接执行（兼容旧模式）。
        """
        if not user_request:
            error_msg = "[MasterScheduler] user_request is empty, reject dispatch"
            logger.error(error_msg)
            return MasterSchedulerResult(success=False, error=error_msg)
        if not task:
            error_msg = "[MasterScheduler] task object is empty, reject dispatch"
            logger.error(error_msg)
            return MasterSchedulerResult(success=False, error=error_msg)

        # 熔断检查
        if self._circuit_breaker_triggered:
            if time.time() < self._cooldown_until:
                remaining = int(self._cooldown_until - time.time())
                error_msg = f"[MasterScheduler] 熔断中，请 {remaining}s 后再试"
                logger.warning(error_msg)
                return MasterSchedulerResult(success=False, error=error_msg)
            else:
                self._circuit_breaker_triggered = False
                self._consecutive_failures = 0
                logger.info("[MasterScheduler] 熔断恢复")

        if not self._scheduler._running:
            # Worker 未启动：直接执行（兼容旧模式）
            return await self._execute_directly(
                user_request, task, chat_history, chat_count,
                session_id, voice_instance, mode, user_id, db_session_id, context_flag
            )

        # Worker 已启动：提交到 ConcurrentTaskScheduler，等待完成
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        future = asyncio.get_event_loop().create_future()
        priority_int = await self._calculate_priority(user_request)

        # 映射到 TaskPriority
        priority_map = {
            0: TaskPriority.CRITICAL,
            1: TaskPriority.HIGH,
            2: TaskPriority.NORMAL,
            3: TaskPriority.LOW,
            4: TaskPriority.BACKGROUND,
        }
        cts_priority = priority_map.get(priority_int, TaskPriority.NORMAL)

        self._task_infos[task_id] = TaskInfo(
            task_id=task_id,
            priority=priority_int,
            state=TaskState.PENDING,
            created_at=time.time()
        )
        self._cancel_events[task_id] = asyncio.Event()
        self._futures[task_id] = future

        await self._scheduler.submit(
            task_type="master",
            payload={
                "internal_task_id": task_id,
                "user_request": user_request,
                "task": task,
                "chat_history": chat_history or [],
                "chat_count": chat_count,
                "session_id": session_id,
                "db_session_id": db_session_id,
                "voice_instance": voice_instance,
                "mode": mode,
                "user_id": user_id,
                "context_flag": context_flag,
            },
            priority=cts_priority,
            user_id=user_id,
            task_id=task_id,
        )

        logger.info("[MasterScheduler] 任务已入队: %s (priority=%d/%s)", task_id, priority_int, cts_priority.name)

        try:
            result = await asyncio.wait_for(future, timeout=300.0)
            return result
        except asyncio.TimeoutError:
            logger.error("[MasterScheduler] 任务超时: %s", task_id)
            self._cancel_events[task_id].set()
            return MasterSchedulerResult(
                success=False,
                error="[MasterScheduler] 任务执行超时（300秒）"
            )

    async def submit(
        self,
        user_request: str,
        task: Task,
        chat_history: list[dict[str, Any]] | None = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance=None,
        mode: str = "daily",
        user_id: str | None = None,
        db_session_id: str | None = None
    ) -> str:
        """
        非阻塞提交任务。只返回 task_id，不等待执行完成。
        调用方可通过 get_task_status(task_id) 查询状态。
        """
        if not self._scheduler._running:
            raise MasterSchedulerError("Worker 未启动，请先调用 start()")

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        priority_int = await self._calculate_priority(user_request)

        priority_map = {
            0: TaskPriority.CRITICAL,
            1: TaskPriority.HIGH,
            2: TaskPriority.NORMAL,
            3: TaskPriority.LOW,
            4: TaskPriority.BACKGROUND,
        }
        cts_priority = priority_map.get(priority_int, TaskPriority.NORMAL)

        self._task_infos[task_id] = TaskInfo(
            task_id=task_id,
            priority=priority_int,
            state=TaskState.PENDING,
            created_at=time.time()
        )
        self._cancel_events[task_id] = asyncio.Event()

        await self._scheduler.submit(
            task_type="master",
            payload={
                "internal_task_id": task_id,
                "user_request": user_request,
                "task": task,
                "chat_history": chat_history or [],
                "chat_count": chat_count,
                "session_id": session_id,
                "db_session_id": db_session_id,
                "voice_instance": voice_instance,
                "mode": mode,
                "user_id": user_id,
            },
            priority=cts_priority,
            user_id=user_id,
            task_id=task_id,
        )

        logger.info("[MasterScheduler] 任务已提交: %s (priority=%d/%s)", task_id, priority_int, cts_priority.name)
        return task_id

    async def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """查询任务状态（异步版本）"""
        info = self._task_infos.get(task_id)
        if not info:
            return None
        return {
            "task_id": info.task_id,
            "state": info.state.value,
            "priority": info.priority,
            "created_at": info.created_at,
            "started_at": info.started_at,
            "completed_at": info.completed_at,
            "success": info.result.success if info.result else None,
            "error": info.result.error if info.result else None,
        }

    async def cancel_task(self, task_id: str) -> bool:
        """请求取消任务（异步版本）"""
        event = self._cancel_events.get(task_id)
        if event and not event.is_set():
            event.set()
            logger.info("[MasterScheduler] 取消请求已发送: %s", task_id)
            return True
        return False

    async def list_active_tasks(self) -> list[dict[str, Any]]:
        """列出所有活跃任务（异步版本）"""
        return [
            {
                "task_id": info.task_id,
                "state": info.state.value,
                "priority": info.priority,
                "elapsed": time.time() - info.created_at,
            }
            for info in self._task_infos.values()
            if info.state in (TaskState.PENDING, TaskState.RUNNING)
        ]

    # ═══════════════════════════════════════════════════════════════
    # 内部实现
    # ═══════════════════════════════════════════════════════════════

    async def _on_scheduler_execute(self, payload: dict[str, Any]):
        """注册给 ConcurrentTaskScheduler 的执行器。负责状态机、熔断器和 future 通知。"""
        task_id = payload.get("internal_task_id")
        if not task_id:
            logger.error("[MasterScheduler] _on_scheduler_execute: missing internal_task_id")
            return

        info = self._task_infos.get(task_id)
        if not info:
            logger.warning("[MasterScheduler] _on_scheduler_execute: unknown task_id %s", task_id)
            return

        # 检查取消
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event and cancel_event.is_set():
            info.state = TaskState.CANCELLED
            result = MasterSchedulerResult(success=False, error="任务被取消")
            info.result = result
            info.completed_at = time.time()
            await self._notify_future(task_id, result)
            return

        info.state = TaskState.RUNNING
        info.started_at = time.time()

        try:
            result = await self._execute_core(task_id, payload)
            info.state = TaskState.COMPLETED
            info.result = result
            info.completed_at = time.time()

            # 成功：重置失败计数
            self._consecutive_failures = 0

            await self._notify_future(task_id, result)

        except Exception as e:
            logger.error(
                "[MasterScheduler] 任务执行失败: %s - %s",
                task_id, e, exc_info=True
            )
            info.state = TaskState.FAILED
            info.error_count += 1
            error_result = MasterSchedulerResult(
                success=False,
                error=f"[MasterScheduler] 任务执行失败: {e}"
            )
            info.result = error_result
            info.completed_at = time.time()

            # 熔断逻辑
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_breaker_triggered = True
                self._cooldown_until = time.time() + self._cooldown_seconds
                logger.error(
                    "[MasterScheduler] 熔断触发！连续失败 %d 次，冷却 %ds",
                    self._consecutive_failures, self._cooldown_seconds
                )

            await self._notify_future(task_id, error_result)

    async def _notify_future(self, task_id: str, result: MasterSchedulerResult):
        """通知等待方任务已完成（线程安全版本）

        兼容跨事件循环调用：如果 future 绑定的 loop 与当前不一致，
        使用 call_soon_threadsafe 安全回推结果。
        """
        future = self._futures.pop(task_id, None)
        if future and not future.done():
            try:
                loop = future.get_loop()
                if loop == self._loop:
                    future.set_result(result)
                else:
                    loop.call_soon_threadsafe(future.set_result, result)
            except (RuntimeError, AttributeError):
                # 循环已关闭或旧版本 asyncio 无 get_loop
                future.set_result(result)

    async def _execute_core(self, task_id: str, context: dict[str, Any]) -> MasterSchedulerResult:
        """实际执行任务（包装原有的分支逻辑）"""
        user_request = context["user_request"]
        task = context["task"]
        chat_history = context.get("chat_history", [])
        chat_count = context.get("chat_count", 0)
        session_id = context.get("session_id", "console")
        db_session_id = context.get("db_session_id")
        voice_instance = context.get("voice_instance")
        mode = context.get("mode", "daily")
        user_id = context.get("user_id")
        context_flag = context.get("context_flag")
        if task and hasattr(task, "metadata") and task.metadata is not None:
            task.metadata["context_flag"] = context_flag

        decision = await self._classify_intent(user_request)
        logger.info(
            "[MasterScheduler] 任务 %s 决策: type=%s, target=%s, reason=%s",
            task_id, decision.dispatch_type.value, decision.target, decision.reason
        )

        if decision.dispatch_type == DispatchType.DIRECT:
            return await self._run_direct(
                task, user_request, chat_history, chat_count,
                session_id, voice_instance, mode, user_id, db_session_id
            )
        elif decision.dispatch_type == DispatchType.SUBAGENT:
            return await self._delegate_to_subagents(
                decision, task, user_request, chat_history,
                chat_count, session_id, voice_instance, mode, user_id, db_session_id
            )
        elif decision.dispatch_type == DispatchType.COMMANDER:
            return await self._delegate_to_commander(user_request, task, session_id)
        elif decision.dispatch_type == DispatchType.LONG_TASK:
            return await self._schedule_long_task(
                user_request, task, session_id, voice_instance, mode, user_id, db_session_id
            )
        else:
            error_msg = f"[MasterScheduler] 未知调度类型: {decision.dispatch_type.value}"
            logger.error(error_msg)
            return MasterSchedulerResult(success=False, error=error_msg)

    async def _execute_directly(
        self, user_request, task, chat_history, chat_count,
        session_id, voice_instance, mode, user_id, db_session_id, context_flag=None
    ) -> MasterSchedulerResult:
        """Worker 未启动时的直接执行（兼容旧模式）"""
        return await self._execute_core(
            "direct_fallback",
            {
                "user_request": user_request,
                "task": task,
                "chat_history": chat_history,
                "chat_count": chat_count,
                "session_id": session_id,
                "db_session_id": db_session_id,
                "voice_instance": voice_instance,
                "mode": mode,
                "user_id": user_id,
                "context_flag": context_flag,
            }
        )

    async def _calculate_priority(self, user_request: str) -> int:
        """
        计算任务优先级（数字越小优先级越高）。
        紧急关键词 → 高优先级，普通查询 → 低优先级。
        【Phase 1】统一为原生 async 接口。
        """
        req = user_request.lower().strip()

        # P0: 紧急/安全相关
        urgent_keywords = ["紧急", "urgent", "stop", "停止", "取消", "cancel", "危险", "error"]
        if any(kw in req for kw in urgent_keywords):
            return 0

        # P1: 交易/资金相关
        trading_keywords = ["btc", "bitcoin", "trade", "buy", "sell", "order", "交易"]
        if any(kw in req for kw in trading_keywords):
            return 1

        # P2: 系统操作（文件删除、进程kill等）
        system_keywords = ["删除", "kill", "format", "重启", "shutdown"]
        if any(kw in req for kw in system_keywords):
            return 2

        # P3: 普通工具调用
        tool_keywords = ["打开", "启动", "搜索", "截图", "查询"]
        if any(kw in req for kw in tool_keywords):
            return 3

        # P4: 闲聊/简单问答（默认最低）
        return 4

    # ═══════════════════════════════════════════════════════════════
    # 原有逻辑（完全保留）
    # ═══════════════════════════════════════════════════════════════

    async def _classify_intent(self, user_request: str) -> DispatchDecision:
        request_lower = user_request.lower().strip()
        if not request_lower:
            return DispatchDecision(dispatch_type=DispatchType.DIRECT, reason="empty request, fallback to direct")
        try:
            # 【修复】先识别信息/能力询问，避免把"你们有 BTC 交易模块吗？"这类介绍性提问误判为交易命令
            info_query_markers = [
                "是什么", "有什么", "有哪些", "有没有", "介绍一下",
                "模块", "功能", "支持", "可以做什么", "能做什么", "会什么",
                "真的假的", "是不是真的", "对吗", "是不是", "你怎么看"
            ]
            trading_action_markers = [
                "买", "卖", "买入", "卖出", "下单", "交易", "开仓", "平仓",
                "做多", "做空", "执行", "启动交易", "开始交易", "运行策略",
                "执行策略", "分析行情", "查看行情", "监控行情"
            ]
            has_info_query = any(m in request_lower for m in info_query_markers)
            has_trading_action = any(m in request_lower for m in trading_action_markers)
            if has_info_query and not has_trading_action:
                return DispatchDecision(
                    dispatch_type=DispatchType.DIRECT,
                    reason="capability/info query, not a trading command"
                )

            crypto_keywords = [
                "btc", "bitcoin", "eth", "ethereum",
                "trade", "order", "buy", "sell", "position", "strategy"
            ]
            if any(kw in request_lower for kw in crypto_keywords):
                return DispatchDecision(
                    dispatch_type=DispatchType.COMMANDER,
                    target="ai_trading_commander",
                    reason="detected crypto keywords"
                )

            long_task_keywords = [
                "monitor", "schedule", "every", "hourly", "daily", "long term",
                "24h", "continuous", "daemon", "loop"
            ]
            if any(kw in request_lower for kw in long_task_keywords):
                return DispatchDecision(
                    dispatch_type=DispatchType.LONG_TASK,
                    reason="detected long-running keywords"
                )

            # 【修复】使用词边界正则匹配，避免路径名/文件名中的子串误判
            subagent_patterns = {
                r'\btest\b': "tester",
                r'\bresearch\b': "researcher",
                r'\bcode\s+review\b': "code_reviewer",
                r'\bsecurity\s+audit\b': "security_auditor",
                r'\boptimize\b': "performance_optimizer",
                r'\bplan\b': "planner",
            }
            matched = []
            for pattern, agent_name in subagent_patterns.items():
                if re.search(pattern, request_lower):
                    matched.append({"agent": agent_name, "task": user_request})
            if matched:
                return DispatchDecision(
                    dispatch_type=DispatchType.SUBAGENT,
                    subtasks=matched,
                    reason=f"matched {len(matched)} subagent(s)"
                )

            return DispatchDecision(dispatch_type=DispatchType.DIRECT, reason="no special keywords, direct execution")
        except Exception as e:
            logger.error("[MasterScheduler] intent classification error: %s", e, exc_info=True)
            return DispatchDecision(dispatch_type=DispatchType.DIRECT, reason=f"classification error fallback: {e}")

    async def _run_direct(self, task, user_request, chat_history, chat_count, session_id,
                          voice_instance, mode, user_id, db_session_id):
        try:
            from core.agent.agent_loop import run_agent_loop_async
            _task_id = task.id if task else None
            final_answer, working_memory = await run_agent_loop_async(
                task=task, max_rounds=30, chat_history=chat_history or [],
                chat_count=chat_count, session_id=session_id,
                db_session_id=db_session_id,
                voice_instance=voice_instance, mode=mode, user_id=user_id,
                cancel_event=self._cancel_events.get(_task_id),
                timeout_deadline=time.time() + 300.0
            )
            if final_answer is None:
                logger.error("[MasterScheduler] run_agent_loop returned None, session_id=%s", session_id)
                return MasterSchedulerResult(success=False, error="main AI loop returned empty result",
                                              dispatch_type=DispatchType.DIRECT)
            if "中断信号" in str(final_answer):
                logger.warning("[MasterScheduler] AgentLoop 被中断, session_id=%s", session_id)
                return MasterSchedulerResult(success=False, error=final_answer,
                                              dispatch_type=DispatchType.DIRECT)
            return MasterSchedulerResult(success=True, final_answer=final_answer,
                                          working_memory=working_memory, dispatch_type=DispatchType.DIRECT)
        except Exception as e:
            logger.error("[MasterScheduler] _run_direct exception: %s", e, exc_info=True)
            raise MasterSchedulerError(f"direct execution failed: {e}") from e

    async def _delegate_to_subagents(self, decision, task, user_request, chat_history,
                                      chat_count, session_id, voice_instance, mode, user_id, db_session_id):
        if not decision.subtasks:
            error_msg = "[MasterScheduler] SUBAGENT decision but subtasks is empty"
            logger.error(error_msg)
            return MasterSchedulerResult(success=False, error=error_msg)
        try:
            from core.subagent.manager import SubAgentManager
            subagent_manager = SubAgentManager()
            agent_names = [s["agent"] for s in decision.subtasks]
            logger.info("[MasterScheduler] delegating to %d subagents: %s", len(decision.subtasks), agent_names)
            parallel_tasks = [
                (st["agent"], st["task"], {"session_id": session_id}, {})
                for st in decision.subtasks
            ]
            results = await subagent_manager.parallel_delegate(parallel_tasks)
            failed = [r for r in results if getattr(r, "status", None) and r.status.value == "failed"]
            if failed:
                logger.error("[MasterScheduler] %d/%d subagents failed", len(failed), len(results))
            summary = await self._summarize(results, decision.subtasks)
            note = f"\n\n[Subagent Results Summary]\n{summary}\n\nReply user based on above."
            enriched_task = task
            if hasattr(task, "description"):
                enriched_task.description = getattr(task, "description", "") + note
            final = await self._run_direct(enriched_task, user_request + note, chat_history,
                                            chat_count, session_id, voice_instance, mode, user_id, db_session_id)
            final.dispatch_type = DispatchType.SUBAGENT
            final.subagent_results = results
            return final
        except Exception as e:
            logger.error("[MasterScheduler] subagent delegation exception: %s", e, exc_info=True)
            logger.warning("[MasterScheduler] fallback to direct execution")
            fallback = await self._run_direct(task, user_request, chat_history, chat_count,
                                               session_id, voice_instance, mode, user_id, db_session_id)
            fallback.dispatch_type = DispatchType.SUBAGENT
            fallback.error = f"subagent failed, fallback: {e}"
            return fallback

    async def _summarize(self, results, subtasks):
        lines = []
        for i, (result, td) in enumerate(zip(results, subtasks, strict=False)):
            name = td.get("agent", "unknown")
            status = getattr(result, "status", None)
            status_str = status.value if status else "unknown"
            output = getattr(result, "output", "")[:200]
            error = getattr(result, "error", "")
            lines.append(f"[{i+1}] {name}: {status_str}")
            if output:
                lines.append(f"    output: {output}")
            if error:
                lines.append(f"    error: {error}")
        return "\n".join(lines)

    async def _delegate_to_commander(self, user_request, task, session_id):
        try:
            from core.btc_integration.ai_trading_commander import AITradingCommander
            existing_commander = getattr(self, '_active_commander', None)
            if existing_commander is not None:
                result = await existing_commander.analyze_and_decide(user_request)
            else:
                commander = AITradingCommander()
                await commander.initialize()
                self._active_commander = commander
                result = await commander.analyze_and_decide(user_request)
            if result is None:
                error_msg = "[MasterScheduler] commander returned None"
                logger.error(error_msg)
                return MasterSchedulerResult(success=False, error=error_msg)
            return MasterSchedulerResult(success=True, final_answer=str(result),
                                          dispatch_type=DispatchType.COMMANDER)
        except ImportError as e:
            error_msg = f"[MasterScheduler] commander module unavailable: {e}"
            logger.error(error_msg)
            return MasterSchedulerResult(success=False, error=error_msg)
        except Exception as e:
            logger.error("[MasterScheduler] commander exception: %s", e, exc_info=True)
            raise MasterSchedulerError(f"commander failed: {e}") from e

    async def _schedule_long_task(self, user_request, task, session_id, voice_instance, mode, user_id, db_session_id):
        try:
            from core.task.long_task_slots import LongTaskSlots
            slots = LongTaskSlots()
            slot_id = None
            for sid in [1, 2, 3]:
                st = slots.get_slot_status(sid)
                if st and st.get("status") == "idle":
                    slot_id = sid
                    break
            if slot_id is None:
                error_msg = "[MasterScheduler] long task slots full (3/3)"
                logger.error(error_msg)
                return MasterSchedulerResult(success=False, error=error_msg)
            tid = task.id if task else "new"
            logger.info("[MasterScheduler] creating long task slot=%s task_id=%s resume_from_checkpoint=True",
                        slot_id, tid)
            created_task_id = slots.create_task(
                slot_id=slot_id,
                task_config={
                    "task_name": user_request[:50],
                    "task_type": "long_task",
                    "task": task, "session_id": session_id,
                    "db_session_id": db_session_id,
                    "voice_instance": voice_instance, "mode": mode,
                    "user_id": user_id,
                    "resume_from_checkpoint": True,
                    "task_id": task.id if task else None
                }
            )
            if not created_task_id:
                error_msg = f"[MasterScheduler] slot {slot_id} task creation failed (returned empty task_id)"
                logger.error(error_msg)
                return MasterSchedulerResult(success=False, error=error_msg)
            return MasterSchedulerResult(
                success=True,
                final_answer=f"Long task created in slot #{slot_id}. Runs in background with checkpoint resume.",
                dispatch_type=DispatchType.LONG_TASK
            )
        except Exception as e:
            logger.error("[MasterScheduler] long task scheduling exception: %s", e, exc_info=True)
            raise MasterSchedulerError(f"long task scheduling failed: {e}") from e


master_scheduler = MasterScheduler()
