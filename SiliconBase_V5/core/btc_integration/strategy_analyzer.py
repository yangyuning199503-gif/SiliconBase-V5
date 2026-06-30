#!/usr/bin/env python3
"""
BTC 策略分析器

功能:
    - 分析市场环境（趋势、波动率、情绪）
    - 根据环境选择最优策略组合
    - 提供策略推荐理由
    - 风险评估

策略库:
    - trend_following: 趋势跟踪 (适合强趋势市场)
    - mean_reversion: 均值回归 (适合震荡市场)
    - breakout: 突破策略 (适合关键位突破)
    - event_driven: 事件驱动 (适合高波动事件)
    - multi_timeframe: 多时间框架 (综合信号)
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MarketRegime(Enum):
    """市场状态枚举"""
    STRONG_UPTREND = "strong_uptrend"      # 强上涨
    WEAK_UPTREND = "weak_uptrend"          # 弱上涨
    STRONG_DOWNTREND = "strong_downtrend"  # 强下跌
    WEAK_DOWNTREND = "weak_downtrend"      # 弱下跌
    RANGING = "ranging"                    # 震荡
    HIGH_VOLATILITY = "high_volatility"    # 高波动
    LOW_VOLATILITY = "low_volatility"      # 低波动
    UNCLEAR = "unclear"                    # 不明确


class StrategyType(Enum):
    """策略类型枚举"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    EVENT_DRIVEN = "event_driven"
    MULTI_TIMEFRAME = "multi_timeframe"


@dataclass
class Strategy:
    """策略定义"""
    id: str
    name: str
    type: StrategyType
    description: str
    suitable_regimes: list[MarketRegime]
    risk_level: int  # 1-5, 5最高
    expected_return: float  # 预期年化收益
    max_drawdown: float  # 最大回撤
    win_rate: float  # 胜率
    avg_trade_duration: str  # 平均持仓时间
    complexity: int  # 复杂度 1-5


@dataclass
class MarketCondition:
    """市场环境数据"""
    # 趋势指标
    trend: str = "sideways"  # uptrend, downtrend, sideways
    trend_strength: float = 0.0  # 0-1

    # 波动率指标
    volatility: float = 0.0  # 波动率百分比
    atr_14: float = 0.0  # ATR值
    bb_width: float = 0.0  # 布林带宽度

    # 动量指标
    rsi_14: float = 50.0
    macd_signal: str = "neutral"

    # 情绪指标
    fear_greed_index: int = 50
    funding_rate: float = 0.0
    funding_sentiment: str = "neutral"

    # 成交量
    volume_24h: float = 0.0
    volume_change: float = 0.0

    # 事件风险
    event_risk: str = "low"  # low, medium, high
    upcoming_events: list[str] = field(default_factory=list)

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "trend_strength": round(self.trend_strength, 2),
            "volatility": round(self.volatility, 2),
            "rsi_14": round(self.rsi_14, 1),
            "macd_signal": self.macd_signal,
            "fear_greed_index": self.fear_greed_index,
            "funding_rate": round(self.funding_rate, 4),
            "event_risk": self.event_risk,
            "timestamp": self.timestamp
        }


@dataclass
class StrategyRecommendation:
    """策略推荐结果"""
    primary_strategy: Strategy
    secondary_strategies: list[Strategy]
    market_regime: MarketRegime
    confidence: float  # 置信度 0-1
    reasoning: str
    risk_warning: str
    suggested_allocation: dict[str, float]  # 资金分配建议
    entry_conditions: list[str]
    exit_conditions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_strategy": {
                "id": self.primary_strategy.id,
                "name": self.primary_strategy.name,
                "type": self.primary_strategy.type.value,
                "risk_level": self.primary_strategy.risk_level,
            },
            "secondary_strategies": [
                {"id": s.id, "name": s.name} for s in self.secondary_strategies
            ],
            "market_regime": self.market_regime.value,
            "confidence": round(self.confidence, 2),
            "reasoning": self.reasoning,
            "risk_warning": self.risk_warning,
            "suggested_allocation": self.suggested_allocation,
            "entry_conditions": self.entry_conditions,
            "exit_conditions": self.exit_conditions,
        }


class StrategyLibrary:
    """策略库"""

    STRATEGIES = [
        Strategy(
            id="stage46_aggressive",
            name="趋势跟踪激进版",
            type=StrategyType.TREND_FOLLOWING,
            description="适合强趋势市场，追涨杀跌，高盈亏比",
            suitable_regimes=[
                MarketRegime.STRONG_UPTREND,
                MarketRegime.STRONG_DOWNTREND,
            ],
            risk_level=4,
            expected_return=120.0,
            max_drawdown=25.0,
            win_rate=0.45,
            avg_trade_duration="1-3天",
            complexity=3
        ),
        Strategy(
            id="stage64_mean_reversion",
            name="均值回归",
            type=StrategyType.MEAN_REVERSION,
            description="适合震荡市场，高抛低吸，高胜率",
            suitable_regimes=[
                MarketRegime.RANGING,
                MarketRegime.LOW_VOLATILITY,
            ],
            risk_level=2,
            expected_return=60.0,
            max_drawdown=12.0,
            win_rate=0.65,
            avg_trade_duration="4-12小时",
            complexity=2
        ),
        Strategy(
            id="stage138_anchor",
            name="支撑阻力突破",
            type=StrategyType.BREAKOUT,
            description="关键位突破交易，趋势启动时入场",
            suitable_regimes=[
                MarketRegime.WEAK_UPTREND,
                MarketRegime.WEAK_DOWNTREND,
                MarketRegime.HIGH_VOLATILITY,
            ],
            risk_level=3,
            expected_return=80.0,
            max_drawdown=18.0,
            win_rate=0.50,
            avg_trade_duration="6-24小时",
            complexity=3
        ),
        Strategy(
            id="stage120_event",
            name="事件驱动",
            type=StrategyType.EVENT_DRIVEN,
            description="基于宏观事件和新闻的交易策略",
            suitable_regimes=[
                MarketRegime.HIGH_VOLATILITY,
            ],
            risk_level=5,
            expected_return=150.0,
            max_drawdown=30.0,
            win_rate=0.40,
            avg_trade_duration="1-7天",
            complexity=4
        ),
        Strategy(
            id="stage154_multiasset",
            name="多资产分散",
            type=StrategyType.MULTI_TIMEFRAME,
            description="多代币组合，分散风险，稳健收益",
            suitable_regimes=[
                MarketRegime.UNCLEAR,
                MarketRegime.RANGING,
            ],
            risk_level=2,
            expected_return=40.0,
            max_drawdown=10.0,
            win_rate=0.55,
            avg_trade_duration="2-5天",
            complexity=2
        ),
    ]

    @classmethod
    def get_all_strategies(cls) -> list[Strategy]:
        """获取所有策略"""
        return cls.STRATEGIES

    @classmethod
    def get_strategy_by_id(cls, strategy_id: str) -> Strategy | None:
        """根据 ID 获取策略"""
        for s in cls.STRATEGIES:
            if s.id == strategy_id:
                return s
        return None

    @classmethod
    def get_strategies_by_regime(cls, regime: MarketRegime) -> list[Strategy]:
        """获取适合特定市场状态的策略"""
        return [s for s in cls.STRATEGIES if regime in s.suitable_regimes]


class StrategyAnalyzer:
    """
    策略分析器

    核心功能:
        1. 分析市场环境
        2. 推荐最优策略
        3. 生成交易建议
    """

    def __init__(self):
        self.strategy_lib = StrategyLibrary()

    def analyze_market(self, market_data: dict[str, Any]) -> MarketCondition:
        """
        分析市场环境

        Args:
            market_data: 原始市场数据

        Returns:
            MarketCondition 对象
        """
        condition = MarketCondition()

        # 解析趋势
        price_change_24h = market_data.get("price_change_24h", 0)
        rsi = market_data.get("rsi_14", 50)

        if price_change_24h > 5 and rsi > 60:
            condition.trend = "uptrend"
            condition.trend_strength = min(1.0, price_change_24h / 10)
        elif price_change_24h < -5 and rsi < 40:
            condition.trend = "downtrend"
            condition.trend_strength = min(1.0, abs(price_change_24h) / 10)
        else:
            condition.trend = "sideways"
            condition.trend_strength = 0.3

        # 解析波动率
        condition.volatility = market_data.get("volatility_24h", 0)
        condition.atr_14 = market_data.get("atr_14", 0)

        # 解析动量
        condition.rsi_14 = rsi
        condition.macd_signal = market_data.get("macd_signal", "neutral")

        # 解析情绪
        condition.fear_greed_index = market_data.get("fear_greed_index", 50)
        condition.funding_rate = market_data.get("funding_rate", 0)

        # 资金费率解读
        if condition.funding_rate > 0.01:
            condition.funding_sentiment = "overheated_long"
        elif condition.funding_rate < -0.01:
            condition.funding_sentiment = "overheated_short"
        else:
            condition.funding_sentiment = "neutral"

        # 事件风险
        condition.event_risk = market_data.get("event_risk", "low")
        condition.upcoming_events = market_data.get("upcoming_events", [])

        return condition

    def detect_market_regime(self, condition: MarketCondition) -> MarketRegime:
        """
        检测市场状态

        Args:
            condition: 市场环境

        Returns:
            MarketRegime 枚举
        """
        # 高波动优先
        if condition.volatility > 5:
            return MarketRegime.HIGH_VOLATILITY

        # 强趋势判断
        if condition.trend == "uptrend":
            if condition.trend_strength > 0.7:
                return MarketRegime.STRONG_UPTREND
            else:
                return MarketRegime.WEAK_UPTREND

        if condition.trend == "downtrend":
            if condition.trend_strength > 0.7:
                return MarketRegime.STRONG_DOWNTREND
            else:
                return MarketRegime.WEAK_DOWNTREND

        # 低波动
        if condition.volatility < 2:
            return MarketRegime.LOW_VOLATILITY

        # 震荡
        if 40 < condition.rsi_14 < 60:
            return MarketRegime.RANGING

        return MarketRegime.UNCLEAR

    def recommend_strategy(
        self,
        condition: MarketCondition,
        user_risk_tolerance: str = "medium"
    ) -> StrategyRecommendation:
        """
        推荐策略

        Args:
            condition: 市场环境
            user_risk_tolerance: 用户风险偏好 (low/medium/high)

        Returns:
            StrategyRecommendation 推荐结果
        """
        # 检测市场状态
        regime = self.detect_market_regime(condition)

        # 获取适合该状态的策略
        suitable_strategies = self.strategy_lib.get_strategies_by_regime(regime)

        # 根据风险偏好过滤
        risk_levels = {"low": [1, 2], "medium": [1, 2, 3], "high": [1, 2, 3, 4, 5]}
        allowed_risk = risk_levels.get(user_risk_tolerance, [1, 2, 3])
        suitable_strategies = [s for s in suitable_strategies if s.risk_level in allowed_risk]

        # 如果没有合适的，选择默认策略
        if not suitable_strategies:
            suitable_strategies = [self.strategy_lib.get_strategy_by_id("stage154_multiasset")]

        # 选择主策略（第一个最合适的）
        primary = suitable_strategies[0]

        # 选择辅助策略（最多2个）
        secondary = suitable_strategies[1:3] if len(suitable_strategies) > 1 else []

        # 计算置信度
        confidence = self._calculate_confidence(condition, primary)

        # 生成推荐理由
        reasoning = self._generate_reasoning(condition, regime, primary)

        # 生成风险提示
        risk_warning = self._generate_risk_warning(condition, primary)

        # 资金分配建议
        allocation = self._suggest_allocation(primary, secondary)

        # 入场/出场条件
        entry_conditions = self._generate_entry_conditions(condition, primary)
        exit_conditions = self._generate_exit_conditions(condition, primary)

        return StrategyRecommendation(
            primary_strategy=primary,
            secondary_strategies=secondary,
            market_regime=regime,
            confidence=confidence,
            reasoning=reasoning,
            risk_warning=risk_warning,
            suggested_allocation=allocation,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions
        )

    def _calculate_confidence(self, condition: MarketCondition, strategy: Strategy) -> float:
        """计算策略匹配置信度"""
        confidence = 0.5  # 基础置信度

        # 趋势匹配加分
        if condition.trend == "uptrend" and strategy.type == StrategyType.TREND_FOLLOWING:
            confidence += 0.2

        # RSI 匹配
        if 30 < condition.rsi_14 < 70:
            confidence += 0.1

        # 波动率匹配
        if condition.volatility < 3 and strategy.type == StrategyType.MEAN_REVERSION:
            confidence += 0.15

        # 资金费率信号
        if abs(condition.funding_rate) > 0.01:
            confidence += 0.05

        return min(1.0, confidence)

    def _generate_reasoning(
        self,
        condition: MarketCondition,
        regime: MarketRegime,
        strategy: Strategy
    ) -> str:
        """生成推荐理由"""
        reasons = []

        # 市场状态
        regime_desc = {
            MarketRegime.STRONG_UPTREND: "市场处于强上涨趋势",
            MarketRegime.WEAK_UPTREND: "市场处于弱上涨趋势",
            MarketRegime.STRONG_DOWNTREND: "市场处于强下跌趋势",
            MarketRegime.WEAK_DOWNTREND: "市场处于弱下跌趋势",
            MarketRegime.RANGING: "市场处于震荡区间",
            MarketRegime.HIGH_VOLATILITY: "市场波动率较高",
            MarketRegime.LOW_VOLATILITY: "市场波动率较低",
            MarketRegime.UNCLEAR: "市场方向尚不明确",
        }
        reasons.append(regime_desc.get(regime, "市场状态复杂"))

        # 技术指标
        if condition.rsi_14 > 70:
            reasons.append(f"RSI 显示超买({condition.rsi_14:.1f})")
        elif condition.rsi_14 < 30:
            reasons.append(f"RSI 显示超卖({condition.rsi_14:.1f})")

        # 资金费率
        if condition.funding_rate > 0.01:
            reasons.append("资金费率显示多头过热")
        elif condition.funding_rate < -0.01:
            reasons.append("资金费率显示空头过热")

        # 策略匹配
        reasons.append(f"推荐 '{strategy.name}' 因为: {strategy.description}")

        return "\n".join(f"• {r}" for r in reasons)

    def _generate_risk_warning(self, condition: MarketCondition, strategy: Strategy) -> str:
        """生成风险提示"""
        warnings = []

        # 高波动警告
        if condition.volatility > 5:
            warnings.append("当前波动率较高，请控制仓位")

        # 事件风险
        if condition.event_risk == "high":
            warnings.append(" upcoming 宏观事件，建议降低杠杆或观望")

        # 策略风险
        if strategy.risk_level >= 4:
            warnings.append(f"该策略风险等级为 {strategy.risk_level}/5，可能产生较大回撤")

        # 资金费率风险
        if abs(condition.funding_rate) > 0.05:
            warnings.append("资金费率极端，注意反转风险")

        return "\n".join(f"⚠️ {w}" for w in warnings) if warnings else "当前风险可控"

    def _suggest_allocation(
        self,
        primary: Strategy,
        secondary: list[Strategy]
    ) -> dict[str, float]:
        """建议资金分配"""
        allocation = {primary.id: 60.0}  # 主策略 60%

        # 辅助策略均分剩余 40%
        if secondary:
            remaining = 40.0 / len(secondary)
            for s in secondary:
                allocation[s.id] = remaining
        else:
            allocation[primary.id] = 100.0

        return allocation

    def _generate_entry_conditions(self, condition: MarketCondition, strategy: Strategy) -> list[str]:
        """生成入场条件"""
        conditions = []

        if strategy.type == StrategyType.TREND_FOLLOWING:
            conditions.append("价格突破前高/前低")
            conditions.append("成交量放大确认")
        elif strategy.type == StrategyType.MEAN_REVERSION:
            conditions.append("价格触及布林带下轨/上轨")
            conditions.append("RSI 进入超卖/超买区域")
        elif strategy.type == StrategyType.BREAKOUT:
            conditions.append("突破关键支撑/阻力位")
            conditions.append("突破时成交量大于均值 1.5 倍")

        conditions.append(f"账户风险度低于 {strategy.risk_level * 10}%")

        return conditions

    def _generate_exit_conditions(self, condition: MarketCondition, strategy: Strategy) -> list[str]:
        """生成出场条件"""
        conditions = []

        conditions.append(f"止损: -{strategy.max_drawdown / 2:.1f}%")
        conditions.append(f"止盈: +{strategy.expected_return / 10:.1f}%")

        if strategy.type == StrategyType.TREND_FOLLOWING:
            conditions.append("趋势反转信号出现")
        elif strategy.type == StrategyType.MEAN_REVERSION:
            conditions.append("价格回归均值")

        conditions.append("持仓时间超过策略平均周期")

        return conditions


# 全局分析器实例
_analyzer: StrategyAnalyzer | None = None


def get_strategy_analyzer() -> StrategyAnalyzer:
    """获取策略分析器单例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = StrategyAnalyzer()
    return _analyzer
