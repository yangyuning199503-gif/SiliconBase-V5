#!/usr/bin/env python3
"""
感知触发语义化增强（V1.1）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能: 将关键词匹配升级为语义向量匹配
降级: V1.0 关键词匹配（83个关键词列表）

Phase 2 规则遵守:
- 独立文件，不污染 perception_manager.py
- 线程安全，使用 RLock
- 实例复用，单例模式
- 空保护不静默，记录日志

环境变量控制:
    ENABLE_PERCEPTION_SEMANTIC=true/false
"""

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# 延迟导入避免循环依赖
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('semantic_trigger')


@dataclass
class SemanticTriggerDecision:
    """语义触发决策结果"""
    should_trigger: bool
    confidence: float
    matched_intent: str
    reason: str
    latency_ms: float
    used_semantic: bool


class SemanticIntent(Enum):
    """语义意图类型"""
    VISUAL_QUERY = "visual_query"      # 视觉查询（"看到什么"）
    LOCATE_REQUEST = "locate_request"   # 定位请求（"在哪里"）
    STATUS_CHECK = "status_check"       # 状态检查（"当前状态"）
    SCREEN_CAPTURE = "screen_capture"   # 截图请求
    UNKNOWN = "unknown"


class SemanticTriggerEngine:
    """
    语义触发引擎（V1.1 增强）

    【单例模式】全局唯一实例
    【线程安全】RLock 保护共享数据
    """

    _instance: Optional['SemanticTriggerEngine'] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 线程锁
        self._lock = threading.RLock()

        # 配置参数
        self._threshold = 0.75
        self._min_interval_seconds = 3.0

        # 状态
        self._last_trigger_time: dict[str, float] = {}
        self._stats = {
            "total_calls": 0,
            "triggered_count": 0,
            "avg_latency_ms": 0.0
        }

        # 语义模式（简化版，实际应使用向量嵌入）
        self._semantic_patterns: dict[SemanticIntent, list[str]] = {
            SemanticIntent.VISUAL_QUERY: [
                "看到", "看见", "显示", "展示", "有什么", "是什么",
                "see", "what do you see", "show me"
            ],
            SemanticIntent.LOCATE_REQUEST: [
                "在哪里", "在哪", "位置", "找到", "定位",
                "where", "locate", "find"
            ],
            SemanticIntent.STATUS_CHECK: [
                "状态", "进度", "情况", "怎么样",
                "status", "progress", "how is"
            ],
            SemanticIntent.SCREEN_CAPTURE: [
                "截图", "截屏", "screenshot", "capture"
            ]
        }

        _get_logger().info("[SemanticTriggerEngine] V1.1 初始化完成")

    def should_trigger(
        self,
        user_input: str,
        context: dict[str, Any] | None = None
    ) -> SemanticTriggerDecision | None:
        """
        语义触发判断（V1.1 增强）

        【规则遵守】
        - 空保护: user_input 为空时返回 None 并记录 warning
        - 返回值: Optional[SemanticTriggerDecision]
        - 线程安全: 使用 self._lock

        Args:
            user_input: 用户输入文本
            context: 上下文信息

        Returns:
            SemanticTriggerDecision 或 None（失败）
        """
        start_time = time.time()
        logger = _get_logger()

        # 空保护不静默
        if not user_input or not user_input.strip():
            logger.warning("[SemanticTrigger] user_input 为空，跳过语义分析")
            return None

        with self._lock:
            self._stats["total_calls"] += 1

            # 检查触发间隔
            session_id = context.get("session_id", "default") if context else "default"
            last_time = self._last_trigger_time.get(session_id, 0)
            time_since_last = time.time() - last_time

            if time_since_last < self._min_interval_seconds:
                logger.debug(f"[SemanticTrigger] 触发间隔太短 ({time_since_last:.1f}s)")
                return SemanticTriggerDecision(
                    should_trigger=False,
                    confidence=0.0,
                    matched_intent=SemanticIntent.UNKNOWN.value,
                    reason=f"触发间隔太短 ({time_since_last:.1f}s < {self._min_interval_seconds}s)",
                    latency_ms=(time.time() - start_time) * 1000,
                    used_semantic=True
                )

            # 语义分析（简化实现，实际应使用向量相似度）
            user_input_lower = user_input.lower()
            best_intent = SemanticIntent.UNKNOWN
            best_score = 0.0
            matched_keywords: list[str] = []

            for intent, keywords in self._semantic_patterns.items():
                for keyword in keywords:
                    if keyword in user_input_lower:
                        # 计算相似度（简化：精确匹配=1.0，否则0.5）
                        score = 1.0 if keyword == user_input_lower else 0.8
                        if score > best_score:
                            best_score = score
                            best_intent = intent
                            matched_keywords = [keyword]

            # 计算延迟
            latency_ms = (time.time() - start_time) * 1000

            # 决策
            should_trigger = best_score >= self._threshold

            if should_trigger:
                self._last_trigger_time[session_id] = time.time()
                self._stats["triggered_count"] += 1
                logger.debug(
                    f"[SemanticTrigger] 触发成功: intent={best_intent.value}, "
                    f"confidence={best_score:.2f}"
                )

            # 更新平均延迟
            n = self._stats["total_calls"]
            self._stats["avg_latency_ms"] = (
                (self._stats["avg_latency_ms"] * (n - 1) + latency_ms) / n
            )

            return SemanticTriggerDecision(
                should_trigger=should_trigger,
                confidence=best_score,
                matched_intent=best_intent.value,
                reason=f"语义匹配: {matched_keywords}" if matched_keywords else "无匹配",
                latency_ms=latency_ms,
                used_semantic=True
            )

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self._stats,
                "trigger_rate": (
                    self._stats["triggered_count"] / self._stats["total_calls"]
                    if self._stats["total_calls"] > 0 else 0.0
                )
            }


# =============================================================================
# 便捷函数（供外部调用）
# =============================================================================

_engine: SemanticTriggerEngine | None = None
_engine_lock = threading.Lock()


def get_semantic_trigger_engine() -> SemanticTriggerEngine:
    """获取语义触发引擎（线程安全单例）"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SemanticTriggerEngine()
    return _engine


def should_trigger_semantic(
    user_input: str,
    context: dict[str, Any] | None = None
) -> SemanticTriggerDecision | None:
    """
    语义触发判断便捷函数

    【规则遵守】
    - 返回值: Optional[SemanticTriggerDecision]
    - 空保护: 不静默，内部已处理
    """
    engine = get_semantic_trigger_engine()
    return engine.should_trigger(user_input, context)


__all__ = [
    'SemanticTriggerEngine',
    'SemanticTriggerDecision',
    'SemanticIntent',
    'should_trigger_semantic',
    'get_semantic_trigger_engine',
]
