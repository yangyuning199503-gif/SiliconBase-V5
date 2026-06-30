#!/usr/bin/env python3
"""
关键决策点检测器 - SiliconBase V5 长任务连续性核心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 识别任务执行中的关键决策点
  ✓ 基于内容、结构、上下文变化的多维度检测
  ✓ 支持自定义决策模式
  ✓ 生成决策摘要用于断点恢复

关键决策类型：
  - 分支决策点：if/else选择、路径抉择
  - 状态转换点：开始/暂停/恢复/完成
  - 外部交互点：工具调用、用户输入
  - 错误恢复点：异常处理、失败重试

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# 确保日志处理器存在
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(name)s] %(levelname)s | %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class DecisionType(Enum):
    """决策类型枚举"""
    BRANCH = "branch"           # 分支决策（if/else选择）
    STATE_CHANGE = "state_change"  # 状态转换
    TOOL_CALL = "tool_call"     # 工具调用
    USER_INPUT = "user_input"   # 用户输入点
    ERROR_RECOVERY = "error_recovery"  # 错误恢复
    MILESTONE = "milestone"     # 里程碑
    CHECKPOINT = "checkpoint"   # 检查点


class DecisionSignificance(Enum):
    """决策重要性级别"""
    CRITICAL = 4    # 关键 - 影响整个任务走向
    HIGH = 3        # 高 - 重要分支或状态
    MEDIUM = 2      # 中 - 常规决策点
    LOW = 1         # 低 - 轻微调整


@dataclass
class DecisionPoint:
    """决策点数据类"""
    step_number: int
    decision_type: DecisionType
    significance: DecisionSignificance
    description: str
    context_before: dict[str, Any] = field(default_factory=dict)
    context_after: dict[str, Any] = field(default_factory=dict)
    alternatives: list[str] = field(default_factory=list)
    selected_option: str = ""
    reasoning: str = ""
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'step_number': self.step_number,
            'decision_type': self.decision_type.value,
            'significance': self.significance.name,
            'description': self.description,
            'selected_option': self.selected_option,
            'reasoning': self.reasoning,
            'alternatives': self.alternatives,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


@dataclass
class DecisionSummary:
    """决策摘要（用于恢复时提供给AI）"""
    total_decisions: int
    critical_decisions: list[DecisionPoint]
    current_path: list[int]  # 步骤序号列表
    key_constraints: list[str]

    def to_prompt_text(self) -> str:
        """转换为提示词文本"""
        lines = ["【关键决策历史】"]

        for decision in self.critical_decisions[-5:]:  # 最近5个关键决策
            lines.append(f"  步骤{decision.step_number}: {decision.description}")
            lines.append(f"    选择: {decision.selected_option}")
            if decision.reasoning:
                lines.append(f"    理由: {decision.reasoning}")

        if self.key_constraints:
            lines.append("\n【关键约束】")
            for constraint in self.key_constraints:
                lines.append(f"  - {constraint}")

        return "\n".join(lines)


class KeyDecisionPatterns:
    """关键决策模式库"""

    # 分支决策模式
    BRANCH_PATTERNS = [
        (r'(?:选择|决定|判断).{0,15}(?:使用|调用|执行|采用|采取)', DecisionSignificance.HIGH),
        (r'(?:如果|假如|若).{0,25}(?:否则|不然|则|就)', DecisionSignificance.CRITICAL),
        (r'(?:方案A|方案B|选项1|选项2|第一种|第二种)', DecisionSignificance.HIGH),
        (r'(?:二选一|多选一|在.*之间选择)', DecisionSignificance.HIGH),
        (r'(?:更好的办法|更优|更合适|建议|推荐)', DecisionSignificance.MEDIUM),
    ]

    # 状态转换模式
    STATE_CHANGE_PATTERNS = [
        (r'(?:开始|启动|着手).{0,10}(?:任务|执行|处理|操作)', DecisionSignificance.HIGH),
        (r'(?:暂停|中断|停止|等待).{0,10}(?:用户|确认|输入)', DecisionSignificance.CRITICAL),
        (r'(?:恢复|继续|重新开始).{0,10}(?:任务|执行)', DecisionSignificance.HIGH),
        (r'(?:完成|结束|搞定|全部完成|顺利结束)', DecisionSignificance.CRITICAL),
        (r'(?:进入|切换到|转为).{0,10}(?:阶段|模式|状态)', DecisionSignificance.MEDIUM),
    ]

    # 工具调用模式
    TOOL_CALL_PATTERNS = [
        (r'(?:调用|使用|执行).{0,10}(?:工具|函数|API)', DecisionSignificance.MEDIUM),
        (r'(?:TOOL_CALL|tool_call|工具调用)', DecisionSignificance.MEDIUM),
    ]

    # 用户输入模式
    USER_INPUT_PATTERNS = [
        (r'(?:等待|需要|请).{0,10}(?:用户|你|您).{0,10}(?:输入|确认|提供)', DecisionSignificance.HIGH),
        (r'(?:请输入|请确认|请提供|请选择)', DecisionSignificance.HIGH),
        (r'(?:由用户决定|让用户选择|交给用户)', DecisionSignificance.CRITICAL),
    ]

    # 错误恢复模式
    ERROR_RECOVERY_PATTERNS = [
        (r'(?:遇到|出现|发生).{0,10}(?:错误|异常|失败|问题)', DecisionSignificance.HIGH),
        (r'(?:重试|再次尝试|换一种方式|备用方案)', DecisionSignificance.HIGH),
        (r'(?:跳过|忽略|绕过).{0,10}(?:这个|当前).{0,10}(?:错误|步骤)', DecisionSignificance.MEDIUM),
        (r'(?:回滚|撤销|恢复到).{0,10}(?:之前|上一个)', DecisionSignificance.CRITICAL),
    ]

    # 里程碑模式
    MILESTONE_PATTERNS = [
        (r'(?:第[一二三123]步|阶段[一二三123]|Step\s*\d+).{0,5}(?:完成|结束)', DecisionSignificance.HIGH),
        (r'(?:里程碑|关键节点|重要进展).{0,10}(?:达成|完成|实现)', DecisionSignificance.HIGH),
        (r'(?:25%|50%|75%|100%).{0,5}(?:完成|进度)', DecisionSignificance.MEDIUM),
    ]


class KeyDecisionDetector:
    """
    关键决策点检测器

    检测任务执行过程中的关键节点，用于：
    1. 智能保存检查点（只在关键决策点保存）
    2. 恢复时提供关键决策历史
    3. 生成任务执行的关键路径摘要
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 significance_threshold: DecisionSignificance = DecisionSignificance.MEDIUM,
                 max_decisions_per_task: int = 50):

        if KeyDecisionDetector._initialized:
            return

        self.significance_threshold = significance_threshold
        self.max_decisions_per_task = max_decisions_per_task

        # 决策历史
        self._decisions: dict[str, list[DecisionPoint]] = {}  # task_id -> decisions
        self._key_constraints: dict[str, set[str]] = {}  # task_id -> constraints

        # 统计
        self._stats = {
            'total_detected': 0,
            'by_type': {t.value: 0 for t in DecisionType},
            'by_significance': {s.name: 0 for s in DecisionSignificance}
        }

        KeyDecisionDetector._initialized = True
        logger.info("[KeyDecisionDetector] 初始化完成")

    def detect(self,
               step_number: int,
               content: str,
               task_id: str,
               context_before: dict[str, Any] = None,
               context_after: dict[str, Any] = None) -> DecisionPoint | None:
        """
        检测单个步骤是否为关键决策点

        Args:
            step_number: 步骤序号
            content: 步骤内容/描述
            task_id: 任务ID
            context_before: 执行前上下文
            context_after: 执行后上下文

        Returns:
            DecisionPoint如果是关键决策点，否则None
        """
        context_before = context_before or {}
        context_after = context_after or {}

        # 检测各类型决策
        detection_results = []

        # 1. 分支决策检测
        branch_result = self._detect_branch(content, context_before, context_after)
        if branch_result:
            detection_results.append(branch_result)

        # 2. 状态转换检测
        state_result = self._detect_state_change(content, context_before, context_after)
        if state_result:
            detection_results.append(state_result)

        # 3. 用户输入检测
        user_result = self._detect_user_input(content)
        if user_result:
            detection_results.append(user_result)

        # 4. 错误恢复检测
        error_result = self._detect_error_recovery(content, context_after)
        if error_result:
            detection_results.append(error_result)

        # 5. 里程碑检测
        milestone_result = self._detect_milestone(content, step_number)
        if milestone_result:
            detection_results.append(milestone_result)

        if not detection_results:
            return None

        # 选择最重要的决策类型
        best_result = max(detection_results, key=lambda x: x[1].value)
        decision_type, significance = best_result

        # 检查是否达到阈值
        if significance.value < self.significance_threshold.value:
            return None

        # 提取决策信息
        description, selected, reasoning, alternatives = self._extract_decision_info(
            content, decision_type, context_after
        )

        # 创建决策点
        decision = DecisionPoint(
            step_number=step_number,
            decision_type=decision_type,
            significance=significance,
            description=description,
            context_before=context_before,
            context_after=context_after,
            alternatives=alternatives,
            selected_option=selected,
            reasoning=reasoning,
            timestamp=datetime.now()
        )

        # 记录决策
        self._record_decision(task_id, decision)

        self._stats['total_detected'] += 1
        self._stats['by_type'][decision_type.value] += 1
        self._stats['by_significance'][significance.name] += 1

        logger.debug(f"[KeyDecisionDetector] 检测到{significance.name}级别{decision_type.value}: {description[:50]}...")

        return decision

    def _detect_branch(self, content: str,
                       context_before: dict,
                       context_after: dict) -> tuple[DecisionType, DecisionSignificance] | None:
        """检测分支决策"""
        for pattern, significance in KeyDecisionPatterns.BRANCH_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (DecisionType.BRANCH, significance)
        return None

    def _detect_state_change(self, content: str,
                             context_before: dict,
                             context_after: dict) -> tuple[DecisionType, DecisionSignificance] | None:
        """检测状态转换"""
        # 检查内容中的状态变化模式
        for pattern, significance in KeyDecisionPatterns.STATE_CHANGE_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (DecisionType.STATE_CHANGE, significance)

        # 检查上下文中的状态变化
        status_before = context_before.get('status')
        status_after = context_after.get('status')
        if status_before and status_after and status_before != status_after:
            # 状态确实发生了变化
            significance = DecisionSignificance.HIGH
            if status_after in ['paused', 'error']:
                significance = DecisionSignificance.CRITICAL
            return (DecisionType.STATE_CHANGE, significance)

        return None

    def _detect_user_input(self, content: str) -> tuple[DecisionType, DecisionSignificance] | None:
        """检测用户输入点"""
        for pattern, significance in KeyDecisionPatterns.USER_INPUT_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (DecisionType.USER_INPUT, significance)
        return None

    def _detect_error_recovery(self, content: str,
                               context_after: dict) -> tuple[DecisionType, DecisionSignificance] | None:
        """检测错误恢复"""
        # 检查错误模式
        for pattern, significance in KeyDecisionPatterns.ERROR_RECOVERY_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (DecisionType.ERROR_RECOVERY, significance)

        # 检查上下文中的错误状态
        if context_after.get('error') or context_after.get('success') is False:
            return (DecisionType.ERROR_RECOVERY, DecisionSignificance.HIGH)

        return None

    def _detect_milestone(self, content: str, step_number: int) -> tuple[DecisionType, DecisionSignificance] | None:
        """检测里程碑"""
        for pattern, significance in KeyDecisionPatterns.MILESTONE_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (DecisionType.MILESTONE, significance)

        # 检查是否是25/50/75/100%的进度点
        progress_match = re.search(r'(\d+)%', content)
        if progress_match:
            progress = int(progress_match.group(1))
            if progress in [25, 50, 75, 100]:
                return (DecisionType.MILESTONE, DecisionSignificance.MEDIUM)

        return None

    def _extract_decision_info(self, content: str,
                               decision_type: DecisionType,
                               context_after: dict) -> tuple[str, str, str, list[str]]:
        """提取决策信息"""
        description = content[:100] + "..." if len(content) > 100 else content

        # 尝试提取选择
        selected = ""
        alternatives = []

        if decision_type == DecisionType.BRANCH:
            # 提取选择结果
            choice_match = re.search(r'(?:选择|决定|采用).{0,5}["「【]([^"」\]]+)["」\]]', content)
            if choice_match:
                selected = choice_match.group(1)

            # 提取选项
            options = re.findall(r'(?:选项|方案|选择)([A-D123]|[一二三四])', content)
            alternatives = [f"选项{opt}" for opt in options]

        elif decision_type == DecisionType.TOOL_CALL:
            tool_name = context_after.get('tool_name', '')
            selected = tool_name
            description = f"调用工具: {tool_name}"

        # 提取推理过程
        reasoning = ""
        reasoning_match = re.search(r'(?:因为|由于|理由|原因).{0,50}', content)
        if reasoning_match:
            reasoning = reasoning_match.group(0)

        return description, selected, reasoning, alternatives

    def _record_decision(self, task_id: str, decision: DecisionPoint):
        """记录决策点"""
        if task_id not in self._decisions:
            self._decisions[task_id] = []

        self._decisions[task_id].append(decision)

        # 限制决策历史长度
        if len(self._decisions[task_id]) > self.max_decisions_per_task:
            # 移除最早的低重要性决策
            low_importance = [d for d in self._decisions[task_id]
                            if d.significance.value <= DecisionSignificance.LOW.value]
            if low_importance:
                self._decisions[task_id].remove(low_importance[0])

    def register_key_constraint(self, task_id: str, constraint: str):
        """注册关键约束（如"必须保存到指定目录"）"""
        if task_id not in self._key_constraints:
            self._key_constraints[task_id] = set()
        self._key_constraints[task_id].add(constraint)

    def get_decision_summary(self, task_id: str) -> DecisionSummary:
        """获取任务的决策摘要"""
        decisions = self._decisions.get(task_id, [])
        constraints = list(self._key_constraints.get(task_id, set()))

        # 筛选关键决策
        critical_decisions = [
            d for d in decisions
            if d.significance.value >= DecisionSignificance.HIGH.value
        ]

        # 当前路径（所有步骤序号）
        current_path = [d.step_number for d in decisions]

        return DecisionSummary(
            total_decisions=len(decisions),
            critical_decisions=critical_decisions,
            current_path=current_path,
            key_constraints=constraints
        )

    def should_save_checkpoint(self, step_number: int, task_id: str) -> bool:
        """
        判断是否应该在此步骤保存检查点

        策略：只在关键决策点保存，避免频繁保存
        """
        decisions = self._decisions.get(task_id, [])

        # 查找最近的决策
        recent_decisions = [d for d in decisions if d.step_number == step_number]

        if not recent_decisions:
            return False

        # 检查是否有高重要性决策
        return any(decision.significance.value >= DecisionSignificance.HIGH.value for decision in recent_decisions)

    def get_key_context_for_recovery(self, task_id: str, current_step: int) -> str:
        """
        获取恢复时需要的关键上下文

        生成精简的决策历史，用于任务恢复时提供给AI
        """
        summary = self.get_decision_summary(task_id)

        # 只包含当前步骤之前的决策
        relevant_decisions = [
            d for d in summary.critical_decisions
            if d.step_number <= current_step
        ]

        # 生成恢复上下文
        lines = ["【任务恢复 - 关键决策历史】"]
        lines.append(f"共{len(relevant_decisions)}个关键决策点：\n")

        for decision in relevant_decisions[-10:]:  # 最近10个
            lines.append(f"步骤{decision.step_number}: [{decision.decision_type.value}] {decision.description}")
            if decision.selected_option:
                lines.append(f"  → 选择: {decision.selected_option}")
            if decision.reasoning:
                lines.append(f"  → 理由: {decision.reasoning}")
            lines.append("")

        if summary.key_constraints:
            lines.append("\n【必须遵守的约束】")
            for constraint in summary.key_constraints:
                lines.append(f"  ⚠ {constraint}")

        return "\n".join(lines)

    def clear_task_history(self, task_id: str):
        """清除任务历史"""
        if task_id in self._decisions:
            del self._decisions[task_id]
        if task_id in self._key_constraints:
            del self._key_constraints[task_id]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

_detector: KeyDecisionDetector | None = None

def get_key_decision_detector() -> KeyDecisionDetector:
    """获取全局检测器实例"""
    global _detector
    if _detector is None:
        _detector = KeyDecisionDetector()
    return _detector


def detect_key_decision(step_number: int,
                       content: str,
                       task_id: str,
                       context_before: dict = None,
                       context_after: dict = None) -> DecisionPoint | None:
    """便捷函数：检测关键决策点"""
    return get_key_decision_detector().detect(
        step_number, content, task_id, context_before, context_after
    )


def should_save_checkpoint(step_number: int, task_id: str) -> bool:
    """便捷函数：判断是否应保存检查点"""
    return get_key_decision_detector().should_save_checkpoint(step_number, task_id)
