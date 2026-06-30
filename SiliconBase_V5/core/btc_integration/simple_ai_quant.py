#!/usr/bin/env python3
"""
极简AI量化框架
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于用户的核心理念：
- AI不发明策略，只做选择
- 固定策略池，长期跑数据优胜劣汰
- 行情识别 + 策略选择 + 仓位控制

策略池（固定5个，不增不减）:
1. 趋势跟踪(Trend)      - 强趋势行情
2. 均值回归(MeanRev)    - 震荡行情
3. 突破交易(Breakout)   - 关键位突破
4. 事件驱动(Event)      - 高波动/重大新闻
5. 多资产分散(Diversified) - 行情不明/分散风险
"""

import time
from dataclasses import dataclass, field
from enum import Enum

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MarketState(Enum):
    """市场状态 - AI只需要识别这5种"""
    STRONG_TREND_UP = "strong_trend_up"      # 强上涨趋势
    STRONG_TREND_DOWN = "strong_trend_down"  # 强下跌趋势
    RANGING = "ranging"                      # 震荡
    HIGH_VOLATILITY = "high_volatility"      # 高波动（事件/新闻）
    UNCLEAR = "unclear"                      # 不明/混沌


class StrategySlot(Enum):
    """策略槽位 - 固定5个策略"""
    TREND_FOLLOWING = "trend_following"      # 趋势跟踪
    MEAN_REVERSION = "mean_reversion"        # 均值回归
    BREAKOUT = "breakout"                    # 突破交易
    EVENT_DRIVEN = "event_driven"            # 事件驱动
    DIVERSIFIED = "diversified"              # 多资产分散


@dataclass
class StrategyPerformance:
    """策略表现记录 - 用于优胜劣汰"""
    strategy_id: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    pnl_total: float = 0.0
    max_drawdown: float = 0.0
    last_used: float = 0.0
    score: float = 0.0  # 综合评分

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    def update_score(self):
        """更新综合评分 - 胜率+盈亏比+回撤加权"""
        if self.total_trades < 5:  # 数据不足，中性分
            self.score = 50.0
            return

        win_rate_score = self.win_rate * 100  # 胜率权重40%

        # 盈亏比
        avg_win = self.pnl_total / self.wins if self.wins > 0 else 0
        avg_loss = abs(self.pnl_total / self.losses) if self.losses > 0 else 1
        profit_ratio = avg_win / avg_loss if avg_loss > 0 else 1
        profit_score = min(profit_ratio * 30, 30)  # 盈亏比权重30%

        # 回撤惩罚
        drawdown_score = max(0, 30 - abs(self.max_drawdown))  # 回撤权重30%

        self.score = win_rate_score * 0.4 + profit_score + drawdown_score


@dataclass
class MarketContext:
    """市场上下文 - AI识别的输入"""
    trend: str = "sideways"           # up/down/sideways
    trend_strength: float = 0.0       # 0-1
    volatility: float = 0.0           # 波动率
    rsi: float = 50.0                 # RSI
    has_major_news: bool = False      # 是否有重大新闻
    news_sentiment: str = "neutral"   # positive/negative/neutral
    btc_dominance: float = 0.0        # BTC市值占比
    funding_rate: float = 0.0         # 资金费率
    timestamp: float = field(default_factory=time.time)

    def to_prompt(self) -> str:
        """转换为AI识别的prompt"""
        return f"""当前市场状态:
- 趋势: {self.trend} (强度: {self.trend_strength:.2f})
- 波动率: {self.volatility:.2%}
- RSI: {self.rsi:.1f}
- 重大新闻: {'有' if self.has_major_news else '无'} (情绪: {self.news_sentiment})
- 资金费率: {self.funding_rate:.4%}
"""


@dataclass
class AllocationResult:
    """仓位分配结果"""
    market_state: MarketState
    allocations: dict[StrategySlot, float]  # 各策略仓位比例
    confidence: float  # AI对判断的置信度
    reasoning: str

    @property
    def primary_strategy(self) -> StrategySlot:
        """主要策略（仓位最高的）"""
        return max(self.allocations.items(), key=lambda x: x[1])[0]


class SimpleAIQuant:
    """
    极简AI量化引擎

    核心逻辑:
    1. AI识别市场状态（5选1）
    2. 根据预设映射选择策略
    3. 根据策略历史表现调整仓位
    """

    # 市场状态 → 策略映射（固定规则，AI不创造）
    STATE_STRATEGY_MAP = {
        MarketState.STRONG_TREND_UP: {
            StrategySlot.TREND_FOLLOWING: 0.7,
            StrategySlot.BREAKOUT: 0.2,
            StrategySlot.DIVERSIFIED: 0.1,
        },
        MarketState.STRONG_TREND_DOWN: {
            StrategySlot.TREND_FOLLOWING: 0.7,
            StrategySlot.BREAKOUT: 0.2,
            StrategySlot.DIVERSIFIED: 0.1,
        },
        MarketState.RANGING: {
            StrategySlot.MEAN_REVERSION: 0.6,
            StrategySlot.DIVERSIFIED: 0.3,
            StrategySlot.BREAKOUT: 0.1,
        },
        MarketState.HIGH_VOLATILITY: {
            StrategySlot.EVENT_DRIVEN: 0.4,
            StrategySlot.DIVERSIFIED: 0.4,
            StrategySlot.TREND_FOLLOWING: 0.2,
        },
        MarketState.UNCLEAR: {
            StrategySlot.DIVERSIFIED: 0.8,
            StrategySlot.MEAN_REVERSION: 0.2,
        },
    }

    def __init__(self):
        # 策略表现跟踪（优胜劣汰数据）
        self.strategy_perf: dict[str, StrategyPerformance] = {
            slot.value: StrategyPerformance(strategy_id=slot.value)
            for slot in StrategySlot
        }

        # 当前分配
        self.current_allocation: AllocationResult | None = None

        # 历史市场状态（用于分析准确率）
        self.state_history: list[tuple[MarketState, float, float]] = []  # (状态, 时间, 后续收益)

        logger.info("[SimpleAIQuant] 极简AI量化引擎初始化完成")
        logger.info(f"[SimpleAIQuant] 策略池: {[s.value for s in StrategySlot]}")

    def detect_market_state(self, context: MarketContext) -> MarketState:
        """
        识别市场状态 - 规则+AI混合

        先用规则快速判断，AI只负责确认和微调
        """
        # 规则判断（硬逻辑）
        if context.has_major_news and context.volatility > 0.05:
            return MarketState.HIGH_VOLATILITY

        if context.trend_strength > 0.7:
            if context.trend == "up":
                return MarketState.STRONG_TREND_UP
            elif context.trend == "down":
                return MarketState.STRONG_TREND_DOWN

        if context.volatility < 0.02 and abs(context.rsi - 50) < 10:
            return MarketState.RANGING

        # 不明状态
        return MarketState.UNCLEAR

    def allocate(self, context: MarketContext) -> AllocationResult:
        """
        仓位分配 - 核心决策

        1. 识别市场状态
        2. 根据状态获取基础分配
        3. 根据策略表现调整权重
        """
        # 1. 识别状态
        market_state = self.detect_market_state(context)

        # 2. 获取基础分配
        base_allocation = self.STATE_STRATEGY_MAP[market_state].copy()

        # 3. 根据策略表现调整
        adjusted = self._adjust_by_performance(base_allocation)

        # 4. 归一化
        total = sum(adjusted.values())
        allocations = {k: v/total for k, v in adjusted.items()}

        # 5. 生成reasoning
        reasoning = self._generate_reasoning(market_state, allocations, context)

        result = AllocationResult(
            market_state=market_state,
            allocations=allocations,
            confidence=self._calc_confidence(context),
            reasoning=reasoning
        )

        self.current_allocation = result

        # 记录
        self.state_history.append((market_state, time.time(), 0.0))

        logger.info(f"[SimpleAIQuant] 状态识别: {market_state.value}")
        logger.info(f"[SimpleAIQuant] 策略分配: {allocations}")

        return result

    def _adjust_by_performance(
        self,
        base_allocation: dict[StrategySlot, float]
    ) -> dict[StrategySlot, float]:
        """根据策略表现调整权重"""
        adjusted = {}

        for slot, base_weight in base_allocation.items():
            perf = self.strategy_perf[slot.value]
            perf.update_score()

            # 评分低于30的策略，权重减半
            if perf.score < 30:
                adjusted[slot] = base_weight * 0.5
            # 评分高于70的策略，权重增加50%
            elif perf.score > 70:
                adjusted[slot] = base_weight * 1.5
            else:
                adjusted[slot] = base_weight

        return adjusted

    def _calc_confidence(self, context: MarketContext) -> float:
        """计算AI对判断的置信度"""
        confidence = 0.5

        # 趋势强度越高，置信度越高
        confidence += context.trend_strength * 0.3

        # 波动率适中时置信度高
        if 0.01 < context.volatility < 0.05:
            confidence += 0.1

        # 有明确新闻信号时置信度高
        if context.has_major_news:
            confidence += 0.1

        return min(confidence, 0.95)

    def _generate_reasoning(
        self,
        state: MarketState,
        allocations: dict[StrategySlot, float],
        context: MarketContext
    ) -> str:
        """生成决策理由"""
        primary = max(allocations.items(), key=lambda x: x[1])

        reasons = {
            MarketState.STRONG_TREND_UP: f"检测到强上涨趋势(强度{context.trend_strength:.0%})，主要使用趋势跟踪策略",
            MarketState.STRONG_TREND_DOWN: f"检测到强下跌趋势(强度{context.trend_strength:.0%})，主要使用趋势跟踪策略做空",
            MarketState.RANGING: f"市场处于震荡区间(RSI{context.rsi:.0f})，使用均值回归策略高抛低吸",
            MarketState.HIGH_VOLATILITY: f"高波动环境(波动率{context.volatility:.1%})，{ '有' if context.has_major_news else '无' }重大新闻，谨慎分散",
            MarketState.UNCLEAR: "行情不明朗，优先风险控制，主要使用分散策略",
        }

        base_reason = reasons.get(state, "未知状态")
        return f"{base_reason}。主要策略: {primary[0].value}({primary[1]:.0%})"

    def record_trade_result(
        self,
        strategy_id: str,
        pnl: float,
        context: MarketContext
    ):
        """
        记录交易结果 - 用于优胜劣汰

        Args:
            strategy_id: 策略ID
            pnl: 盈亏金额（正数盈利，负数亏损）
            context: 当时的市况
        """
        if strategy_id not in self.strategy_perf:
            logger.warning(f"[SimpleAIQuant] 未知策略: {strategy_id}")
            return

        perf = self.strategy_perf[strategy_id]
        perf.total_trades += 1
        perf.pnl_total += pnl
        perf.last_used = time.time()

        if pnl > 0:
            perf.wins += 1
        else:
            perf.losses += 1
            # 更新最大回撤
            drawdown = abs(pnl)
            if drawdown > perf.max_drawdown:
                perf.max_drawdown = drawdown

        # 更新评分
        perf.update_score()

        logger.info(
            f"[SimpleAIQuant] {strategy_id} 交易记录: PnL={pnl:+.2f}, "
            f"胜率={perf.win_rate:.1%}, 评分={perf.score:.1f}"
        )

    def get_strategy_ranking(self) -> list[tuple[str, float, int]]:
        """
        获取策略排名

        Returns:
            [(策略ID, 评分, 交易次数), ...] 按评分排序
        """
        rankings = []
        for strategy_id, perf in self.strategy_perf.items():
            perf.update_score()
            rankings.append((strategy_id, perf.score, perf.total_trades))

        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def get_summary(self) -> dict:
        """获取策略表现摘要"""
        total_trades = sum(p.total_trades for p in self.strategy_perf.values())
        total_pnl = sum(p.pnl_total for p in self.strategy_perf.values())

        return {
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "strategy_ranking": self.get_strategy_ranking(),
            "current_allocation": {
                k.value: v
                for k, v in (self.current_allocation.allocations.items()
                           if self.current_allocation else {})
            } if self.current_allocation else None,
            "current_state": self.current_allocation.market_state.value
                           if self.current_allocation else None,
        }


# 便捷函数
def create_simple_quant() -> SimpleAIQuant:
    """创建极简AI量化引擎"""
    return SimpleAIQuant()


if __name__ == "__main__":
    # 测试
    quant = create_simple_quant()

    # 模拟不同市场环境
    contexts = [
        MarketContext(trend="up", trend_strength=0.8, volatility=0.03, rsi=65),
        MarketContext(trend="sideways", trend_strength=0.2, volatility=0.01, rsi=48),
        MarketContext(trend="up", trend_strength=0.5, volatility=0.08, rsi=70, has_major_news=True),
        MarketContext(trend="down", trend_strength=0.85, volatility=0.04, rsi=35),
    ]

    for i, ctx in enumerate(contexts):
        print(f"\n=== 场景{i+1} ===")
        print(ctx.to_prompt())

        result = quant.allocate(ctx)
        print(f"识别状态: {result.market_state.value}")
        print(f"策略分配: {result.allocations}")
        print(f"置信度: {result.confidence:.1%}")
        print(f"理由: {result.reasoning}")
