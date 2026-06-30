#!/usr/bin/env python3
"""
实时干预系统 - RealTimeIntervention
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
让AI像生命体一样，边执行边倾听，随时调整方向。

【核心理念】
  任务执行 ≠ 耳聋眼盲
  AI在执行时应该保持"耳朵竖着"，用户随时可以喊：
  - "等等，换个方式" → 方法调整
  - "算了别做这个了" → 目标取消
  - "先做这个更重要" → 优先级切换
  - "刚才那样挺好" → 确认继续

【能力矩阵】
  ┌─────────────────────────────────────────────────────┐
  │  干预类型        │  效果              │  记忆保持   │
  ├─────────────────────────────────────────────────────┤
  │  调整方法        │  换条路走          │  ✓ 全保持  │
  │  修正方向        │  微调目标          │  ✓ 全保持  │
  │  切换目标        │  放弃旧做新        │  △ 部分   │
  │  暂停确认        │  等一下再说        │  ✓ 全保持  │
  │  情感安抚        │  只是吐槽          │  ✓ 不影响  │
  └─────────────────────────────────────────────────────┘
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from core.logger import logger
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线


class InterventionType(Enum):
    """干预类型枚举"""
    METHOD_ADJUST = auto()      # 方法调整："用另一种方式做"
    DIRECTION_CORRECT = auto()  # 方向修正："不是这个，是那个"
    GOAL_SWITCH = auto()        # 目标切换："先做这个新的"
    PAUSE_CONFIRM = auto()      # 暂停确认："等等，我看看"
    EMOTIONAL = auto()          # 情感交互："加油" / "好慢啊"
    CLARIFY = auto()            # 需求澄清："为什么要做这个？"
    PROGRESS_QUERY = auto()     # 进度查询："做得怎么样了？"


class ExecutionAdaptation(Enum):
    """执行调整策略"""
    CONTINUE = auto()           # 继续执行（无需调整）
    ADJUST_APPROACH = auto()    # 调整方法（换工具/换步骤）
    REPLAN = auto()             # 重新规划（目标微调）
    PIVOT = auto()              # 完全转向（新目标）
    PAUSE = auto()              # 暂停等待
    ABORT = auto()              # 终止任务


@dataclass
class InterventionContext:
    """干预上下文"""
    task_id: str
    intervention_type: InterventionType
    raw_input: str                  # 用户原始输入
    parsed_intent: str              # 解析后的意图
    timestamp: float = field(default_factory=time.time)
    emotional_tone: str = "neutral" # 情感语调：urgent/calm/frustrated/excited
    confidence: float = 1.0         # 置信度


@dataclass
class ExecutionDelta:
    """执行变更记录"""
    change_type: str                # 变更类型
    before_state: dict              # 变更前状态
    after_state: dict               # 变更后状态
    preserved_work: list            # 保留的工作成果
    discarded_work: list            # 废弃的工作
    reason: str                     # 变更原因
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskMemory:
    """任务记忆 - 保持任务身份不变，内容可调"""
    task_id: str
    original_goal: str              # 原始目标（不变）
    current_goal: str               # 当前目标（可能调整）
    completed_steps: list[dict]     # 已完成步骤
    learned_lessons: list[str]      # 学到的经验
    adaptations: list[ExecutionDelta]  # 历史调整记录
    created_at: float = field(default_factory=time.time)


class RealTimeInterventionHandler:
    """
    实时干预处理器

    像飞行员和塔台对话一样，边飞边接收指令。
    """

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

        # 活跃任务：task_id -> TaskMemory
        self._active_tasks: dict[str, TaskMemory] = {}

        # 干预队列：task_id -> List[InterventionContext]
        self._intervention_queues: dict[str, list[InterventionContext]] = {}

        # 干预处理器：InterventionType -> Callable
        self._handlers: dict[InterventionType, Callable] = {
            InterventionType.METHOD_ADJUST: self._handle_method_adjust,
            InterventionType.DIRECTION_CORRECT: self._handle_direction_correct,
            InterventionType.GOAL_SWITCH: self._handle_goal_switch,
            InterventionType.PAUSE_CONFIRM: self._handle_pause_confirm,
            InterventionType.EMOTIONAL: self._handle_emotional,
            InterventionType.CLARIFY: self._handle_clarify,
            InterventionType.PROGRESS_QUERY: self._handle_progress_query,
        }

        # 监听器：task_id -> Callable（通知AgentLoop有新干预）
        self._listeners: dict[str, Callable] = {}

        self._task_lock = threading.RLock()
        logger.info("[RealTimeIntervention] 实时干预系统初始化完成")

    # ═══════════════════════════════════════════════════════════════
    # 对外 API
    # ═══════════════════════════════════════════════════════════════

    def register_task(self, task_id: str, goal: str,
                      listener: Callable = None) -> TaskMemory:
        """
        注册任务到干预系统

        Args:
            task_id: 任务ID
            goal: 任务目标
            listener: 干预回调函数（有新干预时调用）
        """
        with self._task_lock:
            memory = TaskMemory(
                task_id=task_id,
                original_goal=goal,
                current_goal=goal,
                completed_steps=[],
                learned_lessons=[],
                adaptations=[]
            )
            self._active_tasks[task_id] = memory
            self._intervention_queues[task_id] = []

            if listener:
                self._listeners[task_id] = listener

            logger.info(f"[RTI] 任务注册: {task_id}, 目标: {goal}")
            return memory

    def submit_intervention(self, task_id: str, user_input: str,
                           emotional_tone: str = "neutral") -> bool:
        """
        提交用户干预（从聊天模式实时传入）

        Args:
            task_id: 正在执行的任务ID
            user_input: 用户输入
            emotional_tone: 情感语调

        Returns:
            bool: 是否成功提交
        """
        with self._task_lock:
            if task_id not in self._active_tasks:
                logger.warning(f"[RTI] 任务不存在: {task_id}")
                return False

            # 解析干预类型
            intervention_type, parsed_intent = self._parse_intervention(user_input)

            context = InterventionContext(
                task_id=task_id,
                intervention_type=intervention_type,
                raw_input=user_input,
                parsed_intent=parsed_intent,
                emotional_tone=emotional_tone,
                confidence=0.9
            )

            self._intervention_queues[task_id].append(context)

            # 通知监听器（AgentLoop）
            if task_id in self._listeners:
                try:
                    self._listeners[task_id](context)
                except Exception as e:
                    logger.error(f"[RTI] 通知监听器失败: {e}")

            logger.info(f"[RTI] 干预提交: {task_id}, 类型: {intervention_type.name}, 内容: {user_input[:50]}")
            # 【ExperienceBus】实时干预提交事件
            try:
                event_bus.emit("intervention:submitted", {
                    "task_id": task_id,
                    "intervention_type": intervention_type.name,
                    "emotional_tone": emotional_tone,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.error(f"[RealtimeIntervention] 发送干预事件失败: {e}", exc_info=True)
            return True

    def get_pending_intervention(self, task_id: str) -> InterventionContext | None:
        """获取待处理的干预（AgentLoop每轮调用）"""
        with self._task_lock:
            queue = self._intervention_queues.get(task_id, [])
            if queue:
                return queue.pop(0)
            return None

    def apply_adaptation(self, task_id: str, adaptation: ExecutionAdaptation,
                        details: dict) -> ExecutionDelta:
        """
        应用执行调整，记录变更

        这是核心方法：保持任务身份，记录做了什么调整
        """
        with self._task_lock:
            memory = self._active_tasks.get(task_id)
            if not memory:
                raise ValueError(f"任务不存在: {task_id}")

            # 记录变更前状态
            before = {
                "goal": memory.current_goal,
                "completed_steps_count": len(memory.completed_steps),
                "adaptations_count": len(memory.adaptations)
            }

            # 执行调整
            preserved = []
            discarded = []

            if adaptation == ExecutionAdaptation.ADJUST_APPROACH:
                # 方法调整：保留所有已完成工作
                preserved = memory.completed_steps.copy()
                memory.learned_lessons.append(f"方法调整: {details.get('reason', '')}")

            elif adaptation == ExecutionAdaptation.REPLAN:
                # 重新规划：保留部分相关步骤
                relevant_steps = details.get('relevant_steps', [])
                preserved = [s for s in memory.completed_steps if s.get('id') in relevant_steps]
                discarded = [s for s in memory.completed_steps if s.get('id') not in relevant_steps]
                memory.current_goal = details.get('new_goal', memory.current_goal)

            elif adaptation == ExecutionAdaptation.PIVOT:
                # 完全转向：标记旧工作为历史，开始新目标
                memory.learned_lessons.append(f"目标切换: {memory.current_goal} -> {details.get('new_goal')}")
                memory.current_goal = details.get('new_goal', memory.current_goal)
                # 保留部分通用成果
                preserved = details.get('preserved_steps', [])
                discarded = [s for s in memory.completed_steps if s.get('id') not in [p.get('id') for p in preserved]]
                memory.completed_steps = preserved

            # 记录变更
            after = {
                "goal": memory.current_goal,
                "completed_steps_count": len(memory.completed_steps),
                "adaptations_count": len(memory.adaptations) + 1
            }

            delta = ExecutionDelta(
                change_type=adaptation.name,
                before_state=before,
                after_state=after,
                preserved_work=preserved,
                discarded_work=discarded,
                reason=details.get('reason', '')
            )

            memory.adaptations.append(delta)

            logger.info(f"[RTI] 调整已应用: {task_id}, 类型: {adaptation.name}, 保留: {len(preserved)}, 废弃: {len(discarded)}")
            # 【ExperienceBus】干预调整应用事件
            try:
                event_bus.emit("intervention:applied", {
                    "task_id": task_id,
                    "adaptation": adaptation.name,
                    "preserved": len(preserved),
                    "discarded": len(discarded),
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.error(f"[RealtimeIntervention] 发送干预适应事件失败: {e}", exc_info=True)
            return delta

    def complete_step(self, task_id: str, step: dict):
        """记录完成的步骤"""
        with self._task_lock:
            memory = self._active_tasks.get(task_id)
            if memory:
                memory.completed_steps.append({
                    **step,
                    "completed_at": time.time()
                })

    def get_task_memory(self, task_id: str) -> TaskMemory | None:
        """获取任务记忆（用于显示给用户）"""
        return self._active_tasks.get(task_id)

    def unregister_task(self, task_id: str) -> TaskMemory:
        """注销任务，返回完整记忆（可归档）"""
        with self._task_lock:
            memory = self._active_tasks.pop(task_id, None)
            self._intervention_queues.pop(task_id, None)
            self._listeners.pop(task_id, None)
            return memory

    # ═══════════════════════════════════════════════════════════════
    # 内部处理逻辑
    # ═══════════════════════════════════════════════════════════════

    def _parse_intervention(self, user_input: str) -> tuple[InterventionType, str]:
        """解析用户输入的干预类型"""
        text = user_input.lower()

        # 方法调整
        if any(kw in text for kw in ["换个", "用另一种", "试试", "改一下"]):
            return InterventionType.METHOD_ADJUST, "调整执行方法"

        # 方向修正
        if any(kw in text for kw in ["不是", "错了", "应该是", "我说的是"]):
            return InterventionType.DIRECTION_CORRECT, "修正执行方向"

        # 目标切换
        if any(kw in text for kw in ["先做这个", "别做那个了", "改做", "换成"]):
            return InterventionType.GOAL_SWITCH, "切换目标任务"

        # 暂停确认
        if any(kw in text for kw in ["等等", "停一下", "让我看看", "先别"]):
            return InterventionType.PAUSE_CONFIRM, "暂停等待确认"

        # 进度查询
        if any(kw in text for kw in ["怎么样了", "做好了吗", "进度", "完成了吗"]):
            return InterventionType.PROGRESS_QUERY, "查询执行进度"

        # 澄清
        if any(kw in text for kw in ["为什么", "什么意思", "怎么做"]):
            return InterventionType.CLARIFY, "需求澄清"

        # 情感交互
        if any(kw in text for kw in ["加油", "好慢", "快点", "不错", "真棒"]):
            return InterventionType.EMOTIONAL, "情感交互"

        # 默认
        return InterventionType.METHOD_ADJUST, "未明确，默认方法调整"

    def _handle_method_adjust(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理方法调整干预"""
        logger.info(f"[RTI] 方法调整: {context.raw_input}")
        return ExecutionAdaptation.ADJUST_APPROACH

    def _handle_direction_correct(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理方向修正干预"""
        logger.info(f"[RTI] 方向修正: {context.raw_input}")
        return ExecutionAdaptation.REPLAN

    def _handle_goal_switch(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理目标切换干预"""
        logger.info(f"[RTI] 目标切换: {context.raw_input}")
        return ExecutionAdaptation.PIVOT

    def _handle_pause_confirm(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理暂停确认干预"""
        logger.info(f"[RTI] 暂停确认: {context.raw_input}")
        return ExecutionAdaptation.PAUSE

    def _handle_emotional(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理情感交互"""
        logger.info(f"[RTI] 情感交互: {context.raw_input}")
        # 情感交互不影响执行
        return ExecutionAdaptation.CONTINUE

    def _handle_clarify(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理需求澄清"""
        logger.info(f"[RTI] 需求澄清: {context.raw_input}")
        return ExecutionAdaptation.PAUSE

    def _handle_progress_query(self, context: InterventionContext) -> ExecutionAdaptation:
        """处理进度查询"""
        logger.info(f"[RTI] 进度查询: {context.raw_input}")
        return ExecutionAdaptation.CONTINUE


# 全局实例
realtime_intervention = RealTimeInterventionHandler()


# ═══════════════════════════════════════════════════════════════
# 与 AgentLoop 集成的辅助函数
# ═══════════════════════════════════════════════════════════════

def check_and_apply_intervention(task_id: str,
                                 current_working_memory: list[dict],
                                 current_plan: list) -> tuple[bool, str, dict]:
    """
    供 AgentLoop 每轮调用，检查并应用干预

    Returns:
        (has_intervention, adaptation_type, details)
    """
    intervention = realtime_intervention.get_pending_intervention(task_id)

    if not intervention:
        return False, "", {}

    # 获取任务记忆
    memory = realtime_intervention.get_task_memory(task_id)

    # 构建干预详情
    details = {
        "intervention": intervention,
        "memory": memory,
        "suggested_adaptation": None
    }

    # 根据干预类型决定调整策略
    if intervention.intervention_type == InterventionType.METHOD_ADJUST:
        details["suggested_adaptation"] = ExecutionAdaptation.ADJUST_APPROACH
        details["reason"] = intervention.raw_input

    elif intervention.intervention_type == InterventionType.DIRECTION_CORRECT:
        details["suggested_adaptation"] = ExecutionAdaptation.REPLAN
        details["reason"] = intervention.raw_input
        details["new_goal"] = intervention.parsed_intent

    elif intervention.intervention_type == InterventionType.GOAL_SWITCH:
        details["suggested_adaptation"] = ExecutionAdaptation.PIVOT
        details["reason"] = intervention.raw_input
        details["new_goal"] = intervention.parsed_intent

    elif intervention.intervention_type == InterventionType.PAUSE_CONFIRM:
        details["suggested_adaptation"] = ExecutionAdaptation.PAUSE
        details["reason"] = "用户请求暂停确认"

    elif intervention.intervention_type == InterventionType.PROGRESS_QUERY:
        # 只回复进度，不调整
        details["suggested_adaptation"] = ExecutionAdaptation.CONTINUE
        details["reply"] = f"已完成 {len(memory.completed_steps)} 个步骤，当前目标: {memory.current_goal}"

    return True, details["suggested_adaptation"].name, details


# 导出
__all__ = [
    'RealTimeInterventionHandler',
    'realtime_intervention',
    'InterventionType',
    'ExecutionAdaptation',
    'InterventionContext',
    'ExecutionDelta',
    'TaskMemory',
    'check_and_apply_intervention'
]
