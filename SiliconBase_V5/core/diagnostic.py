"""
SiliconBase V5 全局故障诊断模块

核心原则：宁可崩溃，绝不静默。
"""

import asyncio
import logging
import os
import sys
import traceback
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 诊断开关 ──────────────────────────────────────────────
DIAGNOSTIC_MODE: bool = os.environ.get("DIAGNOSTIC_MODE", "").lower() in ("true", "1", "yes", "on")

if DIAGNOSTIC_MODE:
    print("[DIAGNOSTIC] 警告: 诊断模式已启用，所有降级策略失效，异常将直接抛出！")


def is_diagnostic_mode() -> bool:
    """返回当前是否处于诊断模式"""
    return DIAGNOSTIC_MODE


def diagnostic_raise(original_exception: Exception, context: str = "") -> None:
    """
    诊断模式专用：直接抛出原始异常，不允许任何降级。
    如果传入了上下文，会作为异常说明附加到日志中。
    """
    msg = f"[DIAGNOSTIC] {context}: {type(original_exception).__name__}: {original_exception}"
    logger.error(msg)
    if context:
        raise type(original_exception)(f"{context} -> {original_exception}") from original_exception
    raise original_exception


# ── 异步任务异常捕获 ──────────────────────────────────────
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_ASYNC_EXCEPTION_LOG = _LOG_DIR / "async_exceptions.log"


def _log_async_exception(task: asyncio.Task) -> None:
    """asyncio.Task 的 done_callback：检查未捕获异常并强制记录"""
    exc = task.exception()
    if exc is None:
        return

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    timestamp = datetime.now().isoformat()
    log_entry = (
        f"\n{'='*60}\n"
        f"[ASYNC_EXCEPTION] {timestamp}\n"
        f"Task: {task.get_name()}\n"
        f"Exception: {type(exc).__name__}: {exc}\n"
        f"Traceback:\n{tb}"
        f"{'='*60}\n"
    )

    # 强制写入独立日志文件
    try:
        with open(_ASYNC_EXCEPTION_LOG, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[DIAGNOSTIC] 无法写入 async_exceptions.log: {e}", file=sys.stderr)

    # 诊断模式下：直接打印到 stderr，绝不静默
    print(log_entry, file=sys.stderr)

    # 如果是 CancelledError，不算异常，不抛
    if isinstance(exc, asyncio.CancelledError):
        return

    # 诊断模式下：强制重新抛出，让事件循环崩溃
    if DIAGNOSTIC_MODE:
        raise exc


def safe_create_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Task:
    """
    替代裸 safe_create_task(, name="async_task")：
    1. 自动添加 done_callback 检查未捕获异常
    2. 诊断模式下异常会被重新抛出
    3. 所有异常都会写入 logs/async_exceptions.log
    """
    task = asyncio.create_task(coro, name=name) if loop is None else loop.create_task(coro, name=name)

    task.add_done_callback(_log_async_exception)
    return task


# ── 降级策略拦截器 ────────────────────────────────────────
def no_fallback_in_diagnostic(
    fallback_fn: Callable,
    original_exception: Exception | None = None,
    context: str = "",
) -> Any:
    """
    在降级逻辑分支点调用此函数。
    诊断模式下：直接抛出原始异常，不执行 fallback。
    生产模式下：正常执行 fallback_fn。
    """
    if DIAGNOSTIC_MODE:
        if original_exception is not None:
            diagnostic_raise(original_exception, context)
        raise RuntimeError(f"[DIAGNOSTIC] 降级路径被阻断: {context}")
    return fallback_fn()


# ── 结果有效性断言 ────────────────────────────────────────
def assert_valid_result(
    result: Any,
    *,
    allow_none: bool = False,
    allow_empty: bool = False,
    context: str = "",
) -> Any:
    """
    对 AI / 工具 / 存储的返回结果做有效性断言。
    诊断模式下：无效结果直接抛 ValueError，绝不静默返回 None。
    """
    if not DIAGNOSTIC_MODE:
        return result

    ctx = f" [{context}]" if context else ""

    if result is None and not allow_none:
        msg = f"[DIAGNOSTIC] 返回结果为 None，不允许{ctx}"
        logger.error(msg)
        raise ValueError(msg)

    if not allow_empty and isinstance(result, (str, list, dict, tuple, set)) and len(result) == 0:
        msg = f"[DIAGNOSTIC] 返回结果为空容器，不允许{ctx}"
        logger.error(msg)
        raise ValueError(msg)

    return result


def assert_ai_output(
    output: Any,
    context: str = "AI输出",
) -> str:
    """
    专门用于校验 AI 模型输出。
    无效输出 = 明确报错 + 完整日志。
    """
    if not DIAGNOSTIC_MODE:
        return output if isinstance(output, str) else str(output)

    if output is None:
        msg = f"[DIAGNOSTIC] {context} 返回 None，AI 未产生任何输出"
        logger.error(msg)
        raise ValueError(msg)

    if isinstance(output, str):
        stripped = output.strip()
        if not stripped:
            msg = f"[DIAGNOSTIC] {context} 返回空字符串，AI 输出无效"
            logger.error(msg)
            raise ValueError(msg)
        return stripped

    # 非字符串类型直接拒绝
    msg = f"[DIAGNOSTIC] {context} 返回类型 {type(output).__name__}，预期为字符串"
    logger.error(msg)
    raise TypeError(msg)


# ── except Exception 包装器 ───────────────────────────────
def diagnostic_except_handler(
    exc: Exception,
    context: str = "",
    logger_instance: logging.Logger | None = None,
) -> None:
    """
    在 except Exception 块中调用，替代静默日志。
    诊断模式下：直接重新抛出异常。
    生产模式下：打印 ERROR 日志并继续。
    """
    log = logger_instance or logger
    tb = traceback.format_exc()
    msg = f"[DIAGNOSTIC] {context}: {type(exc).__name__}: {exc}"
    log.error(msg)
    log.error(f"Traceback:\n{tb}")

    if DIAGNOSTIC_MODE:
        raise exc
