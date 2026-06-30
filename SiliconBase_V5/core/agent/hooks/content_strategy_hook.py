#!/usr/bin/env python3
"""
ContentStrategyHook — 内容策略钩子
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：注册到 after_prompt Hook，在 AI 生成回复后、分发前，
      调用 ContentStrategyEngine 进行质量门禁和平台适配。

设计约束：
  - 全 async
  - 异常不阻塞主循环（logger.exception）
  - 结果写入 ctx.extra，供 DistributionController 消费
"""

from typing import Any

from core.logger import logger

try:
    from core.agent.agent_loop_hooks import HookContext, HookResult
except ImportError:
    HookContext = Any
    HookResult = Any

try:
    from core.strategy.content_strategy_engine import ContentStrategyEngine
    _CSE_AVAILABLE = True
except ImportError:
    _CSE_AVAILABLE = False
    ContentStrategyEngine = None


class ContentStrategyHook:
    """内容策略审查 Hook（质量门禁 + 平台适配）"""

    def __init__(self) -> None:
        self._engine: ContentStrategyEngine | None = None

    async def _get_engine(self) -> ContentStrategyEngine | None:
        if self._engine is None and _CSE_AVAILABLE:
            self._engine = ContentStrategyEngine()
        return self._engine

    async def after_prompt(self, ctx: HookContext, response: str = "") -> HookResult:
        """
        after_prompt 钩子：对 AI 响应进行策略性处理。

        流程：
          1. 读取目标平台列表（从 ctx.extra 或配置）
          2. 质量门禁：逐平台判断内容是否可分发
          3. 平台适配：对通过门禁的内容按平台调整格式
          4. 将结果写入 ctx.extra，供下游 DistributionController 读取

        异常时降级：记录异常并返回原始 HookResult，不阻断主循环。
        """
        if ctx is None or not response:
            return HookResult(ctx=ctx)

        engine = await self._get_engine()
        if engine is None:
            logger.debug("[ContentStrategyHook] ContentStrategyEngine 不可用，跳过")
            return HookResult(ctx=ctx)

        try:
            # 从配置或 ctx.extra 读取目标平台
            from core.config import config
            enabled_platforms = (
                ctx.extra.get("enabled_platforms")
                or config.get("platform_dispatcher.enabled_platforms", [])
            )

            if not enabled_platforms:
                logger.debug("[ContentStrategyHook] 无启用平台，跳过策略处理")
                return HookResult(ctx=ctx)

            # 质量门禁 + 平台适配（按平台分别处理）
            adapted_contents: dict[str, str] = {}
            for platform in enabled_platforms:
                should_send = await engine.should_distribute(response, platform)
                if not should_send:
                    logger.info(
                        f"[ContentStrategyHook] 内容未通过 {platform} 质量门禁，跳过"
                    )
                    continue

                adapted = await engine.adapt_message(response, platform)
                adapted_contents[platform] = adapted
                logger.debug(
                    f"[ContentStrategyHook] {platform} 适配完成，长度 {len(adapted)}"
                )

            # 将结果写入 ctx.extra，供 DistributionController 消费
            ctx.extra["strategy_adapted_contents"] = adapted_contents
            ctx.extra["strategy_original_response"] = response

            # 可选：记录话术风格决策（供分析用）
            topic = ctx.extra.get("current_topic", "")
            audience = ctx.extra.get("target_audience", "")
            if topic:
                tone = await engine.select_tone(topic, audience)
                ctx.extra["strategy_selected_tone"] = tone

            logger.info(
                f"[ContentStrategyHook] 策略处理完成，目标平台: {list(adapted_contents.keys())}"
            )

        except Exception as e:
            logger.exception(
                f"[ContentStrategyHook] 策略处理异常（已降级）: {e}"
            )
            # 异常时不阻断主循环，清空策略结果让下游回退到原始内容
            ctx.extra["strategy_adapted_contents"] = {}
            ctx.extra["strategy_original_response"] = response

        return HookResult(ctx=ctx)


# 全局实例
content_strategy_hook = ContentStrategyHook()
