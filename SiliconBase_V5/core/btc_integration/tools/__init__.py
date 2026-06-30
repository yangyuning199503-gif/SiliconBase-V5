#!/usr/bin/env python3
"""
BTC交易工具集 - 兼容层
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

架构说明见: ARCHITECTURE.md

使用方法:
    # 1. 注册工具（系统启动时执行一次）
    from core.btc_integration.tools import register_btc_tools
    register_btc_tools(tool_manager)

    # 2. AI调用工具
    result = tool_manager.call_tool("btc_launch_autopilot", {
        "strategy": "stage46_aggressive",
        "duration_minutes": 60,
        "symbols": ["btc", "bnb"]
    })
"""

from typing import Any

from .auto_risk_gate_tool import AutoRiskGateTool
from .market_tools import KLinesTool, MarketOverviewTool
from .strategy_tools import BTCInterruptTool, BTCStatusQueryTool, RiskAssessmentTool, StrategySelectorTool

# 导入所有工具类
from .trading_tools import (
    BTCGenerateReportTool,
    BTCLaunchAutopilotTool,
    BTCMonitorTradingTool,
    BTCStopAutopilotTool,
)

__all__ = [
    # 工具类
    "BTCLaunchAutopilotTool",
    "BTCStopAutopilotTool",
    "BTCMonitorTradingTool",
    "BTCGenerateReportTool",
    "MarketOverviewTool",
    "KLinesTool",
    "StrategySelectorTool",
    "RiskAssessmentTool",
    "BTCStatusQueryTool",
    "BTCInterruptTool",
    "AutoRiskGateTool",
    # 注册函数
    "register_btc_tools",
    "get_btc_tool_instances",
]


# 工具实例缓存
_tool_instances: dict[str, Any] = {}


def get_btc_tool_instances() -> list[Any]:
    """
    获取所有BTC工具实例

    Returns:
        List[BaseTool]: 工具实例列表
    """
    global _tool_instances

    if not _tool_instances:
        _tool_instances = {
            # 交易执行工具
            "btc_launch_autopilot": BTCLaunchAutopilotTool(),
            "btc_stop_autopilot": BTCStopAutopilotTool(),
            "btc_monitor_trading": BTCMonitorTradingTool(),
            "btc_generate_report": BTCGenerateReportTool(),
            # 市场数据工具
            "btc_market_overview": MarketOverviewTool(),
            "btc_get_klines": KLinesTool(),
            # 策略工具
            "btc_strategy_selector": StrategySelectorTool(),
            "btc_risk_assessment": RiskAssessmentTool(),
            # AI可观测层工具
            "btc_status_query": BTCStatusQueryTool(),
            "btc_interrupt": BTCInterruptTool(),
            # 自动风控工具
            "btc_auto_risk_gate": AutoRiskGateTool(),
        }

    return list(_tool_instances.values())


def register_btc_tools(tool_manager) -> dict[str, bool]:
    """
    注册所有BTC交易工具到V5 ToolManager

    应该在系统启动时调用一次。

    Args:
        tool_manager: V5的ToolManager实例

    Returns:
        Dict[str, bool]: 各工具的注册结果

    Example:
        >>> from core.tool.tool_manager import tool_manager
        >>> from core.btc_integration.tools import register_btc_tools
        >>> results = register_btc_tools(tool_manager)
        >>> print(results)
        {'btc_launch_autopilot': True, 'btc_stop_autopilot': True, ...}
    """
    tools = get_btc_tool_instances()
    results = {}

    for tool in tools:
        try:
            tool_manager.register_tool(tool)
            results[tool.tool_id] = True
            print(f"[BTC Tools] ✅ 已注册: {tool.tool_id}")
        except Exception as e:
            results[tool.tool_id] = False
            print(f"[BTC Tools] ❌ 注册失败 {tool.tool_id}: {e}")

    # 打印汇总
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"[BTC Tools] 注册完成: {success_count}/{total_count} 成功")

    return results


# 便捷函数：检查BTC系统是否可用
def is_btc_system_available() -> bool:
    """检查BTC系统是否可用"""
    try:
        from core.btc_integration.btc_system_client import resolve_btc_system_path
        return resolve_btc_system_path() is not None
    except Exception:
        return False
