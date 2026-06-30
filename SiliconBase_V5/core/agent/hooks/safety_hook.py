#!/usr/bin/env python3
"""
SafetyHook - 安全审查钩子
V5/V6 融合重构 - Phase 6

职责：统一封装幻觉检测（after_prompt）和道德检查（before_tool）。
只提供 async 接口，同步入口已在 Phase 3 废弃。

设计约束：
1. 异常时降级：记录警告并返回原始 ctx，禁止导致对话崩溃。
2. before_tool 不直接控制主循环流程；若道德检查未通过，在 ctx.extra 中
   设置 moral_blocked=True，由主循环检查后继续处理。
3.  hallucination_detector / moral_module 按需延迟导入，避免循环依赖。
"""

import time
from types import SimpleNamespace
from typing import Any

from core.logger import logger

# 【P1 改造】V2 安全架构三层拆分（Detector + Policy）
try:
    from core.safety.detector import HallucinationDetector
    from core.safety.policy import SafetyAction, SafetyPolicy
    _V2_SAFETY_AVAILABLE = True
except ImportError:
    _V2_SAFETY_AVAILABLE = False
    HallucinationDetector = None
    SafetyPolicy = None
    SafetyAction = None

try:
    from core.agent.agent_loop_hooks import HookContext, HookResult
except ImportError:
    HookContext = Any
    HookResult = Any


def _is_v2_safety_enabled() -> bool:
    """v2_safety 已强制开启（Phase 6 改造完成）。
    保留此函数仅避免破坏外部调用方，实际永远返回 True。"""
    return _V2_SAFETY_AVAILABLE


class SafetyHook:
    """安全审查 Hook（幻觉检测 + 道德检查）"""

    def __init__(self):
        self._hallucination_detector = None
        self._hallucination_stats = None
        self._moral_module = None

    async def _get_hallucination_detector(self):
        if self._hallucination_detector is None:
            try:
                from core.safety.hallucination_detector import get_hallucination_detector
                self._hallucination_detector = await get_hallucination_detector()
            except Exception as e:
                logger.debug(f"[SafetyHook] 幻觉检测器初始化失败: {e}")
        return self._hallucination_detector

    async def _get_hallucination_stats(self):
        if self._hallucination_stats is None:
            try:
                from core.safety.hallucination_stats import get_stats_manager
                self._hallucination_stats = await get_stats_manager()
            except Exception as e:
                logger.debug(f"[SafetyHook] 幻觉统计管理器初始化失败: {e}")
        return self._hallucination_stats

    async def _get_moral_module(self):
        if self._moral_module is None:
            try:
                from core.safety.moral_module import get_moral_module
                self._moral_module = await get_moral_module()
            except Exception as e:
                logger.debug(f"[SafetyHook] 道德模块初始化失败: {e}")
        return self._moral_module

    def _get_safety_guard(self):
        try:
            from core.safety.safety_guard import assess_operation_risk
            return assess_operation_risk
        except Exception as e:
            logger.debug(f"[SafetyHook] 安全守卫导入失败: {e}")
            return None

    # ═════════════════════════════════════════════════════════════════════════════
    # after_prompt：幻觉检测
    # ═════════════════════════════════════════════════════════════════════════════
    async def after_prompt(self, ctx: HookContext, response: str) -> HookResult:
        """
        检测 AI 响应中的幻觉内容（Phase 7.3 闭环）。

        返回 HookResult，支持 should_retry 信号。
        异常时降级：记录 ERROR 并返回 HookResult(ctx=ctx, should_retry=False)。
        """
        if ctx is None or not response:
            return HookResult(ctx=ctx)

        try:
            working_memory = getattr(ctx, "working_memory", None)
            session_id = getattr(ctx, "session_id", "")
            user_id = getattr(ctx, "user_id", "default")

            if HallucinationDetector is not None and SafetyPolicy is not None:
                # ═════════════════════════════════════════════════════════════════
                # V2: Detector + Policy 三层拆分（已强制开启，V1 逻辑已删除）
                # ═════════════════════════════════════════════════════════════════
                detector = HallucinationDetector()
                detection = await detector.detect(
                    ai_response=response,
                    context={"conversation_context": getattr(ctx, "extra", {}) or {}},
                    session_id=session_id,
                )

                policy = SafetyPolicy()
                decision = policy.apply(detection, response)

                # 保存统计（复用旧 stats_manager）
                try:
                    from core.safety.hallucination_stats import get_stats_manager
                    stats_manager = await get_stats_manager()
                    if stats_manager:
                        # 【修复】V2 DetectionResult → V1 HallucinationCheckResult 兼容格式
                        compatible_result = SimpleNamespace(
                            hallucination_level=SimpleNamespace(value=detection.level),
                            uncertainty_score=detection.score,
                            response_snippet="",
                            detected_claims=[],
                            uncertain_phrases=[],
                            verification_notes=detection.verification_notes,
                            knowledge_matches=[],
                            timestamp=time.time(),
                        )
                        await stats_manager.save_check_result(
                            session_id=session_id,
                            result=compatible_result,
                            query_text="",
                            user_id=user_id,
                        )
                except Exception as stats_e:
                    logger.warning(f"[SafetyHook] 幻觉统计保存失败: {stats_e}")

                # Executor 层：修改 working_memory 状态
                if working_memory:
                    level = detection.level
                    score = detection.score
                    working_memory.hallucination_flagged = level in ("high", "critical")
                    working_memory.hallucination_level = level
                    working_memory.hallucination_score = score

                    if score >= 0.7:
                        logger.error(f"[SafetyHook] 检测到高度幻觉: 分数={score:.2f}, 等级={level}, 会话={session_id[:8]}")
                    elif score >= 0.4:
                        logger.warning(f"[SafetyHook] 检测到中度不确定: 分数={score:.2f}, 会话={session_id[:8]}")
                    else:
                        logger.debug(f"[SafetyHook] 幻觉检测通过: 分数={score:.2f}")

                # Executor 层：重试决策
                retry_count = getattr(working_memory, "hallucination_retry_count", 0) if working_memory else 0
                if decision.action == SafetyAction.RETRY and retry_count < 2:
                    if working_memory:
                        working_memory.hallucination_retry_count = retry_count + 1
                    logger.info(f"[SafetyHook] 幻觉检测触发重试 (第 {retry_count + 1} 次)")
                    return HookResult(
                        ctx=ctx,
                        should_retry=True,
                        retry_reason=decision.reason,
                    )
                elif retry_count >= 2:
                    logger.warning(f"[SafetyHook] 幻觉重试次数已达上限 ({retry_count})，继续向用户返回结果")
            else:
                logger.error("[SafetyHook] V2 安全模块不可用（Detector/Policy 导入失败），跳过幻觉检测")

        except Exception as e:
            logger.error(f"[SafetyHook] 幻觉检测异常，已降级通过: {e}", exc_info=True)

        return HookResult(ctx=ctx)

    async def before_tool(self, ctx: HookContext, parsed=None) -> HookContext:
        """
        对即将执行的工具调用进行双重安全审查：
        1. safety_guard 动态风险评估（用户画像 + 工具历史）
        2. moral_module 静态道德检查（140+ 条规则）

        若未通过，在 ctx.extra 中设置 blocked 标记，由主循环统一处理。
        异常时降级：记录 ERROR 并放行，绝不阻断正常对话。
        """
        if ctx is None:
            return ctx

        try:
            tool_id = getattr(parsed, "target_tool", "") if parsed else ""
            tool_params = getattr(parsed, "params", {}) if parsed else {}
            if not tool_id:
                return ctx

            user_id = getattr(ctx, "user_id", "default")
            session_id = getattr(ctx, "session_id", "")
            extra = getattr(ctx, "extra", {}) or {}
            round_count = extra.get("round", 0)
            voice_instance = getattr(ctx, "voice_instance", None)

            # -----------------------------------------------------------------
            # 第1层：safety_guard 动态风险评估
            # -----------------------------------------------------------------
            assess_risk = self._get_safety_guard()
            if assess_risk:
                try:
                    from core.safety.risk_level import RiskLevel
                    risk_result = await assess_risk(
                        user_id=user_id,
                        tool_name=tool_id,
                        params=tool_params,
                        context={"session_id": session_id, "round": round_count}
                    )
                    if risk_result.level == RiskLevel.BLOCK:
                        logger.warning(
                            f"[SafetyHook] 工具'{tool_id}'被 safety_guard 阻止: {risk_result.reason}"
                        )
                        blocked_result = {
                            "success": False,
                            "error": f"安全守卫阻止: {risk_result.reason}",
                            "user_message": f"我无法执行此操作，因为存在安全风险: {risk_result.reason}",
                            "blocked_by_safety": True,
                            "safety_reason": risk_result.reason,
                        }
                        self._emit_blocked_event(
                            session_id, round_count, tool_id, tool_params, risk_result.reason, "safety_guard_blocked"
                        )
                        self._speak_moral_block(voice_instance)
                        ctx.extra["safety_blocked"] = True
                        ctx.extra["safety_reason"] = risk_result.reason
                        ctx.extra["safety_blocked_result"] = blocked_result
                        ctx.extra["safety_tool_id"] = tool_id
                        ctx.extra["safety_tool_params"] = tool_params
                        return ctx

                    elif risk_result.level == RiskLevel.CONFIRM:
                        logger.info(
                            f"[SafetyHook] 工具'{tool_id}'需要确认: {risk_result.reason}"
                        )
                        ctx.extra["safety_requires_confirmation"] = True
                        ctx.extra["safety_confirm_reason"] = risk_result.reason
                        ctx.extra["safety_wait_seconds"] = risk_result.wait_seconds
                        ctx.extra["safety_require_double_confirm"] = risk_result.require_double_confirm

                    elif risk_result.level == RiskLevel.NOTICE:
                        logger.info(
                            f"[SafetyHook] 工具'{tool_id}'风险提醒: {risk_result.reason}"
                        )
                        # NOTICE 仅记录，不阻断
                except Exception as risk_e:
                    logger.error(f"[SafetyHook] safety_guard 评估异常（已降级）: {risk_e}", exc_info=True)

            # -----------------------------------------------------------------
            # 第2层：moral_module 静态道德检查
            # -----------------------------------------------------------------
            moral_module = await self._get_moral_module()
            if moral_module:
                try:
                    moral_passed, moral_reason = await moral_module.check_action(tool_id, tool_params)
                    if moral_passed:
                        logger.info(f"[SafetyHook] 工具'{tool_id}'通过道德检查")
                        return ctx

                    logger.warning(f"[SafetyHook] 工具'{tool_id}'未通过道德检查: {moral_reason}")
                    blocked_result = {
                        "success": False,
                        "error": f"道德检查阻止: {moral_reason}",
                        "user_message": f"我无法执行此操作，因为该操作违反了安全准则: {moral_reason}",
                        "blocked_by_moral": True,
                        "moral_reason": moral_reason,
                    }
                    self._emit_blocked_event(
                        session_id, round_count, tool_id, tool_params, moral_reason, "moral_check_blocked"
                    )
                    self._speak_moral_block(voice_instance)

                    ctx.extra["moral_blocked"] = True
                    ctx.extra["moral_reason"] = moral_reason
                    ctx.extra["moral_blocked_result"] = blocked_result
                    ctx.extra["moral_tool_id"] = tool_id
                    ctx.extra["moral_tool_params"] = tool_params

                except Exception as moral_e:
                    logger.error(f"[SafetyHook] 道德检查异常（已降级放行）: {moral_e}", exc_info=True)

        except Exception as e:
            logger.error(f"[SafetyHook] before_tool 整体异常（已降级放行）: {e}", exc_info=True)

        return ctx

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部辅助方法
    # ═════════════════════════════════════════════════════════════════════════════
    def _emit_blocked_event(self, session_id: str, round_count: int, tool_id: str, tool_params: dict, reason: str, event_type: str):
        """发送安全阻止事件到前端。"""
        try:
            from core.sync.sync import emit_event
            emit_event(event_type, session_id, {
                "round": round_count,
                "tool": tool_id,
                "params": tool_params,
                "reason": reason,
            })
        except Exception as evt_e:
            logger.warning(f"[SafetyHook] 发送阻止事件失败: {evt_e}")

    def _speak_moral_block(self, voice_instance):
        """播报安全阻止信息。"""
        if voice_instance:
            try:
                voice_instance.speak(
                    "抱歉，我无法执行此操作，因为它违反了安全准则。",
                    is_system=True,
                    wait=False,
                )
            except Exception as voice_e:
                logger.debug(f"[SafetyHook] 道德阻止语音播报失败: {voice_e}")


# 全局实例
safety_hook = SafetyHook()
