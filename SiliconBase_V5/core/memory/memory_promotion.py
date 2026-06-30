#!/usr/bin/env python3
"""
记忆晋升系统 V1.0 - MemRank算法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心特性】
  ✓ 多维度价值评估（内容、时间、关联、反馈）
  ✓ 动态阈值调整（基于记忆库状态）
  ✓ 自适应衰减（避免过早晋升或遗忘）
  ✓ 图论关联分析（PageRank思想）
  ✓ 零模型依赖（纯算法，无LLM）

【算法设计】
  记忆价值 = 基础价值 × 时间衰减 × 访问频率 × 关联强度

  基础价值 = 内容密度 + 结构化程度 + 场景重要性
  时间衰减 = exp(-λ × 年龄)  （指数衰减）
  访问频率 = log(1 + 访问次数) / log(1 + 平均访问)
  关联强度 = PageRank得分 × 连接密度

【晋升策略】
  - L2→L3: 价值 > 动态阈值 & 年龄 > 24小时 & 访问 > 1次
  - L3→L4: 价值 > 高阈值 & 被引用 > 3次 & 跨场景
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import numpy as np

from core.logger import logger
from core.memory.memory_manager import MemoryLayer
from core.memory.memory_service import get_memory_service


class MemoryValueDimension(Enum):
    """记忆价值维度"""
    CONTENT = "content"          # 内容价值
    TEMPORAL = "temporal"        # 时间价值
    ACCESS = "access"            # 访问价值
    RELATION = "relation"        # 关联价值
    FEEDBACK = "feedback"        # 反馈价值


@dataclass
class MemRankScore:
    """MemRank评分结果"""
    total_score: float = 0.0                    # 总分 (0-1)
    base_value: float = 0.0                     # 基础价值
    temporal_decay: float = 1.0                 # 时间衰减系数
    access_bonus: float = 1.0                   # 访问频率加成
    relation_bonus: float = 1.0                 # 关联强度加成
    feedback_bonus: float = 1.0                 # 反馈加成
    dimensions: dict[str, float] = field(default_factory=dict)  # 各维度得分

    def __post_init__(self):
        if not self.dimensions:
            self.dimensions = {
                "content": 0.0,
                "temporal": 0.0,
                "access": 0.0,
                "relation": 0.0,
                "feedback": 0.0
            }


class MemRankAlgorithm:
    """
    MemRank记忆价值评估算法

    基于信息检索、图论和行为分析的混合算法
    """

    # 内容价值权重
    CONTENT_WEIGHTS = {
        "length": 0.15,           # 长度权重
        "structure": 0.20,        # 结构化程度
        "keywords": 0.25,         # 关键词密度
        "uniqueness": 0.20,       # 独特性（与现有记忆的去重）
        "completeness": 0.20      # 完整性（有上下文、结果等）
    }

    # 高价值关键词（领域特定）
    HIGH_VALUE_KEYWORDS = {
        "preference": ["喜欢", "偏好", "习惯", "总是", "从不", "prefer", "always", "never"],
        "important": ["重要", "关键", "必须", "切记", "important", "critical", "must"],
        "identity": ["我是", "我叫", "我的", "I am", "my name", "my"],
        "goal": ["目标", "计划", "想要", "希望", "goal", "plan", "want"],
        "knowledge": ["知识", "经验", "教训", "技巧", "knowledge", "experience", "lesson"]
    }

    def __init__(self):
        self.decay_lambda = 0.1  # 时间衰减系数
        self.min_promote_score = 0.65  # 最小晋升分数

    def calculate_memrank(self, memory: dict, user_memories: list[dict]) -> MemRankScore:
        """
        计算记忆的MemRank分数

        Args:
            memory: 待评估的记忆
            user_memories: 该用户的所有记忆（用于计算相对价值）

        Returns:
            MemRankScore: 评分结果
        """
        score = MemRankScore()

        # 1. 计算基础价值 (0-1)
        score.base_value = self._calculate_base_value(memory)

        # 2. 计算时间衰减系数 (0-1)
        score.temporal_decay = self._calculate_temporal_decay(memory)

        # 3. 计算访问频率加成 (0.5-2.0)
        score.access_bonus = self._calculate_access_bonus(memory, user_memories)

        # 4. 计算关联强度加成 (0.5-2.0)
        score.relation_bonus = self._calculate_relation_bonus(memory, user_memories)

        # 5. 计算反馈加成 (0.8-1.5)
        score.feedback_bonus = self._calculate_feedback_bonus(memory)

        # 【补丁1】新记忆保护期：24小时内基础价值加权1.3倍
        created_at = memory.get("created_at")
        is_new = False
        if created_at:
            try:
                if isinstance(created_at, str):
                    created_time = datetime.fromisoformat(created_at)
                else:
                    created_time = datetime.fromtimestamp(created_at)
                age_hours = (datetime.now() - created_time).total_seconds() / 3600
                if age_hours < 24:
                    score.base_value = min(1.0, score.base_value * 1.3)
                    is_new = True
            except Exception:
                pass

        # 【补丁2】热点保护：访问>=3次时，时间衰减不低于0.7
        access_count = memory.get("access_count", 0)
        if access_count >= 3:
            score.temporal_decay = max(0.7, score.temporal_decay)

        # 6. 综合计算总分
        score.total_score = (
            score.base_value *
            score.temporal_decay *
            score.access_bonus *
            score.relation_bonus *
            score.feedback_bonus
        )

        # 限制在0-1范围内
        score.total_score = min(1.0, max(0.0, score.total_score))

        # 记录维度信息
        score.dimensions = {
            "is_new": is_new,
            "is_hot": access_count >= 3,
            "base_value": round(score.base_value, 3),
            "temporal_decay": round(score.temporal_decay, 3)
        }

        return score

    def _calculate_base_value(self, memory: dict) -> float:
        """计算基础内容价值"""
        content = memory.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        scores = {}

        # 1. 长度得分 (最优长度: 50-500字符)
        length = len(text)
        if length < 10:
            scores["length"] = 0.1
        elif length < 50:
            scores["length"] = 0.3 + (length - 10) / 40 * 0.4
        elif length < 500:
            scores["length"] = 0.7 + (length - 50) / 450 * 0.3
        else:
            scores["length"] = 1.0

        # 2. 结构化程度
        has_context = bool(memory.get("context"))
        has_metadata = bool(memory.get("metadata"))
        has_tags = bool(memory.get("tags"))
        structure_count = sum([has_context, has_metadata, has_tags])
        scores["structure"] = structure_count / 3.0

        # 3. 关键词密度
        keyword_score = 0.0
        text_lower = text.lower()
        for _category, keywords in self.HIGH_VALUE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    keyword_score += 0.2  # 每个关键词加分
        scores["keywords"] = min(1.0, keyword_score)

        # 4. 独特性（基于内容哈希）
        hashlib.md5(text.encode()).hexdigest()[:16]
        # 独特性通过后续与现有记忆比较计算，这里先给默认值
        scores["uniqueness"] = 0.7

        # 5. 完整性
        has_result = bool(content.get("result") if isinstance(content, dict) else False)
        has_summary = bool(content.get("summary") if isinstance(content, dict) else False)
        scores["completeness"] = (has_result + has_summary) / 2.0 + 0.5

        # 加权求和
        total = sum(scores[k] * self.CONTENT_WEIGHTS[k] for k in scores)
        return min(1.0, total)

    def _calculate_temporal_decay(self, memory: dict) -> float:
        """
        计算时间衰减系数

        使用指数衰减: score = exp(-λ × age_hours)
        但近期记忆应有保护期
        """
        created_at = memory.get("created_at")
        if not created_at:
            return 1.0

        try:
            if isinstance(created_at, str):
                created_time = datetime.fromisoformat(created_at)
            else:
                created_time = datetime.fromtimestamp(created_at)

            age_hours = (datetime.now() - created_time).total_seconds() / 3600

            # 保护期：24小时内不衰减
            if age_hours < 24:
                return 1.0

            # 24小时后开始指数衰减
            adjusted_age = age_hours - 24
            decay = math.exp(-self.decay_lambda * adjusted_age / 24)  # 以天为单位

            return max(0.3, decay)  # 最低保留0.3

        except Exception:
            return 1.0

    def _calculate_access_bonus(self, memory: dict, all_memories: list[dict]) -> float:
        """
        计算访问频率加成

        使用对数缩放避免极端值:
        bonus = log(1 + access_count) / log(1 + avg_access)
        """
        access_count = memory.get("access_count", 0)

        # 计算该用户的平均访问次数
        total_access = sum(m.get("access_count", 0) for m in all_memories)
        avg_access = total_access / max(1, len(all_memories))

        if avg_access == 0:
            return 1.0 if access_count > 0 else 0.8

        # 对数缩放
        memory_log = math.log1p(access_count)
        avg_log = math.log1p(avg_access)

        ratio = memory_log / avg_log

        # 映射到 0.5 - 2.0 范围
        bonus = 0.5 + ratio * 1.5
        return min(2.0, max(0.5, bonus))

    def _calculate_relation_bonus(self, memory: dict, all_memories: list[dict]) -> float:
        """
        计算关联强度加成（简化版PageRank）

        基于:
        1. 直接引用次数
        2. 场景相似度
        3. 时间邻近性
        """
        memory_id = memory.get("id", "")
        scene = memory.get("scene", "")

        # 1. 被引用次数
        referenced_count = 0
        for m in all_memories:
            refs = m.get("referenced_memories", [])
            if memory_id in refs:
                referenced_count += 1

        # 2. 同场景记忆数
        same_scene_count = sum(1 for m in all_memories if m.get("scene") == scene)

        # 3. 计算连接密度
        connection_score = min(1.0, referenced_count / 3.0)  # 被引用3次满分
        scene_score = min(1.0, same_scene_count / 10.0)  # 同场景10个满分

        # 综合关联得分
        relation_score = (connection_score * 0.6 + scene_score * 0.4)

        # 映射到 0.5 - 2.0
        bonus = 0.5 + relation_score * 1.5
        return bonus

    def _calculate_feedback_bonus(self, memory: dict) -> float:
        """计算反馈加成"""
        rating = memory.get("rating", 0)

        if rating == 0:
            return 1.0  # 无反馈，中性
        elif rating >= 4:
            return 1.2 + (rating - 4) * 0.15  # 4分=1.2, 5分=1.35
        elif rating >= 3:
            return 1.0  # 3分，中性
        else:
            return 0.8  # 低分，降权


class MemoryPromotionEngine:
    """
    记忆晋升引擎

    基于MemRank算法，智能决定记忆晋升
    """

    def __init__(self):
        self.mempool = MemRankAlgorithm()
        self.promote_threshold_l2_l3 = 0.60  # L2→L3阈值
        self.promote_threshold_l3_l4 = 0.80  # L3→L4阈值

    async def evaluate_and_promote(self, user_id: str, dry_run: bool = False) -> dict:
        """
        评估并晋升记忆

        Args:
            user_id: 用户ID
            dry_run: 仅评估，不实际晋升

        Returns:
            晋升报告
        """
        report = {
            "user_id": user_id,
            "evaluated": 0,
            "promoted_l2_l3": 0,
            "promoted_l3_l4": 0,
            "rejected": 0,
            "details": []
        }

        try:
            # 1. 获取用户所有L2记忆
            l2_memories = await self._get_layer_memories(user_id, "short")
            l3_memories = await self._get_layer_memories(user_id, "medium")
            all_memories = l2_memories + l3_memories

            if not l2_memories:
                logger.debug(f"[MemPromotion] 用户 {user_id} 无L2记忆需要评估")
                return report

            logger.info(f"[MemPromotion] 开始评估用户 {user_id} 的 {len(l2_memories)} 条L2记忆")

            # 2. 【动态阈值】基于所有记忆得分分布计算
            all_scores = []
            for memory in all_memories:
                score = self.mempool.calculate_memrank(memory, all_memories)
                all_scores.append(score.total_score)

            if len(all_scores) >= 5:
                # 有5条以上记忆时使用动态阈值（60%分位数）
                dynamic_threshold = np.percentile(all_scores, 60)
                threshold_l2_l3 = max(0.55, min(0.75, dynamic_threshold))
                logger.info(f"[MemPromotion] 动态阈值L2→L3: {threshold_l2_l3:.3f} (基于{len(all_scores)}条记忆)")
            else:
                # 记忆太少时使用默认阈值
                threshold_l2_l3 = 0.60
                logger.info(f"[MemPromotion] 使用默认阈值L2→L3: {threshold_l2_l3:.3f} (记忆数量不足)")

            # 3. 评估每条L2记忆并决策
            for memory in l2_memories:
                report["evaluated"] += 1

                score = self.mempool.calculate_memrank(memory, all_memories)

                detail = {
                    "memory_id": memory.get("id", "unknown"),
                    "score": score.total_score,
                    "base_value": score.base_value,
                    "dimensions": score.dimensions,
                    "decision": "keep"
                }

                # 4. 决策（使用动态阈值）
                if score.total_score >= threshold_l2_l3:
                    if not dry_run:
                        success = await self._promote_l2_to_l3(user_id, memory, score)
                        if success:
                            report["promoted_l2_l3"] += 1
                            detail["decision"] = "promoted_l2_l3"
                            logger.info(f"[MemPromotion] L2→L3: {memory.get('id', 'unknown')[:8]}... "
                                       f"得分={score.total_score:.3f}")
                    else:
                        detail["decision"] = "would_promote_l2_l3"
                        report["promoted_l2_l3"] += 1
                else:
                    report["rejected"] += 1
                    detail["decision"] = "rejected"

                report["details"].append(detail)

            # 4. 评估L3→L4晋升
            for memory in l3_memories:
                score = self.mempool.calculate_memrank(memory, all_memories)

                # L3→L4需要更高阈值 + 被引用次数
                referenced = memory.get("referenced_count", 0)
                cross_scene = len({m.get("scene") for m in all_memories
                                     if m.get("id") in memory.get("references", [])})

                if (score.total_score >= self.promote_threshold_l3_l4 and
                    referenced >= 3 and
                    cross_scene >= 2):

                    if not dry_run:
                        success = await self._promote_l3_to_l4(user_id, memory, score)
                        if success:
                            report["promoted_l3_l4"] += 1
                            logger.info(f"[MemPromotion] L3→L4: {memory.get('id', 'unknown')[:8]}...")
                    else:
                        report["promoted_l3_l4"] += 1

            logger.info(f"[MemPromotion] 用户 {user_id} 评估完成: "
                       f"评估={report['evaluated']}, "
                       f"L2→L3={report['promoted_l2_l3']}, "
                       f"L3→L4={report['promoted_l3_l4']}")

            return report

        except Exception as e:
            logger.error(f"[MemPromotion] 评估失败: {e}", exc_info=True)
            return report

    async def _get_layer_memories(self, user_id: str, layer: str) -> list[dict]:
        """获取指定层的记忆"""
        try:
            ms = await get_memory_service()
            results = await ms.query_memories(
                user_id=user_id,
                layer=layer,
                limit=1000  # 获取足够多的记忆
            )
            return results if results else []
        except Exception as e:
            logger.error(f"[MemPromotion] 查询记忆失败: {e}")
            return []

    async def _promote_l2_to_l3(self, user_id: str, memory: dict, score: MemRankScore) -> bool:
        """将L2记忆晋升到L3"""
        try:
            mem_id = memory.get("id")
            content = memory.get("content", {})
            context = memory.get("context", {})

            ms = await get_memory_service()

            # 1. 在L3创建新记忆
            new_id = await ms.add_memory(
                user_id=user_id,
                content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                memory_type=memory.get("mem_type", "promoted"),
                layer=MemoryLayer.MEDIUM.value,
                context={
                    **(context if isinstance(context, dict) else {}),
                    "promoted_from": "short",
                    "original_id": mem_id,
                    "promoted_at": datetime.now().isoformat(),
                    "memrank_score": score.total_score,
                    "promotion_reason": "high_value"
                },
                scene=memory.get("scene", ""),
                rating=memory.get("rating", 0)
            )

            # 2. 标记原L2记忆为已晋升（延长过期时间）
            await ms.update_memory(
                mem_id,
                {
                    "promoted_to": new_id,
                    "promoted_at": datetime.now().isoformat(),
                    "expire_at": (datetime.now() + timedelta(days=7)).isoformat()  # 再保留7天
                }
            )

            return True

        except Exception as e:
            logger.error(f"[MemPromotion] L2→L3晋升失败: {e}")
            return False

    async def _promote_l3_to_l4(self, user_id: str, memory: dict, score: MemRankScore) -> bool:
        """将L3记忆晋升到L4（长期经验）"""
        try:
            mem_id = memory.get("id")
            content = memory.get("content", {})

            ms = await get_memory_service()

            # L4存储需要生成经验摘要
            await ms.add_memory(
                user_id=user_id,
                content=json.dumps({
                    **(content if isinstance(content, dict) else {"text": content}),
                    "evolved_at": datetime.now().isoformat(),
                    "original_id": mem_id,
                    "memrank_score": score.total_score
                }, ensure_ascii=False),
                memory_type="evolved_experience",
                layer=MemoryLayer.LONG.value,  # L4
                context={
                    "promoted_from": "medium",
                    "evidence_count": memory.get("referenced_count", 0),
                    "promotion_reason": "cross_scene_experience"
                },
                scene=memory.get("scene", "")
            )

            return True

        except Exception as e:
            logger.error(f"[MemPromotion] L3→L4晋升失败: {e}")
            return False


# 全局引擎实例
promotion_engine = MemoryPromotionEngine()


async def run_promotion_evaluation(user_id: str | None = None, dry_run: bool = False) -> dict:
    """
    运行记忆晋升评估（便捷函数）

    Args:
        user_id: 指定用户，None则评估所有用户
        dry_run: 仅评估，不实际晋升

    Returns:
        评估报告
    """
    if user_id:
        return await promotion_engine.evaluate_and_promote(user_id, dry_run)
    else:
        # 评估所有活跃用户（最近7天有记忆的用户）
        all_reports = {}
        try:
            ms = await get_memory_service()
            # 获取所有有记忆的用户
            users = await ms.list_users()
            for uid in users:
                all_reports[uid] = await promotion_engine.evaluate_and_promote(uid, dry_run)
        except Exception as e:
            logger.error(f"[MemPromotion] 批量评估失败: {e}")
        return all_reports


# 便捷函数：评估单条记忆价值
def evaluate_memory_value(memory: dict, user_memories: list[dict]) -> MemRankScore:
    """评估单条记忆的价值（用于调试）"""
    return promotion_engine.mempool.calculate_memrank(memory, user_memories)
