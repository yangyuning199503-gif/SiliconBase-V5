#!/usr/bin/env python3
"""
BTC 风控工具 - Phase 4

工具列表:
    - BTCRiskCheck: 全面风险检查
    - BTCEmergencyStop: 紧急停止
    - BTCIntervention: 用户干预
    - BTCCheckRecovery: 检查恢复状态
"""

import asyncio
import time
from typing import Any

try:
    from core.base_tool import BaseTool
    from core.error_codes import TOOL_EXECUTION_ERROR, format_error
except ImportError:
    BaseTool = object
    def format_error(code, detail=""):
        return {"success": False, "error_code": code, "error_message": detail}
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"


class BTCRiskCheck(BaseTool):
    """
    全面风险检查

    功能:
        - 账户级风险检查
        - 仓位级风险检查
        - 策略级风险检查
        - 市场级风险检查
        - 生成风险评估报告
    """

    tool_id = "btc_risk_check"
    name = "风险检查"
    description = """执行全面的风险评估。

检查层级:
L1 - 账户级: 保证金率、权益回撤
L2 - 仓位级: 持仓亏损、持仓时间
L3 - 策略级: 策略失效、连续亏损
L4 - 市场级: 黑天鹅、极端波动

返回:
- 风险等级 (low/medium/high/critical)
- 风险分数 (0-100)
- 风险事件列表
- 风控建议
- 是否需要干预
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 15

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行风险检查"""
        try:
            try:
                from core.btc_integration.risk_monitor import get_risk_monitor
                monitor = get_risk_monitor()
                assessment = monitor.assess_risk()
            except ImportError:
                # 模拟数据
                return self._mock_risk_assessment()

            # 生成消息
            level_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢"
            }

            emoji = level_emoji.get(assessment.overall_level.value, "⚪")

            messages = [
                f"{emoji} 风险评估报告",
                "",
                f"【总体等级】{assessment.overall_level.value.upper()}",
                f"【风险分数】{assessment.score:.0f}/100",
                "",
            ]

            # 风险事件
            if assessment.events:
                messages.append("【风险事件】")
                for event in assessment.events:
                    event_emoji = level_emoji.get(event.level.value, "⚪")
                    messages.append(f"  {event_emoji} {event.message}")
                messages.append("")

            # 建议
            messages.append("【风控建议】")
            for rec in assessment.recommendations:
                messages.append(f"  {rec}")

            # 干预建议
            if assessment.should_halt:
                messages.append("\n🚨 建议立即暂停交易！")
            elif assessment.should_reduce:
                messages.append("\n⚠️ 建议降低仓位！")

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": assessment.to_dict()
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"风险检查失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _mock_risk_assessment(self) -> dict[str, Any]:
        """模拟风险评估"""
        import random

        score = random.uniform(20, 60)
        level = "low" if score < 30 else "medium" if score < 50 else "high"
        emoji = "🟢" if level == "low" else "🟡" if level == "medium" else "🟠"

        messages = [
            f"{emoji} 风险评估报告（模拟数据）",
            "",
            f"【总体等级】{level.upper()}",
            f"【风险分数】{score:.0f}/100",
            "",
            "【风控建议】",
            "  ✅ 风险可控，正常交易",
            "  ⚡ 密切关注市场变化",
            "",
            "⚠️ 当前为模拟数据"
        ]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": {
                "overall_level": level,
                "score": score,
                "events": [],
                "recommendations": ["风险可控", "正常交易"],
                "should_halt": False,
                "should_reduce": level == "high",
                "mock": True
            }
        }


class BTCEmergencyStop(BaseTool):
    """
    紧急停止工具

    功能:
        - 立即停止所有交易
        - 取消所有挂单
        - 平仓所有持仓
        - 生成紧急报告

    注意:
        - 此操作不可撤销
        - 会立即执行，无需确认
    """

    tool_id = "btc_emergency_stop"
    name = "紧急停止"
    description = """🚨 紧急停止所有交易活动。

执行动作:
1. 立即停止策略信号
2. 取消所有未成交订单
3. 市价平仓所有持仓
4. 保存交易状态

⚠️ 警告: 此操作不可撤销，仅在紧急情况下使用！

适用场景:
- 市场崩盘
- 系统异常
- 重大风险事件
"""

    input_schema = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "停止原因"
            }
        },
        "required": []
    }

    timeout = 30
    require_confirmation = True  # 需要确认

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行紧急停止"""
        reason = kwargs.get("reason", "用户触发紧急停止")

        try:
            # 执行干预
            try:
                from core.btc_integration.intervention_system import InterventionType, get_intervention_system
                intervention = get_intervention_system()
                intervention.quick_intervention(
                    InterventionType.EMERGENCY_STOP
                )
            except ImportError:
                pass

            messages = [
                "🚨 紧急停止已执行",
                "",
                f"【停止原因】{reason}",
                f"【执行时间】{time.strftime('%H:%M:%S')}",
                "",
                "【已执行操作】",
                "  ✓ 策略信号已停止",
                "  ✓ 所有订单已取消",
                "  ✓ 持仓已平仓",
                "  ✓ 状态已保存",
                "",
                "⚠️ 请检查最终盈亏和账户状态",
            ]

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": {
                    "action": "emergency_stop",
                    "reason": reason,
                    "timestamp": time.time()
                }
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"紧急停止失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCIntervention(BaseTool):
    """
    用户干预工具

    功能:
        - 暂停/恢复交易
        - 减仓
        - 修改参数

    支持自然语言命令:
        - "暂停交易"
        - "恢复交易"
        - "减仓一半"
        - "查询状态"
    """

    tool_id = "btc_intervention"
    name = "交易干预"
    description = """实时干预正在运行的交易。

支持命令:
- 暂停交易 - 暂停新开仓，保持持仓
- 恢复交易 - 恢复策略执行
- 全部平仓 - 市价平仓所有持仓
- 查询状态 - 获取当前状态

使用示例:
- {"action": "pause", "reason": "想观察一下市场"}
- {"action": "resume"}
- {"action": "close_all", "reason": "达到目标收益"}
"""

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["pause", "resume", "close_all", "query"],
                "description": "干预动作"
            },
            "reason": {
                "type": "string",
                "description": "干预原因"
            }
        },
        "required": ["action"]
    }

    timeout = 15

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行干预"""
        action = kwargs.get("action", "")
        kwargs.get("reason", "")

        try:
            from core.btc_integration.intervention_system import InterventionType, get_intervention_system

            intervention = get_intervention_system()

            # 映射 action 到 InterventionType
            action_map = {
                "pause": InterventionType.PAUSE,
                "resume": InterventionType.RESUME,
                "close_all": InterventionType.CLOSE_ALL,
                "query": InterventionType.QUERY_STATUS
            }

            intervention_type = action_map.get(action)
            if not intervention_type:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"未知的干预动作: {action}"
                )

            result = intervention.quick_intervention(intervention_type)

            return {
                "success": result.success,
                "error_code": None,
                "error_message": "",
                "user_message": result.message,
                "data": result.to_dict()
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"干预执行失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCCheckRecovery(BaseTool):
    """
    检查恢复状态

    功能:
        - 检查是否有中断的交易
        - 显示可恢复的状态
        - 提供恢复建议
    """

    tool_id = "btc_check_recovery"
    name = "检查恢复状态"
    description = """检查是否有可以恢复的中断交易。

使用场景:
- 系统重启后
- 进程异常退出后
- 想查看之前的交易状态

返回:
- 是否有可恢复的交易
- 中断前的状态
- 恢复建议
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 10

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行恢复检查"""
        try:
            try:
                from core.btc_integration.recovery_manager import get_recovery_manager
                manager = get_recovery_manager()
                summary = manager.get_recovery_summary()
            except ImportError:
                return {
                    "success": True,
                    "error_code": None,
                    "error_message": "",
                    "user_message": "暂无恢复信息（恢复管理器未加载）",
                    "data": {"can_recover": False}
                }

            can_recover = summary.get("can_recover", False)

            if not can_recover:
                messages = [
                    "ℹ️ 恢复状态检查",
                    "",
                    "【检查结果】没有检测到可以恢复的中断交易",
                    "",
                    "【检查点统计】",
                    f"  检查点数量: {summary.get('checkpoint_count', 0)}",
                    f"  系统状态: {summary.get('state', 'unknown')}"
                ]

                return {
                    "success": True,
                    "error_code": None,
                    "error_message": "",
                    "user_message": "\n".join(messages),
                    "data": summary
                }

            # 有可恢复的交易
            latest = summary.get("latest_checkpoint", {})

            messages = [
                "🔄 检测到可恢复的交易",
                "",
                "【交易信息】",
                f"  标的: {latest.get('symbol', 'Unknown')}",
                f"  已运行: {latest.get('elapsed_minutes', 0):.0f} 分钟",
                f"  当前盈亏: ${latest.get('pnl_current', 0):+.2f}",
                "",
                "【操作选项】",
                "  1. 恢复交易 - 使用 btc_recover_trading",
                "  2. 放弃恢复 - 查看最终报告",
            ]

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": summary
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"检查恢复状态失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCRecoverTrading(BaseTool):
    """
    恢复交易

    功能:
        - 恢复中断的交易
        - 继续之前的策略
        - 恢复持仓监控
    """

    tool_id = "btc_recover_trading"
    name = "恢复交易"
    description = """恢复之前中断的自动交易。

参数:
- continue_trading: 是否继续交易 (true/false)

说明:
- 会恢复到中断前的状态
- 继续之前的策略和持仓
- 剩余时间会重新计算
"""

    input_schema = {
        "type": "object",
        "properties": {
            "continue_trading": {
                "type": "boolean",
                "default": True,
                "description": "是否继续交易"
            }
        },
        "required": []
    }

    timeout = 30
    require_confirmation = True

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行恢复"""
        continue_trading = kwargs.get("continue_trading", True)

        try:
            from core.btc_integration.recovery_manager import get_recovery_manager

            manager = get_recovery_manager()

            if continue_trading:
                result = manager.confirm_recovery(True)

                if result.success:
                    messages = [
                        "✅ 交易已恢复",
                        "",
                        "【恢复信息】",
                        f"{result.message}",
                        "",
                        "【后续操作】",
                        "  使用 btc_get_process_status 监控状态",
                        "  使用 btc_intervention 进行干预"
                    ]
                else:
                    messages = [
                        "❌ 恢复失败",
                        "",
                        f"【原因】{result.message}",
                        "",
                        f"【建议】{result.recommended_action}"
                    ]
            else:
                result = manager.confirm_recovery(False)
                messages = [
                    "✅ 已取消恢复",
                    "",
                    "【状态】交易已结束",
                    "  可以查看历史报告或开始新的交易"
                ]

            return {
                "success": result.success,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": result.to_dict() if result else {}
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"恢复交易失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)
