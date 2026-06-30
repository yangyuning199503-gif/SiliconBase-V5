#!/usr/bin/env python3
"""
自适应执行器 (Adaptive Executor)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

执行学习到的操作流程，支持暂停、恢复和用户干预。

功能：
1. 执行流程步骤
2. 监控执行状态
3. 支持用户暂停和干预
4. 记录执行结果用于优化
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .procedure_library import Procedure, ProcedureStep


class ExecutionStatus(Enum):
    """执行状态"""
    IDLE = "idle"                    # 空闲
    RUNNING = "running"              # 执行中
    PAUSED = "paused"                # 已暂停（用户干预）
    WAITING_USER = "waiting_user"    # 等待用户输入
    COMPLETED = "completed"          # 完成
    FAILED = "failed"                # 失败
    INTERRUPTED = "interrupted"      # 被中断


@dataclass
class StepExecutionResult:
    """步骤执行结果"""
    step_id: str
    step_number: int
    success: bool
    start_time: float
    end_time: float
    output: Any = None
    error: str | None = None
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    user_intervened: bool = False
    intervention_reason: str | None = None


@dataclass
class ExecutionContext:
    """执行上下文"""
    procedure: Procedure
    parameters: dict[str, Any] = field(default_factory=dict)
    current_step_index: int = 0
    results: list[StepExecutionResult] = field(default_factory=list)
    start_time: float | None = None
    end_time: float | None = None
    status: ExecutionStatus = ExecutionStatus.IDLE
    user_message: str | None = None  # 用户干预时的消息


class AdaptiveExecutor:
    """
    自适应执行器

    执行流程，支持暂停、恢复和用户干预。
    """

    def __init__(self):
        self._context: ExecutionContext | None = None
        self._status = ExecutionStatus.IDLE
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()

        # 回调函数
        self._on_step_start: Callable[[ProcedureStep], None] | None = None
        self._on_step_complete: Callable[[StepExecutionResult], None] | None = None
        self._on_pause: Callable[[str], None] | None = None  # 暂停原因
        self._on_resume: Callable[[], None] | None = None
        self._on_complete: Callable[[ExecutionContext], None] | None = None
        self._on_failed: Callable[[str], None] | None = None
        self._on_waiting_user: Callable[[str], None] | None = None  # 等待用户输入

        # 工具执行器映射
        self._tool_executors: dict[str, Callable] = {}

    def register_callbacks(
        self,
        on_step_start: Callable[[ProcedureStep], None] | None = None,
        on_step_complete: Callable[[StepExecutionResult], None] | None = None,
        on_pause: Callable[[str], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_complete: Callable[[ExecutionContext], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
        on_waiting_user: Callable[[str], None] | None = None
    ):
        """注册回调函数"""
        self._on_step_start = on_step_start
        self._on_step_complete = on_step_complete
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_complete = on_complete
        self._on_failed = on_failed
        self._on_waiting_user = on_waiting_user

    def register_tool_executor(self, tool_name: str, executor: Callable):
        """注册工具执行器"""
        self._tool_executors[tool_name] = executor

    def execute(
        self,
        procedure: Procedure,
        parameters: dict[str, Any] | None = None,
        start_from_step: int = 0
    ) -> ExecutionContext:
        """
        执行流程

        Args:
            procedure: 要执行的流程
            parameters: 运行时参数
            start_from_step: 从第几步开始（用于恢复）

        Returns:
            执行上下文
        """
        # 填充参数
        filled_procedure = procedure.fill_parameters(**(parameters or {}))

        # 创建上下文
        self._context = ExecutionContext(
            procedure=filled_procedure,
            parameters=parameters or {},
            current_step_index=start_from_step,
            start_time=time.time(),
            status=ExecutionStatus.RUNNING
        )

        self._status = ExecutionStatus.RUNNING
        self._pause_event.clear()
        self._stop_event.clear()

        try:
            steps = filled_procedure.steps[start_from_step:]

            for i, step in enumerate(steps):
                # 检查暂停
                if self._pause_event.is_set():
                    self._status = ExecutionStatus.PAUSED
                    if self._on_pause:
                        self._on_pause(self._context.user_message or "用户暂停")
                    # 等待恢复
                    self._wait_for_resume()

                # 检查停止
                if self._stop_event.is_set():
                    self._status = ExecutionStatus.INTERRUPTED
                    break

                # 执行步骤
                self._context.current_step_index = start_from_step + i
                result = self._execute_step(step)
                self._context.results.append(result)

                if not result.success:
                    # 步骤失败，尝试回退
                    if step.fallback_step:
                        # TODO: 实现回退逻辑
                        pass
                    else:
                        # 没有回退，标记失败
                        self._status = ExecutionStatus.FAILED
                        if self._on_failed:
                            self._on_failed(result.error or "步骤执行失败")
                        break

            # 更新状态
            if self._status == ExecutionStatus.RUNNING:
                self._status = ExecutionStatus.COMPLETED

            self._context.end_time = time.time()
            self._context.status = self._status

            # 记录执行结果
            if self._status == ExecutionStatus.COMPLETED:
                procedure.record_execution(
                    success=True,
                    execution_time=self._context.end_time - self._context.start_time
                )
                if self._on_complete:
                    self._on_complete(self._context)

            return self._context

        except Exception as e:
            self._status = ExecutionStatus.FAILED
            self._context.end_time = time.time()
            self._context.status = self._status
            if self._on_failed:
                self._on_failed(str(e))
            return self._context

    def _execute_step(self, step: ProcedureStep) -> StepExecutionResult:
        """执行单个步骤"""
        start_time = time.time()

        if self._on_step_start:
            self._on_step_start(step)

        # 获取工具执行器
        executor = self._tool_executors.get(step.tool_name)
        if not executor:
            return StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                success=False,
                start_time=start_time,
                end_time=time.time(),
                error=f"未知的工具: {step.tool_name}"
            )

        # 执行工具
        try:
            output = executor(**step.tool_params)

            result = StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                success=True,
                start_time=start_time,
                end_time=time.time(),
                output=output
            )

            if self._on_step_complete:
                self._on_step_complete(result)

            return result

        except Exception as e:
            result = StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                success=False,
                start_time=start_time,
                end_time=time.time(),
                error=str(e)
            )

            if self._on_step_complete:
                self._on_step_complete(result)

            return result

    def _wait_for_resume(self):
        """等待恢复信号"""
        while self._pause_event.is_set() and not self._stop_event.is_set():
            time.sleep(0.1)

        if not self._stop_event.is_set():
            self._status = ExecutionStatus.RUNNING
            if self._on_resume:
                self._on_resume()

    def pause(self, message: str | None = None):
        """暂停执行"""
        self._pause_event.set()
        if self._context:
            self._context.user_message = message
            self._context.status = ExecutionStatus.PAUSED

    def resume(self):
        """恢复执行"""
        self._pause_event.clear()

    def stop(self):
        """停止执行"""
        self._stop_event.set()

    def request_user_input(self, prompt: str) -> str | None:
        """
        请求用户输入

        Args:
            prompt: 提示信息

        Returns:
            用户输入（如果用户取消则返回None）
        """
        self._status = ExecutionStatus.WAITING_USER
        self._context.status = ExecutionStatus.WAITING_USER

        if self._on_waiting_user:
            self._on_waiting_user(prompt)

        # 暂停等待用户输入
        self._pause_event.set()

        # TODO: 实现用户输入接收机制
        # 这需要与前端交互，暂时返回None
        return None

    def get_progress(self) -> dict[str, Any]:
        """获取执行进度"""
        if not self._context:
            return {"status": "idle", "progress": 0}

        total_steps = len(self._context.procedure.steps)
        current_step = self._context.current_step_index

        progress = (current_step / total_steps * 100) if total_steps > 0 else 0

        return {
            "status": self._status.value,
            "progress": round(progress, 1),
            "current_step": current_step,
            "total_steps": total_steps,
            "current_step_description": (
                self._context.procedure.steps[current_step].description
                if current_step < total_steps else "完成"
            )
        }

    def get_execution_report(self) -> dict[str, Any]:
        """生成执行报告"""
        if not self._context:
            return {}

        ctx = self._context

        return {
            "procedure_name": ctx.procedure.name,
            "status": ctx.status.value,
            "start_time": datetime.fromtimestamp(ctx.start_time).isoformat() if ctx.start_time else None,
            "end_time": datetime.fromtimestamp(ctx.end_time).isoformat() if ctx.end_time else None,
            "duration": ctx.end_time - ctx.start_time if ctx.end_time and ctx.start_time else None,
            "total_steps": len(ctx.procedure.steps),
            "completed_steps": len([r for r in ctx.results if r.success]),
            "failed_steps": len([r for r in ctx.results if not r.success]),
            "step_results": [
                {
                    "step_number": r.step_number,
                    "success": r.success,
                    "duration": r.end_time - r.start_time,
                    "error": r.error
                }
                for r in ctx.results
            ]
        }


# 全局实例
_executor_instance: AdaptiveExecutor | None = None

def get_adaptive_executor() -> AdaptiveExecutor:
    """获取全局自适应执行器实例"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = AdaptiveExecutor()
    return _executor_instance
