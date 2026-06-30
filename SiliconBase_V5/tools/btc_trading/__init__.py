#!/usr/bin/env python3
"""
BTC 量化交易工具集 - Phase 1 基础适配
集成 btc_system_v1 到 SiliconBase V5

架构:
    - adapter: btc_system 输出适配层
    - base_tools: 基础查询工具
    - trading_tools: 交易执行工具 (Phase 3)
    - strategy_tools: 策略选择工具 (Phase 2)

作者: AI Assistant
版本: 1.0.0
日期: 2026-04-12
"""

# Phase 1: 基础适配
from .adapter import BTCTradingAdapter, adapt_btc_result
from .base_tools import (
    BTCAccountInfo,
    BTCMarketOverview,
    BTCPriceQuery,
    BTCTechnicalAnalysis,
)

# Phase 4: 风控与异常处理
from .risk_tools import (
    BTCCheckRecovery,
    BTCEmergencyStop,
    BTCIntervention,
    BTCRecoverTrading,
    BTCRiskCheck,
)

# Phase 2: 策略选择
from .strategy_tools import (
    BTCRiskAssessment,
    BTCStrategyExplain,
    BTCStrategySelector,
)

# Phase 3: 交易执行
from .trading_tools import (
    BTCConfirmTrade,
    BTCExecuteTrade,
    BTCGenerateReport,
    BTCGetProcessStatus,
    BTCLaunchAutopilot,
    BTCMonitorTrading,
    BTCStopAutopilot,
)

__all__ = [
    # 适配器
    "BTCTradingAdapter",
    "adapt_btc_result",
    # Phase 1 基础工具
    "BTCPriceQuery",
    "BTCMarketOverview",
    "BTCTechnicalAnalysis",
    "BTCAccountInfo",
    # Phase 2 策略工具
    "BTCStrategySelector",
    "BTCStrategyExplain",
    "BTCRiskAssessment",
    # Phase 3 交易工具
    "BTCLaunchAutopilot",
    "BTCGetProcessStatus",
    "BTCStopAutopilot",
    "BTCMonitorTrading",
    "BTCGenerateReport",
    "BTCConfirmTrade",
    "BTCExecuteTrade",
    # Phase 4 风控工具
    "BTCRiskCheck",
    "BTCEmergencyStop",
    "BTCIntervention",
    "BTCCheckRecovery",
    "BTCRecoverTrading",
]
