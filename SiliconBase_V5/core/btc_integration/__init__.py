#!/usr/bin/env python3
"""
BTC 集成核心模块

功能:
    - 配置管理
    - 运行时监控
    - 风控检查
    - 与 btc_system 的进程间通信

架构:
    ┌─────────────────────────────────────┐
    │        BTCIntegrationCore           │
    ├─────────────────────────────────────┤
    │  ┌─────────┐  ┌─────────────────┐  │
    │  │ Config  │  │ ProcessManager  │  │
    │  │ Manager │  │                 │  │
    │  └────┬────┘  └────────┬────────┘  │
    │       └─────────────────┘           │
    │  ┌─────────┐  ┌─────────────────┐  │
    │  │ Risk    │  │ IPC (文件/Redis)│  │
    │  │ Monitor │  │                 │  │
    │  └─────────┘  └─────────────────┘  │
    └─────────────────────────────────────┘
"""

from .auto_trading_scheduler import (
    AutoTradingScheduler,
    AutoTradingStats,
    AutoTradingStatus,
    TradingSession,
    get_auto_trading_scheduler,
)
from .config import BTCTradingConfig, get_btc_config
from .intervention_system import (
    BTCInterventionSystem,
    InterventionCommand,
    InterventionPriority,
    InterventionResult,
    InterventionType,
    get_intervention_system,
)
from .living_system import (
    LivingTradingSystem,
    get_living_system,
)
from .process_guardian import (
    GuardianStatus,
    ProcessGuardian,
    create_guardian_for_process_manager,
)
from .process_manager import (
    BTCProcessManager,
    ProcessState,
    ProcessStatus,
    get_btc_process_manager,
)
from .recovery_manager import (
    BTCRecoveryManager,
    RecoveryResult,
    RecoveryState,
    TradingCheckpoint,
    get_recovery_manager,
)
from .resource_monitor import (
    ResourceAlertLevel,
    ResourceMonitor,
    create_default_monitor,
)
from .risk_monitor import (
    BTCRiskMonitor,
    RiskAssessment,
    RiskEvent,
    RiskEventType,
    RiskLevel,
    RiskThreshold,
    get_risk_monitor,
)
from .strategy_analyzer import (
    MarketCondition,
    StrategyAnalyzer,
    StrategyLibrary,
    StrategyRecommendation,
    get_strategy_analyzer,
)
from .trade_executor import (
    Account,
    BinanceExecutor,
    OKXExecutor,
    Order,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    SimulationExecutor,
    TradeExecutor,
    create_default_executor,
    create_executor,
)
from .workflow_definitions import (
    create_btc_monitor_workflow,
    create_btc_quick_trade_workflow,
    create_btc_trading_workflow,
)

# 导入用户交易管理器（仅在依赖缺失时降级）
try:
    from .user_trading_manager import (
        UserTradingManager,
        UserTradingSession,
        get_user_commander,
        get_user_trading_manager,
        initialize_user_trading_manager,
        shutdown_user_trading_manager,
    )
except ImportError as e:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        f"[BTCIntegration] 用户交易管理器导入失败（依赖缺失）: {e}"
    )
    UserTradingManager = None  # type: ignore
    UserTradingSession = None  # type: ignore
    def get_user_trading_manager():
        return None  # type: ignore
    def get_user_commander():
        return None  # type: ignore
    def initialize_user_trading_manager(*a, **k):
        return None  # type: ignore
    def shutdown_user_trading_manager(*a, **k):
        return None  # type: ignore

__all__ = [
    # 配置
    "BTCTradingConfig",
    "get_btc_config",
    # Phase 2 策略分析
    "StrategyAnalyzer",
    "StrategyLibrary",
    "MarketCondition",
    "StrategyRecommendation",
    "get_strategy_analyzer",
    # Phase 3 进程管理
    "BTCProcessManager",
    "ProcessState",
    "ProcessStatus",
    "get_btc_process_manager",
    # Phase 3 工作流
    "create_btc_trading_workflow",
    "create_btc_quick_trade_workflow",
    "create_btc_monitor_workflow",
    # Phase 4 风控
    "BTCRiskMonitor",
    "RiskThreshold",
    "RiskEvent",
    "RiskAssessment",
    "RiskLevel",
    "RiskEventType",
    "get_risk_monitor",
    # Phase 4 恢复
    "BTCRecoveryManager",
    "TradingCheckpoint",
    "RecoveryResult",
    "RecoveryState",
    "get_recovery_manager",
    # Phase 4 干预
    "BTCInterventionSystem",
    "InterventionCommand",
    "InterventionResult",
    "InterventionType",
    "InterventionPriority",
    "get_intervention_system",
    # 24小时自动交易（三层架构）
    "AutoTradingScheduler",
    "AutoTradingStatus",
    "TradingSession",
    "AutoTradingStats",
    "get_auto_trading_scheduler",
    # 进程守护
    "ProcessGuardian",
    "GuardianStatus",
    "create_guardian_for_process_manager",
    # 资源监控
    "ResourceMonitor",
    "ResourceAlertLevel",
    "create_default_monitor",
    # 活着的交易系统（三层整合）
    "LivingTradingSystem",
    "get_living_system",
    # TradeExecutor 抽象层
    "TradeExecutor",
    "SimulationExecutor",
    "OKXExecutor",
    "BinanceExecutor",
    "Order",
    "Position",
    "Account",
    "OrderSide",
    "OrderType",
    "PositionSide",
    "create_executor",
    "create_default_executor",
    # 用户交易管理器
    "UserTradingManager",
    "UserTradingSession",
    "get_user_trading_manager",
    "get_user_commander",
    "initialize_user_trading_manager",
    "shutdown_user_trading_manager",
]
