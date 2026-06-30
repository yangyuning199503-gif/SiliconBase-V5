"""
裁决引擎 (DecisionEngine)

L1 主权层核心：基于 Intent + SelfState + 最近叙事 + 系统负载，输出 RoutingDecision。
硬编码规则，可解释，可替换为数据驱动策略表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.consciousness.self_narrative import SelfNarrativeLog
from core.consciousness.self_state import SelfState
from core.consciousness.sovereignty_types import Intent, RoutingDecision

try:
    from core.logger import logger
except Exception:
    logger = logging.getLogger(__name__)


@dataclass
class DecisionConfig:
    """裁决引擎配置。"""
    llm_budget_threshold: float = 0.95   # LLM 额度低于 5% 时降级
    high_load_recent_failures: int = 2   # 最近叙事中连续失败次数阈值
    max_pending_user_requests: int = 5   # 待办用户请求超过此数时排队


class DecisionEngine:
    """本地裁决引擎：硬编码规则，输出三选一路由。"""

    def __init__(self, user_id: str, config: DecisionConfig | None = None):
        self.user_id = user_id
        self.config = config or DecisionConfig()

    def evaluate_and_decide(
        self,
        intent: Intent,
        state: SelfState,
        narrative: SelfNarrativeLog,
        system_load: dict | None = None,
    ) -> RoutingDecision:
        """
        基于意图、自我状态、叙事、系统负载做路由裁决。
        """
        system_load = system_load or {}
        recent = narrative.recent(5)
        narrative.recent_text(3)

        # 1. 风险标记 → 要求确认（不直接执行）
        if intent.requires_confirmation or intent.risk_flags:
            return RoutingDecision(
                route_type="user_expression",
                payload={
                    "text": self._build_confirmation_text(intent),
                    "reply_to_user": True,
                    "requires_confirmation": True,
                },
                reason=f"意图存在风险标记: {intent.risk_flags}，需要确认",
                confidence=intent.confidence,
                intent=intent,
            )

        # 2. 系统负载高 → 降级或排队
        if self._is_system_overloaded(state, system_load, recent):
            if intent.intent_type == "chat" and intent.complexity == "low":
                pass  # 低复杂度闲聊仍可处理
            else:
                state.push_pending_request(
                    source="user",
                    summary=f"系统负载高，意图暂挂: {intent.raw_input[:60]}",
                    priority=5,
                    meta={"deferred_intent": intent.to_dict()},
                )
                return RoutingDecision(
                    route_type="user_expression",
                    payload={
                        "text": "当前系统较忙，你的请求已加入待处理队列，稍后会继续处理。",
                        "reply_to_user": True,
                    },
                    reason="系统负载高，意图进入队列",
                    confidence=0.9,
                    intent=intent,
                )

        # 3. 闲聊低复杂度 → 直接表达
        if intent.intent_type == "chat":
            return RoutingDecision(
                route_type="quick_chat",
                payload={
                    "raw_input": intent.raw_input,
                    "topic": intent.meta.get("topic"),
                    "reply_to_user": True,
                },
                reason="低复杂度闲聊，直接表达",
                confidence=intent.confidence,
                intent=intent,
            )

        # 4. 查询类 → 直接表达（由 quick_chat 或表达引擎处理）
        if intent.intent_type == "query":
            return RoutingDecision(
                route_type="quick_chat",
                payload={
                    "raw_input": intent.raw_input,
                    "topic": intent.meta.get("topic"),
                    "reply_to_user": True,
                },
                reason="状态查询类，直接表达",
                confidence=intent.confidence,
                intent=intent,
            )

        # 5. 控制类 + 目标板块 → 板块命令
        if intent.intent_type == "control" and intent.target_plate:
            action = intent.meta.get("action", "handle_control")
            return RoutingDecision(
                route_type="plate_command",
                payload={
                    "plate_id": intent.target_plate,
                    "action": action,
                    "params": {
                        "control_type": intent.meta.get("control_type"),
                        "raw_input": intent.raw_input,
                    },
                },
                reason=f"控制指令，调度板块 {intent.target_plate}",
                confidence=intent.confidence,
                intent=intent,
            )

        # 6. 任务类 → 生成 task_package 进入 AgentLoop
        if intent.intent_type == "task":
            package = self._build_task_package(intent, state)
            return RoutingDecision(
                route_type="agent_loop",
                payload={
                    "task_package": package,
                    "raw_input": intent.raw_input,
                    "force_vision": intent.meta.get("force_vision", False),
                },
                reason="任务类意图，生成 LLM 任务包",
                confidence=intent.confidence,
                intent=intent,
            )

        # 兜底：无法判断 → 要求确认
        return RoutingDecision(
            route_type="user_expression",
            payload={
                "text": f"我没太理解你的意思，你是想让我处理「{intent.raw_input[:40]}」吗？",
                "reply_to_user": True,
                "requires_confirmation": True,
            },
            reason="意图无法可靠裁决，请求确认",
            confidence=0.5,
            intent=intent,
        )

    def decide_after_action(
        self,
        result: dict,
        state: SelfState,
        narrative: SelfNarrativeLog,
    ) -> RoutingDecision | None:
        """
        执行结果回流后，决定下一步。
        P0 只处理：成功完成 → 告知用户；失败 → 简单告警。
        """
        success = result.get("success", False)
        route_type = result.get("route_type", "")
        output = result.get("output", "")

        if route_type == "agent_loop" and success:
            # 任务完成，告知用户
            return RoutingDecision(
                route_type="user_expression",
                payload={
                    "text": output[:200] if output else "任务已完成。",
                    "reply_to_user": True,
                },
                reason="AgentLoop 任务成功完成，告知用户",
                confidence=0.9,
            )

        if route_type == "plate_command" and success:
            return RoutingDecision(
                route_type="user_expression",
                payload={
                    "text": "已调度完成。",
                    "reply_to_user": True,
                },
                reason="板块命令执行成功，告知用户",
                confidence=0.9,
            )

        if not success:
            return RoutingDecision(
                route_type="user_expression",
                payload={
                    "text": "执行时遇到了问题，我会记录并稍后重试。",
                    "reply_to_user": True,
                },
                reason="执行失败，告知用户",
                confidence=0.8,
            )

        return None

    def _is_system_overloaded(
        self,
        state: SelfState,
        system_load: dict,
        recent,
    ) -> bool:
        """判断系统是否负载高。"""
        # LLM 额度低
        used = state.resource_budget.get("llm_calls_used", 0)
        total = state.resource_budget.get("llm_calls_total", 1000)
        if total > 0 and used / total > self.config.llm_budget_threshold:
            return True

        # 最近连续失败
        recent_failures = sum(
            1 for e in recent if getattr(e, "result", "") in ("失败", "fail", "error") or not getattr(e, "result", True)
        )
        if recent_failures >= self.config.high_load_recent_failures:
            return True

        # 待办请求过多
        return len(state.pending_requests) > self.config.max_pending_user_requests

    def _build_confirmation_text(self, intent: Intent) -> str:
        """根据风险标记生成确认话术。"""
        if "negation_detected" in intent.risk_flags:
            return f"你刚才提到「{intent.raw_input[:40]}」，其中包含否定词。你是想让我执行，还是只是讨论？"
        if "example_context" in intent.risk_flags:
            return f"你好像在举例或讨论「{intent.raw_input[:40]}」，不是真的要执行，对吗？"
        if "ambiguous" in intent.risk_flags:
            return f"我没太理解「{intent.raw_input[:40]}」的意思，你能再明确一下吗？"
        return f"请确认：你是想让我处理「{intent.raw_input[:40]}」吗？"

    def _build_task_package(self, intent: Intent, state: SelfState) -> str:
        """给 LLM 的裁剪任务包。"""
        lines = [
            "【你的角色】SiliconBase V5 的本地执行参谋。",
            "【当前自我状态】",
            state.to_prompt_summary(),
            "",
            "【本次任务】",
            intent.raw_input,
            "",
            "请判断需要调用什么工具，或直接给出最终回答。不要展开无关内容。",
        ]
        return "\n".join(lines)
