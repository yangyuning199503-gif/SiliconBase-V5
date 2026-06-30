#!/usr/bin/env python3
"""
轻量级幻觉检测系统 - 让零号机拥有"辨别真假"的基础能力
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【设计原则】
1. 轻量可落地 - 不追求100%检测，先解决70%明显幻觉
2. 非阻断式 - 只标记，不阻断，让AI自己意识到问题
3. 渐进增强 - 从规则匹配开始，逐步引入更复杂检测
4. 与现有架构无缝集成 - 不破坏原有生命体验流程

【核心功能】
1. 不确定性评分 (0-1) - 基于关键词和上下文的置信度评估
2. 事实类型识别 - 识别可验证的事实陈述
3. 与知识库对比 - 简单匹配验证
4. 幻觉率统计 - 数据驱动持续改进

【评分标准】
- 0.0-0.3: 高置信度 (绿色)
- 0.3-0.6: 中等不确定 (黄色)
- 0.6-1.0: 高度疑似幻觉 (红色)
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.exceptions import AIEmptyResponseError
from core.logger import logger

# from core.memory.vector_memory import vector_memory  # 【P1-迁移】已替换为 VectorStore
from core.memory.memory_service import get_memory_service


class HallucinationLevel(Enum):
    """幻觉等级 - 用于分类标记"""
    NONE = "none"           # 无幻觉风险
    LOW = "low"             # 轻微不确定
    MEDIUM = "medium"       # 中等不确定
    HIGH = "high"           # 高度疑似幻觉
    CRITICAL = "critical"   # 严重幻觉（与已知事实矛盾）


@dataclass
class FactClaim:
    """事实陈述 - 从AI输出中提取的可验证陈述"""
    text: str                           # 原始文本
    claim_type: str                     # 陈述类型 (date, number, entity, event, etc.)
    confidence: float                   # AI表达的自我置信度 (0-1)
    has_source: bool                    # 是否有明确来源标注
    source_ref: str | None = None    # 来源引用 (如 "根据L3记忆...")


@dataclass
class HallucinationCheckResult:
    """幻觉检测结果"""
    # 基础评分
    uncertainty_score: float            # 不确定性评分 (0-1)
    hallucination_level: HallucinationLevel

    # 检测详情
    detected_claims: list[FactClaim]    # 检测到的事实陈述
    uncertain_phrases: list[str]        # 检测到的犹豫表达
    contradiction_flags: list[str]      # 矛盾标记

    # 验证结果
    knowledge_matches: list[dict]       # 知识库匹配结果
    verification_notes: list[str]       # 验证备注

    # 元信息
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    response_snippet: str = ""          # 被检测的文本片段

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "uncertainty_score": self.uncertainty_score,
            "hallucination_level": self.hallucination_level.value,
            "detected_claims": [
                {
                    "text": c.text,
                    "type": c.claim_type,
                    "confidence": c.confidence,
                    "has_source": c.has_source
                } for c in self.detected_claims
            ],
            "uncertain_phrases": self.uncertain_phrases,
            "contradiction_flags": self.contradiction_flags,
            "verification_notes": self.verification_notes,
            "timestamp": self.timestamp
        }


class HallucinationDetector:
    """
    轻量级幻觉检测器

    核心策略：
    1. 基于规则的快速检测 (成本低，覆盖70%常见问题)
    2. 与现有记忆系统对比 (利用已有能力)
    3. 渐进式验证 (高风险才触发深度检查)
    """

    # ========== 检测模式库 ==========

    # 不确定性关键词 - 检测AI的犹豫表达
    UNCERTAINTY_PATTERNS = {
        HallucinationLevel.HIGH: [
            r"不确定", r"不知道", r"不清楚", r"不了解", r"无法确定",
            r"可能.*可能", r"也许.*也许",  # 重复犹豫
            r"猜.*是", r"估计.*是",
            r"我不确定", r"我不太确定",
        ],
        HallucinationLevel.MEDIUM: [
            r"可能", r"也许", r"大概", r"或许", r"应该", r"似乎",
            r"看起来.*像是", r"好像是", r"可能是",
            r"通常.*会", r"一般.*会",
            r"据我所知", r"如果我没记错",
        ],
        HallucinationLevel.LOW: [
            r"我觉得", r"我认为", r"我猜", r"我想",
            r"我的理解是", r"从我看来",
        ]
    }

    # 幻觉风险表达 - AI可能"编造"的信号
    HALLUCINATION_MARKERS = [
        r"根据我的训练数据",  # 模糊的"训练数据"引用
        r"我记得",  # 记忆幻觉
        r"上一次.*的时候",  # 虚构的历史
        r"你总是", r"你从来",  # 绝对化表述 (通常不准确)
        r"所有人都知道",  # 虚假共识
        r"研究表明.*[无具体引用]",  # 虚构研究
    ]

    # 可验证事实模式 - 需要特别关注的陈述
    FACT_PATTERNS = {
        "date": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",  # 具体日期
            r"(\d{1,2})月(\d{1,2})日",  # 月日
            r"星期[一二三四五六日]",  # 星期
            r"[去今明后]年",  # 相对年份
        ],
        "number": [
            r"(\d+(?:\.\d+)?)\s*[个百分点|%]",  # 百分比
            r"(\d+(?:\.\d+)?)\s*[万亿百千]?",  # 大数字
            r"第[一二三四五六七八九十\d]+[名个位]",  # 序数
        ],
        "entity": [
            r"[《""]([^《""]+)[》""]",  # 书名/作品名
            r"(?:根据|据)\s*([^，。]+)的",  # 引用某人/某机构
        ],
        "causation": [
            r"因为.*所以",  # 因果关系
            r"导致", r"引起", r"造成",
            r"由于.*因此",
        ]
    }

    # 自我修正表达 - 检测到AI在"圆谎"
    SELF_CORRECTION_PATTERNS = [
        r"更准确地说", r"更正一下", r"我刚才说错了",
        r"实际上", r"事实上",  # 当用于否定前文时
    ]

    # ========== 置信度权重 ==========

    # 各检测维度的权重
    WEIGHTS = {
        "uncertainty_phrases": 0.30,    # 犹豫表达权重
        "hallucination_markers": 0.25,   # 幻觉标记权重
        "source_attribution": 0.20,      # 来源标注权重
        "fact_consistency": 0.15,        # 事实一致性权重
        "self_confidence": 0.10,         # 自我置信度权重
    }

    def __init__(
        self,
        uncertainty_threshold: float = 0.6,
        enable_knowledge_check: bool = True,
        enable_source_tracking: bool = True
    ):
        """
        初始化幻觉检测器

        Args:
            uncertainty_threshold: 不确定性阈值，超过则标记为疑似幻觉
            enable_knowledge_check: 是否启用知识库对比
            enable_source_tracking: 是否启用来源追踪
        """
        self.uncertainty_threshold = uncertainty_threshold
        self.enable_knowledge_check = enable_knowledge_check
        self.enable_source_tracking = enable_source_tracking

        # 统计信息
        self.stats = {
            "total_checks": 0,
            "high_uncertainty_detected": 0,
            "knowledge_verifications": 0,
            "last_check_time": 0
        }

        logger.info(f"[HallucinationDetector] 初始化完成，阈值={uncertainty_threshold}")

    async def check(
        self,
        ai_response: str,
        context: dict | None = None,
        session_id: str = ""
    ) -> HallucinationCheckResult:
        """
        检测AI回复中的幻觉风险

        Args:
            ai_response: AI的回复文本
            context: 上下文信息 (包含记忆引用、工具结果等)
            session_id: 会话ID

        Returns:
            HallucinationCheckResult: 检测结果

        Raises:
            AIEmptyResponseError: 当ai_response为空时抛出
            HallucinationDetectionError: 当检测过程发生严重错误时抛出
        """
        # 【异常处理铁律】AI响应为空 = ERROR日志 + 抛错，禁止静默
        if not ai_response:
            error_msg = "[Hallucination] 检测到空AI响应，无法执行幻觉检测"
            logger.error(error_msg)
            raise AIEmptyResponseError(f"AI响应为空，无法检测幻觉。session_id={session_id}")

        self.stats["total_checks"] += 1
        self.stats["last_check_time"] = time.time()

        context = context or {}

        # 1. 检测不确定性表达
        uncertain_phrases, uncertainty_score = await self._detect_uncertainty(ai_response)

        # 2. 检测幻觉标记
        hallucination_flags = await self._detect_hallucination_markers(ai_response)

        # 3. 提取事实陈述
        detected_claims = await self._extract_fact_claims(ai_response)

        # 4. 检查来源标注
        source_analysis = await self._analyze_source_attribution(ai_response, context)

        # 5. 知识库对比 (仅对高价值陈述)
        knowledge_matches = []
        if self.enable_knowledge_check and detected_claims:
            knowledge_matches = await self._verify_with_knowledge(detected_claims, context)

        # 6. 综合评分
        final_score = await self._calculate_final_score(
            uncertainty_score,
            hallucination_flags,
            source_analysis,
            knowledge_matches,
            detected_claims
        )

        # 7. 确定等级
        level = await self._determine_level(final_score, hallucination_flags, knowledge_matches)

        # 8. 生成验证备注
        notes = await self._generate_verification_notes(
            level, uncertain_phrases, hallucination_flags, source_analysis, knowledge_matches
        )

        result = HallucinationCheckResult(
            uncertainty_score=final_score,
            hallucination_level=level,
            detected_claims=detected_claims,
            uncertain_phrases=uncertain_phrases,
            contradiction_flags=hallucination_flags,
            knowledge_matches=knowledge_matches,
            verification_notes=notes,
            session_id=session_id,
            response_snippet=ai_response[:200] + "..." if len(ai_response) > 200 else ai_response
        )

        # 记录高不确定性检测
        if final_score >= self.uncertainty_threshold:
            self.stats["high_uncertainty_detected"] += 1
            logger.warning(
                f"[HallucinationDetector] 检测到疑似幻觉，"
                f"分数={final_score:.2f}, 等级={level.value}, "
                f"会话={session_id[:8]}..."
            )

        return result

    async def _detect_uncertainty(self, text: str) -> tuple[list[str], float]:
        """
        检测文本中的不确定性表达

        Returns:
            (检测到的短语列表, 综合不确定性分数)
        """
        detected = []
        weighted_score = 0.0

        text_lower = text.lower()

        # 按等级检测
        for level, patterns in self.UNCERTAINTY_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, text_lower)
                if matches:
                    if isinstance(matches[0], str):
                        detected.extend(matches)
                    else:
                        detected.append(pattern)

                    # 不同等级贡献不同分数
                    if level == HallucinationLevel.HIGH:
                        weighted_score += 0.4 * len(matches)
                    elif level == HallucinationLevel.MEDIUM:
                        weighted_score += 0.2 * len(matches)
                    else:
                        weighted_score += 0.1 * len(matches)

        # 去重并限制分数范围
        detected = list(set(detected))
        score = min(weighted_score, 1.0)

        return detected, score

    async def _detect_hallucination_markers(self, text: str) -> list[str]:
        """检测幻觉风险标记"""
        flags = []
        text_lower = text.lower()

        for pattern in self.HALLUCINATION_MARKERS:
            if re.search(pattern, text_lower):
                flags.append(pattern)

        return flags

    async def _extract_fact_claims(self, text: str) -> list[FactClaim]:
        """
        从文本中提取事实陈述

        提取可能需要验证的具体陈述
        """
        claims = []

        for claim_type, patterns in self.FACT_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    # 提取包含匹配的完整句子
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    sentence = text[start:end].strip()

                    # 检查是否有来源标注
                    has_source = await self._check_source_reference(text, match.start())

                    claim = FactClaim(
                        text=sentence,
                        claim_type=claim_type,
                        confidence=0.5,  # 默认中等置信度
                        has_source=has_source
                    )
                    claims.append(claim)

        return claims

    async def _check_source_reference(self, text: str, position: int) -> bool:
        """检查某位置附近是否有来源引用"""
        # 检查前文100字符内是否有来源引用
        context_start = max(0, position - 100)
        context = text[context_start:position]

        source_patterns = [
            r"根据[\w\s]+",
            r"据[\w\s]+称",
            r"来自[\w\s]+",
            r"[Ll]3.*记忆",
            r"记忆.*显示",
            r"检索.*结果",
            r"工具.*返回",
        ]

        return any(re.search(pattern, context) for pattern in source_patterns)

    async def _analyze_source_attribution(
        self,
        text: str,
        context: dict
    ) -> dict[str, Any]:
        """
        分析来源标注情况

        检查AI是否明确标注了信息来源
        """
        analysis = {
            "has_explicit_source": False,
            "source_types": [],
            "unattributed_claims": 0
        }

        # 检测明确来源标注
        source_patterns = {
            "memory": r"根据[\s\w]*记忆|L3.*记忆|长期记忆",
            "tool": r"工具.*显示|查询.*结果|检索.*结果",
            "knowledge": r"根据.*知识|知识库.*显示",
            "reasoning": r"基于.*推理|通过.*分析",
        }

        for source_type, pattern in source_patterns.items():
            if re.search(pattern, text):
                analysis["has_explicit_source"] = True
                analysis["source_types"].append(source_type)

        # 检查上下文中的引用
        if context:
            if context.get("memory_references"):
                analysis["source_types"].append("memory_ref")
            if context.get("tool_results"):
                analysis["source_types"].append("tool_ref")

        return analysis

    async def _verify_with_knowledge(
        self,
        claims: list[FactClaim],
        context: dict
    ) -> list[dict]:
        """
        与知识库对比验证

        简单实现：检索相关知识并返回相似度
        """
        matches = []

        try:
            memory_service = await get_memory_service()
            vector_store = memory_service.vector_store

            if not await vector_store.is_available():
                logger.debug("[HallucinationDetector] VectorStore 不可用，跳过知识验证")
                return matches

            for claim in claims[:3]:  # 只验证前3个陈述，控制成本
                # 使用向量记忆检索相关知识
                query = claim.text[:100]  # 限制长度

                # 优先搜索经验
                exp_results = await vector_store.search("experience", query, limit=3)
                experiences = []
                for r in exp_results:
                    similarity = 1.0 - (r.distance or 0.0)
                    metadata = r.metadata or {}
                    score = similarity
                    if metadata.get("success") in (True, "true", "True"):
                        score += 0.2
                    experiences.append({
                        "id": r.id,
                        "document": r.document,
                        "metadata": metadata,
                        "similarity": similarity,
                        "score": score,
                    })
                experiences.sort(key=lambda x: x["score"], reverse=True)
                experiences = experiences[:1]

                if experiences:
                    exp = experiences[0]
                    similarity = exp["similarity"]

                    matches.append({
                        "claim": claim.text[:50],
                        "matched_content": exp["document"][:100],
                        "similarity": similarity,
                        "source": "experience",
                        "consistent": similarity > 0.7
                    })
                else:
                    # 搜索知识库
                    know_results = await vector_store.search("knowledge", query, limit=1)
                    knowledge = []
                    for r in know_results:
                        similarity = 1.0 - (r.distance or 0.0)
                        knowledge.append({
                            "id": r.id,
                            "document": r.document,
                            "metadata": r.metadata or {},
                            "similarity": similarity,
                        })

                    if knowledge:
                        know = knowledge[0]
                        matches.append({
                            "claim": claim.text[:50],
                            "matched_content": know["document"][:100],
                            "similarity": know["similarity"],
                            "source": "knowledge",
                            "consistent": know["similarity"] > 0.6
                        })

        except Exception as e:
            logger.warning(f"[HallucinationDetector] 知识验证失败: {e}")

        return matches

    async def _calculate_final_score(
        self,
        uncertainty_score: float,
        hallucination_flags: list[str],
        source_analysis: dict,
        knowledge_matches: list[dict],
        detected_claims: list[FactClaim]
    ) -> float:
        """计算最终不确定性分数"""

        # 基础分数来自不确定性检测
        score = uncertainty_score * self.WEIGHTS["uncertainty_phrases"]

        # 幻觉标记增加分数
        if hallucination_flags:
            score += min(len(hallucination_flags) * 0.1, self.WEIGHTS["hallucination_markers"])

        # 无来源标注增加风险
        if not source_analysis["has_explicit_source"] and detected_claims:
            # 有事实陈述但无来源标注，增加风险
            unattributed_ratio = len([c for c in detected_claims if not c.has_source]) / len(detected_claims)
            score += unattributed_ratio * self.WEIGHTS["source_attribution"]
        else:
            # 有来源标注，降低分数
            score -= 0.1

        # 知识库一致性检查
        if knowledge_matches:
            inconsistent = [m for m in knowledge_matches if not m.get("consistent", True)]
            if inconsistent:
                score += len(inconsistent) * 0.1
            else:
                score -= 0.05

        # 确保分数在0-1范围内
        return max(0.0, min(1.0, score))

    async def _determine_level(
        self,
        score: float,
        flags: list[str],
        knowledge_matches: list[dict]
    ) -> HallucinationLevel:
        """根据分数确定幻觉等级"""

        # 检查是否有明确矛盾
        has_contradiction = any(
            not m.get("consistent", True) for m in knowledge_matches
        )

        if score >= 0.8 or has_contradiction and score >= 0.6:
            return HallucinationLevel.CRITICAL
        elif score >= 0.6 or has_contradiction and score >= 0.4:
            return HallucinationLevel.HIGH
        elif score >= 0.4:
            return HallucinationLevel.MEDIUM
        elif score >= 0.2:
            return HallucinationLevel.LOW
        else:
            return HallucinationLevel.NONE

    async def _generate_verification_notes(
        self,
        level: HallucinationLevel,
        uncertain_phrases: list[str],
        flags: list[str],
        source_analysis: dict,
        knowledge_matches: list[dict]
    ) -> list[str]:
        """生成验证备注"""
        notes = []

        if level == HallucinationLevel.NONE:
            notes.append("✓ 无明显幻觉风险")
        elif level == HallucinationLevel.LOW:
            notes.append("⚠ 轻微不确定性")
        elif level == HallucinationLevel.MEDIUM:
            notes.append("⚠ 存在不确定表述")
        elif level == HallucinationLevel.HIGH:
            notes.append("⚠ 高度疑似幻觉")
        elif level == HallucinationLevel.CRITICAL:
            notes.append("❌ 检测到与知识库矛盾的陈述")

        if uncertain_phrases:
            notes.append(f"检测到 {len(uncertain_phrases)} 处不确定表达")

        if not source_analysis["has_explicit_source"]:
            notes.append("建议添加信息来源标注")

        if knowledge_matches:
            consistent = sum(1 for m in knowledge_matches if m.get("consistent"))
            notes.append(f"知识库验证: {consistent}/{len(knowledge_matches)} 项一致")

        return notes

    async def get_stats(self) -> dict[str, Any]:
        """获取检测统计"""
        return {
            **self.stats,
            "high_uncertainty_rate": (
                self.stats["high_uncertainty_detected"] / max(1, self.stats["total_checks"])
            )
        }


# ========== 便捷函数 ==========

# 全局检测器实例
_hallucination_detector: HallucinationDetector | None = None


async def get_hallucination_detector() -> HallucinationDetector:
    """获取全局幻觉检测器实例"""
    global _hallucination_detector
    if _hallucination_detector is None:
        _hallucination_detector = HallucinationDetector()
    return _hallucination_detector


async def check_hallucination(
    ai_response: str,
    context: dict | None = None,
    session_id: str = ""
) -> HallucinationCheckResult:
    """
    便捷函数：检测幻觉

    Args:
        ai_response: AI回复文本
        context: 上下文信息
        session_id: 会话ID

    Returns:
        HallucinationCheckResult
    """
    detector = await get_hallucination_detector()
    return await detector.check(ai_response, context, session_id)


async def format_hallucination_warning(result: HallucinationCheckResult) -> str:
    """
    格式化幻觉警告信息

    用于在AI输出中附加警告标记
    """
    if result.hallucination_level == HallucinationLevel.NONE:
        return ""

    level_emojis = {
        HallucinationLevel.LOW: "💭",
        HallucinationLevel.MEDIUM: "⚠️",
        HallucinationLevel.HIGH: "🚨",
        HallucinationLevel.CRITICAL: "❌"
    }

    emoji = level_emojis.get(result.hallucination_level, "⚠️")

    warning = f"\n\n{emoji} [事实核查] "

    if result.hallucination_level == HallucinationLevel.CRITICAL:
        warning += "检测到与知识库矛盾的内容，请谨慎对待。"
    elif result.hallucination_level == HallucinationLevel.HIGH:
        warning += "上述内容包含较多不确定表述，建议核实。"
    elif result.hallucination_level == HallucinationLevel.MEDIUM:
        warning += "部分内容基于推测，如有疑问请进一步确认。"
    else:
        warning += "轻微不确定。"

    if result.verification_notes:
        warning += f" ({'; '.join(result.verification_notes[:2])})"

    return warning


# ========== 自我质疑提示词生成 ==========

SELF_QUESTIONING_PROMPT = """
【🧠 自我质疑与事实核查指南】

在回答用户时，请遵循以下原则：

1. **知识边界意识**
   - 如果你不确定某个信息，明确说"我不确定"或"我可能记错了"
   - 如果你不知道，直接说"我不知道"
   - 绝对不要编造不存在的事实、数据或引用

2. **信息来源标注**
   - 基于记忆的内容：标注"根据L3长期记忆..."
   - 基于工具查询：标注"根据工具查询结果..."
   - 基于推理：标注"基于现有信息推理..."
   - 纯推测：明确说"这是我的推测，未经证实"

3. **置信度表达**
   - 高置信度 (80%+): 用确定的语气
   - 中等置信度 (50-80%): 用"可能是"、"很可能是"
   - 低置信度 (<50%): 明确说明"不确定"、"只是猜测"

4. **避免幻觉的具体措施**
   - 不要虚构具体日期、数字、人名
   - 不要编造"研究表明"或"专家说过"
   - 不要假装记得不存在的对话历史
   - 对于模糊记忆，使用"我记得好像...但不确定"

5. **当被质疑时**
   - 承认不确定性比坚持错误更重要
   - 主动说"让我再查证一下"
   - 如果发现自己的错误，立即更正

记住：说"不知道"不会降低你的价值，但编造信息会。
"""


def inject_self_questioning_prompt(base_prompt: str) -> str:
    """
    向提示词注入自我质疑约束

    Args:
        base_prompt: 原始提示词

    Returns:
        注入后的提示词
    """
    return f"""{base_prompt}

{SELF_QUESTIONING_PROMPT}
"""


async def _test_main():
    # 简单测试
    detector = HallucinationDetector()

    test_cases = [
        "根据L3记忆，用户昨天提到了这个项目。",
        "我不确定，但可能是星期三吧...",
        "研究表明，90%的人都喜欢这个功能。",
        "根据工具查询结果，当前温度是25度。",
    ]

    print("=== 幻觉检测测试 ===\n")

    for text in test_cases:
        result = await detector.check(text, session_id="test")
        print(f"文本: {text}")
        print(f"分数: {result.uncertainty_score:.2f}")
        print(f"等级: {result.hallucination_level.value}")
        print(f"备注: {result.verification_notes}")
        print("-" * 50)


if __name__ == "__main__":
    asyncio.run(_test_main())
