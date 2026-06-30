"""
DirectiveTranslator - 把意识线程的内部状态翻译成可执行的 ConsciousnessDirective。

ConsciousnessDirective 是意识 → AgentLoop 的硬连接：
- 不是 prompt 装饰
- 带 TTL 和作用域
- 必须被 AgentLoop 在工具选择层强制消费
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, TypedDict


class DirectiveType(str, Enum):
    FORCE_TOOL = "FORCE_TOOL"
    AVOID_TOOL = "AVOID_TOOL"
    ASK_USER = "ASK_USER"
    SWITCH_GOAL = "SWITCH_GOAL"
    PAUSE = "PAUSE"
    REFLECT = "REFLECT"


class ConsciousnessDirective(TypedDict):
    directive_type: str
    target: str | None
    reason: str
    confidence: float
    expires_at: float
    source: str
    context: dict[str, Any]


class DirectiveTranslator:
    """把 UKF 状态、世界模型建议、内在动机翻译成指令。"""

    def from_world_model(
        self,
        suggestion: dict[str, Any] | None,
        available_tools: list[str],
    ) -> list[ConsciousnessDirective]:
        """从世界模型建议生成 FORCE_TOOL 指令。"""
        directives: list[ConsciousnessDirective] = []
        if not suggestion:
            return directives

        if suggestion.get("type") == "mcts_plan":
            best = suggestion.get("best_action")
            if best and best in available_tools:
                directives.append({
                    "directive_type": DirectiveType.FORCE_TOOL.value,
                    "target": best,
                    "reason": f"world_model MCTS 推荐首步: {suggestion.get('reason', '')}",
                    "confidence": float(suggestion.get("confidence", 0.5)),
                    "expires_at": time.monotonic() + 60.0,
                    "source": "world_model",
                    "context": {
                        "plan": suggestion.get("action_sequence", [])[:3],
                    },
                })
        return directives

    def from_ukf_state(
        self,
        ukf_state: dict[str, Any],
        thought: str,
        available_tools: list[str],
    ) -> list[ConsciousnessDirective]:
        """从 UKF 状态生成 FORCE_TOOL / REFLECT 指令。"""
        directives: list[ConsciousnessDirective] = []
        state_vec = ukf_state.get("state")
        if state_vec is None:
            return directives

        try:
            flat = list(state_vec)
            action_will = float(flat[0])
            reflect_tendency = float(flat[1])
        except Exception:
            action_will = float(ukf_state.get("action_will", 0.0))
            reflect_tendency = float(ukf_state.get("reflect_tendency", 0.0))

        if action_will > 0.45:
            target = self._extract_tool_from_thought(thought, available_tools)
            if target:
                directives.append({
                    "directive_type": DirectiveType.FORCE_TOOL.value,
                    "target": target,
                    "reason": "UKF action_will 高于阈值",
                    "confidence": min(1.0, action_will),
                    "expires_at": time.monotonic() + 30.0,
                    "source": "consciousness_ukf",
                    "context": {"action_will": action_will},
                })

        if reflect_tendency > 0.50:
            directives.append({
                "directive_type": DirectiveType.REFLECT.value,
                "target": None,
                "reason": "UKF reflect_tendency 高于阈值",
                "confidence": min(1.0, reflect_tendency),
                "expires_at": time.monotonic() + 30.0,
                "source": "consciousness_ukf",
                "context": {"reflect_tendency": reflect_tendency},
            })

        return directives

    def from_intrinsic_drive(self, drive: Any) -> list[ConsciousnessDirective]:
        """从内在动机生成 PAUSE / ASK_USER 指令。"""
        directives: list[ConsciousnessDirective] = []
        if drive is None:
            return directives

        should_rest = getattr(drive, "should_rest", False)
        energy_level = getattr(drive, "energy_level", 1.0)
        if should_rest or energy_level < 0.2:
            directives.append({
                "directive_type": DirectiveType.PAUSE.value,
                "target": None,
                "reason": "能量低，建议休息",
                "confidence": min(1.0, 1.0 - energy_level),
                "expires_at": time.monotonic() + 300.0,
                "source": "intrinsic_motivation",
                "context": {"energy_level": energy_level},
            })
        return directives

    def _extract_tool_from_thought(
        self,
        thought: str,
        available_tools: list[str],
    ) -> str | None:
        """启发式：从思考文本中提取最匹配的工具名。"""
        if not thought or not available_tools:
            return None
        thought_lower = thought.lower()
        for tool in available_tools:
            if tool.lower() in thought_lower:
                return tool
        return None
