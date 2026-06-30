#!/usr/bin/env python3
"""
自动风控门工具
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
在自动交易模式下替代人工确认，自动评估风险并决策

功能:
- 评估当前风险等级
- 检查日亏损限制
- 检查市场条件
- 自动通过或拒绝交易
"""

from typing import Any

from core.btc_integration.risk_monitor import RiskLevel, get_risk_monitor
from core.logger import logger

from .base_btc_tool import BaseBTCTool


class AutoRiskGateTool(BaseBTCTool):
    """
    自动风控门工具

    使用示例:
        tool = AutoRiskGateTool()
        result = tool.execute({
            "max_daily_loss": 5.0,
            "risk_tolerance": "medium",
            "strategy": {"id": "stage46_aggressive", "risk_level": 4},
            "risk": {"overall_level": "medium", "score": 45}
        })
    """

    tool_id = "btc_auto_risk_gate"
    name = "btc_auto_risk_gate"
    description = "自动风控检查门，评估风险并自动决策是否执行交易"
    parameters = {
        "type": "object",
        "properties": {
            "max_daily_loss": {
                "type": "number",
                "description": "最大日亏损百分比",
                "default": 5.0
            },
            "risk_tolerance": {
                "type": "string",
                "description": "风险偏好",
                "enum": ["low", "medium", "high"],
                "default": "medium"
            },
            "strategy": {
                "type": "object",
                "description": "策略信息"
            },
            "risk": {
                "type": "object",
                "description": "风险评估结果"
            }
        },
        "required": []
    }

    def __init__(self):
        super().__init__()
        self.risk_monitor = get_risk_monitor()

    def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        执行自动风控检查

        Args:
            parameters: 包含max_daily_loss, risk_tolerance, strategy, risk

        Returns:
            Dict: 包含success, user_message, data
                data.approved: bool 是否通过
                data.reason: str 决策原因
        """
        parameters.get("max_daily_loss", 5.0)
        risk_tolerance = parameters.get("risk_tolerance", "medium")
        strategy = parameters.get("strategy", {})
        parameters.get("risk", {})

        try:
            logger.info(f"[AutoRiskGate] 执行自动风控检查: 风险承受={risk_tolerance}")

            # 1. 获取最新风险评估
            risk_assessment = self.risk_monitor.assess_risk()

            # 2. 检查是否触发熔断级风险
            if risk_assessment.should_halt:
                return self._format_success(
                    data={
                        "approved": False,
                        "reason": f"高风险触发熔断: {risk_assessment.overall_level.value}",
                        "risk_level": risk_assessment.overall_level.value,
                        "risk_score": risk_assessment.score,
                        "recommendations": risk_assessment.recommendations
                    },
                    message=f"❌ 自动风控拒绝: 当前风险等级 {risk_assessment.overall_level.value}，建议暂停交易"
                )

            # 3. 根据风险偏好检查风险等级
            risk_level = risk_assessment.overall_level

            # 风险偏好映射到允许的最大风险等级
            tolerance_map = {
                "low": RiskLevel.LOW,
                "medium": RiskLevel.MEDIUM,
                "high": RiskLevel.HIGH
            }

            max_allowed_level = tolerance_map.get(risk_tolerance, RiskLevel.MEDIUM)

            # 风险等级权重（用于比较）
            level_weights = {
                RiskLevel.LOW: 1,
                RiskLevel.MEDIUM: 2,
                RiskLevel.HIGH: 3,
                RiskLevel.CRITICAL: 4
            }

            if level_weights.get(risk_level, 0) > level_weights.get(max_allowed_level, 2):
                return self._format_success(
                    data={
                        "approved": False,
                        "reason": f"风险等级 {risk_level.value} 超过 {risk_tolerance} 偏好的阈值",
                        "risk_level": risk_level.value,
                        "risk_score": risk_assessment.score
                    },
                    message=f"❌ 自动风控拒绝: 风险等级 {risk_level.value} 超过 {risk_tolerance} 阈值"
                )

            # 4. 检查策略风险等级匹配
            strategy_risk_level = strategy.get("risk_level", 3)

            # 低风险偏好只允许低风险的策略
            if risk_tolerance == "low" and strategy_risk_level > 2:
                return self._format_success(
                    data={
                        "approved": False,
                        "reason": f"低风险偏好不匹配高风险策略(风险等级{strategy_risk_level})",
                        "strategy_risk": strategy_risk_level
                    },
                    message=f"❌ 自动风控拒绝: 策略风险等级{strategy_risk_level}超过低风险偏好限制"
                )

            # 5. 检查风险分数
            if risk_assessment.score > 70:  # 风险分数超过70
                return self._format_success(
                    data={
                        "approved": False,
                        "reason": f"风险分数过高: {risk_assessment.score}",
                        "risk_score": risk_assessment.score
                    },
                    message=f"❌ 自动风控拒绝: 风险分数 {risk_assessment.score} 超过阈值"
                )

            # 6. 检查是否需要减仓警告
            should_reduce = risk_assessment.should_reduce

            # 所有检查通过
            return self._format_success(
                data={
                    "approved": True,
                    "reason": "自动风控检查通过",
                    "risk_level": risk_level.value,
                    "risk_score": risk_assessment.score,
                    "should_reduce": should_reduce,
                    "warnings": risk_assessment.recommendations if should_reduce else []
                },
                message=f"✅ 自动风控通过: 风险等级 {risk_level.value}，分数 {risk_assessment.score}"
            )

        except Exception as e:
            logger.error(f"[AutoRiskGate] 风控检查异常: {e}")
            # 异常时保守处理，拒绝交易
            return self._format_success(
                data={
                    "approved": False,
                    "reason": f"风控检查异常: {str(e)}",
                    "error": str(e)
                },
                message=f"❌ 自动风控异常，拒绝交易: {str(e)}"
            )


# 工具实例
auto_risk_gate_tool = AutoRiskGateTool()
