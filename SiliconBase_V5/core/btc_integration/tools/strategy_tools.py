#!/usr/bin/env python3
"""
策略选择和风险评估工具
基于市场行情推荐最优策略

【新增】BTC 状态查询 + AI 中断工具（同一文件内扩展）
"""

from typing import Any

from core.btc_integration.market_data import get_market_data_provider
from core.logger import logger

from .base_btc_tool import BaseBTCTool


class StrategySelectorTool(BaseBTCTool):
    """策略选择工具"""

    tool_id = "btc_strategy_selector"
    name = "BTC策略选择器"
    description = """
    基于当前市场环境，智能推荐最优的BTC交易策略。

    分析维度:
    - 市场趋势（上涨/下跌/震荡）
    - 波动率水平
    - 风险偏好

    推荐策略:
    - stage46_aggressive: 激进趋势跟踪，适合高波动上涨行情
    - stage148_livebase: 稳健基准策略，适合震荡行情
    - stage200_dualcore: 双核对冲，适合多币种配置
    """

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "risk_tolerance": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "medium",
                "description": "风险承受度"
            },
            "market_preference": {
                "type": "string",
                "enum": ["trend", "range", "any"],
                "default": "any",
                "description": "市场偏好：趋势/震荡/任意"
            }
        }
    }

    # 策略数据库
    STRATEGIES = {
        "stage46_aggressive": {
            "name": "激进趋势跟踪",
            "description": "适合高波动上涨行情，追求高收益",
            "risk_level": "high",
            "market_condition": "trend",
            "recommended_for": "趋势明确的市场"
        },
        "stage148_livebase": {
            "name": "稳健基准策略",
            "description": "风险控制较好，适合震荡行情",
            "risk_level": "medium",
            "market_condition": "range",
            "recommended_for": "震荡整理期"
        },
        "stage200_dualcore": {
            "name": "双核对冲",
            "description": "多币种对冲配置，分散风险",
            "risk_level": "medium",
            "market_condition": "any",
            "recommended_for": "多币种配置"
        },
        "stage46_pack": {
            "name": "保守打包策略",
            "description": "低波动下的保守策略",
            "risk_level": "low",
            "market_condition": "range",
            "recommended_for": "低风险偏好"
        }
    }

    def _execute(self,
                 symbol: str = "BTC",
                 risk_tolerance: str = "medium",
                 market_preference: str = "any",
                 **kwargs) -> dict[str, Any]:
        """执行策略选择"""
        try:
            # 获取市场数据
            provider = get_market_data_provider()
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                price_data = loop.run_until_complete(provider.get_price(symbol))
            except Exception:
                price_data = None

            # 分析市场状态
            market_analysis = self._analyze_market(price_data)

            # 根据条件筛选策略
            candidates = self._filter_strategies(
                risk_tolerance=risk_tolerance,
                market_condition=market_analysis["condition"],
                market_preference=market_preference
            )

            # 选择最优策略
            primary_strategy = candidates[0] if candidates else "stage148_livebase"

            data = {
                "symbol": symbol,
                "market_analysis": market_analysis,
                "risk_tolerance": risk_tolerance,
                "primary_strategy": {
                    "id": primary_strategy,
                    **self.STRATEGIES[primary_strategy]
                },
                "alternative_strategies": [
                    {"id": s, **self.STRATEGIES[s]}
                    for s in candidates[1:3] if s in self.STRATEGIES
                ],
                "recommendation_reason": self._generate_reason(
                    market_analysis, primary_strategy
                )
            }

            message = f"推荐策略: {self.STRATEGIES[primary_strategy]['name']} | "
            message += f"理由: {data['recommendation_reason']}"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[StrategySelectorTool] 错误: {e}")
            # 失败时返回默认策略
            return self._format_success({
                "symbol": symbol,
                "primary_strategy": {
                    "id": "stage148_livebase",
                    **self.STRATEGIES["stage148_livebase"]
                },
                "fallback": True
            }, "使用默认稳健策略（分析过程出错）")

    def _analyze_market(self, price_data) -> dict[str, Any]:
        """分析市场状态"""
        if not price_data:
            return {
                "condition": "unknown",
                "trend": "neutral",
                "volatility": "medium"
            }

        change = price_data.change_24h_percent

        # 判断趋势
        if change > 5:
            trend = "strong_up"
        elif change > 2:
            trend = "up"
        elif change < -5:
            trend = "strong_down"
        elif change < -2:
            trend = "down"
        else:
            trend = "neutral"

        # 判断波动率
        abs_change = abs(change)
        if abs_change > 10:
            volatility = "extreme"
        elif abs_change > 5:
            volatility = "high"
        elif abs_change > 2:
            volatility = "medium"
        else:
            volatility = "low"

        # 市场条件
        if trend in ["strong_up", "up"]:
            condition = "trend"
        elif trend in ["strong_down", "down"]:
            condition = "downtrend"
        else:
            condition = "range"

        return {
            "condition": condition,
            "trend": trend,
            "volatility": volatility,
            "change_24h": change
        }

    def _filter_strategies(self,
                          risk_tolerance: str,
                          market_condition: str,
                          market_preference: str) -> list[str]:
        """筛选符合条件的策略"""
        candidates = []

        for strategy_id, info in self.STRATEGIES.items():
            # 风险匹配
            if risk_tolerance == "low" and info["risk_level"] != "low":
                continue
            if risk_tolerance == "medium" and info["risk_level"] == "high":
                continue

            # 市场条件匹配
            if market_preference != "any" and info["market_condition"] != "any" and info["market_condition"] != market_condition:
                continue

            candidates.append(strategy_id)

        # 按优先级排序
        priority_order = ["stage148_livebase", "stage46_aggressive", "stage200_dualcore", "stage46_pack"]
        candidates.sort(key=lambda x: priority_order.index(x) if x in priority_order else 999)

        return candidates

    def _generate_reason(self, market_analysis: dict, strategy: str) -> str:
        """生成推荐理由"""
        reasons = {
            "stage46_aggressive": "当前趋势向上，适合激进策略捕捉涨幅",
            "stage148_livebase": "市场震荡，稳健策略更适合风险控制",
            "stage200_dualcore": "多币种配置可分散单一资产风险",
            "stage46_pack": "低波动环境下，保守策略更安全"
        }
        return reasons.get(strategy, "基于综合评估推荐")


class RiskAssessmentTool(BaseBTCTool):
    """风险评估工具"""

    tool_id = "btc_risk_assessment"
    name = "BTC风险评估"
    description = """
    评估当前BTC交易的风险等级，包括：
    - 市场波动风险
    - 仓位风险（如果已开仓）
    - 流动性风险
    - 系统性风险

    返回风险等级：low / medium / high / critical
    """

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "account_equity": {
                "type": "number",
                "default": 10000,
                "description": "账户权益（用于计算仓位风险）"
            }
        }
    }

    def _execute(self,
                 symbol: str = "BTC",
                 account_equity: float = 10000,
                 **kwargs) -> dict[str, Any]:
        """执行风险评估"""
        try:
            # 获取市场数据
            provider = get_market_data_provider()
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                price_data = loop.run_until_complete(provider.get_price(symbol))
            except Exception:
                price_data = None

            # 获取当前交易状态
            trading_state = self.client.get_autopilot_state()

            # 各项风险评估
            market_risk = self._assess_market_risk(price_data)
            position_risk = self._assess_position_risk(trading_state, account_equity)
            system_risk = self._assess_system_risk(trading_state)

            # 综合风险等级
            overall_level = self._calculate_overall_risk(
                market_risk, position_risk, system_risk
            )

            data = {
                "symbol": symbol,
                "overall_risk": overall_level["level"],
                "overall_risk_desc": overall_level["description"],
                "risk_score": overall_level["score"],
                "details": {
                    "market_risk": market_risk,
                    "position_risk": position_risk,
                    "system_risk": system_risk
                },
                "warnings": self._generate_warnings(
                    market_risk, position_risk, system_risk
                ),
                "recommendations": self._generate_recommendations(overall_level["level"])
            }

            message = f"综合风险: {overall_level['description']} (评分: {overall_level['score']}/100)"
            if data["warnings"]:
                message += f" | 警告: {', '.join(data['warnings'][:2])}"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[RiskAssessmentTool] 错误: {e}")
            return self._format_success({
                "overall_risk": "medium",
                "overall_risk_desc": "中等风险（评估过程出错，使用默认值）",
                "risk_score": 50,
                "fallback": True
            }, "风险评估使用默认值")

    def _assess_market_risk(self, price_data) -> dict[str, Any]:
        """评估市场风险"""
        if not price_data:
            return {"level": "medium", "score": 50, "reason": "无法获取市场数据"}

        change = abs(price_data.change_24h_percent)

        if change > 10:
            return {"level": "high", "score": 80, "reason": "24h波动超过10%"}
        elif change > 5:
            return {"level": "medium-high", "score": 65, "reason": "24h波动超过5%"}
        elif change > 2:
            return {"level": "medium", "score": 50, "reason": "正常波动范围"}
        else:
            return {"level": "low", "score": 20, "reason": "低波动环境"}

    def _assess_position_risk(self, trading_state, account_equity: float) -> dict[str, Any]:
        """评估仓位风险"""
        if trading_state.status != "running":
            return {"level": "low", "score": 10, "reason": "当前无持仓"}

        # 根据盈亏评估
        pnl = trading_state.pnl_today
        pnl_pct = (pnl / account_equity) * 100 if account_equity > 0 else 0

        if pnl_pct < -5:
            return {"level": "high", "score": 75, "reason": f"当日亏损 {pnl_pct:.1f}%"}
        elif pnl_pct < -2:
            return {"level": "medium", "score": 50, "reason": f"当日亏损 {pnl_pct:.1f}%"}
        elif pnl_pct > 5:
            return {"level": "medium", "score": 40, "reason": "盈利较高，注意回撤"}
        else:
            return {"level": "low", "score": 25, "reason": "盈亏在正常范围"}

    def _assess_system_risk(self, trading_state) -> dict[str, Any]:
        """评估系统风险"""
        # 检查Coinglass风控状态
        if trading_state.coinglass_mode == "pause_new_entries":
            return {"level": "high", "score": 70, "reason": f"风控暂停: {trading_state.coinglass_reason}"}

        return {"level": "low", "score": 20, "reason": "系统运行正常"}

    def _calculate_overall_risk(self, market_risk, position_risk, system_risk) -> dict[str, Any]:
        """计算综合风险"""
        avg_score = (market_risk["score"] + position_risk["score"] + system_risk["score"]) / 3

        if avg_score >= 70:
            return {"level": "high", "score": int(avg_score), "description": "高风险"}
        elif avg_score >= 50:
            return {"level": "medium", "score": int(avg_score), "description": "中等风险"}
        elif avg_score >= 30:
            return {"level": "low-medium", "score": int(avg_score), "description": "中低风险"}
        else:
            return {"level": "low", "score": int(avg_score), "description": "低风险"}

    def _generate_warnings(self, market_risk, position_risk, system_risk) -> list[str]:
        """生成风险提示"""
        warnings = []

        if market_risk["level"] == "high":
            warnings.append("市场波动剧烈")
        if position_risk["level"] == "high":
            warnings.append("仓位风险较高")
        if system_risk["level"] == "high":
            warnings.append("风控已触发")

        return warnings

    def _generate_recommendations(self, risk_level: str) -> list[str]:
        """生成建议"""
        recommendations = {
            "high": [
                "建议降低仓位或暂停交易",
                "密切关注市场动态",
                "考虑设置止损"
            ],
            "medium": [
                "保持当前策略，注意风险控制",
                "定期评估市场状况"
            ],
            "low": [
                "市场环境良好，可按计划执行",
                "继续保持风险监控"
            ]
        }
        return recommendations.get(risk_level, ["请根据实际情况判断"])


# ═══════════════════════════════════════════════════════════════
# 【新增】AI 可观测层工具：状态查询 + 策略中断
# ═══════════════════════════════════════════════════════════════

class BTCStatusQueryTool(BaseBTCTool):
    """BTC 运行状态查询工具（供 AI 调用）"""

    tool_id = "btc_status_query"
    name = "BTC状态查询"
    description = """
    查询当前用户的BTC交易运行状态，包括：
    - 活跃策略列表
    - 最近的交易事件（最近20条）
    - 当前风险等级
    - 待处理的干预命令

    AI 在回答用户关于交易状态的问题时应优先调用此工具。
    """

    input_schema = {
        "type": "object",
        "properties": {
            "detail_level": {
                "type": "string",
                "enum": ["summary", "events", "full"],
                "default": "summary",
                "description": "查询详细程度: summary=摘要, events=包含最近事件, full=全部信息"
            }
        }
    }

    telemetry_enabled = False  # 查询类工具不发射遥测（避免递归）

    def _execute(self, detail_level: str = "summary", **kwargs) -> dict[str, Any]:
        """执行状态查询"""
        try:
            # 获取交易状态
            trading_state = self.client.get_autopilot_state()

            # 获取 EventBus 摘要
            from core.btc_integration.event_bus import event_bus
            user_id = kwargs.get("user_id", "default")
            summary = event_bus.get_summary(user_id)

            result = {
                "autopilot_status": trading_state.status if trading_state else "unknown",
                "has_activity": summary.get("has_activity", False),
                "active_strategies": summary.get("active_strategies", []),
                "risk_level": summary.get("risk_level", "none"),
                "latest_signal": summary.get("latest_signal"),
            }

            # 根据 detail_level 追加信息
            if detail_level in ("events", "full"):
                recent_events = event_bus.get_recent_events_by_user(
                    user_id=user_id,
                    limit=20,
                )
                result["recent_events"] = [
                    {
                        "type": e.event_type.value,
                        "source": e.source,
                        "symbol": e.symbol,
                        "data": e.data,
                        "timestamp": e.timestamp,
                    }
                    for e in recent_events
                ]

            if detail_level == "full":
                from core.btc_integration.intervention_system import get_intervention_system
                intervention_system = get_intervention_system()
                result["pending_interventions"] = intervention_system.get_pending_interventions(user_id)

            # 生成自然语言摘要
            summary_text = summary.get("summary_text", "")
            message = f"交易状态: {summary_text}" if summary_text else "当前无活跃交易活动"

            return self._format_success(result, message)

        except Exception as e:
            logger.error(f"[BTCStatusQueryTool] 错误: {e}")
            return self._format_error("QUERY_ERROR", str(e), "状态查询失败")


class BTCInterruptTool(BaseBTCTool):
    """BTC 策略中断工具（供 AI 调用）"""

    tool_id = "btc_interrupt"
    name = "BTC策略中断"
    description = """
    向正在运行的BTC交易策略发送中断命令。

    支持的命令:
    - pause: 暂停交易（保持持仓，停止新开仓）
    - resume: 恢复交易
    - close_all: 立即平仓所有持仓
    - emergency_stop: 紧急停止（平仓+终止策略）
    - reduce: 减仓

    敏感操作（close_all, emergency_stop）需要用户确认。
    """

    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["pause", "resume", "close_all", "emergency_stop", "reduce"],
                "description": "中断命令类型"
            },
            "reason": {
                "type": "string",
                "description": "AI 决策原因",
                "default": ""
            },
            "params": {
                "type": "object",
                "description": "额外参数",
                "default": {}
            }
        },
        "required": ["command"]
    }

    # 敏感操作需要用户确认
    require_confirmation = True

    # 命令 → 确认提示映射
    CONFIRMATION_MESSAGES = {
        "pause": "AI 请求暂停BTC交易，是否确认？",
        "resume": "AI 请求恢复BTC交易，是否确认？",
        "close_all": "AI 请求立即平仓所有BTC持仓，是否确认？",
        "emergency_stop": "AI 请求紧急停止BTC交易（将平仓所有持仓），是否确认？",
        "reduce": "AI 请求减仓，是否确认？",
    }

    def get_confirmation_prompt(self, params: dict[str, Any]) -> str:
        """获取确认提示"""
        command = params.get("command", "unknown")
        return self.CONFIRMATION_MESSAGES.get(command, f"AI 请求执行 {command}，是否确认？")

    def _execute(self, command: str, reason: str = "", params: dict = None, **kwargs) -> dict[str, Any]:
        """执行中断命令"""
        try:
            user_id = kwargs.get("user_id", "default")

            from core.btc_integration.intervention_system import get_intervention_system
            intervention_system = get_intervention_system()

            result = intervention_system.submit_ai_intervention(
                user_id=user_id,
                intervention_type_str=command,
                params=params or {},
                reason=reason or "AI 决策",
            )

            if result.success:
                # 显式emit干预事件
                from core.btc_integration.event_bus import EventPriority, EventType
                self._emit_to_eventbus(
                    event_type=EventType.AI_INTERVENTION,
                    data={
                        "command": command,
                        "reason": reason,
                        "command_id": result.command_id,
                    },
                    priority=EventPriority.CRITICAL if command in ("emergency_stop", "close_all") else EventPriority.HIGH,
                )

                action_desc = {
                    "pause": "交易已暂停",
                    "resume": "交易已恢复",
                    "close_all": "平仓命令已提交",
                    "emergency_stop": "紧急停止已执行",
                    "reduce": "减仓命令已提交",
                }

                return self._format_success({
                    "command": command,
                    "command_id": result.command_id,
                    "status": "submitted",
                }, action_desc.get(command, f"命令 {command} 已提交"))
            else:
                return self._format_error(
                    "INTERRUPT_FAILED",
                    result.message,
                    f"中断命令提交失败: {result.message}"
                )

        except Exception as e:
            logger.error(f"[BTCInterruptTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e), "中断命令执行失败")
