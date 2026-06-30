"""
ReflectionBridge - ReAct 反思循环桥接器
从 agent_loop.py 抽取的反思调用封装。
"""

import asyncio
import time
from typing import Any

from core.logger import logger

# ═══════════════════════════════════════════════════════════════════════════════
# 反思去重锁与冷却窗口
# ═══════════════════════════════════════════════════════════════════════════════
_reflection_lock = asyncio.Lock()
_last_reflection_time: float = 0.0
_LAST_REFLECTION_COOLDOWN = 10.0  # 10秒内同类型反思只执行一次


async def reflect_with_dedup(
    reflector,
    task: str,
    step_info: dict,
    trajectory: list,
    reflection_type: str = "default"
) -> dict | None:
    """带去重的反思调用。

    reflection_type: 用于区分不同类型的反思（failure/general/hook）
    返回: 反思结果，或 None（被去重跳过）
    """
    async with _reflection_lock:
        global _last_reflection_time
        now = time.time()

        if now - _last_reflection_time < _LAST_REFLECTION_COOLDOWN:
            logger.info(
                f"[ReflectionBridge] 反思去重：{reflection_type} 反思被跳过"
                f"（距离上次反思 {now - _last_reflection_time:.1f}s，冷却 {_LAST_REFLECTION_COOLDOWN}s）"
            )
            return None

        _last_reflection_time = now
        result = await reflector.reflect_after_step(task, step_info, trajectory)
        return result


async def run_react_reflection(
    reflector: Any,
    user_instruction: str,
    parsed: Any,
    result: dict[str, Any],
    execution_history: list[dict],
    working_memory: Any,
) -> None:
    """执行 ReAct 反思循环。

    调用 reflector.reflect_after_step() 并根据反思建议更新 working_memory。
    任何错误均降级处理，不阻断主循环。
    """
    try:
        if reflector is not None:
            reflection = await reflect_with_dedup(
                reflector=reflector,
                task=user_instruction,
                step_info={
                    "tool": parsed.target_tool,
                    "params": parsed.params,
                    "result": result,
                    "success": result.get("success", False) if isinstance(result, dict) else False,
                    "step_number": len(execution_history),
                },
                trajectory=execution_history[-5:],
                reflection_type="hook"
            )
            if reflection and getattr(reflection, 'needs_adjustment', False):
                working_memory.append({
                    "role": "system",
                    "source": "reflection_bridge",
                    "content": f"[反思] {getattr(reflection, 'suggestion', '需要调整策略')}",
                })
                logger.info(f"[AgentLoop] 反思建议: {getattr(reflection, 'suggestion', '')}")
        else:
            logger.debug("[AgentLoop] Reflector未初始化，跳过ReAct反思")
    except Exception as e:
        logger.warning(f"[AgentLoop] 反思系统调用失败: {e}")


async def run_tool_failure_reflection(
    reflector: Any,
    user_instruction: str,
    parsed: Any,
    result: dict[str, Any],
    execution_history: list[dict],
    working_memory: Any,
    chat_history: list[dict] | None = None,
    tool_empty_async: bool = False,
    tool_failed_async: bool = False,
) -> None:
    """工具失败后的深度反思与策略调整。

    从 agent_loop.py 内联逻辑提取，封装反射器调用、反思消息构建、
    working_memory / chat_history 更新、以及强制继续标志设置。
    """
    try:
        step_info = {
            "tool": parsed.target_tool,
            "params": parsed.params if hasattr(parsed, 'params') else {},
            "result": result,
            "success": result.get("success", False) and not tool_empty_async,
            "step_number": len(execution_history) if execution_history else 0,
        }

        if reflector is not None:
            reflection = await reflect_with_dedup(
                reflector=reflector,
                task=user_instruction,
                step_info=step_info,
                trajectory=[],
                reflection_type="tool_failure"
            )
        else:
            reflection = None
            logger.warning("[AgentLoop] Reflector不可用，跳过反思")

        if reflection:
            failure_reason = result.get('user_message', '未知错误')
            if tool_empty_async:
                failure_reason = "工具返回了空结果，可能需要调整参数或尝试其他工具"

            reflection_msg = (
                f"【工具执行反思】\n"
                f"工具: {parsed.target_tool}\n"
                f"状态: {'执行失败' if tool_failed_async else '返回空结果'}\n"
                f"原因: {failure_reason}\n"
                f"反思洞察: {getattr(reflection, 'insight', '无')}\n"
                f"建议: {getattr(reflection, 'suggestion', '请尝试其他方法或工具')}\n"
                f"替代工具: {getattr(reflection, 'metadata', {}).get('alternative_tool', '无')}\n"
                f"\n[重要] 请根据反思建议调整策略并继续执行，不要结束任务。"
            )

            working_memory.append({
                "role": "system",
                "source": "reflection_bridge",
                "content": reflection_msg
            })

            if chat_history is not None:
                chat_history.append({
                    "role": "system",
                    "content": f"[系统反思] {getattr(reflection, 'suggestion', '需要调整策略')}"
                })

            logger.info(
                f"[AgentLoop] 工具失败反思已触发: "
                f"{getattr(reflection, 'suggestion', '')[:80]}..."
            )

            working_memory.force_continue = True
            working_memory.reflection_triggered = True

    except Exception as e:
        logger.warning(f"[AgentLoop] 工具失败反思系统调用失败: {e}")
        working_memory.append({
            "role": "system",
            "source": "reflection_bridge",
            "content": f"工具{parsed.target_tool}执行未成功，请分析原因并尝试其他方法继续完成任务。"
        })
