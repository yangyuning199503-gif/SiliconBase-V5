"""
自我决策引擎 - 思维线程的本地大脑

每轮循环：
1. 用 21 个板块的聚合摘要更新自我状态。
2. 基于自我状态和最近自我叙事做三选一决策。
3. 构建给 LLM 的裁剪任务包。

原则：
- 不调用 LLM。
- 不读原始日志。
- 决策规则硬编码、可解释。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.consciousness.self_narrative import SelfNarrativeLog
from core.consciousness.self_state import SelfState
from core.memory import module_state_manager

try:
    from core.consciousness.self_awareness import SelfAwareness
except Exception:
    SelfAwareness = None

logger = logging.getLogger(__name__)


@dataclass
class OutputIntent:
    """思维线程输出意图。"""
    kind: str  # "llm_package" | "plate_command" | "user_expression"
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class SelfEngine:
    """
    本地自我决策引擎。

    不依赖 LLM，只做结构化状态更新和硬编码规则决策。
    """

    def __init__(self, user_id: str):
        self.user_id = user_id

    # ═══════════════════════════════════════════════════════════════════════
    # 1. 更新自我状态
    # ═══════════════════════════════════════════════════════════════════════

    def update_from_plates(self, state: SelfState,
                           perception_buffer: list[dict] | None = None,
                           recent_events: list[dict] | None = None) -> None:
        """
        从板块聚合状态（module_state_manager）和感知缓冲区更新 plate_status。
        不读原始日志，只提取关键信息。
        """
        # 1.1 读取 module_state_manager 已聚合的模块摘要
        try:
            module_states = module_state_manager.get_recent_module_states(limit=50)
            state.update_from_module_states(module_states)
        except Exception as e:
            logger.debug(f"[SelfEngine] 读取模块状态失败: {e}")

        # 1.2 从感知缓冲区提取高优先级条目（如告警）
        if perception_buffer:
            for entry in perception_buffer[-10:]:
                if not isinstance(entry, dict):
                    continue
                level = entry.get("level", "info")
                source = entry.get("source", "perception")
                summary = entry.get("summary", "") or str(entry.get("data", ""))[:60]
                if level in ("alert", "warning") and summary:
                    state.push_pending_request(source, summary, priority=8)
                elif level == "error":
                    state.push_pending_request(source, summary, priority=9)

        # 1.3 从最近事件提取板块状态变化
        if recent_events:
            for ev in recent_events[-20:]:
                if not isinstance(ev, dict):
                    continue
                name = ev.get("name", "")
                data = ev.get("data", {})
                if name in ("task.completed", "task.failed"):
                    result = "成功" if name == "task.completed" else "失败"
                    summary = data.get("task_id", "") if isinstance(data, dict) else ""
                    if summary:
                        state.record_last_action(f"任务结束:{summary}", result)

        # 1.4 同步 SelfAwareness 的生命体征/情绪
        if SelfAwareness is not None:
            try:
                awareness = SelfAwareness()
                state.update_from_self_awareness(awareness.get_life_state())
            except Exception as e:
                logger.debug(f"[SelfEngine] 读取 SelfAwareness 失败: {e}")

    def update_from_user_input(self, state: SelfState, text: str,
                               classification: dict[str, Any] | None = None) -> None:
        """
        用户输入不直接转给 LLM，先更新自我状态里的待办项。
        """
        category = (classification or {}).get("category", "task")
        confidence = (classification or {}).get("confidence", 5)
        force_vision = (classification or {}).get("force_vision", False)

        # 更新当前主任务候选
        if category == "simple_chat":
            state.set_mode("working")
        elif category in ("task", "direct_task") or force_vision:
            state.update_task(f"处理用户请求: {text[:40]}")
            state.set_mode("working")
        elif category == "task_control":
            state.set_mode("working")

        # 压入待办
        state.push_pending_request(
            source="user",
            summary=text[:120],
            priority=7 if category != "simple_chat" else 4,
            meta={"category": category, "confidence": confidence, "force_vision": force_vision},
        )

    def update_from_action_result(self, state: SelfState, action: str, result: str,
                                  details: dict[str, Any] | None = None) -> None:
        """执行后更新 last_action。"""
        state.record_last_action(action, result, details)

    # ═══════════════════════════════════════════════════════════════════════
    # 2. 三选一决策
    # ═══════════════════════════════════════════════════════════════════════

    def decide(self, state: SelfState, narrative: SelfNarrativeLog) -> list[OutputIntent]:
        """
        基于自我状态做简单决策，返回一个或多个输出意图。
        规则硬编码，确保可解释。
        """
        intents: list[OutputIntent] = []

        # 规则 1：高优先级板块告警 -> 发出板块命令 + 用户表达
        alerts = [r for r in state.pending_requests if r.get("priority", 5) >= 8 and r.get("source") != "user"]
        if alerts:
            alert = alerts[0]
            plate_id = self._infer_plate_from_source(alert.get("source", ""))
            if plate_id:
                intents.append(OutputIntent(
                    kind="plate_command",
                    payload={
                        "plate_id": plate_id,
                        "action": "handle_alert",
                        "params": {"summary": alert.get("summary", ""), "priority": alert.get("priority", 5)},
                    },
                    reason="高优先级板块告警，优先调度",
                ))
            intents.append(OutputIntent(
                kind="user_expression",
                payload={"text": f"检测到 {plate_id or '系统'} 异常，正在处理。"},
                reason="向用户同步告警",
            ))
            state.set_mode("alerting")
            return intents

        # 规则 2：用户闲聊 -> 直接表达，不进 LLM
        simple_chat_reqs = [r for r in state.pending_requests
                            if r.get("source") == "user" and
                            r.get("meta", {}).get("category") == "simple_chat"]
        if simple_chat_reqs:
            req = simple_chat_reqs[0]
            intents.append(OutputIntent(
                kind="user_expression",
                payload={"text": "", "reply_to_user": True, "raw_input": req.get("summary", "")},
                reason="用户闲聊，直接表达",
            ))
            state.set_mode("working")
            return intents

        # 规则 3：用户任务请求 -> 给 LLM 的任务包
        user_tasks = [r for r in state.pending_requests
                      if r.get("source") == "user" and r.get("priority", 5) >= 5]
        if user_tasks:
            req = user_tasks[0]
            package = self._build_llm_package(state, req)
            intents.append(OutputIntent(
                kind="llm_package",
                payload={"package": package, "raw_input": req.get("summary", "")},
                reason="有待处理用户任务，需要 LLM 填空",
            ))
            state.set_mode("working")
            return intents

        # 规则 3：资源预算低 -> 用户表达 + 进入节能
        used = state.resource_budget.get("llm_calls_used", 0)
        total = state.resource_budget.get("llm_calls_total", 1000)
        if total > 0 and used / total > 0.95:
            intents.append(OutputIntent(
                kind="user_expression",
                payload={"text": "今日 LLM 调用额度快用完了，我将进入节能模式。"},
                reason="资源预算接近耗尽",
            ))
            state.set_mode("hibernating")
            return intents

        # 规则 4：空闲且资源足够 -> 内部反思任务包（可选）
        if state.mode == "idle" and (total == 0 or used / total < 0.5):
            recent = narrative.recent_text(3)
            package = (
                "当前没有紧急任务。请基于以下最近自我叙事，给出下一步该关注什么的简短判断：\n"
                f"{recent}"
            )
            intents.append(OutputIntent(
                kind="llm_package",
                payload={"package": package, "internal": True},
                reason="空闲时主动反思",
            ))
            state.set_mode("reflecting")
            return intents

        # 默认：保持 idle
        state.set_mode("idle")
        return intents

    # ═══════════════════════════════════════════════════════════════════════
    # 3. 构建 LLM 任务包
    # ═══════════════════════════════════════════════════════════════════════

    def _build_llm_package(self, state: SelfState, request: dict[str, Any]) -> str:
        """
        把用户问题/板块摘要打包成填空题。
        LLM 看不到 21 个板块全貌，也看不到"我是谁"，只收到：
        - 当前任务与进度
        - 上次动作结果
        - 本次具体问题
        - 最近几条自我叙事
        """
        lines = [
            "【你的角色】SiliconBase V5 的本地思维助手。",
            "【当前自我状态】",
            state.to_prompt_summary(),
            "",
            "【本次问题】",
            request.get("summary", ""),
            "",
            "请只回答这个具体问题，不要展开无关内容。",
        ]
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # 4. 辅助
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _infer_plate_from_source(source: str) -> str:
        """从来源字符串推断板块 ID。"""
        source_lower = source.lower()
        mapping = {
            "vision": "vision",
            "trading": "trading",
            "memory": "memory",
            "voice": "voice",
            "task": "task_scheduler",
            "session": "dialogue",
            "weak": "weak_connection",
            "safety": "safety",
            "intervention": "intervention",
        }
        for k, v in mapping.items():
            if k in source_lower:
                return v
        return "consciousness_self"
