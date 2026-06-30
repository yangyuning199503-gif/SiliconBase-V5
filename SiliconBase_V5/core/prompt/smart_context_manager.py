#!/usr/bin/env python3
"""
智能上下文管理器 - SiliconBase V5 核心集成模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 整合ImportanceEngine、KeyDecisionDetector、LongTaskContextManager
  ✓ 统一的上下文构建接口
  ✓ 长任务自动检测和管理
  ✓ 智能检查点保存

这是修复计划的核心集成模块，将各个独立组件串联起来。

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# 导入修复计划中的核心组件
from core.consciousness.life_presence import AIState, EventType, get_life_presence_manager
from core.memory.memory_continuity_guard import get_continuity_guard
from core.prompt.context_builder import ContextBuilder
from core.strategy.importance_engine import get_importance_engine
from core.strategy.key_decision_detector import get_key_decision_detector
from core.task.long_task_context_manager import LongTaskContextManager, get_long_task_manager


class TaskType(Enum):
    """任务类型"""
    SHORT = "short"         # 短任务（< 5分钟）
    MEDIUM = "medium"       # 中等任务（5-30分钟）
    LONG = "long"           # 长任务（> 30分钟）


@dataclass
class SmartContextConfig:
    """智能上下文配置"""
    # 长任务阈值（步数）
    long_task_threshold: int = 20

    # 启用/禁用各功能
    enable_importance_filter: bool = True
    enable_key_decision_detection: bool = True
    enable_long_task_context: bool = True
    enable_continuity_guard: bool = True
    enable_life_presence: bool = True

    # 检查点配置
    checkpoint_enabled: bool = True
    checkpoint_min_interval: int = 5  # 最少间隔5步


class SmartContextManager:
    """
    智能上下文管理器

    统一管理：
    1. 重要性评估和筛选
    2. 关键决策点检测
    3. 长任务上下文管理
    4. 记忆连续性保护
    5. AI生命感/播报
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: SmartContextConfig = None):
        if SmartContextManager._initialized:
            return

        self.config = config or SmartContextConfig()

        # 初始化各组件
        self._importance_engine = get_importance_engine()
        self._key_decision_detector = get_key_decision_detector()
        self._continuity_guard = get_continuity_guard()
        self._life_presence = get_life_presence_manager()

        # 长任务管理器字典（task_id -> manager）
        self._long_task_managers: dict[str, LongTaskContextManager] = {}

        # 任务状态跟踪
        self._task_stats: dict[str, dict] = {}

        SmartContextManager._initialized = True
        logger.info("[SmartContextManager] 智能上下文管理器初始化完成")

    def initialize_task(self,
                       task_id: str,
                       goal: str,
                       constraints: list[str] = None,
                       user_id: str = "default") -> dict[str, Any]:
        """
        初始化任务

        在任务开始时调用，设置所有必要的上下文
        """
        constraints = constraints or []

        # 注册到连续性守护者
        if self.config.enable_continuity_guard:
            self._continuity_guard.register_task(task_id, goal, constraints)

        # 判断任务类型并初始化长任务管理器
        if self.config.enable_long_task_context:
            manager = get_long_task_manager(task_id, user_id)
            manager.initialize_task(goal, constraints)
            self._long_task_managers[task_id] = manager

        # 初始化任务统计
        self._task_stats[task_id] = {
            'start_time': time.time(),
            'step_count': 0,
            'goal': goal,
            'constraints': constraints
        }

        # 播报任务开始
        if self.config.enable_life_presence:
            self._life_presence.on_task_start(goal)

        logger.info(f"[SmartContextManager] 任务初始化: {task_id}, 目标: {goal[:50]}...")

        return {
            'task_id': task_id,
            'goal': goal,
            'is_long_task': False,  # 初始未知，后续根据步数判断
            'features_enabled': {
                'importance_filter': self.config.enable_importance_filter,
                'key_decision': self.config.enable_key_decision_detection,
                'long_task_context': self.config.enable_long_task_context,
                'continuity_guard': self.config.enable_continuity_guard,
                'life_presence': self.config.enable_life_presence
            }
        }

    def on_step_start(self, task_id: str, step_number: int, action: str):
        """步骤开始时调用"""
        # 更新AI状态
        if self.config.enable_life_presence:
            self._life_presence.update_state(AIState.EXECUTING, action)

        # 更新统计
        if task_id in self._task_stats:
            self._task_stats[task_id]['step_count'] = step_number

    def on_step_complete(self,
                        task_id: str,
                        step_number: int,
                        action: str,
                        result: str,
                        success: bool = True,
                        tool_name: str = None,
                        context: dict = None) -> dict[str, Any]:
        """
        步骤完成时调用

        这是核心方法，处理：
        1. 长任务上下文更新
        2. 关键决策点检测
        3. 连续性检查
        4. 播报
        """
        context = context or {}
        events_triggered = []

        # 1. 更新长任务上下文
        if self.config.enable_long_task_context and task_id in self._long_task_managers:
            manager = self._long_task_managers[task_id]
            manager.add_step(
                action=action,
                result=result,
                tool_name=tool_name,
                success=success,
                context=context
            )

            # 检测是否为长任务
            is_long_task = step_number >= self.config.long_task_threshold
            if is_long_task and step_number == self.config.long_task_threshold:
                logger.info(f"[SmartContextManager] 任务 {task_id} 已转为长任务模式")
                events_triggered.append('long_task_mode_activated')

        # 2. 检测关键决策点
        decision = None
        if self.config.enable_key_decision_detection:
            decision = self._key_decision_detector.detect(
                step_number=step_number,
                content=f"{action} {result}",
                task_id=task_id,
                context_before=context.get('before'),
                context_after={'success': success, **context.get('after', {})}
            )

            if decision:
                events_triggered.append(f'key_decision:{decision.decision_type.value}')

        # 3. 连续性检查
        continuity_check = None
        if self.config.enable_continuity_guard:
            continuity_check = self._continuity_guard.check_continuity(
                task_id=task_id,
                current_output=result,
                step_number=step_number
            )

            if not continuity_check.ok:
                events_triggered.append(f'continuity_issue:{continuity_check.intervention_type}')

        # 4. 播报
        if self.config.enable_life_presence:
            if tool_name:
                self._life_presence.on_tool_result(tool_name, success, result)
            elif success:
                self._life_presence.announce(EventType.TOOL_SUCCESS, action)

        return {
            'step_number': step_number,
            'is_key_decision': decision is not None,
            'decision': decision.to_dict() if decision else None,
            'continuity_ok': continuity_check.ok if continuity_check else True,
            'intervention': continuity_check.reminder if continuity_check and not continuity_check.ok else None,
            'events': events_triggered
        }

    async def build_context(self,
                     task_id: str,
                     system_prompt: str,
                     chat_history: list[dict],
                     execution_history: list[dict],
                     current_step: int = 0) -> list[dict]:
        """
        构建智能上下文

        整合所有组件的智能上下文构建
        """
        goal = ""
        if task_id in self._task_stats:
            goal = self._task_stats[task_id]['goal']

        # 判断是否为长任务
        is_long_task = (
            self.config.enable_long_task_context and
            task_id in self._long_task_managers and
            current_step >= self.config.long_task_threshold
        )

        # 长任务：使用长任务上下文管理器
        if is_long_task:
            manager = self._long_task_managers[task_id]
            long_context = manager.get_context_for_ai()

            # 构建消息
            messages = [
                {"role": "system", "content": f"{system_prompt}\n\n{long_context}"}
            ]

            # 添加最近的用户消息
            recent_user_msgs = [m for m in chat_history if m.get("role") == "user"][-3:]
            messages.extend(recent_user_msgs)

            return messages

        # 普通任务：使用增强的上下文构建
        working_memory = None  # 可以从参数传入

        messages = await ContextBuilder.build_context_with_importance(
            system_prompt=system_prompt,
            working_memory=working_memory,
            execution_history=execution_history,
            current_task=goal,
            chat_history=chat_history,
            use_importance_filter=self.config.enable_importance_filter
        )

        return messages

    def should_save_checkpoint(self, task_id: str, step_number: int) -> bool:
        """判断是否应该保存检查点"""
        if not self.config.checkpoint_enabled:
            return False

        # 使用关键决策检测器判断
        if self.config.enable_key_decision_detection:
            return self._key_decision_detector.should_save_checkpoint(step_id=task_id, step_number=step_number)

        # 默认策略：每10步保存一次
        return step_number % 10 == 0

    def get_recovery_context(self, task_id: str, resume_step: int = None) -> str:
        """获取任务恢复的上下文"""
        if not self.config.enable_long_task_context or task_id not in self._long_task_managers:
            return ""

        manager = self._long_task_managers[task_id]
        return manager.get_context_for_recovery(resume_step)

    def on_task_complete(self, task_id: str, success: bool = True):
        """任务完成时调用"""
        # 播报
        if self.config.enable_life_presence:
            goal = self._task_stats.get(task_id, {}).get('goal', '任务')
            self._life_presence.on_task_complete(goal, success)

        # 清理资源
        if task_id in self._long_task_managers:
            # 保留数据，只是记录完成时间
            pass

        logger.info(f"[SmartContextManager] 任务完成: {task_id}, 成功: {success}")

    def on_error(self, task_id: str, error_message: str, critical: bool = False):
        """发生错误时调用"""
        if self.config.enable_life_presence:
            self._life_presence.on_error(error_message, critical)

    def get_status(self, task_id: str) -> dict[str, Any]:
        """获取任务状态"""
        status = {
            'task_id': task_id,
            'is_long_task': False,
            'step_count': 0,
            'features': {}
        }

        if task_id in self._task_stats:
            stats = self._task_stats[task_id]
            status['step_count'] = stats['step_count']
            status['is_long_task'] = stats['step_count'] >= self.config.long_task_threshold
            status['duration'] = time.time() - stats['start_time']

        if self.config.enable_long_task_context and task_id in self._long_task_managers:
            manager = self._long_task_managers[task_id]
            status['context_stats'] = manager.get_execution_stats()

        status['features'] = {
            'importance_filter': self.config.enable_importance_filter,
            'key_decision': self.config.enable_key_decision_detection,
            'long_task': self.config.enable_long_task_context and status['is_long_task'],
            'continuity_guard': self.config.enable_continuity_guard,
            'life_presence': self.config.enable_life_presence
        }

        return status

    def get_ai_status_indicator(self) -> dict[str, Any]:
        """获取AI状态指示器（供前端使用）"""
        if self.config.enable_life_presence:
            return self._life_presence.get_status_indicator().to_dict()
        return {}


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

_manager: SmartContextManager | None = None

def get_smart_context_manager(config: SmartContextConfig = None) -> SmartContextManager:
    """获取全局管理器实例"""
    global _manager
    if _manager is None:
        _manager = SmartContextManager(config)
    return _manager


def initialize_smart_task(task_id: str, goal: str,
                         constraints: list[str] = None,
                         user_id: str = "default") -> dict[str, Any]:
    """便捷函数：初始化智能任务"""
    return get_smart_context_manager().initialize_task(task_id, goal, constraints, user_id)


async def build_smart_context(task_id: str, system_prompt: str,
                       chat_history: list[dict],
                       execution_history: list[dict],
                       current_step: int = 0) -> list[dict]:
    """便捷函数：构建智能上下文"""
    return await get_smart_context_manager().build_context(
        task_id, system_prompt, chat_history, execution_history, current_step
    )
