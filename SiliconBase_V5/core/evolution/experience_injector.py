#!/usr/bin/env python3
"""
经验注入器 V3 - 智能经验注入与效果追踪系统

核心改进：
1. 动态数量调整 - 根据任务复杂度自适应调整经验数量
2. 语义相关性重排序 - 基于嵌入相似度的精准匹配
3. 多样性保证 - 避免相似经验冗余
4. 时效性加权 - 新经验优先
5. 上下文匹配 - 多维度上下文过滤
6. 效果追踪系统 - 闭环经验优化

Author: Agent-6 Experience Optimizer
Version: 3.0.0
"""

import asyncio
import hashlib
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from core.logger import logger

# 【P1-迁移】改用 vector_memory_compat（内部桥接 VectorStore）
from core.memory.vector_memory_compat import vector_memory
from core.safety.moral_module import filter_experiences  # 【Agent-3】导入道德过滤

# 【P3新增】周期性任务注册
try:
    from core.task.background_task_registry import BackgroundTaskRegistry
except ImportError as e:
    logger.warning(f"[ExperienceInjector] BackgroundTaskRegistry 导入失败: {e}")
    BackgroundTaskRegistry = None


@dataclass
class ExperienceUsageRecord:
    """经验使用记录 - 用于效果追踪"""
    exp_id: str
    task_hash: str
    used_at: float
    task_success: bool | None = None
    feedback_score: float | None = None  # 用户反馈 0-10
    effectiveness_score: float | None = None  # 实际效果评分
    resolved_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperienceEffectiveness:
    """经验效果统计"""
    exp_id: str
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    average_feedback: float = 0.0
    last_used: float | None = None
    effectiveness_score: float = 0.5  # 0-1

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def update(self, task_success: bool, feedback_score: float | None = None):
        """更新效果统计"""
        self.usage_count += 1
        self.last_used = time.time()

        if task_success:
            self.success_count += 1
        else:
            self.failure_count += 1

        if feedback_score is not None:
            # 移动平均更新
            self.average_feedback = (
                self.average_feedback * (self.usage_count - 1) + feedback_score
            ) / self.usage_count

        # 综合效果分 = 成功率 * 0.6 + 反馈分 * 0.4
        feedback_normalized = self.average_feedback / 10.0 if self.average_feedback > 0 else 0.5
        self.effectiveness_score = self.success_rate * 0.6 + feedback_normalized * 0.4


@dataclass
class ScoredExperience:
    """带评分的经验条目"""
    exp_id: str
    content: str
    metadata: dict[str, Any]

    # 各维度评分
    relevance_score: float = 0.0  # 相关性 0-1
    recency_score: float = 0.0    # 时效性 0-1
    diversity_score: float = 0.0  # 多样性贡献 0-1
    quality_score: float = 0.0    # 质量评分 0-1
    effectiveness_score: float = 0.0  # 历史效果 0-1

    # 综合评分
    final_score: float = 0.0

    def calculate_final_score(self, weights: dict[str, float] | None = None):
        """计算综合得分"""
        w = weights or {
            'relevance': 0.35,
            'recency': 0.15,
            'diversity': 0.15,
            'quality': 0.20,
            'effectiveness': 0.15
        }
        self.final_score = (
            self.relevance_score * w['relevance'] +
            self.recency_score * w['recency'] +
            self.diversity_score * w['diversity'] +
            self.quality_score * w['quality'] +
            self.effectiveness_score * w['effectiveness']
        )


class ExperienceEffectivenessTracker:
    """
    经验效果追踪器

    功能：
    - 记录经验使用情况
    - 追踪任务成功/失败
    - 统计经验效果
    - 反馈循环优化
    """

    def __init__(self, storage_path: str | None = None):
        self._usage_records: list[ExperienceUsageRecord] = []
        self._effectiveness_cache: dict[str, ExperienceEffectiveness] = {}
        self._task_exp_map: dict[str, list[str]] = defaultdict(list)  # task_hash -> exp_ids
        self._storage_path = storage_path or "data/experience_effectiveness.json"
        self._load_data()

    def track_usage(self, exp_id: str, task: str) -> str:
        """
        记录经验被使用

        Args:
            exp_id: 经验ID
            task: 任务描述

        Returns:
            task_hash: 任务哈希，用于后续更新结果
        """
        task_hash = hashlib.md5(f"{task}:{time.time()}".encode()).hexdigest()[:12]

        record = ExperienceUsageRecord(
            exp_id=exp_id,
            task_hash=task_hash,
            used_at=time.time()
        )
        self._usage_records.append(record)
        self._task_exp_map[task_hash].append(exp_id)

        logger.debug(f"[EffectivenessTracker] 记录使用: exp_id={exp_id}, task_hash={task_hash}")
        return task_hash

    def track_outcome(self, task_hash: str, task_success: bool,
                      feedback_score: float | None = None):
        """
        追踪任务结果

        Args:
            task_hash: 任务哈希（track_usage返回）
            task_success: 任务是否成功
            feedback_score: 用户反馈评分 0-10
        """
        # 找到对应的记录
        for record in self._usage_records:
            if record.task_hash == task_hash and record.task_success is None:
                record.task_success = task_success
                record.feedback_score = feedback_score
                record.resolved_at = time.time()

                # 更新经验效果统计
                for exp_id in self._task_exp_map[task_hash]:
                    self._update_effectiveness(exp_id, task_success, feedback_score)

                logger.info(f"[EffectivenessTracker] 记录结果: task_hash={task_hash}, success={task_success}")
                break

        self._persist_data()

    def _update_effectiveness(self, exp_id: str, task_success: bool,
                              feedback_score: float | None = None):
        """更新经验效果统计"""
        if exp_id not in self._effectiveness_cache:
            self._effectiveness_cache[exp_id] = ExperienceEffectiveness(exp_id=exp_id)

        effectiveness = self._effectiveness_cache[exp_id]
        effectiveness.update(task_success, feedback_score)

    def get_effectiveness(self, exp_id: str) -> ExperienceEffectiveness | None:
        """获取经验效果统计"""
        return self._effectiveness_cache.get(exp_id)

    def get_exp_effectiveness_score(self, exp_id: str) -> float:
        """获取经验效果评分 0-1"""
        eff = self._effectiveness_cache.get(exp_id)
        if eff is None:
            return 0.5  # 默认中性分
        return eff.effectiveness_score

    def get_top_effective_experiences(self, limit: int = 10) -> list[tuple[str, float]]:
        """获取效果最好的经验列表"""
        scored = [
            (exp_id, eff.effectiveness_score)
            for exp_id, eff in self._effectiveness_cache.items()
            if eff.usage_count >= 2  # 至少使用2次才有统计意义
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def get_low_effectiveness_experiences(self, threshold: float = 0.3) -> list[str]:
        """获取低效果的经验ID列表（用于清理）"""
        return [
            exp_id for exp_id, eff in self._effectiveness_cache.items()
            if eff.effectiveness_score < threshold and eff.usage_count >= 3
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取追踪统计信息"""
        total_records = len(self._usage_records)
        resolved_records = [r for r in self._usage_records if r.task_success is not None]

        return {
            "total_usage_records": total_records,
            "resolved_records": len(resolved_records),
            "tracked_experiences": len(self._effectiveness_cache),
            "average_success_rate": sum(
                eff.success_rate for eff in self._effectiveness_cache.values()
            ) / len(self._effectiveness_cache) if self._effectiveness_cache else 0,
            "high_effectiveness_count": sum(
                1 for eff in self._effectiveness_cache.values()
                if eff.effectiveness_score >= 0.7
            )
        }

    def _load_data(self):
        """从文件加载数据"""
        try:
            import os
            if os.path.exists(self._storage_path):
                with open(self._storage_path, encoding='utf-8') as f:
                    data = json.load(f)

                    # 加载效果缓存
                    for exp_id, eff_data in data.get('effectiveness', {}).items():
                        self._effectiveness_cache[exp_id] = ExperienceEffectiveness(**eff_data)

                    # 加载未解决的使用记录并重建 task_exp_map
                    for record_data in data.get('usage_records', []):
                        record = ExperienceUsageRecord(**record_data)
                        self._usage_records.append(record)
                        self._task_exp_map[record.task_hash].append(record.exp_id)

                    logger.info(f"[EffectivenessTracker] 加载了 {len(self._effectiveness_cache)} 条效果记录, {len(self._usage_records)} 条使用记录")
        except Exception as e:
            logger.warning(f"[EffectivenessTracker] 加载数据失败: {e}")

    def _persist_data(self):
        """持久化数据到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)

            # 只持久化未解决的使用记录（已解决的可清理）
            unresolved_records = [r for r in self._usage_records if r.task_success is None]

            data = {
                'effectiveness': {
                    exp_id: asdict(eff)
                    for exp_id, eff in self._effectiveness_cache.items()
                },
                'usage_records': [asdict(r) for r in unresolved_records],
                'updated_at': datetime.now().isoformat()
            }

            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[EffectivenessTracker] 持久化数据失败: {e}")


class RelevanceRanker:
    """
    语义相关性重排序器

    基于多维度语义相似度计算
    """

    def __init__(self):
        self._embedding_cache: dict[str, list[float]] = {}

    def rerank_by_relevance(
        self,
        experiences: list[dict[str, Any]],
        task: str,
        context: dict[str, Any] | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        """
        根据语义相关性重排序经验

        Args:
            experiences: 经验列表
            task: 任务描述
            context: 上下文信息

        Returns:
            List[(经验, 相关性得分)]
        """
        scored = []

        for exp in experiences:
            score = self._calculate_relevance_score(exp, task, context)
            scored.append((exp, score))

        # 按相关性降序
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _calculate_relevance_score(
        self,
        exp: dict[str, Any],
        task: str,
        context: dict[str, Any] | None = None
    ) -> float:
        """
        计算相关性得分 0-1

        多维度计算：
        - 文本相似度 (词汇重叠)
        - 语义相似度 (如有嵌入向量)
        - 任务类型匹配
        - 上下文匹配
        """
        scores = []

        # 1. 文本相似度 (词汇级)
        exp_content = self._extract_exp_text(exp)
        text_sim = self._text_similarity(exp_content, task)
        scores.append(('text', text_sim, 0.4))

        # 2. 语义相似度 (如有向量)
        semantic_sim = self._semantic_similarity(exp, task)
        if semantic_sim > 0:
            scores.append(('semantic', semantic_sim, 0.3))

        # 3. 任务类型匹配
        if context and 'task_type' in context:
            type_match = self._task_type_match(exp, context['task_type'])
            scores.append(('type', type_match, 0.2))

        # 4. 关键词匹配
        keyword_match = self._keyword_match_score(exp, task)
        scores.append(('keyword', keyword_match, 0.1))

        # 加权汇总
        total_weight = sum(w for _, _, w in scores)
        if total_weight == 0:
            return 0.5

        final_score = sum(s * w for _, s, w in scores) / total_weight
        return min(1.0, max(0.0, final_score))

    def _extract_exp_text(self, exp: dict[str, Any]) -> str:
        """提取经验的文本内容"""
        if 'document' in exp:
            return exp['document']
        if 'content' in exp:
            content = exp['content']
            if isinstance(content, str):
                return content
            return content.get('task_desc', '') + ' ' + content.get('result', '')
        return ''

    def _text_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的词汇相似度"""
        if not text1 or not text2:
            return 0.0

        # 分词并转为小写
        words1 = set(self._tokenize(text1.lower()))
        words2 = set(self._tokenize(text2.lower()))

        if not words1 or not words2:
            return 0.0

        # Jaccard相似度
        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    def _tokenize(self, text: str) -> list[str]:
        """简单分词"""
        import re
        # 提取中文字符和英文单词
        chinese = re.findall(r'[\u4e00-\u9fff]', text)
        english = re.findall(r'[a-zA-Z]+', text)
        return chinese + [w.lower() for w in english]

    def _semantic_similarity(self, exp: dict[str, Any], task: str) -> float:
        """计算语义相似度（基于嵌入向量）"""
        # 如果经验包含相似度信息，直接使用
        if 'similarity' in exp:
            return exp['similarity']

        # 否则返回0，表示无法计算
        return 0.0

    def _task_type_match(self, exp: dict[str, Any], task_type: str) -> float:
        """检查经验是否匹配指定任务类型"""
        metadata = exp.get('metadata', {})
        exp_type = metadata.get('task_type', '')

        if not exp_type:
            return 0.5  # 未知类型

        return 1.0 if exp_type == task_type else 0.0

    def _keyword_match_score(self, exp: dict[str, Any], task: str) -> float:
        """关键词匹配得分"""
        # 提取任务关键词
        import re
        keywords = re.findall(r'[\u4e00-\u9fff]{2,}', task)

        if not keywords:
            return 0.5

        exp_text = self._extract_exp_text(exp)
        matched = sum(1 for kw in keywords if kw in exp_text)

        return matched / len(keywords) if keywords else 0.0


class DiversityEnsurer:
    """
    多样性保证器

    避免相似经验重复注入，确保经验覆盖面
    """

    def __init__(self, min_diversity_threshold: float = 0.7):
        self.min_diversity_threshold = min_diversity_threshold

    def ensure_diversity(
        self,
        experiences: list[ScoredExperience],
        max_similar: int = 1
    ) -> list[ScoredExperience]:
        """
        确保经验列表的多样性

        策略：
        1. 基于内容相似度聚类
        2. 每类最多保留max_similar条
        3. 优先保留高评分经验

        Args:
            experiences: 已评分的经验列表
            max_similar: 每类最多保留数量

        Returns:
            多样性过滤后的经验列表
        """
        if not experiences:
            return []

        # 按评分排序
        sorted_exps = sorted(experiences, key=lambda x: x.final_score, reverse=True)

        selected = []
        clusters: dict[str, list[ScoredExperience]] = defaultdict(list)

        for exp in sorted_exps:
            # 确定经验所属类别
            cluster_id = self._get_cluster_id(exp)

            # 检查与已选经验的相似度
            is_diverse = True
            for selected_exp in selected:
                sim = self._calculate_similarity(exp, selected_exp)
                if sim > (1 - self.min_diversity_threshold):
                    is_diverse = False
                    break

            if is_diverse or len(clusters[cluster_id]) < max_similar:
                clusters[cluster_id].append(exp)
                selected.append(exp)
                exp.diversity_score = 1.0 if is_diverse else 0.5
            else:
                exp.diversity_score = 0.1  # 重复类别扣分

        return selected

    @staticmethod
    def _get_cluster_id(exp: ScoredExperience) -> str:
        """根据经验内容确定类别ID"""
        # 基于metadata中的类别信息
        exp_type = exp.metadata.get('task_type', '')
        if exp_type:
            return exp_type

        # 或基于内容关键词
        content = exp.content.lower()

        type_keywords = {
            'file': ['文件', 'file', '读取', '写入', '保存'],
            'code': ['代码', 'code', '函数', '类', '实现'],
            'api': ['api', '接口', '调用', 'http', '请求'],
            'data': ['数据', 'data', '分析', '统计', 'csv'],
            'debug': ['调试', 'debug', '错误', 'bug', '修复'],
        }

        for type_name, keywords in type_keywords.items():
            if any(kw in content for kw in keywords):
                return type_name

        return 'general'

    def _calculate_similarity(self, exp1: ScoredExperience, exp2: ScoredExperience) -> float:
        """计算两个经验的相似度"""
        # 内容相似度
        content_sim = self._text_similarity(exp1.content, exp2.content)

        # 元数据相似度
        meta_sim = 0.0
        if exp1.metadata.get('task_type') == exp2.metadata.get('task_type'):
            meta_sim = 0.3

        # 综合相似度
        return min(1.0, content_sim * 0.7 + meta_sim * 0.3)

    def _text_similarity(self, text1: str, text2: str) -> float:
        """文本相似度"""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0


class RecencyWeighter:
    """
    时效性加权器

    给较新的经验更高权重
    """

    def __init__(self):
        # 时间衰减配置（天数 -> 权重）
        self.decay_curve = {
            7: 1.0,      # 一周内
            30: 0.9,     # 一月内
            90: 0.75,    # 三月内
            180: 0.6,    # 半年内
            365: 0.45,   # 一年内
            float('inf'): 0.3  # 超过一年
        }

    def apply_recency_boost(
        self,
        experiences: list[ScoredExperience]
    ) -> list[ScoredExperience]:
        """
        应用时效性加权

        Args:
            experiences: 经验列表

        Returns:
            更新recency_score后的经验列表
        """
        now = time.time()

        for exp in experiences:
            age_days = self._calculate_age_days(exp.metadata, now)
            exp.recency_score = self._get_recency_weight(age_days)

        return experiences

    def _calculate_age_days(self, metadata: dict[str, Any], now: float) -> float:
        """计算经验年龄（天）"""
        # 尝试多种时间字段
        timestamp_fields = ['timestamp', 'created_at', 'time', 'date']

        for field in timestamp_fields:
            if field in metadata:
                ts = metadata[field]
                try:
                    if isinstance(ts, (int, float)):
                        return (now - ts) / 86400
                    elif isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        return (now - dt.timestamp()) / 86400
                except Exception:
                    continue

        # 默认返回中等年龄
        return 30.0

    def _get_recency_weight(self, age_days: float) -> float:
        """根据年龄获取时效权重"""
        for threshold, weight in sorted(self.decay_curve.items()):
            if age_days <= threshold:
                return weight
        return 0.3


class ContextFilter:
    """
    上下文过滤器

    根据当前上下文过滤不相关的经验
    """

    def __init__(self):
        self.min_context_match = 0.3

    def filter_by_context(
        self,
        experiences: list[ScoredExperience],
        context: dict[str, Any]
    ) -> list[ScoredExperience]:
        """
        根据上下文过滤经验

        过滤维度：
        - 用户ID匹配
        - 任务类型匹配
        - 环境上下文匹配
        - 时间上下文匹配

        Args:
            experiences: 经验列表
            context: 当前上下文

        Returns:
            过滤后的经验列表
        """
        filtered = []

        for exp in experiences:
            match_score = self._calculate_context_match(exp, context)

            if match_score >= self.min_context_match:
                # 上下文匹配度作为质量加成（避免直接修改原始对象，使用独立加分）
                quality_bonus = min(0.1, match_score * 0.1)
                exp.quality_score = min(1.0, exp.quality_score + quality_bonus)
                filtered.append(exp)

        return filtered

    def _calculate_context_match(self, exp: ScoredExperience, context: dict[str, Any]) -> float:
        """计算经验与上下文的匹配度"""
        scores = []

        # 1. 用户匹配
        if 'user_id' in context:
            exp_user = exp.metadata.get('user_id', 'default')
            if exp_user == context['user_id']:
                scores.append(('user', 1.0, 0.2))
            else:
                scores.append(('user', 0.3, 0.2))  # 其他用户的经验也有参考价值

        # 2. 任务类型匹配
        if 'task_type' in context:
            exp_type = exp.metadata.get('task_type', '')
            if exp_type == context['task_type']:
                scores.append(('type', 1.0, 0.3))
            else:
                scores.append(('type', 0.1, 0.3))

        # 3. 工具/技能匹配
        if 'tools' in context:
            exp_tools = exp.metadata.get('tools_used', [])
            if isinstance(exp_tools, str):
                exp_tools = [exp_tools]

            tool_overlap = len(set(exp_tools) & set(context['tools']))
            if tool_overlap > 0:
                match = tool_overlap / max(len(exp_tools), len(context['tools']))
                scores.append(('tools', match, 0.25))

        # 4. 领域匹配
        if 'domain' in context:
            exp_domain = exp.metadata.get('domain', '')
            if exp_domain == context['domain']:
                scores.append(('domain', 1.0, 0.25))

        # 计算加权平均
        if not scores:
            return 0.5  # 默认中等匹配

        total_weight = sum(w for _, _, w in scores)
        weighted_sum = sum(s * w for _, s, w in scores)

        return weighted_sum / total_weight if total_weight > 0 else 0.5


class ExperienceInjectorV3:
    """
    经验注入器 V3 - 智能经验注入与效果追踪

    相比V2的核心改进：
    1. 动态数量调整 - 根据任务复杂度自适应
    2. 语义相关性重排序
    3. 多样性保证
    4. 时效性加权
    5. 上下文匹配
    6. 完整的效果追踪闭环

    Usage:
        injector = ExperienceInjectorV3()

        # 注入经验
        enhanced_prompt, tracking_ids = await injector.inject(
            task="编写Python函数",
            base_prompt="你是一个Python专家...",
            context={"task_type": "code", "user_id": "user123"}
        )

        # 追踪效果
        injector.track_experience_outcome(tracking_ids, task_success=True)
    """

    def __init__(
        self,
        vector_mem=None,
        enable_tracking: bool = True,
        min_quality_threshold: float = 0.5
    ):
        self.vector_mem = vector_mem or vector_memory
        self.enable_tracking = enable_tracking
        self.min_quality_threshold = min_quality_threshold

        # 初始化各模块
        self.relevance_ranker = RelevanceRanker()
        self.diversity_ensurer = DiversityEnsurer()
        self.recency_weighter = RecencyWeighter()
        self.context_filter = ContextFilter()
        self.effectiveness_tracker = ExperienceEffectivenessTracker() if enable_tracking else None

        # 复杂度评估配置
        self.complexity_indicators = {
            'high': ['复杂', 'difficult', 'hard', '多步骤', '集成', '优化', '架构'],
            'medium': ['分析', '比较', '转换', '处理', '生成'],
            'low': ['简单', '查询', '获取', '检查', '查看']
        }

        # 【Fix】后台任务注册表与任务引用，防止协程被 GC 导致 RuntimeWarning
        self._experience_task_registry: Any | None = None
        self._experience_tasks: dict[str, asyncio.Task] = {}

        logger.info("[ExperienceInjectorV3] 初始化完成")

    async def periodic_experience_extraction(
        self,
        user_id: str = "default",
        interval: int = 300,
    ) -> asyncio.Task | None:
        """
        【P3新增】每5分钟自动触发一次经验提取。

        使用 BackgroundTaskRegistry 注册周期任务，不是裸 asyncio.create_task。
        实际提取委托给 Reflector.extract_experiences_from_executions。

        Args:
            user_id: 用户标识
            interval: 周期间隔（秒），默认300秒（5分钟）

        Returns:
            asyncio.Task: 已注册的后台任务对象；注册失败时返回 None
        """
        if BackgroundTaskRegistry is None:
            logger.warning("[ExperienceInjectorV3] BackgroundTaskRegistry 不可用，无法注册周期经验提取")
            return None

        try:
            from core.reflector.reflector import reflector

            async def _extraction_loop():
                """周期执行的经验提取协程"""
                while True:
                    try:
                        # 全局状态检查点
                        from core.feature_manager import AppStatus, feature_manager
                        if feature_manager.get_app_status() != AppStatus.RUNNING:
                            await asyncio.sleep(1)
                            continue

                        await asyncio.sleep(interval)

                        # 【P2-优化】优先级调度：检测是否有用户交互任务在运行
                        # 如果有活跃的用户 AgentLoop，跳过本次后台提取，避免争抢本地模型
                        _has_active_user_task = False
                        try:
                            from core.dialog.dialogue_manager import dialogue_manager
                            # _active_loops 不为空表示有用户任务正在运行
                            if dialogue_manager._active_loops:
                                _has_active_user_task = True
                                logger.info(
                                    f"[ExperienceInjectorV3] 检测到用户任务运行中，"
                                    f"跳过本次经验提取 (active_users={list(dialogue_manager._active_loops.keys())})"
                                )
                        except Exception:
                            pass

                        if _has_active_user_task:
                            continue

                        # 【P3-优化】限制后台单次任务规模，limit=10（已由 Reflector 默认限制）
                        extracted = await reflector.extract_experiences_from_executions(
                            user_id=user_id,
                            limit=10,
                        )
                        if extracted:
                            logger.info(
                                f"[ExperienceInjectorV3] 周期性经验提取完成: "
                                f"{len(extracted)} 条新经验已入库"
                            )
                        else:
                            logger.debug(
                                "[ExperienceInjectorV3] 周期性经验提取: 无新经验"
                            )
                    except asyncio.CancelledError:
                        logger.info("[ExperienceInjectorV3] 周期经验提取任务已取消")
                        break
                    except Exception as e:
                        logger.error(
                            f"[ExperienceInjectorV3] 周期经验提取异常: {e}",
                            exc_info=False,
                        )
                        await asyncio.sleep(interval)

            # 【Fix】使用类级别的 registry 实例，避免每次调用都新建导致任务孤立
            if self._experience_task_registry is None:
                self._experience_task_registry = BackgroundTaskRegistry("experience_injector")

            coro = _extraction_loop()
            try:
                task = await self._experience_task_registry.register(
                    name=f"periodic_experience_extraction_{user_id}",
                    coro=coro,
                )
                self._experience_tasks[user_id] = task
                logger.info(
                    f"[ExperienceInjectorV3] 已注册周期经验提取任务 "
                    f"(user={user_id}, interval={interval}s)"
                )
                return task
            except asyncio.CancelledError:
                coro.close()
                logger.debug("[ExperienceInjectorV3] 周期经验提取注册被取消，协程已清理")
                raise
            except Exception:
                # 【Fix】任何注册异常都必须关闭协程对象，避免 RuntimeWarning
                coro.close()
                raise

        except Exception as e:
            logger.error(
                f"[ExperienceInjectorV3] 注册周期经验提取失败: {e}",
                exc_info=False,
            )
            return None

    async def inject(
        self,
        task: str,
        base_prompt: str,
        context: dict[str, Any] | None = None,
        user_id: str = "default"
    ) -> tuple[str, list[str]]:
        """
        注入经验到提示词

        Args:
            task: 任务描述
            base_prompt: 基础提示词
            context: 上下文信息（task_type, user_id, domain等）
            user_id: 用户ID

        Returns:
            (enhanced_prompt, tracking_ids)
            - enhanced_prompt: 增强后的提示词
            - tracking_ids: 用于效果追踪的ID列表
        """
        try:
            # 1. 评估任务复杂度
            complexity = self._assess_complexity(task)
            success_count = self._calculate_exp_count(complexity)

            # 2. 检索经验
            experiences = await self._search_experiences(task, user_id, limit=success_count * 3)

            if not experiences:
                logger.info("[ExperienceInjectorV3] 未找到相关经验")
                return base_prompt, []

            # 3. 转换为评分经验对象
            scored_exps = self._convert_to_scored_experiences(experiences)

            # 4. 相关性重排序
            scored_exps = self._apply_relevance_ranking(scored_exps, task, context)

            # 5. 时效性加权
            scored_exps = self.recency_weighter.apply_recency_boost(scored_exps)

            # 6. 上下文过滤
            if context:
                scored_exps = self.context_filter.filter_by_context(scored_exps, context)

            # 7. 多样性保证
            scored_exps = self.diversity_ensurer.ensure_diversity(scored_exps)

            # 8. 计算最终评分并排序
            for exp in scored_exps:
                exp.calculate_final_score()
            scored_exps.sort(key=lambda x: x.final_score, reverse=True)

            # 9. 选择前N条
            selected = scored_exps[:success_count]

            # 10. 记录使用（用于效果追踪）
            tracking_ids = []
            if self.effectiveness_tracker:
                for exp in selected:
                    task_hash = self.effectiveness_tracker.track_usage(exp.exp_id, task)
                    tracking_ids.append(task_hash)

            # 11. 格式化输出
            experience_text = self._format_experiences(selected, task, complexity)
            enhanced_prompt = base_prompt + "\n\n" + experience_text

            logger.info(
                f"[ExperienceInjectorV3] 注入 {len(selected)} 条经验 "
                f"(复杂度:{complexity}, 任务:{task[:30]}...)"
            )

            return enhanced_prompt, tracking_ids

        except Exception as e:
            logger.error(f"[ExperienceInjectorV3] 经验注入失败: {e}")
            return base_prompt, []

    async def inject_experience(self, task_description: str, base_prompt: str) -> str:
        """
        向后兼容：将经验注入到基础提示词中

        Args:
            task_description: 当前任务描述
            base_prompt: 原始系统提示词

        Returns:
            注入经验后的完整提示词
        """
        enhanced_prompt, _ = await self.inject(
            task=task_description,
            base_prompt=base_prompt,
            context=None,
            user_id="default"
        )
        return enhanced_prompt

    def _assess_complexity(self, task: str) -> int:
        """
        评估任务复杂度 1-5

        基于：
        - 关键词分析
        - 任务长度
        - 结构复杂度
        """
        task_lower = task.lower()
        complexity_score = 2  # 默认中等复杂度

        # 关键词分析
        for indicator in self.complexity_indicators['high']:
            if indicator in task_lower:
                complexity_score += 2

        for indicator in self.complexity_indicators['medium']:
            if indicator in task_lower:
                complexity_score += 1

        # 长度因子
        task_len = len(task)
        if task_len > 200:
            complexity_score += 1
        elif task_len < 30:
            complexity_score -= 1

        # 结构复杂度（逗号、步骤数等）
        step_indicators = ['步骤', '首先', '然后', '接着', '最后', '第一步']
        step_count = sum(1 for ind in step_indicators if ind in task)
        complexity_score += step_count // 2

        return min(5, max(1, complexity_score))

    def _calculate_exp_count(self, complexity: int) -> int:
        """根据复杂度计算经验数量 2-5"""
        # 复杂度1-2: 2条
        # 复杂度3: 3条
        # 复杂度4: 4条
        # 复杂度5: 5条
        return min(5, max(2, complexity))

    async def _search_experiences(
        self,
        task: str,
        user_id: str,
        limit: int = 15
    ) -> list[dict[str, Any]]:
        """检索相关经验"""
        try:
            # 搜索成功经验
            success_exps = await self.vector_mem.search_experience(
                task_desc=task,
                user_id=user_id,
                only_success=True,
                limit=limit
            )

            # 搜索失败经验（用于避坑）
            failure_exps = await self.vector_mem.search_experience(
                task_desc=task,
                user_id=user_id,
                only_success=False,
                limit=min(5, limit // 2)
            )

            # 过滤出真正的失败经验
            failure_exps = [
                exp for exp in failure_exps
                if not self._is_success_exp(exp)
            ]

            # 合并（成功经验优先）
            all_exps = success_exps + failure_exps[:2]

            return all_exps

        except Exception as e:
            logger.error(f"[ExperienceInjectorV3] 搜索经验失败: {e}")
            return []

    def _is_success_exp(self, exp: dict[str, Any]) -> bool:
        """判断是否为成功经验"""
        metadata = exp.get('metadata', {})
        success = metadata.get('success', True)
        success = success.lower() == 'true' if isinstance(success, str) else bool(success)
        return success

    def _convert_to_scored_experiences(
        self,
        experiences: list[dict[str, Any]]
    ) -> list[ScoredExperience]:
        """转换为评分经验对象"""
        scored_list = []

        for exp in experiences:
            exp_id = exp.get('id', '')
            content = exp.get('document', '') or exp.get('content', '')
            metadata = exp.get('metadata', {})

            # 基础质量分
            quality = metadata.get('quality_score', 0.5)
            if isinstance(quality, str):
                try:
                    quality = float(quality)
                except Exception:
                    quality = 0.5

            # 效果分
            effectiveness = 0.5
            if self.effectiveness_tracker:
                effectiveness = self.effectiveness_tracker.get_exp_effectiveness_score(exp_id)

            scored = ScoredExperience(
                exp_id=exp_id,
                content=content,
                metadata=metadata,
                quality_score=quality,
                effectiveness_score=effectiveness
            )
            scored_list.append(scored)

        return scored_list

    def _apply_relevance_ranking(
        self,
        experiences: list[ScoredExperience],
        task: str,
        context: dict[str, Any] | None
    ) -> list[ScoredExperience]:
        """应用相关性重排序"""
        # 准备原始经验格式
        raw_exps = [
            {
                'id': exp.exp_id,
                'document': exp.content,
                'metadata': exp.metadata
            }
            for exp in experiences
        ]

        # 相关性排序
        ranked = self.relevance_ranker.rerank_by_relevance(raw_exps, task, context)

        # 更新经验的相关性得分
        exp_map = {exp.exp_id: exp for exp in experiences}
        for raw_exp, score in ranked:
            exp_id = raw_exp['id']
            if exp_id in exp_map:
                exp_map[exp_id].relevance_score = score

        return experiences

    def _format_experiences(
        self,
        experiences: list[ScoredExperience],
        task: str,
        complexity: int
    ) -> str:
        """格式化经验为提示词文本"""
        lines = ["【历史经验参考】"]

        success_exps = [e for e in experiences if self._is_success_exp({'metadata': e.metadata})]
        failure_exps = [e for e in experiences if not self._is_success_exp({'metadata': e.metadata})]

        # 成功经验
        if success_exps:
            for i, exp in enumerate(success_exps, 1):
                parsed = self._parse_experience_content(exp.content)
                lines.append(f"[成功{i}] {parsed.get('task', '未知任务')[:80]}")
                steps = parsed.get('steps', '')
                if steps:
                    lines.append(f"  步骤: {steps[:100]}{'...' if len(steps) > 100 else ''}")

        # 失败教训
        if failure_exps:
            for i, exp in enumerate(failure_exps, 1):
                parsed = self._parse_experience_content(exp.content)
                lines.append(f"[教训{i}] {parsed.get('task', '未知任务')[:60]}")
                result = parsed.get('result', '')
                if result:
                    lines.append(f"  错误: {result[:80]}")

        return "\n".join(lines)

    def _parse_experience_content(self, content: str) -> dict[str, str]:
        """解析经验内容"""
        result = {"task": "", "steps": "", "result": ""}

        try:
            # 尝试解析 [Task]xxx | [Steps]yyy | [Result]zzz 格式
            parts = content.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("[Task]"):
                    result["task"] = part[6:].strip()
                elif part.startswith("[Steps]"):
                    result["steps"] = part[7:].strip()
                elif part.startswith("[Result]"):
                    result["result"] = part[8:].strip()

            # 如果没解析到，使用整个内容作为任务
            if not result["task"]:
                result["task"] = content[:200]

        except Exception:
            result["task"] = content[:200]

        return result

    def track_experience_outcome(
        self,
        tracking_ids: list[str],
        task_success: bool,
        feedback_score: float | None = None
    ):
        """
        追踪经验使用后的效果

        Args:
            tracking_ids: inject返回的追踪ID列表
            task_success: 任务是否成功
            feedback_score: 用户反馈评分 0-10
        """
        if not self.effectiveness_tracker or not tracking_ids:
            return

        for task_hash in tracking_ids:
            self.effectiveness_tracker.track_outcome(task_hash, task_success, feedback_score)

        logger.info(f"[ExperienceInjectorV3] 记录 {len(tracking_ids)} 条经验效果: success={task_success}")

    def get_effectiveness_report(self) -> dict[str, Any]:
        """获取效果追踪报告"""
        if not self.effectiveness_tracker:
            return {"error": "效果追踪未启用"}

        return self.effectiveness_tracker.get_stats()

    def get_injection_stats(self) -> dict[str, Any]:
        """获取注入器统计信息"""
        stats = {
            "version": "3.0.0",
            "modules": {
                "relevance_ranker": True,
                "diversity_ensurer": True,
                "recency_weighter": True,
                "context_filter": True,
                "effectiveness_tracker": self.enable_tracking
            }
        }

        if self.effectiveness_tracker:
            stats["effectiveness"] = self.effectiveness_tracker.get_stats()

        return stats

    def record_tool_experience(
        self,
        user_id: str,
        tool_name: str,
        success: bool,
        execution_time_ms: int
    ) -> int:
        """
        记录工具执行经验

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            success: 是否执行成功
            execution_time_ms: 执行时间（毫秒）

        Returns:
            获得的经验值
        """
        try:
            # 基础经验值
            base_xp = 10

            # 成功奖励
            success_bonus = 5 if success else 0

            # 效率奖励（执行快有额外奖励）
            speed_bonus = 5 if execution_time_ms < 1000 else 0

            total_xp = base_xp + success_bonus + speed_bonus

            logger.info(f"[ExperienceInjectorV3] 记录工具经验: {tool_name}, success={success}, XP={total_xp}")

            return total_xp
        except Exception as e:
            logger.error(f"[ExperienceInjectorV3] 记录工具经验失败: {e}")
            return 0


# =============================================================================
# 便捷函数和全局实例
# =============================================================================

def track_experience_usage(exp_id: str, task_success: bool):
    """
    追踪经验被使用后的效果（便捷函数）

    Args:
        exp_id: 经验ID
        task_success: 任务是否成功
    """
    tracker = ExperienceEffectivenessTracker()
    task_hash = tracker.track_usage(exp_id, f"manual_track_{exp_id}")
    tracker.track_outcome(task_hash, task_success)


# 全局V3实例
_experience_injector_v3: ExperienceInjectorV3 | None = None


def get_experience_injector_v3(
    vector_mem=None,
    enable_tracking: bool = True,
    refresh: bool = False
) -> ExperienceInjectorV3:
    """
    获取ExperienceInjectorV3全局实例

    Args:
        vector_mem: 向量内存实例
        enable_tracking: 是否启用效果追踪
        refresh: 是否强制刷新实例

    Returns:
        ExperienceInjectorV3实例
    """
    global _experience_injector_v3
    if _experience_injector_v3 is None or refresh:
        _experience_injector_v3 = ExperienceInjectorV3(
            vector_mem=vector_mem,
            enable_tracking=enable_tracking
        )
    return _experience_injector_v3


async def inject_experience_to_prompt(task: str, base_prompt: str) -> str:
    """
    便捷函数：将经验注入提示词（使用V1版本）

    Args:
        task: 任务描述
        base_prompt: 基础提示词

    Returns:
        注入经验后的完整提示词
    """
    return await experience_injector.inject_experience(task, base_prompt)


async def inject_experience_v3(
    task: str,
    base_prompt: str,
    context: dict[str, Any] | None = None,
    user_id: str = "default"
) -> tuple[str, list[str]]:
    """
    便捷函数：使用V3注入经验

    Args:
        task: 任务描述
        base_prompt: 基础提示词
        context: 上下文信息
        user_id: 用户ID

    Returns:
        (enhanced_prompt, tracking_ids)
    """
    injector = get_experience_injector_v3()
    return await injector.inject(task, base_prompt, context, user_id)


# =============================================================================
# 原有ExperienceInjector类（保留向后兼容）
# =============================================================================

class ExperienceInjector:
    """
    经验注入器 V1 - 基础实现（贝叶斯增强版）

    作用：在AI执行任务前，将相关历史经验（成功/失败）
          格式化为提示词的一部分，引导AI参考历史经验做决策

    【增强】集成Reflector信念引擎，使用贝叶斯加权排序
    """

    def __init__(self, max_success: int = 3, max_failure: int = 2):
        """
        初始化经验注入器

        Args:
            max_success: 最多注入的成功经验数量，默认3条
            max_failure: 最多注入的失败教训数量，默认2条
        """
        self.max_success = max_success
        self.max_failure = max_failure

        # 【新增】引用Reflector的信念引擎（通过单例）
        from core.reflector import reflector
        self.reflector = reflector

        self.success_template = """【成功经验 #{idx}】
任务类型: {pattern}
执行步骤: {steps}
结果: {result}
建议: 以上方法曾经成功，可优先考虑采用相同步骤。"""

        self.failure_template = """【失败教训 #{idx}】
任务类型: {pattern}
失败原因: {error}
建议: 避免以上错误做法，尝试其他方法。"""

        self.no_experience_msg = ""  # 空字符串表示不注入任何内容

    async def inject_experience(self, task_description: str, base_prompt: str) -> str:
        """
        将经验注入到基础提示词中

        Args:
            task_description: 当前任务描述
            base_prompt: 原始系统提示词

        Returns:
            注入经验后的完整提示词
        """
        try:
            experiences = await self._retrieve_experiences(task_description)

            if not experiences["success"] and not experiences["failure"]:
                return base_prompt

            experience_text = self._format_experiences(experiences)
            full_prompt = base_prompt + "\n\n" + experience_text

            logger.info(f"[ExperienceInjector] 注入{len(experiences['success'])}条成功,{len(experiences['failure'])}条失败经验")
            return full_prompt

        except Exception as e:
            logger.error(f"[ExperienceInjector] 经验注入失败: {e}")
            return base_prompt

    def _is_success_exp(self, exp: dict) -> bool:
        """判断是否为成功经验"""
        metadata = exp.get("metadata", {})
        success = metadata.get("success", True)
        if isinstance(success, str):
            success = success.lower() == "true"
        return success

    async def _retrieve_experiences(self, task: str) -> dict[str, list[dict]]:
        """
        检索与任务相关的历史经验

        Args:
            task: 任务描述字符串

        Returns:
            包含成功经验和失败教训的字典
        """
        result = {"success": [], "failure": []}

        try:
            success_exps = await vector_memory.search_experience(
                task_desc=task,
                only_success=True,
                limit=self.max_success
            )
            result["success"] = success_exps

            all_exps = await vector_memory.search_experience(
                task_desc=task,
                only_success=False,
                limit=self.max_success + self.max_failure
            )

            for exp in all_exps:
                metadata = exp.get("metadata", {})
                is_success = metadata.get("success")
                if isinstance(is_success, str):
                    is_success = is_success.lower() == "true"

                if not is_success and len(result["failure"]) < self.max_failure:
                    result["failure"].append(exp)

            # 【Agent-3】道德过滤：过滤掉不道德的经验（测试阶段可配置）
            from core.config import config
            moral_filter_enabled = config.get("moral_filter.enabled", True)
            strict_mode = config.get("moral_filter.strict_mode", False)
            filter_success = config.get("moral_filter.filter_success_exp", False)
            filter_failure = config.get("moral_filter.filter_failure_exp", True)

            if moral_filter_enabled:
                original_success_count = len(result["success"])
                original_failure_count = len(result["failure"])

                # 测试阶段：成功经验不过滤（除非strict_mode开启）
                if strict_mode or filter_success:
                    result["success"] = filter_experiences(result["success"])

                # 失败经验默认过滤（防止AI学习错误行为）
                if filter_failure:
                    result["failure"] = filter_experiences(result["failure"])

                filtered_count = (original_success_count - len(result["success"]) +
                                original_failure_count - len(result["failure"]))
                if filtered_count > 0:
                    logger.info(f"[ExperienceInjector] [MoralFilter] 过滤了 {filtered_count} 条不道德经验 "
                              f"(严格模式:{strict_mode}, 过滤成功:{filter_success}, 过滤失败:{filter_failure})")
            else:
                logger.debug("[ExperienceInjector] [MoralFilter] 道德过滤已禁用")

        except Exception as e:
            logger.error(f"[ExperienceInjector] 检索经验失败: {e}")

        return result

    def _format_experiences(self, experiences: dict[str, list[dict]]) -> str:
        """
        将经验格式化为可供AI阅读的文本

        Args:
            experiences: 包含成功和失败经验的字典

        Returns:
            格式化后的经验文本
        """
        lines = ["【历史经验参考】"]

        for i, exp in enumerate(experiences["success"], 1):
            doc = exp.get("document", "")
            parsed = self._parse_experience_document(doc)
            lines.append(f"[成功{i}] {parsed.get('pattern', '未知任务')[:80]}")
            steps = parsed.get("steps", "")
            if steps:
                lines.append(f"  步骤: {steps[:100]}")

        if experiences["failure"]:
            for i, exp in enumerate(experiences["failure"], 1):
                doc = exp.get("document", "")
                parsed = self._parse_experience_document(doc)
                error = parsed.get("result", "未知错误")
                if "失败:" in error:
                    error = error.split("失败:")[1]
                lines.append(f"[教训{i}] {parsed.get('pattern', '未知任务')[:60]} - 错误: {error[:80]}")

        return "\n".join(lines)

    def _parse_experience_document(self, doc: str) -> dict[str, str]:
        """
        解析经验文档字符串为结构化数据

        格式: [Task]xxx | [Steps]yyy | [Result]zzz

        Args:
            doc: 经验文档字符串

        Returns:
            包含pattern、steps、result的字典
        """
        result = {
            "pattern": "",
            "steps": "",
            "result": ""
        }

        try:
            parts = doc.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("[Task]"):
                    result["pattern"] = part[6:].strip()
                elif part.startswith("[Steps]"):
                    result["steps"] = part[7:].strip()
                elif part.startswith("[Result]"):
                    result["result"] = part[8:].strip()
        except Exception:
            result["pattern"] = doc[:100]

        return result

    async def get_experience_stats(self) -> dict:
        """
        获取经验库统计信息

        Returns:
            包含成功经验数、失败教训数、总数的字典
        """
        try:
            all_success = await vector_memory.search_experience("", only_success=True, limit=1000)
            all_failure = await vector_memory.search_experience("", only_success=False, limit=1000)

            failure_count = sum(1 for exp in all_failure if not self._is_success_exp(exp))

            return {
                "success_count": len(all_success),
                "failure_count": failure_count,
                "total": len(all_success) + failure_count
            }
        except Exception as e:
            logger.error(f"[ExperienceInjector] 获取统计失败: {e}")
            return {"success_count": 0, "failure_count": 0, "total": 0}

    def record_tool_experience(
        self,
        user_id: str,
        tool_name: str,
        success: bool,
        execution_time_ms: int
    ) -> int:
        """
        记录工具执行经验

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            success: 是否执行成功
            execution_time_ms: 执行时间（毫秒）

        Returns:
            获得的经验值
        """
        try:
            # 基础经验值
            base_xp = 10

            # 成功奖励
            success_bonus = 5 if success else 0

            # 效率奖励（执行快有额外奖励）
            speed_bonus = 5 if execution_time_ms < 1000 else 0

            total_xp = base_xp + success_bonus + speed_bonus

            logger.info(f"[ExperienceInjectorV3] 记录工具经验: {tool_name}, success={success}, XP={total_xp}")

            return total_xp
        except Exception as e:
            logger.error(f"[ExperienceInjectorV3] 记录工具经验失败: {e}")
            return 0


# 向后兼容：保留原有的ExperienceInjector实例（必须在类定义之后）
experience_injector = ExperienceInjector()
