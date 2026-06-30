#!/usr/bin/env python3
"""
PromptAssemblyBridge - Prompt 片段准备桥接器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的 exploration_enhancement、layer_prompt、
three_views、reflection、experience、world_model 等片段准备逻辑。
"""

from dataclasses import dataclass
from typing import Any

from core.agent.phase_context import PhaseContext
from core.agent.phase_registry import register_phase
from core.logger import logger


@dataclass
class PromptFragments:
    exploration_enhancement: str = ""
    layer_prompt: str = ""
    three_views_prompt: str = ""
    reflection_section: str = ""
    experience_context: str = ""
    world_model_section: str = ""
    trading_section: str = ""  # ← 新增：交易上下文（来自指挥官AI）
    exploration_context: Any = None


async def prepare_prompt_fragments_async(ctx: PhaseContext) -> PromptFragments:
    """准备 Prompt 组装所需的所有片段。

    从 agent_loop.py 内联逻辑提取，保持原有行为不变。
    """
    # 从统一上下文读取原来的一堆参数
    assembler = ctx.get("assembler")

    # 防御性兜底：assembler 未传入时返回最小可用结构，不崩
    if assembler is None:
        logger.warning("[PromptAssemblyBridge] assembler 未传入，跳过三观/层级组装")
        return PromptFragments()

    working_memory = ctx.working_memory
    user_instruction = ctx.get("user_instruction", "")
    user_id = ctx.user_id
    ctx.get("task_type", "default")
    exploration_engine = ctx.get("exploration_engine")
    exploration_context = ctx.get("exploration_context")
    prompt_builder = ctx.get("prompt_builder")
    reflection_context = ctx.get("reflection_context", "")
    belief_confidence = ctx.get("belief_confidence", 0.5)
    strategy_recommendation = ctx.get("strategy_recommendation", "")
    world_model_manager = ctx.get("world_model_manager")

    fragments = PromptFragments()

    # [3-7架构] 获取探索提示增强
    try:
        if exploration_context:
            working_memory.exploration_round = min(getattr(working_memory, 'exploration_round', 0) + 1, 10)
            current_round = working_memory.exploration_round
            fragments.exploration_enhancement = (
                f"[认知阶段: 探索第{current_round}/3轮]\n"
                f"{exploration_context.get('instruction', '请探索最佳执行路径')}\n"
            )
            if current_round >= 3:
                _session_id = getattr(ctx, 'session_id', None) or getattr(working_memory, 'session_id', None) or ''
                fragments.exploration_context = exploration_engine.continue_exploration(
                    _session_id, {"success": True}
                )
            else:
                fragments.exploration_context = exploration_context
        else:
            fragments.exploration_enhancement = exploration_engine.get_prompt_enhancement(
                user_instruction, working_memory.exploration_round
            )
            fragments.exploration_context = exploration_context
    except Exception as e:
        logger.debug(f"[PromptAssemblyBridge] 探索增强失败: {e}")
        fragments.exploration_context = exploration_context

    # 根据当前层级补充特定提示词
    try:
        if working_memory.query_stage == "layer1":
            fragments.layer_prompt = prompt_builder.build_layer1(user_instruction, working_memory)
        elif working_memory.query_stage == "layer2":
            fragments.layer_prompt = prompt_builder.build_layer2(
                working_memory.current_category, working_memory
            )
        elif working_memory.query_stage == "layer3":
            fragments.layer_prompt = prompt_builder.build_layer3(
                working_memory.current_tool, working_memory
            )
        else:
            # 默认任务模式：system_prompt 已通过 _build_dynamic_tool_summary 注入工具分类
            # 此处不再重复注入，避免与 system_prompt 中的工具信息重叠
            fragments.layer_prompt = ""
    except Exception as e:
        logger.debug(f"[PromptAssemblyBridge] 层级提示构建失败: {e}")

    # 三观/反思/经验注入
    # three_views 已关闭：通过 roles.yaml 移除 + 此处关闭独立注入链路
    fragments.three_views_prompt = ""
    try:
        # 原 assemble_three_views 调用已禁用，保留 try 块以容纳 reflection/experience/trading 注入
        _ = ""
        fragments.reflection_section = await assembler.assemble_reflection_context(
            reflection_context=reflection_context,
            belief_confidence=belief_confidence,
            strategy_recommendation=strategy_recommendation,
            user_id=user_id,
        )
        fragments.experience_context = await assembler.assemble_experience_context(
            task_description=user_instruction,
        )
        fragments.trading_section = await assembler.assemble_trading_context(user_id=user_id)
    except Exception as e:
        logger.warning(f"[PromptAssemblyBridge] 上下文组装失败: {e}")
        fragments.three_views_prompt = ""
        fragments.reflection_section = ""
        fragments.experience_context = ""
        fragments.trading_section = ""

    # 世界模型决策预测
    try:
        if world_model_manager is not None:
            fragments.world_model_section = await world_model_manager.get_prediction_for_decision(working_memory)
            if fragments.world_model_section:
                logger.info(
                    f"[P0断裂点#1修复] 世界模型预测已注入核心提示词，"
                    f"长度: {len(fragments.world_model_section)}"
                )
    except Exception as e:
        logger.debug(f"[PromptAssemblyBridge] 世界模型预测获取失败: {e}")
        fragments.world_model_section = ""

    return fragments


register_phase("prompt_assembly", prepare_prompt_fragments_async, order=2)
