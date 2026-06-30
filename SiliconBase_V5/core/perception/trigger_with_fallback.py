#!/usr/bin/env python3
"""
感知触发统一接口（V1.0 + V1.1 增强层）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

设计: V1.1 增强失败时自动降级到 V1.0
规则: 不修改原有代码，只在此文件做集成

Phase 2 规则遵守:
- 增强层独立文件
- 不污染 perception_manager.py
- 严格降级机制
"""

import os
import time
from typing import Any


# 延迟导入避免循环依赖
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('trigger_fallback')


def should_trigger_perception(
    user_input: str,
    context: dict[str, Any] | None = None,
    trigger_keywords: list = None  # V1.0 基础关键词列表
) -> tuple[bool, dict[str, Any]]:
    """
    统一触发判断接口（V1.0 + V1.1 增强层）

    【规则遵守】
    - 返回值规范: (bool, dict) 元组
    - 空保护不静默: 空输入记录 warning
    - 降级机制: V1.1 失败自动降级到 V1.0

    Args:
        user_input: 用户输入
        context: 上下文
        trigger_keywords: V1.0 基础关键词列表

    Returns:
        (是否触发, 详细信息)
        详细信息包含: {
            "method": "semantic"|"keyword",
            "confidence": float,
            "reason": str,
            "latency_ms": float
        }
    """
    logger = _get_logger()
    start_time = time.time()

    # 空保护不静默
    if not user_input or not user_input.strip():
        logger.warning("[Trigger] user_input 为空")
        return False, {"reason": "empty_input", "method": "none"}

    # 检查增强功能开关
    use_enhanced = os.environ.get("ENABLE_PERCEPTION_SEMANTIC", "true").lower() == "true"

    # 尝试 V1.1 增强层
    if use_enhanced:
        try:
            from .semantic_trigger_enhanced import should_trigger_semantic

            result = should_trigger_semantic(user_input, context)

            if result is not None:
                latency_ms = (time.time() - start_time) * 1000

                return result.should_trigger, {
                    "method": "semantic",
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "matched_intent": result.matched_intent,
                    "latency_ms": latency_ms,
                    "used_enhanced": True
                }
            else:
                logger.warning("[Trigger] V1.1 返回 None，准备降级")

        except Exception as e:
            logger.warning(f"[Trigger] V1.1 异常: {e}，降级到 V1.0")

    # V1.0 基础层（降级）
    return _should_trigger_base(user_input, trigger_keywords or [], start_time)


def _should_trigger_base(
    user_input: str,
    trigger_keywords: list,
    start_time: float
) -> tuple[bool, dict[str, Any]]:
    """
    V1.0 基础触发判断（关键词匹配）

    【规则遵守】
    - 私有函数，不暴露给外部
    - 返回值与增强层一致
    """
    logger = _get_logger()
    user_input_lower = user_input.lower()

    for keyword in trigger_keywords:
        if keyword in user_input_lower:
            latency_ms = (time.time() - start_time) * 1000
            logger.debug(f"[Trigger] V1.0 关键词触发: '{keyword}'")
            return True, {
                "method": "keyword",
                "confidence": 1.0,
                "reason": f"关键词匹配: {keyword}",
                "matched_keyword": keyword,
                "latency_ms": latency_ms,
                "used_enhanced": False
            }

    latency_ms = (time.time() - start_time) * 1000
    return False, {
        "method": "keyword",
        "confidence": 0.0,
        "reason": "无关键词匹配",
        "latency_ms": latency_ms,
        "used_enhanced": False
    }


__all__ = ['should_trigger_perception']
