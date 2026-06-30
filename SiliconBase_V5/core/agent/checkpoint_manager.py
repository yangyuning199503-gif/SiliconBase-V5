#!/usr/bin/env python3
"""
CheckpointManager 断点续传管理器 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【断点续传第一阶段】核心类实现

【核心功能】
  ✓ 任务执行状态管理（创建、暂停、恢复、完成）
  ✓ 执行步骤追踪（开始、完成、断点标记）
  ✓ 断点续传支持（从断点恢复任务执行）
  ✓ 双存储架构（内存缓存 + 持久化存储）

【数据模型】
  - ExecutionStep: 单个执行步骤的完整记录
  - TaskExecutionState: 任务整体执行状态

【存储架构】
  - 内存缓存: 活跃任务的快速访问
  - 持久化: 通过 memory_manager 存储到 MEDIUM 层
  - 存储类型: record_type="task_state"

【使用示例】
  >>> from core.agent.checkpoint_manager import checkpoint_manager
  >>>
  >>> # 创建任务
  >>> checkpoint_manager.create_task(
  ...     task_id="task_001",
  ...     user_id="user_001",
  ...     total_steps=5,
  ...     global_context={"goal": "完成数据分析"}
  ... )
  >>>
  >>> # 开始步骤
  >>> checkpoint_manager.start_step(
  ...     task_id="task_001",
  ...     step_number=1,
  ...     step_goal="获取数据",
  ...     input_context={"source": "database"}
  ... )
  >>>
  >>> # 完成步骤
  >>> checkpoint_manager.complete_step(
  ...     task_id="task_001",
  ...     step_number=1,
  ...     tool_name="query_db",
  ...     tool_params={"table": "users"},
  ...     output_result={"data": [...]},
  ...     success=True
  ... )
  >>>
  >>> # 保存断点
  >>> checkpoint_manager.save_checkpoint(task_id="task_001", checkpoint_name="数据获取完成")
  >>>
  >>> # 暂停任务
  >>> checkpoint_manager.pause_task(task_id="task_001", reason="等待用户确认")
  >>>
  >>> # 恢复任务（断点续传核心）
  >>> state = checkpoint_manager.resume_task("task_001")
"""

import asyncio
import json

# 日志记录器
import logging
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from core.diagnostic import diagnostic_except_handler, safe_create_task

# 项目路径
BASE_DIR = Path(__file__).parent.parent
CHECKPOINT_DIR = BASE_DIR / "data" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

from core.exceptions import CheckpointError  # 从统一异常模块导入

# Phase 7.0 基建：检查点-记忆桥接（延迟导入避免循环依赖）
_checkpoint_memory_bridge = None

def _get_checkpoint_memory_bridge():
    global _checkpoint_memory_bridge
    if _checkpoint_memory_bridge is None:
        try:
            from core.memory.checkpoint_memory_bridge import CheckpointMemoryBridge
            _checkpoint_memory_bridge = CheckpointMemoryBridge()
        except Exception as e:
            logger.warning(f"[CheckpointManager] CheckpointMemoryBridge 初始化失败: {e}")
            _checkpoint_memory_bridge = False
    return _checkpoint_memory_bridge if _checkpoint_memory_bridge is not False else None


# ═══════════════════════════════════════════════════════════════
# 统一状态定义导入（消除影子定义）
# ═══════════════════════════════════════════════════════════════

try:
    from core.task.task_status import TaskStatus
except ImportError:
    # 降级：如果统一模块不可用，保留最小定义
    from enum import Enum
    class TaskStatus(Enum):
        PENDING = "pending"
        RUNNING = "running"
        PAUSED = "paused"
        COMPLETED = "completed"
        FAILED = "failed"
        INTERRUPTED = "interrupted"
        READY = "ready"
        AWAITING_CONFIRMATION = "awaiting_confirmation"
        CONFIRMING_UNDERSTANDING = "confirming_understanding"
        CONFIRMED = "confirmed"
        CANCELLED = "cancelled"
        ARCHIVED = "archived"


# ═══════════════════════════════════════════════════════════════
# 敏感信息过滤函数
# ═══════════════════════════════════════════════════════════════

def _sanitize_sensitive_data(data: dict[str, Any], context: str = "") -> dict[str, Any]:
    """
    递归清理敏感字段

    检测并替换以下敏感信息：
    - password, token, secret, api_key, auth, credential
    - 对应的值会被替换为 "***FILTERED***"
    """
    if not isinstance(data, dict):
        return data

    sensitive_keys = {
        'password', 'passwd', 'pwd', 'token', 'secret', 'api_key', 'apikey',
        'auth', 'authorization', 'credential', 'private_key', 'access_key',
        'ssh_key', 'privatekey', 'accesskey', 'client_secret'
    }

    sanitized = {}
    for key, value in data.items():
        # 检查键名是否包含敏感关键词
        key_lower = str(key).lower()
        is_sensitive_key = any(sk in key_lower for sk in sensitive_keys)

        if is_sensitive_key:
            sanitized[key] = "***FILTERED***"
            # 记录过滤事件（不记录实际值）
            logger.debug(f"[CheckpointManager] 敏感信息已过滤: {context}.{key}")
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_sensitive_data(value, f"{context}.{key}" if context else key)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_sensitive_data(item, f"{context}.{key}[{i}]") if isinstance(item, dict) else item
                for i, item in enumerate(value)
            ]
        else:
            sanitized[key] = value

    return sanitized


# ═══════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExecutionStep:
    """
    执行步骤数据类

    记录单个步骤的完整执行信息，包括输入、输出、工具调用、执行结果等。
    支持标记为断点，用于后续恢复执行。

    Attributes:
        step_number: 步骤序号（从1开始）
        task_id: 所属任务ID
        step_goal: 本步骤目标描述
        input_context: 输入上下文数据
        tool_name: 使用的工具名称（可选）
        tool_params: 工具调用参数（可选）
        output_result: 步骤输出结果（可选）
        success: 步骤是否成功（可选）
        error_message: 错误信息（可选）
        started_at: 开始时间（可选）
        completed_at: 完成时间（可选）
        is_checkpoint: 是否是断点标记
        checkpoint_name: 断点名称（可选）
    """
    step_number: int
    task_id: str
    step_goal: str
    input_context: dict[str, Any]
    tool_name: str | None = None
    tool_params: dict[str, Any] | None = None
    output_result: dict[str, Any] | None = None
    success: bool | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    is_checkpoint: bool = False
    checkpoint_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于JSON序列化），自动过滤敏感信息"""
        return {
            "step_number": self.step_number,
            "task_id": self.task_id,
            "step_goal": self.step_goal,
            "input_context": _sanitize_sensitive_data(self.input_context, "input_context"),
            "tool_name": self.tool_name,
            "tool_params": _sanitize_sensitive_data(self.tool_params, "tool_params") if self.tool_params else None,
            "output_result": _sanitize_sensitive_data(self.output_result, "output_result") if self.output_result else None,
            "success": self.success,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "is_checkpoint": self.is_checkpoint,
            "checkpoint_name": self.checkpoint_name
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ExecutionStep':
        """从字典创建实例（反序列化）"""
        data = data.copy()

        # 解析时间字符串
        if isinstance(data.get("started_at"), str):
            data["started_at"] = datetime.fromisoformat(data["started_at"])
        if isinstance(data.get("completed_at"), str):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"])

        # 过滤有效字段
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)

    def mark_checkpoint(self, name: str) -> None:
        """标记此步骤为断点"""
        self.is_checkpoint = True
        self.checkpoint_name = name
        logger.debug(f"[ExecutionStep] 步骤 {self.step_number} 标记为断点: {name}")

    def is_completed(self) -> bool:
        """检查步骤是否已完成"""
        return self.completed_at is not None and self.success is not None


@dataclass
class TaskExecutionState:
    """
    任务执行状态数据类

    记录整个任务的执行状态，包括所有步骤、进度、全局上下文等。
    支持断点续传：从断点恢复时，只需重新执行未完成步骤。

    Attributes:
        task_id: 任务唯一标识
        user_id: 用户ID
        total_steps: 总步骤数
        completed_steps: 已完成步骤数
        current_step_number: 当前执行到的步骤序号
        status: 任务状态 (pending/running/paused/completed/failed)
        steps: 所有执行步骤列表
        global_context: 全局上下文数据（跨步骤共享）
        created_at: 创建时间
        updated_at: 更新时间
        resumed_at: 上次恢复时间（可选）
        resume_count: 恢复次数统计
        last_checkpoint_step: 最后一个断点步骤序号（可选）
        pause_reason: 暂停原因（可选）
        phase_anchors: 阶段锚点列表（修复新增）
        checkpoint_id: 检查点唯一标识（异步持久化确认用）
    """
    task_id: str
    user_id: str
    total_steps: int
    completed_steps: int = 0
    current_step_number: int = 0
    status: str = field(default="pending")
    steps: list[ExecutionStep] = field(default_factory=list)
    global_context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    resumed_at: datetime | None = None
    resume_count: int = 0
    last_checkpoint_step: int | None = None
    pause_reason: str | None = None
    phase_anchors: list[dict[str, Any]] = field(default_factory=list)  # 【修复新增】阶段锚点列表
    checkpoint_id: str | None = field(default=None)  # 【修复新增】检查点唯一标识

    def __post_init__(self):
        """初始化后验证状态一致性"""
        if self.status not in [s.value for s in TaskStatus]:
            logger.warning(f"[TaskExecutionState] 未知状态 '{self.status}'，重置为 'pending'")
            self.status = "pending"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于JSON序列化），自动过滤敏感信息"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "current_step_number": self.current_step_number,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "global_context": _sanitize_sensitive_data(self.global_context, "global_context"),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resumed_at": self.resumed_at.isoformat() if self.resumed_at else None,
            "resume_count": self.resume_count,
            "last_checkpoint_step": self.last_checkpoint_step,
            "pause_reason": self.pause_reason,
            "phase_anchors": self.phase_anchors,  # 【修复新增】保存阶段锚点
            "checkpoint_id": self.checkpoint_id  # 【修复新增】保存检查点ID
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'TaskExecutionState':
        """从字典创建实例（反序列化）"""
        data = data.copy()

        # 解析步骤列表
        if "steps" in data and isinstance(data["steps"], list):
            data["steps"] = [ExecutionStep.from_dict(step) for step in data["steps"]]
        else:
            data["steps"] = []

        # 【修复新增】解析阶段锚点列表
        if "phase_anchors" in data and isinstance(data["phase_anchors"], list):
            data["phase_anchors"] = data["phase_anchors"]
        else:
            data["phase_anchors"] = []

        # 解析时间字符串
        for field_name in ["created_at", "updated_at", "resumed_at"]:
            if isinstance(data.get(field_name), str):
                data[field_name] = datetime.fromisoformat(data[field_name])

        # 过滤有效字段
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)

    def get_progress_percentage(self) -> float:
        """获取进度百分比"""
        if self.total_steps <= 0:
            return 0.0
        return round((self.completed_steps / self.total_steps) * 100, 2)

    def get_current_step(self) -> ExecutionStep | None:
        """获取当前步骤"""
        for step in self.steps:
            if step.step_number == self.current_step_number:
                return step
        return None

    def get_last_checkpoint(self) -> ExecutionStep | None:
        """获取最后一个断点步骤"""
        if self.last_checkpoint_step is None:
            return None
        for step in self.steps:
            if step.step_number == self.last_checkpoint_step:
                return step
        return None

    def can_resume(self) -> bool:
        """检查任务是否可以恢复

        支持的状态：PAUSED（正常暂停）、FAILED（失败重试）、INTERRUPTED（崩溃/中断恢复）
        """
        return self.status in [
            TaskStatus.PAUSED.value,
            TaskStatus.FAILED.value,
            TaskStatus.INTERRUPTED.value
        ]

    def get_resume_step_number(self) -> int:
        """
        获取恢复执行时应开始的步骤序号

        策略：
        1. 如果有断点且断点步骤有效（>0），从断点步骤开始
        2. 如果断点步骤为0（任务级别断点，无执行步骤），从第1步开始
        3. 否则从当前未完成步骤开始
        4. 如果没有未完成步骤，从最后一步+1开始
        """
        if self.last_checkpoint_step is not None:
            if self.last_checkpoint_step > 0:
                # 有有效断点步骤，从该步骤开始
                return self.last_checkpoint_step
            else:
                # 断点步骤为0，表示任务级别断点（无执行步骤），从第1步开始
                return 1

        # 找到第一个未完成的步骤
        for step in self.steps:
            if not step.is_completed():
                return step.step_number

        # 所有步骤都完成了，返回下一步
        return self.completed_steps + 1

    def update_timestamp(self) -> None:
        """更新修改时间"""
        self.updated_at = datetime.now()


# ═══════════════════════════════════════════════════════════════
# CheckpointManager 核心类
# ═══════════════════════════════════════════════════════════════

class CheckpointManager:
    """
    断点续传管理器

    管理任务的创建、执行、暂停、恢复和断点保存。
    支持内存缓存 + 持久化双存储架构。

    【单例模式】
    全局唯一实例通过 checkpoint_manager 访问

    【线程安全】
    所有操作使用 RLock 保证线程安全

    【存储策略】
    - 内存缓存: 活跃任务的快速访问 (_tasks)
    - 持久化: 通过 memory_manager 存储到 MEDIUM 层
    - 本地备份: JSONL 文件作为降级方案

    【断点续传流程】
    1. 创建任务 -> create_task()
    2. 循环执行步骤:
       a. 开始步骤 -> start_step()
       b. 执行工具调用
       c. 完成步骤 -> complete_step()
       d. 可选: 保存断点 -> save_checkpoint()
    3. 暂停/异常 -> pause_task()
    4. 恢复任务 -> resume_task()（从断点继续）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式创建"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器"""
        if self._initialized:
            return
        self._initialized = True

        # 【新增】强制PostgreSQL模式配置
        self._force_postgres = os.getenv(
            "SILICONBASE_CHECKPOINT_FORCE_POSTGRES",
            "false"
        ).lower() == "true"

        if self._force_postgres:
            logger.info("[CheckpointManager] 强制PostgreSQL模式已启用")

        # 内存缓存: task_id -> TaskExecutionState
        self._tasks: dict[str, TaskExecutionState] = {}
        self._tasks_lock = asyncio.Lock()


        # 用户任务索引: user_id -> List[task_id]
        self._user_tasks: dict[str, list[str]] = {}
        self._user_tasks_lock = asyncio.Lock()

        # 持久化存储目录
        self._checkpoint_dir = CHECKPOINT_DIR

        # 回调注册表
        self._callbacks: dict[str, list[Callable]] = {
            "on_task_created": [],
            "on_task_started": [],
            "on_step_completed": [],
            "on_checkpoint_saved": [],
            "on_task_paused": [],
            "on_task_resumed": [],
            "on_task_completed": [],
            "on_task_failed": []
        }

        # 尝试加载 memory_manager（延迟加载）
        self._memory_manager = None

        logger.info("[CheckpointManager] 断点续传管理器初始化完成")

    def _get_memory_manager(self):
        """获取 memory_manager 实例（延迟加载）"""
        if self._memory_manager is None:
            try:
                from core.memory.memory_manager import memory_manager
                self._memory_manager = memory_manager
            except ImportError as e:
                logger.warning(f"[CheckpointManager] memory_manager 导入失败: {e}")
        return self._memory_manager

    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """触发事件回调"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.warning(f"[CheckpointManager] 回调执行失败 {event}: {e}")

    async def _extract_and_store_experience(self, task_state: TaskExecutionState) -> None:
        """
        【2026-03-22 关键修复】任务完成后提取并存储经验

        从完成的任务状态中提取经验，并存储到L3/L4记忆层：
        - L3 (medium): 一般经验和失败教训
        - L4 (evolve): 高质量经验 (>0.8分)

        Args:
            task_state: 任务执行状态
        """
        try:
            from core.memory.memory_manager import MemoryLayer, MemoryType, memory_manager

            # 直接保存原始任务执行记录（不再经过硬编码模板萃取）
            experience_content = {
                'task_id': task_state.task_id,
                'task_type': task_state.global_context.get('task_type', 'general'),
                'success': task_state.status == TaskStatus.COMPLETED.value,
                'total_steps': task_state.total_steps,
                'completed_steps': task_state.completed_steps,
                'steps_summary': [
                    {
                        'step_number': s.step_number,
                        'step_goal': s.step_goal,
                        'tool_name': s.tool_name,
                        'success': s.success,
                        'error_message': s.error_message
                    }
                    for s in task_state.steps
                ],
                'recorded_at': datetime.now().isoformat()
            }

            mem_id = await memory_manager.store_memory(
                layer=MemoryLayer.MEDIUM,
                mem_type=MemoryType.EXPERIENCE,
                content=experience_content,
                context={
                    'task_id': task_state.task_id,
                    'user_id': task_state.user_id,
                },
                scene=f"experience_{task_state.task_id}",
                rating=5,
                expire_days=30
            )
            if mem_id:
                logger.debug(f"[CheckpointManager] 经验已存储到L3: {mem_id[:8]}...")

            # 成功任务额外升 L4
            if task_state.status == TaskStatus.COMPLETED.value:
                mem_id = await memory_manager.store_memory(
                    layer=MemoryLayer.EVOLVE,
                    mem_type=MemoryType.KNOWLEDGE,
                    content=experience_content,
                    context={
                        'task_id': task_state.task_id,
                        'user_id': task_state.user_id,
                        'is_high_quality': True
                    },
                    scene=f"knowledge_{task_state.task_id}",
                    rating=5,
                    expire_days=365
                )
                if mem_id:
                    logger.info(f"[CheckpointManager] 成功任务经验已存储到L4: {mem_id[:8]}...")

        except ImportError as e:
            logger.warning(f"[CheckpointManager] 经验存储模块未就绪: {e}")
        except Exception as e:
            logger.error(f"[CheckpointManager] 经验存储失败: {e}")

    def register_callback(self, event: str, callback: Callable) -> bool:
        """
        注册事件回调

        Args:
            event: 事件类型
            callback: 回调函数

        Returns:
            是否注册成功
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)
            logger.debug(f"[CheckpointManager] 注册回调: {event}")
            return True
        logger.warning(f"[CheckpointManager] 未知事件类型: {event}")
        return False

    # ═══════════════════════════════════════════════════════════════
    # 核心API: 任务管理
    # ═══════════════════════════════════════════════════════════════

    async def create_task(self, task_id: str, user_id: str, total_steps: int,
                   global_context: dict[str, Any] | None = None) -> TaskExecutionState:
        """
        创建新任务

        Args:
            task_id: 任务唯一标识
            user_id: 用户ID
            total_steps: 预计总步骤数
            global_context: 全局上下文（跨步骤共享的数据）

        Returns:
            任务执行状态对象

        Raises:
            ValueError: 如果 task_id 已存在
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            if task_id in self._tasks:
                raise ValueError(f"任务 {task_id} 已存在")

            # 创建任务状态
            state = TaskExecutionState(
                task_id=task_id,
                user_id=user_id,
                total_steps=total_steps,
                status=TaskStatus.PENDING.value,
                global_context=global_context or {},
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            # 保存到内存缓存
            self._tasks[task_id] = state

            # 更新用户任务索引
            async with self._user_tasks_lock:
                if user_id not in self._user_tasks:
                    self._user_tasks[user_id] = []
                if task_id not in self._user_tasks[user_id]:
                    self._user_tasks[user_id].append(task_id)

            # 持久化存储
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 创建任务时持久化失败: task_id={task_id}"
                logger.error(error_msg)
                # 回滚内存中的任务
                del self._tasks[task_id]
                async with self._user_tasks_lock:
                    if user_id in self._user_tasks and task_id in self._user_tasks[user_id]:
                        self._user_tasks[user_id].remove(task_id)
                raise CheckpointError(error_msg)

            # 触发回调
            self._trigger_callbacks("on_task_created", state)

            logger.info(f"[CheckpointManager] 创建任务: {task_id}, 用户: {user_id}, 步骤数: {total_steps}")
            return state

    async def create_task_async(self, task_id: str, user_id: str, total_steps: int,
                                global_context: dict[str, Any] | None = None,
                                working_memory=None) -> TaskExecutionState:
        """异步创建新任务（Phase 8 原生异步驱动）

        Args:
            task_id: 任务唯一标识
            user_id: 用户ID
            total_steps: 预计总步骤数
            global_context: 全局上下文（跨步骤共享的数据）
            working_memory: 工作记忆实例（可选），创建时保存到 global_context

        Returns:
            任务执行状态对象

        Raises:
            ValueError: 如果 task_id 已存在
            CheckpointError: 持久化失败
        """
        async def _sync_op():
            async with self._tasks_lock:
                if task_id in self._tasks:
                    raise ValueError(f"任务 {task_id} 已存在")

                state = TaskExecutionState(
                    task_id=task_id,
                    user_id=user_id,
                    total_steps=total_steps,
                    status=TaskStatus.PENDING.value,
                    global_context=global_context or {},
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )

                self._tasks[task_id] = state

                async with self._user_tasks_lock:
                    if user_id not in self._user_tasks:
                        self._user_tasks[user_id] = []
                    if task_id not in self._user_tasks[user_id]:
                        self._user_tasks[user_id].append(task_id)

                # 【修复BUG-1】如果传入了 working_memory，保存到 global_context
                if working_memory is not None:
                    state.global_context["working_memory"] = working_memory.to_dict_full()

                persist_success = await self._persist_task_state(state)
                if not persist_success:
                    error_msg = f"[SILENT_FAILURE_BLOCKED] 创建任务时持久化失败: task_id={task_id}"
                    logger.error(error_msg)
                    del self._tasks[task_id]
                    async with self._user_tasks_lock:
                        if user_id in self._user_tasks and task_id in self._user_tasks[user_id]:
                            self._user_tasks[user_id].remove(task_id)
                    raise CheckpointError(error_msg)

                self._trigger_callbacks("on_task_created", state)
                return state

        state = await _sync_op()
        logger.info(f"[CheckpointManager] 异步创建任务: {task_id}, 用户: {user_id}, 步骤数: {total_steps}")
        return state
    async def start_step(self, task_id: str, step_number: int, step_goal: str,
                  input_context: dict[str, Any] | None = None) -> ExecutionStep:
        """
        开始执行一个步骤

        Args:
            task_id: 任务ID
            step_number: 步骤序号（从1开始）
            step_goal: 步骤目标描述
            input_context: 步骤输入上下文

        Returns:
            执行步骤对象

        Raises:
            KeyError: 如果任务不存在
            ValueError: 如果步骤序号无效
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                raise KeyError(f"任务 {task_id} 不存在")

            state = self._tasks[task_id]

            # 验证步骤序号
            if step_number < 1 or step_number > state.total_steps:
                raise ValueError(f"步骤序号 {step_number} 超出范围 [1, {state.total_steps}]")

            # 更新任务状态为运行中
            state.status = TaskStatus.RUNNING.value
            state.current_step_number = step_number
            state.update_timestamp()

            # 创建步骤
            step = ExecutionStep(
                step_number=step_number,
                task_id=task_id,
                step_goal=step_goal,
                input_context=input_context or {},
                started_at=datetime.now()
            )

            # 添加到步骤列表（如果已存在则替换）
            existing_idx = None
            for idx, s in enumerate(state.steps):
                if s.step_number == step_number:
                    existing_idx = idx
                    break

            if existing_idx is not None:
                state.steps[existing_idx] = step
            else:
                state.steps.append(step)

            # 持久化
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 开始步骤时持久化失败: task_id={task_id}, step_number={step_number}"
                logger.error(error_msg)
                raise CheckpointError(error_msg)

            # 触发回调
            self._trigger_callbacks("on_task_started", state, step)

            logger.debug(f"[CheckpointManager] 任务 {task_id} 开始步骤 {step_number}: {step_goal}")
            return step

    async def start_step_async(self, task_id: str, step_number: int, step_goal: str,
                                input_context: dict[str, Any] | None = None) -> ExecutionStep:
        """异步开始一个步骤（Phase 8 原生异步驱动）"""
        async def _sync_op():
            async with self._tasks_lock:
                if task_id not in self._tasks:
                    raise KeyError(f"任务 {task_id} 不存在")
                state = self._tasks[task_id]
                if step_number < 1 or step_number > state.total_steps:
                    raise ValueError(f"步骤序号 {step_number} 超出范围 [1, {state.total_steps}]")
                state.status = TaskStatus.RUNNING.value
                state.current_step_number = step_number
                state.update_timestamp()
                step = ExecutionStep(
                    step_number=step_number,
                    task_id=task_id,
                    step_goal=step_goal,
                    input_context=input_context or {},
                    started_at=datetime.now()
                )
                existing_idx = None
                for idx, s in enumerate(state.steps):
                    if s.step_number == step_number:
                        existing_idx = idx
                        break
                if existing_idx is not None:
                    state.steps[existing_idx] = step
                else:
                    state.steps.append(step)
                persist_success = await self._persist_task_state(state)
                if not persist_success:
                    error_msg = f"[SILENT_FAILURE_BLOCKED] 开始步骤时持久化失败: task_id={task_id}, step_number={step_number}"
                    logger.error(error_msg)
                    raise CheckpointError(error_msg)
                self._trigger_callbacks("on_task_started", state, step)
                return step
        return await _sync_op()

    async def complete_step(self, task_id: str, step_number: int,
                     tool_name: str | None = None,
                     tool_params: dict[str, Any] | None = None,
                     output_result: dict[str, Any] | None = None,
                     success: bool = True,
                     error_message: str | None = None) -> ExecutionStep:
        """
        完成一个步骤

        Args:
            task_id: 任务ID
            step_number: 步骤序号
            tool_name: 使用的工具名称
            tool_params: 工具调用参数
            output_result: 步骤输出结果
            success: 是否成功
            error_message: 错误信息（失败时）

        Returns:
            更新后的执行步骤对象

        Raises:
            KeyError: 如果任务或步骤不存在
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                raise KeyError(f"任务 {task_id} 不存在")

            state = self._tasks[task_id]

            # 查找步骤
            step = None
            for s in state.steps:
                if s.step_number == step_number:
                    step = s
                    break

            if step is None:
                logger.warning(f"[CheckpointManager] 步骤 {step_number} 不存在于任务 {task_id}，自动创建")
                step = ExecutionStep(
                    step_number=step_number,
                    task_id=task_id,
                    step_goal=f"自动创建步骤 {step_number}",
                    input_context={}
                )
                state.steps.append(step)

            # 更新步骤信息
            step.tool_name = tool_name
            step.tool_params = tool_params
            step.output_result = output_result
            step.success = success
            step.error_message = error_message
            step.completed_at = datetime.now()

            # 更新任务状态
            if success:
                state.completed_steps = max(state.completed_steps, step_number)

                # 检查是否所有步骤都完成了
                if state.completed_steps >= state.total_steps:
                    state.status = TaskStatus.COMPLETED.value
                    self._trigger_callbacks("on_task_completed", state)
                    # 【2026-03-22 关键修复】任务完成后提取经验
                    await self._extract_and_store_experience(state)
                    logger.info(f"[CheckpointManager] 任务 {task_id} 完成，已触发经验提取")
            else:
                state.status = TaskStatus.FAILED.value
                self._trigger_callbacks("on_task_failed", state, step)
                # 【2026-03-22 关键修复】任务失败也提取教训
                await self._extract_and_store_experience(state)
                logger.warning(f"[CheckpointManager] 任务 {task_id} 步骤 {step_number} 失败，已提取失败教训: {error_message}")

            state.update_timestamp()

            # 持久化
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 完成步骤时持久化失败: task_id={task_id}, step_number={step_number}"
                logger.error(error_msg)
                raise CheckpointError(error_msg)

            # 触发回调
            self._trigger_callbacks("on_step_completed", state, step)

            logger.debug(f"[CheckpointManager] 任务 {task_id} 完成步骤 {step_number}, 成功: {success}")
            return step

    async def complete_step_async(self, task_id: str, step_number: int,
                                  tool_name: str | None = None,
                                  tool_params: dict[str, Any] | None = None,
                                  output_result: dict[str, Any] | None = None,
                                  success: bool = True,
                                  error_message: str | None = None) -> ExecutionStep:
        """异步完成一个步骤（Phase 8 原生异步驱动）

        Args:
            task_id: 任务ID
            step_number: 步骤序号
            tool_name: 使用的工具名称
            tool_params: 工具调用参数
            output_result: 步骤输出结果
            success: 是否成功
            error_message: 错误信息（失败时）

        Returns:
            更新后的执行步骤对象

        Raises:
            KeyError: 如果任务或步骤不存在
            CheckpointError: 持久化失败
        """
        async def _sync_op():
            async with self._tasks_lock:
                if task_id not in self._tasks:
                    raise KeyError(f"任务 {task_id} 不存在")

                state = self._tasks[task_id]

                step = None
                for s in state.steps:
                    if s.step_number == step_number:
                        step = s
                        break

                if step is None:
                    logger.warning(f"[CheckpointManager] 步骤 {step_number} 不存在于任务 {task_id}，自动创建")
                    step = ExecutionStep(
                        step_number=step_number,
                        task_id=task_id,
                        step_goal=f"自动创建步骤 {step_number}",
                        input_context={}
                    )
                    state.steps.append(step)

                step.tool_name = tool_name
                step.tool_params = tool_params
                step.output_result = output_result
                step.success = success
                step.error_message = error_message
                step.completed_at = datetime.now()

                if success:
                    state.completed_steps = max(state.completed_steps, step_number)
                    if state.completed_steps >= state.total_steps:
                        state.status = TaskStatus.COMPLETED.value
                        self._trigger_callbacks("on_task_completed", state)
                        await self._extract_and_store_experience(state)
                        # 自动清理已完成的任务
                        self.cleanup_completed_tasks(before_days=0)
                        logger.info(f"[CheckpointManager] 任务 {task_id} 完成，已触发经验提取并自动清理")
                else:
                    state.status = TaskStatus.FAILED.value
                    self._trigger_callbacks("on_task_failed", state, step)
                    await self._extract_and_store_experience(state)
                    logger.warning(f"[CheckpointManager] 任务 {task_id} 步骤 {step_number} 失败，已提取失败教训: {error_message}")

                state.update_timestamp()

                persist_success = await self._persist_task_state(state)
                if not persist_success:
                    error_msg = f"[SILENT_FAILURE_BLOCKED] 完成步骤时持久化失败: task_id={task_id}, step_number={step_number}"
                    logger.error(error_msg)
                    raise CheckpointError(error_msg)

                self._trigger_callbacks("on_step_completed", state, step)
                return step, state

        step, state = await _sync_op()
        logger.debug(f"[CheckpointManager] 任务 {task_id} 异步完成步骤 {step_number}, 成功: {success}")
        return step

    async def save_checkpoint(self, task_id: str, checkpoint_name: str) -> ExecutionStep | None:
        """
        保存断点

        将当前步骤标记为断点，用于后续恢复执行。
        如果没有当前执行步骤（如任务刚开始或纯对话任务），
        则在任务状态级别记录断点信息，而不关联到具体步骤。

        Args:
            task_id: 任务ID
            checkpoint_name: 断点名称（描述性）

        Returns:
            被标记为断点的步骤对象，如果没有步骤则返回None

        Raises:
            KeyError: 如果任务不存在
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                raise KeyError(f"任务 {task_id} 不存在")

            state = self._tasks[task_id]

            # 获取当前步骤
            current_step = state.get_current_step()

            if current_step is not None:
                # 正常情况：有当前步骤，标记为断点
                current_step.mark_checkpoint(checkpoint_name)
                state.last_checkpoint_step = current_step.step_number
                logger.info(f"[CheckpointManager] 任务 {task_id} 保存断点: {checkpoint_name} (步骤 {current_step.step_number})")
            else:
                # 特殊情况：没有当前步骤（任务刚开始或纯对话任务）
                # 在任务状态级别记录断点信息
                state.last_checkpoint_step = 0  # 标记为步骤0，表示任务级别断点
                logger.info(f"[CheckpointManager] 任务 {task_id} 保存断点: {checkpoint_name} (任务级别，无执行步骤)")

            state.update_timestamp()

            # 持久化
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 保存断点时持久化失败: task_id={task_id}, checkpoint_name={checkpoint_name}"
                logger.error(error_msg)
                raise CheckpointError(error_msg)

            self._trigger_callbacks("on_checkpoint_saved", state, current_step)

            return current_step

    async def save_checkpoint_async(self, task_id: str, checkpoint_name: str, state: TaskExecutionState | None = None, working_memory=None) -> ExecutionStep | None:
        """异步保存断点（Phase 7.0 基建）

        初始实现：桥接到内部 _async_save，保持与同步版相同的行为。
        未来可替换为原生 asyncpg 实现。

        Args:
            task_id: 任务ID
            checkpoint_name: 断点名称
            state: 可选的外部传入状态（为 None 时从内部任务表获取）
            working_memory: 工作记忆实例（可选），保存到 global_context

        Returns:
            被标记为断点的步骤对象
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                raise KeyError(f"任务 {task_id} 不存在")

            _state = state if state is not None else self._tasks[task_id]

            current_step = _state.get_current_step()

            if current_step is not None:
                current_step.mark_checkpoint(checkpoint_name)
                _state.last_checkpoint_step = current_step.step_number
                logger.info(f"[CheckpointManager] 异步保存断点: {checkpoint_name} (步骤 {current_step.step_number})")
            else:
                _state.last_checkpoint_step = 0
                logger.info(f"[CheckpointManager] 异步保存断点: {checkpoint_name} (任务级别)")

            _state.update_timestamp()
            state = _state

        # 【修复BUG-2】保存 working_memory 到 global_context
        if working_memory is not None:
            state.global_context["working_memory"] = working_memory.to_dict_full()

        # 【修复】保存最近对话历史到 global_context（断点续传上下文恢复）
        if working_memory is not None:
            try:
                msgs = working_memory.get_message_history() if hasattr(working_memory, 'get_message_history') else []
                state.global_context["chat_history"] = [
                    {"role": msg.get("role", "user"), "content": str(msg.get("content", ""))[:500]}
                    for msg in (msgs[-20:] if msgs else [])
                ]
            except Exception as e:
                logger.debug(f"[CheckpointManager] 对话历史保存失败（非阻塞）: {e}")
                state.global_context["chat_history"] = []
        else:
            state.global_context["chat_history"] = []

        # 异步持久化（锁外执行，避免阻塞事件循环）
        # 【零静默失败】_async_save 失败时直接抛出 CheckpointError，无需检查返回值
        await self._async_save(state)

        self._trigger_callbacks("on_checkpoint_saved", state, current_step)
        return current_step

    async def load_checkpoint_async(self, checkpoint_id: str) -> dict | None:
        """异步加载断点（Phase 7.0 基建）

        Args:
            checkpoint_id: 断点/任务ID

        Returns:
            断点状态字典，不存在则返回 None
        """
        loaded_state = await self._async_load(checkpoint_id)
        if loaded_state is None:
            return None
        # 转换为 dict 以保持与同步 restore 路径一致的返回格式
        return loaded_state.to_dict() if hasattr(loaded_state, 'to_dict') else loaded_state.__dict__

    async def pause_task(self, task_id: str, reason: str | None = None) -> TaskExecutionState:
        """
        暂停任务

        暂停任务执行，保存当前状态以便后续恢复。

        Args:
            task_id: 任务ID
            reason: 暂停原因

        Returns:
            任务执行状态对象

        Raises:
            KeyError: 如果任务不存在
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                raise KeyError(f"任务 {task_id} 不存在")

            state = self._tasks[task_id]

            # 运行中或待处理的任务都可以暂停
            if state.status not in (TaskStatus.RUNNING.value, TaskStatus.PENDING.value):
                logger.warning(f"[CheckpointManager] 任务 {task_id} 状态为 {state.status}，无法暂停")
                return state

            state.status = TaskStatus.PAUSED.value
            state.pause_reason = reason
            state.update_timestamp()

            # 持久化
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 暂停任务时持久化失败: task_id={task_id}"
                logger.error(error_msg)
                raise CheckpointError(error_msg)

            # 触发回调
            self._trigger_callbacks("on_task_paused", state)

            logger.info(f"[CheckpointManager] 任务 {task_id} 已暂停，原因: {reason}")
            return state

    async def resume_task(self, task_id: str) -> TaskExecutionState:
        """
        恢复任务（断点续传核心）

        从上次保存的状态恢复任务执行。根据断点信息决定从哪个步骤继续。

        Args:
            task_id: 任务ID

        Returns:
            任务执行状态对象（已恢复状态）

        Raises:
            KeyError: 如果任务不存在
            ValueError: 如果任务状态不允许恢复
            CheckpointError: 持久化失败
        """
        async with self._tasks_lock:
            loaded_from_storage = task_id not in self._tasks
            if loaded_from_storage:
                # 尝试从持久化存储加载
                state = await self._load_task_state_async(task_id)
                if state is None:
                    raise KeyError(f"任务 {task_id} 不存在")
                self._tasks[task_id] = state
            else:
                state = self._tasks[task_id]

            # 【崩溃恢复】如果从持久化加载且状态为 RUNNING，自动修正为 INTERRUPTED
            if loaded_from_storage and state.status == TaskStatus.RUNNING.value:
                logger.warning(
                    f"[CheckpointManager] 任务 {task_id} 从持久化加载时状态为 RUNNING，"
                    f"疑似崩溃/异常中断，自动修正为 INTERRUPTED 以允许恢复"
                )
                state.status = TaskStatus.INTERRUPTED.value

            # 检查是否可以恢复
            if not state.can_resume():
                raise ValueError(f"任务 {task_id} 状态为 {state.status}，无法恢复")

            # 更新恢复信息
            state.status = TaskStatus.RUNNING.value
            state.resumed_at = datetime.now()
            state.resume_count += 1
            state.pause_reason = None

            # 确定恢复步骤
            resume_step = state.get_resume_step_number()
            state.current_step_number = resume_step
            state.update_timestamp()

            # 持久化
            # 【2026-03-10 修复】检查持久化结果，禁止静默失败
            persist_success = await self._persist_task_state(state)
            if not persist_success:
                error_msg = f"[SILENT_FAILURE_BLOCKED] 恢复任务时持久化失败: task_id={task_id}"
                logger.error(error_msg)
                raise CheckpointError(error_msg)

            # 触发回调
            self._trigger_callbacks("on_task_resumed", state)

            checkpoint_info = ""
            if state.last_checkpoint_step:
                checkpoint = state.get_last_checkpoint()
                if checkpoint:
                    checkpoint_info = f"，从断点 '{checkpoint.checkpoint_name}' (步骤 {checkpoint.step_number}) 恢复"

            logger.info(f"[CheckpointManager] 任务 {task_id} 已恢复，当前步骤: {resume_step}{checkpoint_info}")

            # Phase 7.0 基建：断点恢复后回流记忆上下文
            bridge = _get_checkpoint_memory_bridge()
            if bridge:
                try:
                    import asyncio
                    checkpoint_id = state.checkpoint_id or task_id
                    if asyncio.get_event_loop().is_running():
                        safe_create_task(bridge.restore_workflow_checkpoint(checkpoint_id, user_id=state.user_id), name="restore_workflow_checkpoint")
                    else:
                        asyncio.get_event_loop().run_until_complete(
                            bridge.restore_workflow_checkpoint(checkpoint_id, user_id=state.user_id)
                        )
                    logger.info(f"[CheckpointManager] 已触发记忆上下文回流: task_id={task_id}")
                except Exception as e:
                    logger.warning(f"[CheckpointManager] 记忆上下文回流失败（非阻塞）: {e}")

            return state

    async def resume_task_async(self, task_id: str, session_id: str | None = None) -> TaskExecutionState:
        """异步恢复任务（Phase 8 原生异步驱动）

        从上次保存的状态恢复任务执行。根据断点信息决定从哪个步骤继续。

        Args:
            task_id: 任务ID
            session_id: 会话ID（可选），用于精确恢复对话历史

        Returns:
            任务执行状态对象（已恢复状态）

        Raises:
            KeyError: 如果任务不存在
            ValueError: 如果任务状态不允许恢复
            CheckpointError: 持久化失败
        """
        async def _sync_op():
            async with self._tasks_lock:
                loaded_from_storage = task_id not in self._tasks
                if loaded_from_storage:
                    state = await self._load_task_state_async(task_id)
                    if state is None:
                        raise KeyError(f"任务 {task_id} 不存在")
                    self._tasks[task_id] = state
                else:
                    state = self._tasks[task_id]

                # 【崩溃恢复】如果从持久化加载且状态为 RUNNING，自动修正为 INTERRUPTED
                if loaded_from_storage and state.status == TaskStatus.RUNNING.value:
                    logger.warning(
                        f"[CheckpointManager] 任务 {task_id} 从持久化加载时状态为 RUNNING，"
                        f"疑似崩溃/异常中断，自动修正为 INTERRUPTED 以允许恢复"
                    )
                    state.status = TaskStatus.INTERRUPTED.value

                if not state.can_resume():
                    raise ValueError(f"任务 {task_id} 状态为 {state.status}，无法恢复")

                state.status = TaskStatus.RUNNING.value
                state.resumed_at = datetime.now()
                state.resume_count += 1
                state.pause_reason = None

                resume_step = state.get_resume_step_number()
                state.current_step_number = resume_step
                state.update_timestamp()

                persist_success = await self._persist_task_state(state)
                if not persist_success:
                    error_msg = f"[SILENT_FAILURE_BLOCKED] 恢复任务时持久化失败: task_id={task_id}"
                    logger.error(error_msg)
                    raise CheckpointError(error_msg)

                self._trigger_callbacks("on_task_resumed", state)
                return state

        state = await _sync_op()

        checkpoint_info = ""
        if state.last_checkpoint_step:
            checkpoint = state.get_last_checkpoint()
            if checkpoint:
                checkpoint_info = f"，从断点 '{checkpoint.checkpoint_name}' (步骤 {checkpoint.step_number}) 恢复"

        logger.info(f"[CheckpointManager] 任务 {task_id} 已异步恢复，当前步骤: {state.current_step_number}{checkpoint_info}")

        # Phase 7.0 基建：断点恢复后回流记忆上下文
        bridge = _get_checkpoint_memory_bridge()
        if bridge:
            try:
                checkpoint_id = state.checkpoint_id or task_id
                await bridge.restore_workflow_checkpoint(checkpoint_id, user_id=state.user_id)
                logger.info(f"[CheckpointManager] 已触发记忆上下文回流: task_id={task_id}")
            except Exception as e:
                logger.warning(f"[CheckpointManager] 记忆上下文回流失败（非阻塞）: {e}")

        # 【修复】恢复对话历史到 DialogueManager 会话（断点续传上下文重建）
        _chat_history = state.global_context.get("chat_history", [])
        if _chat_history:
            try:
                from core.dialog.dialogue_manager import dialogue_manager
                # 优先使用传入的 session_id，否则回退到 user_id
                _session_id = session_id or state.user_id
                session = dialogue_manager._sessions.get(_session_id)
                if session and hasattr(session, 'chat_history') and not session.chat_history:
                    session.chat_history = _chat_history.copy()
                    logger.info(f"[CheckpointManager] 已恢复会话对话历史: {len(_chat_history)}条")
            except Exception as e:
                logger.debug(f"[CheckpointManager] 对话历史恢复注入失败（非阻塞）: {e}")

        return state

    async def get_task_progress(self, task_id: str) -> dict[str, Any]:
        """
        获取任务进度

        Args:
            task_id: 任务ID

        Returns:
            进度信息字典

        Raises:
            KeyError: 如果任务不存在
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                # 尝试从持久化加载
                state = await self._load_task_state_async(task_id)
                if state is None:
                    raise KeyError(f"任务 {task_id} 不存在")
            else:
                state = self._tasks[task_id]

            current_step = state.get_current_step()
            last_checkpoint = state.get_last_checkpoint()

            return {
                "task_id": state.task_id,
                "status": state.status,
                "progress_percentage": state.get_progress_percentage(),
                "completed_steps": state.completed_steps,
                "total_steps": state.total_steps,
                "current_step_number": state.current_step_number,
                "current_step_goal": current_step.step_goal if current_step else None,
                "last_checkpoint_step": state.last_checkpoint_step,
                "last_checkpoint_name": last_checkpoint.checkpoint_name if last_checkpoint else None,
                "can_resume": state.can_resume(),
                "resume_step_number": state.get_resume_step_number() if state.can_resume() else None,
                "resume_count": state.resume_count,
                "created_at": state.created_at.isoformat(),
                "updated_at": state.updated_at.isoformat(),
                "resumed_at": state.resumed_at.isoformat() if state.resumed_at else None
            }

    async def _persist_task_state_async(self, state: TaskExecutionState) -> bool:
        """
        异步持久化任务状态

        【修复BUG-3】内部正确 await 异步的 MemoryManager.store_memory，
        消除同步方法直接调用异步函数导致的未 await 问题。

        双存储策略：
        1. 优先使用 memory_manager 存储到 MEDIUM 层
        2. 降级到本地 JSONL 文件（仅在非强制模式下）
        3. 阶段锚点保存到PostgreSQL

        Args:
            state: 任务执行状态

        Returns:
            是否持久化成功

        Raises:
            CheckpointError: 强制PostgreSQL模式下存储失败时抛出
        """
        success = False
        last_error = None

        # 【修复新增】保存阶段锚点到PostgreSQL
        if state.phase_anchors:
            try:
                from core.memory.phase_anchor import get_phase_anchor_manager
                phase_anchor_manager = get_phase_anchor_manager()
                coros = []
                for anchor in state.phase_anchors:
                    coros.append(phase_anchor_manager.save(
                        phase=anchor.get("phase", "unknown"),
                        data=anchor.get("data", {}),
                        user_id=state.user_id,
                        task_id=state.task_id
                    ))
                if coros:
                    await asyncio.gather(*coros)
                logger.debug(f"[CheckpointManager] 阶段锚点已保存到PostgreSQL: {state.task_id}, 数量: {len(state.phase_anchors)}")
            except Exception as e:
                logger.error(f"[CheckpointManager] 保存阶段锚点到PostgreSQL失败: {e}", exc_info=True)

        # 阶段1: 尝试PostgreSQL存储（通过memory_manager）
        mem_mgr = self._get_memory_manager()
        if mem_mgr:
            try:
                from core.memory.memory_manager import MemoryLayer, MemoryType

                content = {
                    "record_type": "task_state",
                    "task_state": state.to_dict()
                }

                context = {
                    "task_id": state.task_id,
                    "user_id": state.user_id,
                    "status": state.status,
                    "completed_steps": state.completed_steps,
                    "total_steps": state.total_steps,
                    "source": "checkpoint_manager",
                    "phase_anchors_count": len(state.phase_anchors)
                }

                mem_id = await mem_mgr.store_memory(
                    layer=MemoryLayer.MEDIUM,
                    mem_type=MemoryType.EVENT,
                    content=content,
                    context=context,
                    scene=f"checkpoint_{state.task_id}",
                    rating=10 if state.status == TaskStatus.COMPLETED.value else 5,
                    expire_days=30
                )

                if mem_id:
                    logger.debug(f"[CheckpointManager] 任务状态已持久化到 memory_manager: {state.task_id}")
                    success = True

            except Exception as e:
                last_error = e
                diagnostic_except_handler(e, context="[CheckpointManager] memory_manager 存储失败", logger_instance=logger)

        # 阶段2: 处理失败情况
        if not success:
            if self._force_postgres:
                # 【关键】强制PostgreSQL模式：不降级，直接报错
                error_msg = (
                    f"[CHECKPOINT_CRITICAL] 强制PostgreSQL模式下存储失败，"
                    f"任务ID: {state.task_id}。错误: {last_error}\n"
                    f"系统配置禁止降级到本地存储，请检查PostgreSQL连接。"
                )
                logger.error(f"[SILENT_FAILURE_BLOCKED] {error_msg}")
                raise CheckpointError(error_msg) from last_error
            else:
                # 单实例模式允许降级
                try:
                    await asyncio.to_thread(self._save_to_jsonl, state)
                    success = True
                    logger.warning(
                        f"[CHECKPOINT_DEGRADED] 任务状态已降级保存到本地JSONL: "
                        f"{state.task_id}。注意：多实例环境可能导致数据不一致！"
                    )
                except Exception as e:
                    diagnostic_except_handler(e, context="[CheckpointManager] 本地存储也失败", logger_instance=logger)
                    raise CheckpointError(f"所有存储方式都失败: {e}") from e

        return success

    async def _persist_task_state(self, state: TaskExecutionState) -> bool:
        """
        持久化任务状态（异步版本）

        直接使用 await 调用异步的 _persist_task_state_async。
        """
        return await self._persist_task_state_async(state)

    def _save_to_jsonl(self, state: TaskExecutionState) -> None:
        """
        保存到本地 JSONL 文件

        Raises:
            CheckpointError: 保存失败
        """
        user_dir = self._checkpoint_dir / state.user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        file_path = user_dir / f"{state.task_id}.json"
        temp_path = file_path.with_suffix('.json.tmp')

        try:
            # 原子写入
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
                f.flush()
                import os as os_module
                os_module.fsync(f.fileno())

            # 重命名
            import os as os_module
            os_module.replace(temp_path, file_path)

            # 验证写入
            if not file_path.exists():
                raise OSError("文件写入验证失败")

        except Exception as e:
            # 清理临时文件
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except (OSError, PermissionError) as e:
                    logger.error(f"[CheckpointManager] 清理临时文件失败: {e}", exc_info=True)
                    # 不抛出异常，但必须记录错误
            raise CheckpointError(f"无法保存任务状态到本地: {e}") from e

    def _load_task_state(self, task_id: str) -> TaskExecutionState | None:
        """
        从持久化存储加载任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务执行状态对象，不存在则返回 None

        Raises:
            CheckpointError: 状态存在但加载/解析失败
        """
        task_state = None

        # 尝试从 memory_manager 加载
        mem_mgr = self._get_memory_manager()
        if mem_mgr:
            try:
                import asyncio

                from core.memory.memory_manager import MemoryLayer

                results = asyncio.get_event_loop().run_until_complete(
                    mem_mgr.retrieve_memory(
                        layer=MemoryLayer.MEDIUM,
                        scene=f"checkpoint_{task_id}",
                        limit=1
                    )
                )

                if results:
                    content = results[0].get("content", {})
                    if isinstance(content, str):
                        content = json.loads(content)

                    if content.get("record_type") == "task_state":
                        state_data = content.get("task_state", {})
                        task_state = TaskExecutionState.from_dict(state_data)
                        logger.debug(f"[CheckpointManager] 从 memory_manager 加载任务状态成功: {task_id}")

            except Exception as e:
                diagnostic_except_handler(e, context="[CheckpointManager] 从 memory_manager 加载失败", logger_instance=logger)

        # 如果 memory_manager 加载失败，降级到本地 JSONL 加载
        if task_state is None:
            file_found = False
            try:
                # 遍历用户目录查找任务文件
                for user_dir in self._checkpoint_dir.iterdir():
                    if user_dir.is_dir():
                        task_file = user_dir / f"{task_id}.json"
                        if task_file.exists():
                            file_found = True
                            with open(task_file, encoding='utf-8') as f:
                                data = json.load(f)

                            # 验证数据完整性
                            if not isinstance(data, dict):
                                raise CheckpointError(f"任务状态数据格式错误: 期望dict, 实际{type(data)}")

                            required_fields = ['task_id', 'user_id', 'total_steps', 'status']
                            missing = [f for f in required_fields if f not in data]
                            if missing:
                                raise CheckpointError(f"任务状态数据缺少必填字段: {missing}")

                            task_state = TaskExecutionState.from_dict(data)
                            logger.debug(f"[CheckpointManager] 从本地文件加载任务状态成功: {task_id}")
                            break

                # 没有找到文件 - 正常返回None
                if not file_found:
                    return None

            except CheckpointError:
                raise
            except Exception as e:
                diagnostic_except_handler(e, context="[CheckpointManager] 本地加载失败", logger_instance=logger)
                raise CheckpointError(f"无法加载任务状态 {task_id}: {e}") from e

        # 【修复新增】从PostgreSQL恢复阶段锚点
        if task_state is not None:
            try:
                from core.memory.phase_anchor import get_phase_anchor_manager
                phase_anchor_manager = get_phase_anchor_manager()
                postgres_anchors = phase_anchor_manager.get_by_task(task_id, limit=100)

                if postgres_anchors:
                    # 合并PostgreSQL中的阶段锚点（去重）
                    existing_phases = {a.get("phase") for a in task_state.phase_anchors}
                    for anchor in postgres_anchors:
                        if anchor.get("phase") not in existing_phases:
                            task_state.phase_anchors.append(anchor)

                    logger.info(f"[CheckpointManager] 从PostgreSQL恢复阶段锚点: {task_id}, 数量: {len(postgres_anchors)}")

            except Exception as e:
                logger.error(f"[CheckpointManager] 从PostgreSQL恢复阶段锚点失败: {e}", exc_info=True)
                # 不阻断主流程，继续使用已加载的任务状态

        return task_state

    async def _async_save(self, state: TaskExecutionState) -> bool:
        """
        异步保存任务状态

        Args:
            state: 任务执行状态

        Returns:
            是否保存成功

        Raises:
            CheckpointError: 保存失败时抛出，绝不静默返回 False
        """
        try:
            return await self._persist_task_state_async(state)
        except CheckpointError:
            raise
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 异步保存失败: {e}", exc_info=True)
            raise CheckpointError(f"异步保存任务状态失败: {e}") from e

    async def _load_task_state_async(self, task_id: str) -> TaskExecutionState | None:
        """从持久化存储异步加载任务状态（原生 async 路径）"""
        task_state = None

        # 尝试从 memory_manager 加载
        mem_mgr = self._get_memory_manager()
        if mem_mgr:
            try:
                from core.memory.memory_manager import MemoryLayer
                results = await mem_mgr.retrieve_memory(
                    layer=MemoryLayer.MEDIUM,
                    scene=f"checkpoint_{task_id}",
                    limit=1
                )
                if results:
                    content = results[0].get("content", {})
                    if isinstance(content, str):
                        content = json.loads(content)
                    if content.get("record_type") == "task_state":
                        state_data = content.get("task_state", {})
                        task_state = TaskExecutionState.from_dict(state_data)
                        logger.debug(f"[CheckpointManager] 从 memory_manager 异步加载任务状态成功: {task_id}")
            except Exception as e:
                diagnostic_except_handler(e, context="[CheckpointManager] 从 memory_manager 异步加载失败", logger_instance=logger)

        # 降级到本地 JSONL 加载（文件 I/O 用 to_thread）
        if task_state is None:
            def _load_from_disk():
                for user_dir in self._checkpoint_dir.iterdir():
                    if user_dir.is_dir():
                        task_file = user_dir / f"{task_id}.json"
                        if task_file.exists():
                            with open(task_file, encoding='utf-8') as f:
                                data = json.load(f)
                            if not isinstance(data, dict):
                                raise CheckpointError(f"任务状态数据格式错误: 期望dict, 实际{type(data)}")
                            required_fields = ['task_id', 'user_id', 'total_steps', 'status']
                            missing = [f for f in required_fields if f not in data]
                            if missing:
                                raise CheckpointError(f"任务状态数据缺少必填字段: {missing}")
                            return TaskExecutionState.from_dict(data)
                return None

            try:
                task_state = await asyncio.to_thread(_load_from_disk)
                if task_state:
                    logger.debug(f"[CheckpointManager] 从本地文件异步加载任务状态成功: {task_id}")
            except CheckpointError:
                raise
            except Exception as e:
                diagnostic_except_handler(e, context="[CheckpointManager] 本地异步加载失败", logger_instance=logger)
                raise CheckpointError(f"无法加载任务状态 {task_id}: {e}") from e

        # 从PostgreSQL恢复阶段锚点
        if task_state is not None:
            try:
                from core.memory.phase_anchor import get_phase_anchor_manager
                phase_anchor_manager = get_phase_anchor_manager()
                postgres_anchors = await phase_anchor_manager.get_by_task_async(task_id, limit=100)
                if postgres_anchors:
                    existing_phases = {a.get("phase") for a in task_state.phase_anchors}
                    for anchor in postgres_anchors:
                        if anchor.get("phase") not in existing_phases:
                            task_state.phase_anchors.append(anchor)
                    logger.info(f"[CheckpointManager] 从PostgreSQL异步恢复阶段锚点: {task_id}, 数量: {len(postgres_anchors)}")
            except Exception as e:
                logger.error(f"[CheckpointManager] 从PostgreSQL异步恢复阶段锚点失败: {e}", exc_info=True)

        return task_state

    async def _async_load(self, task_id: str) -> TaskExecutionState | None:
        """
        异步加载任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务执行状态对象，不存在则返回 None

        Raises:
            CheckpointError: 加载过程中发生异常时抛出，
            与"状态不存在返回None"严格区分
        """
        try:
            return await self._load_task_state_async(task_id)
        except CheckpointError:
            raise
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 异步加载失败: {e}", exc_info=True)
            raise CheckpointError(f"异步加载任务状态失败: {e}") from e

    async def save_checkpoint_with_confirmation(self, state: TaskExecutionState) -> bool:
        """
        保存检查点并确认写入成功

        【零静默失败】保存失败时抛出异常，绝不静默返回成功

        Args:
            state: 任务执行状态

        Returns:
            是否保存并确认成功

        Raises:
            CheckpointError: 所有重试都失败时抛出
        """
        import asyncio

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # 尝试保存
                # 【零静默失败】_async_save 失败时直接抛出 CheckpointError
                await self._async_save(state)

                # 确认写入：从数据库读取验证
                verified_state = await self._async_load(state.task_id)
                if verified_state and verified_state.checkpoint_id == state.checkpoint_id:
                    logger.info(f"[CheckpointManager] 检查点保存并确认成功: {state.task_id}")
                    return True
                else:
                    logger.warning(f"[CheckpointManager] 检查点保存后验证失败，尝试{attempt+1}/{max_retries}")
                    last_error = "保存后验证失败"

            except Exception as e:
                last_error = e
                logger.error(f"[SILENT_FAILURE_BLOCKED] 检查点保存尝试{attempt+1}失败: {e}")

            # 指数退避重试
            if attempt < max_retries - 1:
                await asyncio.sleep(0.1 * (2 ** attempt))

        # 所有重试失败
        error_msg = f"[CHECKPOINT_CRITICAL] 检查点保存失败（已重试{max_retries}次）: {last_error}"
        logger.error(f"[SILENT_FAILURE_BLOCKED] {error_msg}")
        raise CheckpointError(error_msg)

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    async def get_task(self, task_id: str) -> TaskExecutionState | None:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务执行状态对象，不存在则返回 None

        Raises:
            CheckpointError: 状态存在但加载失败
        """
        async with self._tasks_lock:
            if task_id in self._tasks:
                return self._tasks[task_id]

        # 尝试从持久化加载
        return await self._load_task_state_async(task_id)

    async def get_user_tasks(self, user_id: str,
                      status_filter: list[str] | None = None) -> list[TaskExecutionState]:
        """
        获取用户的所有任务

        Args:
            user_id: 用户ID
            status_filter: 状态过滤列表，None表示不过滤

        Returns:
            任务执行状态列表
        """
        tasks = []

        # 【死锁修复】统一锁获取顺序：先 _tasks_lock 后 _user_tasks_lock
        async with self._tasks_lock:
            async with self._user_tasks_lock:
                task_ids = self._user_tasks.get(user_id, [])

            # 在锁内获取所有任务状态
            for task_id in task_ids:
                try:
                    state = self._tasks.get(task_id)
                    if state and (status_filter is None or state.status in status_filter):
                        tasks.append(state)
                except Exception as e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 加载用户任务失败 {task_id}: {e}")

        return tasks

    def list_checkpoints(self, task_id: str) -> list[dict[str, Any]]:
        """
        获取任务的所有断点

        Args:
            task_id: 任务ID

        Returns:
            断点信息列表
        """
        try:
            state = self.get_task(task_id)
            if not state:
                return []
        except CheckpointError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 获取断点列表失败 {task_id}: {e}")
            return []

        checkpoints = []
        for step in state.steps:
            if step.is_checkpoint:
                checkpoints.append({
                    "step_number": step.step_number,
                    "checkpoint_name": step.checkpoint_name,
                    "step_goal": step.step_goal,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None
                })

        return sorted(checkpoints, key=lambda x: x["step_number"])

    # ═══════════════════════════════════════════════════════════════
    # 管理接口
    # ═══════════════════════════════════════════════════════════════

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            是否删除成功
        """
        async with self._tasks_lock:
            if task_id not in self._tasks:
                logger.warning(f"[CheckpointManager] 任务 {task_id} 不存在，无法删除")
                return False

            state = self._tasks[task_id]
            user_id = state.user_id

            # 从内存中移除
            del self._tasks[task_id]

            # 从用户索引中移除
            async with self._user_tasks_lock:
                if user_id in self._user_tasks and task_id in self._user_tasks[user_id]:
                    self._user_tasks[user_id].remove(task_id)

        # 删除本地文件
        try:
            user_dir = self._checkpoint_dir / user_id
            task_file = user_dir / f"{task_id}.json"
            if task_file.exists():
                task_file.unlink()
        except Exception as e:
            logger.warning(f"[CheckpointManager] 删除本地文件失败: {e}")

        logger.info(f"[CheckpointManager] 任务 {task_id} 已删除")
        return True

    async def cleanup_completed_tasks(self, user_id: str | None = None,
                               before_days: int = 7) -> int:
        """
        清理已完成的任务

        Args:
            user_id: 用户ID，None表示清理所有用户
            before_days: 清理该天数之前完成的任务

        Returns:
            清理的任务数量
        """
        cutoff = datetime.now() - __import__('datetime').timedelta(days=before_days)
        count = 0

        async with self._tasks_lock:
            tasks_to_delete = []

            for task_id, state in self._tasks.items():
                if user_id and state.user_id != user_id:
                    continue

                if state.status == TaskStatus.COMPLETED.value and state.updated_at < cutoff:
                    tasks_to_delete.append(task_id)

            for task_id in tasks_to_delete:
                await self.delete_task(task_id)
                count += 1

        logger.info(f"[CheckpointManager] 清理 {count} 个已完成任务")
        return count

    async def get_stats(self) -> dict[str, Any]:
        """获取管理器统计信息"""
        async with self._tasks_lock:
            total_tasks = len(self._tasks)
            status_counts = {}
            for state in self._tasks.values():
                status_counts[state.status] = status_counts.get(state.status, 0) + 1

        async with self._user_tasks_lock:
            total_users = len(self._user_tasks)

        return {
            "total_tasks_in_memory": total_tasks,
            "total_users": total_users,
            "status_distribution": status_counts,
            "checkpoint_dir": str(self._checkpoint_dir)
        }


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

checkpoint_manager = None

try:
    checkpoint_manager = CheckpointManager()
    logger.info("【成功】 CheckpointManager (断点续传管理器) 初始化成功")
except Exception as e:
    logger.error(f"[SILENT_FAILURE_BLOCKED] CheckpointManager 初始化失败: {e}", exc_info=True)
    raise RuntimeError(f"CheckpointManager 初始化失败: {e}") from e


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_checkpoint_manager() -> CheckpointManager | None:
    """获取断点续传管理器实例"""
    return checkpoint_manager


async def create_task_with_auto_id(user_id: str, total_steps: int,
                             global_context: dict[str, Any] | None = None) -> TaskExecutionState:
    """
    使用自动生成的任务ID创建任务

    Args:
        user_id: 用户ID
        total_steps: 总步骤数
        global_context: 全局上下文

    Returns:
        任务执行状态对象

    Raises:
        RuntimeError: CheckpointManager 未初始化
        CheckpointError: 创建任务失败
    """
    if checkpoint_manager is None:
        raise RuntimeError("CheckpointManager 未初始化")

    task_id = f"task_{user_id}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return await checkpoint_manager.create_task(task_id, user_id, total_steps, global_context)


# ═══════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件是 SiliconBase V5 系统"断点续传"功能的第一阶段实现，
# 提供任务执行状态的完整生命周期管理。
#
# 【核心组件】
# 1. ExecutionStep: 执行步骤数据类，记录单个步骤的完整信息
# 2. TaskExecutionState: 任务执行状态类，管理整个任务的进度
# 3. CheckpointManager: 断点管理器，提供创建/暂停/恢复等核心API
#
# 【断点续传流程】
#   create_task() -> start_step() -> [执行工具] -> complete_step()
#   -> [可选: save_checkpoint()] -> [暂停: pause_task()] -> resume_task() -> ...
#
# 【存储架构】
#   内存缓存: _tasks Dict 提供快速访问
#   持久化: memory_manager MEDIUM 层（优先）
#   降级: 本地 JSONL 文件
#
# 【使用入口】
#   from core.agent.checkpoint_manager import checkpoint_manager
#   state = checkpoint_manager.resume_task("task_001")  # 断点续传
#
# ═══════════════════════════════════════════════════════════════
