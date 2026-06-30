#!/usr/bin/env python3
"""
BTC交易执行工具
提供启动、停止、监控等交易操作
"""

from typing import Any

from core.btc_integration.event_bus import EventPriority, EventType
from core.logger import logger

from .base_btc_tool import BaseBTCTool


class BTCLaunchAutopilotTool(BaseBTCTool):
    """启动BTC自动交易工具"""

    tool_id = "btc_launch_autopilot"
    name = "启动BTC自动交易"
    description = """
    启动btc_system的autopilot进行自动量化交易。

    支持选择策略、设置时长和交易对。
    启动后会创建一个独立的交易进程，在后台自动执行交易策略。

    常用策略:
    - stage46_aggressive: 激进策略，适合趋势行情
    - stage148_livebase: 稳健策略，适合震荡行情
    - stage200_dualcore: 双核策略，多币种对冲

    返回包含process_id，可用于后续监控和停止。
    """

    input_schema = {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "description": "策略ID，如 stage46_aggressive",
                "default": "stage46_aggressive"
            },
            "duration_minutes": {
                "type": "integer",
                "description": "运行时长（分钟）",
                "default": 60,
                "minimum": 10,
                "maximum": 1440
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": '交易对列表，如 ["btc", "bnb"]',
                "default": ["btc"]
            }
        },
        "required": []
    }

    output_schema = {
        "type": "object",
        "properties": {
            "process_id": {"type": "string"},
            "status": {"type": "string"},
            "pid": {"type": "integer"}
        }
    }

    require_confirmation = True  # 需要用户确认

    def _execute(self,
                 strategy: str = "stage46_aggressive",
                 duration_minutes: int = 60,
                 symbols: list[str] = None,
                 **kwargs) -> dict[str, Any]:
        """执行启动交易"""
        try:
            symbols = symbols or ["btc"]

            # 启动autopilot
            success = self.client.start_autopilot(
                strategy=strategy,
                duration_minutes=duration_minutes,
                symbols=symbols,
                confirm_demo=True
            )

            if success:
                state = self.client.get_autopilot_state()
                # 显式emit策略启动事件（AI可观测）
                self._emit_to_eventbus(
                    event_type=EventType.STRATEGY_CHANGE,
                    data={
                        "status": "started",
                        "strategy": strategy,
                        "duration_minutes": duration_minutes,
                        "symbols": symbols,
                        "pid": state.pid,
                    },
                    priority=EventPriority.HIGH,
                    symbol=symbols[0].upper() if symbols else None,
                )
                return self._format_success({
                    "process_id": str(state.pid) if state.pid else "unknown",
                    "pid": state.pid,
                    "status": "started",
                    "strategy": strategy,
                    "duration": duration_minutes,
                    "symbols": symbols
                }, f"成功启动 {strategy} 策略的自动交易，运行时长 {duration_minutes} 分钟")
            else:
                return self._format_error(
                    "START_FAILED",
                    "启动交易失败，可能已有运行中的进程",
                    "交易启动失败，请检查是否已有运行中的交易进程"
                )

        except Exception as e:
            logger.error(f"[BTCLaunchAutopilotTool] 错误: {e}")
            return self._format_error(
                "EXECUTION_ERROR",
                str(e),
                "启动交易时发生错误"
            )


class BTCStopAutopilotTool(BaseBTCTool):
    """停止BTC自动交易工具"""

    tool_id = "btc_stop_autopilot"
    name = "停止BTC自动交易"
    description = "停止当前运行的btc_system autopilot交易进程"

    input_schema = {
        "type": "object",
        "properties": {
            "timeout": {
                "type": "integer",
                "description": "等待超时时间（秒）",
                "default": 30
            },
            "force": {
                "type": "boolean",
                "description": "是否强制终止",
                "default": False
            }
        }
    }

    require_confirmation = True

    def _execute(self, timeout: int = 30, force: bool = False, **kwargs) -> dict[str, Any]:
        """执行停止交易"""
        try:
            # 获取当前状态
            state = self.client.get_autopilot_state()

            if state.status not in ["running", "starting", "paused"]:
                return self._format_success({
                    "was_running": False,
                    "status": state.status
                }, "当前没有运行中的交易进程")

            # 停止交易
            success = self.client.stop_autopilot(timeout=timeout)

            if success:
                # 显式emit策略停止事件（AI可观测）
                self._emit_to_eventbus(
                    event_type=EventType.STRATEGY_CHANGE,
                    data={
                        "status": "stopped",
                        "previous_status": state.status,
                    },
                    priority=EventPriority.HIGH,
                )
                return self._format_success({
                    "was_running": True,
                    "stopped": True,
                    "previous_status": state.status
                }, "交易进程已成功停止")
            else:
                return self._format_error(
                    "STOP_FAILED",
                    "停止交易失败",
                    "停止交易时发生错误，请手动检查进程状态"
                )

        except Exception as e:
            logger.error(f"[BTCStopAutopilotTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))


class BTCMonitorTradingTool(BaseBTCTool):
    """监控BTC交易状态工具"""

    tool_id = "btc_monitor_trading"
    name = "监控BTC交易状态"
    description = """
    获取当前BTC交易的运行状态，包括：
    - 进程状态（运行中/已停止）
    - 当前持仓
    - 今日盈亏
    - Coinglass风险状态
    """

    input_schema = {
        "type": "object",
        "properties": {}
    }

    def _execute(self, **kwargs) -> dict[str, Any]:
        """获取交易状态"""
        try:
            state = self.client.get_autopilot_state()

            data = {
                "status": state.status,
                "pid": state.pid,
                "version": state.version,
                "strategy": state.strategy_name,
                "pnl_today": state.pnl_today,
                "trades_count": state.trades_count,
                "positions": state.positions,
                "coinglass_mode": state.coinglass_mode,
                "coinglass_reason": state.coinglass_reason,
                "last_update": state.last_update
            }

            # 生成状态描述
            status_desc = self._generate_status_description(state)

            return self._format_success(data, status_desc)

        except Exception as e:
            logger.error(f"[BTCMonitorTradingTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))

    def _generate_status_description(self, state) -> str:
        """生成状态描述文本"""
        if state.status == "running":
            desc = f"交易运行中 | 策略: {state.strategy_name} | "
            desc += f"今日盈亏: ${state.pnl_today:+.2f} | "
            desc += f"交易数: {state.trades_count}"
            if state.coinglass_mode:
                desc += f" | 风控: {state.coinglass_mode}"
            return desc
        elif state.status == "paused":
            return f"交易已暂停 | 策略: {state.strategy_name}"
        elif state.status == "stopped":
            return "交易已停止"
        else:
            return f"状态: {state.status}"


class BTCGenerateReportTool(BaseBTCTool):
    """生成BTC交易报告工具"""

    tool_id = "btc_generate_report"
    name = "生成BTC交易报告"
    description = "生成当前或历史的BTC交易报告"

    input_schema = {
        "type": "object",
        "properties": {
            "report_type": {
                "type": "string",
                "enum": ["status", "summary", "full"],
                "default": "status"
            }
        }
    }

    def _execute(self, report_type: str = "status", **kwargs) -> dict[str, Any]:
        """生成报告"""
        try:
            state = self.client.get_autopilot_state()

            if report_type == "status":
                data = {
                    "type": "status_report",
                    "status": state.status,
                    "pnl": state.pnl_today,
                    "positions": state.positions,
                    "timestamp": state.last_update
                }
                message = f"当前状态: {state.status} | 盈亏: ${state.pnl_today:+.2f}"

            elif report_type == "summary":
                data = {
                    "type": "summary_report",
                    "strategy": state.strategy_name,
                    "version": state.version,
                    "runtime_summary": "详见报告文件"
                }
                message = f"策略: {state.strategy_name} | 版本: {state.version}"

            else:  # full
                data = {
                    "type": "full_report",
                    "complete_state": state.__dict__
                }
                message = "完整报告已生成"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[BTCGenerateReportTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))
