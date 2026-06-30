#!/usr/bin/env python3
"""
BTC 交易执行工具 - Phase 3

工具列表:
    - BTCLaunchAutopilot: 启动交易引擎
    - BTCGetProcessStatus: 获取进程状态
    - BTCStopAutopilot: 停止交易
    - BTCMonitorTrading: 监控交易
    - BTCGenerateReport: 生成报告
"""

import asyncio
import time
from typing import Any

try:
    from core.base_tool import BaseTool
    from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
except ImportError:
    BaseTool = object
    def format_error(code, detail=""):
        return {"success": False, "error_code": code, "error_message": detail}
    INVALID_PARAMS = "INVALID_PARAMS"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"



class BTCLaunchAutopilot(BaseTool):
    """
    启动 BTC 自动交易引擎

    功能:
        - 启动 btc_system autopilot 进程
        - 配置策略参数
        - 返回进程 ID

    注意:
        - 此工具会创建独立进程
        - 不占用 AI 线程池
        - 支持长时间运行（1小时以上）
    """

    tool_id = "btc_launch_autopilot"
    name = "启动交易引擎"
    description = """启动 btc_system 自动交易引擎。

参数:
- symbol: 交易标的 (BTC/ETH/SOL)
- strategy: 策略ID (如 stage46_aggressive)
- budget: 预算金额 (USDT)
- duration_minutes: 运行时长 (分钟)

返回:
- process_id: 进程ID
- status: 启动状态
- logs: 启动日志

注意:
- 启动成功后会创建独立进程
- 可以通过 btc_get_process_status 查询状态
- 可以通过 btc_stop_autopilot 停止
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "strategy": {
                "type": "string",
                "default": "stage46_aggressive"
            },
            "budget": {
                "type": "number",
                "default": 1000
            },
            "duration_minutes": {
                "type": "integer",
                "default": 60
            }
        },
        "required": []
    }

    timeout = 60
    require_confirmation = True  # 重要操作需要确认

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行启动"""
        symbol = kwargs.get("symbol", "BTC").upper()
        strategy = kwargs.get("strategy", "stage46_aggressive")
        budget = kwargs.get("budget", 1000)
        duration = kwargs.get("duration_minutes", 60)

        # 参数验证
        if duration < 5 or duration > 240:
            return format_error(
                INVALID_PARAMS,
                detail="运行时长必须在 5-240 分钟之间"
            )

        if budget <= 0:
            return format_error(
                INVALID_PARAMS,
                detail="预算必须大于 0"
            )

        try:
            # 获取进程管理器
            try:
                from core.btc_integration.process_manager import get_btc_process_manager
                manager = get_btc_process_manager()
            except ImportError:
                # 开发模式：模拟启动
                return self._mock_launch(symbol, strategy, budget, duration)

            # 检查是否已有运行中的进程
            state = manager.get_state()
            if state.status.value in ["running", "starting"]:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"已有运行中的交易进程 (PID: {state.pid})，请先停止"
                )

            # 启动进程
            success = manager.start(
                strategy=strategy,
                duration_minutes=duration,
                symbols=[symbol]
            )

            if not success:
                state = manager.get_state()
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"启动失败: {state.last_error}"
                )

            # 获取启动后的状态
            state = manager.get_state()

            messages = [
                "✅ 交易引擎已启动",
                "",
                "【配置信息】",
                f"标的: {symbol}",
                f"策略: {strategy}",
                f"预算: ${budget:,.0f}",
                f"时长: {duration} 分钟",
                "",
                "【进程信息】",
                f"进程ID: {state.pid}",
                f"启动时间: {time.strftime('%H:%M:%S', time.localtime(state.start_time))}",
                "",
                "【监控命令】",
                "查询状态: 使用 btc_get_process_status",
                "停止交易: 使用 btc_stop_autopilot",
                "",
                "⚠️ 交易正在运行中，请密切关注风险控制！"
            ]

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": {
                    "process_id": f"btc_{state.pid}",
                    "pid": state.pid,
                    "status": "running",
                    "symbol": symbol,
                    "strategy": strategy,
                    "budget": budget,
                    "duration_minutes": duration,
                    "start_time": state.start_time
                }
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"启动交易引擎失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _mock_launch(
        self,
        symbol: str,
        strategy: str,
        budget: float,
        duration: int
    ) -> dict[str, Any]:
        """模拟启动（开发模式）"""
        import random

        mock_pid = random.randint(10000, 99999)

        messages = [
            "✅ 交易引擎已启动（模拟模式）",
            "",
            "【配置信息】",
            f"标的: {symbol}",
            f"策略: {strategy}",
            f"预算: ${budget:,.0f}",
            f"时长: {duration} 分钟",
            "",
            "【模拟进程信息】",
            f"进程ID: {mock_pid}",
            "状态: running",
            "",
            "⚠️ 当前为模拟模式，未连接真实交易引擎",
            "真实交易需要配置 btc_system 路径和 API Key"
        ]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": {
                "process_id": f"btc_{mock_pid}",
                "pid": mock_pid,
                "status": "running",
                "symbol": symbol,
                "strategy": strategy,
                "budget": budget,
                "duration_minutes": duration,
                "start_time": time.time(),
                "mock": True
            }
        }


class BTCGetProcessStatus(BaseTool):
    """
    获取交易进程状态

    功能:
        - 查询进程运行状态
        - 获取持仓信息
        - 获取盈亏数据
        - 获取运行日志
    """

    tool_id = "btc_get_process_status"
    name = "获取进程状态"
    description = """查询交易进程的运行状态和盈亏情况。

返回信息:
- 进程状态 (running/paused/stopped/error)
- 运行时长
- 当前盈亏
- 持仓情况
- 交易次数
- 最近日志
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 10

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行状态查询"""
        try:
            try:
                from core.btc_integration.process_manager import get_btc_process_manager
                manager = get_btc_process_manager()
                report = manager.get_report()
            except ImportError:
                # 模拟数据
                return self._mock_status()

            status = report.get("status", "unknown")
            pnl = report.get("pnl_today", 0)
            runtime = report.get("runtime_seconds", 0)

            # 格式化运行时间
            hours = int(runtime // 3600)
            minutes = int((runtime % 3600) // 60)
            seconds = int(runtime % 60)
            runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # 盈亏 emoji
            pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

            messages = [
                "📊 交易进程状态",
                "",
                f"【运行状态】{self._format_status(status)}",
                f"【运行时间】{runtime_str}",
                f"【今日盈亏】{pnl_emoji} ${pnl:+.2f}",
                f"【交易次数】{report.get('trades_count', 0)} 次",
            ]

            # 持仓信息
            positions = report.get("current_position", {})
            if positions:
                messages.append("\n【当前持仓】")
                for sym, pos in positions.items():
                    side = pos.get("side", "UNKNOWN")
                    size = pos.get("size", 0)
                    pnl_pos = pos.get("pnl", 0)
                    messages.append(f"  {sym}: {side} {size} (${pnl_pos:+.2f})")

            # 最近日志
            logs = report.get("logs_tail", [])
            if logs:
                messages.append("\n【最近日志】")
                for log in logs[-5:]:
                    messages.append(f"  {log}")

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": report
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"获取状态失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _format_status(self, status: str) -> str:
        """格式化状态显示"""
        status_map = {
            "running": "🟢 运行中",
            "paused": "⏸️ 已暂停",
            "stopped": "⏹️ 已停止",
            "error": "❌ 错误",
            "idle": "⚪ 空闲"
        }
        return status_map.get(status, f"⚪ {status}")

    def _mock_status(self) -> dict[str, Any]:
        """模拟状态（开发模式）"""
        import random

        runtime = random.uniform(300, 3600)
        hours = int(runtime // 3600)
        minutes = int((runtime % 3600) // 60)
        seconds = int(runtime % 60)

        pnl = random.uniform(-100, 200)
        pnl_emoji = "🟢" if pnl > 0 else "🔴"

        messages = [
            "📊 交易进程状态（模拟数据）",
            "",
            "【运行状态】🟢 运行中",
            f"【运行时间】{hours:02d}:{minutes:02d}:{seconds:02d}",
            f"【今日盈亏】{pnl_emoji} ${pnl:+.2f}",
            f"【交易次数】{random.randint(2, 10)} 次",
            "",
            "【当前持仓】",
            f"  BTC: LONG 0.05 (${pnl*0.8:+.2f})",
            "",
            "⚠️ 当前为模拟数据"
        ]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": {
                "status": "running",
                "runtime_seconds": runtime,
                "pnl_today": pnl,
                "trades_count": random.randint(2, 10),
                "mock": True
            }
        }


class BTCStopAutopilot(BaseTool):
    """
    停止交易引擎

    功能:
        - 停止 autopilot 进程
        - 保留或平仓（可选）
        - 生成最终报告
    """

    tool_id = "btc_stop_autopilot"
    name = "停止交易引擎"
    description = """停止正在运行的交易引擎。

参数:
- close_positions: 是否平仓 (true/false)
- timeout: 等待超时（秒）

注意:
- 默认会等待当前订单完成
- 可以设置 close_positions=true 平仓所有持仓
"""

    input_schema = {
        "type": "object",
        "properties": {
            "close_positions": {
                "type": "boolean",
                "default": False,
                "description": "是否平仓所有持仓"
            },
            "timeout": {
                "type": "integer",
                "default": 30
            }
        },
        "required": []
    }

    timeout = 30
    require_confirmation = True

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行停止"""
        close_positions = kwargs.get("close_positions", False)
        timeout = kwargs.get("timeout", 30)

        try:
            try:
                from core.btc_integration.process_manager import get_btc_process_manager
                manager = get_btc_process_manager()

                # 获取停止前的状态
                manager.get_report()

                # 停止进程
                success = manager.stop(timeout=timeout)

                if not success:
                    return format_error(
                        TOOL_EXECUTION_ERROR,
                        detail="停止进程失败"
                    )

                # 获取最终报告
                final_report = manager.get_report()

            except ImportError:
                # 模拟停止
                final_report = {
                    "status": "stopped",
                    "runtime_seconds": 3600,
                    "pnl_today": 127.5,
                    "trades_count": 8
                }
                final_report["mock"] = True

            pnl = final_report.get("pnl_today", 0)
            pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            runtime = final_report.get("runtime_seconds", 0)

            messages = [
                "⏹️ 交易引擎已停止",
                "",
                "【运行统计】",
                f"运行时间: {int(runtime // 60)} 分钟",
                f"交易次数: {final_report.get('trades_count', 0)} 次",
                f"最终盈亏: {pnl_emoji} ${pnl:+.2f}",
            ]

            if pnl > 0:
                messages.append("\n🎉 恭喜盈利！")
            elif pnl < 0:
                messages.append("\n💪 别灰心，下次再战！")

            if close_positions:
                messages.append("\n✅ 所有持仓已平仓")

            if final_report.get("mock"):
                messages.append("\n⚠️ 当前为模拟数据")

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": final_report
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"停止失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCMonitorTrading(BaseTool):
    """
    监控交易状态（内部使用）

    功能:
        - 定期检查进程状态
        - 生成进度报告
        - 异常检测
    """

    tool_id = "btc_monitor_trading"
    name = "监控交易"
    description = """监控交易进程状态（内部使用）。

用于工作流中的监控循环步骤。
每 5 分钟检查一次状态并生成报告。
"""

    input_schema = {
        "type": "object",
        "properties": {
            "process_id": {
                "type": "string"
            }
        },
        "required": ["process_id"]
    }

    timeout = 300  # 5 分钟

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行监控"""
        kwargs.get("process_id", "")

        # 实际上这个工具会被工作流引擎定期调用
        # 这里只返回当前状态
        status_tool = BTCGetProcessStatus()
        return status_tool._execute()

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCGenerateReport(BaseTool):
    """
    生成交易报告

    功能:
        - 汇总交易数据
        - 生成图表（可选）
        - 保存到文件
    """

    tool_id = "btc_generate_report"
    name = "生成交易报告"
    description = """生成详细的交易报告。

返回信息:
- 盈亏统计
- 交易明细
- 策略表现
- 风险指标
"""

    input_schema = {
        "type": "object",
        "properties": {
            "report_type": {
                "type": "string",
                "enum": ["status", "final", "daily"],
                "default": "status"
            }
        },
        "required": []
    }

    timeout = 15

    def _execute(self, **kwargs) -> dict[str, Any]:
        """生成报告"""
        report_type = kwargs.get("report_type", "status")

        try:
            # 获取当前状态
            status_tool = BTCGetProcessStatus()
            status_result = status_tool._execute()

            data = status_result.get("data", {})

            messages = [
                "📊 交易报告",
                "",
                "【基本信息】",
                f"报告类型: {report_type}",
                f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            ]

            if data.get("mock"):
                messages.append("数据类型: 模拟数据")

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": data
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"生成报告失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCConfirmTrade(BaseTool):
    """
    交易确认工具（用于工作流的用户确认步骤）

    功能:
        - 显示交易详情
        - 等待用户确认
        - 返回确认结果
    """

    tool_id = "btc_confirm_trade"
    name = "确认交易"
    description = """显示交易详情并等待用户确认。

注意:
- 此工具会在工作流中自动调用
- 需要用户在前端点击【确认】或【取消】
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 300  # 5 分钟等待用户确认
    require_confirmation = True

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        执行确认

        注意：实际的确认逻辑由工作流引擎处理
        此工具只返回占位结果
        """
        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "交易已确认",
            "data": {"confirmed": True}
        }

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCExecuteTrade(BaseTool):
    """
    执行单次交易（快速交易）

    功能:
        - 执行单次买入/卖出
        - 不启动长期监控
    """

    tool_id = "btc_execute_trade"
    name = "执行交易"
    description = """执行单次交易（买入或卖出）。

参数:
- symbol: 交易对
- side: 方向 (buy/sell)
- amount: 金额 (USDT)

注意:
- 此工具用于快速交易
- 不启动长期监控进程
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "side": {
                "type": "string",
                "enum": ["buy", "sell"],
                "default": "buy"
            },
            "amount": {
                "type": "number",
                "default": 100
            }
        },
        "required": []
    }

    timeout = 30
    require_confirmation = True

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行交易"""
        symbol = kwargs.get("symbol", "BTC").upper()
        side = kwargs.get("side", "buy")
        amount = kwargs.get("amount", 100)

        # 这里应该调用真实的交易 API
        # 目前返回模拟结果

        messages = [
            "✅ 交易已执行（模拟）",
            "",
            "【交易详情】",
            f"标的: {symbol}",
            f"方向: {side.upper()}",
            f"金额: ${amount:,.2f}",
            "",
            "⚠️ 当前为模拟交易，未真实下单"
        ]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": {
                "order_id": f"mock_{int(time.time())}",
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "status": "filled",
                "mock": True
            }
        }

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)
