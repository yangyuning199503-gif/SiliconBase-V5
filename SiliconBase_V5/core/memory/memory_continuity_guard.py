#!/usr/bin/env python3
"""
记忆连续性守护者 - SiliconBase V5 长任务防遗忘核心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 检测AI是否偏离原始目标
  ✓ 定期注入关键约束提醒
  ✓ 自动纠正偏离的执行
  ✓ 保障几小时任务的目标一致性

核心机制：
  - 目标漂移检测：对比当前输出与原始目标
  - 约束注入：定期提醒关键约束
  - 干预建议：生成纠正提示词

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# 导入依赖
from core.strategy.importance_engine import get_importance_engine


class DriftLevel(Enum):
    """目标漂移级别"""
    NONE = 0        # 无漂移
    SLIGHT = 1      # 轻微漂移
    MODERATE = 2    # 中度漂移
    SEVERE = 3      # 严重漂移


class InterventionType(Enum):
    """干预类型"""
    NONE = "none"               # 无需干预
    GENTLE_NUDGE = "nudge"      # 温和提醒
    CONSTRAINT_INJECTION = "constraint"  # 约束注入
    STRONG_REMINDER = "strong"  # 强提醒
    EXECUTION_HALT = "halt"     # 暂停执行（严重偏离）


@dataclass
class DriftCheckResult:
    """漂移检测结果"""
    drift_level: DriftLevel
    drift_score: float  # 0-1
    intervention_type: InterventionType
    intervention_message: str
    suggestions: list[str]

    def should_intervene(self) -> bool:
        return self.drift_level.value >= DriftLevel.MODERATE.value


@dataclass
class ContinuityCheck:
    """连续性检查结果"""
    ok: bool
    intervention_type: str = ""
    reminder: str = ""
    constraints_to_inject: list[str] = None

    def __post_init__(self):
        if self.constraints_to_inject is None:
            self.constraints_to_inject = []


class MemoryContinuityGuard:
    """
    记忆连续性守护者

    在长时间任务中持续监控AI是否偏离目标：
    1. 定期检测目标漂移
    2. 关键约束持续注入
    3. 偏离时主动干预
    """

    # 配置
    CHECK_INTERVAL = 10             # 每10步检查一次
    DRIFT_THRESHOLD_SLIGHT = 0.3    # 轻微漂移阈值
    DRIFT_THRESHOLD_MODERATE = 0.5  # 中度漂移阈值
    DRIFT_THRESHOLD_SEVERE = 0.7    # 严重漂移阈值
    CONSTRAINT_INJECTION_INTERVAL = 5  # 每5步注入一次约束

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if MemoryContinuityGuard._initialized:
            return

        self._importance_engine = get_importance_engine()

        # 任务状态
        self._task_goals: dict[str, str] = {}  # task_id -> goal
        self._task_constraints: dict[str, list[str]] = {}  # task_id -> constraints
        self._execution_history: dict[str, deque] = {}  # task_id -> recent outputs

        # 统计
        self._stats = {
            'total_checks': 0,
            'drift_detected': 0,
            'interventions': 0
        }

        MemoryContinuityGuard._initialized = True
        logger.info("[MemoryContinuityGuard] 初始化完成")

    def register_task(self, task_id: str, goal: str, constraints: list[str] = None):
        """注册任务"""
        self._task_goals[task_id] = goal
        self._task_constraints[task_id] = constraints or []
        self._execution_history[task_id] = deque(maxlen=20)

        logger.info(f"[MemoryContinuityGuard] 注册任务: {task_id}")

    def check_continuity(self,
                         task_id: str,
                         current_output: str,
                         step_number: int) -> ContinuityCheck:
        """
        检查记忆连续性

        在Agent Loop中每次执行后调用
        """
        if task_id not in self._task_goals:
            return ContinuityCheck(ok=True)

        self._stats['total_checks'] += 1

        # 记录执行输出
        self._execution_history[task_id].append({
            'step': step_number,
            'output': current_output
        })

        # 定期漂移检测
        if step_number % self.CHECK_INTERVAL == 0:
            drift_result = self._detect_drift(task_id, current_output)

            if drift_result.drift_level.value >= DriftLevel.MODERATE.value:
                self._stats['drift_detected'] += 1

                if drift_result.should_intervene():
                    self._stats['interventions'] += 1
                    return ContinuityCheck(
                        ok=drift_result.intervention_type != InterventionType.EXECUTION_HALT,
                        intervention_type=drift_result.intervention_type.value,
                        reminder=drift_result.intervention_message,
                        constraints_to_inject=self._task_constraints[task_id]
                    )

        # 定期约束注入
        if step_number % self.CONSTRAINT_INJECTION_INTERVAL == 0:
            constraints = self._task_constraints.get(task_id, [])
            if constraints:
                return ContinuityCheck(
                    ok=True,
                    intervention_type=InterventionType.CONSTRAINT_INJECTION.value,
                    reminder=self._build_constraint_reminder(constraints),
                    constraints_to_inject=constraints
                )

        return ContinuityCheck(ok=True)

    def _detect_drift(self, task_id: str, current_output: str) -> DriftCheckResult:
        """
        检测目标漂移

        对比当前输出与原始目标的相似度
        """
        goal = self._task_goals.get(task_id, '')
        if not goal:
            return DriftCheckResult(
                drift_level=DriftLevel.NONE,
                drift_score=0.0,
                intervention_type=InterventionType.NONE,
                intervention_message="",
                suggestions=[]
            )

        # 计算与目标的相关性
        msg = {'content': current_output}
        ctx = {'goal': goal}
        score = self._importance_engine.calculate(msg, ctx)

        # 相关性低表示漂移
        relevance = score.total
        drift_score = 1.0 - relevance

        # 判断漂移级别
        if drift_score >= self.DRIFT_THRESHOLD_SEVERE:
            drift_level = DriftLevel.SEVERE
            intervention = InterventionType.EXECUTION_HALT
            message = self._build_strong_reminder(task_id, goal)
        elif drift_score >= self.DRIFT_THRESHOLD_MODERATE:
            drift_level = DriftLevel.MODERATE
            intervention = InterventionType.STRONG_REMINDER
            message = self._build_strong_reminder(task_id, goal)
        elif drift_score >= self.DRIFT_THRESHOLD_SLIGHT:
            drift_level = DriftLevel.SLIGHT
            intervention = InterventionType.GENTLE_NUDGE
            message = self._build_gentle_nudge(goal)
        else:
            drift_level = DriftLevel.NONE
            intervention = InterventionType.NONE
            message = ""

        suggestions = self._generate_suggestions(task_id, current_output, drift_level)

        return DriftCheckResult(
            drift_level=drift_level,
            drift_score=drift_score,
            intervention_type=intervention,
            intervention_message=message,
            suggestions=suggestions
        )

    def _build_gentle_nudge(self, goal: str) -> str:
        """构建温和提醒"""
        return f"【提醒】当前任务目标是：{goal[:100]}... 请确保执行方向与此一致。"

    def _build_strong_reminder(self, task_id: str, goal: str) -> str:
        """构建强提醒"""
        constraints = self._task_constraints.get(task_id, [])

        lines = [
            "⚠️ 【重要提醒】",
            f"原始任务目标：{goal}",
            "",
            "请注意，当前执行方向似乎偏离了原始目标。",
            "请重新评估当前行动是否与目标一致。",
            ""
        ]

        if constraints:
            lines.append("必须遵守的约束：")
            for c in constraints:
                lines.append(f"  ⚠ {c}")

        lines.append("\n请确认是否继续当前方向，或调整以符合目标。")

        return "\n".join(lines)

    def _build_constraint_reminder(self, constraints: list[str]) -> str:
        """构建约束提醒"""
        lines = ["【约束提醒】在执行时请牢记："]
        for c in constraints:
            lines.append(f"  ⚠ {c}")
        return "\n".join(lines)

    def _generate_suggestions(self, task_id: str,
                              current_output: str,
                              drift_level: DriftLevel) -> list[str]:
        """生成纠正建议"""
        suggestions = []

        # 分析当前输出
        if "搜索" in current_output and "保存" not in current_output:
            suggestions.append("已进行搜索，接下来请记得保存结果")

        if "打开" in current_output and "关闭" not in current_output:
            suggestions.append("已打开资源，请记得使用后关闭")

        # 基于漂移级别
        if drift_level == DriftLevel.SEVERE:
            suggestions.append("建议暂停当前操作，回顾原始目标")
            suggestions.append("考虑是否需要调整执行策略")
        elif drift_level == DriftLevel.MODERATE:
            suggestions.append("检查当前步骤是否偏离主线")
            suggestions.append("确认下一步是否回归目标")

        return suggestions

    def add_constraint(self, task_id: str, constraint: str):
        """动态添加约束"""
        if task_id not in self._task_constraints:
            self._task_constraints[task_id] = []
        if constraint not in self._task_constraints[task_id]:
            self._task_constraints[task_id].append(constraint)
            logger.info(f"[MemoryContinuityGuard] 任务{task_id}添加约束: {constraint}")

    def get_injection_context(self, task_id: str, step_number: int) -> str | None:
        """
        获取需要注入的上下文

        在构建AI提示词时调用，获取额外的约束提醒
        """
        constraints = self._task_constraints.get(task_id, [])
        if not constraints:
            return None

        # 每隔一定步骤注入
        if step_number % self.CONSTRAINT_INJECTION_INTERVAL == 0:
            return self._build_constraint_reminder(constraints)

        return None

    def get_execution_summary(self, task_id: str) -> dict[str, Any]:
        """获取执行摘要"""
        return {
            'task_id': task_id,
            'goal': self._task_goals.get(task_id, ''),
            'constraints': self._task_constraints.get(task_id, []),
            'total_checks': self._stats['total_checks'],
            'drift_detected': self._stats['drift_detected'],
            'interventions': self._stats['interventions']
        }

    def clear_task(self, task_id: str):
        """清理任务数据"""
        for store in [self._task_goals, self._task_constraints, self._execution_history]:
            if task_id in store:
                del store[task_id]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

_guard: MemoryContinuityGuard | None = None

def get_continuity_guard() -> MemoryContinuityGuard:
    """获取全局守护者实例"""
    global _guard
    if _guard is None:
        _guard = MemoryContinuityGuard()
    return _guard


def check_continuity(task_id: str, current_output: str, step_number: int) -> ContinuityCheck:
    """便捷函数：检查连续性"""
    return get_continuity_guard().check_continuity(task_id, current_output, step_number)


def register_task_with_guard(task_id: str, goal: str, constraints: list[str] = None):
    """便捷函数：注册任务"""
    get_continuity_guard().register_task(task_id, goal, constraints)
