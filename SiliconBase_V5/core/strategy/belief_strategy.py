#!/usr/bin/env python3
"""
贝叶斯策略模式 - 用概率分布表示策略有效性

核心设计理念:
1. 用 Beta 分布建模策略成功率的不确定性
2. 支持加权证据更新（反思质量作为置信度）
3. 提供探索-利用平衡的选择机制
4. 量化不确定性，支持风险决策

Author: Agent-Bayesian
Version: 1.0.0
"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import numpy as np
    from scipy.stats import beta as beta_dist
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    np = None
    beta_dist = None


class StrategyStatus(Enum):
    """策略状态"""
    ACTIVE = "active"           # 活跃使用中
    UNDER_REVIEW = "review"     # 效果存疑，观察中
    DEPRECATED = "deprecated"   # 已弃用
    EXPERIMENTAL = "experimental"  # 实验性策略


@dataclass
class BeliefStrategyPattern:
    """
    贝叶斯策略模式 - 替代原有的 StrategyPattern

    关键改进:
    - success_rate: float → Beta(α, β) 分布
    - usage_count: int → alpha + beta - 2 (试验次数)
    - 新增置信区间、UCB评分、Thompson采样支持

    Attributes:
        pattern_id: 策略唯一标识
        name: 人类可读的策略名称
        description: 策略详细描述
        applicable_scenarios: 适用场景关键词列表
        strategy_steps: 策略执行步骤

        # 贝叶斯核心参数
        alpha: Beta分布α参数 (成功次数 + 1 + prior_alpha - 1)
        beta: Beta分布β参数 (失败次数 + 1 + prior_beta - 1)
        prior_alpha: 先验α（保留用于重置）
        prior_beta: 先验β（保留用于重置）

        # 元数据
        created_at: 创建时间戳
        last_updated: 最后更新时间戳
        last_used: 最后使用时间
        status: 策略状态
        evidence_history: 证据历史（用于调试和分析）
        metadata: 扩展元数据
    """

    # 基础信息
    pattern_id: str
    name: str
    description: str = ""
    applicable_scenarios: list[str] = field(default_factory=list)
    strategy_steps: list[str] = field(default_factory=list)

    # 贝叶斯核心参数（Beta分布）
    alpha: float = 1.0  # 成功次数 + 1（先验）
    beta: float = 1.0   # 失败次数 + 1（先验）

    # 先验保存（用于重置或对比）
    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    # 时间戳
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    # 状态和元数据
    status: StrategyStatus = field(default=StrategyStatus.ACTIVE)
    evidence_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理：确保参数有效"""
        # 确保 alpha, beta > 0
        if self.alpha <= 0:
            self.alpha = 1.0
        if self.beta <= 0:
            self.beta = 1.0

        # 保存先验（如果未设置）
        if not hasattr(self, '_prior_saved'):
            self.prior_alpha = self.alpha
            self.prior_beta = self.beta
            self._prior_saved = True

    # ========== 核心贝叶斯方法 ==========

    def update_with_evidence(self, success: bool, confidence: float = 1.0,
                            context: dict | None = None):
        """
        贝叶斯更新：根据新证据更新信念

        数学原理:
            先验: Beta(α, β)
            似然: Bernoulli(success)
            后验: Beta(α + confidence*success, β + confidence*(1-success))

        Args:
            success: 是否成功
            confidence: 证据置信度 (0-1)，反思质量越高，置信度越高
            context: 上下文信息（用于历史记录）

        示例:
            >>> pattern = BeliefStrategyPattern("p1", "测试策略")
            >>> pattern.update_with_evidence(True, confidence=0.9)  # 高质量成功
            >>> pattern.update_with_evidence(False, confidence=0.5) # 低质量失败
        """
        # 确保置信度在有效范围
        confidence = max(0.0, min(1.0, confidence))

        # Beta(α, β) + 加权证据 → Beta(α + w*success, β + w*(1-success))
        if success:
            self.alpha += confidence
        else:
            self.beta += confidence

        self.last_updated = time.time()

        # 记录证据历史
        evidence_record = {
            "timestamp": time.time(),
            "success": success,
            "confidence": confidence,
            "alpha_before": self.alpha - confidence if success else self.alpha,
            "beta_before": self.beta if success else self.beta - confidence,
            "alpha_after": self.alpha,
            "beta_after": self.beta,
            "context": context or {}
        }
        self.evidence_history.append(evidence_record)

        # 限制历史记录长度（避免内存无限增长）
        if len(self.evidence_history) > 100:
            self.evidence_history = self.evidence_history[-100:]

    def batch_update(self, successes: int, failures: int,
                     avg_confidence: float = 1.0):
        """
        批量更新：一次性更新多个试验结果

        用于历史数据迁移或批量导入

        Args:
            successes: 成功次数
            failures: 失败次数
            avg_confidence: 平均置信度
        """
        self.alpha += successes * avg_confidence
        self.beta += failures * avg_confidence
        self.last_updated = time.time()

    def get_success_probability(self) -> float:
        """
        获取当前成功率期望 E[p] = α / (α + β)

        这是Beta分布的均值，也是MAP估计（最大后验估计）
        """
        return self.alpha / (self.alpha + self.beta)

    def get_variance(self) -> float:
        """
        获取成功率的不确定性（方差）

        Var[p] = αβ / ((α+β)²(α+β+1))

        方差越大，不确定性越高
        """
        alpha, beta = self.alpha, self.beta
        return (alpha * beta) / ((alpha + beta)**2 * (alpha + beta + 1))

    def get_standard_deviation(self) -> float:
        """获取标准差"""
        return math.sqrt(self.get_variance())

    def get_confidence_interval(self, confidence_level: float = 0.95) -> tuple[float, float]:
        """
        获取成功率置信区间

        量化"我知道什么"以及"我对知道的东西有多确定"

        Args:
            confidence_level: 置信水平，默认95%

        Returns:
            (下限, 上限) 的元组
        """
        if not SCIPY_AVAILABLE or beta_dist is None:
            # 无scipy时使用正态近似
            mean = self.get_success_probability()
            std = self.get_standard_deviation()
            z = 1.96 if confidence_level == 0.95 else 2.576  # 95% or 99%
            lower = max(0.0, mean - z * std)
            upper = min(1.0, mean + z * std)
            return (lower, upper)

        # 使用Beta分布的分位数
        alpha = (1 - confidence_level) / 2
        lower = beta_dist.ppf(alpha, self.alpha, self.beta)
        upper = beta_dist.ppf(1 - alpha, self.alpha, self.beta)

        return (float(lower), float(upper))

    def get_uncertainty(self) -> float:
        """
        获取不确定性度量 (0-1)

        使用置信区间宽度作为不确定性指标
        """
        lower, upper = self.get_confidence_interval(0.95)
        return upper - lower

    def get_effective_sample_size(self) -> float:
        """
        获取有效样本量 = α + β - 2

        减2是因为先验贡献了1+1=2的伪计数
        """
        return self.alpha + self.beta - 2

    # ========== 探索-利用平衡方法 ==========

    def get_ucb_score(self, total_trials: int,
                      exploration_factor: float = 1.414) -> float:
        """
        计算UCB评分（Upper Confidence Bound）

        UCB1公式: score = mean + exploration * sqrt(2*ln(total_trials) / n_i)

        特性:
        - 利用项: mean = E[p]（当前最佳估计）
        - 探索项: 与试验次数的平方根成反比（试得少，不确定性高）

        Args:
            total_trials: 所有策略的总试验次数
            exploration_factor: 探索因子（默认√2，理论最优）

        Returns:
            UCB评分（越高越值得尝试）
        """
        n_i = self.get_effective_sample_size()

        if n_i == 0:
            return float('inf')  # 新策略优先探索

        mean = self.get_success_probability()
        exploration_term = exploration_factor * math.sqrt(
            2 * math.log(max(1, total_trials)) / n_i
        )

        return mean + exploration_term

    def thompson_sample(self) -> float:
        """
        Thompson采样：从Beta分布中采样一次

        返回采样值（0-1之间），用于策略选择
        """
        if np is None or not hasattr(np.random, 'beta'):
            # 简单的近似采样（使用Beta均值加正态扰动）
            mean = self.get_success_probability()
            std = self.get_standard_deviation()
            import random
            return max(0.0, min(1.0, random.gauss(mean, std)))

        return float(np.random.beta(self.alpha, self.beta))

    def is_significantly_better_than(self, other: 'BeliefStrategyPattern',
                                     threshold: float = 0.95) -> bool:
        """
        判断当前策略是否显著优于另一策略

        使用假设检验: P(this_success > other_success) > threshold

        Args:
            other: 另一策略
            threshold: 显著性阈值

        Returns:
            是否显著更优
        """
        if not SCIPY_AVAILABLE or beta_dist is None:
            # 简化的比较：比较置信区间下限
            self_lower = self.get_confidence_interval(0.95)[0]
            other_upper = other.get_confidence_interval(0.95)[1]
            return self_lower > other_upper

        # 更精确的计算：计算 P(a > b) for Beta(a1, b1) vs Beta(a2, b2)
        from scipy import integrate

        def integrand(x):
            return beta_dist.pdf(x, self.alpha, self.beta) * \
                   beta_dist.cdf(x, other.alpha, other.beta)

        prob_better, _ = integrate.quad(integrand, 0, 1)
        return prob_better > threshold

    # ========== 状态管理方法 ==========

    def mark_used(self):
        """标记策略被使用"""
        self.last_used = time.time()
        self.metadata['usage_count'] = self.metadata.get('usage_count', 0) + 1

    def reset_to_prior(self):
        """重置为先验（遗忘所有观测）"""
        self.alpha = self.prior_alpha
        self.beta = self.prior_beta
        self.evidence_history.clear()
        self.last_updated = time.time()

    def update_status(self):
        """
        根据当前信念自动更新状态

        规则:
        - 试验次数 < 3: EXPERIMENTAL
        - 成功率 < 0.3 且试验 > 10: UNDER_REVIEW
        - 成功率 < 0.1 且试验 > 20: DEPRECATED
        - 其他: ACTIVE
        """
        n = self.get_effective_sample_size()
        success_rate = self.get_success_probability()

        if n < 3:
            self.status = StrategyStatus.EXPERIMENTAL
        elif success_rate < 0.1 and n >= 20:
            self.status = StrategyStatus.DEPRECATED
        elif success_rate < 0.3 and n >= 10:
            self.status = StrategyStatus.UNDER_REVIEW
        else:
            self.status = StrategyStatus.ACTIVE

    # ========== 序列化方法 ==========

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于存储）"""
        ci_lower, ci_upper = self.get_confidence_interval(0.95)
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "applicable_scenarios": self.applicable_scenarios,
            "strategy_steps": self.strategy_steps,
            "alpha": self.alpha,
            "beta": self.beta,
            "prior_alpha": self.prior_alpha,
            "prior_beta": self.prior_beta,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "last_used": self.last_used,
            "status": self.status.value,
            "evidence_history": self.evidence_history[-20:],  # 只保存最近20条
            "metadata": self.metadata,
            # 导出计算值（方便查询）
            "_computed": {
                "success_probability": self.get_success_probability(),
                "confidence_interval_95": [ci_lower, ci_upper],
                "effective_samples": self.get_effective_sample_size(),
                "uncertainty": self.get_uncertainty()
            }
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'BeliefStrategyPattern':
        """从字典创建实例"""
        # 处理旧版StrategyPattern的迁移
        if 'success_rate' in data and 'alpha' not in data:
            # 从旧格式迁移
            success_rate = data.get('success_rate', 0.5)
            usage_count = data.get('usage_count', 1)
            # 用最大似然估计反推合理的alpha, beta
            alpha = success_rate * usage_count + 1
            beta = (1 - success_rate) * usage_count + 1
        else:
            alpha = data.get('alpha', 1.0)
            beta = data.get('beta', 1.0)

        # 处理status字段
        status_str = data.get('status', 'active')
        try:
            status = StrategyStatus(status_str)
        except ValueError:
            status = StrategyStatus.ACTIVE

        return cls(
            pattern_id=data['pattern_id'],
            name=data['name'],
            description=data.get('description', ''),
            applicable_scenarios=data.get('applicable_scenarios', []),
            strategy_steps=data.get('strategy_steps', []),
            alpha=alpha,
            beta=beta,
            prior_alpha=data.get('prior_alpha', alpha),
            prior_beta=data.get('prior_beta', beta),
            created_at=data.get('created_at', time.time()),
            last_updated=data.get('last_updated', time.time()),
            last_used=data.get('last_used', time.time()),
            status=status,
            evidence_history=data.get('evidence_history', []),
            metadata=data.get('metadata', {})
        )

    def __repr__(self) -> str:
        """字符串表示"""
        ci_lower, ci_upper = self.get_confidence_interval(0.95)
        return (f"BeliefStrategyPattern({self.pattern_id}: "
                f"{self.get_success_probability():.2%} "
                f"[{ci_lower:.2%}-{ci_upper:.2%}], "
                f"n={self.get_effective_sample_size():.0f}, "
                f"status={self.status.value})")


# =============================================================================
# 向后兼容: StrategyPattern 别名
# =============================================================================

# 保留旧名称的兼容性
StrategyPattern = BeliefStrategyPattern
