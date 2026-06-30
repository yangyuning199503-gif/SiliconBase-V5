#!/usr/bin/env python3
r"""
3槽位长任务管理器
符合大纲：长期任务的3个面板，独立运行，AI可查看/修改/暂停/恢复

【核心特性】
- 固定3个槽位（slot_id: 1, 2, 3），对应大纲要求的3个面板
- 每个槽位独立运行，互不干扰
- AI可查看所有槽位状态
- AI可修改槽位参数（需确认）
- 用户可暂停/恢复槽位任务
- 恢复时必须AI确认百分百理解需求（大纲第5条规则）

【槽位状态流转】
IDLE -> RUNNING -> PAUSED -> RUNNING -> IDLE
              \-> ERROR -> IDLE

作者: Fix-Agent-P0-4a
日期: 2026-03-04
"""

import asyncio
import contextlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.diagnostic import safe_create_task
from core.logger import logger

# 新增导入 - 用于连接AgentLoop
from core.task.task_queue import Task

# 【蓝屏修复】延迟导入避免循环导入
# from core.agent.agent_loop import run_agent_loop  # 改为在方法内部延迟导入


class SlotStatus(Enum):
    """槽位任务状态枚举"""
    IDLE = "idle"           # 空闲 - 槽位可用
    RUNNING = "running"     # 运行中 - 任务正在执行
    PAUSED = "paused"       # 已暂停 - 用户暂停，等待恢复
    ERROR = "error"         # 错误 - 任务执行出错
    PREEMPTED = "preempted" # 【P2修复】被抢占 - 任务被更高优先级任务抢占


class TaskPriority(Enum):
    """
    【P2修复】任务优先级枚举

    用于槽位抢占策略:
    - LOW: 低优先级任务，可被NORMAL/HIGH/CRITICAL抢占
    - NORMAL: 普通优先级，可被HIGH/CRITICAL抢占
    - HIGH: 高优先级，可被CRITICAL抢占
    - CRITICAL: 关键任务，不可被抢占
    """
    LOW = 1      # 低优先级
    NORMAL = 2   # 普通优先级
    HIGH = 3     # 高优先级
    CRITICAL = 4 # 关键优先级（不可抢占）


class TaskPhase(Enum):
    """
    任务执行阶段枚举

    用于自动进度估算和阶段锚点跟踪
    """
    ANALYZING = "analyzing"     # 分析阶段 (0-20%)
    PLANNING = "planning"       # 规划阶段 (20-40%)
    EXECUTING = "executing"     # 执行阶段 (40-80%)
    VERIFYING = "verifying"     # 验证阶段 (80-100%)
    COMPLETED = "completed"     # 完成 (100%)


@dataclass
class SlotTask:
    """槽位任务数据结构"""
    slot_id: int                            # 槽位ID (1, 2, 3)
    task_id: str                            # 任务唯一标识
    task_name: str                          # 任务名称
    task_type: str                          # 任务类型
    params: dict[str, Any]                  # 任务参数
    status: SlotStatus                      # 当前状态
    progress: float                         # 进度 0-100
    created_at: float                       # 创建时间戳
    updated_at: float                       # 更新时间戳
    started_at: float | None = None      # 开始执行时间
    paused_at: float | None = None       # 暂停时间
    resumed_at: float | None = None      # 恢复时间
    completed_at: float | None = None    # 完成时间
    ai_understanding: str | None = None  # AI理解确认内容
    user_requirements: str | None = None # 用户需求描述
    error_message: str | None = None     # 错误信息
    result: dict[str, Any] | None = None # 执行结果
    timeout: int = 3600                     # 任务超时时间（秒），默认3600秒
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据
    # 【P1修复】自动进度更新相关字段
    current_phase: TaskPhase = TaskPhase.ANALYZING  # 当前执行阶段
    phase_start_time: float | None = None        # 当前阶段开始时间
    estimated_rounds: int = 10                      # 预估总轮次
    current_round: int = 0                          # 当前轮次
    # 【P2修复】优先级和抢占相关字段
    priority: TaskPriority = TaskPriority.NORMAL    # 任务优先级，默认NORMAL
    preempted_by: str | None = None              # 被哪个任务抢占
    waiting_since: float | None = None           # 进入等待队列的时间

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（用于API响应）"""
        return {
            "slot_id": self.slot_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_type": self.task_type,
            "params": self.params,
            "status": self.status.value,
            "progress": round(self.progress, 2),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "paused_at": self.paused_at,
            "resumed_at": self.resumed_at,
            "completed_at": self.completed_at,
            "ai_understanding": self.ai_understanding,
            "user_requirements": self.user_requirements,
            "error_message": self.error_message,
            "result": self.result,
            "timeout": self.timeout,
            "metadata": self.metadata,
            # 【P1修复】添加进度阶段信息
            "current_phase": self.current_phase.value if self.current_phase else None,
            "current_round": self.current_round,
            "estimated_rounds": self.estimated_rounds
        }


class LongTaskSlots:
    """
    3槽位长任务管理器

    管理3个独立的长任务槽位，支持创建、暂停、恢复、修改等操作。
    符合大纲第5条规则：恢复时必须AI确认百分百理解需求。

    【P1修复】自动进度更新
    - 支持基于阶段的进度估算
    - 支持基于轮次的进度估算
    - 在AgentLoop回调中自动更新进度
    """

    MAX_SLOTS = 3  # 最大槽位数（大纲要求3个面板）

    # 【P1修复】阶段到进度范围的映射
    PHASE_PROGRESS_MAP = {
        TaskPhase.ANALYZING: (0, 20),
        TaskPhase.PLANNING: (20, 40),
        TaskPhase.EXECUTING: (40, 80),
        TaskPhase.VERIFYING: (80, 100),
        TaskPhase.COMPLETED: (100, 100)
    }

    # 【P1修复】阶段显示名称（中文）
    PHASE_DISPLAY_NAMES = {
        TaskPhase.ANALYZING: "分析中",
        TaskPhase.PLANNING: "规划中",
        TaskPhase.EXECUTING: "执行中",
        TaskPhase.VERIFYING: "验证中",
        TaskPhase.COMPLETED: "已完成"
    }

    def __init__(self):
        """初始化3槽位管理器"""
        # 初始化3个槽位，初始状态为None（空闲）
        self._slots: dict[int, SlotTask | None] = {1: None, 2: None, 3: None}
        # 使用RLock确保线程安全（支持同线程内重入）
        self._lock = threading.RLock()
        # 【新增】槽位级锁 - 用于保护每个槽位的状态变更
        self._slot_locks: dict[int, threading.RLock] = {}
        # 【新增】全局锁 - 用于保护_slot_locks字典的访问
        self._global_lock = threading.RLock()
        # 状态变更回调列表（用于WebSocket推送）
        self._callbacks: list[Callable[[int, SlotTask, str], None]] = []
        # 任务执行器字典（槽位ID -> 执行线程）
        self._executors: dict[int, threading.Thread] = {}
        # 【超时机制】超时监控线程字典（槽位ID -> 监控线程）
        self._timeout_monitors: dict[int, threading.Thread] = {}
        # 【超时机制】超时标志字典（槽位ID -> 超时标志）
        self._timeout_flags: dict[int, bool] = {}
        # 【P1修复】进度更新标志字典（槽位ID -> 更新标志）
        self._progress_update_flags: dict[int, bool] = {}
        # 【P2修复】等待队列 - 存储等待执行的任务
        self._waiting_queue: list[SlotTask] = []
        # 【P2修复】等待队列锁
        self._waiting_queue_lock = threading.RLock()

        logger.info("[LongTaskSlots] 3槽位长任务管理器初始化完成")

    def _generate_task_id(self) -> str:
        """生成唯一任务ID"""
        return f"longtask_{uuid.uuid4().hex[:16]}_{int(time.time())}"

    def _notify_callbacks(self, slot_id: int, task: SlotTask | None, event: str):
        """通知所有注册的回调函数"""
        for callback in self._callbacks:
            try:
                callback(slot_id, task, event)
            except Exception as e:
                logger.error(f"[LongTaskSlots] 回调执行失败 slot={slot_id}: {e}")

    def _is_valid_slot(self, slot_id: int) -> bool:
        """检查槽位ID是否有效"""
        return isinstance(slot_id, int) and 1 <= slot_id <= self.MAX_SLOTS

    def _get_slot_lock(self, slot_id: int) -> threading.RLock:
        """
        【新增】获取槽位级锁

        为每个槽位提供独立的锁，避免不同槽位之间的竞争，
        同时确保同一线程可以重入。

        Args:
            slot_id: 槽位ID

        Returns:
            threading.RLock: 槽位级锁
        """
        with self._global_lock:
            if slot_id not in self._slot_locks:
                self._slot_locks[slot_id] = threading.RLock()
            return self._slot_locks[slot_id]

    # ═══════════════════════════════════════════════════════════
    # 【P1修复】自动进度更新方法
    # ═══════════════════════════════════════════════════════════

    def _update_auto_progress(self, slot_id: int, phase: TaskPhase = None,
                              current_round: int = None, estimated_rounds: int = None):
        """
        【P1修复】自动更新槽位任务进度

        根据当前阶段和轮次自动估算进度，无需外部显式调用update_progress

        进度阶段定义:
        - analyzing: 分析阶段 (0-20%)
        - planning: 规划阶段 (20-40%)
        - executing: 执行阶段 (40-80%)
        - verifying: 验证阶段 (80-100%)

        Args:
            slot_id: 槽位ID
            phase: 当前执行阶段（可选，不传则使用当前阶段）
            current_round: 当前轮次（可选）
            estimated_rounds: 预估总轮次（可选）

        Returns:
            float: 更新后的进度值 (0-100)
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return 0.0

            task = self._slots[slot_id]
            if task is None or task.status != SlotStatus.RUNNING:
                return 0.0

            # 更新阶段信息
            if phase is not None:
                task.current_phase = phase
                task.phase_start_time = time.time()

            # 更新轮次信息
            if current_round is not None:
                task.current_round = current_round
            if estimated_rounds is not None:
                task.estimated_rounds = max(1, estimated_rounds)  # 至少1轮

            # 计算基于阶段的进度
            phase_progress = self._calculate_phase_progress(task)

            # 计算基于轮次的进度
            round_progress = self._calculate_round_progress(task)

            # 综合进度：阶段进度占60%，轮次进度占40%
            # 这样可以在阶段切换时平滑过渡，同时反映实际执行进度
            combined_progress = phase_progress * 0.6 + round_progress * 0.4

            # 限制在0-100范围内
            task.progress = max(0.0, min(99.9, combined_progress))  # 运行时最大99.9%，完成时才100%
            task.updated_at = time.time()

            # 通知进度更新
            self._notify_callbacks(slot_id, task, "progress_updated")

            logger.debug(f"[LongTaskSlots] 槽位{slot_id}自动进度更新: {task.progress:.1f}%, "
                        f"阶段: {self.PHASE_DISPLAY_NAMES.get(task.current_phase, 'unknown')}, "
                        f"轮次: {task.current_round}/{task.estimated_rounds}")

            return task.progress

    def _calculate_phase_progress(self, task: SlotTask) -> float:
        """
        【P1修复】基于当前阶段计算进度

        Args:
            task: 槽位任务对象

        Returns:
            float: 基于阶段的进度值 (0-100)
        """
        phase_range = self.PHASE_PROGRESS_MAP.get(task.current_phase, (0, 20))
        phase_min, phase_max = phase_range

        # 如果阶段刚开始，返回阶段最小值
        if task.phase_start_time is None:
            return float(phase_min)

        # 计算在当前阶段停留的时间
        elapsed_in_phase = time.time() - task.phase_start_time

        # 预估每个阶段的典型持续时间（秒）
        typical_phase_duration = {
            TaskPhase.ANALYZING: 30,   # 分析阶段预计30秒
            TaskPhase.PLANNING: 20,    # 规划阶段预计20秒
            TaskPhase.EXECUTING: 120,  # 执行阶段预计2分钟
            TaskPhase.VERIFYING: 15,   # 验证阶段预计15秒
            TaskPhase.COMPLETED: 1
        }

        duration = typical_phase_duration.get(task.current_phase, 30)

        # 根据时间计算阶段内进度（0-1）
        phase_ratio = min(1.0, elapsed_in_phase / duration)

        # 计算实际进度
        progress = phase_min + (phase_max - phase_min) * phase_ratio
        return progress

    def _calculate_round_progress(self, task: SlotTask) -> float:
        """
        【P1修复】基于轮次计算进度

        Args:
            task: 槽位任务对象

        Returns:
            float: 基于轮次的进度值 (0-100)
        """
        if task.estimated_rounds <= 0:
            return 50.0  # 默认值

        # 基于轮次的简单线性进度
        round_ratio = min(1.0, task.current_round / task.estimated_rounds)
        return round_ratio * 100.0

    def set_task_phase(self, slot_id: int, phase: TaskPhase) -> bool:
        """
        【P1修复】设置槽位任务的当前阶段

        供AgentLoop回调调用，用于更新任务执行阶段

        Args:
            slot_id: 槽位ID
            phase: 执行阶段

        Returns:
            bool: 是否成功更新
        """
        try:
            self._update_auto_progress(slot_id, phase=phase)
            logger.info(f"[LongTaskSlots] 槽位{slot_id}阶段更新: {self.PHASE_DISPLAY_NAMES.get(phase, phase.value)}")
            return True
        except Exception as e:
            logger.error(f"[LongTaskSlots] 设置槽位{slot_id}阶段失败: {e}")
            return False

    def update_task_round(self, slot_id: int, current_round: int, estimated_rounds: int = None) -> bool:
        """
        【P1修复】更新槽位任务的当前轮次

        供AgentLoop回调调用，用于基于轮次估算进度

        Args:
            slot_id: 槽位ID
            current_round: 当前轮次
            estimated_rounds: 预估总轮次（可选）

        Returns:
            bool: 是否成功更新
        """
        try:
            self._update_auto_progress(
                slot_id,
                current_round=current_round,
                estimated_rounds=estimated_rounds
            )
            return True
        except Exception as e:
            logger.error(f"[LongTaskSlots] 更新槽位{slot_id}轮次失败: {e}")
            return False

    def get_progress_status_text(self, slot_id: int) -> str:
        """
        【P1修复】获取进度状态文本

        用于前端显示，如"分析中 - 15%"、"执行中 - 第3轮/预计10轮"

        Args:
            slot_id: 槽位ID

        Returns:
            str: 进度状态文本
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return "无效槽位"

            task = self._slots[slot_id]
            if task is None:
                return "槽位空闲"

            if task.status == SlotStatus.IDLE:
                return "已完成"
            elif task.status == SlotStatus.ERROR:
                return "执行出错"
            elif task.status == SlotStatus.PAUSED:
                return "已暂停"

            # 构建状态文本
            phase_name = self.PHASE_DISPLAY_NAMES.get(task.current_phase, "执行中")
            progress_pct = round(task.progress, 1)

            # 如果是执行阶段，显示轮次信息
            if task.current_phase == TaskPhase.EXECUTING and task.current_round > 0:
                return f"{phase_name} - {progress_pct}% (第{task.current_round}轮/{task.estimated_rounds}轮)"
            else:
                return f"{phase_name} - {progress_pct}%"

    async def _extract_and_store_experience(self, task: SlotTask, user_id: str) -> None:
        """
        【2026-03-22 关键修复】长任务完成后提取并存储经验

        从完成的槽位任务中提取经验，并存储到L3/L4记忆层：
        - L3 (medium): 一般经验和失败教训
        - L4 (evolve): 高质量经验 (>0.8分)

        Args:
            task: 槽位任务对象
            user_id: 用户ID
        """
        try:
            from core.memory.memory_manager import MemoryLayer, MemoryType, memory_manager

            # 直接保存原始任务执行记录（不再经过硬编码模板萃取）
            experience_content = {
                'task_id': task.task_id,
                'task_name': task.task_name,
                'task_type': task.task_type,
                'success': task.status == SlotStatus.IDLE and task.progress >= 100.0,
                'progress': task.progress,
                'params': task.params,
                'user_requirements': task.user_requirements,
                'duration': (task.completed_at - task.started_at) if task.started_at and task.completed_at else 0,
                'recorded_at': time.time()
            }

            mem_id = memory_manager.store_memory(
                layer=MemoryLayer.MEDIUM,
                mem_type=MemoryType.EXPERIENCE,
                content=experience_content,
                context={
                    'task_id': task.task_id,
                    'user_id': user_id,
                    'slot_id': task.slot_id,
                    'source': 'long_task_slots'
                },
                scene=f"longtask_experience_{task.task_id}",
                rating=5,
                expire_days=30
            )
            if mem_id:
                logger.debug(f"[LongTaskSlots] 经验已存储到L3: {mem_id[:8]}...")

            # 成功任务额外升 L4
            if task.status == SlotStatus.IDLE and task.progress >= 100.0:
                mem_id = memory_manager.store_memory(
                    layer=MemoryLayer.EVOLVE,
                    mem_type=MemoryType.KNOWLEDGE,
                    content=experience_content,
                    context={
                        'task_id': task.task_id,
                        'user_id': user_id,
                        'slot_id': task.slot_id,
                        'is_high_quality': True,
                        'source': 'long_task_slots'
                    },
                    scene=f"longtask_knowledge_{task.task_id}",
                    rating=5,
                    expire_days=365
                )
                if mem_id:
                    logger.info(f"[LongTaskSlots] 成功任务经验已存储到L4: {mem_id[:8]}...")

        except ImportError as e:
            logger.warning(f"[LongTaskSlots] 经验存储模块未就绪: {e}")
        except Exception as e:
            logger.error(f"[LongTaskSlots] 经验存储失败: {e}")

    def _execute_slot_task(self, slot_id: int, task: SlotTask):
        """
        在后台线程中执行槽位任务 - 连接槽位系统与AgentLoop的桥梁

        【关键修复】使用槽位级锁保护状态变更，遵循零静默失败原则：
        - 状态异常时记录ERROR日志并抛出异常
        - 执行失败时更新状态为ERROR，不静默忽略
        - 所有异常路径都有明确日志

        【超时机制】防止任务死循环或卡住导致槽位被永久占用：
        - 支持从配置读取默认超时: config.get("task.slot_timeout", 3600)
        - 使用监控线程定期检查执行时间
        - 超时后强制终止任务并更新状态为ERROR

        【P1修复】自动进度更新
        - 在AgentLoop回调中更新进度
        - 添加阶段锚点跟踪（分析中->规划中->执行中->验证中）
        - 支持根据轮次估算进度
        """
        # 【超时机制】获取超时时间（从任务配置或全局配置）
        try:
            from core.config import config
            default_timeout = config.get("task.slot_timeout", 3600)
        except Exception:
            default_timeout = 3600
        timeout = getattr(task, "timeout", None) or default_timeout

        # 【超时机制】初始化超时标志
        self._timeout_flags[slot_id] = False

        # 【P1修复】初始化自动进度更新标志
        self._progress_update_flags: dict[int, bool] = getattr(self, '_progress_update_flags', {})
        self._progress_update_flags[slot_id] = True

        async def run_task_async():
            """【Phase 7.5】异步执行槽位任务"""
            # 【关键】获取槽位级锁，确保线程安全
            slot_lock = self._get_slot_lock(slot_id)

            with slot_lock:
                try:
                    # 【零静默失败】状态检查 - 确保任务处于可执行状态
                    if task.status != SlotStatus.RUNNING:
                        logger.error(
                            f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务状态异常: "
                            f"期望RUNNING，实际{task.status}"
                        )
                        raise RuntimeError(f"任务状态异常，无法执行: {task.status}")

                    logger.info(f"[LongTaskSlots] 开始执行槽位{slot_id}任务: {task.task_id}")

                    # 【P1修复】初始化阶段和进度
                    task.current_phase = TaskPhase.ANALYZING
                    task.phase_start_time = time.time()
                    task.current_round = 0
                    task.estimated_rounds = 10
                    task.status = SlotStatus.RUNNING
                    task.started_at = time.time()
                    self._notify_callbacks(slot_id, task, "started")
                except Exception as e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务启动异常: {e}")
                    task.status = SlotStatus.ERROR
                    task.error_message = str(e)
                    self._notify_callbacks(slot_id, task, "error")
                    if slot_id in self._executors:
                        del self._executors[slot_id]
                    return

            # 【Phase 7.5】启动自动进度更新协程和超时监控协程
            progress_task = asyncio.create_task(
                self._auto_progress_updater_async(slot_id, task)
            )
            timeout_task = asyncio.create_task(
                self._start_timeout_monitor_async(slot_id, timeout, task.started_at)
            )

            # 【关键】任务执行阶段在锁外进行，避免长时间持有锁
            final_answer = None
            working_memory = None
            execution_error = None
            start_time = time.time()

            try:
                # 【超时机制】检查是否已超时
                if self._timeout_flags.get(slot_id, False):
                    raise TimeoutError(f"任务执行超时({timeout}s)")

                # 检测工作流任务类型
                if task.task_type == "workflow":
                    # 【工作流模式】使用 WorkflowExecutor 执行工作流
                    logger.info(f"[LongTaskSlots] 槽位{slot_id}检测到工作流任务，切换到工作流执行模式")
                    try:
                        from core.workflow.workflow_executor import WorkflowExecutor
                        executor = WorkflowExecutor()

                        # 获取工作流执行ID
                        execution_id = task.metadata.get("execution_id") if task.metadata else None
                        if not execution_id:
                            execution_id = task.params.get("execution_id") if task.params else None

                        if execution_id:
                            # 【P1修复】更新阶段为执行中
                            self.set_task_phase(slot_id, TaskPhase.EXECUTING)

                            # 【Phase 7.5】直接 await 工作流异步模式执行
                            result = await executor.run_workflow_mode_async(
                                execution_id=execution_id,
                                user_id=task.metadata.get("user_id", "default") if task.metadata else "default",
                                voice_instance=None,
                                chat_history=[]
                            )

                            if result.get("success"):
                                final_answer = result.get("variables", {}).get("final_answer", "工作流执行完成")
                            else:
                                final_answer = f"工作流执行失败: {result.get('error', '未知错误')}"
                                execution_error = RuntimeError(final_answer)

                            logger.info(f"[LongTaskSlots] 槽位{slot_id}工作流执行完成: {execution_id}")

                            # 【超时机制】检查是否已超时
                            if time.time() - start_time > timeout or self._timeout_flags.get(slot_id, False):
                                raise TimeoutError(f"任务执行超时({timeout}s)")
                        else:
                            error_msg = "工作流任务缺少 execution_id"
                            logger.error(f"[LongTaskSlots] {error_msg}")
                            execution_error = RuntimeError(error_msg)
                    except Exception as e:
                        logger.error(f"[LongTaskSlots] 工作流执行异常: {e}", exc_info=True)
                        execution_error = e
                        final_answer = f"工作流执行异常: {str(e)}"
                else:
                    # 【普通模式】创建 TaskQueue 可用的 Task 对象
                    task_obj = Task(
                        type="long_task",
                        intent={
                            "raw": task.user_requirements or task.task_name,
                            "task_name": task.task_name,
                            "task_type": task.task_type,
                            "slot_id": slot_id
                        },
                        session_id=f"slot_{slot_id}_{task.task_id}",
                        metadata={
                            "slot_id": slot_id,
                            "slot_task_id": task.task_id,
                            "is_pausable": True,
                            "is_pausable_task": True,  # 【修复】添加正确的key名，兼容AgentLoop检查
                            "source": "long_task_slots"
                        }
                    )

                    # 【P1修复】创建进度回调函数供AgentLoop调用
                    def progress_callback(round_num: int, max_rounds: int, context: dict = None):
                        """
                        AgentLoop进度回调函数

                        Args:
                            round_num: 当前轮次
                            max_rounds: 最大轮次
                            context: 额外上下文，可包含phase等信息
                        """
                        try:
                            # 根据轮次确定阶段
                            phase = TaskPhase.EXECUTING
                            if round_num == 0:
                                phase = TaskPhase.ANALYZING
                            elif round_num == 1:
                                phase = TaskPhase.PLANNING
                            elif round_num >= max_rounds - 2:
                                phase = TaskPhase.VERIFYING

                            # 如果context中指定了phase，优先使用
                            if context and "phase" in context:
                                phase_str = context["phase"]
                                with contextlib.suppress(ValueError):
                                    phase = TaskPhase(phase_str)

                            self._update_auto_progress(
                                slot_id,
                                phase=phase,
                                current_round=round_num,
                                estimated_rounds=max_rounds
                            )
                        except Exception as e:
                            # 【静默失败修复】回调异常必须是ERROR级别
                            logger.error(f"[LongTaskSlots] 进度回调异常: {e}", exc_info=True)

                    # 将回调函数存入任务metadata，供AgentLoop获取
                    task.metadata["_progress_callback"] = progress_callback

                    # 【P1修复】更新阶段为规划中
                    self.set_task_phase(slot_id, TaskPhase.PLANNING)

                    # 【蓝屏修复】延迟导入避免循环导入
                    from core.agent.agent_loop import run_agent_loop_async

                    # 【恢复机制】从 metadata 读取恢复参数
                    resume_from_checkpoint = task.metadata.get("_resume_from_checkpoint", False) if task.metadata else False
                    original_task_id = task.metadata.get("_original_task_id", None) if task.metadata else None

                    # 【Phase 7.5】直接 await AgentLoop 异步执行任务
                    try:
                        final_answer, working_memory = await run_agent_loop_async(
                            task=task_obj,
                            max_rounds=100,
                            chat_history=[],
                            chat_count=0,
                            session_id=task_obj.session_id,
                            db_session_id=None,
                            voice_instance=None,
                            mode="daily",
                            resume_from_checkpoint=resume_from_checkpoint,
                            task_id=original_task_id
                        )
                    except Exception as e:
                        logger.error(f"[LongTaskSlots] run_agent_loop_async 执行异常: {e}", exc_info=True)
                        raise

                    # 【超时机制】检查是否已超时
                    if time.time() - start_time > timeout or self._timeout_flags.get(slot_id, False):
                        raise TimeoutError(f"任务执行超时({timeout}s)")

            except TimeoutError as e:
                # 【超时机制】捕获超时异常
                execution_error = e
                logger.error(f"[TIMEOUT] 槽位{slot_id}任务执行超时: {e}")
            except Exception as e:
                # 【零静默失败】捕获执行异常
                execution_error = e
                logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务执行异常: {e}")
            finally:
                # 【P1修复】停止自动进度更新
                self._progress_update_flags[slot_id] = False
                # 【Phase 7.5】取消辅助协程
                for t in (progress_task, timeout_task):
                    if not t.done():
                        t.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await t

            # 【关键】重新获取锁以更新最终状态
            with slot_lock:
                try:
                    if execution_error:
                        # 【零静默失败】执行失败时更新状态为ERROR
                        task.status = SlotStatus.ERROR
                        task.error_message = str(execution_error)
                        self._notify_callbacks(slot_id, task, "error")
                    elif final_answer:
                        # 【P1修复】更新阶段为已完成
                        task.current_phase = TaskPhase.COMPLETED
                        task.progress = 100.0

                        # 任务完成，更新槽位状态
                        # 从task metadata获取user_id，如果没有则使用default_user
                        task_user_id = task.metadata.get("user_id", "default_user") if task.metadata else "default_user"
                        await self.complete_task(slot_id, {
                            "answer": final_answer,
                            "success": True
                        }, task_user_id)
                        logger.info(f"[LongTaskSlots] 槽位{slot_id}任务完成")
                    else:
                        # 【零静默失败】无执行结果时标记为错误
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务执行未完成，无返回结果")
                        self.set_task_error(slot_id, "任务执行未完成")
                except Exception as e:
                    # 【零静默失败】状态更新异常
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务状态更新异常: {e}")
                    try:
                        task.status = SlotStatus.ERROR
                        task.error_message = f"状态更新失败: {str(e)}"
                        self._notify_callbacks(slot_id, task, "error")
                    except Exception as inner_e:
                        # [SILENT_FAILURE_BLOCKED] 状态更新失败必须记录，不能静默
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}任务状态标记为ERROR失败: {inner_e}")
                finally:
                    # 清理执行线程引用
                    if slot_id in self._executors:
                        del self._executors[slot_id]

        # 【Phase 7.5】启动后台线程执行异步任务
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_task_async())
            finally:
                loop.close()

        executor_thread = threading.Thread(target=run_in_thread, daemon=True)
        executor_thread.start()

        # 保存执行线程引用
        self._executors[slot_id] = executor_thread

        logger.info(f"[LongTaskSlots] 槽位{slot_id}任务执行线程已启动，超时时间: {timeout}s")

    def _auto_progress_updater(self, slot_id: int, task: SlotTask):
        """
        【P1修复】自动进度更新线程（同步版本，保留兼容）

        定期自动更新任务进度，即使AgentLoop没有主动回调

        Args:
            slot_id: 槽位ID
            task: 槽位任务对象
        """
        logger.info(f"[LongTaskSlots] 槽位{slot_id}自动进度更新线程已启动")

        update_interval = 5  # 每5秒更新一次

        while self._progress_update_flags.get(slot_id, False):
            try:
                time.sleep(update_interval)

                # 检查是否需要停止
                if not self._progress_update_flags.get(slot_id, False):
                    break

                # 检查任务状态
                with self._lock:
                    current_task = self._slots.get(slot_id)
                    if current_task is None or current_task.status != SlotStatus.RUNNING:
                        break

                # 自动更新进度
                self._update_auto_progress(slot_id)

            except Exception as e:
                # 【静默失败修复】自动进度更新异常必须是ERROR级别，并更新任务状态
                logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}自动进度更新异常: {e}", exc_info=True)
                try:
                    self.set_task_error(slot_id, f"进度更新异常: {e}")
                except Exception as set_error_e:
                    # [SILENT_FAILURE_BLOCKED] 任务状态更新失败必须记录，不能静默
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}设置任务错误状态失败: {set_error_e}")
                break

        logger.info(f"[LongTaskSlots] 槽位{slot_id}自动进度更新线程已停止")

    async def _auto_progress_updater_async(self, slot_id: int, task: SlotTask):
        """
        【Phase 7.5】自动进度更新协程（异步版本）

        与同步版本行为一致，但使用 await asyncio.sleep 协作式让出，
        与主执行协程共享事件循环。
        """
        logger.info(f"[LongTaskSlots] 槽位{slot_id}自动进度更新协程已启动")

        update_interval = 5  # 每5秒更新一次

        while self._progress_update_flags.get(slot_id, False):
            try:
                await asyncio.sleep(update_interval)

                # 检查是否需要停止
                if not self._progress_update_flags.get(slot_id, False):
                    break

                # 检查任务状态
                with self._lock:
                    current_task = self._slots.get(slot_id)
                    if current_task is None or current_task.status != SlotStatus.RUNNING:
                        break

                # 自动更新进度
                self._update_auto_progress(slot_id)

            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}自动进度更新异常: {e}", exc_info=True)
                try:
                    self.set_task_error(slot_id, f"进度更新异常: {e}")
                except Exception as set_error_e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 槽位{slot_id}设置任务错误状态失败: {set_error_e}")
                break

        logger.info(f"[LongTaskSlots] 槽位{slot_id}自动进度更新协程已停止")

    def _start_timeout_monitor(self, slot_id: int, timeout: int, start_time: float = None):
        """
        【超时机制】启动超时监控线程（同步版本，保留兼容）

        定期检查任务是否超时，超时后设置超时标志

        Args:
            slot_id: 槽位ID
            timeout: 超时时间（秒）
            start_time: 任务实际开始时间戳（可选，用于避免竞争条件）
        """
        def monitor():
            # 使用传入的start_time或当前时间作为fallback
            monitor_start_time = start_time if start_time is not None else time.time()
            check_interval = min(30, timeout / 10)  # 检查间隔：30秒或超时的1/10

            while True:
                time.sleep(check_interval)

                # 检查任务是否仍在运行
                with self._lock:
                    task = self._slots.get(slot_id)
                    if not task or task.status != SlotStatus.RUNNING:
                        # 任务已结束，停止监控
                        logger.debug(f"[LongTaskSlots] 槽位{slot_id}任务已结束，超时监控停止")
                        break

                # 检查是否超时（使用传入的start_time计算elapsed）
                elapsed = time.time() - monitor_start_time
                if elapsed > timeout:
                    logger.warning(f"[TIMEOUT] 槽位{slot_id}任务执行超时: {elapsed:.1f}s > {timeout}s")
                    self._timeout_flags[slot_id] = True

                    # 设置任务错误状态
                    try:
                        self.set_task_error(slot_id, f"任务执行超时({timeout}s)")
                    except Exception as e:
                        logger.error(f"[TIMEOUT] 设置超时错误状态失败: {e}")
                    break

        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        self._timeout_monitors[slot_id] = monitor_thread
        logger.debug(f"[LongTaskSlots] 槽位{slot_id}超时监控线程已启动，检查间隔: {min(30, timeout/10):.1f}s")

    async def _start_timeout_monitor_async(self, slot_id: int, timeout: int, start_time: float = None):
        """
        【Phase 7.5】超时监控协程（异步版本）

        与同步版本行为一致，但使用 await asyncio.sleep 协作式让出。
        """
        monitor_start_time = start_time if start_time is not None else time.time()
        check_interval = min(30, timeout / 10)

        while True:
            await asyncio.sleep(check_interval)

            # 检查任务是否仍在运行
            with self._lock:
                task = self._slots.get(slot_id)
                if not task or task.status != SlotStatus.RUNNING:
                    logger.debug(f"[LongTaskSlots] 槽位{slot_id}任务已结束，超时监控协程停止")
                    break

            # 检查是否超时
            elapsed = time.time() - monitor_start_time
            if elapsed > timeout:
                logger.warning(f"[TIMEOUT] 槽位{slot_id}任务执行超时: {elapsed:.1f}s > {timeout}s")
                self._timeout_flags[slot_id] = True

                try:
                    self.set_task_error(slot_id, f"任务执行超时({timeout}s)")
                except Exception as e:
                    logger.error(f"[TIMEOUT] 设置超时错误状态失败: {e}")
                break

    # ═══════════════════════════════════════════════════════════
    # 核心操作方法
    # ═══════════════════════════════════════════════════════════

    def create_task(self, slot_id: int, task_config: dict[str, Any]) -> str:
        """
        在指定槽位创建任务

        【P2修复】支持槽位抢占策略:
        - 如果槽位被占用，比较新任务和当前任务的优先级
        - 如果新任务优先级更高，抢占当前任务
        - 如果当前任务优先级更高或相等，新任务进入等待队列

        Args:
            slot_id: 槽位ID (1, 2, 或 3)
            task_config: 任务配置字典，包含：
                - task_name: 任务名称（必填）
                - task_type: 任务类型（必填）
                - params: 任务参数（可选，默认空字典）
                - user_requirements: 用户需求（可选）
                - priority: 任务优先级（可选，默认NORMAL），可选值: LOW, NORMAL, HIGH, CRITICAL
                - allow_preempt: 是否允许被抢占（可选，默认True）

        Returns:
            str: 创建的任务ID

        Raises:
            ValueError: 槽位ID无效
        """
        with self._lock:
            # 检查槽位ID有效性
            if not self._is_valid_slot(slot_id):
                raise ValueError(f"槽位ID无效: {slot_id}，必须是1、2或3")

            # 解析优先级
            priority_str = task_config.get("priority", "NORMAL").upper()
            try:
                new_task_priority = TaskPriority[priority_str]
            except KeyError:
                new_task_priority = TaskPriority.NORMAL

            # 【P2修复】检查槽位是否被占用，进行抢占判断
            if self._slots[slot_id] is not None:
                existing_task = self._slots[slot_id]
                existing_priority = existing_task.priority

                # 检查是否可以抢占
                can_preempt = (
                    new_task_priority.value > existing_priority.value and
                    existing_priority != TaskPriority.CRITICAL and
                    task_config.get("allow_preempt", True)
                )

                if can_preempt:
                    # 抢占当前任务
                    logger.warning(
                        f"[PREEMPT] 槽位{slot_id}任务被抢占: "
                        f"{existing_task.task_id} (优先级{existing_priority.name}) -> "
                        f"新任务 (优先级{new_task_priority.name})"
                    )
                    self._preempt_task(slot_id, existing_task)
                else:
                    # 不能抢占，新任务进入等待队列
                    logger.info(
                        f"[WAITING] 槽位{slot_id}被占用，新任务进入等待队列: "
                        f"当前优先级={existing_priority.name}, 新优先级={new_task_priority.name}"
                    )
                    return self._add_to_waiting_queue(task_config, slot_id)

            # 创建并执行任务
            return self._create_and_execute_task(slot_id, task_config, new_task_priority)

    def _create_and_execute_task(self, slot_id: int, task_config: dict[str, Any],
                                 priority: TaskPriority) -> str:
        """
        【P2修复】创建并执行任务（内部方法）

        Args:
            slot_id: 槽位ID
            task_config: 任务配置
            priority: 任务优先级

        Returns:
            str: 任务ID
        """
        # 验证必填字段
        task_name = task_config.get("task_name")
        task_type = task_config.get("task_type")
        if not task_name or not task_type:
            raise ValueError("task_name和task_type为必填项")

        # 创建任务
        now = time.time()
        metadata = task_config.get("metadata", {})
        # 【断点续传修复】将 resume_from_checkpoint 和 task_id 存入 metadata
        if "resume_from_checkpoint" in task_config:
            metadata["_resume_from_checkpoint"] = task_config["resume_from_checkpoint"]
        if "task_id" in task_config:
            metadata["_original_task_id"] = task_config["task_id"]
        task = SlotTask(
            slot_id=slot_id,
            task_id=self._generate_task_id(),
            task_name=task_name,
            task_type=task_type,
            params=task_config.get("params", {}),
            status=SlotStatus.RUNNING,
            progress=0.0,
            created_at=now,
            updated_at=now,
            started_at=now,
            user_requirements=task_config.get("user_requirements"),
            metadata=metadata,
            priority=priority  # 【P2修复】设置优先级
        )

        # 保存到槽位
        self._slots[slot_id] = task

        # 通知回调
        self._notify_callbacks(slot_id, task, "created")

        # 启动任务执行
        self._execute_slot_task(slot_id, task)

        logger.info(f"[LongTaskSlots] 槽位{slot_id}创建并执行任务: {task.task_id} (优先级{priority.name})")
        return task.task_id

    def _preempt_task(self, slot_id: int, existing_task: SlotTask):
        """
        【P2修复】抢占槽位中的任务

        将被抢占的任务保存状态并移出槽位，供后续恢复

        Args:
            slot_id: 槽位ID
            existing_task: 被抢占的任务
        """
        # 设置任务为被抢占状态
        existing_task.status = SlotStatus.PREEMPTED
        existing_task.preempted_by = "higher_priority_task"

        # 停止任务执行
        self._stop_task_execution(slot_id)

        # 将被抢占的任务保存到metadata供后续恢复
        existing_task.metadata["preempted_at"] = time.time()
        existing_task.metadata["preempted_slot"] = slot_id

        # 通知回调
        self._notify_callbacks(slot_id, existing_task, "preempted")

        # 清空槽位
        self._slots[slot_id] = None

        logger.info(f"[PREEMPT] 任务 {existing_task.task_id} 已被抢占，保存状态供恢复")

    def _add_to_waiting_queue(self, task_config: dict[str, Any],
                              slot_id: int) -> str:
        """
        【P2修复】将任务添加到等待队列

        Args:
            task_config: 任务配置
            slot_id: 期望的槽位ID

        Returns:
            str: 任务ID（等待状态）
        """
        with self._waiting_queue_lock:
            # 解析优先级
            priority_str = task_config.get("priority", "NORMAL").upper()
            try:
                priority = TaskPriority[priority_str]
            except KeyError:
                priority = TaskPriority.NORMAL

            # 创建等待任务
            now = time.time()
            task = SlotTask(
                slot_id=slot_id,  # 期望的槽位
                task_id=self._generate_task_id(),
                task_name=task_config.get("task_name"),
                task_type=task_config.get("task_type"),
                params=task_config.get("params", {}),
                status=SlotStatus.IDLE,  # 等待状态显示为IDLE
                progress=0.0,
                created_at=now,
                updated_at=now,
                user_requirements=task_config.get("user_requirements"),
                metadata=task_config.get("metadata", {}),
                priority=priority,
                waiting_since=now  # 【P2修复】记录进入等待队列的时间
            )

            # 添加到等待队列（按优先级排序）
            self._waiting_queue.append(task)
            self._waiting_queue.sort(key=lambda t: (t.priority.value, t.waiting_since))

            logger.info(f"[WAITING] 任务 {task.task_id} 已加入等待队列 (优先级{priority.name})")
            return task.task_id

    def _stop_task_execution(self, slot_id: int):
        """
        【P2修复】停止槽位中的任务执行

        Args:
            slot_id: 槽位ID
        """
        # 设置超时标志来停止任务
        self._timeout_flags[slot_id] = True

        # 停止进度更新
        if hasattr(self, '_progress_update_flags'):
            self._progress_update_flags[slot_id] = False

        # 等待执行线程结束
        if slot_id in self._executors:
            executor_thread = self._executors[slot_id]
            if executor_thread and executor_thread.is_alive():
                # 给线程一些时间优雅退出
                executor_thread.join(timeout=2.0)
            del self._executors[slot_id]

    def get_waiting_queue(self) -> list[dict[str, Any]]:
        """
        【P2修复】获取等待队列中的任务

        Returns:
            List[Dict]: 等待队列中的任务列表
        """
        with self._waiting_queue_lock:
            return [{
                "task_id": t.task_id,
                "task_name": t.task_name,
                "priority": t.priority.name,
                "slot_id": t.slot_id,
                "waiting_since": t.waiting_since,
                "wait_time_seconds": time.time() - t.waiting_since if t.waiting_since else 0
            } for t in self._waiting_queue]

    def cancel_waiting_task(self, task_id: str) -> bool:
        """
        【P2修复】取消等待队列中的任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功取消
        """
        with self._waiting_queue_lock:
            for i, task in enumerate(self._waiting_queue):
                if task.task_id == task_id:
                    self._waiting_queue.pop(i)
                    logger.info(f"[WAITING] 任务 {task_id} 已从等待队列取消")
                    return True
            return False

    def get_slot_status(self, slot_id: int) -> SlotTask | None:
        """
        获取指定槽位状态

        Args:
            slot_id: 槽位ID (1, 2, 或 3)

        Returns:
            SlotTask: 槽位任务对象，如果槽位空闲则返回None

        Raises:
            ValueError: 槽位ID无效
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                raise ValueError(f"槽位ID无效: {slot_id}")
            return self._slots[slot_id]

    def get_all_slots_status(self) -> list[SlotTask | None]:
        """
        获取所有槽位状态

        Returns:
            List[SlotTask]: 包含3个槽位状态的列表（空闲槽位为None）
        """
        with self._lock:
            return [self._slots[1], self._slots[2], self._slots[3]]

    def get_all_slots_status_dict(self) -> dict[str, Any]:
        """
        获取所有槽位状态（字典格式，用于API）

        Returns:
            Dict: 包含槽位状态的字典
        """
        with self._lock:
            return {
                "slots": [
                    self._slots[i].to_dict() if self._slots[i] else {
                        "slot_id": i,
                        "status": SlotStatus.IDLE.value,
                        "task_id": None,
                        "task_name": None
                    }
                    for i in range(1, self.MAX_SLOTS + 1)
                ],
                "timestamp": time.time()
            }

    def pause_task(self, slot_id: int, reason: str = "用户暂停") -> bool:
        """
        暂停槽位任务

        Args:
            slot_id: 槽位ID
            reason: 暂停原因

        Returns:
            bool: 是否成功暂停
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                logger.warning(f"[LongTaskSlots] 暂停失败：槽位ID无效 {slot_id}")
                return False

            task = self._slots[slot_id]
            if task is None:
                logger.warning(f"[LongTaskSlots] 暂停失败：槽位{slot_id}空闲")
                return False

            if task.status != SlotStatus.RUNNING:
                logger.warning(f"[LongTaskSlots] 暂停失败：槽位{slot_id}任务状态为{task.status.value}，无法暂停")
                return False

            # 【新增】发送中断信号 - 确保任务能真正中断执行
            from core.agent.interrupt_handler import interrupt_handler
            interrupt_handler.interrupt(task.task_id, reason=reason)
            logger.info(f"[LongTaskSlots] 已向槽位{slot_id}任务发送中断信号: {task.task_id}")

            # 【新增】保存断点 - 支持断点续传
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                checkpoint_manager.save_checkpoint(task.task_id, f"用户暂停断点: {reason}")
                logger.info(f"[LongTaskSlots] 已保存槽位{slot_id}任务断点: {task.task_id}")
            except Exception as e:
                # 【静默失败修复】断点操作失败必须是ERROR级别
                logger.error(f"[LongTaskSlots] 保存断点失败: {e}", exc_info=True)

            # 更新状态
            task.status = SlotStatus.PAUSED
            task.paused_at = time.time()
            task.updated_at = time.time()
            task.metadata["pause_reason"] = reason

            # 通知回调
            self._notify_callbacks(slot_id, task, "paused")

            logger.info(f"[LongTaskSlots] 槽位{slot_id}任务已暂停: {task.task_id}, 原因: {reason}")
            return True

    def resume_task(self, slot_id: int, ai_confirmation: str) -> bool:
        """
        恢复槽位任务（需AI确认理解）

        【大纲要求】必须AI确认百分百理解需求后才能恢复

        Args:
            slot_id: 槽位ID
            ai_confirmation: AI确认理解的内容（必须非空）

        Returns:
            bool: 是否成功恢复
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                logger.warning(f"[LongTaskSlots] 恢复失败：槽位ID无效 {slot_id}")
                return False

            task = self._slots[slot_id]
            if task is None:
                logger.warning(f"[LongTaskSlots] 恢复失败：槽位{slot_id}空闲")
                return False

            if task.status != SlotStatus.PAUSED:
                logger.warning(f"[LongTaskSlots] 恢复失败：槽位{slot_id}任务状态为{task.status.value}，无法恢复")
                return False

            # 【核心检查】大纲第5条规则：必须AI确认理解
            if not ai_confirmation or not ai_confirmation.strip():
                logger.warning(f"[LongTaskSlots] 恢复失败：缺少AI确认理解内容 slot={slot_id}")
                return False

            # 验证AI理解充分性（简单检查：长度至少20字符）
            if len(ai_confirmation.strip()) < 20:
                logger.warning(f"[LongTaskSlots] 恢复失败：AI确认内容过短，请详细说明理解 slot={slot_id}")
                return False

            # 【新增】从断点恢复
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                try:
                    asyncio.get_running_loop()
                    safe_create_task(checkpoint_manager.resume_task(task.task_id), name="resume_task")
                except RuntimeError:
                    asyncio.run(checkpoint_manager.resume_task(task.task_id))
                logger.info(f"[LongTaskSlots] 已从断点恢复槽位{slot_id}任务: {task.task_id}")
            except Exception as e:
                # 【静默失败修复】断点操作失败必须是ERROR级别
                logger.error(f"[LongTaskSlots] 从断点恢复失败: {e}", exc_info=True)

            # 更新状态
            task.status = SlotStatus.RUNNING
            task.ai_understanding = ai_confirmation
            task.resumed_at = time.time()
            task.updated_at = time.time()
            task.metadata["resume_count"] = task.metadata.get("resume_count", 0) + 1

            # 【新增】重新启动执行（如果线程已终止）
            if slot_id not in self._executors or not self._executors[slot_id].is_alive():
                logger.info(f"[LongTaskSlots] 槽位{slot_id}执行线程已终止，重新启动")
                self._execute_slot_task(slot_id, task)

            # 通知回调
            self._notify_callbacks(slot_id, task, "resumed")

            logger.info(f"[LongTaskSlots] 槽位{slot_id}任务已恢复: {task.task_id}")
            return True

    def modify_task_params(self, slot_id: int, new_params: dict[str, Any]) -> bool:
        """
        AI修改槽位参数

        允许AI在任务运行过程中修改参数（如调整配置、更新进度等）

        Args:
            slot_id: 槽位ID
            new_params: 新的参数字典

        Returns:
            bool: 是否成功修改
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                logger.warning(f"[LongTaskSlots] 修改失败：槽位ID无效 {slot_id}")
                return False

            task = self._slots[slot_id]
            if task is None:
                logger.warning(f"[LongTaskSlots] 修改失败：槽位{slot_id}空闲")
                return False

            # 更新参数
            old_params = task.params.copy()
            task.params.update(new_params)
            task.updated_at = time.time()

            # 记录修改历史
            if "param_changes" not in task.metadata:
                task.metadata["param_changes"] = []
            task.metadata["param_changes"].append({
                "timestamp": time.time(),
                "old": old_params,
                "new": task.params.copy()
            })

            # 通知回调
            self._notify_callbacks(slot_id, task, "modified")

            logger.info(f"[LongTaskSlots] 槽位{slot_id}任务参数已修改: {task.task_id}")
            return True

    async def update_progress(self, slot_id: int, progress: float) -> bool:
        """
        更新槽位任务进度

        Args:
            slot_id: 槽位ID
            progress: 进度值 (0-100)

        Returns:
            bool: 是否成功更新
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return False

            task = self._slots[slot_id]
            if task is None:
                return False

            # 限制进度范围
            task.progress = max(0.0, min(100.0, progress))
            task.updated_at = time.time()

            # 如果进度100%，自动标记为完成
            if task.progress >= 100.0:
                # 从task metadata获取user_id，如果没有则使用default_user
                task_user_id = task.metadata.get("user_id", "default_user") if task.metadata else "default_user"
                await self._complete_task_internal(slot_id, task_user_id)
            else:
                self._notify_callbacks(slot_id, task, "progress_updated")

            return True

    async def _complete_task_internal(self, slot_id: int, user_id: str = "default_user"):
        """内部方法：完成任务（必须在锁内调用）"""
        task = self._slots[slot_id]
        if task:
            task.status = SlotStatus.IDLE
            task.progress = 100.0
            task.completed_at = time.time()
            task.updated_at = time.time()

            # 【2026-03-22 关键修复】任务完成后提取并存储经验
            await self._extract_and_store_experience(task, user_id)

            # 【游戏化】长任务完成经验值奖励
            try:
                from api.gamification_api import _calculate_level, _load_gamification_data, _save_gamification_data

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

                # 计算经验值（基础50 + 耗时奖励）
                xp_earned = 50
                if task.started_at and task.completed_at:
                    duration = task.completed_at - task.started_at
                    if duration > 300:  # 超过5分钟额外奖励
                        xp_earned += 30

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
                    "source": "long_task_complete",
                    "slot_id": slot_id,
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

                logger.info(f"[Gamification] 长任务完成，槽位{slot_id}，用户 {user_id} 获得 {xp_earned} XP")

            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] [Gamification] 记录长任务经验值失败: {e}")

            self._notify_callbacks(slot_id, task, "completed")
            logger.info(f"[LongTaskSlots] 槽位{slot_id}任务已完成: {task.task_id}")

            # 【P2修复】清空槽位
            self._slots[slot_id] = None

            # 【P2修复】检查等待队列，如果有等待该槽位的任务，自动启动
            self._check_and_start_waiting_task(slot_id)

    def _check_and_start_waiting_task(self, slot_id: int):
        """
        【P2修复】检查并启动等待队列中的任务

        Args:
            slot_id: 空闲的槽位ID
        """
        with self._waiting_queue_lock:
            # 查找等待该槽位的最高优先级任务
            for i, waiting_task in enumerate(self._waiting_queue):
                if waiting_task.slot_id == slot_id:
                    # 从等待队列移除
                    task_config = {
                        "task_name": waiting_task.task_name,
                        "task_type": waiting_task.task_type,
                        "params": waiting_task.params,
                        "user_requirements": waiting_task.user_requirements,
                        "metadata": waiting_task.metadata,
                        "priority": waiting_task.priority.name
                    }
                    self._waiting_queue.pop(i)

                    logger.info(f"[WAITING] 槽位{slot_id}空闲，自动启动等待任务: {waiting_task.task_id}")

                    # 在槽位锁外启动任务
                    # 注意：这里直接调用 _create_and_execute_task，但需要在锁内调用
                    # 所以需要重新获取锁
                    with self._lock:
                        self._create_and_execute_task(slot_id, task_config, waiting_task.priority)
                    return

    async def complete_task(self, slot_id: int, result: dict[str, Any] | None = None, user_id: str = "default_user") -> bool:
        """
        手动完成槽位任务

        Args:
            slot_id: 槽位ID
            result: 任务执行结果（可选）
            user_id: 用户ID（可选，用于经验值记录）

        Returns:
            bool: 是否成功完成
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return False

            task = self._slots[slot_id]
            if task is None:
                return False

            if result:
                task.result = result

            await self._complete_task_internal(slot_id, user_id)
            return True

    def stop_task(self, slot_id: int) -> bool:
        """
        停止槽位任务（强制终止，不保存结果）

        Args:
            slot_id: 槽位ID

        Returns:
            bool: 是否成功停止
        """
        with self._lock:
            # 【修复】先检查槽位有效性
            if not self._is_valid_slot(slot_id):
                logger.warning(f"[LongTaskSlots] 停止失败：槽位ID无效 {slot_id}")
                return False

            task = self._slots[slot_id]
            if task is None:
                logger.warning(f"[LongTaskSlots] 停止失败：槽位{slot_id}空闲")
                return False

            old_task_id = task.task_id

            # 【修复】发送中断信号给正在执行的任务（RUNNING或PAUSED状态都需要中断）
            if task.status in (SlotStatus.RUNNING, SlotStatus.PAUSED):
                from core.agent.interrupt_handler import interrupt_handler
                interrupt_handler.interrupt(task.task_id, reason="用户手动停止")
                logger.info(f"[LongTaskSlots] 已向槽位{slot_id}任务发送中断信号: {old_task_id}")

            # 【新增】清理断点数据
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                checkpoint_manager.clear_checkpoint(task.task_id)
                logger.info(f"[LongTaskSlots] 已清理槽位{slot_id}任务断点: {old_task_id}")
            except Exception as e:
                # 【静默失败修复】断点操作失败必须是ERROR级别
                logger.error(f"[LongTaskSlots] 清理断点失败: {e}", exc_info=True)

            # 清理执行线程引用
            if slot_id in self._executors:
                del self._executors[slot_id]

            # 清空槽位
            self._slots[slot_id] = None

            # 通知回调
            self._notify_callbacks(slot_id, None, "stopped")

            logger.info(f"[LongTaskSlots] 槽位{slot_id}任务已停止: {old_task_id}")
            return True

    def set_task_error(self, slot_id: int, error_message: str) -> bool:
        """
        设置槽位任务为错误状态

        Args:
            slot_id: 槽位ID
            error_message: 错误信息

        Returns:
            bool: 是否成功设置
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return False

            task = self._slots[slot_id]
            if task is None:
                return False

            task.status = SlotStatus.ERROR
            task.error_message = error_message
            task.updated_at = time.time()

            self._notify_callbacks(slot_id, task, "error")

            logger.error(f"[LongTaskSlots] 槽位{slot_id}任务出错: {task.task_id}, 错误: {error_message}")
            return True

    # ═══════════════════════════════════════════════════════════
    # AI交互方法
    # ═══════════════════════════════════════════════════════════

    def get_slot_summary_for_ai(self, slot_id: int) -> dict[str, Any] | None:
        """
        获取槽位摘要（供AI查看）

        Args:
            slot_id: 槽位ID

        Returns:
            Dict: 槽位摘要信息
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return None

            task = self._slots[slot_id]
            if task is None:
                return {
                    "slot_id": slot_id,
                    "status": "idle",
                    "message": "槽位空闲"
                }

            return {
                "slot_id": slot_id,
                "task_id": task.task_id,
                "task_name": task.task_name,
                "task_type": task.task_type,
                "status": task.status.value,
                "progress": task.progress,
                "params": task.params,
                "user_requirements": task.user_requirements,
                "ai_understanding": task.ai_understanding,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "paused_at": task.paused_at,
                "resumed_at": task.resumed_at,
                "error_message": task.error_message
            }

    def get_all_slots_summary_for_ai(self) -> dict[str, Any]:
        """
        获取所有槽位摘要（供AI查看）

        Returns:
            Dict: 所有槽位摘要
        """
        with self._lock:
            return {
                "total_slots": self.MAX_SLOTS,
                "active_slots": sum(1 for t in self._slots.values() if t is not None),
                "slots": [
                    self.get_slot_summary_for_ai(i) if self._slots[i] else {
                        "slot_id": i,
                        "status": "idle"
                    }
                    for i in range(1, self.MAX_SLOTS + 1)
                ]
            }

    def update_ai_understanding(self, slot_id: int, understanding: str) -> bool:
        """
        AI更新对需求的理解

        Args:
            slot_id: 槽位ID
            understanding: AI理解内容

        Returns:
            bool: 是否成功更新
        """
        with self._lock:
            if not self._is_valid_slot(slot_id):
                return False

            task = self._slots[slot_id]
            if task is None:
                return False

            task.ai_understanding = understanding
            task.updated_at = time.time()

            logger.info(f"[LongTaskSlots] 槽位{slot_id}AI理解已更新: {task.task_id}")
            return True

    # ═══════════════════════════════════════════════════════════
    # 回调注册
    # ═══════════════════════════════════════════════════════════

    def register_callback(self, callback: Callable[[int, SlotTask | None, str], None]):
        """
        注册状态变更回调（用于WebSocket推送）

        回调函数签名: callback(slot_id: int, task: SlotTask, event: str) -> None
        event类型: created, paused, resumed, modified, completed, stopped, error, progress_updated

        Args:
            callback: 回调函数
        """
        self._callbacks.append(callback)
        logger.info(f"[LongTaskSlots] 注册回调函数，当前回调数: {len(self._callbacks)}")

    def unregister_callback(self, callback: Callable[[int, SlotTask | None, str], None]):
        """注销状态变更回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            logger.info(f"[LongTaskSlots] 注销回调函数，当前回调数: {len(self._callbacks)}")

    # ═══════════════════════════════════════════════════════════
    # 统计信息
    # ═══════════════════════════════════════════════════════════

    def get_statistics(self) -> dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict: 统计信息
        """
        with self._lock:
            status_counts = {"idle": 0, "running": 0, "paused": 0, "error": 0}

            for slot_id in range(1, self.MAX_SLOTS + 1):
                task = self._slots[slot_id]
                if task is None:
                    status_counts["idle"] += 1
                else:
                    status_counts[task.status.value] += 1

            return {
                "total_slots": self.MAX_SLOTS,
                "status_distribution": status_counts,
                "callback_count": len(self._callbacks)
            }


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_long_task_slots_instance: LongTaskSlots | None = None
_instance_lock = threading.Lock()


def get_long_task_slots() -> LongTaskSlots:
    """
    获取全局3槽位长任务管理器实例（单例模式）

    Returns:
        LongTaskSlots: 全局实例
    """
    global _long_task_slots_instance
    if _long_task_slots_instance is None:
        with _instance_lock:
            if _long_task_slots_instance is None:
                _long_task_slots_instance = LongTaskSlots()
    return _long_task_slots_instance


def reset_long_task_slots():
    """重置全局实例（仅用于测试）"""
    global _long_task_slots_instance
    with _instance_lock:
        _long_task_slots_instance = None


# ═══════════════════════════════════════════════════════════════════
# WebSocket集成 - 槽位状态变更实时推送
# ═══════════════════════════════════════════════════════════════════

def init_websocket_integration():
    """
    初始化WebSocket集成
    在应用启动时调用，将槽位状态变更推送到前端

    【WebSocket 统一改造】所有广播走 FastAPI ConnectionManager（8600 端口），
    不再依赖独立的 websocket_server (8601)。
    """
    try:
        import asyncio

        from api.cloud_api import ConnectionManager

        manager = ConnectionManager()
        slots_manager = get_long_task_slots()

        def on_slot_status_change(slot_id: int, task: SlotTask | None, event_type: str):
            """槽位状态变更回调"""
            try:
                # 构建推送数据
                data = {
                    "type": "slot_update",
                    "slot_id": slot_id,
                    "event": event_type,
                    "timestamp": time.time(),
                    "task": task.to_dict() if task else None
                }

                # 异步广播（在事件循环中执行）
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        safe_create_task(manager.broadcast(data), name="slot_broadcast")
                    else:
                        loop.run_until_complete(manager.broadcast(data))
                except RuntimeError:
                    # 无事件循环时跳过
                    pass

            except ImportError as ie:
                # 【静默失败修复】WebSocket推送问题需要记录
                logger.warning(f"[LongTaskSlots] WebSocket未就绪，跳过推送: {ie}")
            except Exception as e:
                logger.error(f"[LongTaskSlots] WebSocket推送失败: {e}")

        # 注册回调
        slots_manager.register_callback(on_slot_status_change)
        logger.info("[LongTaskSlots] WebSocket集成已初始化")

    except ImportError as e:
        logger.warning(f"[LongTaskSlots] WebSocket集成失败（realtime_sync 未就绪）: {e}")
    except Exception as e:
        logger.error(f"[LongTaskSlots] WebSocket集成初始化失败: {e}")


# 【修复】删除模块级别的自动初始化，避免循环导入
# 由 main.py 在系统启动完成后统一调用 init_websocket_integration()


# ═══════════════════════════════════════════════════════════
# 文件角色总结
# ═══════════════════════════════════════════════════════════
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"3槽位长任务管理器"，提供固定3个槽位的
# 长任务管理能力，对应大纲要求的"长期任务的3个面板"。
#
# 【架构设计】
# - SlotStatus枚举: 定义槽位任务状态
# - SlotTask数据类: 槽位任务数据结构
# - LongTaskSlots类: 核心管理器，提供线程安全的槽位操作
# - 全局单例: 通过get_long_task_slots()获取唯一实例
#
# 【核心特性】
# 1. 固定3槽位: 对应大纲3个面板，slot_id为1, 2, 3
# 2. 线程安全: 使用RLock确保多线程安全
# 3. AI确认机制: resume_task()必须提供AI确认内容（大纲第5条规则）
# 4. 状态回调: 支持注册回调函数，用于WebSocket推送
# 5. AI可操作: AI可以查看、修改参数、更新理解
#
# 【状态流转】
# IDLE -> create_task -> RUNNING
# RUNNING -> pause_task -> PAUSED
# PAUSED -> resume_task(ai_confirmation) -> RUNNING
# RUNNING/PAUSED -> stop_task -> IDLE
# RUNNING -> set_task_error -> ERROR -> stop_task -> IDLE
# RUNNING -> update_progress(100) -> IDLE (自动完成)
#
# 【关联文件】
# - api/long_task_slots_api.py: FastAPI接口
# - core/long_running_manager.py: 传统长任务管理器（兼容）
# - api/cloud_api.py /ws/*: WebSocket推送
#
# ═══════════════════════════════════════════════════════════
