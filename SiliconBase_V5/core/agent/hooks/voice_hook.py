#!/usr/bin/env python3
"""
VoiceHook - 语音播报钩子
V5/V6 融合重构 - Phase 6

职责：把散落在 agent_loop.py 各处的语音播报逻辑集中到本模块。
只提供 async 接口，由 agent_loop_hooks 注册表统一驱动。

设计约束：
1. 不接管控制流，只负责"何时说什么"的封装。
2. 异常时静默降级，绝不因语音播报失败导致对话崩溃。
3. 对于 agent_loop.py 中已有的辅助函数（如 speak_ai_reply），优先复用而非重写。
"""

from typing import Any

from core.logger import logger

try:
    from core.agent.agent_loop_hooks import HookContext
except ImportError:
    HookContext = Any


class VoiceHook:
    """语音播报 Hook"""

    # ═════════════════════════════════════════════════════════════════════════════
    # 标准生命周期 Hook
    # ═════════════════════════════════════════════════════════════════════════════
    async def before_prompt(self, ctx: HookContext, messages=None) -> HookContext:
        """AI 思考前的过程播报（如'正在思考'提示）。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        working_memory = getattr(ctx, "working_memory", None)
        if not voice_instance or not working_memory:
            return ctx

        try:
            if getattr(working_memory, '_thinking_announced', False):
                return ctx

            from core.agent.voice_strategy import VoiceAnnounceStrategy
            if not VoiceAnnounceStrategy.is_process_announce_enabled("thinking"):
                return ctx

            if not VoiceAnnounceStrategy.should_announce_by_type(VoiceAnnounceStrategy.THINKING):
                return ctx

            thinking_msg = VoiceAnnounceStrategy.get_thinking_announcement()
            voice_instance.speak(thinking_msg, is_system=True, wait=False, protected=False)
            working_memory._thinking_announced = True
        except Exception as e:
            logger.debug(f"[VoiceHook] before_prompt 播报失败: {e}")
        return ctx

    async def after_prompt(self, ctx: HookContext, response=None) -> HookContext:
        """Prompt 返回后的语音处理。处理空响应等异常情况。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not response and voice_instance:
            try:
                from voice.voice_prompts import SystemAnnouncements
                voice_instance.speak(SystemAnnouncements.SYSTEM_ERROR)
            except Exception as e:
                logger.debug(f"[VoiceHook] after_prompt 空响应播报失败: {e}")
        return ctx

    async def after_tool(self, ctx: HookContext, tool_result=None) -> HookContext:
        """工具执行后的语音播报。当前工具结果播报已被删除，此处预留扩展。"""
        return ctx

    async def after_loop(self, ctx: HookContext) -> HookContext:
        """主循环结束后的语音播报（如轮次上限提示）。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        extra = getattr(ctx, "extra", {}) or {}
        if not voice_instance or not extra.get("max_rounds_reached"):
            return ctx

        try:
            voice_instance.speak(
                "任务执行轮次已达上限，请重新下达指令继续",
                is_system=True,
                wait=False,
                priority=3,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] after_loop 播报失败: {e}")
        return ctx

    # ═════════════════════════════════════════════════════════════════════════════
    # Phase 6 新增意图/状态特定 Hook
    # ═════════════════════════════════════════════════════════════════════════════
    async def on_complete(self, ctx: HookContext, answer: str | None = None) -> HookContext:
        """FINAL_ANSWER 时的完成播报。复用 speak_ai_reply 的去重/截断逻辑。"""
        if not answer:
            return ctx
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx

        try:
            # 延迟导入避免循环依赖
            from core.agent.agent_loop import speak_ai_reply
            speak_ai_reply(answer, voice_instance=voice_instance)
        except Exception as e:
            logger.debug(f"[VoiceHook] on_complete 播报失败: {e}")
        return ctx

    async def on_plan(self, ctx: HookContext, reply: str | None = None) -> HookContext:
        """PLAN 意图时的播报。"""
        if not reply:
            return ctx
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx

        try:
            voice_instance.speak(reply)
        except Exception as e:
            logger.debug(f"[VoiceHook] on_plan 播报失败: {e}")
        return ctx

    async def on_layer_switch(self, ctx: HookContext, **kwargs) -> HookContext:
        """层级切换时的策略播报。复用 announce_with_strategy。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        working_memory = getattr(ctx, "working_memory", None)
        if not voice_instance or not working_memory:
            return ctx

        try:
            from core.agent.voice_strategy import announce_with_strategy
            announce_with_strategy(voice_instance, working_memory, **kwargs)
        except Exception as e:
            logger.debug(f"[VoiceHook] on_layer_switch 播报失败: {e}")
        return ctx

    async def on_pause(self, ctx: HookContext) -> HookContext:
        """任务暂停播报。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "任务已暂停，请告诉我您的需求",
                is_system=True,
                wait=False,
                priority=2,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_pause 播报失败: {e}")
        return ctx

    async def on_resume(self, ctx: HookContext) -> HookContext:
        """任务恢复播报。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "任务已恢复，继续执行",
                is_system=True,
                wait=False,
                priority=2,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_resume 播报失败: {e}")
        return ctx

    async def on_terminate(self, ctx: HookContext) -> HookContext:
        """任务终止播报。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "当前任务已终止，正在处理新请求",
                is_system=True,
                wait=False,
                priority=2,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_terminate 播报失败: {e}")
        return ctx

    async def on_user_assist(self, ctx: HookContext, reason: str | None = None) -> HookContext:
        """CALL_USER / 需要用户协助时的播报。"""
        if not reason:
            return ctx
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                f"需要您协助: {reason}",
                is_system=True,
                priority=3,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_user_assist 播报失败: {e}")
        return ctx

    async def on_world_model(self, ctx: HookContext) -> HookContext:
        """世界模型激活播报。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "世界模型已激活，开始预测行动后果",
                is_system=True,
                wait=False,
                priority=3,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_world_model 播报失败: {e}")
        return ctx

    async def on_understanding_confirmed(self, ctx: HookContext) -> HookContext:
        """用户理解确认后的播报。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "理解已确认，准备恢复任务",
                is_system=True,
                wait=False,
                priority=2,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_understanding_confirmed 播报失败: {e}")
        return ctx

    async def on_moral_blocked(self, ctx: HookContext) -> HookContext:
        """道德检查被阻止时的语音播报（由 SafetyHook 触发前或主循环调用）。"""
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            voice_instance.speak(
                "抱歉，我无法执行此操作，因为它违反了安全准则。",
                is_system=True,
                wait=False,
            )
        except Exception as e:
            logger.debug(f"[VoiceHook] on_moral_blocked 播报失败: {e}")
        return ctx

    async def on_error(self, ctx: HookContext, error_msg: str | None = None) -> HookContext:
        """通用错误/提示播报。复用 speak_ai_reply 的去重与截断逻辑。"""
        if not error_msg:
            return ctx
        voice_instance = getattr(ctx, "voice_instance", None)
        if not voice_instance:
            return ctx
        try:
            from core.agent.agent_loop import speak_ai_reply
            speak_ai_reply(error_msg, voice_instance=voice_instance)
        except Exception as e:
            logger.debug(f"[VoiceHook] on_error 播报失败: {e}")
        return ctx


# 全局实例
voice_hook = VoiceHook()
