#!/usr/bin/env python3
"""
信念引擎 - 管理所有策略的贝叶斯信念状态

核心职责:
1. 维护策略信念集合
2. 执行贝叶斯更新
3. 提供策略选择算法（Thompson/UCB）
4. 与向量记忆集成（持久化）
5. 提供信念分析工具

Author: Agent-Bayesian
Version: 1.0.0
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.logger import logger

from .belief_strategy import BeliefStrategyPattern, StrategyStatus


@dataclass
class SelectionResult:
    """策略选择结果"""
    pattern_id: str
    pattern: BeliefStrategyPattern
    selection_method: str  # "thompson", "ucb", "greedy", "random"
    score: float  # 选择时的评分
    alternatives: list[tuple[str, float]]  # 其他候选及其分数


@dataclass
class BeliefStats:
    """信念统计信息"""
    total_patterns: int
    active_patterns: int
    experimental_patterns: int
    deprecated_patterns: int
    total_evidence: float
    average_uncertainty: float
    top_performing: list[tuple[str, float]]  # (pattern_id, success_prob)
    needs_exploration: list[str]  # 需要更多试验的策略ID


class BeliefEngine:
    """
    信念引擎 - 贝叶斯反思系统的核心

    Usage:
        engine = BeliefEngine()

        # 更新策略信念
        engine.update_strategy("pattern_1", success=True, confidence=0.9)

        # 选择策略
        selected = engine.select_strategy_thompson(["pattern_1", "pattern_2"])

        # 分析信念状态
        stats = engine.get_stats()
    """

    # 配置常量
    DEFAULT_EXPLORATION_FACTOR = 1.414  # √2，UCB理论最优
    MIN_CONFIDENCE = 0.1  # 最小证据置信度
    MAX_CONFIDENCE = 1.0  # 最大证据置信度

    def __init__(self, vector_mem=None, auto_save: bool = True):
        """
        初始化信念引擎

        Args:
            vector_mem: 向量内存实例（用于持久化）
            auto_save: 是否自动保存更新
        """
        self.beliefs: dict[str, BeliefStrategyPattern] = {}
        self.vector_mem = vector_mem
        self.auto_save = auto_save

        # 选择策略配置
        self.exploration_factor = self.DEFAULT_EXPLORATION_FACTOR
        self.selection_history: list[dict] = []  # 选择历史（用于分析）

        # 从向量记忆加载已有策略
        if vector_mem:
            self._load_from_vector_memory()

        logger.info(f"[BeliefEngine] 初始化完成，加载了 {len(self.beliefs)} 个策略信念")

    # ========== 核心CRUD操作 ==========

    def register_strategy(self, pattern: BeliefStrategyPattern) -> bool:
        """
        注册新策略

        Args:
            pattern: 策略模式实例

        Returns:
            是否成功注册
        """
        if pattern.pattern_id in self.beliefs:
            logger.warning(f"[BeliefEngine] 策略 {pattern.pattern_id} 已存在，跳过注册")
            return False

        self.beliefs[pattern.pattern_id] = pattern

        if self.auto_save:
            self._save_to_vector_memory(pattern.pattern_id)

        logger.info(f"[BeliefEngine] 注册新策略: {pattern.pattern_id}")
        return True

    def get_strategy(self, pattern_id: str) -> BeliefStrategyPattern | None:
        """获取策略信念"""
        return self.beliefs.get(pattern_id)

    def update_strategy(self, pattern_id: str, success: bool,
                       confidence: float = 1.0,
                       context: dict | None = None) -> bool:
        """
        更新策略信念（核心方法）

        这是贝叶斯学习的入口点：根据执行结果更新策略成功率的后验分布

        Args:
            pattern_id: 策略ID
            success: 是否成功
            confidence: 证据置信度 (0-1)
            context: 上下文信息

        Returns:
            是否成功更新
        """
        # 确保置信度在有效范围
        confidence = max(self.MIN_CONFIDENCE, min(self.MAX_CONFIDENCE, confidence))

        if pattern_id not in self.beliefs:
            # 策略不存在，创建新的（均匀先验）
            logger.warning(f"[BeliefEngine] 策略 {pattern_id} 不存在，创建新信念")
            pattern = BeliefStrategyPattern(
                pattern_id=pattern_id,
                name=context.get('name', pattern_id) if context else pattern_id,
                description=context.get('description', '') if context else '',
                applicable_scenarios=context.get('scenarios', []) if context else [],
                strategy_steps=context.get('steps', []) if context else []
            )
            self.beliefs[pattern_id] = pattern

        pattern = self.beliefs[pattern_id]

        # 执行贝叶斯更新
        pattern.update_with_evidence(success, confidence, context)
        pattern.mark_used()
        pattern.update_status()

        # 保存到向量记忆
        if self.auto_save:
            self._save_to_vector_memory(pattern_id)

        logger.debug(f"[BeliefEngine] 更新 {pattern_id}: success={success}, "
                    f"confidence={confidence:.2f}, new_prob={pattern.get_success_probability():.2%}")

        return True

    def batch_update(self, updates: list[tuple[str, bool, float]]):
        """
        批量更新（用于历史数据导入）

        Args:
            updates: [(pattern_id, success, confidence), ...]
        """
        for pattern_id, success, confidence in updates:
            self.update_strategy(pattern_id, success, confidence)

        logger.info(f"[BeliefEngine] 批量更新完成: {len(updates)} 条记录")

    # ========== 策略选择算法 ==========

    def select_strategy_thompson(self, candidates: list[str],
                                  context: dict | None = None) -> SelectionResult | None:
        """
        Thompson采样选择策略

        原理: 从每个候选策略的Beta分布中采样，选择采样值最高的

        优势:
        - 天然平衡探索和利用
        - 不确定性高的策略有更多探索机会
        - 概率最优（最小化后悔）

        适用场景:
        - 在线学习（需要持续探索）
        - 策略效果可能随时间变化
        - 对探索成本不敏感

        Args:
            candidates: 候选策略ID列表
            context: 选择上下文（用于记录）

        Returns:
            SelectionResult或None
        """
        if not candidates:
            return None

        valid_candidates = []
        samples = []

        for pattern_id in candidates:
            if pattern_id in self.beliefs:
                belief = self.beliefs[pattern_id]
                # 跳过已废弃的策略
                if belief.status == StrategyStatus.DEPRECATED:
                    continue
                valid_candidates.append(pattern_id)
                samples.append((pattern_id, belief.thompson_sample()))

        if not samples:
            return None

        # 选择采样值最高的
        samples.sort(key=lambda x: x[1], reverse=True)
        selected_id, selected_score = samples[0]

        # 记录选择
        result = SelectionResult(
            pattern_id=selected_id,
            pattern=self.beliefs[selected_id],
            selection_method="thompson",
            score=selected_score,
            alternatives=samples[1:]
        )

        self._record_selection(result, context)
        return result

    def select_strategy_ucb(self, candidates: list[str],
                           exploration_factor: float | None = None,
                           context: dict | None = None) -> SelectionResult | None:
        """
        UCB (Upper Confidence Bound) 选择策略

        原理: score = mean + exploration * sqrt(2*ln(total_trials)/n_i)

        优势:
        - 有理论保证的后悔界
        - 确定性的（可复现）
        - 明确的探索参数

        适用场景:
        - 需要确定性选择
        - 探索有成本（想尽快收敛到最优）
        - A/B测试

        Args:
            candidates: 候选策略ID列表
            exploration_factor: 探索因子（默认√2）
            context: 选择上下文

        Returns:
            SelectionResult或None
        """
        if not candidates:
            return None

        exploration = exploration_factor or self.exploration_factor

        # 计算总试验次数
        total_trials = sum(
            self.beliefs[pid].get_effective_sample_size()
            for pid in candidates if pid in self.beliefs
        )

        valid_candidates = []
        scores = []

        for pattern_id in candidates:
            if pattern_id not in self.beliefs:
                continue
            belief = self.beliefs[pattern_id]
            if belief.status == StrategyStatus.DEPRECATED:
                continue

            score = belief.get_ucb_score(max(1, total_trials), exploration)
            valid_candidates.append(pattern_id)
            scores.append((pattern_id, score))

        if not scores:
            return None

        # 选择UCB分数最高的
        scores.sort(key=lambda x: x[1], reverse=True)
        selected_id, selected_score = scores[0]

        result = SelectionResult(
            pattern_id=selected_id,
            pattern=self.beliefs[selected_id],
            selection_method="ucb",
            score=selected_score,
            alternatives=scores[1:]
        )

        self._record_selection(result, context)
        return result

    def select_strategy_greedy(self, candidates: list[str],
                               context: dict | None = None) -> SelectionResult | None:
        """
        贪心选择（纯利用）

        选择当前成功率期望最高的策略

        适用场景:
        - 探索阶段已结束
        - 需要最大化短期收益
        - 生产环境（稳定优先）
        """
        if not candidates:
            return None

        scores = []
        for pattern_id in candidates:
            if pattern_id in self.beliefs:
                belief = self.beliefs[pattern_id]
                if belief.status != StrategyStatus.DEPRECATED:
                    scores.append((pattern_id, belief.get_success_probability()))

        if not scores:
            return None

        scores.sort(key=lambda x: x[1], reverse=True)
        selected_id, selected_score = scores[0]

        result = SelectionResult(
            pattern_id=selected_id,
            pattern=self.beliefs[selected_id],
            selection_method="greedy",
            score=selected_score,
            alternatives=scores[1:]
        )

        self._record_selection(result, context)
        return result

    def select_strategy(self, candidates: list[str],
                       method: str = "thompson",
                       context: dict | None = None) -> SelectionResult | None:
        """
        通用策略选择接口

        Args:
            candidates: 候选策略ID列表
            method: 选择方法 ("thompson", "ucb", "greedy", "random")
            context: 选择上下文
        """
        selectors = {
            "thompson": self.select_strategy_thompson,
            "ucb": self.select_strategy_ucb,
            "greedy": self.select_strategy_greedy,
        }

        selector = selectors.get(method, self.select_strategy_thompson)
        return selector(candidates, context=context)

    # ========== 批量操作 ==========

    def rank_strategies(self, candidates: list[str],
                       by: str = "success_prob") -> list[tuple[str, float]]:
        """
        对候选策略排序

        Args:
            candidates: 候选策略ID列表
            by: 排序依据 ("success_prob", "ucb", "uncertainty")

        Returns:
            [(pattern_id, score), ...] 按分数降序
        """
        scores = []

        for pattern_id in candidates:
            if pattern_id not in self.beliefs:
                continue

            belief = self.beliefs[pattern_id]

            if by == "success_prob":
                score = belief.get_success_probability()
            elif by == "ucb":
                total_trials = sum(
                    self.beliefs.get(pid, BeliefStrategyPattern(pid, "")).get_effective_sample_size()
                    for pid in candidates
                )
                score = belief.get_ucb_score(max(1, total_trials))
            elif by == "uncertainty":
                score = -belief.get_uncertainty()  # 负的，因为不确定性越小越好
            else:
                score = belief.get_success_probability()

            scores.append((pattern_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def get_active_strategies(self, min_samples: int = 0) -> list[BeliefStrategyPattern]:
        """
        获取活跃策略列表

        Args:
            min_samples: 最小样本数过滤
        """
        return [
            belief for belief in self.beliefs.values()
            if belief.status in [StrategyStatus.ACTIVE, StrategyStatus.EXPERIMENTAL]
            and belief.get_effective_sample_size() >= min_samples
        ]

    # ========== 分析和统计 ==========

    def get_stats(self) -> BeliefStats:
        """获取信念系统统计信息"""
        total_patterns = len(self.beliefs)

        status_counts = defaultdict(int)
        total_evidence = 0.0
        uncertainties = []

        for belief in self.beliefs.values():
            status_counts[belief.status] += 1
            total_evidence += belief.get_effective_sample_size()
            uncertainties.append(belief.get_uncertainty())

        # 获取表现最佳的策略
        ranked = self.rank_strategies(
            list(self.beliefs.keys()),
            by="success_prob"
        )[:5]

        # 需要更多探索的策略（试验次数少或不确定性高）
        needs_exploration = [
            pid for pid, belief in self.beliefs.items()
            if belief.get_effective_sample_size() < 5
            or belief.get_uncertainty() > 0.5
        ]

        return BeliefStats(
            total_patterns=total_patterns,
            active_patterns=status_counts[StrategyStatus.ACTIVE],
            experimental_patterns=status_counts[StrategyStatus.EXPERIMENTAL],
            deprecated_patterns=status_counts[StrategyStatus.DEPRECATED],
            total_evidence=total_evidence,
            average_uncertainty=sum(uncertainties) / len(uncertainties) if uncertainties else 0,
            top_performing=ranked,
            needs_exploration=needs_exploration
        )

    def compare_strategies(self, pattern_id1: str,
                          pattern_id2: str) -> dict[str, Any]:
        """
        比较两个策略

        Returns:
            比较结果字典
        """
        if pattern_id1 not in self.beliefs or pattern_id2 not in self.beliefs:
            return {"error": "One or both patterns not found"}

        b1, b2 = self.beliefs[pattern_id1], self.beliefs[pattern_id2]

        # 计算B是否显著优于A
        b1_significantly_better = b1.is_significantly_better_than(b2)
        b2_significantly_better = b2.is_significantly_better_than(b1)

        return {
            "pattern_1": {
                "id": pattern_id1,
                "success_prob": b1.get_success_probability(),
                "confidence_interval": b1.get_confidence_interval(),
                "samples": b1.get_effective_sample_size()
            },
            "pattern_2": {
                "id": pattern_id2,
                "success_prob": b2.get_success_probability(),
                "confidence_interval": b2.get_confidence_interval(),
                "samples": b2.get_effective_sample_size()
            },
            "comparison": {
                "prob_difference": b1.get_success_probability() - b2.get_success_probability(),
                "significantly_better": pattern_id1 if b1_significantly_better else (
                    pattern_id2 if b2_significantly_better else None
                )
            }
        }

    # ========== 持久化 ==========

    def _load_from_vector_memory(self):
        """从向量记忆加载策略信念"""
        if not self.vector_mem:
            return

        try:
            # 搜索策略模式
            results = self.vector_mem.search(
                query="belief_strategy",
                limit=100
            )

            for result in results:
                content = result.get("content", {})
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except json.JSONDecodeError as e:
                        logger.error(f"[BeliefEngine] JSON解析失败: {e}", exc_info=True)
                        continue

                if content.get("type") == "belief_strategy" or "alpha" in content:
                    try:
                        pattern = BeliefStrategyPattern.from_dict(content)
                        self.beliefs[pattern.pattern_id] = pattern
                    except (ValueError, TypeError, KeyError) as e:
                        logger.error(f"[BeliefEngine] 加载策略失败: {e}", exc_info=True)
                        continue

            logger.info(f"[BeliefEngine] 从向量记忆加载了 {len(self.beliefs)} 个策略")

        except Exception as e:
            logger.warning(f"[BeliefEngine] 加载向量记忆失败: {e}")

    def _save_to_vector_memory(self, pattern_id: str):
        """保存策略信念到向量记忆"""
        if not self.vector_mem:
            return

        try:
            if pattern_id not in self.beliefs:
                return

            pattern = self.beliefs[pattern_id]
            data = pattern.to_dict()
            data["type"] = "belief_strategy"

            # 使用向量记忆的add方法
            if hasattr(self.vector_mem, 'add'):
                self.vector_mem.add(
                    content=json.dumps(data, ensure_ascii=False),
                    metadata={
                        "pattern_id": pattern_id,
                        "type": "belief_strategy",
                        "success_prob": pattern.get_success_probability(),
                        "updated_at": time.time()
                    }
                )

        except Exception as e:
            logger.warning(f"[BeliefEngine] 保存策略失败: {e}")

    def save_all(self):
        """保存所有策略"""
        for pattern_id in self.beliefs:
            self._save_to_vector_memory(pattern_id)
        logger.info(f"[BeliefEngine] 保存了 {len(self.beliefs)} 个策略")

    def _record_selection(self, result: SelectionResult, context: dict | None):
        """记录策略选择"""
        record = {
            "timestamp": time.time(),
            "pattern_id": result.pattern_id,
            "method": result.selection_method,
            "score": result.score,
            "context": context or {}
        }
        self.selection_history.append(record)

        # 限制历史长度
        if len(self.selection_history) > 1000:
            self.selection_history = self.selection_history[-1000:]


# 全局实例
_belief_engine: BeliefEngine | None = None


def get_belief_engine(vector_mem=None, refresh: bool = False) -> BeliefEngine:
    """获取全局信念引擎实例"""
    global _belief_engine
    if _belief_engine is None or refresh:
        _belief_engine = BeliefEngine(vector_mem=vector_mem)
    return _belief_engine
