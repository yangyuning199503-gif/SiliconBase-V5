#!/usr/bin/env python3
"""
ToolFeedback 增强层 - 连接 Reflector 和 RL Engine

设计原则：
1. 不替换原有 ToolFeedbackFilter，而是包装增强
2. 原有逻辑作为 fallback
3. 连接现有高级功能：Reflector, RL Engine
4. 错误保护：增强失败时回退到基础逻辑

增强点：
- 源识别（AI调用 vs 系统调用 vs 视觉事件）
- Reflector 评估重要性
- RL Engine 学习最优过滤策略
- 上下文感知

作者: SiliconBase Team
版本: 1.0.0 (增强层)
"""

# ========================================
# 标准库
# ========================================
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ========================================
# 导入基础层
# ========================================
from core.consciousness.tool_feedback_filter import (
    FeedbackDecision,
    FeedbackLevel,
    ToolFeedbackConfig,
    ToolFeedbackFilter,
)

# ========================================
# 延迟导入高级功能
# ========================================
_reflector = None
_rl_engine = None
_exp_engine = None
_logger = None


def _get_logger():
    global _logger
    if _logger is None:
        try:
            from core.logger import logger
            _logger = logger
        except ImportError:
            import logging
            _logger = logging.getLogger('tool_feedback_enhanced')
    return _logger


def _get_reflector():
    """获取反思系统"""
    global _reflector
    if _reflector is None:
        try:
            from core.reflector.reflector import Reflector
            _reflector = Reflector()
            _get_logger().info("[ToolFeedbackEnhanced] Reflector 已连接")
        except Exception as e:
            _get_logger().warning(f"[ToolFeedbackEnhanced] Reflector 连接失败: {e}")
            _reflector = False
    return _reflector if _reflector is not False else None


def _get_rl_engine():
    """获取强化学习引擎"""
    global _rl_engine
    if _rl_engine is None:
        try:
            from core.evolution.reinforcement_learning_engine import ReinforcementLearningEngine
            _rl_engine = ReinforcementLearningEngine()
            _get_logger().info("[ToolFeedbackEnhanced] RL Engine 已连接")
        except Exception as e:
            _get_logger().warning(f"[ToolFeedbackEnhanced] RL Engine 连接失败: {e}")
            _rl_engine = False
    return _rl_engine if _rl_engine is not False else None


def _get_experience_engine():
    """获取经验引擎"""
    global _exp_engine
    if _exp_engine is None:
        try:
            from core.evolution.experience_engine import ExperienceEngine
            _exp_engine = ExperienceEngine()
            _get_logger().info("[ToolFeedbackEnhanced] ExperienceEngine 已连接")
        except Exception as e:
            _get_logger().warning(f"[ToolFeedbackEnhanced] ExperienceEngine 连接失败: {e}")
            _exp_engine = False
    return _exp_engine if _exp_engine is not False else None


# ========================================
# 增强层类型定义
# ========================================
class EventSource(Enum):
    """事件来源"""
    AI_EXPLICIT = "ai_explicit"      # AI明确调用
    SYSTEM_AUTO = "system_auto"      # 系统自动调用
    VISUAL_DETECT = "visual_detect"  # 视觉检测
    USER_DIRECT = "user_direct"      # 用户直接调用
    UNKNOWN = "unknown"              # 未知


@dataclass
class EnhancedFeedbackDecision:
    """增强版反馈决策"""
    level: FeedbackLevel
    source: EventSource
    reason: str
    content: str | None
    base_decision: FeedbackDecision | None = None
    importance_score: float = 0.5
    confidence: float = 1.0
    used_enhancement: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ========================================
# 学习记忆
# ========================================
class ToolFeedbackLearningMemory:
    """
    工具反馈学习记忆

    记录工具调用历史和AI反应，用于学习过滤策略
    """

    def __init__(self, max_entries: int = 2000):
        self._tool_history: dict[str, dict] = defaultdict(lambda: {
            "count": 0,
            "ai_reactions": [],
            "success_count": 0,
            "failure_count": 0,
            "learned_importance": 0.5
        })
        self._context_patterns: dict[str, float] = {}
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def record_tool_call(self, tool_id: str, context: str, success: bool):
        """记录工具调用"""
        with self._lock:
            key = f"{tool_id}_{context}"
            self._tool_history[key]["count"] += 1
            if success:
                self._tool_history[key]["success_count"] += 1
            else:
                self._tool_history[key]["failure_count"] += 1

    def record_ai_reaction(self, tool_id: str, context: str, reaction: str):
        """
        记录AI反应

        reaction:
        - "used": AI使用了反馈信息
        - "ignored": AI忽略了
        - "asked_for_more": AI要求更多信息（过滤过度）
        - "confused": AI表现出困惑
        """
        with self._lock:
            key = f"{tool_id}_{context}"
            self._tool_history[key]["ai_reactions"].append({
                "reaction": reaction,
                "timestamp": time.time()
            })

            # 基于反应调整重要性
            current = self._tool_history[key]["learned_importance"]

            if reaction == "used":
                new_val = min(0.9, current + 0.05)
            elif reaction == "asked_for_more":
                new_val = min(0.9, current + 0.15)  # 需要更多信息
            elif reaction == "ignored":
                new_val = max(0.1, current - 0.05)
            elif reaction == "confused":
                new_val = min(0.9, current + 0.1)  # 困惑可能由于信息不足
            else:
                new_val = current

            self._tool_history[key]["learned_importance"] = new_val

    def get_learned_importance(self, tool_id: str, context: str) -> float:
        """获取学习到的重要性"""
        with self._lock:
            key = f"{tool_id}_{context}"
            return self._tool_history[key]["learned_importance"]

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        with self._lock:
            return {
                "unique_patterns": len(self._tool_history),
                "total_calls": sum(h["count"] for h in self._tool_history.values()),
                "avg_importance": sum(h["learned_importance"] for h in self._tool_history.values()) / len(self._tool_history) if self._tool_history else 0.5
            }


# ========================================
# 增强版工具反馈过滤器
# ========================================
class EnhancedToolFeedbackFilter(ToolFeedbackFilter):
    """
    增强版工具反馈过滤器

    在原有 ToolFeedbackFilter 基础上添加：
    1. 源识别（AI/系统/视觉/用户）
    2. Reflector 重要性评估
    3. RL Engine 策略学习
    4. 上下文感知过滤

    使用方式与原有 ToolFeedbackFilter 兼容
    """

    def __init__(self, config: ToolFeedbackConfig | None = None,
                 user_id: str = "default",
                 enable_enhancement: bool = True):
        """
        初始化增强版过滤器

        Args:
            config: 配置对象
            user_id: 用户ID
            enable_enhancement: 是否启用增强
        """
        # 父类初始化
        super().__init__(config)

        self.user_id = user_id
        self.enable_enhancement = enable_enhancement

        # 学习记忆
        self._learning_memory = ToolFeedbackLearningMemory()

        # 统计
        self._stats = {
            "total_filtered": 0,
            "enhanced_filtered": 0,
            "fallback_to_base": 0,
            "base_only": 0
        }

        _get_logger().info(
            f"[EnhancedToolFeedbackFilter] 初始化完成，"
            f"用户: {user_id}, 增强: {enable_enhancement}"
        )

    async def filter_feedback(
        self,
        tool_id: str,
        result: dict[str, Any],
        user_id: str = "default",
        execution_context: dict[str, Any] | None = None,
        source: EventSource = EventSource.UNKNOWN
    ) -> EnhancedFeedbackDecision:
        """
        过滤反馈（增强版）

        Args:
            tool_id: 工具ID
            result: 执行结果
            user_id: 用户ID
            execution_context: 执行上下文
            source: 事件来源（新增）

        Returns:
            EnhancedFeedbackDecision: 增强版决策
        """
        self._stats["total_filtered"] += 1

        # 第1步：基础层判断
        try:
            base_decision = super().filter_feedback(
                tool_id, result, user_id, execution_context
            )
        except Exception as e:
            _get_logger().error(
                f"[SILENT_FAILURE_BLOCKED] 基础层过滤失败: {e}",
                exc_info=True
            )
            # 创建默认决策
            base_decision = FeedbackDecision(
                level=FeedbackLevel.INTERACTIVE,
                content=str(result.get("user_message", "")),
                reason="基础层失败，安全回退"
            )

        # 如果未启用增强，返回基础结果
        if not self.enable_enhancement:
            self._stats["base_only"] += 1
            return EnhancedFeedbackDecision(
                level=base_decision.level,
                source=source,
                reason=base_decision.reason,
                content=base_decision.content,
                base_decision=base_decision,
                used_enhancement=False
            )

        # 第2步：增强层判断
        try:
            enhanced = await self._enhanced_decision(
                tool_id, result, execution_context, source, base_decision
            )

            if enhanced.used_enhancement:
                self._stats["enhanced_filtered"] += 1
            else:
                self._stats["base_only"] += 1

            return enhanced

        except Exception as e:
            # 增强层失败，回退到基础
            self._stats["fallback_to_base"] += 1
            _get_logger().warning(
                f"[SILENT_FAILURE_BLOCKED] 增强层失败，回退: {e}",
                exc_info=True
            )

            return EnhancedFeedbackDecision(
                level=base_decision.level,
                source=source,
                reason=f"{base_decision.reason} (增强层失败回退)",
                content=base_decision.content,
                base_decision=base_decision,
                used_enhancement=False
            )

    async def _enhanced_decision(
        self,
        tool_id: str,
        result: dict[str, Any],
        context: dict[str, Any] | None,
        source: EventSource,
        base_decision: FeedbackDecision
    ) -> EnhancedFeedbackDecision:
        """增强决策逻辑"""

        # 提取上下文关键词
        context_key = self._extract_context_key(context)

        # 记录调用
        self._learning_memory.record_tool_call(
            tool_id, context_key, result.get("success", False)
        )

        # 1. 源识别：AI明确调用 → 总是重要
        if source == EventSource.AI_EXPLICIT and base_decision.level in [FeedbackLevel.SILENT]:
            # AI自己调用的工具，应该给予反馈
            return EnhancedFeedbackDecision(
                    level=FeedbackLevel.OBSERVABLE,  # 至少可观测
                    source=source,
                    reason="AI明确调用的工具，从SILENT提升",
                    content=base_decision.content or self._format_summary(tool_id, result),
                    base_decision=base_decision,
                    importance_score=0.8,
                    used_enhancement=True,
                    metadata={"escalation": "ai_explicit"}
                )

        # 2. 源识别：系统自动调用 → 学习决定
        if source == EventSource.SYSTEM_AUTO:
            learned_importance = self._learning_memory.get_learned_importance(
                tool_id, context_key
            )

            # 学习显示AI不关心
            if learned_importance < 0.3 and base_decision.level != FeedbackLevel.SILENT:
                return EnhancedFeedbackDecision(
                    level=FeedbackLevel.SILENT,
                    source=source,
                    reason=f"系统调用，学习显示重要性低 ({learned_importance:.2f})",
                    content=None,
                    base_decision=base_decision,
                    importance_score=learned_importance,
                    used_enhancement=True
                )

            # 学习显示AI关心
            if learned_importance > 0.7 and base_decision.level == FeedbackLevel.SILENT:
                return EnhancedFeedbackDecision(
                    level=FeedbackLevel.OBSERVABLE,
                    source=source,
                    reason=f"系统调用，学习显示重要性高 ({learned_importance:.2f})",
                    content=self._format_summary(tool_id, result),
                    base_decision=base_decision,
                    importance_score=learned_importance,
                    used_enhancement=True
                )

        # 3. 源识别：视觉检测事件 → 学习重要性
        if source == EventSource.VISUAL_DETECT:
            learned_importance = self._learning_memory.get_learned_importance(
                tool_id, context_key
            )

            # 获取视觉结果的特殊信息
            visual_data = result.get("data", {})
            has_critical_detection = visual_data.get("critical", False)
            detection_confidence = visual_data.get("confidence", 0.5)

            # 关键视觉事件总是重要
            if has_critical_detection:
                return EnhancedFeedbackDecision(
                    level=FeedbackLevel.INTERACTIVE,
                    source=source,
                    reason="视觉检测到关键对象/事件",
                    content=base_decision.content or self._format_summary(tool_id, result),
                    base_decision=base_decision,
                    importance_score=0.9,
                    used_enhancement=True,
                    metadata={"visual": {"critical": True, "confidence": detection_confidence}}
                )

            # 高置信度 + 学习显示关心
            if detection_confidence > 0.8 and learned_importance > 0.5:
                return EnhancedFeedbackDecision(
                    level=FeedbackLevel.OBSERVABLE,
                    source=source,
                    reason=f"视觉检测重要 (置信度:{detection_confidence:.2f}, 学习重要性:{learned_importance:.2f})",
                    content=self._format_summary(tool_id, result),
                    base_decision=base_decision,
                    importance_score=(detection_confidence + learned_importance) / 2,
                    used_enhancement=True,
                    metadata={"visual": {"confidence": detection_confidence, "learned": learned_importance}}
                )

            # 学习显示AI不关心视觉事件
            if learned_importance < 0.3:
                return EnhancedFeedbackDecision(
                    level=FeedbackLevel.SILENT,
                    source=source,
                    reason=f"视觉事件，学习显示不重要 ({learned_importance:.2f})",
                    content=None,
                    base_decision=base_decision,
                    importance_score=learned_importance,
                    used_enhancement=True
                )

        # 4. 使用 Reflector 评估（复杂场景）
        if self._should_use_reflector(tool_id, result, context):
            reflector_assessment = await self._assess_with_reflector(
                tool_id, result, context
            )

            if reflector_assessment and reflector_assessment.get("importance", 0.5) > 0.8:
                # Reflector 认为很重要
                return EnhancedFeedbackDecision(
                        level=FeedbackLevel.INTERACTIVE,
                        source=source,
                        reason=f"Reflector评估重要性高 ({reflector_assessment.get('reason', '')})",
                        content=self._format_full(tool_id, result),
                        base_decision=base_decision,
                        importance_score=reflector_assessment.get("importance", 0.8),
                        used_enhancement=True,
                        metadata={"reflector": reflector_assessment}
                    )

        # 4. 使用 ExperienceEngine 获取经验建议（策略指导）
        exp_advice = self._get_experience_advice(tool_id, result, context)
        if exp_advice and exp_advice.get("should_override"):
            # 经验建议覆盖基础决策
            new_level = FeedbackLevel[exp_advice.get("level", "OBSERVABLE")]
            return EnhancedFeedbackDecision(
                level=new_level,
                source=source,
                reason=f"ExperienceEngine建议: {exp_advice.get('reason', '')}",
                content=exp_advice.get("content") or base_decision.content,
                base_decision=base_decision,
                importance_score=exp_advice.get("importance", 0.6),
                used_enhancement=True,
                metadata={"experience": exp_advice}
            )

        # 无显著增强，使用基础决策
        return EnhancedFeedbackDecision(
            level=base_decision.level,
            source=source,
            reason=base_decision.reason,
            content=base_decision.content,
            base_decision=base_decision,
            importance_score=0.5,
            used_enhancement=False
        )

    def _extract_context_key(self, context: dict | None) -> str:
        """提取上下文关键词"""
        if not context:
            return "default"

        task = context.get("current_task", "")[:20]
        goal = context.get("goal", "")[:20]
        return f"{task}_{goal}" if task or goal else "default"

    def _should_use_reflector(self, tool_id: str, result: dict, context: dict | None) -> bool:
        """判断是否使用 Reflector（只在复杂场景）"""
        # 只在以下情况使用 Reflector：
        # 1. 失败且错误码复杂
        # 2. 上下文包含关键决策点

        if not result.get("success", True):
            error_code = result.get("error_code", "")
            if error_code in ["STRATEGY_ERROR", "CONTEXT_ERROR"]:
                return True

        return False

    async def _assess_with_reflector(self, tool_id: str, result: dict, context: dict | None) -> dict | None:
        """
        使用 Reflector 评估工具反馈重要性

        通过 Reflector 的反思能力，评估工具执行结果是否值得反馈给 AI
        """
        reflector = _get_reflector()
        if reflector is None:
            return None

        try:
            # 构建反思上下文
            task = context.get("current_task", "未知任务") if context else "未知任务"
            step_info = {
                "tool_id": tool_id,
                "success": result.get("success", False),
                "error_code": result.get("error_code", ""),
                "user_message": result.get("user_message", ""),
                "data_summary": str(result.get("data", {}))[:200]
            }

            # 调用 Reflector 的单步反思（轻量级）

            reflection = await reflector.reflect_after_step(
                task=task,
                step_info=step_info,
                trajectory=[]
            )

            if reflection:
                # 根据反思结果评估重要性
                importance = 0.5
                reason = reflection.insight

                # 失败情况增加重要性
                if not result.get("success", True):
                    importance = max(importance, 0.7)

                # 高置信度反思增加重要性
                if reflection.confidence > 0.8:
                    importance = max(importance, 0.6)

                # 质量问题增加重要性
                if "error" in reflection.observation.lower() or "失败" in reflection.observation:
                    importance = max(importance, 0.8)

                return {
                    "importance": min(importance, 0.9),
                    "reason": reason,
                    "reflection_level": reflection.level.value,
                    "confidence": reflection.confidence
                }

            return None

        except Exception as e:
            _get_logger().debug(f"Reflector 评估失败: {e}")
            return None

    def _get_experience_advice(
        self,
        tool_id: str,
        result: dict,
        context: dict | None
    ) -> dict | None:
        """
        从 ExperienceEngine 获取经验建议

        咨询经验引擎，获取关于如何处理此工具反馈的策略建议。

        Returns:
            Optional[Dict]: 建议内容，包含 should_override、level、reason 等
        """
        exp_engine = _get_experience_engine()
        if exp_engine is None:
            return None

        try:
            # 构建任务描述
            task = context.get("current_task", "") if context else ""
            if not task:
                return None  # 无任务上下文时不咨询经验

            # 构建当前步骤信息
            current_step = {
                "tool_id": tool_id,
                "success": result.get("success", False),
                "has_data": bool(result.get("data")),
                "error_type": result.get("error_code", "")
            }

            # 获取策略建议
            advice = exp_engine.get_strategy_advice(task, [current_step])

            if not advice or not advice.experiences:
                return None

            # 分析建议，决定是否需要覆盖
            best_exp = advice.experiences[0]

            # 根据经验质量和相关性决定是否覆盖
            if best_exp.quality_score > 0.8 and best_exp.relevance_score > 0.7:
                # 高质量经验建议
                suggestion_text = best_exp.suggestion.lower()

                # 解析建议内容
                should_override = False
                level = "OBSERVABLE"
                reason = best_exp.suggestion

                if "详细" in suggestion_text or "完整" in suggestion_text:
                    level = "INTERACTIVE"
                    should_override = True
                elif "静默" in suggestion_text or "隐藏" in suggestion_text:
                    level = "SILENT"
                    should_override = True
                elif "简要" in suggestion_text or "总结" in suggestion_text:
                    level = "OBSERVABLE"
                    should_override = True

                return {
                    "should_override": should_override,
                    "level": level,
                    "reason": reason,
                    "quality_score": best_exp.quality_score,
                    "relevance_score": best_exp.relevance_score,
                    "experience_id": best_exp.id if hasattr(best_exp, 'id') else None
                }

            return None

        except Exception as e:
            _get_logger().debug(f"ExperienceEngine 咨询失败: {e}")
            return None

    def report_ai_reaction(self, tool_id: str, context: dict | None, reaction: str):
        """
        报告AI对工具反馈的反应

        Args:
            tool_id: 工具ID
            context: 上下文
            reaction: 反应类型
                - "used": AI使用了反馈
                - "ignored": AI忽略了
                - "asked_for_more": AI要求更多信息
                - "confused": AI困惑
        """
        context_key = self._extract_context_key(context)
        self._learning_memory.record_ai_reaction(tool_id, context_key, reaction)

        # 同时记录到 RL Engine
        rl_engine = _get_rl_engine()
        if rl_engine:
            try:
                reward = self._reaction_to_reward(reaction)
                rl_engine.record_action_outcome(
                    action=f"filter_{tool_id}",
                    success=(reaction in ["used", "asked_for_more"]),
                    reward=reward
                )
            except Exception as e:
                _get_logger().debug(f"RL Engine 记录失败: {e}")

    def _reaction_to_reward(self, reaction: str) -> float:
        """反应转奖励"""
        rewards = {
            "used": 1.0,
            "asked_for_more": 0.5,
            "ignored": 0.0,
            "confused": -0.5
        }
        return rewards.get(reaction, 0.0)

    def _format_summary(self, tool_id: str, result: dict) -> str:
        """格式化摘要"""
        success = result.get("success", False)
        msg = result.get("user_message", "")
        icon = "✓" if success else "✗"
        return f"[{icon}] {tool_id}: {msg[:50]}"

    def _format_full(self, tool_id: str, result: dict) -> str:
        """格式化完整反馈"""
        success = result.get("success", False)
        msg = result.get("user_message", "")
        data = result.get("data", {})
        return f"[工具执行] {tool_id}\n状态: {'成功' if success else '失败'}\n消息: {msg}\n数据: {str(data)[:200]}"

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            **self._stats,
            "enhancement_rate": (
                self._stats["enhanced_filtered"] / self._stats["total_filtered"]
                if self._stats["total_filtered"] > 0 else 0
            ),
            "learning_stats": self._learning_memory.get_stats()
        }


# ========================================
# 全局管理器
# ========================================
class EnhancedToolFeedbackManager:
    """管理增强版过滤器的单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self._filters: dict[str, EnhancedToolFeedbackFilter] = {}
        self._lock = threading.RLock()

    def get_filter(self, user_id: str = "default",
                   enable_enhancement: bool = True) -> EnhancedToolFeedbackFilter:
        """获取过滤器"""
        with self._lock:
            if user_id not in self._filters:
                self._filters[user_id] = EnhancedToolFeedbackFilter(
                    user_id=user_id,
                    enable_enhancement=enable_enhancement
                )
            return self._filters[user_id]


# 全局实例
enhanced_tool_feedback_manager = EnhancedToolFeedbackManager()


# ========================================
# 便捷函数
# ========================================
async def filter_with_enhancement(
    tool_id: str,
    result: dict[str, Any],
    source: EventSource,
    context: dict[str, Any] | None = None,
    user_id: str = "default"
) -> EnhancedFeedbackDecision:
    """
    便捷函数：使用增强版过滤

    Args:
        tool_id: 工具ID
        result: 执行结果
        source: 事件来源
        context: 上下文
        user_id: 用户ID

    Returns:
        EnhancedFeedbackDecision: 增强版决策
    """
    filter_instance = enhanced_tool_feedback_manager.get_filter(user_id)
    return await filter_instance.filter_feedback(
        tool_id=tool_id,
        result=result,
        user_id=user_id,
        execution_context=context,
        source=source
    )


def report_reaction(tool_id: str, context: dict | None, reaction: str, user_id: str = "default"):
    """
    全局便捷函数：报告AI对工具反馈的反应

    Args:
        tool_id: 工具ID
        context: 执行上下文
        reaction: 反应类型 ("used", "ignored", "asked_for_more", "confused")
        user_id: 用户ID
    """
    try:
        filter_instance = enhanced_tool_feedback_manager.get_filter(user_id)
        filter_instance.report_ai_reaction(tool_id, context, reaction)
    except Exception as e:
        _get_logger().debug(f"报告反应失败: {e}")


# ========================================
# 模块导出
# ========================================
__all__ = [
    'EventSource',
    'ToolFeedbackLearningMemory',
    'EnhancedFeedbackDecision',
    'EnhancedToolFeedbackFilter',
    'EnhancedToolFeedbackManager',
    'enhanced_tool_feedback_manager',
    'filter_with_enhancement',
    'report_reaction',
]
