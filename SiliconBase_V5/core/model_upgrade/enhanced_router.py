#!/usr/bin/env python3
"""
增强型模型路由器 - Enhanced Model Router

实现智能任务路由，根据任务类型、复杂度、成本和质量要求选择最优模型。

特性：
1. 多维度模型评估（质量/成本/速度/可靠性）
2. 任务复杂度自动评估
3. 模型能力匹配
4. 动态优先级调整
5. 支持多个云提供商（OpenAI/Anthropic/DeepSeek等）
"""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from core.ai.model_profile import MODEL_PROFILES, ModelProfile, TaskType, list_profiles
from core.logger import logger


class ModelCapability(Enum):
    """模型能力级别"""
    BASIC = "basic"           # 基础能力：简单对话
    STANDARD = "standard"     # 标准能力：一般任务
    ADVANCED = "advanced"     # 高级能力：复杂推理
    EXPERT = "expert"         # 专家能力：专业领域
    VISION = "vision"         # 视觉能力：图像理解
    MULTIMODAL = "multimodal" # 多模态：文本+图像+音频


class RoutingStrategy(Enum):
    """路由策略"""
    # 成本优先
    COST_FIRST = "cost_first"
    # 质量优先
    QUALITY_FIRST = "quality_first"
    # 速度优先
    SPEED_FIRST = "speed_first"
    # 平衡策略
    BALANCED = "balanced"
    # 智能自适应
    ADAPTIVE = "adaptive"


@dataclass
class TaskRequirements:
    """任务需求描述"""
    task_type: TaskType
    complexity: ModelCapability
    require_vision: bool = False
    require_tools: bool = False
    require_json: bool = False
    require_streaming: bool = True
    context_length: int = 4096
    preferred_language: str = "zh"
    max_budget: float = 0.1  # 最大预算（美元）
    max_latency: int = 5000  # 最大延迟（毫秒）


@dataclass
class RoutingResult:
    """路由结果"""
    provider: str
    model: str
    full_name: str
    strategy: RoutingStrategy
    confidence: float  # 路由置信度 0-1
    estimated_cost: float
    estimated_latency: int
    quality_score: float
    reason: str


@dataclass
class ModelScore:
    """模型评分"""
    provider: str
    model: str
    full_name: str
    total_score: float
    quality_score: float
    cost_score: float
    speed_score: float
    reliability_score: float
    capability_match: float


class EnhancedModelRouter:
    """
    增强型模型路由器

    实现智能模型选择，平衡成本、质量和性能。
    """

    # 模型能力映射
    CAPABILITY_MAP = {
        # OpenAI
        "openai/gpt-4": ModelCapability.EXPERT,
        "openai/gpt-4o": ModelCapability.MULTIMODAL,
        "openai/gpt-4o-mini": ModelCapability.ADVANCED,
        "openai/o1-preview": ModelCapability.EXPERT,
        "openai/o1-mini": ModelCapability.ADVANCED,

        # Anthropic
        "anthropic/claude-3-opus": ModelCapability.EXPERT,
        "anthropic/claude-3-sonnet": ModelCapability.ADVANCED,
        "anthropic/claude-3-haiku": ModelCapability.STANDARD,

        # DeepSeek
        "deepseek/deepseek-chat": ModelCapability.ADVANCED,
        "deepseek/deepseek-reasoner": ModelCapability.EXPERT,

        # 本地Ollama
        "ollama/qwen3:8b": ModelCapability.ADVANCED,
        "ollama/llama3.2:3b": ModelCapability.STANDARD,
        "ollama/llama3.2-vision:11b": ModelCapability.VISION,
        "ollama/deepseek-coder:6.7b": ModelCapability.ADVANCED,
        "ollama/phi4:14b": ModelCapability.ADVANCED,
    }

    # 任务复杂度与模型能力匹配
    COMPLEXITY_MATCH = {
        ModelCapability.BASIC: [TaskType.CHAT, TaskType.SUMMARIZE],
        ModelCapability.STANDARD: [TaskType.CHAT, TaskType.SUMMARIZE, TaskType.TRANSLATE],
        ModelCapability.ADVANCED: [TaskType.CHAT, TaskType.CODE, TaskType.ANALYSIS,
                                    TaskType.SUMMARIZE, TaskType.TRANSLATE],
        ModelCapability.EXPERT: [TaskType.CHAT, TaskType.CODE, TaskType.ANALYSIS,
                                  TaskType.PLANNING, TaskType.REASONING, TaskType.CREATIVE],
        ModelCapability.VISION: [TaskType.VISION],
        ModelCapability.MULTIMODAL: [TaskType.CHAT, TaskType.VISION, TaskType.ANALYSIS],
    }

    def __init__(self):
        self.profiles = MODEL_PROFILES
        self.performance_history: dict[str, list[dict]] = {}
        self.routing_stats: dict[str, dict] = {}
        self._strategy_weights = {
            RoutingStrategy.COST_FIRST: {"cost": 0.5, "quality": 0.2, "speed": 0.2, "reliability": 0.1},
            RoutingStrategy.QUALITY_FIRST: {"cost": 0.1, "quality": 0.5, "speed": 0.2, "reliability": 0.2},
            RoutingStrategy.SPEED_FIRST: {"cost": 0.2, "quality": 0.2, "speed": 0.5, "reliability": 0.1},
            RoutingStrategy.BALANCED: {"cost": 0.25, "quality": 0.3, "speed": 0.25, "reliability": 0.2},
            RoutingStrategy.ADAPTIVE: {"cost": 0.25, "quality": 0.3, "speed": 0.25, "reliability": 0.2},
        }

    def route(self,
              task_requirements: TaskRequirements,
              strategy: RoutingStrategy = RoutingStrategy.ADAPTIVE,
              excluded_models: list[str] | None = None) -> RoutingResult:
        """
        路由到最佳模型

        Args:
            task_requirements: 任务需求
            strategy: 路由策略
            excluded_models: 排除的模型列表

        Returns:
            RoutingResult: 路由结果
        """
        start_time = time.time()

        # 1. 筛选候选模型
        candidates = self._filter_candidates(task_requirements, excluded_models or [])

        if not candidates:
            # 无候选模型，fallback到本地
            return self._create_fallback_result(task_requirements)

        # 2. 评分模型
        scores = self._score_models(candidates, task_requirements, strategy)

        # 3. 选择最佳模型
        best = max(scores, key=lambda x: x.total_score)

        # 4. 构建结果
        result = self._build_routing_result(best, task_requirements, strategy)

        # 记录路由统计
        routing_time = (time.time() - start_time) * 1000
        self._record_routing(result, routing_time)

        logger.info(f"[EnhancedRouter] 路由决策: {result.full_name}, "
                   f"策略={strategy.value}, 耗时={routing_time:.2f}ms")

        return result

    def _filter_candidates(self,
                          requirements: TaskRequirements,
                          excluded: list[str]) -> list[ModelProfile]:
        """筛选候选模型"""
        candidates = []

        for profile in list_profiles(active_only=True):
            full_name = profile.full_name

            # 排除列表检查
            if full_name in excluded or profile.name in excluded:
                continue

            caps = profile.capabilities

            # 任务类型支持检查
            if not caps.supports_task(requirements.task_type):
                continue

            # 视觉支持检查
            if requirements.require_vision and not caps.supports_vision:
                continue

            # 工具支持检查
            if requirements.require_tools and not caps.supports_tools:
                continue

            # JSON模式检查
            if requirements.require_json and not caps.supports_json_mode:
                continue

            # 上下文长度检查
            if caps.context_length < requirements.context_length:
                continue

            # 预算检查（预估）
            estimated_cost = caps.estimate_cost(1000, 500)
            if estimated_cost > requirements.max_budget:
                continue

            candidates.append(profile)

        return candidates

    def _score_models(self,
                     candidates: list[ModelProfile],
                     requirements: TaskRequirements,
                     strategy: RoutingStrategy) -> list[ModelScore]:
        """为候选模型评分"""
        scores = []

        # 获取策略权重
        weights = self._strategy_weights.get(strategy, self._strategy_weights[RoutingStrategy.BALANCED])

        # 自适应策略调整权重
        if strategy == RoutingStrategy.ADAPTIVE:
            weights = self._adapt_weights(requirements)

        for profile in candidates:
            caps = profile.capabilities
            full_name = profile.full_name

            # 质量评分 (0-10)
            quality = caps.quality_score

            # 成本评分 (0-10, 越低越贵)
            if caps.cost_per_1k_tokens == 0 and caps.cost_per_1k_input == 0:
                cost = 10.0  # 免费模型满分
            else:
                avg_cost = (caps.cost_per_1k_tokens +
                          caps.cost_per_1k_input + caps.cost_per_1k_output) / 3
                cost = max(0, 10 - avg_cost * 100)

            # 速度评分 (0-10)
            speed = max(0, 10 - caps.avg_latency_ms / 500)

            # 可靠性评分 (0-10)
            reliability = self._get_reliability_score(full_name)

            # 能力匹配评分 (0-10)
            capability_match = self._get_capability_match(profile, requirements)

            # 综合评分
            total = (
                quality * weights["quality"] +
                cost * weights["cost"] +
                speed * weights["speed"] +
                reliability * weights["reliability"]
            ) * (0.8 + 0.2 * capability_match / 10)  # 能力匹配作为乘数

            scores.append(ModelScore(
                provider=profile.provider,
                model=profile.name,
                full_name=full_name,
                total_score=round(total, 2),
                quality_score=round(quality, 2),
                cost_score=round(cost, 2),
                speed_score=round(speed, 2),
                reliability_score=round(reliability, 2),
                capability_match=round(capability_match, 2)
            ))

        return scores

    def _adapt_weights(self, requirements: TaskRequirements) -> dict[str, float]:
        """根据任务需求自适应调整权重"""
        weights = {"cost": 0.25, "quality": 0.3, "speed": 0.25, "reliability": 0.2}

        # 根据任务类型调整
        if requirements.task_type in [TaskType.REASONING, TaskType.PLANNING, TaskType.CODE]:
            weights["quality"] += 0.2
            weights["cost"] -= 0.1
            weights["speed"] -= 0.1

        elif requirements.task_type in [TaskType.CHAT, TaskType.SUMMARIZE]:
            weights["cost"] += 0.15
            weights["quality"] -= 0.05
            weights["speed"] -= 0.1

        elif requirements.task_type == TaskType.VISION:
            weights["quality"] += 0.15
            weights["cost"] -= 0.05

        # 根据预算调整
        if requirements.max_budget < 0.01:  # 预算紧张
            weights["cost"] += 0.2
            weights["quality"] -= 0.1

        # 根据延迟要求调整
        if requirements.max_latency < 2000:  # 要求快速响应
            weights["speed"] += 0.2
            weights["quality"] -= 0.1

        # 归一化
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}

    def _get_reliability_score(self, full_name: str) -> float:
        """获取模型可靠性评分"""
        history = self.performance_history.get(full_name, [])
        if not history:
            return 8.0  # 默认可靠性

        # 计算最近的成功率
        recent = history[-20:]  # 最近20次
        successes = sum(1 for h in recent if h.get("success", True))
        success_rate = successes / len(recent) if recent else 1.0

        return 5.0 + success_rate * 5.0  # 5-10分

    def _get_capability_match(self, profile: ModelProfile, requirements: TaskRequirements) -> float:
        """计算能力匹配度"""
        full_name = profile.full_name
        model_capability = self.CAPABILITY_MAP.get(full_name, ModelCapability.STANDARD)

        # 获取任务复杂度要求的能力
        required_capability = requirements.complexity

        # 能力级别数值
        capability_levels = {
            ModelCapability.BASIC: 1,
            ModelCapability.STANDARD: 2,
            ModelCapability.ADVANCED: 3,
            ModelCapability.VISION: 3,
            ModelCapability.EXPERT: 4,
            ModelCapability.MULTIMODAL: 4,
        }

        model_level = capability_levels.get(model_capability, 2)
        required_level = capability_levels.get(required_capability, 2)

        # 计算匹配度
        if model_level >= required_level:
            # 能力足够，给满分或略高
            return 10.0
        else:
            # 能力不足，按比例扣分
            return (model_level / required_level) * 10

    def _build_routing_result(self,
                             score: ModelScore,
                             requirements: TaskRequirements,
                             strategy: RoutingStrategy) -> RoutingResult:
        """构建路由结果"""
        profile = self.profiles.get(score.full_name)
        caps = profile.capabilities if profile else None

        if caps:
            estimated_cost = caps.estimate_cost(1000, 500)
            estimated_latency = caps.avg_latency_ms
            quality_score = caps.quality_score
        else:
            estimated_cost = 0.01
            estimated_latency = 1000
            quality_score = 7.0

        return RoutingResult(
            provider=score.provider,
            model=score.model,
            full_name=score.full_name,
            strategy=strategy,
            confidence=score.total_score / 10,
            estimated_cost=estimated_cost,
            estimated_latency=estimated_latency,
            quality_score=quality_score,
            reason=f"综合评分={score.total_score}, 质量={score.quality_score}, "
                   f"成本={score.cost_score}, 速度={score.speed_score}"
        )

    def _create_fallback_result(self, requirements: TaskRequirements) -> RoutingResult:
        """创建降级结果"""
        return RoutingResult(
            provider="ollama",
            model="qwen3:8b",
            full_name="ollama/qwen3:8b",
            strategy=RoutingStrategy.ADAPTIVE,
            confidence=0.5,
            estimated_cost=0.0,
            estimated_latency=800,
            quality_score=7.5,
            reason="无满足条件的云端模型，降级到本地模型"
        )

    def _record_routing(self, result: RoutingResult, routing_time_ms: float):
        """记录路由决策"""
        key = result.full_name
        if key not in self.routing_stats:
            self.routing_stats[key] = {
                "count": 0,
                "total_routing_time_ms": 0,
                "last_used": None
            }

        self.routing_stats[key]["count"] += 1
        self.routing_stats[key]["total_routing_time_ms"] += routing_time_ms
        self.routing_stats[key]["last_used"] = datetime.now().isoformat()

    def record_performance(self,
                          full_name: str,
                          success: bool,
                          latency_ms: float,
                          tokens_used: int = 0,
                          error: str | None = None):
        """记录模型性能"""
        if full_name not in self.performance_history:
            self.performance_history[full_name] = []

        self.performance_history[full_name].append({
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "error": error
        })

        # 限制历史记录大小
        if len(self.performance_history[full_name]) > 100:
            self.performance_history[full_name] = self.performance_history[full_name][-100:]

    def get_routing_stats(self) -> dict[str, Any]:
        """获取路由统计"""
        return {
            "routing_stats": self.routing_stats,
            "performance_summary": {
                model: {
                    "total_calls": len(history),
                    "success_rate": sum(1 for h in history if h["success"]) / len(history) if history else 1.0,
                    "avg_latency": sum(h["latency_ms"] for h in history) / len(history) if history else 0
                }
                for model, history in self.performance_history.items()
            }
        }

    def evaluate_task_complexity(self, message: str, context: list[dict] | None = None) -> ModelCapability:
        """
        评估任务复杂度

        Args:
            message: 用户消息
            context: 对话上下文

        Returns:
            ModelCapability: 所需模型能力级别
        """
        text = message.lower()
        total_len = len(message) + sum(len(m.get("content", "")) for m in (context or []))

        # 视觉任务
        vision_keywords = ["图片", "图像", "看图", "照片", "vision", "image", "picture", "photo", "图"]
        if any(kw in text for kw in vision_keywords):
            return ModelCapability.VISION

        # 专家级任务关键词
        expert_keywords = [
            "深度分析", "复杂推理", "数学证明", "算法设计", "架构设计",
            "deep analysis", "complex reasoning", "mathematical proof",
            "algorithm design", "system architecture"
        ]
        if any(kw in text for kw in expert_keywords):
            return ModelCapability.EXPERT

        # 高级任务关键词
        advanced_keywords = [
            "分析", "规划", "计划", "推理", "代码", "编程", "优化",
            "analyze", "plan", "strategy", "reasoning", "code", "program",
            "optimize", "refactor", "debug"
        ]
        has_advanced = any(kw in text for kw in advanced_keywords)

        # 根据长度和关键词判断
        if total_len > 3000 or has_advanced:
            return ModelCapability.ADVANCED
        elif total_len > 1000:
            return ModelCapability.STANDARD
        else:
            return ModelCapability.BASIC
