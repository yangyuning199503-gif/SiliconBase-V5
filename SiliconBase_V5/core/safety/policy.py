#!/usr/bin/env python3
"""
安全策略（SafetyPolicy）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：安全系统三层拆分之策略层
职责：纯同步规则引擎，零 IO，将 DetectionResult 映射为 SafetyDecision
约束：
  - 禁止调用 LLM 或任何异步操作
  - 纯规则映射，无状态修改
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.safety.detector import DetectionResult


class SafetyAction(Enum):
    """安全动作枚举"""
    PASS = "pass"           # 通过，无需处理
    ANNOTATE = "annotate"   # 标注不确定性
    WARN = "warn"           # 警告用户
    RETRY = "retry"         # 要求重试


@dataclass(frozen=True)
class SafetyDecision:
    """
    安全决策——不可变数据契约
    """
    action: SafetyAction
    reason: str
    processed_response: str   # 如需修改响应（如前置警告）
    metadata: dict[str, Any]  # 统计/日志用


def inject_hallucination_prompt(base_prompt: str, flagged: bool = False) -> str:
    """
    向提示词注入幻觉检测相关约束
    【P1 迁移】从 hallucination_integration.py 迁移到 policy.py
    """
    try:
        from core.safety.hallucination_detector import SELF_QUESTIONING_PROMPT
    except ImportError:
        SELF_QUESTIONING_PROMPT = ""

    if flagged:
        extra_constraint = """
        ⚠️ 【重要提醒】你之前的回答被检测到存在不确定或可能错误的表述。
        请这次特别注意：
        1. 不确定的信息明确说"我不确定"
        2. 不要编造具体数字、日期或人名
        3. 基于记忆的内容请明确标注来源
        """
        return f"{base_prompt}\n\n{extra_constraint}\n\n{SELF_QUESTIONING_PROMPT}"
    else:
        return f"{base_prompt}\n\n{SELF_QUESTIONING_PROMPT}"


class SafetyPolicy:
    """
    安全策略——纯同步规则引擎，零 IO

    将 DetectionResult 映射为 SafetyDecision。
    """

    STRATEGIES: dict[str, SafetyAction] = {
        "none": SafetyAction.PASS,
        "low": SafetyAction.PASS,
        "medium": SafetyAction.ANNOTATE,
        "high": SafetyAction.WARN,
        "critical": SafetyAction.RETRY,
    }

    def apply(self, result: DetectionResult, ai_response: str) -> SafetyDecision:
        """
        应用安全策略

        Args:
            result: 检测结果（来自 HallucinationDetector）
            ai_response: 原始 AI 响应

        Returns:
            SafetyDecision: 纯数据决策结果
        """
        action = self.STRATEGIES.get(result.level, SafetyAction.PASS)

        if action == SafetyAction.WARN:
            notes = "; ".join(result.verification_notes[:2])
            reason = f"AI 响应存在不确定性 (分数={result.score:.2f}). 备注: {notes}"
            return SafetyDecision(
                action=action,
                reason=reason,
                processed_response=ai_response,
                metadata={"level": result.level, "score": result.score, "notes": result.verification_notes}
            )

        if action == SafetyAction.RETRY:
            return SafetyDecision(
                action=action,
                reason="检测到严重幻觉，建议重试",
                processed_response=ai_response,
                metadata={"level": result.level, "score": result.score}
            )

        if action == SafetyAction.ANNOTATE:
            return SafetyDecision(
                action=action,
                reason="存在中等不确定性，已标注",
                processed_response=ai_response,
                metadata={"level": result.level, "score": result.score}
            )

        # PASS
        return SafetyDecision(
            action=action,
            reason="通过安全检测",
            processed_response=ai_response,
            metadata={"level": result.level, "score": result.score}
        )
