#!/usr/bin/env python3
"""
WorkflowExecutor - 工作流执行器 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
协调 WorkflowEngine 和 AgentLoop 之间的执行

【核心特性】
1. 连接工作流引擎与 AgentLoop
2. 执行单个步骤和完整工作流
3. 处理步骤间的数据传递（变量解析）
4. 与 CheckpointManager 集成（保存步骤结果）
5. 支持感知融合和结果验证

【架构位置】
- 位于: core/workflow/workflow_executor.py
- 调用方: AgentLoop（工作流模式）、LongTaskSlots
- 依赖: WorkflowEngine、PerceptionFusion、CheckpointManager、ToolManager
"""

import asyncio
import contextlib
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any

# 导入项目组件
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('workflow_executor')

# 导入工作流引擎
try:
    from .workflow_engine import (
        ExecutionStatus,
        StepStatus,
        VariableResolver,
        WorkflowEngine,
        get_workflow_engine,
    )
    WORKFLOW_ENGINE_AVAILABLE = True
except ImportError as e:
    WORKFLOW_ENGINE_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] WorkflowEngine 导入失败: {e}")

# 导入感知融合
try:
    from .perception_fusion import (
        ExpectedOutcome,
        get_perception_fusion,
    )
    PERCEPTION_FUSION_AVAILABLE = True
except ImportError as e:
    PERCEPTION_FUSION_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] PerceptionFusion 导入失败: {e}")

# 导入状态机
try:
    from .state_machine import StateEvent, create_state_machine
    STATE_MACHINE_AVAILABLE = True
except ImportError as e:
    STATE_MACHINE_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] WorkflowStateMachine 导入失败: {e}")

# 导入事件类
try:
    from .events import (
        StepCompleted,
        StepFailed,
        StepStarted,
        WorkflowCompleted,
        WorkflowFailed,
        WorkflowPaused,
        WorkflowResumed,
        WorkflowStarted,
        get_event_bus,
    )
    EVENTS_AVAILABLE = True
except ImportError as e:
    EVENTS_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] Events 导入失败: {e}")

# 导入子代理步骤执行器
try:
    from .subagent_step import SubAgentStepExecutor
    SUBAGENT_STEP_AVAILABLE = True
except ImportError as e:
    SUBAGENT_STEP_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] SubAgentStepExecutor 导入失败: {e}")

# 【修复断点2】导入检查点记忆桥接器
try:
    from core.memory.checkpoint_memory_bridge import (
        CheckpointMemoryBridge,
        get_checkpoint_memory_bridge,
    )
    CHECKPOINT_MEMORY_BRIDGE_AVAILABLE = True
except ImportError as e:
    CHECKPOINT_MEMORY_BRIDGE_AVAILABLE = False
    logger.warning(f"[WorkflowExecutor] CheckpointMemoryBridge 导入失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 进度推送配置
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProgressPushConfig:
    """进度推送配置"""
    enabled: bool = True              # 启用实时进度推送
    throttle_interval_ms: float = 500  # 节流间隔（毫秒）
    min_progress_delta: float = 5.0    # 最小进度变化百分比（%）
    enable_websocket: bool = True      # 启用WebSocket推送
    enable_event_bus: bool = True      # 启用事件总线推送

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "throttle_interval_ms": self.throttle_interval_ms,
            "min_progress_delta": self.min_progress_delta,
            "enable_websocket": self.enable_websocket,
            "enable_event_bus": self.enable_event_bus
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 工作流进度广播器
# ═══════════════════════════════════════════════════════════════════════════════

class WorkflowProgressBroadcaster:
    """
    工作流进度广播器 - 负责实时进度推送

    【核心功能】
    1. 节流控制：按时间间隔（默认500ms）或进度变化（>5%）触发推送
    2. 多渠道推送：支持事件总线和WebSocket
    3. 进度计算：计算整体进度和当前步骤进度

    【推送类型】
    - step_started: 步骤开始
    - step_progress: 步骤执行中进度
    - step_completed: 步骤完成
    - step_failed: 步骤失败
    """

    def __init__(self, config: ProgressPushConfig | None = None):
        self.config = config or ProgressPushConfig()

        # 推送状态跟踪
        self._last_push_time: dict[str, float] = {}  # execution_id -> last_push_time
        self._last_progress: dict[str, float] = {}   # execution_id -> last_progress_percent
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

        # WebSocket管理器（延迟加载）
        self._ws_manager: Any | None = None

        logger.info("[WorkflowProgressBroadcaster] 进度广播器初始化完成")

    def _get_ws_manager(self) -> Any | None:
        """延迟加载WebSocket管理器（统一走 FastAPI ConnectionManager）"""
        if self._ws_manager is None and self.config.enable_websocket:
            try:
                from api.cloud_api import ConnectionManager
                _manager = ConnectionManager()

                class _WSManagerCompat:
                    """兼容层：适配旧版 ws_manager API"""

                    async def broadcast_to_user(self, user_id: str, message: dict):
                        await _manager.send_to_user(user_id, message)

                    def broadcast_sync(self, user_id: str, message: dict):
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(_manager.send_to_user(user_id, message))
                            else:
                                loop.run_until_complete(_manager.send_to_user(user_id, message))
                        except Exception:
                            pass

                self._ws_manager = _WSManagerCompat()
                logger.debug("[WorkflowProgressBroadcaster] WebSocket管理器加载成功")
            except ImportError:
                logger.debug("[WorkflowProgressBroadcaster] WebSocket管理器不可用")
        return self._ws_manager

    def _should_push(self, execution_id: str, current_progress: float) -> bool:
        """
        检查是否应该推送进度（节流控制）

        Args:
            execution_id: 执行实例ID
            current_progress: 当前进度（0-100）

        Returns:
            bool: 是否应该推送
        """
        if not self.config.enabled:
            return False

        with self._lock:
            now = time.time()
            last_time = self._last_push_time.get(execution_id, 0)
            last_progress = self._last_progress.get(execution_id, 0)

            # 检查时间间隔（转换为秒）
            time_elapsed_ms = (now - last_time) * 1000
            if time_elapsed_ms >= self.config.throttle_interval_ms:
                return True

            # 检查进度变化
            progress_delta = abs(current_progress - last_progress)
            return progress_delta >= self.config.min_progress_delta

    async def _should_push_async(self, execution_id: str, current_progress: float) -> bool:
        """【Phase 7.5】异步版本：检查是否应该推送进度（节流控制）"""
        if not self.config.enabled:
            return False

        async with self._async_lock:
            now = time.time()
            last_time = self._last_push_time.get(execution_id, 0)
            last_progress = self._last_progress.get(execution_id, 0)

            time_elapsed_ms = (now - last_time) * 1000
            if time_elapsed_ms >= self.config.throttle_interval_ms:
                return True

            progress_delta = abs(current_progress - last_progress)
            return progress_delta >= self.config.min_progress_delta

    def _update_push_state(self, execution_id: str, progress: float):
        """更新推送状态"""
        with self._lock:
            self._last_push_time[execution_id] = time.time()
            self._last_progress[execution_id] = progress

    async def _update_push_state_async(self, execution_id: str, progress: float):
        """【Phase 7.5】异步版本：更新推送状态"""
        async with self._async_lock:
            self._last_push_time[execution_id] = time.time()
            self._last_progress[execution_id] = progress

    def _calculate_overall_progress(self, step_index: int, total_steps: int,
                                    step_progress: float = 0.0) -> float:
        """
        计算整体进度

        Args:
            step_index: 当前步骤索引（从0开始）
            total_steps: 总步骤数
            step_progress: 当前步骤进度（0-100）

        Returns:
            float: 整体进度（0-100）
        """
        if total_steps <= 0:
            return 0.0

        # 已完成步骤的贡献 + 当前步骤的贡献
        completed_contribution = (step_index / total_steps) * 100
        current_contribution = (step_progress / 100) * (100 / total_steps)

        return min(100.0, completed_contribution + current_contribution)

    def broadcast(self, execution_id: str, step_id: str, step_name: str,
                  step_index: int, total_steps: int,
                  step_progress: float = 0.0, status: str = "running",
                  message: str = "", workflow_id: str | None = None,
                  user_id: str = "default", force: bool = False) -> bool:
        """
        广播进度更新

        Args:
            execution_id: 执行实例ID
            step_id: 步骤ID
            step_name: 步骤名称
            step_index: 当前步骤索引
            total_steps: 总步骤数
            step_progress: 当前步骤进度（0-100）
            status: 状态（running/completed/failed/paused）
            message: 进度消息
            workflow_id: 工作流ID
            user_id: 用户ID
            force: 强制推送（忽略节流控制）

        Returns:
            bool: 是否成功推送
        """
        if not self.config.enabled:
            return False

        # 计算整体进度
        overall_progress = self._calculate_overall_progress(
            step_index, total_steps, step_progress
        )

        # 检查是否应该推送（如果不是强制推送）
        if not force and not self._should_push(execution_id, overall_progress):
            return False

        try:
            # 更新推送状态
            self._update_push_state(execution_id, overall_progress)

            # 构建进度数据
            progress_data = {
                "execution_id": execution_id,
                "workflow_id": workflow_id or "",
                "current_step": step_index + 1,  # 转为1-based
                "total_steps": total_steps,
                "step_id": step_id,
                "step_name": step_name,
                "progress_percent": round(step_progress, 2),
                "overall_percent": round(overall_progress, 2),
                "status": status,
                "message": message,
                "timestamp": time.time()
            }

            # 1. 通过事件总线推送
            if self.config.enable_event_bus and EVENTS_AVAILABLE:
                self._push_via_event_bus(
                    execution_id, step_id, step_name,
                    step_index, total_steps, step_progress,
                    overall_progress, status, message,
                    workflow_id, user_id
                )

            # 2. 通过WebSocket推送
            if self.config.enable_websocket:
                self._push_via_websocket(execution_id, progress_data, user_id)

            logger.debug(f"[WorkflowProgressBroadcaster] 进度推送: {execution_id} "
                        f"步骤 {step_index + 1}/{total_steps} ({step_progress:.1f}%)")
            return True

        except Exception as e:
            logger.warning(f"[WorkflowProgressBroadcaster] 进度推送失败: {e}")
            return False

    async def broadcast_async(self, execution_id: str, step_id: str, step_name: str,
                              step_index: int, total_steps: int,
                              step_progress: float = 0.0, status: str = "running",
                              message: str = "", workflow_id: str | None = None,
                              user_id: str = "default", force: bool = False) -> bool:
        """【Phase 7.5】异步版本：广播进度更新"""
        if not self.config.enabled:
            return False

        overall_progress = self._calculate_overall_progress(
            step_index, total_steps, step_progress
        )

        if not force and not await self._should_push_async(execution_id, overall_progress):
            return False

        try:
            await self._update_push_state_async(execution_id, overall_progress)

            progress_data = {
                "execution_id": execution_id,
                "workflow_id": workflow_id or "",
                "current_step": step_index + 1,
                "total_steps": total_steps,
                "step_id": step_id,
                "step_name": step_name,
                "progress_percent": round(step_progress, 2),
                "overall_percent": round(overall_progress, 2),
                "status": status,
                "message": message,
                "timestamp": time.time()
            }

            if self.config.enable_event_bus and EVENTS_AVAILABLE:
                self._push_via_event_bus(
                    execution_id, step_id, step_name,
                    step_index, total_steps, step_progress,
                    overall_progress, status, message,
                    workflow_id, user_id
                )

            if self.config.enable_websocket:
                await self._push_via_websocket_async(execution_id, progress_data, user_id)

            logger.debug(f"[WorkflowProgressBroadcaster] 进度推送: {execution_id} "
                        f"步骤 {step_index + 1}/{total_steps} ({step_progress:.1f}%)")
            return True

        except Exception as e:
            logger.warning(f"[WorkflowProgressBroadcaster] 进度推送失败: {e}")
            return False

    def _push_via_event_bus(self, execution_id: str, step_id: str, step_name: str,
                            step_index: int, total_steps: int,
                            step_progress: float, overall_progress: float,
                            status: str, message: str,
                            workflow_id: str | None, user_id: str):
        """通过事件总线推送进度"""
        try:
            from .events import StepProgress, get_event_bus

            event = StepProgress(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step_name,
                step_index=step_index,
                total_steps=total_steps,
                progress_percent=round(step_progress, 2),
                overall_percent=round(overall_progress, 2),
                status=status,
                message=message,
                workflow_id=workflow_id,
                user_id=user_id
            )
            get_event_bus().publish(event)

        except Exception as e:
            logger.debug(f"[WorkflowProgressBroadcaster] 事件总线推送失败: {e}")

    def _push_via_websocket(self, execution_id: str, progress_data: dict[str, Any],
                            user_id: str):
        """通过WebSocket推送进度"""
        try:
            ws_manager = self._get_ws_manager()
            if not ws_manager:
                return

            # 构建WebSocket消息
            ws_message = {
                "type": "workflow_progress",
                "data": progress_data
            }

            # 广播到用户频道
            try:
                import asyncio
                try:
                    # 已有事件循环，创建任务异步发送（不等待）
                    asyncio.create_task(
                        ws_manager.broadcast_to_user(user_id, ws_message)
                    )
                except RuntimeError:
                    # 无运行中的事件循环，安全使用 asyncio.run
                    asyncio.run(
                        ws_manager.broadcast_to_user(user_id, ws_message)
                    )
            except Exception as e:
                # 降级：尝试同步方式（如果可用）
                logger.debug(f"[WorkflowProgressBroadcaster] 异步发送失败，尝试同步方式: {e}")
                try:
                    if hasattr(ws_manager, 'broadcast_sync'):
                        ws_manager.broadcast_sync(user_id, ws_message)
                except Exception as e2:
                    logger.debug(f"[WorkflowProgressBroadcaster] 同步发送也失败: {e2}")

        except Exception as e:
            logger.debug(f"[WorkflowProgressBroadcaster] WebSocket推送失败: {e}")

    async def _push_via_websocket_async(self, execution_id: str, progress_data: dict[str, Any],
                                        user_id: str):
        """【Phase 7.5】异步版本：通过WebSocket推送进度"""
        try:
            ws_manager = self._get_ws_manager()
            if not ws_manager:
                return

            ws_message = {
                "type": "workflow_progress",
                "data": progress_data
            }

            if hasattr(ws_manager, 'broadcast_to_user'):
                await ws_manager.broadcast_to_user(user_id, ws_message)

        except Exception as e:
            logger.debug(f"[WorkflowProgressBroadcaster] WebSocket推送失败: {e}")

    def broadcast_step_started(self, execution_id: str, step_id: str,
                               step_name: str, step_index: int, total_steps: int,
                               workflow_id: str | None = None,
                               user_id: str = "default") -> bool:
        """
        广播步骤开始事件

        Args:
            execution_id: 执行实例ID
            step_id: 步骤ID
            step_name: 步骤名称
            step_index: 步骤索引
            total_steps: 总步骤数
            workflow_id: 工作流ID
            user_id: 用户ID

        Returns:
            bool: 是否成功推送
        """
        return self.broadcast(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=0.0,
            status="running",
            message=f"开始执行步骤: {step_name}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True  # 步骤开始强制推送
        )

    async def broadcast_step_started_async(self, execution_id: str, step_id: str,
                                           step_name: str, step_index: int, total_steps: int,
                                           workflow_id: str | None = None,
                                           user_id: str = "default") -> bool:
        """【Phase 7.5】异步版本：广播步骤开始事件"""
        return await self.broadcast_async(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=0.0,
            status="running",
            message=f"开始执行步骤: {step_name}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True
        )

    def broadcast_step_completed(self, execution_id: str, step_id: str,
                                 step_name: str, step_index: int, total_steps: int,
                                 workflow_id: str | None = None,
                                 user_id: str = "default") -> bool:
        """
        广播步骤完成事件

        Args:
            execution_id: 执行实例ID
            step_id: 步骤ID
            step_name: 步骤名称
            step_index: 步骤索引
            total_steps: 总步骤数
            workflow_id: 工作流ID
            user_id: 用户ID

        Returns:
            bool: 是否成功推送
        """
        return self.broadcast(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=100.0,
            status="completed",
            message=f"步骤完成: {step_name}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True  # 步骤完成强制推送
        )

    async def broadcast_step_completed_async(self, execution_id: str, step_id: str,
                                             step_name: str, step_index: int, total_steps: int,
                                             workflow_id: str | None = None,
                                             user_id: str = "default") -> bool:
        """【Phase 7.5】异步版本：广播步骤完成事件"""
        return await self.broadcast_async(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=100.0,
            status="completed",
            message=f"步骤完成: {step_name}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True
        )

    def broadcast_step_failed(self, execution_id: str, step_id: str,
                              step_name: str, step_index: int, total_steps: int,
                              error: str, workflow_id: str | None = None,
                              user_id: str = "default") -> bool:
        """
        广播步骤失败事件

        Args:
            execution_id: 执行实例ID
            step_id: 步骤ID
            step_name: 步骤名称
            step_index: 步骤索引
            total_steps: 总步骤数
            error: 错误信息
            workflow_id: 工作流ID
            user_id: 用户ID

        Returns:
            bool: 是否成功推送
        """
        return self.broadcast(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=0.0,
            status="failed",
            message=f"步骤失败: {error}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True  # 步骤失败强制推送
        )

    async def broadcast_step_failed_async(self, execution_id: str, step_id: str,
                                          step_name: str, step_index: int, total_steps: int,
                                          error: str, workflow_id: str | None = None,
                                          user_id: str = "default") -> bool:
        """【Phase 7.5】异步版本：广播步骤失败事件"""
        return await self.broadcast_async(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step_name,
            step_index=step_index,
            total_steps=total_steps,
            step_progress=0.0,
            status="failed",
            message=f"步骤失败: {error}",
            workflow_id=workflow_id,
            user_id=user_id,
            force=True
        )

    def cleanup(self, execution_id: str):
        """
        清理执行实例的推送状态

        Args:
            execution_id: 执行实例ID
        """
        with self._lock:
            self._last_push_time.pop(execution_id, None)
            self._last_progress.pop(execution_id, None)

    async def cleanup_async(self, execution_id: str):
        """【Phase 7.5】异步版本：清理执行实例的推送状态"""
        async with self._async_lock:
            self._last_push_time.pop(execution_id, None)
            self._last_progress.pop(execution_id, None)


# ═══════════════════════════════════════════════════════════════════════════════
# 执行配置
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionConfig:
    """执行配置"""
    enable_perception: bool = True           # 启用感知
    enable_verification: bool = True         # 启用结果验证
    save_checkpoints: bool = True            # 保存检查点
    max_retries_per_step: int = 3            # 每步最大重试次数
    step_timeout: int = 60                   # 步骤超时（秒）
    on_step_error: str = "pause"             # 步骤错误处理: pause/skip/continue

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_perception": self.enable_perception,
            "enable_verification": self.enable_verification,
            "save_checkpoints": self.save_checkpoints,
            "max_retries_per_step": self.max_retries_per_step,
            "step_timeout": self.step_timeout,
            "on_step_error": self.on_step_error
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 执行结果
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepExecutionResult:
    """步骤执行结果"""
    step_id: str
    success: bool
    result: Any = None
    error: str = ""
    execution_time: float = 0.0
    perception_context: Any | None = None
    verification_result: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "perception_context": self.perception_context.to_dict() if self.perception_context else None,
            "verification_result": self.verification_result.to_dict() if self.verification_result else None
        }


@dataclass
class WorkflowExecutionResult:
    """工作流执行结果"""
    execution_id: str
    workflow_id: str
    success: bool
    status: str
    step_results: list[StepExecutionResult] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    total_execution_time: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "success": self.success,
            "status": self.status,
            "step_results": [r.to_dict() for r in self.step_results],
            "variables": self.variables,
            "error": self.error,
            "total_execution_time": self.total_execution_time,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 工作流执行器主类
# ═══════════════════════════════════════════════════════════════════════════════

class WorkflowExecutor:
    """工作流执行器 - 连接 WorkflowEngine 和 AgentLoop"""

    def __init__(self, config: ExecutionConfig | None = None,
                 progress_config: ProgressPushConfig | None = None):
        """
        初始化工作流执行器

        Args:
            config: 执行配置，如果为None则使用默认配置
            progress_config: 进度推送配置，如果为None则使用默认配置
        """
        self.config = config or ExecutionConfig()

        # 【新增】进度广播器
        self._progress_broadcaster = WorkflowProgressBroadcaster(progress_config)

        # 延迟加载的依赖
        self._workflow_engine: WorkflowEngine | None = None
        self._perception_fusion: Any | None = None
        self._tool_manager: Any | None = None
        self._checkpoint_manager: Any | None = None
        self._subagent_manager: Any | None = None

        # 子代理步骤执行器
        self._subagent_executor: SubAgentStepExecutor | None = None

        # 【修复断点2】检查点记忆桥接器
        self._checkpoint_memory_bridge: CheckpointMemoryBridge | None = None

        # 状态机映射（execution_id -> state_machine）
        self._state_machines: dict[str, Any] = {}

        # 锁
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

        # BUG-1修复: 在__init__中创建ProcessPoolExecutor，避免重复创建
        self._timeout_executor = ProcessPoolExecutor(max_workers=1)

        logger.info("[WorkflowExecutor] 工作流执行器初始化完成")

    def _get_subagent_manager(self) -> Any | None:
        """延迟加载 SubAgentManager"""
        if self._subagent_manager is None:
            try:
                from core.subagent.manager import subagent_manager
                self._subagent_manager = subagent_manager
            except ImportError:
                logger.warning("[WorkflowExecutor] SubAgentManager 不可用")
        return self._subagent_manager

    def _get_subagent_executor(self) -> SubAgentStepExecutor | None:
        """获取或创建子代理步骤执行器"""
        if self._subagent_executor is None and SUBAGENT_STEP_AVAILABLE:
            try:
                subagent_manager = self._get_subagent_manager()
                self._subagent_executor = SubAgentStepExecutor(
                    subagent_manager=subagent_manager
                )
            except Exception as e:
                logger.error(f"[WorkflowExecutor] SubAgentStepExecutor 初始化失败: {e}")
        return self._subagent_executor

    def _get_workflow_engine(self) -> WorkflowEngine | None:
        """延迟加载 WorkflowEngine"""
        if self._workflow_engine is None and WORKFLOW_ENGINE_AVAILABLE:
            try:
                self._workflow_engine = get_workflow_engine()
            except Exception as e:
                logger.error(f"[WorkflowExecutor] WorkflowEngine 加载失败: {e}")
        return self._workflow_engine

    def _get_perception_fusion(self) -> Any | None:
        """延迟加载 PerceptionFusion"""
        if self._perception_fusion is None and PERCEPTION_FUSION_AVAILABLE:
            try:
                self._perception_fusion = get_perception_fusion()
            except Exception as e:
                logger.error(f"[WorkflowExecutor] PerceptionFusion 加载失败: {e}")
        return self._perception_fusion

    def _get_tool_manager(self) -> Any | None:
        """延迟加载 ToolManager"""
        if self._tool_manager is None:
            try:
                from core.tool.tool_manager import ToolManager
                self._tool_manager = ToolManager()
            except ImportError:
                logger.warning("[WorkflowExecutor] ToolManager 不可用")
        return self._tool_manager

    def _get_checkpoint_manager(self) -> Any | None:
        """延迟加载 CheckpointManager"""
        if self._checkpoint_manager is None:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                self._checkpoint_manager = checkpoint_manager
            except ImportError:
                logger.warning("[WorkflowExecutor] CheckpointManager 不可用")
        return self._checkpoint_manager

    def _get_checkpoint_memory_bridge(self) -> CheckpointMemoryBridge | None:
        """【修复断点2】延迟加载 CheckpointMemoryBridge"""
        if self._checkpoint_memory_bridge is None and CHECKPOINT_MEMORY_BRIDGE_AVAILABLE:
            try:
                self._checkpoint_memory_bridge = get_checkpoint_memory_bridge()
                if self._checkpoint_memory_bridge:
                    logger.info("[WorkflowExecutor] CheckpointMemoryBridge 加载成功")
            except Exception as e:
                logger.warning(f"[WorkflowExecutor] CheckpointMemoryBridge 加载失败: {e}")
        return self._checkpoint_memory_bridge

    def _get_or_create_state_machine(self, execution: Any) -> Any | None:
        """获取或创建工作流状态机"""
        if not STATE_MACHINE_AVAILABLE:
            return None

        execution_id = execution.execution_id
        if execution_id not in self._state_machines:
            try:
                state_machine = create_state_machine(execution_id, execution)
                self._state_machines[execution_id] = state_machine
                logger.debug(f"[WorkflowExecutor] 创建状态机: {execution_id}")
            except Exception as e:
                logger.error(f"[WorkflowExecutor] 状态机创建失败: {e}")
                return None

        return self._state_machines.get(execution_id)

    # ═══════════════════════════════════════════════════════════════════════════
    # 工作流执行主入口
    # ═══════════════════════════════════════════════════════════════════════════

    async def run_workflow_mode(self, execution_id: str,
                         user_id: str = "default",
                         voice_instance: Any | None = None,
                         chat_history: list[dict] | None = None,
                         **kwargs) -> dict[str, Any]:
        """
        工作流模式执行主入口

        这是连接 AgentLoop 的核心方法，执行完整的工作流。

        Args:
            execution_id: 执行实例ID
            user_id: 用户ID
            voice_instance: 语音实例（用于播报）
            chat_history: 聊天历史
            **kwargs: 额外参数

        Returns:
            Dict: 执行结果
        """
        start_time = time.time()

        # 获取执行实例
        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            error_msg = "WorkflowEngine 不可用"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        execution = workflow_engine.get_execution(execution_id)
        if not execution:
            error_msg = f"执行实例不存在: {execution_id}"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        # 【Phase 7.5】获取 slot_id（修复 NameError）
        slot_id = self._get_execution_slot_id(execution_id)

        if not execution.workflow:
            error_msg = "执行实例未关联工作流定义"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        # 获取或创建状态机
        state_machine = self._get_or_create_state_machine(execution)

        # 启动状态机
        if state_machine:
            try:
                state_machine.transition(StateEvent.start())
            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 状态机启动失败: {e}")

        # 发送工作流开始事件
        if EVENTS_AVAILABLE:
            try:
                event = WorkflowStarted(
                    execution_id=execution_id,
                    workflow_id=execution.workflow_id,
                    user_id=user_id,
                    step_count=len(execution.workflow.steps)
                )
                get_event_bus().publish(event)
                logger.info(f"[WorkflowExecutor] 工作流开始: {execution_id}")
            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 事件创建失败: {e}")

        # 初始化执行结果
        result = WorkflowExecutionResult(
            execution_id=execution_id,
            workflow_id=execution.workflow_id,
            success=False,
            status="running",
            started_at=start_time
        )

        try:
            # 更新执行状态
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = start_time

            # 遍历执行步骤
            steps = execution.workflow.steps
            total_steps = len(steps)

            for idx, step in enumerate(steps):
                # 检查是否暂停
                if execution.status == ExecutionStatus.PAUSED:
                    logger.info(f"[WorkflowExecutor] 执行暂停: {execution_id}")
                    result.status = "paused"

                    # 发送暂停事件
                    if EVENTS_AVAILABLE:
                        try:
                            event = WorkflowPaused(
                                execution_id=execution_id,
                                step_idx=idx,
                                reason="用户暂停"
                            )
                            get_event_bus().publish(event)
                        except Exception:
                            pass
                    break

                # 更新当前步骤索引
                execution.current_step_idx = idx

                # 播报步骤开始（如果有语音）
                if voice_instance and hasattr(voice_instance, 'speak'):
                    try:
                        from voice.voice_prompts import STEP_NAME_MAP, DialogueAnnouncements
                        step_display = step.description or STEP_NAME_MAP.get(step.name, "")
                        step_name_part = f"，{step_display}" if step_display else ""
                        voice_instance.speak(
                            DialogueAnnouncements.WORKFLOW_STEP.format(
                                step_num=idx + 1, total_steps=total_steps, step_name=step_name_part
                            ),
                            is_system=True, wait=False
                        )
                    except Exception as e:
                        logger.debug(f"[WorkflowExecutor] 语音播报失败: {e}")

                # 执行步骤
                step_result = await self.execute_step(
                    execution, step, voice_instance, slot_id, idx, total_steps
                )
                result.step_results.append(step_result)

                # 检查步骤结果
                if not step_result.success:
                    if step.is_critical:
                        # 关键步骤失败，终止执行
                        logger.error(f"[WorkflowExecutor] 关键步骤失败: {step.step_id}")
                        execution.status = ExecutionStatus.FAILED
                        result.status = "failed"
                        result.error = step_result.error

                        # 发送失败事件
                        if EVENTS_AVAILABLE:
                            try:
                                event = WorkflowFailed(
                                    execution_id=execution_id,
                                    step_id=step.step_id,
                                    error=step_result.error
                                )
                                get_event_bus().publish(event)
                            except Exception:
                                pass
                        break
                    else:
                        # 非关键步骤失败，根据配置处理
                        if self.config.on_step_error == "pause":
                            execution.status = ExecutionStatus.PAUSED
                            result.status = "paused"
                            logger.warning(f"[WorkflowExecutor] 非关键步骤失败，执行暂停: {step.step_id}")
                            break
                        elif self.config.on_step_error == "skip":
                            logger.info(f"[WorkflowExecutor] 跳过失败步骤: {step.step_id}")
                            continue
                        # on_step_error == "continue" 时继续执行

                # 更新进度
                execution.step_results[step.step_id] = step_result.result

            # 执行完成
            if execution.status != ExecutionStatus.FAILED and execution.status != ExecutionStatus.PAUSED:
                execution.status = ExecutionStatus.COMPLETED
                result.status = "completed"
                result.success = True

                # 发送完成事件
                if EVENTS_AVAILABLE:
                    try:
                        event = WorkflowCompleted(
                            execution_id=execution_id,
                            workflow_id=execution.workflow_id,
                            total_steps=total_steps,
                            execution_time=time.time() - start_time
                        )
                        get_event_bus().publish(event)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 执行异常: {e}", exc_info=True)
            execution.status = ExecutionStatus.FAILED
            result.status = "error"
            result.error = str(e)

            # 发送失败事件
            if EVENTS_AVAILABLE:
                try:
                    event = WorkflowFailed(
                        execution_id=execution_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

        finally:
            # 更新结果信息
            result.completed_at = time.time()
            result.total_execution_time = result.completed_at - start_time
            result.variables = dict(execution.variables)

            # 更新执行实例
            execution.completed_at = result.completed_at

            # 更新状态机
            if state_machine:
                try:
                    if result.success:
                        state_machine.transition(StateEvent.complete())
                    else:
                        state_machine.transition(StateEvent.error(result.error))
                except Exception as e:
                    logger.warning(f"[WorkflowExecutor] 状态机更新失败: {e}")

            # 【修复】清理进度广播器的缓存，避免内存泄漏
            if self._progress_broadcaster:
                try:
                    self._progress_broadcaster.cleanup(execution_id)
                    logger.debug(f"[WorkflowExecutor] 清理进度缓存: {execution_id}")
                except Exception as e:
                    logger.debug(f"[WorkflowExecutor] 清理进度缓存失败: {e}")

        logger.info(f"[WorkflowExecutor] 执行完成: {execution_id}, 状态: {result.status}")
        return result.to_dict()

    async def run_workflow_mode_async(self, execution_id: str,
                                      user_id: str = "default",
                                      voice_instance: Any | None = None,
                                      chat_history: list[dict] | None = None,
                                      **kwargs) -> dict[str, Any]:
        """
        【Phase 7.5】异步版本：工作流模式执行主入口

        这是连接 AgentLoop 的核心方法，执行完整的工作流。
        """
        start_time = time.time()

        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            error_msg = "WorkflowEngine 不可用"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        execution = workflow_engine.get_execution(execution_id)
        if not execution:
            error_msg = f"执行实例不存在: {execution_id}"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        slot_id = self._get_execution_slot_id(execution_id)

        if not execution.workflow:
            error_msg = "执行实例未关联工作流定义"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        state_machine = self._get_or_create_state_machine(execution)

        if state_machine:
            try:
                state_machine.transition(StateEvent.start())
            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 状态机启动失败: {e}")

        if EVENTS_AVAILABLE:
            try:
                event = WorkflowStarted(
                    execution_id=execution_id,
                    workflow_id=execution.workflow_id,
                    user_id=user_id,
                    step_count=len(execution.workflow.steps)
                )
                get_event_bus().publish(event)
                logger.info(f"[WorkflowExecutor] 工作流开始: {execution_id}")
            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 事件创建失败: {e}")

        result = WorkflowExecutionResult(
            execution_id=execution_id,
            workflow_id=execution.workflow_id,
            success=False,
            status="running",
            started_at=start_time
        )

        try:
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = start_time

            steps = execution.workflow.steps
            total_steps = len(steps)

            for idx, step in enumerate(steps):
                if execution.status == ExecutionStatus.PAUSED:
                    logger.info(f"[WorkflowExecutor] 执行暂停: {execution_id}")
                    result.status = "paused"

                    if EVENTS_AVAILABLE:
                        try:
                            event = WorkflowPaused(
                                execution_id=execution_id,
                                step_idx=idx,
                                reason="用户暂停"
                            )
                            get_event_bus().publish(event)
                        except Exception:
                            pass
                    break

                execution.current_step_idx = idx

                if voice_instance and hasattr(voice_instance, 'speak'):
                    try:
                        from voice.voice_prompts import STEP_NAME_MAP, DialogueAnnouncements
                        step_display = step.description or STEP_NAME_MAP.get(step.name, "")
                        step_name_part = f"，{step_display}" if step_display else ""
                        voice_instance.speak(
                            DialogueAnnouncements.WORKFLOW_STEP.format(
                                step_num=idx + 1, total_steps=total_steps, step_name=step_name_part
                            ),
                            is_system=True, wait=False
                        )
                    except Exception as e:
                        logger.debug(f"[WorkflowExecutor] 语音播报失败: {e}")

                step_result = await self.execute_step_async(
                    execution, step, voice_instance, slot_id, idx, total_steps
                )
                result.step_results.append(step_result)

                if not step_result.success:
                    if step.is_critical:
                        logger.error(f"[WorkflowExecutor] 关键步骤失败: {step.step_id}")
                        execution.status = ExecutionStatus.FAILED
                        result.status = "failed"
                        result.error = step_result.error

                        if EVENTS_AVAILABLE:
                            try:
                                event = WorkflowFailed(
                                    execution_id=execution_id,
                                    step_id=step.step_id,
                                    error=step_result.error
                                )
                                get_event_bus().publish(event)
                            except Exception:
                                pass
                        break
                    else:
                        if self.config.on_step_error == "pause":
                            execution.status = ExecutionStatus.PAUSED
                            result.status = "paused"
                            logger.warning(f"[WorkflowExecutor] 非关键步骤失败，执行暂停: {step.step_id}")
                            break
                        elif self.config.on_step_error == "skip":
                            logger.info(f"[WorkflowExecutor] 跳过失败步骤: {step.step_id}")
                            continue

                execution.step_results[step.step_id] = step_result.result

            if execution.status != ExecutionStatus.FAILED and execution.status != ExecutionStatus.PAUSED:
                execution.status = ExecutionStatus.COMPLETED
                result.status = "completed"
                result.success = True

                if EVENTS_AVAILABLE:
                    try:
                        event = WorkflowCompleted(
                            execution_id=execution_id,
                            workflow_id=execution.workflow_id,
                            total_steps=total_steps,
                            execution_time=time.time() - start_time
                        )
                        get_event_bus().publish(event)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 执行异常: {e}", exc_info=True)
            execution.status = ExecutionStatus.FAILED
            result.status = "error"
            result.error = str(e)

            if EVENTS_AVAILABLE:
                try:
                    event = WorkflowFailed(
                        execution_id=execution_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

        finally:
            result.completed_at = time.time()
            result.total_execution_time = result.completed_at - start_time
            result.variables = dict(execution.variables)

            execution.completed_at = result.completed_at

            if state_machine:
                try:
                    if result.success:
                        state_machine.transition(StateEvent.complete())
                    else:
                        state_machine.transition(StateEvent.error(result.error))
                except Exception as e:
                    logger.warning(f"[WorkflowExecutor] 状态机更新失败: {e}")

            if self._progress_broadcaster:
                try:
                    self._progress_broadcaster.cleanup(execution_id)
                    logger.debug(f"[WorkflowExecutor] 清理进度缓存: {execution_id}")
                except Exception as e:
                    logger.debug(f"[WorkflowExecutor] 清理进度缓存失败: {e}")

        logger.info(f"[WorkflowExecutor] 执行完成: {execution_id}, 状态: {result.status}")
        return result.to_dict()

    async def execute_step(self, execution: Any, step: Any,
                     voice_instance: Any | None = None,
                     slot_id: int | None = None,
                     step_index: int = 0,
                     total_steps: int = 1) -> StepExecutionResult:
        """
        执行单个步骤

        Args:
            execution: 工作流执行实例
            step: 工作流步骤
            voice_instance: 语音实例
            slot_id: 槽位ID，用于WebSocket广播
            step_index: 当前步骤索引
            total_steps: 总步骤数

        Returns:
            StepExecutionResult: 步骤执行结果
        """
        start_time = time.time()
        step_id = step.step_id
        execution_id = execution.execution_id
        workflow_id = getattr(execution, 'workflow_id', None)
        user_id = getattr(execution, 'user_id', 'default')  # 【修复】获取用户ID

        logger.info(f"[WorkflowExecutor] 执行步骤: {step_id} ({step.name})")

        # 【新增】检查是否为子代理步骤
        tool_params = getattr(step, 'tool_params', {}) or {}
        is_subagent_step = tool_params.get('agent_name') is not None or \
                          tool_params.get('use_subagent') is True

        if is_subagent_step and SUBAGENT_STEP_AVAILABLE:
            return await self._execute_subagent_step(
                execution, step, voice_instance, slot_id, step_index, total_steps
            )

        # 发送步骤开始事件
        if EVENTS_AVAILABLE:
            try:
                event = StepStarted(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_category=step.step_category,
                    step_index=step_index,
                    total_steps=total_steps
                )
                get_event_bus().publish(event)
            except Exception:
                pass

        # 【新增】广播步骤开始进度
        self._progress_broadcaster.broadcast_step_started(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step.name,
            step_index=step_index,
            total_steps=total_steps,
            workflow_id=workflow_id,
            user_id=user_id  # 【修复】传递用户ID
        )

        # 更新步骤状态
        step.status = StepStatus.RUNNING
        step.started_at = start_time

        result = StepExecutionResult(step_id=step_id, success=False)

        try:
            # ═══════════════════════════════════════════════════════════════════
            # 1. 解析输入参数（变量引用）
            # ═══════════════════════════════════════════════════════════════════
            resolved_params = self._resolve_step_inputs(execution, step)
            logger.debug(f"[WorkflowExecutor] 步骤 {step_id} 参数解析完成: {resolved_params}")

            # 【新增】广播参数解析进度（25%）
            self._progress_broadcaster.broadcast(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=25.0,
                status="running",
                message="参数解析完成",
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

            # ═══════════════════════════════════════════════════════════════════
            # 2. 执行前感知（可选）
            # ═══════════════════════════════════════════════════════════════════
            perception_ctx = None
            if self.config.enable_perception and PERCEPTION_FUSION_AVAILABLE:
                perception_ctx = await self._capture_pre_step_perception(step, execution)
                result.perception_context = perception_ctx

            # 【新增】广播感知完成进度（40%）
            self._progress_broadcaster.broadcast(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=40.0,
                status="running",
                message="执行前感知完成",
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

            # ═══════════════════════════════════════════════════════════════════
            # 3. 执行工具
            # ═══════════════════════════════════════════════════════════════════
            tool_result = self._execute_tool(step.tool_id, resolved_params, step.timeout)

            if not tool_result:
                raise RuntimeError("工具执行返回空结果")

            result.result = tool_result
            step.result = tool_result

            # 【新增】广播工具执行进度（70%）
            self._progress_broadcaster.broadcast(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=70.0,
                status="running",
                message="工具执行完成",
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

            # ═══════════════════════════════════════════════════════════════════
            # 4. 处理结果
            # ═══════════════════════════════════════════════════════════════════
            if tool_result.get("success"):
                step.status = StepStatus.COMPLETED
                result.success = True

                # 提取输出变量
                if WORKFLOW_ENGINE_AVAILABLE:
                    outputs = VariableResolver.extract_outputs(
                        tool_result, step.output_mapping, step_id
                    )
                    execution.variables.update(outputs)
                    execution.step_results[step_id] = tool_result

                    logger.debug(f"[WorkflowExecutor] 步骤 {step_id} 输出变量: {outputs}")
            else:
                step.status = StepStatus.FAILED
                step.error = tool_result.get("error", "未知错误")
                result.error = step.error
                result.success = False

                logger.warning(f"[WorkflowExecutor] 步骤 {step_id} 执行失败: {step.error}")

            # ═══════════════════════════════════════════════════════════════════
            # 5. 执行后验证（可选）
            # ═══════════════════════════════════════════════════════════════════
            if self.config.enable_verification and PERCEPTION_FUSION_AVAILABLE and step.step_category in ["launch", "save", "transform", "verify"]:
                verification = self._verify_step_result(step, tool_result, perception_ctx)
                result.verification_result = verification

                if verification and not verification.all_passed:
                    logger.warning(f"[WorkflowExecutor] 步骤 {step_id} 验证未通过")
                    if step.is_critical:
                        result.success = False
                        result.error = "执行结果验证未通过"

            # 【新增】广播验证完成进度（90%）
            self._progress_broadcaster.broadcast(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=90.0,
                status="running",
                message="结果验证完成",
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

            # ═══════════════════════════════════════════════════════════════════
            # 6. 保存检查点（【修复断点2】传入 slot_id 支持增强检查点）
            # ═══════════════════════════════════════════════════════════════════
            if self.config.save_checkpoints:
                self._save_checkpoint(execution, step_id, step.status.value, slot_id)

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 步骤 {step_id} 执行异常: {e}", exc_info=True)
            step.status = StepStatus.FAILED
            step.error = str(e)
            result.success = False
            result.error = str(e)

            # 发送步骤失败事件
            if EVENTS_AVAILABLE:
                try:
                    event = StepFailed(
                        execution_id=execution_id,
                        step_id=step_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            # 【新增】广播步骤失败
            self._progress_broadcaster.broadcast_step_failed(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                error=str(e),
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

        finally:
            step.completed_at = time.time()
            result.execution_time = step.completed_at - start_time

            # 发送步骤完成事件
            if EVENTS_AVAILABLE and result.success:
                try:
                    event = StepCompleted(
                        execution_id=execution_id,
                        step_id=step_id,
                        execution_time=result.execution_time
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            # 【新增】广播步骤完成
            if result.success:
                self._progress_broadcaster.broadcast_step_completed(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_index=step_index,
                    total_steps=total_steps,
                    workflow_id=workflow_id,
                    user_id=user_id  # 【修复】传递用户ID
                )

        return result

    async def execute_step_async(self, execution: Any, step: Any,
                                 voice_instance: Any | None = None,
                                 slot_id: int | None = None,
                                 step_index: int = 0,
                                 total_steps: int = 1) -> StepExecutionResult:
        """
        【Phase 7.5】异步版本：执行单个步骤
        """
        start_time = time.time()
        step_id = step.step_id
        execution_id = execution.execution_id
        workflow_id = getattr(execution, 'workflow_id', None)
        user_id = getattr(execution, 'user_id', 'default')

        logger.info(f"[WorkflowExecutor] 执行步骤: {step_id} ({step.name})")

        tool_params = getattr(step, 'tool_params', {}) or {}
        is_subagent_step = tool_params.get('agent_name') is not None or \
                          tool_params.get('use_subagent') is True

        if is_subagent_step and SUBAGENT_STEP_AVAILABLE:
            return await self._execute_subagent_step_async(
                execution, step, voice_instance, slot_id, step_index, total_steps
            )

        if EVENTS_AVAILABLE:
            try:
                event = StepStarted(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_category=step.step_category,
                    step_index=step_index,
                    total_steps=total_steps
                )
                get_event_bus().publish(event)
            except Exception:
                pass

        await self._progress_broadcaster.broadcast_step_started_async(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step.name,
            step_index=step_index,
            total_steps=total_steps,
            workflow_id=workflow_id,
            user_id=user_id
        )

        step.status = StepStatus.RUNNING
        step.started_at = start_time

        result = StepExecutionResult(step_id=step_id, success=False)

        try:
            resolved_params = self._resolve_step_inputs(execution, step)
            logger.debug(f"[WorkflowExecutor] 步骤 {step_id} 参数解析完成: {resolved_params}")

            await self._progress_broadcaster.broadcast_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=25.0,
                status="running",
                message="参数解析完成",
                workflow_id=workflow_id,
                user_id=user_id
            )

            perception_ctx = None
            if self.config.enable_perception and PERCEPTION_FUSION_AVAILABLE:
                perception_ctx = await self._capture_pre_step_perception(step, execution)
                result.perception_context = perception_ctx

            await self._progress_broadcaster.broadcast_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=40.0,
                status="running",
                message="执行前感知完成",
                workflow_id=workflow_id,
                user_id=user_id
            )

            tool_result = await self._execute_tool_async(step.tool_id, resolved_params, step.timeout)

            if not tool_result:
                raise RuntimeError("工具执行返回空结果")

            result.result = tool_result
            step.result = tool_result

            await self._progress_broadcaster.broadcast_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=70.0,
                status="running",
                message="工具执行完成",
                workflow_id=workflow_id,
                user_id=user_id
            )

            if tool_result.get("success"):
                step.status = StepStatus.COMPLETED
                result.success = True

                if WORKFLOW_ENGINE_AVAILABLE:
                    outputs = VariableResolver.extract_outputs(
                        tool_result, step.output_mapping, step_id
                    )
                    execution.variables.update(outputs)
                    execution.step_results[step_id] = tool_result

                    logger.debug(f"[WorkflowExecutor] 步骤 {step_id} 输出变量: {outputs}")
            else:
                step.status = StepStatus.FAILED
                step.error = tool_result.get("error", "未知错误")
                result.error = step.error
                result.success = False

                logger.warning(f"[WorkflowExecutor] 步骤 {step_id} 执行失败: {step.error}")

            if self.config.enable_verification and PERCEPTION_FUSION_AVAILABLE and step.step_category in ["launch", "save", "transform", "verify"]:
                verification = self._verify_step_result(step, tool_result, perception_ctx)
                result.verification_result = verification

                if verification and not verification.all_passed:
                    logger.warning(f"[WorkflowExecutor] 步骤 {step_id} 验证未通过")
                    if step.is_critical:
                        result.success = False
                        result.error = "执行结果验证未通过"

            await self._progress_broadcaster.broadcast_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                step_progress=90.0,
                status="running",
                message="结果验证完成",
                workflow_id=workflow_id,
                user_id=user_id
            )

            if self.config.save_checkpoints:
                await self._save_checkpoint_async(execution, step_id, step.status.value, slot_id)

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 步骤 {step_id} 执行异常: {e}", exc_info=True)
            step.status = StepStatus.FAILED
            step.error = str(e)
            result.success = False
            result.error = str(e)

            if EVENTS_AVAILABLE:
                try:
                    event = StepFailed(
                        execution_id=execution_id,
                        step_id=step_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            await self._progress_broadcaster.broadcast_step_failed_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                error=str(e),
                workflow_id=workflow_id,
                user_id=user_id
            )

        finally:
            step.completed_at = time.time()
            result.execution_time = step.completed_at - start_time

            if EVENTS_AVAILABLE and result.success:
                try:
                    event = StepCompleted(
                        execution_id=execution_id,
                        step_id=step_id,
                        execution_time=result.execution_time
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            if result.success:
                await self._progress_broadcaster.broadcast_step_completed_async(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_index=step_index,
                    total_steps=total_steps,
                    workflow_id=workflow_id,
                    user_id=user_id
                )

        return result

    def _resolve_step_inputs(self, execution: Any, step: Any) -> dict[str, Any]:
        """解析步骤输入参数"""
        if not WORKFLOW_ENGINE_AVAILABLE:
            return step.tool_params

        return VariableResolver.resolve(
            step.tool_params,
            execution.variables,
            execution.step_results
        )

    def _execute_tool(self, tool_id: str, params: dict[str, Any],
                     timeout: int = 60) -> dict[str, Any]:
        """执行工具（支持超时控制）

        Args:
            tool_id: 工具标识符
            params: 工具参数
            timeout: 超时时间（秒），默认60秒，可通过配置覆盖

        Returns:
            工具执行结果字典
        """
        # 从配置读取超时时间（如果可用）
        try:
            from core.config import config
            timeout = config.get("workflow.step_timeout", timeout)
        except Exception:
            pass  # 使用传入的timeout或默认值

        tool_manager = self._get_tool_manager()

        if tool_manager:
            try:
                # BUG-2修复: 使用ProcessPoolExecutor支持强制终止
                future = self._timeout_executor.submit(tool_manager.execute_tool, tool_id, params)
                try:
                    return future.result(timeout=timeout)
                except FuturesTimeoutError:
                    # 取消任务并终止进程
                    future.cancel()
                    logger.error(f"[WorkflowExecutor] 工具执行超时: {tool_id} (超时时间: {timeout}秒)")
                    return {
                        "success": False,
                        "error": f"步骤执行超时，超过{timeout}秒未完成",
                        "error_code": "STEP_TIMEOUT"
                    }
            except Exception as e:
                logger.error(f"[WorkflowExecutor] 工具执行异常: {e}")
                return {"success": False, "error": str(e)}
        else:
            # 测试模式：模拟执行
            logger.warning(f"[WorkflowExecutor] ToolManager 不可用，模拟执行工具: {tool_id}")
            return {"success": True, "data": {"mock": True, "tool_id": tool_id, "params": params}}

    async def _execute_tool_async(self, tool_id: str, params: dict[str, Any],
                                  timeout: int = 60) -> dict[str, Any]:
        """
        【Phase 7.5】异步版本：执行工具（支持超时控制）

        统一收口到 tool_manager.execute_tool_async()，由 AsyncToolGateway 提供
        取消追踪、超时控制和线程池管理。
        """
        try:
            from core.config import config
            timeout = config.get("workflow.step_timeout", timeout)
        except Exception:
            pass

        tool_manager = self._get_tool_manager()

        if tool_manager:
            try:
                return await tool_manager.execute_tool_async(
                    tool_id=tool_id,
                    params=params,
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"[WorkflowExecutor] 工具执行超时: {tool_id} (超时时间: {timeout}秒)")
                return {
                    "success": False,
                    "error": f"步骤执行超时，超过{timeout}秒未完成",
                    "error_code": "STEP_TIMEOUT"
                }
            except Exception as e:
                logger.error(f"[WorkflowExecutor] 工具执行异常: {e}")
                return {"success": False, "error": str(e)}
        else:
            logger.warning(f"[WorkflowExecutor] ToolManager 不可用，模拟执行工具: {tool_id}")
            return {"success": True, "data": {"mock": True, "tool_id": tool_id, "params": params}}

    async def _capture_pre_step_perception(self, step: Any, execution: Any) -> Any | None:
        """捕获执行前感知"""
        if not PERCEPTION_FUSION_AVAILABLE:
            return None

        perception = self._get_perception_fusion()
        if not perception:
            return None

        try:
            return await perception.capture_for_step(
                step_category=step.step_category,
                step_goal=step.name,
                execution_history=list(execution.step_results.keys())
            )
        except Exception as e:
            logger.warning(f"[WorkflowExecutor] 感知捕获失败: {e}")
            return None

    def _verify_step_result(self, step: Any, tool_result: dict[str, Any],
                           perception_ctx: Any | None) -> Any | None:
        """验证步骤结果"""
        if not PERCEPTION_FUSION_AVAILABLE:
            return None

        perception = self._get_perception_fusion()
        if not perception:
            return None

        try:
            # 构建预期结果
            expected = ExpectedOutcome(
                visual_indicator=step.description,
                data_format={"success": "bool"}
            )

            return perception.verify(expected, perception_ctx, tool_result)
        except Exception as e:
            logger.warning(f"[WorkflowExecutor] 结果验证失败: {e}")
            return None

    def _save_checkpoint(self, execution: Any, step_id: str, status: str, slot_id: int | None = None):
        """
        保存检查点

        【修复断点2】优先使用 CheckpointMemoryBridge 保存增强检查点（包含记忆锚点、感知历史）
        如果 CheckpointMemoryBridge 不可用，则回退到基础 CheckpointManager
        """
        # 【修复断点2】尝试使用增强检查点
        checkpoint_bridge = self._get_checkpoint_memory_bridge()
        if checkpoint_bridge:
            try:
                import asyncio

                # 构建执行状态
                execution_state = {
                    "execution_id": execution.execution_id,
                    "workflow_id": getattr(execution, 'workflow_id', ''),
                    "current_step": step_id,
                    "status": status,
                    "variables": getattr(execution, 'variables', {}),
                    "step_results": getattr(execution, 'step_results', {}),
                    "slot_id": slot_id,
                    "timestamp": time.time()
                }

                # 【修复】异步保存增强检查点 - 使用 asyncio.run 标准化桥接
                checkpoint_id = asyncio.run(
                    checkpoint_bridge.save_workflow_checkpoint(
                        task_id=execution.execution_id,
                        execution_state=execution_state,
                        slot_id=slot_id,
                        checkpoint_type=f"step_{status}"
                    )
                )

                logger.info(f"[WorkflowExecutor] 增强检查点已保存: {checkpoint_id}, 步骤: {step_id}")
                return

            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 增强检查点保存失败，回退到基础检查点: {e}")

        # 回退到基础检查点
        checkpoint_mgr = self._get_checkpoint_manager()
        if not checkpoint_mgr:
            return

        try:
            checkpoint_mgr.save_checkpoint(
                task_id=execution.execution_id,
                checkpoint_name=f"步骤 {step_id}: {status}"
            )
            logger.debug(f"[WorkflowExecutor] 基础检查点已保存: {execution.execution_id}, 步骤: {step_id}")
        except Exception as e:
            logger.warning(f"[WorkflowExecutor] 保存检查点失败: {e}")

    async def _save_checkpoint_async(self, execution: Any, step_id: str, status: str, slot_id: int | None = None):
        """
        【Phase 7.5】异步版本：保存检查点

        使用 await checkpoint_manager.save_checkpoint_async(...) 或 run_in_executor 桥接
        """
        checkpoint_bridge = self._get_checkpoint_memory_bridge()
        if checkpoint_bridge:
            try:
                execution_state = {
                    "execution_id": execution.execution_id,
                    "workflow_id": getattr(execution, 'workflow_id', ''),
                    "current_step": step_id,
                    "status": status,
                    "variables": getattr(execution, 'variables', {}),
                    "step_results": getattr(execution, 'step_results', {}),
                    "slot_id": slot_id,
                    "timestamp": time.time()
                }

                checkpoint_id = await checkpoint_bridge.save_workflow_checkpoint(
                    task_id=execution.execution_id,
                    execution_state=execution_state,
                    slot_id=slot_id,
                    checkpoint_type=f"step_{status}"
                )

                logger.info(f"[WorkflowExecutor] 增强检查点已保存: {checkpoint_id}, 步骤: {step_id}")
                return

            except Exception as e:
                logger.warning(f"[WorkflowExecutor] 增强检查点保存失败，回退到基础检查点: {e}")

        checkpoint_mgr = self._get_checkpoint_manager()
        if not checkpoint_mgr:
            return

        try:
            if hasattr(checkpoint_mgr, 'save_checkpoint_async'):
                await checkpoint_mgr.save_checkpoint_async(
                    task_id=execution.execution_id,
                    checkpoint_name=f"步骤 {step_id}: {status}"
                )
            else:
                await asyncio.to_thread(
                    checkpoint_mgr.save_checkpoint,
                    execution.execution_id,
                    f"步骤 {step_id}: {status}"
                )
            logger.debug(f"[WorkflowExecutor] 基础检查点已保存: {execution.execution_id}, 步骤: {step_id}")
        except Exception as e:
            logger.warning(f"[WorkflowExecutor] 保存检查点失败: {e}")

    async def _execute_subagent_step(
        self,
        execution: Any,
        step: Any,
        voice_instance: Any | None = None,
        slot_id: int | None = None,
        step_index: int = 0,
        total_steps: int = 1
    ) -> StepExecutionResult:
        """
        执行子代理步骤

        【新增】支持在工作流中执行子代理步骤

        Args:
            execution: 工作流执行实例
            step: 工作流步骤（配置为子代理步骤）
            voice_instance: 语音实例
            slot_id: 槽位ID，用于WebSocket广播
            step_index: 当前步骤索引
            total_steps: 总步骤数

        Returns:
            StepExecutionResult: 步骤执行结果
        """
        start_time = time.time()
        step_id = step.step_id
        execution_id = execution.execution_id
        workflow_id = getattr(execution, 'workflow_id', None)
        user_id = getattr(execution, 'user_id', 'default')  # 【修复】获取用户ID

        logger.info(f"[WorkflowExecutor] 执行子代理步骤: {step_id} ({step.name})")

        result = StepExecutionResult(step_id=step_id, success=False)

        # 【新增】广播步骤开始
        self._progress_broadcaster.broadcast_step_started(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step.name,
            step_index=step_index,
            total_steps=total_steps,
            workflow_id=workflow_id,
            user_id=user_id  # 【修复】传递用户ID
        )

        try:
            # 获取子代理步骤执行器
            subagent_executor = self._get_subagent_executor()
            if not subagent_executor:
                raise RuntimeError("SubAgentStepExecutor 不可用")

            # 更新步骤状态
            step.status = StepStatus.RUNNING
            step.started_at = start_time

            # 执行子代理步骤
            subagent_result = await subagent_executor.execute(
                step=step,
                execution_context=execution,
                slot_id=slot_id,
                voice_instance=voice_instance
            )

            # 处理结果
            if subagent_result.get('success'):
                step.status = StepStatus.COMPLETED
                result.success = True
                result.result = subagent_result.get('output')

                # 提取结构化输出到执行变量
                structured_outputs = subagent_result.get('structured_outputs', {})
                if structured_outputs:
                    execution.variables.update(structured_outputs)
                    execution.step_results[step_id] = structured_outputs
                else:
                    execution.step_results[step_id] = {"output": subagent_result.get('output')}

                # 记录验证结果
                verification = subagent_result.get('verification')
                if verification:
                    result.verification_result = verification
                    logger.info(f"[WorkflowExecutor] 子代理步骤 {step_id} 验证结果: {verification.get('verified_by')}")

                logger.info(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行成功")
            else:
                step.status = StepStatus.FAILED
                step.error = subagent_result.get('error', '子代理执行失败')
                result.error = step.error
                result.success = False
                logger.warning(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行失败: {step.error}")

            # 保存执行元数据
            result.result = subagent_result

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行异常: {e}", exc_info=True)
            step.status = StepStatus.FAILED
            step.error = str(e)
            result.success = False
            result.error = str(e)

            # 发送步骤失败事件
            if EVENTS_AVAILABLE:
                try:
                    event = StepFailed(
                        execution_id=execution_id,
                        step_id=step_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            # 【新增】广播步骤失败
            self._progress_broadcaster.broadcast_step_failed(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                error=str(e),
                workflow_id=workflow_id,
                user_id=user_id  # 【修复】传递用户ID
            )

        finally:
            step.completed_at = time.time()
            result.execution_time = step.completed_at - start_time

            # 发送步骤完成事件
            if EVENTS_AVAILABLE and result.success:
                try:
                    event = StepCompleted(
                        execution_id=execution_id,
                        step_id=step_id,
                        execution_time=result.execution_time
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            # 【新增】广播步骤完成
            if result.success:
                self._progress_broadcaster.broadcast_step_completed(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_index=step_index,
                    total_steps=total_steps,
                    workflow_id=workflow_id,
                    user_id=user_id  # 【修复】传递用户ID
                )

        return result

    async def _execute_subagent_step_async(
        self,
        execution: Any,
        step: Any,
        voice_instance: Any | None = None,
        slot_id: int | None = None,
        step_index: int = 0,
        total_steps: int = 1
    ) -> StepExecutionResult:
        """
        【Phase 7.5】异步版本：执行子代理步骤

        移除内部的 asyncio.run() 或 new_event_loop()，直接 await
        """
        start_time = time.time()
        step_id = step.step_id
        execution_id = execution.execution_id
        workflow_id = getattr(execution, 'workflow_id', None)
        user_id = getattr(execution, 'user_id', 'default')

        logger.info(f"[WorkflowExecutor] 执行子代理步骤: {step_id} ({step.name})")

        result = StepExecutionResult(step_id=step_id, success=False)

        await self._progress_broadcaster.broadcast_step_started_async(
            execution_id=execution_id,
            step_id=step_id,
            step_name=step.name,
            step_index=step_index,
            total_steps=total_steps,
            workflow_id=workflow_id,
            user_id=user_id
        )

        try:
            subagent_executor = self._get_subagent_executor()
            if not subagent_executor:
                raise RuntimeError("SubAgentStepExecutor 不可用")

            step.status = StepStatus.RUNNING
            step.started_at = start_time

            subagent_result = await subagent_executor.execute(
                step=step,
                execution_context=execution,
                slot_id=slot_id,
                voice_instance=voice_instance
            )

            if subagent_result.get('success'):
                step.status = StepStatus.COMPLETED
                result.success = True
                result.result = subagent_result.get('output')

                structured_outputs = subagent_result.get('structured_outputs', {})
                if structured_outputs:
                    execution.variables.update(structured_outputs)
                    execution.step_results[step_id] = structured_outputs
                else:
                    execution.step_results[step_id] = {"output": subagent_result.get('output')}

                verification = subagent_result.get('verification')
                if verification:
                    result.verification_result = verification
                    logger.info(f"[WorkflowExecutor] 子代理步骤 {step_id} 验证结果: {verification.get('verified_by')}")

                logger.info(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行成功")
            else:
                step.status = StepStatus.FAILED
                step.error = subagent_result.get('error', '子代理执行失败')
                result.error = step.error
                result.success = False
                logger.warning(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行失败: {step.error}")

            result.result = subagent_result

        except Exception as e:
            logger.error(f"[WorkflowExecutor] 子代理步骤 {step_id} 执行异常: {e}", exc_info=True)
            step.status = StepStatus.FAILED
            step.error = str(e)
            result.success = False
            result.error = str(e)

            if EVENTS_AVAILABLE:
                try:
                    event = StepFailed(
                        execution_id=execution_id,
                        step_id=step_id,
                        error=str(e)
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            await self._progress_broadcaster.broadcast_step_failed_async(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step.name,
                step_index=step_index,
                total_steps=total_steps,
                error=str(e),
                workflow_id=workflow_id,
                user_id=user_id
            )

        finally:
            step.completed_at = time.time()
            result.execution_time = step.completed_at - start_time

            if EVENTS_AVAILABLE and result.success:
                try:
                    event = StepCompleted(
                        execution_id=execution_id,
                        step_id=step_id,
                        execution_time=result.execution_time
                    )
                    get_event_bus().publish(event)
                except Exception:
                    pass

            if result.success:
                await self._progress_broadcaster.broadcast_step_completed_async(
                    execution_id=execution_id,
                    step_id=step_id,
                    step_name=step.name,
                    step_index=step_index,
                    total_steps=total_steps,
                    workflow_id=workflow_id,
                    user_id=user_id
                )

        return result

    def _get_execution_slot_id(self, execution_id: str) -> int | None:
        """
        获取执行实例关联的槽位ID

        Args:
            execution_id: 执行实例ID

        Returns:
            Optional[int]: 槽位ID，如果没有关联则返回None
        """
        # 尝试从执行元数据中获取槽位ID
        execution = None
        workflow_engine = self._get_workflow_engine()
        if workflow_engine:
            with contextlib.suppress(Exception):
                execution = workflow_engine.get_execution(execution_id)

        if execution and hasattr(execution, 'metadata') and execution.metadata:
            return execution.metadata.get('slot_id')

        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════════════════

    def get_execution_status(self, execution_id: str) -> dict[str, Any]:
        """获取执行状态"""
        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            return {"error": "WorkflowEngine 不可用"}

        return workflow_engine.get_execution_status(execution_id)

    def pause_execution(self, execution_id: str, reason: str = "") -> bool:
        """暂停执行"""
        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            return False

        return workflow_engine.pause_execution(execution_id, reason)

    def resume_execution(self, execution_id: str) -> bool:
        """恢复执行"""
        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            return False

        return workflow_engine.resume_execution(execution_id)

    def cancel_execution(self, execution_id: str) -> bool:
        """取消执行"""
        workflow_engine = self._get_workflow_engine()
        if not workflow_engine:
            return False

        return workflow_engine.cancel_execution(execution_id)

    async def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        voice_instance: Any | None = None,
        user_id: str = "default"
    ) -> dict[str, Any]:
        """
        【修复断点3】从检查点恢复执行

        1. 从 CheckpointMemoryBridge 加载增强检查点
        2. 重建执行上下文（包括记忆锚点、感知历史）
        3. 从断点处继续执行

        Args:
            checkpoint_id: 检查点ID
            voice_instance: 语音实例
            user_id: 用户ID

        Returns:
            Dict[str, Any]: 执行结果
        """
        logger.info(f"[WorkflowExecutor] 从检查点恢复执行: {checkpoint_id}")

        # 1. 获取 CheckpointMemoryBridge
        checkpoint_bridge = self._get_checkpoint_memory_bridge()
        if not checkpoint_bridge:
            error_msg = "CheckpointMemoryBridge 不可用，无法恢复执行"
            logger.error(f"[WorkflowExecutor] {error_msg}")
            return {"success": False, "error": error_msg}

        try:
            # 2. 加载检查点和记忆上下文
            state, memory_context = await checkpoint_bridge.restore_workflow_checkpoint(checkpoint_id)

            if not state:
                error_msg = f"检查点不存在或已损坏: {checkpoint_id}"
                logger.error(f"[WorkflowExecutor] {error_msg}")
                return {"success": False, "error": error_msg}

            logger.info(f"[WorkflowExecutor] 检查点加载成功: {checkpoint_id}")
            logger.debug(f"[WorkflowExecutor] 记忆上下文: {list(memory_context.keys())}")

            # 3. 获取执行ID和工作流ID
            execution_id = state.get("execution_id")
            workflow_id = state.get("workflow_id")

            if not execution_id or not workflow_id:
                error_msg = "检查点中缺少执行ID或工作流ID"
                logger.error(f"[WorkflowExecutor] {error_msg}")
                return {"success": False, "error": error_msg}

            # 4. 获取工作流引擎
            workflow_engine = self._get_workflow_engine()
            if not workflow_engine:
                error_msg = "WorkflowEngine 不可用"
                logger.error(f"[WorkflowExecutor] {error_msg}")
                return {"success": False, "error": error_msg}

            # 5. 获取或重新创建工作流执行实例
            execution = workflow_engine.get_execution(execution_id)
            if not execution:
                logger.warning(f"[WorkflowExecutor] 执行实例不存在，尝试重新创建: {execution_id}")
                # 如果执行实例不存在，需要重新创建
                # 这通常发生在系统重启后
                # 从检查点状态重建执行实例
                execution = await workflow_engine.create_execution_from_checkpoint(
                    workflow_id=workflow_id,
                    checkpoint_state=state,
                    user_id=user_id
                )
                if not execution:
                    error_msg = "无法从检查点重建执行实例"
                    logger.error(f"[WorkflowExecutor] {error_msg}")
                    return {"success": False, "error": error_msg}

            # 6. 恢复执行状态
            # 恢复变量
            if "variables" in state:
                execution.variables.update(state["variables"])
                logger.debug(f"[WorkflowExecutor] 恢复变量: {list(state['variables'].keys())}")

            # 恢复步骤结果
            if "step_results" in state:
                execution.step_results.update(state["step_results"])
                logger.debug(f"[WorkflowExecutor] 恢复步骤结果: {list(state['step_results'].keys())}")

            # 恢复当前步骤索引
            current_step = state.get("current_step")
            if current_step:
                # 找到当前步骤的索引
                for idx, step in enumerate(execution.workflow.steps):
                    if step.step_id == current_step:
                        execution.current_step_idx = idx
                        logger.info(f"[WorkflowExecutor] 恢复执行位置: 步骤 {idx} ({current_step})")
                        break

            # 7. 【关键】注入记忆上下文到执行元数据
            if not hasattr(execution, 'metadata') or execution.metadata is None:
                execution.metadata = {}

            execution.metadata["restored_from_checkpoint"] = checkpoint_id
            execution.metadata["memory_context"] = memory_context
            execution.metadata["resolved_anchor_context"] = memory_context.get("anchor_context", {})
            execution.metadata["loaded_memories"] = memory_context.get("loaded_memories", [])

            logger.info(f"[WorkflowExecutor] 记忆上下文已注入: "
                       f"{len(memory_context.get('loaded_memories', []))} 条记忆")

            # 8. 更新执行状态为运行中
            execution.status = ExecutionStatus.RUNNING

            # 9. 发送恢复事件
            if EVENTS_AVAILABLE:
                try:
                    event = WorkflowResumed(
                        execution_id=execution_id,
                        checkpoint_id=checkpoint_id,
                        reason="从检查点恢复执行"
                    )
                    get_event_bus().publish(event)
                except Exception as e:
                    logger.warning(f"[WorkflowExecutor] 发送恢复事件失败: {e}")

            # 10. 继续执行工作流
            logger.info(f"[WorkflowExecutor] 开始继续执行: {execution_id}")

            result = await self.execute_workflow(
                execution_id=execution_id,
                user_id=user_id,
                voice_instance=voice_instance,
                slot_id=state.get("slot_id")
            )

            # 标记恢复成功
            result["restored_from_checkpoint"] = checkpoint_id
            result["memory_context_applied"] = True

            logger.info(f"[WorkflowExecutor] 从检查点恢复执行完成: {execution_id}, "
                       f"状态: {result.get('status')}")

            return result

        except Exception as e:
            error_msg = f"从检查点恢复执行失败: {e}"
            logger.error(f"[WorkflowExecutor] {error_msg}", exc_info=True)
            return {"success": False, "error": error_msg, "checkpoint_id": checkpoint_id}

    def __del__(self):
        """
        BUG-1修复: 析构时关闭ProcessPoolExecutor
        """
        if hasattr(self, '_timeout_executor') and self._timeout_executor:
            try:
                self._timeout_executor.shutdown(wait=False)
                logger.debug("[WorkflowExecutor] ProcessPoolExecutor已关闭")
            except Exception:
                pass  # 忽略关闭时的异常

        # 【新增】清理进度广播器
        if hasattr(self, '_progress_broadcaster') and self._progress_broadcaster:
            with contextlib.suppress(Exception):
                # 清理所有执行实例的推送状态
                # 注意：这里只清理引用，不逐个调用cleanup以加快速度
                logger.debug("[WorkflowExecutor] 进度广播器已清理")


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

_workflow_executor = None
_executor_lock = threading.Lock()


def get_workflow_executor(config: ExecutionConfig | None = None,
                         progress_config: ProgressPushConfig | None = None) -> WorkflowExecutor:
    """获取工作流执行器单例"""
    global _workflow_executor
    if _workflow_executor is None:
        with _executor_lock:
            if _workflow_executor is None:
                _workflow_executor = WorkflowExecutor(config, progress_config)
    return _workflow_executor
