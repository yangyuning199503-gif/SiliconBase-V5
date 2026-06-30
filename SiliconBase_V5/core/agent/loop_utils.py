#!/usr/bin/env python3
"""
LoopUtils - AgentLoop 通用辅助函数集合
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的薄工具函数，无状态、无副作用。
"""

from typing import Any

from core.agent.agent_loop_hooks import AgentLoopHooks, HookContext
from core.ai.ai_adapter import call_thinker_async


async def call_llm_with_retry(
    messages: list[dict[str, str]],
    hook_ctx: HookContext,
    agent_loop_hooks: AgentLoopHooks,
    logger: Any,
    max_retries: int = 2,
    hard_timeout: int = 70,
) -> tuple[str, HookContext]:
    """调用 LLM，支持 after_prompt Hook 的幻觉检测重试闭环。

    Args:
        messages: 传入 messages（会被原地修改注入约束提示词）
        hook_ctx: 当前 Hook 上下文
        agent_loop_hooks: Hook 注册器实例
        logger: 日志记录器
        max_retries: 最大重试次数（默认 2）

    Returns:
        (response, hook_ctx)
    """
    import asyncio

    from core.ai.model_router import ModelProviderNotAvailableError, ModelRoutingError
    from core.exceptions import AIConnectionError, AITimeoutError

    # LLM 调用异常重试（网络/超时/服务不可用）
    llm_retry_count = 0
    last_error = None
    while True:
        try:
            response = await call_thinker_async(messages, hard_timeout=hard_timeout)
            break
        except (AIConnectionError, AITimeoutError, ModelRoutingError, ModelProviderNotAvailableError) as e:
            last_error = e
            if llm_retry_count < max_retries:
                llm_retry_count += 1
                # 【修复】AI服务不可用时缩短等待时间，默认5秒
                wait_time = min(1.0 * llm_retry_count, 5.0)
                logger.warning(f"[LLM-Retry] AI调用失败，第 {llm_retry_count} 次重试: {e}")
                await asyncio.sleep(wait_time)
            else:
                # 【修复】AI服务不可用时不再抛异常，返回友好错误信息
                error_str = str(last_error)
                is_provider_unavailable = any(kw in error_str for kw in [
                    "服务不可用", "不可用", "ModelRoutingError", "所有AI模型都不可用",
                    "Connection refused", "ConnectionError"
                ])
                if is_provider_unavailable:
                    logger.warning(f"[LLM-Retry] AI服务不可用，已放弃重试: {last_error}")
                    raise RuntimeError("AI服务暂时不可用，请稍后重试") from last_error
                raise last_error from e

    hook_result = await agent_loop_hooks.execute_async_with_signals(
        'after_prompt', hook_ctx, response=response
    )
    hook_ctx = hook_result.ctx

    # 【P1-2】解析并记录 AI 决策过程到 decisions collection
    try:
        from core.diagnostic import safe_create_task
        from core.memory.memory_service import get_memory_service
        from core.traceability import get_trace_id, save_decision
        from core.utils.text_parser import extract_thinking_from_response, extract_tool_calls_from_response
        _tid = get_trace_id()
        _reasoning = extract_thinking_from_response(response) if 'extract_thinking_from_response' in dir() else ""
        _reasoning = _reasoning or ""
        _tool_calls = extract_tool_calls_from_response(response) if 'extract_tool_calls_from_response' in dir() else []
        _decision = f"工具调用: {', '.join([t.get('tool', '') for t in _tool_calls[:2]])}" if _tool_calls else "直接回答"
        if _tid or hook_ctx.user_id:
            _ms = await get_memory_service()
            _task_obj = getattr(hook_ctx, 'task', None)
            _intent_obj = getattr(_task_obj, 'intent', None) or {}
            _query = _intent_obj.get('raw', '')
            safe_create_task(save_decision(
                user_id=hook_ctx.user_id or "default",
                query=_query,
                decision=_decision,
                reasoning=str(_reasoning)[:300],
                trace_id=_tid,
                memory_service=_ms,
            ), name="loop_utils_save_decision")
    except Exception as e:
        logger.error(f"[LoopUtils] 决策记录失败: {e}", exc_info=True)

    # 幻觉检测重试闭环
    hallucination_retry_count = 0
    while hook_result.should_retry and hallucination_retry_count < max_retries:
        hallucination_retry_count += 1
        logger.warning(
            f"[Hallucination-Async] 检测到高风险响应，"
            f"触发第 {hallucination_retry_count} 次重试: {hook_result.retry_reason}"
        )

        try:
            # 【P1 改造】V2 安全架构已强制开启，直接从 policy.py 导入
            from core.safety.policy import inject_hallucination_prompt

            constrained_system_prompt = inject_hallucination_prompt("")
            if messages and messages[0].get("role") == "system":
                original_prompt = messages[0].get("content", "")
                messages[0]["content"] = f"{original_prompt}\n\n[约束] {constrained_system_prompt}"
            else:
                messages.insert(0, {"role": "system", "content": constrained_system_prompt})
        except Exception as inject_err:
            logger.error(f"[Hallucination-Async] 约束提示词注入失败: {inject_err}", exc_info=True)

        # LLM 幻觉重试时同样保护网络异常（使用独立计数器）
        hallucination_llm_retry_count = 0
        while True:
            try:
                response = await call_thinker_async(messages, hard_timeout=hard_timeout)
                break
            except (AIConnectionError, AITimeoutError, ModelRoutingError, ModelProviderNotAvailableError) as e:
                if hallucination_llm_retry_count < max_retries:
                    hallucination_llm_retry_count += 1
                    logger.warning(f"[LLM-Retry] 幻觉重试时调用失败，第 {hallucination_llm_retry_count} 次重试: {e}")
                    await asyncio.sleep(min(1.0 * hallucination_llm_retry_count, 5.0))
                else:
                    error_str = str(e)
                    is_provider_unavailable = any(kw in error_str for kw in [
                        "服务不可用", "不可用", "ModelRoutingError", "所有AI模型都不可用",
                        "Connection refused", "ConnectionError"
                    ])
                    if is_provider_unavailable:
                        logger.warning(f"[LLM-Retry] AI服务不可用，已放弃重试: {e}")
                        raise RuntimeError("AI服务暂时不可用，请稍后重试") from e
                    raise

        hook_result = await agent_loop_hooks.execute_async_with_signals(
            'after_prompt', hook_ctx, response=response
        )
        hook_ctx = hook_result.ctx

    return response, hook_ctx


async def trigger_tool_evolution(
    task_history: list[dict],
    evolution_manager: Any,
    logger: Any,
) -> None:
    """任务完成后检查是否需要进化新工具。

    从 agent_loop.py 内联逻辑提取，封装进化检查、分析和生成流程。
    """
    try:
        if await evolution_manager.need_new_tool(task_history):
            logger.info("[AgentLoop] 检测到工具缺口，启动进化...")
            new_tool_spec = await evolution_manager.analyze_and_generate_tool(task_history)
            if new_tool_spec:
                success = await evolution_manager.evolve_new_tool(new_tool_spec)
                if success:
                    logger.info(f"[AgentLoop] 系统已进化出新工具: {new_tool_spec.get('name')}")
    except Exception as e:
        logger.error(f"[AgentLoop] 进化检查失败: {e}", exc_info=True)

import time
from typing import Any

try:
    from core.constants import MemoryWeights
except ImportError:
    class MemoryWeights:
        L2_SEMANTIC = 0.4
        L3_WORKFLOW = 0.3
        L4_EPISODIC = 0.2
        L5_PROCEDURAL = 0.1

from core.logger import logger


def _prepare_response_with_memory_metadata(
    response_text: str,
    working_memory,
    message_id: str | None = None
) -> dict[str, Any]:
    """准备带有记忆元数据的响应（已从 agent_loop.py 迁移）。"""
    response = {
        "role": "assistant",
        "content": response_text,
        "timestamp": time.time(),
    }

    if message_id:
        response["message_id"] = message_id

    memory_metadata = {
        "memory_count": 0,
        "memory_ids": [],
        "relevance_score": 0.0,
        "memory_types": []
    }

    try:
        saved_metadata = getattr(working_memory, 'last_memory_metadata', None)

        if saved_metadata:
            total_count = (
                saved_metadata.get('l1_count', 0) +
                saved_metadata.get('l2_count', 0) +
                saved_metadata.get('l3_count', 0) +
                saved_metadata.get('l4_count', 0)
            )
            memory_metadata["memory_count"] = total_count

            all_ids = []
            all_ids.extend(saved_metadata.get('l1_ids', []))
            all_ids.extend(saved_metadata.get('l2_ids', []))
            all_ids.extend(saved_metadata.get('l3_ids', []))
            all_ids.extend(saved_metadata.get('l4_ids', []))
            memory_metadata["memory_ids"] = list(set(all_ids))

            all_types = []
            all_types.extend(saved_metadata.get('l1_types', []))
            all_types.extend(saved_metadata.get('l2_types', []))
            all_types.extend(saved_metadata.get('l3_types', []))
            all_types.extend(saved_metadata.get('l4_types', []))
            type_mapping = {
                'chat': 'context',
                'experience': 'experience',
                'strategy': 'preference',
                'knowledge': 'knowledge',
                'extracted_pattern': 'pattern'
            }
            normalized_types = [type_mapping.get(t, t) for t in all_types if t]
            memory_metadata["memory_types"] = list(set(normalized_types))

            l1_count = saved_metadata.get('l1_count', 0)
            l2_count = saved_metadata.get('l2_count', 0)
            l3_count = saved_metadata.get('l3_count', 0)
            l4_count = saved_metadata.get('l4_count', 0)

            max_expected = 10
            weighted_score = min(1.0, (
                l1_count * MemoryWeights.L2_SEMANTIC +
                l2_count * MemoryWeights.L3_WORKFLOW +
                l3_count * MemoryWeights.L4_EPISODIC +
                l4_count * MemoryWeights.L5_PROCEDURAL
            ) / max_expected)
            memory_metadata["relevance_score"] = round(weighted_score, 2)

            logger.info(f"[AgentLoop] 记忆元数据 prepared: count={memory_metadata['memory_count']}, "
                       f"types={memory_metadata['memory_types']}, score={memory_metadata['relevance_score']}")
        else:
            logger.debug("[AgentLoop] 无保存的记忆元数据，使用默认值")

    except Exception as e:
        logger.error(f"[AgentLoop] 记忆元数据获取失败: {e}", exc_info=True)

    response.update(memory_metadata)
    return response
