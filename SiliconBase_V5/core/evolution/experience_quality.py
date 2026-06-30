#!/usr/bin/env python3
"""
经验质量评估模块 V1.0 - 5维度质量评估系统
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【评估维度】
  1. Effectiveness (有效性)  → 是否成功解决问题
  2. Reusability (可复用性)  → 是否可应用到其他场景
  3. Timeliness (时效性)     → 是否仍然有效（时间衰减）
  4. Relevance (相关性)      → 与当前任务的相关程度
  5. Reliability (可靠性)    → 历史成功率统计

【核心功能】
  ✓ 自动评估经验质量
  ✓ 过滤低质量经验
  ✓ 高质量经验加权
  ✓ 与memory/vector_memory集成

【集成方式】
  - 使用 call_thinker 进行AI辅助评估
  - 使用 memory 存储质量评分
  - 使用 vector_memory 检索相关经验

【2026-02-22 创建】
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.ai.ai_adapter import call_thinker
from core.logger import logger
from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举

# 【P1-迁移】改用 vector_memory_compat（内部桥接 VectorStore）
from core.memory.vector_memory_compat import vector_memory


class QualityDimension(Enum):
    """质量评估维度枚举"""
    EFFECTIVENESS = "effectiveness"
    REUSABILITY = "reusability"
    TIMELINESS = "timeliness"
    RELEVANCE = "relevance"
    RELIABILITY = "reliability"


@dataclass
class QualityScore:
    """
    质量评分数据类

    Attributes:
        effectiveness: 有效性得分 (0-10)
        reusability: 可复用性得分 (0-10)
        timeliness: 时效性得分 (0-10)
        relevance: 相关性得分 (0-10)
        reliability: 可靠性得分 (0-10)
        overall: 综合得分 (0-10)
        details: 评分详情
        assessed_at: 评估时间
    """
    effectiveness: float = 0.0
    reusability: float = 0.0
    timeliness: float = 0.0
    relevance: float = 0.0
    reliability: float = 0.0
    overall: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    assessed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        """确保overall分数是有效的"""
        if self.overall <= 0:
            self._calculate_overall()

    def _calculate_overall(self) -> float:
        """
        计算综合得分（加权平均）

        权重配置：
        - 有效性: 30% (最关键)
        - 可复用性: 20%
        - 时效性: 15%
        - 相关性: 20%
        - 可靠性: 15%
        """
        weights = {
            "effectiveness": 0.30,
            "reusability": 0.20,
            "timeliness": 0.15,
            "relevance": 0.20,
            "reliability": 0.15
        }

        self.overall = (
            self.effectiveness * weights["effectiveness"] +
            self.reusability * weights["reusability"] +
            self.timeliness * weights["timeliness"] +
            self.relevance * weights["relevance"] +
            self.reliability * weights["reliability"]
        )
        return round(self.overall, 2)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityScore":
        """从字典创建"""
        return cls(**data)

    def is_high_quality(self, threshold: float = 7.0) -> bool:
        """是否为高质量经验"""
        return self.overall >= threshold

    def is_low_quality(self, threshold: float = 4.0) -> bool:
        """是否为低质量经验"""
        return self.overall <= threshold


@dataclass
class ExperienceData:
    """
    经验数据结构

    Attributes:
        memory_id: 记忆ID
        task_desc: 任务描述
        steps: 执行步骤
        success: 是否成功
        result: 结果描述
        created_at: 创建时间
        usage_count: 使用次数
        success_count: 成功次数
        context: 额外上下文
    """
    memory_id: str
    task_desc: str
    steps: list[str] = field(default_factory=list)
    success: bool = False
    result: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    usage_count: int = 0
    success_count: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_memory_record(cls, record: dict[str, Any]) -> "ExperienceData":
        """从memory记录创建经验数据"""
        content = record.get("content", {})
        context = record.get("context", {})


        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                content = {"description": content}

        return cls(
            memory_id=record.get("id", ""),
            task_desc=content.get("task_desc", "") or content.get("description", ""),
            steps=content.get("steps", []),
            success=context.get("success", False),
            result=content.get("result", ""),
            created_at=record.get("created_at", datetime.now().isoformat()),
            usage_count=context.get("usage_count", 0),
            success_count=context.get("success_count", 0),
            context=context
        )

    @classmethod
    def from_vector_record(cls, record: dict[str, Any]) -> "ExperienceData":
        """从vector_memory记录创建经验数据"""
        document = record.get("document", "")
        metadata = record.get("metadata", {})


        parsed = cls._parse_document(document)

        return cls(
            memory_id=record.get("id", ""),
            task_desc=parsed.get("task", ""),
            steps=parsed.get("steps", "").split("->") if parsed.get("steps") else [],
            success=metadata.get("success", "false").lower() == "true",
            result=parsed.get("result", ""),
            created_at=metadata.get("timestamp", datetime.now().isoformat()),
            context=metadata
        )

    @staticmethod
    def _parse_document(doc: str) -> dict[str, str]:
        """解析经验文档字符串"""
        result = {"task": "", "steps": "", "result": "", "score": ""}

        try:
            parts = doc.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("[Task]"):
                    result["task"] = part[6:].strip()
                elif part.startswith("[Steps]"):
                    result["steps"] = part[7:].strip()
                elif part.startswith("[Result]"):
                    result["result"] = part[8:].strip()
                elif part.startswith("[Score]"):
                    result["score"] = part[7:].strip()
        except Exception:
            result["task"] = doc[:100]

        return result


class ExperienceQualityAssessor:
    """
    经验质量评估器 - 5维度评估系统

    评估流程：
    1. 提取经验特征
    2. 计算各维度得分
    3. 综合评分
    4. 存储质量记录
    """


    TIME_DECAY = {
        7: 1.0,
        30: 0.9,
        90: 0.7,
        180: 0.5,
        365: 0.3,
    }


    QUALITY_LEVELS = {
        "excellent": 8.5,
        "good": 7.0,
        "fair": 5.0,
        "poor": 3.0,
        "bad": 0.0
    }

    def __init__(self, enable_ai_assessment: bool = True, ai_threshold: float = 0.3):
        """
        初始化质量评估器

        Args:
            enable_ai_assessment: 是否启用AI辅助评估
            ai_threshold: AI评估触发阈值（当规则评估置信度低于此值时使用AI）
        """
        self.enable_ai_assessment = enable_ai_assessment
        self.ai_threshold = ai_threshold
        self._quality_cache: dict[str, QualityScore] = {}
        self._cache_ttl = 300

        logger.info("[ExperienceQualityAssessor] 质量评估器初始化完成")

    async def assess_experience(self, experience_data: dict[str, Any]) -> QualityScore:
        """
        评估单条经验质量

        Args:
            experience_data: 经验数据字典，格式：
                {
                    "memory_id": "xxx",
                    "task_desc": "任务描述",
                    "steps": [...],
                    "success": True/False,
                    "result": "结果描述",
                    "created_at": "ISO时间",
                    "usage_count": 使用次数,
                    "success_count": 成功次数,
                    "context": {...}
                }

        Returns:
            QualityScore: 质量评分对象
        """
        try:

            exp = ExperienceData(**experience_data) if isinstance(experience_data, dict) else experience_data

            memory_id = exp.memory_id


            cached_score = self._get_cached_score(memory_id)
            if cached_score:
                logger.debug(f"[QualityAssessor] 使用缓存评分: {memory_id[:8]}...")
                return cached_score


            effectiveness = self._assess_effectiveness(exp)
            reusability = self._assess_reusability(exp)
            timeliness = self._assess_timeliness(exp)
            relevance = self._assess_relevance(exp)
            reliability = self._assess_reliability(exp)


            score = QualityScore(
                effectiveness=effectiveness,
                reusability=reusability,
                timeliness=timeliness,
                relevance=relevance,
                reliability=reliability,
                details={
                    "memory_id": memory_id,
                    "task_desc": exp.task_desc[:50],
                    "assessment_method": "rule_based"
                }
            )


            score._calculate_overall()


            if self.enable_ai_assessment and self._should_use_ai_assessment(exp, score):
                ai_score = self._ai_assess_experience(exp)
                if ai_score:

                    score = self._blend_scores(score, ai_score)
                    score.details["assessment_method"] = "hybrid"


            self._cache_score(memory_id, score)


            await self._store_quality_record(memory_id, score)

            logger.info(
                f"[QualityAssessor] 评估完成 {memory_id[:8]}... "
                f"得分: {score.overall:.1f} (E:{score.effectiveness:.1f} R:{score.reusability:.1f} "
                f"T:{score.timeliness:.1f} L:{score.relevance:.1f} B:{score.reliability:.1f})"
            )

            return score

        except Exception as e:
            logger.error(f"[QualityAssessor] 评估失败: {e}")

            return QualityScore(
                effectiveness=5.0, reusability=5.0, timeliness=5.0,
                relevance=5.0, reliability=5.0, overall=5.0,
                details={"error": str(e)}
            )

    async def assess_batch(self, experiences: list[dict[str, Any]]) -> list[tuple[dict[str, Any], QualityScore]]:
        """
        批量评估经验质量

        Args:
            experiences: 经验数据列表

        Returns:
            List[Tuple[经验数据, 质量评分]]: 评估结果列表
        """
        results = []

        logger.info(f"[QualityAssessor] 开始批量评估 {len(experiences)} 条经验")

        for i, exp_data in enumerate(experiences, 1):
            try:
                score = await self.assess_experience(exp_data)
                results.append((exp_data, score))

                if i % 10 == 0:
                    logger.info(f"[QualityAssessor] 已评估 {i}/{len(experiences)} 条")

            except Exception as e:
                logger.error(f"[QualityAssessor] 批量评估第{i}条失败: {e}")

                continue


        high_quality = sum(1 for _, s in results if s.is_high_quality())
        low_quality = sum(1 for _, s in results if s.is_low_quality())

        logger.info(
            f"[QualityAssessor] 批量评估完成: "
            f"高质量 {high_quality}, 低质量 {low_quality}, 总计 {len(results)}"
        )

        return results

    async def filter_low_quality(self, experiences: list[dict[str, Any]],
                          threshold: float = 4.0) -> list[dict[str, Any]]:
        """
        过滤低质量经验

        Args:
            experiences: 经验数据列表
            threshold: 质量阈值，低于此值过滤掉

        Returns:
            List[Dict]: 过滤后的高质量经验列表
        """
        filtered = []
        removed_count = 0

        for exp_data in experiences:
            try:
                score = await self.assess_experience(exp_data)

                if score.overall > threshold:

                    exp_data["quality_score"] = score.overall
                    exp_data["quality_level"] = self._get_quality_level(score.overall)
                    filtered.append(exp_data)
                else:
                    removed_count += 1

            except Exception as e:
                logger.warning(f"[QualityAssessor] 过滤评估失败，保留该经验: {e}")
                filtered.append(exp_data)

        logger.info(
            f"[QualityAssessor] 低质量过滤完成: "
            f"保留 {len(filtered)} 条, 移除 {removed_count} 条"
        )

        return filtered

    async def update_experience_rating(self, memory_id: str, new_rating: int) -> bool:
        """
        更新经验评分

        Args:
            memory_id: 记忆ID
            new_rating: 新评分 (0-10)

        Returns:
            bool: 是否成功
        """
        try:

            if memory_id:
                ms = await get_memory_service()
                await ms.rate_memory(memory_id, max(0, min(10, new_rating)))


            if memory_id in self._quality_cache:
                del self._quality_cache[memory_id]


            await self._store_rating_update(memory_id, new_rating)

            logger.info(f"[QualityAssessor] 更新评分成功: {memory_id[:8]}... -> {new_rating}")
            return True

        except Exception as e:
            logger.error(f"[QualityAssessor] 更新评分失败: {e}")
            return False

    async def get_quality_stats(self) -> dict[str, Any]:
        """
        获取质量统计信息

        Returns:
            Dict: 统计数据
        """
        try:
            stats = {
                "total_assessed": 0,
                "quality_distribution": {
                    "excellent": 0,
                    "good": 0,
                    "fair": 0,
                    "poor": 0,
                    "bad": 0
                },
                "dimension_averages": {
                    "effectiveness": 0.0,
                    "reusability": 0.0,
                    "timeliness": 0.0,
                    "relevance": 0.0,
                    "reliability": 0.0
                },
                "average_score": 0.0,
                "high_quality_rate": 0.0
            }


            if self._quality_cache:
                scores = list(self._quality_cache.values())
                stats["total_assessed"] = len(scores)


                for score in scores:
                    level = self._get_quality_level(score.overall)
                    if level in stats["quality_distribution"]:
                        stats["quality_distribution"][level] += 1


                dims = ["effectiveness", "reusability", "timeliness", "relevance", "reliability"]
                for dim in dims:
                    avg = sum(getattr(s, dim) for s in scores) / len(scores)
                    stats["dimension_averages"][dim] = round(avg, 2)


                stats["average_score"] = round(sum(s.overall for s in scores) / len(scores), 2)
                high_count = sum(1 for s in scores if s.is_high_quality())
                stats["high_quality_rate"] = round(high_count / len(scores) * 100, 1)


            try:
                vm_stats = await vector_memory.get_stats()
                stats["total_experiences"] = vm_stats.get("experience_count", 0)
            except Exception:
                stats["total_experiences"] = 0

            return stats

        except Exception as e:
            logger.error(f"[QualityAssessor] 获取统计失败: {e}")
            return {"error": str(e)}

    async def get_weighted_experiences(self, experiences: list[dict[str, Any]],
                                  task_context: str = "") -> list[dict[str, Any]]:
        """
        获取加权后的经验列表（高质量经验排在前面）

        Args:
            experiences: 经验数据列表
            task_context: 当前任务上下文（用于相关性加权）

        Returns:
            List[Dict]: 加权排序后的经验列表
        """
        weighted = []

        for exp_data in experiences:
            try:
                score = await self.assess_experience(exp_data)


                quality_weight = score.overall / 10.0


                relevance_boost = 1.0
                if task_context and exp_data.get("task_desc"):

                    relevance_boost = self._calculate_text_similarity(
                        task_context, exp_data.get("task_desc", "")
                    )

                final_weight = quality_weight * (0.5 + 0.5 * relevance_boost)

                exp_data["quality_score"] = score.overall
                exp_data["quality_weight"] = round(final_weight, 3)
                exp_data["quality_level"] = self._get_quality_level(score.overall)

                weighted.append((exp_data, final_weight))

            except Exception as e:
                logger.warning(f"[QualityAssessor] 加权计算失败: {e}")
                exp_data["quality_score"] = 5.0
                exp_data["quality_weight"] = 0.5
                weighted.append((exp_data, 0.5))


        weighted.sort(key=lambda x: x[1], reverse=True)

        return [exp for exp, _ in weighted]





    def _assess_effectiveness(self, exp: ExperienceData) -> float:
        """
        评估有效性 - 是否成功解决问题

        评估因素：
        - 成功状态 (success): 成功=8分，失败=2分
        - 结果描述完整性: 有详细结果+1分
        - 步骤完整性: 有详细步骤+1分
        """
        base_score = 8.0 if exp.success else 2.0


        if exp.result and len(exp.result) > 10:
            base_score += 1.0


        if exp.steps and len(exp.steps) >= 2:
            base_score += 1.0

        return min(10.0, base_score)

    def _assess_reusability(self, exp: ExperienceData) -> float:
        """
        评估可复用性 - 是否可应用到其他场景

        评估因素：
        - 任务描述泛化程度: 具体任务低分，通用模式高分
        - 步骤抽象程度: 具体工具调用低分，通用流程高分
        - 使用次数: 被多次使用说明可复用性高
        """
        base_score = 5.0


        task_len = len(exp.task_desc)
        if 20 <= task_len <= 100:
            base_score += 1.5


        specific_patterns = [
            r"\d+\.\d+\.\d+\.\d+",
            r"C:\\|/home/|/usr/",
            r"\b[0-9a-f]{8,}\b",
        ]
        import re
        for pattern in specific_patterns:
            if re.search(pattern, exp.task_desc, re.IGNORECASE):
                base_score -= 1.0
                break


        if exp.usage_count > 5:
            base_score += 2.0
        elif exp.usage_count > 2:
            base_score += 1.0


        if exp.steps:

            generic_words = ["analyze", "check", "process", "validate", "配置", "检查", "分析"]
            for step in exp.steps:
                step_str = str(step).lower()
                if any(word in step_str for word in generic_words):
                    base_score += 0.5
                    break

        return min(10.0, max(0.0, base_score))

    def _assess_timeliness(self, exp: ExperienceData) -> float:
        """
        评估时效性 - 是否仍然有效

        评估因素：
        - 创建时间: 越新越高分
        - 涉及技术时效性: （需要配置信息）

        时间衰减：
        - 7天内: 10分
        - 30天内: 9分
        - 90天内: 7分
        - 180天内: 5分
        - 365天内: 3分
        - 超过365天: 2分
        """
        try:
            created = datetime.fromisoformat(exp.created_at.replace('Z', '+00:00'))
            now = datetime.now()
            days_old = (now - created).days


            if days_old <= 7:
                return 10.0
            elif days_old <= 30:
                return 9.0
            elif days_old <= 90:
                return 7.0
            elif days_old <= 180:
                return 5.0
            elif days_old <= 365:
                return 3.0
            else:
                return 2.0

        except Exception:

            return 5.0

    def _assess_relevance(self, exp: ExperienceData) -> float:
        """
        评估相关性 - 与任务的相关程度

        注意：这需要具体的任务上下文来评估
        在没有上下文的情况下，基于以下因素：
        - 任务描述完整性
        - 步骤详细程度
        - 上下文信息丰富度
        """
        base_score = 5.0


        if exp.task_desc:
            task_len = len(exp.task_desc)
            if task_len >= 20:
                base_score += 2.0
            elif task_len >= 10:
                base_score += 1.0


        if exp.steps:
            step_count = len(exp.steps)
            if step_count >= 3:
                base_score += 1.5
            elif step_count >= 1:
                base_score += 0.5


        if exp.context:
            context_score = min(1.5, len(exp.context) * 0.3)
            base_score += context_score

        return min(10.0, base_score)

    def _assess_reliability(self, exp: ExperienceData) -> float:
        """
        评估可靠性 - 成功率统计

        评估因素：
        - 历史成功率: success_count / usage_count
        - 成功状态: 最近一次是否成功
        - 使用次数: 样本量越大越可靠
        """
        if exp.usage_count == 0:

            return 8.0 if exp.success else 3.0


        success_rate = exp.success_count / exp.usage_count if exp.usage_count > 0 else 0.5


        base_score = success_rate * 10


        if exp.usage_count >= 10:
            confidence = 1.0
        elif exp.usage_count >= 5:
            confidence = 0.9
        elif exp.usage_count >= 3:
            confidence = 0.8
        else:
            confidence = 0.7


        if exp.success:
            base_score += 1.0

        return min(10.0, base_score * confidence + (1 - confidence) * 5)

    def _should_use_ai_assessment(self, exp: ExperienceData, rule_score: QualityScore) -> bool:
        """判断是否应使用AI辅助评估"""

        scores = [
            rule_score.effectiveness, rule_score.reusability,
            rule_score.timeliness, rule_score.relevance, rule_score.reliability
        ]
        variance = max(scores) - min(scores)


        return variance > 4.0

    def _ai_assess_experience(self, exp: ExperienceData) -> QualityScore | None:
        """使用AI辅助评估经验质量"""
        try:
            system_prompt = """你是一个经验质量评估专家。请评估以下任务经验的质量。
请从5个维度进行评分（0-10分），并返回JSON格式结果：
{
    "effectiveness": 有效性评分,
    "reusability": 可复用性评分,
    "timeliness": 时效性评分,
    "relevance": 相关性评分,
    "reliability": 可靠性评分,
    "reasoning": "评分理由简述"
}"""

            user_prompt = f"""任务描述: {exp.task_desc}
执行步骤: {' -> '.join(exp.steps) if exp.steps else '无'}
执行结果: {'成功' if exp.success else '失败'} - {exp.result}
使用次数: {exp.usage_count}次
创建时间: {exp.created_at}

请评估这条经验的质量。"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = call_thinker(messages, temperature=0.3)

            if response:

                import re
                json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return QualityScore(
                        effectiveness=result.get("effectiveness", 5.0),
                        reusability=result.get("reusability", 5.0),
                        timeliness=result.get("timeliness", 5.0),
                        relevance=result.get("relevance", 5.0),
                        reliability=result.get("reliability", 5.0),
                        details={"ai_reasoning": result.get("reasoning", "")}
                    )

            return None

        except Exception as e:
            logger.warning(f"[QualityAssessor] AI评估失败: {e}")
            return None

    def _blend_scores(self, rule_score: QualityScore, ai_score: QualityScore) -> QualityScore:
        """混合规则和AI评分结果（规则70% + AI30%）"""
        return QualityScore(
            effectiveness=round(rule_score.effectiveness * 0.7 + ai_score.effectiveness * 0.3, 2),
            reusability=round(rule_score.reusability * 0.7 + ai_score.reusability * 0.3, 2),
            timeliness=round(rule_score.timeliness * 0.7 + ai_score.timeliness * 0.3, 2),
            relevance=round(rule_score.relevance * 0.7 + ai_score.relevance * 0.3, 2),
            reliability=round(rule_score.reliability * 0.7 + ai_score.reliability * 0.3, 2),
            details={**rule_score.details, **ai_score.details, "blended": True}
        )

    def _get_cached_score(self, memory_id: str) -> QualityScore | None:
        """获取缓存的评分"""
        if memory_id in self._quality_cache:
            cached = self._quality_cache[memory_id]
            cached_time = datetime.fromisoformat(cached.assessed_at)
            if (datetime.now() - cached_time).seconds < self._cache_ttl:
                return cached
            else:
                del self._quality_cache[memory_id]
        return None

    def _cache_score(self, memory_id: str, score: QualityScore):
        """缓存评分结果"""
        self._quality_cache[memory_id] = score


        if len(self._quality_cache) > 1000:

            items = list(self._quality_cache.items())
            for key, _ in items[:200]:
                del self._quality_cache[key]

    async def _store_quality_record(self, memory_id: str, score: QualityScore):
        """存储质量记录到memory"""
        try:
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default_user",
                content={
                    "memory_id": memory_id,
                    "quality_score": score.to_dict()
                },
                memory_type="quality_record",
                layer="medium",
                context={
                    "target_memory_id": memory_id,
                    "overall_score": score.overall,
                    "quality_level": self._get_quality_level(score.overall)
                },
                rating=int(score.overall),
                expire_days=30,
                source=MemorySource.SYSTEM  # Agent-4: 系统写入
            )
        except Exception as e:
            logger.warning(f"[QualityAssessor] 存储质量记录失败: {e}")

    async def _store_rating_update(self, memory_id: str, new_rating: int):
        """存储评分更新记录"""
        try:
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default_user",
                content={
                    "memory_id": memory_id,
                    "new_rating": new_rating,
                    "updated_at": datetime.now().isoformat()
                },
                memory_type="rating_update",
                layer="short",
                expire_days=7,
                source=MemorySource.SYSTEM  # Agent-4: 系统写入
            )
        except Exception as e:
            logger.warning(f"[QualityAssessor] 存储评分更新记录失败: {e}")

    def _get_quality_level(self, score: float) -> str:
        """获取质量等级"""
        for level, threshold in sorted(self.QUALITY_LEVELS.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold:
                return level
        return "bad"

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算两段文本的简单相似度（基于共同词）

        Returns:
            float: 相似度 0-1
        """
        if not text1 or not text2:
            return 0.0


        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0


        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0






quality_assessor = ExperienceQualityAssessor()






async def assess_experience(experience_data: dict[str, Any]) -> QualityScore:
    """便捷函数：评估单条经验"""
    return await quality_assessor.assess_experience(experience_data)


async def filter_high_quality_experiences(experiences: list[dict[str, Any]],
                                    min_score: float = 7.0) -> list[dict[str, Any]]:
    """便捷函数：过滤高质量经验"""
    results = await quality_assessor.assess_batch(experiences)
    return [exp for exp, score in results if score.overall >= min_score]


async def get_experience_quality_report() -> dict[str, Any]:
    """便捷函数：获取经验质量报告"""
    return await quality_assessor.get_quality_stats()



async def assess_quality(experience: dict[str, Any]) -> dict[str, float]:
    """向后兼容的质量评估接口"""
    score = await quality_assessor.assess_experience(experience)
    return {
        "overall": score.overall,
        "effectiveness": score.effectiveness,
        "reusability": score.reusability,
        "timeliness": score.timeliness,
        "relevance": score.relevance,
        "reliability": score.reliability
    }
