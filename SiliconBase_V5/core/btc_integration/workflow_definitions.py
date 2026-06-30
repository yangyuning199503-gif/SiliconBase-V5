#!/usr/bin/env python3
"""
BTC 交易工作流定义

工作流列表:
    - BTC_TRADING_WORKFLOW: 1小时自主交易
    - BTC_QUICK_TRADE: 快速交易
    - BTC_MONITOR_WORKFLOW: 监控模式
"""

from core.workflow.workflow_engine import WorkflowDefinition, WorkflowStep


def create_btc_trading_workflow(
    symbol: str = "BTC",
    budget: float = 1000,
    duration_minutes: int = 60,
    risk_tolerance: str = "medium",
    auto_mode: bool = False,
    max_daily_loss: float = 5.0
) -> WorkflowDefinition:
    """
    创建 BTC 自主交易工作流

    工作流步骤:
        1. 市场分析 - 查询市场数据
        2. 策略选择 - AI 选择最优策略
        3. 风险评估 - 评估市场风险
        4. 用户确认/自动风控 - 关键决策点（auto_mode=True时自动）
        5. 启动交易 - 启动 autopilot 进程
        6. 监控循环 - 每 5 分钟检查一次
        7. 结束报告 - 生成最终报告

    Args:
        symbol: 交易标的
        budget: 预算金额
        duration_minutes: 交易时长
        risk_tolerance: 风险偏好
        auto_mode: 是否自动模式（跳过人工确认）
        max_daily_loss: 最大日亏损百分比（自动模式下使用）

    Returns:
        WorkflowDefinition 工作流定义
    """

    steps = [
        # 步骤 1: 市场分析
        WorkflowStep(
            step_id="market_analysis",
            name="市场分析",
            description=f"分析 {symbol} 的市场环境",
            tool_id="btc_market_overview",
            tool_params={},
            is_critical=False,
            step_category="check"
        ),

        # 步骤 2: 策略选择
        WorkflowStep(
            step_id="strategy_selection",
            name="策略选择",
            description="根据市场环境选择最优策略",
            tool_id="btc_strategy_selector",
            tool_params={
                "symbol": symbol,
                "risk_tolerance": risk_tolerance,
                "budget": budget
            },
            is_critical=True,
            step_category="planning",
            inputs={
                "market_data": "$market_analysis.result"
            }
        ),

        # 步骤 3: 风险评估
        WorkflowStep(
            step_id="risk_assessment",
            name="风险评估",
            description="评估当前市场风险",
            tool_id="btc_risk_assessment",
            tool_params={
                "symbol": symbol,
                "account_equity": budget
            },
            is_critical=True,
            step_category="check"
        ),

        # 步骤 4: 用户确认/自动风控（关键节点）
        WorkflowStep(
            step_id="auto_risk_check" if auto_mode else "user_confirmation",
            name="自动风控检查" if auto_mode else "用户确认",
            description="自动评估风险并决策" if auto_mode else "确认交易策略和参数",
            tool_id="btc_auto_risk_gate" if auto_mode else "btc_confirm_trade",
            tool_params={
                "max_daily_loss": max_daily_loss,
                "risk_tolerance": risk_tolerance
            } if auto_mode else {},
            is_critical=True,
            step_category="verify",
            requires_confirmation=not auto_mode,  # 自动模式下跳过确认
            confirmation_message=None if auto_mode else f"""
请确认以下交易计划：

【标的】{symbol}
【预算】${budget:,.0f}
【时长】{duration_minutes} 分钟
【风险偏好】{risk_tolerance}

【推荐策略】
{{strategy_name}}

【风险提示】
{{risk_warning}}

点击【确认】开始自动交易，或【取消】放弃。
            """,
            inputs={
                "strategy": "$strategy_selection.data.primary_strategy",
                "risk": "$risk_assessment.data"
            }
        ),

        # 步骤 5: 启动交易
        WorkflowStep(
            step_id="launch_trading",
            name="启动交易引擎",
            description="启动 btc_system autopilot",
            tool_id="btc_launch_autopilot",
            tool_params={
                "symbol": symbol,
                "budget": budget,
                "duration_minutes": duration_minutes,
                "strategy": "$strategy_selection.data.primary_strategy.id"
            },
            is_critical=True,
            step_category="action",
            timeout=60,
            inputs={
                "strategy_id": "$strategy_selection.data.primary_strategy.id"
            }
        ),

        # 步骤 6: 监控循环（重复执行）
        WorkflowStep(
            step_id="monitoring_loop",
            name="监控交易状态",
            description="监控交易进程和生成报告",
            tool_id="btc_monitor_trading",
            tool_params={},
            is_critical=False,
            step_category="check",
            execution_mode="parallel",  # 与交易引擎并行
            timeout=300,  # 5分钟一次
            inputs={
                "process_id": "$launch_trading.data.process_id"
            }
        ),

        # 步骤 7: 结束报告
        WorkflowStep(
            step_id="final_report",
            name="生成最终报告",
            description="汇总交易结果",
            tool_id="btc_generate_report",
            tool_params={},
            is_critical=False,
            step_category="verify",
            inputs={
                "process_id": "$launch_trading.data.process_id",
                "monitoring_data": "$monitoring_loop.result"
            }
        )
    ]

    return WorkflowDefinition(
        workflow_id=f"btc_trading_{symbol.lower()}_{int(time.time())}",
        name=f"{symbol} {'自动' if auto_mode else '自主'}交易",
        description=f"{duration_minutes}分钟{'全自动' if auto_mode else '自动'}量化交易",
        steps=steps,
        variables={
            "symbol": symbol,
            "budget": budget,
            "duration_minutes": duration_minutes,
            "risk_tolerance": risk_tolerance,
            "auto_mode": auto_mode,
            "max_daily_loss": max_daily_loss,
            "start_time": None,
            "end_time": None
        },
        timeout_per_step=300,
        max_retries=2
    )


def create_btc_quick_trade_workflow(
    symbol: str = "BTC",
    side: str = "buy",
    amount: float = 100
) -> WorkflowDefinition:
    """
    创建快速交易工作流

    用于单次快速交易，不包含持续监控
    """
    steps = [
        WorkflowStep(
            step_id="check_price",
            name="查询价格",
            tool_id="btc_price_query",
            tool_params={"symbol": symbol}
        ),

        WorkflowStep(
            step_id="risk_check",
            name="风险检查",
            tool_id="btc_risk_assessment",
            tool_params={"symbol": symbol}
        ),

        WorkflowStep(
            step_id="confirm_trade",
            name="确认交易",
            tool_id="btc_confirm_trade",
            tool_params={},
            requires_confirmation=True,
            confirmation_message=f"确认 {side} {amount} USDT 的 {symbol}?"
        ),

        WorkflowStep(
            step_id="execute_trade",
            name="执行交易",
            tool_id="btc_execute_trade",
            tool_params={
                "symbol": symbol,
                "side": side,
                "amount": amount
            },
            timeout=30
        )
    ]

    return WorkflowDefinition(
        workflow_id=f"btc_quick_{int(time.time())}",
        name=f"{symbol} 快速交易",
        description="单次快速交易",
        steps=steps,
        timeout_per_step=60
    )


def create_btc_monitor_workflow(
    process_id: str
) -> WorkflowDefinition:
    """
    创建监控工作流

    用于监控正在运行的交易进程
    """
    steps = [
        WorkflowStep(
            step_id="check_status",
            name="检查进程状态",
            tool_id="btc_get_process_status",
            tool_params={"process_id": process_id}
        ),

        WorkflowStep(
            step_id="get_account",
            name="获取账户信息",
            tool_id="btc_account_info",
            tool_params={}
        ),

        WorkflowStep(
            step_id="generate_status_report",
            name="生成状态报告",
            tool_id="btc_generate_report",
            tool_params={
                "process_id": process_id,
                "report_type": "status"
            }
        )
    ]

    return WorkflowDefinition(
        workflow_id=f"btc_monitor_{process_id}",
        name="交易监控",
        description="监控交易进程状态",
        steps=steps,
        timeout_per_step=30
    )


# 导入 time 模块（在文件末尾避免循环导入）
import time
