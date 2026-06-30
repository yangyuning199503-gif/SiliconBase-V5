#!/usr/bin/env python3
"""
LifePresence 增强层 - 连接 ImportanceEngine 和 Reflector

设计原则：
1. 不替换原有 SmartAnnouncer，而是包装增强
2. 原有逻辑作为 fallback
3. 连接现有高级功能：ImportanceEngine, Reflector
4. 错误保护：增强失败时回退到基础逻辑

作者: SiliconBase Team
版本: 1.0.0 (增强层)
"""

# ========================================
# 标准库
# ========================================
import threading
import time
from dataclasses import dataclass
from typing import Any

# ========================================
# 导入基础层（原有功能）
# ========================================
from core.consciousness.life_presence import (
    AnnounceEvent,
    NotificationLevel,
    SmartAnnouncer,
)

# ========================================
# 延迟导入高级功能（避免循环依赖）
# ========================================
_importance_engine = None
_reflector = None
_logger = None


def _get_logger():
    global _logger
    if _logger is None:
        try:
            from core.logger import logger
            _logger = logger
        except ImportError:
            import logging
            _logger = logging.getLogger('life_presence_enhanced')
    return _logger


def _get_importance_engine():
    """获取重要性引擎（延迟导入）"""
    global _importance_engine
    if _importance_engine is None:
        try:
            from core.strategy.importance_engine import ImportanceEngine
            _importance_engine = ImportanceEngine()
            _get_logger().info("[LifePresenceEnhanced] ImportanceEngine 已连接")
        except Exception as e:
            _get_logger().warning(f"[LifePresenceEnhanced] ImportanceEngine 连接失败: {e}")
            _importance_engine = False  # 标记为不可用
    return _importance_engine if _importance_engine is not False else None


def _get_reflector():
    """获取反思系统（延迟导入）"""
    global _reflector
    if _reflector is None:
        try:
            from core.reflector.reflector import Reflector
            _reflector = Reflector()
            _get_logger().info("[LifePresenceEnhanced] Reflector 已连接")
        except Exception as e:
            _get_logger().warning(f"[LifePresenceEnhanced] Reflector 连接失败: {e}")
            _reflector = False
    return _reflector if _reflector is not False else None


# ========================================
# 增强决策结果
# ========================================
@dataclass
class EnhancedDecision:
    """增强层的决策结果"""
    should_announce: bool
    base_decision: bool           # 基础层决策
    enhanced_decision: bool       # 增强层决策
    reason: str
    importance_score: float = 0.5
    confidence: float = 1.0
    used_enhancement: bool = False


# ========================================
# 学习记忆（简单版）
# ========================================
class AnnouncementLearningMemory:
    """
    播报学习记忆

    记录历史事件和AI反应，用于学习
    """

    def __init__(self, max_size: int = 1000):
        self._history: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._max_size = max_size

    def record_event(self, event_key: str, context: dict[str, Any]):
        """记录事件"""
        with self._lock:
            if event_key not in self._history:
                self._history[event_key] = {
                    "count": 0,
                    "contexts": [],
                    "ai_reactions": [],
                    "learned_importance": 0.5
                }

            self._history[event_key]["count"] += 1
            self._history[event_key]["contexts"].append({
                "timestamp": time.time(),
                "context": context
            })

            # 限制历史长度
            if len(self._history[event_key]["contexts"]) > 10:
                self._history[event_key]["contexts"] = self._history[event_key]["contexts"][-10:]

    def record_ai_reaction(self, event_key: str, reaction: str):
        """
        记录AI对播报的反应

        reaction: "acknowledged", "ignored", "interrupted", "asked_for_repeat"
        """
        with self._lock:
            if event_key not in self._history:
                return

            self._history[event_key]["ai_reactions"].append({
                "reaction": reaction,
                "timestamp": time.time()
            })

            # 基于反应调整重要性
            current = self._history[event_key]["learned_importance"]
            if reaction == "ignored":
                new_val = max(0.1, current - 0.05)
            elif reaction == "acknowledged":
                new_val = min(0.9, current + 0.02)
            elif reaction == "interrupted":
                new_val = max(0.1, current - 0.1)  # 被打断说明太烦人
            elif reaction == "asked_for_repeat":
                new_val = min(0.9, current + 0.1)  # 要求重复说明重要
            else:
                new_val = current

            self._history[event_key]["learned_importance"] = new_val

    def get_learned_importance(self, event_key: str) -> float:
        """获取学习到的重要性"""
        with self._lock:
            if event_key in self._history:
                return self._history[event_key]["learned_importance"]
            return 0.5  # 默认值


# ========================================
# 增强版智能播报器
# ========================================
class EnhancedSmartAnnouncer(SmartAnnouncer):
    """
    增强版智能播报器

    在原有 SmartAnnouncer 基础上添加：
    1. ImportanceEngine 评估
    2. 上下文感知
    3. 学习记忆
    4. 错误回退到基础逻辑

    使用方式与原有 SmartAnnouncer 完全兼容
    """

    def __init__(self, level: NotificationLevel = NotificationLevel.NORMAL,
                 user_id: str = "default",
                 enable_enhancement: bool = True):
        """
        初始化增强版播报器

        Args:
            level: 通知级别（继承自基础）
            user_id: 用户ID（用于学习隔离）
            enable_enhancement: 是否启用增强功能
        """
        # 调用父类初始化
        super().__init__(level)

        self.user_id = user_id
        self.enable_enhancement = enable_enhancement

        # 学习记忆
        self._learning_memory = AnnouncementLearningMemory()

        # 统计
        self._stats = {
            "total_calls": 0,
            "enhanced_calls": 0,
            "fallback_calls": 0,
            "base_only_calls": 0
        }

        _get_logger().info(
            f"[EnhancedSmartAnnouncer] 初始化完成，"
            f"用户: {user_id}, 增强: {enable_enhancement}"
        )

    def should_announce(self, event: AnnounceEvent,
                       context: dict[str, Any] | None = None) -> bool:
        """
        判断是否应当播报（增强版）

        Args:
            event: 播报事件
            context: 上下文信息（可选）

        Returns:
            bool: 是否应当播报
        """
        self._stats["total_calls"] += 1

        # 第1步：基础层判断（原有逻辑）
        try:
            base_decision = super().should_announce(event)
        except Exception as e:
            _get_logger().error(
                f"[SILENT_FAILURE_BLOCKED] 基础层判断失败: {e}",
                exc_info=True
            )
            base_decision = True  # 失败时保守处理

        # 如果未启用增强，直接返回基础判断
        if not self.enable_enhancement:
            self._stats["base_only_calls"] += 1
            return base_decision

        # 第2步：增强层判断
        try:
            enhanced_result = self._enhanced_decision(event, context, base_decision)

            if enhanced_result.used_enhancement:
                self._stats["enhanced_calls"] += 1
                _get_logger().debug(
                    f"[EnhancedSmartAnnouncer] 增强决策: "
                    f"基础={base_decision}, 增强={enhanced_result.should_announce}, "
                    f"原因={enhanced_result.reason}"
                )
                return enhanced_result.should_announce
            else:
                # 增强层无法判断，使用基础
                self._stats["base_only_calls"] += 1
                return base_decision

        except Exception as e:
            # 增强层失败，记录并回退到基础
            self._stats["fallback_calls"] += 1
            _get_logger().warning(
                f"[SILENT_FAILURE_BLOCKED] 增强层失败，回退到基础: {e}",
                exc_info=True
            )
            return base_decision

    def _enhanced_decision(self, event: AnnounceEvent,
                          context: dict[str, Any] | None,
                          base_decision: bool) -> EnhancedDecision:
        """
        增强决策逻辑

        策略：
        1. 如果基础层说"是"，检查是否过度播报
        2. 如果基础层说"否"，检查是否漏掉重要信息
        """
        event_key = self._create_event_key(event)

        # 记录事件到学习记忆
        if context:
            self._learning_memory.record_event(event_key, context)

        # 获取学习到的重要性
        learned_importance = self._learning_memory.get_learned_importance(event_key)

        # 尝试使用 ImportanceEngine
        importance_score = self._calculate_importance(event, context)

        # 综合决策
        if base_decision:
            # 基础层说播报，但学习显示AI经常忽略
            if learned_importance < 0.3:
                return EnhancedDecision(
                    should_announce=False,
                    base_decision=True,
                    enhanced_decision=False,
                    reason=f"基础层同意但学习显示重要性低 ({learned_importance:.2f})",
                    importance_score=importance_score,
                    used_enhancement=True
                )

            # ImportanceEngine 认为不重要
            if importance_score < 0.2:
                return EnhancedDecision(
                    should_announce=False,
                    base_decision=True,
                    enhanced_decision=False,
                    reason=f"ImportanceEngine 评分过低 ({importance_score:.2f})",
                    importance_score=importance_score,
                    used_enhancement=True
                )
        else:
            # 基础层说不播报，但学习显示AI经常关注
            if learned_importance > 0.7:
                return EnhancedDecision(
                    should_announce=True,
                    base_decision=False,
                    enhanced_decision=True,
                    reason=f"基础层忽略但学习显示重要性高 ({learned_importance:.2f})",
                    importance_score=importance_score,
                    used_enhancement=True
                )

            # ImportanceEngine 认为很重要
            if importance_score > 0.8:
                return EnhancedDecision(
                    should_announce=True,
                    base_decision=False,
                    enhanced_decision=True,
                    reason=f"ImportanceEngine 评分很高 ({importance_score:.2f})",
                    importance_score=importance_score,
                    used_enhancement=True
                )

        # 无显著差异，使用基础决策
        return EnhancedDecision(
            should_announce=base_decision,
            base_decision=base_decision,
            enhanced_decision=base_decision,
            reason="增强层无显著差异，使用基础决策",
            importance_score=importance_score,
            used_enhancement=False
        )

    def _calculate_importance(self, event: AnnounceEvent,
                             context: dict[str, Any] | None) -> float:
        """
        计算事件重要性

        使用 ImportanceEngine 如果可用
        """
        importance_engine = _get_importance_engine()

        if importance_engine is None:
            return 0.5  # 默认中值

        try:
            # 构建评估输入
            assessment_input = {
                "event_type": event.event_type.value,
                "message": event.message,
                "data": event.data,
                "context": context or {}
            }

            # 调用 ImportanceEngine
            score = importance_engine.assess_importance(assessment_input)
            return score

        except Exception as e:
            _get_logger().debug(f"ImportanceEngine 评估失败: {e}")
            return 0.5

    def _create_event_key(self, event: AnnounceEvent) -> str:
        """创建事件签名（用于学习）"""
        tool_name = event.data.get('tool_name', '') if event.data else ''
        return f"{event.event_type.value}_{tool_name}"

    def report_ai_reaction(self, event: AnnounceEvent, reaction: str):
        """
        报告AI对播报的反应（用于学习）

        Args:
            event: 播报的事件
            reaction: AI反应类型
                - "acknowledged": AI确认/回应
                - "ignored": AI忽略
                - "interrupted": AI打断/跳过
                - "asked_for_repeat": AI要求重复
        """
        event_key = self._create_event_key(event)
        self._learning_memory.record_ai_reaction(event_key, reaction)

        _get_logger().debug(
            f"[EnhancedSmartAnnouncer] 记录AI反应: {event_key} -> {reaction}"
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "enhancement_rate": (
                self._stats["enhanced_calls"] / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            ),
            "fallback_rate": (
                self._stats["fallback_calls"] / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            )
        }

    def get_learning_stats(self) -> dict[str, Any]:
        """获取学习统计"""
        return {
            "learned_patterns": len(self._learning_memory._history),
            "sample_patterns": list(self._learning_memory._history.keys())[:5]
        }


# ========================================
# 便捷函数
# ========================================
def create_enhanced_announcer(
    level: NotificationLevel = NotificationLevel.NORMAL,
    user_id: str = "default",
    enable_enhancement: bool = True
) -> EnhancedSmartAnnouncer:
    """
    创建增强版播报器

    Args:
        level: 通知级别
        user_id: 用户ID
        enable_enhancement: 是否启用增强

    Returns:
        EnhancedSmartAnnouncer: 增强版播报器
    """
    return EnhancedSmartAnnouncer(
        level=level,
        user_id=user_id,
        enable_enhancement=enable_enhancement
    )


# ========================================
# 模块导出
# ========================================
__all__ = [
    'EnhancedSmartAnnouncer',
    'EnhancedDecision',
    'AnnouncementLearningMemory',
    'create_enhanced_announcer',
]
