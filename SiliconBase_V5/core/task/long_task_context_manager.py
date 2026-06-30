#!/usr/bin/env python3
"""
长任务上下文管理器 - SiliconBase V5 记忆连续性核心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 三层记忆架构（短期/中期/长期）
  ✓ 关键约束持续注入
  ✓ 增量式历史摘要
  ✓ 几小时长任务的记忆连续性保障

核心机制：
  - 短期记忆：最近10步详细记录
  - 中期记忆：每20步AI摘要一次
  - 长期记忆：关键约束和决策永不丢失

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# 导入重要性评估和关键决策检测（使用try-except确保独立导入）
try:
    from core.strategy.importance_engine import ImportanceLevel, calculate_importance
except ImportError:
    # Fallback：如果无法导入，使用简化版本
    def calculate_importance(message, context, step_number=0):
        return type('obj', (object,), {'total': 0.5})()
    ImportanceLevel = None

try:
    from core.strategy.key_decision_detector import DecisionPoint, detect_key_decision
except ImportError:
    # Fallback
    def detect_key_decision(step_number, content, task_id, context_before=None, context_after=None):
        return None
    DecisionPoint = None


class ContextLayer(Enum):
    """上下文层级"""
    SHORT_TERM = "short_term"    # 短期记忆
    MEDIUM_TERM = "medium_term"  # 中期记忆（摘要）
    LONG_TERM = "long_term"      # 长期记忆（关键约束）


@dataclass
class ExecutionStep:
    """执行步骤记录"""
    step_number: int
    timestamp: float
    action: str
    result: str
    tool_name: str | None = None
    tool_params: dict | None = None
    success: bool = True
    is_key_decision: bool = False
    decision_info: DecisionPoint | None = None
    importance_score: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            'step_number': self.step_number,
            'timestamp': self.timestamp,
            'action': self.action,
            'result': self.result[:200] if len(self.result) > 200 else self.result,
            'tool_name': self.tool_name,
            'success': self.success,
            'is_key_decision': self.is_key_decision,
            'importance_score': self.importance_score
        }


@dataclass
class MediumSummary:
    """中期记忆摘要"""
    start_step: int
    end_step: int
    timestamp: float
    summary: str
    key_outcomes: list[str] = field(default_factory=list)
    key_decisions: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'step_range': f"{self.start_step}-{self.end_step}",
            'summary': self.summary,
            'key_outcomes': self.key_outcomes,
            'key_decisions': self.key_decisions
        }


@dataclass
class LongTermContext:
    """长期记忆上下文"""
    task_goal: str = ""
    constraints: list[str] = field(default_factory=list)
    key_decisions: list[DecisionPoint] = field(default_factory=list)
    critical_findings: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """转换为提示词文本"""
        lines = []

        if self.task_goal:
            lines.append(f"【任务目标】{self.task_goal}")

        if self.constraints:
            lines.append("\n【关键约束】")
            for c in self.constraints:
                lines.append(f"  ⚠ {c}")

        if self.key_decisions:
            lines.append("\n【关键决策】")
            for d in self.key_decisions[-5:]:
                lines.append(f"  步骤{d.step_number}: {d.description}")
                if d.selected_option:
                    lines.append(f"    → {d.selected_option}")

        if self.critical_findings:
            lines.append("\n【重要发现】")
            for f in self.critical_findings:
                lines.append(f"  • {f}")

        return "\n".join(lines)


class LongTaskContextManager:
    """
    长任务上下文管理器

    管理几小时长任务的记忆连续性：
    1. 分层存储：短期/中期/长期记忆分离
    2. 智能摘要：定期用AI压缩历史
    3. 关键约束：重要信息持续注入
    4. 恢复支持：从任意点恢复任务
    """

    # 配置参数
    SHORT_TERM_LIMIT = 10           # 短期记忆保留10步
    MEDIUM_TERM_LIMIT = 10          # 中期记忆最多保留10个摘要
    SUMMARY_INTERVAL = 20           # 每20步摘要一次
    CONSTRAINT_REMINDER_INTERVAL = 5  # 每5步提醒一次关键约束

    _instances: dict[str, 'LongTaskContextManager'] = {}

    def __new__(cls, task_id: str, user_id: str = "default"):
        """每个task_id一个实例"""
        key = f"{user_id}:{task_id}"
        if key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, task_id: str, user_id: str = "default"):
        self.task_id = task_id
        self.user_id = user_id

        # 三层记忆
        self.short_term: deque = deque(maxlen=self.SHORT_TERM_LIMIT)
        self.medium_term: list[MediumSummary] = []
        self.long_term = LongTermContext()

        # 执行状态
        self.current_step = 0
        self.start_time = time.time()
        self.last_summary_step = 0

        # 配置
        self.enable_ai_summary = True
        self.summary_model = "default"

        logger.info(f"[LongTaskContextManager] 初始化任务 {task_id}")

    def initialize_task(self, goal: str, constraints: list[str] = None):
        """初始化任务"""
        self.long_term.task_goal = goal
        if constraints:
            self.long_term.constraints.extend(constraints)

        logger.info(f"[LongTaskContextManager] 任务初始化: {goal[:50]}...")

    def add_step(self,
                 action: str,
                 result: str,
                 tool_name: str = None,
                 tool_params: dict = None,
                 success: bool = True,
                 context: dict = None) -> ExecutionStep:
        """
        添加执行步骤

        这是核心方法，每次AI执行一个步骤后调用
        """
        self.current_step += 1
        context = context or {}

        # 计算重要性
        msg = {'content': f"{action} {result}"}
        ctx = {'goal': self.long_term.task_goal}
        importance = calculate_importance(msg, ctx, self.current_step)

        # 检测关键决策
        decision = detect_key_decision(
            self.current_step,
            f"{action} {result}",
            self.task_id,
            context_before=context.get('before'),
            context_after=context.get('after', {'success': success})
        )

        # 创建步骤记录
        step = ExecutionStep(
            step_number=self.current_step,
            timestamp=time.time(),
            action=action,
            result=result,
            tool_name=tool_name,
            tool_params=tool_params,
            success=success,
            is_key_decision=decision is not None,
            decision_info=decision,
            importance_score=importance.total
        )

        # 添加到短期记忆
        self.short_term.append(step)

        # 关键决策存入长期记忆
        if decision and decision.significance.value >= 3:  # HIGH及以上
            self.long_term.key_decisions.append(decision)
            logger.info(f"[LongTaskContextManager] 记录关键决策: 步骤{self.current_step}")

        # 检查是否需要摘要
        if self.current_step - self.last_summary_step >= self.SUMMARY_INTERVAL:
            self._generate_medium_summary()

        return step

    def _generate_medium_summary(self):
        """生成中期记忆摘要"""
        if len(self.short_term) < 5:
            return

        steps_to_summarize = list(self.short_term)
        start_step = steps_to_summarize[0].step_number
        end_step = steps_to_summarize[-1].step_number

        # 提取关键结果
        key_outcomes = []
        for step in steps_to_summarize:
            if step.importance_score > 0.7:
                key_outcomes.append(f"步骤{step.step_number}: {step.result[:100]}")

        # 生成摘要（简化版，实际可调用AI生成）
        summary = self._ai_summarize_steps(steps_to_summarize)

        medium_summary = MediumSummary(
            start_step=start_step,
            end_step=end_step,
            timestamp=time.time(),
            summary=summary,
            key_outcomes=key_outcomes,
            key_decisions=[s.step_number for s in steps_to_summarize if s.is_key_decision]
        )

        self.medium_term.append(medium_summary)
        self.last_summary_step = end_step

        # 限制中期记忆大小
        if len(self.medium_term) > self.MEDIUM_TERM_LIMIT:
            self._merge_oldest_summaries()

        logger.info(f"[LongTaskContextManager] 生成摘要: 步骤{start_step}-{end_step}")

    def _ai_summarize_steps(self, steps: list[ExecutionStep]) -> str:
        """使用AI生成步骤摘要（简化版）"""
        if not steps:
            return "无执行记录"

        # 统计信息
        total = len(steps)
        successes = sum(1 for s in steps if s.success)
        failures = total - successes
        tools_used = {s.tool_name for s in steps if s.tool_name}

        # 提取关键步骤
        key_steps = [s for s in steps if s.importance_score > 0.7]

        # 构建摘要文本
        parts = [f"执行了{total}个步骤"]

        if failures > 0:
            parts.append(f"其中{failures}个失败")

        if tools_used:
            parts.append(f"使用了工具: {', '.join(tools_used)}")

        if key_steps:
            key_desc = '; '.join([s.action[:30] for s in key_steps[-3:]])
            parts.append(f"关键操作: {key_desc}")

        return '；'.join(parts)

    def _merge_oldest_summaries(self):
        """合并最老的摘要"""
        if len(self.medium_term) < 2:
            return

        # 合并前两个摘要
        first = self.medium_term[0]
        second = self.medium_term[1]

        merged = MediumSummary(
            start_step=first.start_step,
            end_step=second.end_step,
            timestamp=time.time(),
            summary=f"早期执行（步骤{first.start_step}-{second.end_step}）已归档",
            key_outcomes=first.key_outcomes + second.key_outcomes,
            key_decisions=first.key_decisions + second.key_decisions
        )

        self.medium_term = [merged] + self.medium_term[2:]

    def get_context_for_ai(self) -> str:
        """
        获取发送给AI的完整上下文

        这是最重要的方法，在每次调用AI前使用
        """
        parts = []

        # 1. 长期记忆（始终包含）
        long_term_text = self.long_term.to_prompt_text()
        if long_term_text:
            parts.append(long_term_text)

        # 2. 中期记忆（历史摘要）
        if self.medium_term:
            parts.append("\n【执行历史摘要】")
            for summary in self.medium_term[-3:]:  # 最近3个摘要
                parts.append(f"  步骤{summary.start_step}-{summary.end_step}: {summary.summary}")
                if summary.key_outcomes:
                    parts.append(f"    关键结果: {len(summary.key_outcomes)}项")

        # 3. 短期记忆（最近详情）
        if self.short_term:
            parts.append("\n【最近执行详情】")
            for step in list(self.short_term)[-5:]:  # 最近5步
                status = "✓" if step.success else "✗"
                parts.append(f"  {status} 步骤{step.step_number}: {step.action[:50]}...")
                if not step.success:
                    parts.append(f"    失败: {step.result[:100]}")

        # 4. 约束提醒（定期）
        if (self.current_step % self.CONSTRAINT_REMINDER_INTERVAL == 0 and
            self.long_term.constraints):
            parts.append("\n【约束提醒】")
            parts.append("请务必遵守以下约束：")
            for constraint in self.long_term.constraints:
                parts.append(f"  ⚠ {constraint}")

        return "\n\n".join(parts)

    def get_context_for_recovery(self, resume_step: int = None) -> str:
        """
        获取用于任务恢复的上下文

        精简版，只包含最关键的信息
        """
        parts = []

        # 任务目标
        parts.append(f"【恢复任务】{self.long_term.task_goal}")
        parts.append(f"从步骤{resume_step or self.current_step}恢复执行\n")

        # 关键约束
        if self.long_term.constraints:
            parts.append("【必须遵守的约束】")
            for c in self.long_term.constraints:
                parts.append(f"  ⚠ {c}")
            parts.append("")

        # 关键决策
        if self.long_term.key_decisions:
            parts.append("【已做出的关键决策】")
            for d in self.long_term.key_decisions:
                parts.append(f"  步骤{d.step_number}: {d.description}")
                if d.selected_option:
                    parts.append(f"    → 选择了: {d.selected_option}")
            parts.append("")

        # 当前进度摘要
        if self.medium_term:
            parts.append("【执行进度】")
            for summary in self.medium_term[-2:]:
                parts.append(f"  步骤{summary.start_step}-{summary.end_step}: {summary.summary}")

        return "\n".join(parts)

    def add_constraint(self, constraint: str):
        """添加关键约束"""
        if constraint not in self.long_term.constraints:
            self.long_term.constraints.append(constraint)
            logger.info(f"[LongTaskContextManager] 添加约束: {constraint}")

    def add_critical_finding(self, finding: str):
        """添加重要发现"""
        self.long_term.critical_findings.append(finding)

    def get_execution_stats(self) -> dict[str, Any]:
        """获取执行统计"""
        total_steps = self.current_step
        successful_steps = sum(1 for s in self.short_term if s.success)

        return {
            'task_id': self.task_id,
            'total_steps': total_steps,
            'successful_steps': successful_steps,
            'failed_steps': total_steps - successful_steps,
            'duration_seconds': time.time() - self.start_time,
            'key_decisions': len(self.long_term.key_decisions),
            'summaries_generated': len(self.medium_term)
        }

    def export_context(self) -> dict[str, Any]:
        """导出完整上下文（用于持久化）"""
        return {
            'task_id': self.task_id,
            'user_id': self.user_id,
            'current_step': self.current_step,
            'long_term': asdict(self.long_term),
            'medium_term': [asdict(s) for s in self.medium_term],
            'short_term': [asdict(s) for s in self.short_term],
            'start_time': self.start_time
        }

    @classmethod
    def import_context(cls, data: dict[str, Any]) -> 'LongTaskContextManager':
        """导入上下文（用于恢复）"""
        manager = cls(data['task_id'], data['user_id'])

        manager.current_step = data.get('current_step', 0)
        manager.start_time = data.get('start_time', time.time())

        # 恢复长期记忆
        lt_data = data.get('long_term', {})
        manager.long_term = LongTermContext(
            task_goal=lt_data.get('task_goal', ''),
            constraints=lt_data.get('constraints', []),
            key_decisions=[DecisionPoint(**d) for d in lt_data.get('key_decisions', [])],
            critical_findings=lt_data.get('critical_findings', [])
        )

        # 恢复中期记忆
        for s_data in data.get('medium_term', []):
            manager.medium_term.append(MediumSummary(**s_data))

        # 恢复短期记忆
        for s_data in data.get('short_term', []):
            step = ExecutionStep(**s_data)
            manager.short_term.append(step)

        return manager

    @classmethod
    def cleanup_old_instances(cls, max_age_hours: int = 24):
        """清理旧的实例"""
        current_time = time.time()
        to_remove = []

        for key, instance in cls._instances.items():
            age_hours = (current_time - instance.start_time) / 3600
            if age_hours > max_age_hours:
                to_remove.append(key)

        for key in to_remove:
            del cls._instances[key]
            logger.info(f"[LongTaskContextManager] 清理旧实例: {key}")


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_long_task_manager(task_id: str, user_id: str = "default") -> LongTaskContextManager:
    """获取长任务上下文管理器"""
    return LongTaskContextManager(task_id, user_id)


def initialize_long_task(task_id: str, goal: str,
                        constraints: list[str] = None,
                        user_id: str = "default") -> LongTaskContextManager:
    """初始化长任务"""
    manager = get_long_task_manager(task_id, user_id)
    manager.initialize_task(goal, constraints)
    return manager
