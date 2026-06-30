#!/usr/bin/env python3
"""
ExperienceEngine - 统一的经验引擎（Week 4 功能整合）

整合经验注入(ExperienceInjector)和反思系统(Reflector)，
提供统一的经验提取、整合和应用接口，遵循零静默失败原则。

核心功能：
1. 经验提取与整合（反思 + 经验注入）
2. 经验去重与质量评估
3. 策略模式提取和应用
4. 经验效果追踪闭环
"""

import time
from dataclasses import dataclass, field
from typing import Any

from core.exceptions import ExperienceRecordError
from core.logger import logger


@dataclass
class ExtractedExperience:
    """提取的经验条目"""
    exp_id: str
    content: str
    source: str                    # 来源: "reflection" | "injection" | "merged"
    relevance_score: float = 0.0   # 相关性评分 0-1
    quality_score: float = 0.0     # 质量评分 0-1
    timestamp: float = 0.0         # 时间戳
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exp_id": self.exp_id,
            "content": self.content,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "quality_score": self.quality_score,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class ExperienceMergeResult:
    """经验整合结果"""
    experiences: list[ExtractedExperience] = field(default_factory=list)
    duplicates_removed: int = 0
    from_reflection: int = 0
    from_injection: int = 0
    merged_count: int = 0
    total_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiences": [e.to_dict() for e in self.experiences],
            "duplicates_removed": self.duplicates_removed,
            "from_reflection": self.from_reflection,
            "from_injection": self.from_injection,
            "merged_count": self.merged_count,
            "total_score": self.total_score,
            "count": len(self.experiences)
        }


@dataclass
class StrategyAdvice:
    """策略建议"""
    pattern_id: str
    name: str
    description: str
    steps: list[str]
    applicable_scenarios: list[str]
    confidence: float = 0.0
    success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "steps": self.steps,
            "applicable_scenarios": self.applicable_scenarios,
            "confidence": self.confidence,
            "success_rate": self.success_rate
        }


class ExperienceEngine:
    """
    统一的经验引擎（整合经验注入和反思结果）

    设计原则：
    1. 延迟导入避免循环依赖
    2. 零静默失败 - 任何提取失败都抛出明确异常
    3. 去重整合 - 合并反思和经验注入的结果，去除重复
    4. 质量优先 - 基于多维度评分排序

    使用示例：
        engine = ExperienceEngine()

        # 提取整合经验
        result = engine.extract_experience(execution_history)

        # 获取策略建议
        advice = engine.get_strategy_advice(task_description, current_steps)

        # 追踪经验效果
        engine.track_outcome(exp_ids, task_success=True)
    """

    def __init__(self, user_id: str = "default"):
        """
        初始化经验引擎

        Args:
            user_id: 用户ID，用于个性化经验提取
        """
        self.user_id = user_id
        self._reflector = None
        self._experience_injector = None
        self._initialized = False

        # 去重配置
        self.similarity_threshold = 0.85  # 相似度阈值，超过认为是重复
        self.max_experiences = 10         # 最大返回经验数

        logger.info(f"[ExperienceEngine] 初始化完成，用户: {user_id}")

    def _lazy_init(self):
        """延迟初始化"""
        if self._initialized:
            return

        try:
            from core.evolution.experience_injector import get_experience_injector_v3
            from core.reflector import Reflector

            self._reflector = Reflector()
            self._experience_injector = get_experience_injector_v3()
            self._initialized = True

            logger.debug("[ExperienceEngine] 延迟初始化完成")
        except Exception as e:
            logger.error(f"[ExperienceEngine] 初始化失败: {e}")
            raise ExperienceRecordError(f"经验引擎初始化失败: {e}") from e

    async def extract_experience(self, execution_history: list[dict[str, Any]],
                          task_description: str = "") -> ExperienceMergeResult:
        """
        提取经验（去重整合）

        整合反思分析和经验检索的结果，进行去重和质量排序。

        Args:
            execution_history: 执行历史记录列表
            task_description: 任务描述，用于相关性匹配

        Returns:
            ExperienceMergeResult: 整合后的经验结果

        Raises:
            ExperienceRecordError: 提取失败时抛出
        """
        self._lazy_init()

        result = ExperienceMergeResult()

        try:
            # ===== 1. 反思分析 =====
            reflection_experiences = self._extract_from_reflection(execution_history, task_description)
            result.from_reflection = len(reflection_experiences)

            # ===== 2. 经验检索 =====
            injection_experiences = await self._extract_from_injection(task_description)
            result.from_injection = len(injection_experiences)

            # ===== 3. 合并去重 =====
            merged = self._merge_experiences(reflection_experiences, injection_experiences)
            result.merged_count = len(merged)

            # ===== 4. 排序和截断 =====
            sorted_experiences = self._sort_by_quality(merged)
            result.experiences = sorted_experiences[:self.max_experiences]

            # ===== 5. 计算统计 =====
            result.duplicates_removed = (len(reflection_experiences) + len(injection_experiences)) - len(merged)
            result.total_score = sum(e.quality_score for e in result.experiences)

            logger.info(f"[ExperienceEngine] 经验提取完成: "
                       f"反思{result.from_reflection}条 + "
                       f"注入{result.from_injection}条 - "
                       f"去重{result.duplicates_removed}条 = "
                       f"最终{len(result.experiences)}条")

            return result

        except Exception as e:
            logger.error(f"[ExperienceEngine] 经验提取失败: {e}")
            raise ExperienceRecordError(f"经验提取失败: {e}") from e

    def _extract_from_reflection(self, execution_history: list[dict[str, Any]],
                                 task_description: str) -> list[ExtractedExperience]:
        """从反思系统提取经验"""
        experiences = []

        try:
            # 获取策略模式
            advice = self._reflector.get_strategy_advice(task_description, execution_history)

            if advice and advice.get("applicable_patterns"):
                for pattern_data in advice["applicable_patterns"]:
                    exp = ExtractedExperience(
                        exp_id=pattern_data.get("pattern_id", f"refl_{int(time.time())}"),
                        content=self._format_pattern_as_experience(pattern_data),
                        source="reflection",
                        relevance_score=pattern_data.get("success_rate", 0.5),
                        quality_score=pattern_data.get("success_rate", 0.5) * 0.8 + 0.2,
                        timestamp=time.time(),
                        metadata={
                            "pattern_id": pattern_data.get("pattern_id"),
                            "usage_count": pattern_data.get("usage_count", 0),
                            "type": "strategy_pattern"
                        }
                    )
                    experiences.append(exp)

            # 获取反思历史中的洞察
            if hasattr(self._reflector, 'reflection_history'):
                for reflection in self._reflector.reflection_history[-5:]:  # 最近5条
                    if reflection.confidence > 0.6:  # 只取高置信度的
                        exp = ExtractedExperience(
                            exp_id=f"insight_{reflection.timestamp}",
                            content=f"洞察: {reflection.insight} | 建议: {reflection.suggestion}",
                            source="reflection",
                            relevance_score=reflection.confidence,
                            quality_score=reflection.confidence * 0.7 + 0.3,
                            timestamp=reflection.timestamp,
                            metadata={
                                "level": reflection.level.value if hasattr(reflection.level, 'value') else str(reflection.level),
                                "trigger": reflection.trigger.value if hasattr(reflection.trigger, 'value') else str(reflection.trigger),
                                "type": "reflection_insight"
                            }
                        )
                        experiences.append(exp)

        except Exception as e:
            logger.warning(f"[ExperienceEngine] 反思经验提取异常: {e}")
            # 反思失败不阻断，继续处理

        return experiences

    async def _extract_from_injection(self, task_description: str) -> list[ExtractedExperience]:
        """从经验注入系统提取经验"""
        experiences = []

        try:
            # 使用V3注入器的检索功能
            raw_experiences = await self._experience_injector.search_experiences(
                task=task_description,
                user_id=self.user_id,
                limit=15
            )

            for exp_data in raw_experiences:
                exp_id = exp_data.get('id', f"inj_{hash(str(exp_data))}")
                content = exp_data.get('document', '') or exp_data.get('content', '')
                metadata = exp_data.get('metadata', {})

                # 计算质量分（兼容 str/float/None/其他类型）
                raw_quality = metadata.get('quality_score', 0.5)
                try:
                    quality = float(raw_quality)
                except (TypeError, ValueError):
                    quality = 0.5

                # 获取效果分
                effectiveness = 0.5
                if hasattr(self._experience_injector, 'effectiveness_tracker'):
                    effectiveness = self._experience_injector.effectiveness_tracker.get_exp_effectiveness_score(exp_id)

                exp = ExtractedExperience(
                    exp_id=exp_id,
                    content=content,
                    source="injection",
                    relevance_score=exp_data.get('similarity', 0.5),
                    quality_score=quality * 0.6 + effectiveness * 0.4,
                    timestamp=metadata.get('timestamp', time.time()),
                    metadata={
                        **metadata,
                        "type": "injected_experience"
                    }
                )
                experiences.append(exp)

        except (AttributeError, TypeError, RuntimeError) as e:
            logger.warning(f"[ExperienceEngine] 经验注入提取异常: {e}")
            # 注入失败不阻断

        return experiences

    def _merge_experiences(self, reflection_experiences: list[ExtractedExperience],
                          injection_experiences: list[ExtractedExperience]) -> list[ExtractedExperience]:
        """
        合并经验，去除重复

        使用内容相似度检测重复经验，保留质量较高的版本。
        """
        merged = []
        all_experiences = reflection_experiences + injection_experiences

        # 按内容相似度去重
        for exp in all_experiences:
            is_duplicate = False

            for existing in merged:
                similarity = self._calculate_similarity(exp.content, existing.content)
                if similarity > self.similarity_threshold:
                    # 发现重复，保留质量较高的
                    is_duplicate = True
                    if exp.quality_score > existing.quality_score:
                        # 替换为更高质量的
                        existing.content = exp.content
                        existing.quality_score = exp.quality_score
                        existing.source = "merged"
                        existing.metadata["merged_from"] = [existing.source, exp.source]
                    break

            if not is_duplicate:
                merged.append(exp)

        return merged

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度（Jaccard系数）"""
        if not text1 or not text2:
            return 0.0

        # 简单分词
        words1 = set(self._tokenize(text1.lower()))
        words2 = set(self._tokenize(text2.lower()))

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词"""
        import re
        # 提取中文字符和英文单词
        chinese = re.findall(r'[\u4e00-\u9fff]', text)
        english = re.findall(r'[a-zA-Z_]+', text)
        return chinese + [w.lower() for w in english]

    @staticmethod
    def _sort_by_quality(experiences: list[ExtractedExperience]) -> list[ExtractedExperience]:
        """按质量分数排序"""
        return sorted(experiences, key=lambda e: e.quality_score, reverse=True)

    @staticmethod
    def _format_pattern_as_experience(pattern_data: dict[str, Any]) -> str:
        """将策略模式格式化为经验文本"""
        lines = [
            f"【策略模式: {pattern_data.get('name', '未知')}】",
            f"描述: {pattern_data.get('description', '')}",
            f"适用场景: {', '.join(pattern_data.get('applicable_scenarios', []))}",
            "执行步骤:"
        ]
        for i, step in enumerate(pattern_data.get('strategy_steps', []), 1):
            lines.append(f"  {i}. {step}")
        return "\n".join(lines)

    def get_strategy_advice(self, task: str, current_steps: list[dict[str, Any]]) -> StrategyAdvice | None:
        """
        获取策略建议

        Args:
            task: 任务描述
            current_steps: 当前已执行步骤

        Returns:
            StrategyAdvice: 策略建议，无可用建议时返回None
        """
        self._lazy_init()

        try:
            advice = self._reflector.get_strategy_advice(task, current_steps)

            if advice and advice.get("applicable_patterns"):
                pattern = advice["applicable_patterns"][0]  # 取最佳匹配
                return StrategyAdvice(
                    pattern_id=pattern.get("pattern_id", ""),
                    name=pattern.get("name", ""),
                    description=pattern.get("description", ""),
                    steps=pattern.get("strategy_steps", []),
                    applicable_scenarios=pattern.get("applicable_scenarios", []),
                    confidence=pattern.get("success_rate", 0.5),
                    success_rate=pattern.get("success_rate", 0.0)
                )

            return None

        except Exception as e:
            logger.error(f"[ExperienceEngine] 获取策略建议失败: {e}")
            return None

    def track_outcome(self, exp_ids: list[str], task_success: bool,
                     feedback_score: float | None = None):
        """
        追踪经验使用效果

        Args:
            exp_ids: 经验ID列表
            task_success: 任务是否成功
            feedback_score: 用户反馈评分 0-10
        """
        self._lazy_init()

        try:
            if hasattr(self._experience_injector, 'effectiveness_tracker'):
                for exp_id in exp_ids:
                    task_hash = self._experience_injector.effectiveness_tracker.track_usage(
                        exp_id, f"tracked_task_{int(time.time())}"
                    )
                    self._experience_injector.effectiveness_tracker.track_outcome(
                        task_hash, task_success, feedback_score
                    )

                logger.info(f"[ExperienceEngine] 追踪 {len(exp_ids)} 条经验效果: success={task_success}")
        except Exception as e:
            logger.error(f"[ExperienceEngine] 追踪经验效果失败: {e}")
            # 追踪失败不阻断主流程

    @staticmethod
    def format_experiences_for_prompt(merge_result: ExperienceMergeResult) -> str:
        """
        将经验整合结果格式化为提示词

        Args:
            merge_result: 经验整合结果

        Returns:
            格式化的提示词文本
        """
        if not merge_result.experiences:
            return "【经验参考】暂无相关历史经验，请基于最佳实践自主决策。"

        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║                    【历史经验参考】                           ║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"共整合 {len(merge_result.experiences)} 条经验 "
            f"(来源: 反思{merge_result.from_reflection}条 + 注入{merge_result.from_injection}条, "
            f"去重{merge_result.duplicates_removed}条)",
            ""
        ]

        # 分类展示
        strategy_patterns = [e for e in merge_result.experiences if e.metadata.get("type") == "strategy_pattern"]
        reflections = [e for e in merge_result.experiences if e.metadata.get("type") == "reflection_insight"]
        injected = [e for e in merge_result.experiences if e.metadata.get("type") == "injected_experience"]

        if strategy_patterns:
            lines.append("┌─────────────────────────────────────────────────────────────┐")
            lines.append("│ 【策略模式 - 推荐参考】                                       │")
            lines.append("└─────────────────────────────────────────────────────────────┘")
            for i, exp in enumerate(strategy_patterns, 1):
                lines.append(f"\n[策略{i}] 质量分: {exp.quality_score:.0%}")
                lines.append(exp.content[:300] + ("..." if len(exp.content) > 300 else ""))

        if reflections:
            lines.append("\n┌─────────────────────────────────────────────────────────────┐")
            lines.append("│ 【反思洞察 - 注意事项】                                       │")
            lines.append("└─────────────────────────────────────────────────────────────┘")
            for i, exp in enumerate(reflections, 1):
                lines.append(f"{i}. {exp.content[:150]}{'...' if len(exp.content) > 150 else ''}")

        if injected:
            lines.append("\n┌─────────────────────────────────────────────────────────────┐")
            lines.append("│ 【历史经验 - 成功案例】                                       │")
            lines.append("└─────────────────────────────────────────────────────────────┘")
            for i, exp in enumerate(injected[:3], 1):  # 最多显示3条
                lines.append(f"\n[经验{i}] 相关度: {exp.relevance_score:.0%}")
                lines.append(exp.content[:200] + ("..." if len(exp.content) > 200 else ""))

        lines.extend([
            "",
            "┌─────────────────────────────────────────────────────────────┐",
            "│ 【行动指导】                                                  │",
            "└─────────────────────────────────────────────────────────────┘",
            "1. 优先参考策略模式中的推荐步骤",
            "2. 注意反思洞察中提到的坑点",
            "3. 结合历史经验调整执行策略",
            "4. 如都不适用，可创新解决方案"
        ])

        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """获取经验引擎统计信息"""
        self._lazy_init()

        try:
            injector_stats = {}
            if hasattr(self._experience_injector, 'get_injection_stats'):
                injector_stats = self._experience_injector.get_injection_stats()

            reflector_stats = {}
            if hasattr(self._reflector, 'strategy_patterns'):
                reflector_stats = {
                    "strategy_patterns_count": len(self._reflector.strategy_patterns),
                    "reflection_history_count": len(getattr(self._reflector, 'reflection_history', []))
                }

            return {
                "user_id": self.user_id,
                "initialized": self._initialized,
                "injector": injector_stats,
                "reflector": reflector_stats,
                "similarity_threshold": self.similarity_threshold,
                "max_experiences": self.max_experiences
            }
        except Exception as e:
            logger.error(f"[ExperienceEngine] 获取统计信息失败: {e}")
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 全局实例和便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

_experience_engine_instance: ExperienceEngine | None = None


def get_experience_engine(user_id: str = "default") -> ExperienceEngine:
    """获取经验引擎全局实例"""
    global _experience_engine_instance
    if _experience_engine_instance is None:
        _experience_engine_instance = ExperienceEngine(user_id=user_id)
    return _experience_engine_instance


async def extract_and_format_experiences(execution_history: list[dict[str, Any]],
                                   task_description: str = "",
                                   user_id: str = "default") -> str:
    """
    便捷函数：提取并格式化经验

    Args:
        execution_history: 执行历史
        task_description: 任务描述
        user_id: 用户ID

    Returns:
        格式化的经验提示词
    """
    engine = get_experience_engine(user_id)
    result = await engine.extract_experience(execution_history, task_description)
    return engine.format_experiences_for_prompt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# ExperienceEngine是Week 4功能整合的核心组件之一，统一整合反思系统和经验注入器，
# 为系统提供统一的经验提取、整合和应用接口。
#
# 【核心功能】
# 1. 双重来源提取：从反思系统和经验注入器同时提取经验
# 2. 智能去重：基于内容相似度合并重复经验
# 3. 质量排序：多维度评分确保高质量经验优先
# 4. 策略建议：从策略模式中提取可复用建议
# 5. 效果追踪：闭环追踪经验使用效果
#
# 【设计特点】
# 1. 延迟初始化：避免循环依赖
# 2. 容错处理：单一路径失败不阻断整体流程
# 3. 完整结果：ExperienceMergeResult包含详细统计
# 4. 提示词友好：提供format_experiences_for_prompt()方法
#
# 【使用场景】
# 1. AgentLoop执行前调用extract_experience()获取参考
# 2. 提示词构建时调用format_experiences_for_prompt()
# 3. 任务完成后调用track_outcome()反馈效果
# 4. 策略决策时调用get_strategy_advice()
#
# ═══════════════════════════════════════════════════════════════════════════════
