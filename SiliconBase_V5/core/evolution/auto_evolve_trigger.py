#!/usr/bin/env python3
"""
AutoEvolveTrigger - 自动记忆进化触发器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的自动进化嵌套函数。
"""

from typing import Any


def _auto_evolve_impl(
    execution_history: list[dict],
    user_instruction: str,
    session_id: str,
    logger: Any,
) -> None:
    """后台执行自动记忆进化（线程安全，无状态依赖）。"""
    try:
        from core.evolution.evolution import evolution
        if execution_history:
            steps = [h.get("tool") for h in execution_history if h.get("tool")]
            evolution.learn_from_execution(
                task_type="memory_compression",
                task_description=user_instruction,
                approach=str(steps),
                outcome="success",
                effectiveness=0.8,
                context={"session_id": session_id, "trigger": "auto"}
            )
            logger.info("[AgentLoop] 自动记忆进化已触发")
    except Exception as e:
        logger.debug(f"[AgentLoop] 自动记忆进化失败: {e}")


def submit_auto_evolve(
    execution_history: list[dict],
    user_instruction: str,
    session_id: str,
    executor: Any,
    logger: Any,
) -> None:
    """提交自动记忆进化任务到线程池。

    Args:
        execution_history: 执行历史
        user_instruction: 用户指令
        session_id: 会话ID
        executor: ThreadPoolExecutor 实例
        logger: 日志记录器
    """
    try:
        future = executor.submit(
            _auto_evolve_impl,
            execution_history,
            user_instruction,
            session_id,
            logger,
        )
        future.add_done_callback(
            lambda f: logger.error(
                f"[AgentLoop] auto_evolve异常: {f.exception()}", exc_info=True
            ) if f.exception() else None
        )
    except Exception as submit_error:
        logger.error(f"[AgentLoop] 提交auto_evolve失败: {submit_error}", exc_info=True)
