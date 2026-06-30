#!/usr/bin/env python3
"""
重试策略（RetryPolicy）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：有状态的重试决策对象，绑定单个任务生命周期
职责：接收 TaskCompletionAnalyzer 的 AnalysisResult，输出 RetryDecision
约束：
  - 禁止修改外部 working_memory
  - 状态绑定到本实例，禁止动态 setattr
  - 纯决策逻辑，零 IO
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisResult:
    """
    任务完成分析结果——由 TaskCompletionAnalyzer 输出

    注：此 dataclass 放在 retry_policy.py 是因为 whitepaper 中
    RetryPolicy.decide() 接收此类型。实际应由 TaskCompletionAnalyzer 定义，
    此处放置以避免循环导入，后续整合时可迁移。
    """
    is_completed: bool
    confidence: float
    reasoning: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetryDecision:
    """
    重试决策——不可变结果数据
    """
    action: str           # "continue" / "yield" / "abort" / "complete"
    reason: str
    force_continue_count: int
    max_force_continues: int


class RetryPolicy:
    """
    重试策略——有状态，生命周期绑定到单个任务

    创建时机：任务开始时
    销毁时机：任务结束时
    """

    def __init__(self, max_force_continues: int = 3) -> None:
        self.max_force_continues: int = max_force_continues
        self.force_continue_count: int = 0
        self.decision_history: list[dict[str, Any]] = []

    def decide(self, analysis: AnalysisResult, current_round: int) -> RetryDecision:
        """
        根据分析结果做出重试决策

        决策逻辑：
        1. 任务已完成 → complete
        2. 强制继续次数超限 → abort
        3. 置信度过低 → yield（交由用户）
        4. 其他 → continue
        """
        # 1. 任务已完成
        if analysis.is_completed:
            return RetryDecision(
                action="complete",
                reason=analysis.reasoning,
                force_continue_count=self.force_continue_count,
                max_force_continues=self.max_force_continues
            )

        # 2. 增加强制继续计数
        self.force_continue_count += 1

        # 3. 强制继续次数超限
        if self.force_continue_count >= self.max_force_continues:
            return RetryDecision(
                action="abort",
                reason=f"强制继续次数已达上限 ({self.max_force_continues})",
                force_continue_count=self.force_continue_count,
                max_force_continues=self.max_force_continues
            )

        # 4. 置信度过低，建议交由用户
        if analysis.confidence < 0.3:
            return RetryDecision(
                action="yield",
                reason="置信度过低，建议用户介入",
                force_continue_count=self.force_continue_count,
                max_force_continues=self.max_force_continues
            )

        # 5. 默认继续
        return RetryDecision(
            action="continue",
            reason=analysis.reasoning,
            force_continue_count=self.force_continue_count,
            max_force_continues=self.max_force_continues
        )

    def record_decision(self, decision: RetryDecision) -> None:
        """记录决策历史，用于后续复盘"""
        self.decision_history.append({
            "action": decision.action,
            "reason": decision.reason,
            "round": len(self.decision_history)
        })
