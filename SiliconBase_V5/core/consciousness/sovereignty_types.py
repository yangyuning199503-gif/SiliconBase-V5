"""
主权-翻译-执行-记忆四层架构的共享数据结构
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Intent:
    """L2 翻译层输出的结构化意图。"""
    intent_type: str = "chat"          # chat | task | control | query
    complexity: str = "low"            # low | medium | high
    sentiment: str = "neutral"         # neutral | urgent | negative
    target_plate: str | None = None # 控制类意图的目标板块
    risk_flags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_input: str = ""
    # 附加结构化信息，如任务关键词、控制动作等
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.risk_flags) or self.confidence < 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "complexity": self.complexity,
            "sentiment": self.sentiment,
            "target_plate": self.target_plate,
            "risk_flags": self.risk_flags,
            "confidence": self.confidence,
            "raw_input": self.raw_input,
            "meta": self.meta,
        }


@dataclass
class RoutingDecision:
    """L1 主权层输出的路由裁决。"""
    route_type: str = "unknown"        # quick_chat | agent_loop | plate_command | user_expression | queue | unknown
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    intent: Intent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_type": self.route_type,
            "payload": self.payload,
            "reason": self.reason,
            "confidence": self.confidence,
            "intent": self.intent.to_dict() if self.intent else None,
        }


@dataclass
class ActionResult:
    """L3 执行层返回的执行结果，必须回流 L1。"""
    route_type: str = ""
    success: bool = False
    output: str = ""
    error: str | None = None
    plate_used: str | None = None
    tool_used: str | None = None
    raw_input: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_type": self.route_type,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "plate_used": self.plate_used,
            "tool_used": self.tool_used,
            "raw_input": self.raw_input,
            "metadata": self.metadata,
        }
