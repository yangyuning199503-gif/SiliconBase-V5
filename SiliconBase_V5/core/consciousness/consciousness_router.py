#!/usr/bin/env python3
"""
ConsciousnessRouter - 思维线程调度 LLM 入口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

职责：
  根据用户输入 + 系统内在状态 + 当前任务状态，建议输入应该走哪条 LLM 路径。

设计约束：
  - 思维线程是调度器，LLM 仍是 CPU。router 只做路由决策，不生成语言。
  - 所有决策必须可解释（记录 reason / confidence）。
  - 失败时降级到 direct_task，不阻塞用户。
  - 不引入新第三方库。
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class RouteDecision:
    """路由决策结果"""
    mode: Literal["quick_chat", "direct_task", "interrupt_resume", "defer", "alignment"]
    reason: str = ""
    confidence: float = 0.5
    suggested_timeout: int = 30
    suggested_scene: str | None = None
    need_vision: bool = False
    context_injection: list[dict] = field(default_factory=list)
    pause_current_task: bool = False
    resume_after: int | None = None


class ConsciousnessRouter:
    """
    意识路由器。

    综合考虑：
      1. 输入分类（classify_user_input）
      2. 内在动机状态（energy / mastery / autonomy / curiosity）
      3. 是否有活跃任务
      4. 最近独白 / 紧急洞察
      5. 用户最近 60 秒打断次数
    """

    def __init__(
        self,
        user_id: str = "default",
        intrinsic_motivation=None,
        consciousness=None,
    ):
        self.user_id = user_id
        self._intrinsic_motivation = intrinsic_motivation
        self._consciousness = consciousness

        try:
            from core.config import config
            self._low_energy_threshold = config.get("consciousness.router.low_energy_threshold", 0.3)
            self._max_interruptions = config.get("consciousness.router.max_interruptions_before_pause", 2)
            self._enabled = config.get("consciousness.router.enabled", True)
        except Exception:
            self._low_energy_threshold = 0.3
            self._max_interruptions = 2
            self._enabled = True

    def suggest_route(
        self,
        user_input: str,
        classification: dict[str, Any],
        has_active_task: bool = False,
        interruption_count: int = 0,
        chat_history: list[dict] | None = None,
    ) -> RouteDecision:
        """
        给出路由建议。

        Returns:
            RouteDecision
        """
        if not self._enabled:
            return self._direct_task("router 已禁用，降级到直接任务")

        category = classification.get("category", "task")

        # 1. 简单聊天：直接走快速路径
        if category == "simple_chat":
            return RouteDecision(
                mode="quick_chat",
                reason="输入分类为简单聊天，直接快速回应",
                confidence=0.9,
                suggested_timeout=15,
                suggested_scene="chat",
            )

        # 2. 任务控制：直接操作任务
        if category == "task_control":
            control_type = classification.get("control_type", "")
            if control_type in ("resume", "retry"):
                return RouteDecision(
                    mode="interrupt_resume",
                    reason=f"任务控制指令: {control_type}",
                    confidence=0.9,
                    suggested_timeout=15,
                )
            return RouteDecision(
                mode="direct_task",
                reason=f"任务控制指令: {control_type}",
                confidence=0.9,
                suggested_timeout=15,
            )

        # 3. 状态查询：快速路径
        if category == "task_status_query":
            return RouteDecision(
                mode="quick_chat",
                reason="任务状态查询，读取快照后快速回答",
                confidence=0.9,
                suggested_timeout=15,
                suggested_scene="chat",
            )

        # 4. 有活跃任务时：判断是否插话
        if has_active_task:
            # 连续打断超过阈值 -> 暂停原任务并询问意图
            if interruption_count >= self._max_interruptions:
                return RouteDecision(
                    mode="interrupt_resume",
                    reason=f"用户连续打断 {interruption_count} 次，暂停原任务并询问意图",
                    confidence=0.8,
                    pause_current_task=True,
                    suggested_timeout=15,
                )

            # 系统能量低 -> 对齐确认
            energy = self._get_energy()
            if energy < self._low_energy_threshold:
                return RouteDecision(
                    mode="alignment",
                    reason=f"系统能量低({energy:.2f})，先确认用户意图",
                    confidence=0.7,
                    suggested_timeout=20,
                )

        # 5. 默认：直接走任务路径
        return RouteDecision(
            mode="direct_task",
            reason="未触发特殊路由规则，进入标准任务流",
            confidence=0.6,
            suggested_timeout=60,
        )

    def _direct_task(self, reason: str) -> RouteDecision:
        return RouteDecision(
            mode="direct_task",
            reason=reason,
            confidence=0.5,
            suggested_timeout=60,
        )

    def _get_energy(self) -> float:
        """获取当前能量水平，失败返回 1.0（不触发低能量规则）。"""
        if self._intrinsic_motivation is None:
            return 1.0
        try:
            return float(getattr(self._intrinsic_motivation, "energy", 1.0))
        except Exception:
            return 1.0
