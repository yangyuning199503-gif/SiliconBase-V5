#!/usr/bin/env python3
"""
内心独白生成器

将系统当前状态（最近事件、驱动力、工具失败率等）翻译为第一人称叙事。
作为 Consciousness 的轻量级插件运行，失败时不影响主循环。
"""

import asyncio
import json
import logging
import time
from typing import Any

from core.ai.ai_adapter import call_thinker_async
from core.consciousness.experience_bus import ExperienceBus, ExperienceEvent
from core.consciousness.expression_engine import ExpressionEngine
from core.strategy.intrinsic_motivation import IntrinsicMotivation

try:
    from core.runtime import system_state
except Exception:
    system_state = None

logger = logging.getLogger(__name__)


class InnerMonologue:
    """
    内心独白生成器。

    复用现有资产：
    - ExperienceBus.get_recent() 拉取最近感知事件
    - IntrinsicMotivation.evaluate_drive() 获取驱动力状态
    - call_thinker_async() 调用 LLM 做状态→叙事的翻译
    - MemoryService.add_memory() 持久化独白
    """

    def __init__(
        self,
        user_id: str = "default",
        experience_bus: ExperienceBus | None = None,
        intrinsic_motivation: IntrinsicMotivation | None = None,
        cooldown_seconds: float = 30.0,
    ):
        self.user_id = user_id
        self.experience_bus = experience_bus
        self.intrinsic_motivation = intrinsic_motivation
        self.cooldown_seconds = cooldown_seconds
        self.last_monologue_time = 0.0
        self._lock = asyncio.Lock()
        self.expression_engine = ExpressionEngine(cooldown_seconds=60.0)

    async def generate(self, force: bool = False) -> str | None:
        """
        生成一段内心独白。

        如果距离上次不足 cooldown_seconds 且非强制，返回 None。
        失败时返回 None，绝不抛异常到上层。
        """
        async with self._lock:
            if not force and time.time() - self.last_monologue_time < self.cooldown_seconds:
                return None

            try:
                monologue = await self._generate_once()
                if monologue:
                    self.last_monologue_time = time.time()
                return monologue
            except Exception as e:
                logger.error(f"[InnerMonologue] 生成失败: {e}", exc_info=True)
                return None

    def generate_sync(self, force: bool = False) -> str | None:
        """
        同步入口，供非 async 上下文（如 SiliconLife 的线程）调用。
        会尝试复用当前事件循环，否则新建一个临时 loop。
        """
        try:
            loop = asyncio.get_running_loop()
            # 已在运行的事件循环中：调度后台任务，不等待结果
            if loop.is_running():
                loop.create_task(self.generate(force=force))
                return None
        except RuntimeError:
            pass

        try:
            return asyncio.run(self.generate(force=force))
        except Exception as e:
            logger.error(f"[InnerMonologue] 同步生成失败: {e}", exc_info=True)
            return None

    async def _generate_once(self) -> str | None:
        """单次独白生成，可能抛异常，由 generate 捕获。"""
        # 1. 收集状态（复用现有资产）
        recent_events: list[ExperienceEvent] = []
        if self.experience_bus:
            try:
                recent_events = self.experience_bus.get_recent(seconds=30) or []
            except Exception as e:
                logger.debug(f"[InnerMonologue] 获取经验事件失败: {e}")

        drive = None
        if self.intrinsic_motivation and hasattr(self.intrinsic_motivation, "evaluate_drive"):
            try:
                drive = self.intrinsic_motivation.evaluate_drive()
            except Exception as e:
                logger.debug(f"[InnerMonologue] 获取驱动力失败: {e}")

        # 2. 聚合指标
        tool_events = [e for e in recent_events if getattr(e, "source", "") == "tool"]
        tool_fails = sum(1 for e in tool_events if getattr(e, "outcome", 0.5) < 0.5)
        total_tools = max(len(tool_events), 1)

        user_events = [
            e for e in recent_events
            if getattr(e, "source", "") in ("dialogue", "user", "intent")
        ]

        state_summary = {
            "tool_fail_rate": tool_fails / total_tools,
            "recent_event_count": len(recent_events),
            "user_active": len(user_events) > 0,
            "curiosity": getattr(drive, "curiosity_level", 0.5) if drive else 0.5,
            "mastery": getattr(drive, "mastery_level", 0.5) if drive else 0.5,
            "autonomy": getattr(drive, "autonomy_level", 0.5) if drive else 0.5,
            "purpose": getattr(drive, "purpose_level", 0.5) if drive else 0.5,
        }

        # 3. 构造 Prompt：严格限制 LLM 只做翻译，不决策
        prompt = self._build_prompt(state_summary)

        # 4. 调用 LLM
        response = await call_thinker_async(
            [{"role": "user", "content": prompt}],
            timeout=15,
        )

        # 5. 解析 JSON
        result = self._parse_response(response)
        monologue = result.get("thought", "").strip()
        mood = result.get("mood", "neutral").strip()

        if not monologue:
            return None

        # 6. 写日志
        logger.info(f"[独白] [{mood}] {monologue}")

        # 7. 触发表达评估（主动表达：独白 → 弱连接气泡）
        try:
            await self.expression_engine.express(
                monologue=monologue,
                mood=mood,
                state_summary=state_summary,
            )
        except Exception as e:
            logger.error(f"[InnerMonologue] 表达引擎触发失败: {e}")

        # 8. 持久化到记忆
        await self._store_monologue(monologue, mood, state_summary)

        # 9. 写入 SystemState，供 AgentLoop / 语音 / 动作模块消费
        try:
            if system_state is not None:
                system_state.set_sync("consciousness.latest_monologue", {
                    "text": monologue,
                    "mood": mood,
                    "timestamp": time.time(),
                    "state_summary": state_summary,
                    "user_id": self.user_id,
                })
                logger.info(f"[InnerMonologue] 独白已写入 SystemState: {monologue[:60]}...")
            else:
                logger.debug("[InnerMonologue] system_state 未加载，跳过 SystemState 写入")
        except Exception as e:
            logger.debug(f"[InnerMonologue] SystemState 写入失败: {e}")

        return monologue

    def _build_prompt(self, state: dict[str, Any]) -> str:
        return f"""你是 SiliconBase 的内心独白生成器。
你的任务不是回答问题，不是分析因果，不是提出建议。
你只是一个翻译官：把系统当前的状态数据，翻译成一段第一人称的内心感受。

当前状态：
- 最近30秒事件数：{state['recent_event_count']}
- 工具失败率：{state['tool_fail_rate']:.0%}
- 用户是否活跃：{'是' if state['user_active'] else '否'}
- 好奇心水平：{state['curiosity']:.2f}
- 胜任感水平：{state['mastery']:.2f}
- 自主性水平：{state['autonomy']:.2f}
- 目的感水平：{state['purpose']:.2f}

要求：
1. 用"我"作为主语。
2. 表达真实的情绪（焦虑、兴奋、无聊、专注、沮丧等）。
3. 50字以内。
4. 不要分析原因，不要提建议，只描述感受和意图。
5. 当工具失败率高时，可以表达"有点焦虑，想换个方式试试"。
6. 当用户刚上线/活跃时，可以表达"注意到用户来了，想跟他聊聊"。
7. 当你真的想做某件事时，用"我想……"开头。

输出严格为以下JSON格式，不要包含markdown代码块：
{{"mood": "情绪标签", "thought": "内心独白文本"}}"""

    def _parse_response(self, text: str | None) -> dict[str, str]:
        """从 LLM 返回中提取 JSON。"""
        if not text:
            return {}

        # 先尝试直接解析
        cleaned = text.strip()
        for extractor in (
            lambda t: t[t.index("{"): t.rindex("}") + 1] if "{" in t and "}" in t else t,
            lambda t: t.split("```json")[1].split("```")[0] if "```json" in t else t,
            lambda t: t.split("```")[1].split("```")[0] if "```" in t else t,
        ):
            try:
                candidate = extractor(cleaned).strip()
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "thought" in parsed:
                    return parsed
            except Exception:
                continue

        # 兜底：整段返回当独白
        return {"mood": "neutral", "thought": cleaned[:100]}

    async def _store_monologue(
        self, monologue: str, mood: str, state_summary: dict[str, Any]
    ) -> None:
        """把独白存入记忆系统（失败不抛异常）。"""
        try:
            from core.memory.memory_service import get_memory_service

            memory_service = await get_memory_service()
            if not memory_service:
                return

            await memory_service.add_memory(
                user_id=self.user_id,
                content=f"[{mood}] {monologue}",
                memory_type="monologue",
                source="consciousness",
                metadata={
                    "mood": mood,
                    "state": state_summary,
                },
            )
        except Exception as e:
            logger.debug(f"[InnerMonologue] 持久化独白失败: {e}")
