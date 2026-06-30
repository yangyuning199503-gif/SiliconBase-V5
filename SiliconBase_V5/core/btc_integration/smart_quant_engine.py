#!/usr/bin/env python3
"""
智能量化引擎 V2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心理念：AI像专业交易员一样综合分析所有维度

分析维度：
1. 技术面 - 价格行为、指标、趋势
2. 消息面 - 新闻、事件、宏观数据
3. 情绪面 - 市场恐慌/贪婪、资金流向
4. 基本面 - 链上数据、交易所资金流

决策流程：
多维度分析 → 因子权重动态调整 → 策略选择+参数优化 → 执行 → 带背景的反馈
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MarketDimension(Enum):
    """市场分析维度"""
    TECHNICAL = "technical"      # 技术面
    NEWS = "news"                # 消息面
    SENTIMENT = "sentiment"      # 情绪面
    FUNDAMENTAL = "fundamental"  # 基本面/链上


class StrategyType(Enum):
    """策略类型 - 更细分的策略"""
    # 趋势类
    TREND_FOLLOW = "trend_follow"           # 趋势跟随
    TREND_MOMENTUM = "trend_momentum"       # 趋势动量
    TREND_REVERSAL = "trend_reversal"       # 趋势反转

    # 震荡类
    MEAN_REVERSION = "mean_reversion"       # 均值回归
    RANGE_BOUND = "range_bound"             # 区间交易
    BOLLINGER_BANDS = "bollinger_bands"     # 布林带

    # 突破类
    BREAKOUT_MOMENTUM = "breakout_momentum" # 动量突破
    BREAKOUT_REVERSAL = "breakout_reversal" # 假突破反转

    # 事件类
    NEWS_MOMENTUM = "news_momentum"         # 新闻动量
    EVENT_ARBITRAGE = "event_arbitrage"     # 事件套利

    # 特殊类
    HIGH_VOLATILITY = "high_volatility"     # 高波动策略
    LOW_LIQUIDITY = "low_liquidity"         # 低流动性策略
    CORRELATION_TRADE = "correlation_trade" # 相关性交易


@dataclass
class MarketFactor:
    """市场因子 - 单个分析指标"""
    name: str
    dimension: MarketDimension
    value: float                    # 归一化值 -1到1
    weight: float                   # 权重 0-1
    confidence: float               # 置信度 0-1
    description: str                # 人类可读描述
    raw_data: dict = field(default_factory=dict)  # 原始数据

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dimension": self.dimension.value,
            "value": round(self.value, 3),
            "weight": round(self.weight, 2),
            "confidence": round(self.confidence, 2),
            "description": self.description,
        }


@dataclass
class NewsImpact:
    """消息影响分析"""
    source: str                     # 消息来源
    title: str                      # 标题
    content: str                    # 内容摘要
    timestamp: float

    # 分析结果
    sentiment: str                  # positive/negative/neutral
    impact_score: float             # 影响程度 -1到1
    urgency: str                    # immediate/short_term/medium_term
    affected_symbols: list[str]     # 影响的币种

    # 分类标签
    category: str                   # macro/exchange/security/technology
    keywords: list[str]             # 关键词

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title[:100],
            "sentiment": self.sentiment,
            "impact_score": round(self.impact_score, 2),
            "urgency": self.urgency,
            "category": self.category,
            "keywords": self.keywords,
        }


@dataclass
class MarketContext:
    """完整市场上下文 - AI决策的输入"""
    symbol: str
    timestamp: float

    # 技术面
    price: float
    price_change_24h: float
    volume_24h: float
    rsi: float
    macd_signal: str
    trend: str                      # up/down/sideways
    trend_strength: float
    support_levels: list[float]
    resistance_levels: list[float]

    # 消息面（最近24小时）
    recent_news: list[NewsImpact]

    # 情绪面
    fear_greed_index: int
    funding_rate: float
    open_interest_change: float
    social_sentiment: str

    # 基本面/链上
    exchange_inflow: float          # 交易所流入
    exchange_outflow: float         # 交易所流出
    whale_movement: str             # 巨鲸动向
    network_activity: str           # 网络活跃度

    # 跨市场
    btc_dominance: float
    eth_btc_ratio: float
    usdt_premium: float             # USDT溢价
    global_market_sentiment: str

    def to_prompt(self) -> str:
        """转换为AI分析的prompt"""
        news_summary = "\n".join([
            f"  - [{n.source}] {n.title[:50]}... (情绪:{n.sentiment}, 影响:{n.impact_score:+.2f})"
            for n in self.recent_news[-3:]
        ]) if self.recent_news else "  无重大新闻"

        return f"""【{self.symbol} 市场分析】时间: {datetime.fromtimestamp(self.timestamp)}

【技术面】
- 价格: ${self.price:,.2f} (24h {self.price_change_24h:+.2%})
- 趋势: {self.trend} (强度: {self.trend_strength:.0%})
- RSI: {self.rsi:.1f} | MACD: {self.macd_signal}
- 支撑位: {self.support_levels}
- 阻力位: {self.resistance_levels}

【消息面】(最近24h)
{news_summary}

【情绪面】
- 恐慌贪婪指数: {self.fear_greed_index}/100
- 资金费率: {self.funding_rate:.4%}
- 社媒情绪: {self.social_sentiment}

【资金面】
- 交易所净流入: {self.exchange_inflow - self.exchange_outflow:+.2f} BTC
- 巨鲸动向: {self.whale_movement}
- USDT溢价: {self.usdt_premium:.2%}

【跨市场】
- BTC市占率: {self.btc_dominance:.1%}
- 全球市场情绪: {self.global_market_sentiment}
"""


@dataclass
class StrategyParameters:
    """策略参数空间 - AI在区间内选择"""
    # 入场参数
    entry_rsi_min: int = 30         # RSI下限
    entry_rsi_max: int = 70         # RSI上限
    entry_volume_threshold: float = 1.5  # 成交量倍数阈值

    # 出场参数
    take_profit_pct: float = 3.0    # 止盈百分比
    stop_loss_pct: float = 2.0      # 止损百分比

    # 仓位参数
    position_size_pct: float = 10.0 # 仓位占资金比例
    max_leverage: int = 5           # 最大杠杆

    # 时间参数
    hold_time_max: int = 48         # 最大持仓时间(小时)

    # 过滤参数
    min_volatility: float = 0.01    # 最小波动率
    max_volatility: float = 0.10    # 最大波动率

    def to_dict(self) -> dict:
        return {
            "entry_rsi_range": f"{self.entry_rsi_min}-{self.entry_rsi_max}",
            "volume_threshold": f"{self.entry_volume_threshold}x",
            "take_profit": f"{self.take_profit_pct}%",
            "stop_loss": f"{self.stop_loss_pct}%",
            "position_size": f"{self.position_size_pct}%",
            "max_leverage": f"{self.max_leverage}x",
            "hold_time_max": f"{self.hold_time_max}h",
            "volatility_range": f"{self.min_volatility:.1%}-{self.max_volatility:.1%}",
        }


@dataclass
class TradingDecision:
    """完整交易决策"""
    symbol: str
    timestamp: float

    # 决策内容
    action: str                     # open_long/open_short/hold/close
    strategy: StrategyType
    strategy_params: StrategyParameters
    position_size: float            # 仓位大小
    leverage: int

    # 决策背景
    market_context: MarketContext   # 当时的完整市场背景
    factors: list[MarketFactor]     # 分析的各个因子
    primary_factor: str             # 主要驱动因子

    # AI分析
    reasoning: str                  # 详细决策理由
    confidence: float               # 置信度
    risk_assessment: str            # 风险评估
    alternative_strategies: list[str]  # 备选策略及为什么不选

    # 预期
    expected_hold_time: int         # 预期持仓时间
    expected_profit_pct: float      # 预期收益
    max_acceptable_loss_pct: float  # 最大可接受亏损

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "strategy": self.strategy.value,
            "strategy_params": self.strategy_params.to_dict(),
            "position_size": self.position_size,
            "leverage": self.leverage,
            "primary_factor": self.primary_factor,
            "confidence": round(self.confidence, 2),
            "reasoning": self.reasoning,
            "risk_assessment": self.risk_assessment,
        }


@dataclass
class TradeExecution:
    """交易执行结果"""
    decision: TradingDecision

    # 执行详情
    entry_price: float
    entry_time: float
    exit_price: float | None = None
    exit_time: float | None = None

    # 结果
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"            # open/closed

    # 复盘分析（平仓后填充）
    post_analysis: str = ""         # 事后分析：预测 vs 实际
    lessons_learned: str = ""       # 经验教训
    strategy_effectiveness: float = 0.0  # 策略有效性评分


class SmartQuantEngine:
    """
    智能量化引擎

    特点：
    1. 多维度分析（技术+消息+情绪+资金）
    2. 因子权重动态调整
    3. 策略参数AI优化
    4. 带完整上下文的反馈闭环
    """

    def __init__(self):
        # 策略历史表现（带上下文）
        self.strategy_history: list[TradeExecution] = []

        # 因子权重学习
        self.factor_weights: dict[str, float] = {
            "technical_trend": 0.25,
            "technical_momentum": 0.15,
            "news_sentiment": 0.20,
            "news_impact": 0.10,
            "market_sentiment": 0.15,
            "fundamental_flow": 0.15,
        }

        # 消息影响历史（用于学习消息效果）
        self.news_impact_history: list[dict] = []

        logger.info("[SmartQuantEngine] 智能量化引擎初始化完成")

    def analyze_market(self, context: MarketContext) -> list[MarketFactor]:
        """
        多维度市场分析

        分析所有维度，生成因子列表
        """
        factors = []

        # 1. 技术面分析
        factors.extend(self._analyze_technical(context))

        # 2. 消息面分析
        factors.extend(self._analyze_news(context))

        # 3. 情绪面分析
        factors.extend(self._analyze_sentiment(context))

        # 4. 资金面分析
        factors.extend(self._analyze_fundamental(context))

        # 根据历史表现调整权重
        factors = self._adjust_factor_weights(factors)

        return factors

    def _analyze_technical(self, context: MarketContext) -> list[MarketFactor]:
        """技术面分析"""
        factors = []

        # 趋势因子
        trend_value = context.trend_strength if context.trend == "up" else -context.trend_strength
        factors.append(MarketFactor(
            name="trend_direction",
            dimension=MarketDimension.TECHNICAL,
            value=trend_value,
            weight=self.factor_weights["technical_trend"],
            confidence=0.8,
            description=f"趋势{context.trend}, 强度{context.trend_strength:.0%}",
        ))

        # RSI因子
        rsi_normalized = (context.rsi - 50) / 50  # 映射到-1到1
        factors.append(MarketFactor(
            name="rsi_momentum",
            dimension=MarketDimension.TECHNICAL,
            value=rsi_normalized,
            weight=self.factor_weights["technical_momentum"],
            confidence=0.7,
            description=f"RSI={context.rsi:.1f} ({'超买' if context.rsi > 70 else '超卖' if context.rsi < 30 else '中性'})",
        ))

        # 成交量因子
        volume_factor = min(context.volume_24h / 1000000, 1.0)  # 归一化
        factors.append(MarketFactor(
            name="volume_strength",
            dimension=MarketDimension.TECHNICAL,
            value=volume_factor,
            weight=0.1,
            confidence=0.6,
            description=f"24h成交量 {context.volume_24h/1e6:.1f}M",
        ))

        return factors

    def _analyze_news(self, context: MarketContext) -> list[MarketFactor]:
        """消息面分析"""
        factors = []

        if not context.recent_news:
            return factors

        # 综合新闻影响
        total_impact = 0
        total_weight = 0
        urgent_news = []

        for news in context.recent_news:
            weight = abs(news.impact_score) * news.confidence if hasattr(news, 'confidence') else abs(news.impact_score)
            total_impact += news.impact_score * weight
            total_weight += weight

            if news.urgency == "immediate":
                urgent_news.append(news)

        if total_weight > 0:
            avg_impact = total_impact / total_weight
            factors.append(MarketFactor(
                name="news_sentiment",
                dimension=MarketDimension.NEWS,
                value=avg_impact,
                weight=self.factor_weights["news_sentiment"],
                confidence=min(total_weight, 1.0),
                description=f"新闻情绪{avg_impact:+.2f} ({len(context.recent_news)}条)",
            ))

        # 紧急消息因子
        if urgent_news:
            urgent_impact = sum(n.impact_score for n in urgent_news) / len(urgent_news)
            factors.append(MarketFactor(
                name="urgent_news",
                dimension=MarketDimension.NEWS,
                value=urgent_impact,
                weight=self.factor_weights["news_impact"],
                confidence=0.9,
                description=f"紧急消息: {urgent_news[0].title[:50]}...",
            ))

        return factors

    def _analyze_sentiment(self, context: MarketContext) -> list[MarketFactor]:
        """情绪面分析"""
        factors = []

        # 恐慌贪婪指数
        fgi_normalized = (context.fear_greed_index - 50) / 50
        factors.append(MarketFactor(
            name="fear_greed",
            dimension=MarketDimension.SENTIMENT,
            value=fgi_normalized,
            weight=self.factor_weights["market_sentiment"],
            confidence=0.75,
            description=f"恐慌贪婪指数 {context.fear_greed_index}/100 ({'贪婪' if context.fear_greed_index > 75 else '恐惧' if context.fear_greed_index < 25 else '中性'})",
        ))

        # 资金费率因子
        funding_normalized = min(max(context.funding_rate * 100, -1), 1)  # 限制在-1到1
        factors.append(MarketFactor(
            name="funding_sentiment",
            dimension=MarketDimension.SENTIMENT,
            value=funding_normalized,
            weight=0.1,
            confidence=0.7,
            description=f"资金费率 {context.funding_rate:.4%} ({'多头过热' if context.funding_rate > 0.01 else '空头过热' if context.funding_rate < -0.01 else '平衡'})",
        ))

        return factors

    def _analyze_fundamental(self, context: MarketContext) -> list[MarketFactor]:
        """资金面/基本面分析"""
        factors = []

        # 交易所资金流
        net_flow = context.exchange_inflow - context.exchange_outflow
        if net_flow != 0:
            flow_normalized = min(max(net_flow / 1000, -1), 1)  # 假设1000BTC为标准
            factors.append(MarketFactor(
                name="exchange_flow",
                dimension=MarketDimension.FUNDAMENTAL,
                value=-flow_normalized,  # 流入为负（看跌），流出为正（看涨）
                weight=self.factor_weights["fundamental_flow"],
                confidence=0.65,
                description=f"交易所净{'流入' if net_flow > 0 else '流出'} {abs(net_flow):.1f} BTC",
            ))

        # 巨鲸动向
        whale_value = {"accumulating": 0.5, "distributing": -0.5, "neutral": 0}.get(
            context.whale_movement, 0
        )
        factors.append(MarketFactor(
            name="whale_activity",
            dimension=MarketDimension.FUNDAMENTAL,
            value=whale_value,
            weight=0.1,
            confidence=0.6,
            description=f"巨鲸{context.whale_movement}",
        ))

        return factors

    def _adjust_factor_weights(self, factors: list[MarketFactor]) -> list[MarketFactor]:
        """根据市场环境动态调整因子权重"""
        # 高波动时增加技术面权重
        volatility_high = any(
            f.name == "volume_strength" and f.value > 0.7 for f in factors
        )

        # 有重大新闻时增加消息面权重
        has_major_news = any(f.dimension == MarketDimension.NEWS and f.confidence > 0.8 for f in factors)

        for factor in factors:
            if volatility_high and factor.dimension == MarketDimension.TECHNICAL:
                factor.weight *= 1.2
            if has_major_news and factor.dimension == MarketDimension.NEWS:
                factor.weight *= 1.3

        return factors

    def select_strategy(
        self,
        context: MarketContext,
        factors: list[MarketFactor]
    ) -> tuple[StrategyType, StrategyParameters]:
        """
        选择策略并优化参数

        基于因子分析结果选择最合适的策略，并在参数空间内优化
        """
        # 计算综合得分
        technical_score = sum(f.value * f.weight for f in factors if f.dimension == MarketDimension.TECHNICAL)
        news_score = sum(f.value * f.weight for f in factors if f.dimension == MarketDimension.NEWS)
        sentiment_score = sum(f.value * f.weight for f in factors if f.dimension == MarketDimension.SENTIMENT)

        # 策略选择逻辑
        strategy = self._determine_strategy(technical_score, news_score, sentiment_score, context)

        # 参数优化
        params = self._optimize_parameters(strategy, context, factors)

        return strategy, params

    def _determine_strategy(
        self,
        technical_score: float,
        news_score: float,
        sentiment_score: float,
        context: MarketContext
    ) -> StrategyType:
        """确定策略类型"""

        # 高影响新闻优先
        if abs(news_score) > 0.5:
            return StrategyType.NEWS_MOMENTUM if news_score > 0 else StrategyType.EVENT_ARBITRAGE

        # 强趋势
        if abs(technical_score) > 0.6:
            if context.trend == "up":
                return StrategyType.TREND_MOMENTUM if technical_score > 0.8 else StrategyType.TREND_FOLLOW
            else:
                return StrategyType.TREND_MOMENTUM if technical_score < -0.8 else StrategyType.TREND_FOLLOW

        # 震荡
        if context.trend == "sideways":
            return StrategyType.MEAN_REVERSION if context.rsi < 30 or context.rsi > 70 else StrategyType.RANGE_BOUND

        # 高波动
        if context.price_change_24h > 0.1:  # 24h涨跌超过10%
            return StrategyType.HIGH_VOLATILITY

        # 默认
        return StrategyType.TREND_FOLLOW

    def _optimize_parameters(
        self,
        strategy: StrategyType,
        context: MarketContext,
        factors: list[MarketFactor]
    ) -> StrategyParameters:
        """
        优化策略参数

        根据市场条件在参数空间内选择最优参数
        """
        params = StrategyParameters()

        # 根据波动率调整止盈止损
        volatility = context.price_change_24h
        if volatility > 0.05:  # 高波动
            params.take_profit_pct = 5.0
            params.stop_loss_pct = 3.0
        elif volatility < 0.02:  # 低波动
            params.take_profit_pct = 2.0
            params.stop_loss_pct = 1.5

        # 根据RSI调整入场区间
        if context.rsi > 70:
            params.entry_rsi_max = 80  # 允许追高超买
        elif context.rsi < 30:
            params.entry_rsi_min = 20  # 允许抄底超卖

        # 根据趋势强度调整仓位
        if context.trend_strength > 0.8:
            params.position_size_pct = 15.0  # 强趋势重仓
            params.max_leverage = 10
        elif context.trend_strength < 0.3:
            params.position_size_pct = 5.0   # 弱趋势轻仓
            params.max_leverage = 3

        return params

    def make_decision(self, context: MarketContext) -> TradingDecision:
        """
        生成交易决策

        综合分析所有维度，生成带完整上下文的决策
        """
        # 1. 多维度分析
        factors = self.analyze_market(context)

        # 2. 选择策略并优化参数
        strategy, params = self.select_strategy(context, factors)

        # 3. 确定主要驱动因子
        primary_factor = max(factors, key=lambda f: abs(f.value) * f.weight)

        # 4. 生成决策理由
        reasoning = self._generate_reasoning(context, factors, strategy, primary_factor)

        # 5. 计算置信度
        confidence = self._calculate_confidence(factors, context)

        # 6. 风险评估
        risk_assessment = self._assess_risk(context, strategy, params)

        # 7. 确定action
        action = self._determine_action(strategy, factors, context)

        return TradingDecision(
            symbol=context.symbol,
            timestamp=time.time(),
            action=action,
            strategy=strategy,
            strategy_params=params,
            position_size=params.position_size_pct,
            leverage=params.max_leverage if action != "hold" else 0,
            market_context=context,
            factors=factors,
            primary_factor=primary_factor.name,
            reasoning=reasoning,
            confidence=confidence,
            risk_assessment=risk_assessment,
            alternative_strategies=[],  # 可扩展
            expected_hold_time=24,
            expected_profit_pct=params.take_profit_pct,
            max_acceptable_loss_pct=params.stop_loss_pct,
        )

    def _generate_reasoning(
        self,
        context: MarketContext,
        factors: list[MarketFactor],
        strategy: StrategyType,
        primary_factor: MarketFactor
    ) -> str:
        """生成详细决策理由"""
        lines = [f"选择{strategy.value}策略，主要基于以下分析："]

        lines.append(f"\n1. 主要驱动因子：{primary_factor.description}")
        lines.append(f"   影响程度：{primary_factor.value:+.2f} (权重{primary_factor.weight:.0%})")

        lines.append("\n2. 技术面：")
        lines.append(f"   - 趋势：{context.trend} (强度{context.trend_strength:.0%})")
        lines.append(f"   - RSI：{context.rsi:.1f}")
        lines.append(f"   - 支撑/阻力：{context.support_levels[0] if context.support_levels else 'N/A'} / {context.resistance_levels[0] if context.resistance_levels else 'N/A'}")

        if context.recent_news:
            lines.append("\n3. 消息面：")
            for news in context.recent_news[:2]:
                lines.append(f"   - [{news.source}] {news.title[:40]}... (影响{news.impact_score:+.2f})")

        lines.append("\n4. 情绪面：")
        lines.append(f"   - 恐慌贪婪指数：{context.fear_greed_index}")
        lines.append(f"   - 资金费率：{context.funding_rate:.4%}")

        return "\n".join(lines)

    def _calculate_confidence(self, factors: list[MarketFactor], context: MarketContext) -> float:
        """计算决策置信度"""
        base_confidence = 0.5

        # 因子一致性越高，置信度越高
        factor_values = [f.value for f in factors]
        if factor_values:
            agreement = 1 - (max(factor_values) - min(factor_values)) / 2
            base_confidence += agreement * 0.2

        # 高权重因子置信度高
        high_conf_factors = sum(1 for f in factors if f.confidence > 0.7)
        base_confidence += min(high_conf_factors * 0.05, 0.15)

        # 趋势强度增加置信度
        base_confidence += context.trend_strength * 0.1

        return min(base_confidence, 0.95)

    def _assess_risk(
        self,
        context: MarketContext,
        strategy: StrategyType,
        params: StrategyParameters
    ) -> str:
        """风险评估"""
        risks = []

        if context.price_change_24h > 0.1:
            risks.append("24h涨幅过大，存在回调风险")

        if context.funding_rate > 0.02:
            risks.append("资金费率过高，多头过热")

        if params.max_leverage > 5:
            risks.append("使用高杠杆，注意仓位管理")

        if not risks:
            return "风险可控"

        return "；".join(risks)

    def _determine_action(
        self,
        strategy: StrategyType,
        factors: list[MarketFactor],
        context: MarketContext
    ) -> str:
        """确定具体行动"""
        composite_score = sum(f.value * f.weight for f in factors)

        if abs(composite_score) < 0.2:
            return "hold"

        if composite_score > 0:
            return "open_long"
        else:
            return "open_short"

    def record_execution(self, execution: TradeExecution):
        """记录交易执行结果，带完整上下文"""
        self.strategy_history.append(execution)

        # 提取消息影响用于学习
        if execution.decision.market_context.recent_news:
            for news in execution.decision.market_context.recent_news:
                self.news_impact_history.append({
                    "news": news.to_dict(),
                    "strategy": execution.decision.strategy.value,
                    "pnl": execution.pnl,
                    "timestamp": execution.entry_time,
                })

        logger.info(f"[SmartQuantEngine] 记录交易: {execution.decision.symbol} {execution.decision.strategy.value} PnL={execution.pnl:+.2f}")

    def analyze_strategy_effectiveness(self, strategy_id: str) -> dict:
        """
        分析策略有效性（带上下文）

        不是简单的胜率，而是分析在什么市场条件下表现好/差
        """
        executions = [e for e in self.strategy_history if e.decision.strategy.value == strategy_id]

        if not executions:
            return {"error": "无历史数据"}

        # 按市场状态分组统计
        results_by_condition = {
            "strong_trend": [],
            "ranging": [],
            "high_volatility": [],
            "with_major_news": [],
            "normal": [],
        }

        for e in executions:
            ctx = e.decision.market_context

            if ctx.trend_strength > 0.7:
                results_by_condition["strong_trend"].append(e.pnl)
            elif ctx.trend == "sideways":
                results_by_condition["ranging"].append(e.pnl)
            elif ctx.price_change_24h > 0.1:
                results_by_condition["high_volatility"].append(e.pnl)
            elif ctx.recent_news:
                results_by_condition["with_major_news"].append(e.pnl)
            else:
                results_by_condition["normal"].append(e.pnl)

        # 计算各条件下表现
        analysis = {}
        for condition, pnls in results_by_condition.items():
            if pnls:
                analysis[condition] = {
                    "trades": len(pnls),
                    "win_rate": sum(1 for p in pnls if p > 0) / len(pnls),
                    "avg_pnl": sum(pnls) / len(pnls),
                    "total_pnl": sum(pnls),
                }

        return {
            "strategy": strategy_id,
            "total_trades": len(executions),
            "overall_win_rate": sum(1 for e in executions if e.pnl > 0) / len(executions),
            "by_market_condition": analysis,
            "best_condition": max(analysis.items(), key=lambda x: x[1]["avg_pnl"])[0] if analysis else None,
            "worst_condition": min(analysis.items(), key=lambda x: x[1]["avg_pnl"])[0] if analysis else None,
        }


def create_smart_quant_engine() -> SmartQuantEngine:
    """创建智能量化引擎"""
    return SmartQuantEngine()


if __name__ == "__main__":
    # 测试
    engine = create_smart_quant_engine()

    # 构造测试上下文
    test_context = MarketContext(
        symbol="BTC",
        timestamp=time.time(),
        price=65000.0,
        price_change_24h=0.05,
        volume_24h=500000000,
        rsi=68,
        macd_signal="bullish",
        trend="up",
        trend_strength=0.75,
        support_levels=[63000, 61000],
        resistance_levels=[67000, 70000],
        recent_news=[
            NewsImpact(
                source="BlockBeats",
                title="美联储暗示可能降息",
                content="...",
                timestamp=time.time(),
                sentiment="positive",
                impact_score=0.6,
                urgency="short_term",
                affected_symbols=["BTC", "ETH"],
                category="macro",
                keywords=["fed", "rate cut"],
            )
        ],
        fear_greed_index=65,
        funding_rate=0.0005,
        open_interest_change=0.05,
        social_sentiment="positive",
        exchange_inflow=500,
        exchange_outflow=800,
        whale_movement="accumulating",
        network_activity="high",
        btc_dominance=0.52,
        eth_btc_ratio=0.055,
        usdt_premium=0.001,
        global_market_sentiment="bullish",
    )

    print("=" * 60)
    print("智能量化引擎测试")
    print("=" * 60)
    print(test_context.to_prompt())

    # 生成决策
    decision = engine.make_decision(test_context)

    print("\n" + "=" * 60)
    print("AI决策结果")
    print("=" * 60)
    print(f"行动: {decision.action}")
    print(f"策略: {decision.strategy.value}")
    print(f"参数: {decision.strategy_params.to_dict()}")
    print(f"主要驱动: {decision.primary_factor}")
    print(f"置信度: {decision.confidence:.1%}")
    print(f"风险评估: {decision.risk_assessment}")
    print(f"\n决策理由:\n{decision.reasoning}")
