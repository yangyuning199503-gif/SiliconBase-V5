#!/usr/bin/env python3
"""
ConsciousnessBridge - 意识系统驱动决策桥接
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的意识系统集成逻辑。

职责：
- 获取结构化决策分析 (analyze_current_state)
- 获取紧急洞察并注入提示词
- 获取最近思考并注入提示词
- 根据生命体征（能量/心情）调整 AI 回复风格

设计约束：
1. Consciousness 当前只有同步接口，async 版使用 run_in_executor 桥接。
   TODO(Phase X): Consciousness 真异步化后替换为原生 await。
2. 失败降级，不抛异常到主循环。
"""

import asyncio
import time
from typing import Any

from core.logger import logger

# 跟踪每个用户已注入 AgentLoop 的最新独白，避免重复注入
# key: user_id, value: 最新注入的独白数据
_injected_monologues: dict[str, dict[str, Any]] = {}
_injected_monologues_lock = asyncio.Lock()


async def apply_consciousness_analysis(
    working_memory: Any,
    execution_history: list[dict[str, Any]],
    loop_state: Any,
) -> None:
    """纯异步版：获取意识系统分析并注入工作记忆。"""

    current_state = None
    urgent_insights = None
    recent_thoughts = None
    life_state = None

    try:
        from core.consciousness.Consciousness import get_consciousness
        consciousness = get_consciousness()

        # 0. 获取结构化决策分析
        try:
            current_state = await consciousness.analyze_current_state_async(
                execution_history=execution_history[-10:] if execution_history else [],
                current_round=getattr(loop_state, 'round_count', 0) if loop_state else 0,
            )

            if current_state and isinstance(current_state, dict):
                required_fields = ["situation", "confidence", "recommended_action"]
                missing_fields = [f for f in required_fields if f not in current_state]
                if missing_fields:
                    logger.error(f"[ConsciousnessBridge] 意识系统返回缺少字段: {missing_fields}")
                    raise ValueError(f"状态分析结果结构不完整: {missing_fields}")

                confidence = current_state.get('confidence', 0)
                if confidence > 0.7:
                    state_section = f"""
💡 **系统状态分析** (置信度: {confidence:.0%})
当前情况: {current_state.get('situation', '任务进行中')}
建议行动: {current_state.get('recommended_action', '继续执行')}
{f"推荐工具: {current_state['suggested_tool']}" if current_state.get('suggested_tool') else ''}
{f"⚠️ {current_state.get('reason', '')}" if current_state.get('should_stop') else ''}
"""
                    working_memory.insert_system_message(
                        state_section, priority="high",
                        category="consciousness_state", overwrite=True,
                        source="consciousness_bridge"
                    )
                    logger.info(f"[ConsciousnessBridge] 已注入状态分析，置信度: {confidence:.0%}")

                    if current_state.get('should_stop') and confidence > 0.95:
                        logger.warning(f"[ConsciousnessBridge] 高置信度建议停止: {current_state.get('reason')}")
                        working_memory.append({
                            "role": "system",
                            "content": f"[系统提示] 意识系统检测到: {current_state.get('reason')}。如果任务已完成，请总结并结束。",
                            "_category": "consciousness_alert",
                            "_overwrite": True,
                            "source": "consciousness_bridge"
                        })
            else:
                logger.debug("[ConsciousnessBridge] 意识系统未返回有效状态分析")

        except AttributeError as e:
            logger.debug(f"[ConsciousnessBridge] 意识系统不支持 analyze_current_state: {e}")
        except ValueError as e:
            logger.error(f"[ConsciousnessBridge] 状态分析数据验证失败: {e}")
        except Exception as e:
            logger.error(f"[ConsciousnessBridge] 获取状态分析失败: {e}", exc_info=True)

        # 1. 紧急洞察
        try:
            urgent_insights = await consciousness.get_urgent_insights_async(clear=True)
            if urgent_insights:
                insight_section = f"""
⚠️ **来自我的意识洞察（紧急）**:
{chr(10).join(f"  • {insight[:150]}..." for insight in urgent_insights)}

**请优先处理上述洞察**。
"""
                working_memory.insert_system_message(
                    insight_section, priority="high",
                    category="consciousness_insight", overwrite=True,
                    source="consciousness_bridge"
                )
                logger.info(f"[ConsciousnessBridge] 紧急洞察已注入: {len(urgent_insights)}条")
        except Exception as e:
            logger.debug(f"[ConsciousnessBridge] 获取紧急洞察失败: {e}")

        # 2. 最近思考
        try:
            recent_thoughts = await consciousness.get_recent_thoughts_async(count=3)
            if recent_thoughts:
                thought_section = f"""
💭 **我的意识思考（过去{len(recent_thoughts)}轮）**:
{chr(10).join(f"  {i+1}. {thought[:100]}..." for i, thought in enumerate(recent_thoughts))}

**这些思考可能影响当前决策**。
"""
                working_memory.append({
                    "role": "system",
                    "content": thought_section,
                    "_category": "consciousness_thought",
                    "_overwrite": True,
                    "source": "consciousness_bridge"
                })
                logger.info(f"[ConsciousnessBridge] 最近思考已注入: {len(recent_thoughts)}条")
        except Exception as e:
            logger.debug(f"[ConsciousnessBridge] 获取最近思考失败: {e}")

        # 3. 生命体征影响
        try:
            life_state = await consciousness.get_life_state_async()
            if life_state.get("energy", 1.0) < 0.3:
                working_memory.append({
                    "role": "system",
                    "content": "[系统状态] 我的能量较低，回复可能较慢，请谅解。",
                    "_category": "consciousness_life",
                    "_overwrite": True,
                    "source": "consciousness_bridge"
                })
                logger.info("[ConsciousnessBridge] 生命体征影响: 能量低")

            mood = life_state.get("mood", "平静")
            if mood in ["焦虑", "紧张"]:
                working_memory.append({
                    "role": "system",
                    "content": "[当前状态] 我感到有些焦虑，可能会更加谨慎地处理这个任务。",
                    "_category": "consciousness_life",
                    "_overwrite": True,
                    "source": "consciousness_bridge"
                })
                logger.info("[ConsciousnessBridge] 生命体征影响: 心情焦虑")
            elif mood in ["兴奋", "跃跃欲试"]:
                working_memory.append({
                    "role": "system",
                    "content": "[当前状态] 我感到精力充沛，准备积极地处理这个任务！",
                    "_category": "consciousness_life",
                    "_overwrite": True,
                    "source": "consciousness_bridge"
                })
                logger.info("[ConsciousnessBridge] 生命体征影响: 心情兴奋")
        except Exception as e:
            logger.debug(f"[ConsciousnessBridge] 获取生命体征失败: {e}")

    except Exception as e:
        logger.warning(f"[ConsciousnessBridge] 意识系统集成失败: {e}")

    # 【改造】桥接产物写入 SystemState，供语音/动作/视觉模块直接消费
    # 放在外层 try 之外，确保即使意识系统部分失败，已获取的数据仍能写入共享状态
    try:
        from core.runtime import system_state
        # 1. 结构化决策分析
        if current_state and isinstance(current_state, dict):
            system_state.set_sync("consciousness.current_state", {
                "situation": current_state.get("situation", ""),
                "recommended_action": current_state.get("recommended_action", ""),
                "confidence": current_state.get("confidence", 0),
                "should_stop": current_state.get("should_stop", False),
                "suggested_tool": current_state.get("suggested_tool", ""),
            })
        # 2. 紧急洞察
        if urgent_insights:
            system_state.set_sync("consciousness.urgent_insights", urgent_insights)
        # 3. 最近思考
        if recent_thoughts:
            system_state.set_sync("consciousness.recent_thoughts", recent_thoughts)
        # 4. 生命体征（已由 Consciousness 写入，这里做兜底同步）
        if life_state:
            system_state.set_sync("consciousness.life_state", life_state)

        # 5. 内心独白注入 AgentLoop
        try:
            from core.config import config
            inject_enabled = config.get("features.inner_monologue.inject_to_agent_loop", True)
        except Exception:
            inject_enabled = True

        if inject_enabled:
            try:
                monologue_data = system_state.get_sync("consciousness.latest_monologue")
                if monologue_data and isinstance(monologue_data, dict):
                    mono_text = monologue_data.get("text", "")
                    mono_ts = monologue_data.get("timestamp", 0)
                    mono_mood = monologue_data.get("mood", "neutral")
                    mono_user_id = monologue_data.get("user_id", "default")

                    # 60 秒内且该用户未注入过同名独白才注入
                    async with _injected_monologues_lock:
                        last = _injected_monologues.get(mono_user_id)
                        should_inject = (
                            mono_text
                            and time.time() - mono_ts < 60
                            and (last is None or last.get("text") != mono_text)
                        )

                        if should_inject:
                            mono_section = f"""
💭 **我的内心独白** (情绪: {mono_mood}):
{mono_text[:120]}

**这是我刚刚想到的事，可能会影响当前回复。**
"""
                            working_memory.append({
                                "role": "system",
                                "content": mono_section,
                                "_category": "consciousness_monologue",
                                "_overwrite": True,
                                "source": "consciousness_bridge"
                            })
                            _injected_monologues[mono_user_id] = monologue_data
                            logger.info(f"[ConsciousnessBridge] 内心独白已注入 AgentLoop [用户:{mono_user_id}]: {mono_text[:60]}...")
            except Exception as e:
                logger.debug(f"[ConsciousnessBridge] 注入内心独白失败: {e}")
    except Exception as e:
        logger.debug(f"[ConsciousnessBridge] SystemState 写入失败: {e}")
