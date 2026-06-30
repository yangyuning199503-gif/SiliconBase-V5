#!/usr/bin/env python3
"""
AI交易指挥官 (AITradingCommander) - MCP标准版
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI驱动的交易指挥中心，全链路通过MCP协议对接

Phase4整改后：
- 淘汰自定义适配层（smart_quant_engine / trade_executor / simple_ai_quant / intelligence_integration）
- 统一通过MCP协议调用外部能力（量化决策、交易执行、AI推理）
- 多角色Prompt标准化，禁止裸调AI接口
- 所有消息逐层异步汇总到主AI
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from core.btc_integration.event_bus import (
    EventType,
    TradingEvent,
    event_bus,
    publish_ai_decision,
    publish_ai_intervention,
)
from core.btc_integration.news_monitor import NewsMonitor, start_news_monitor
from core.btc_integration.trading_memory import get_trading_memory
from core.btc_integration.trading_subagent import TradingSubAgent, start_trading_subagent
from core.config import config
from core.logger import logger
from core.task.background_task_registry import BackgroundTaskRegistry

# MCP协议客户端（Phase4核心替换）
try:
    from core.mcp.client import mcp_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("[AITradingCommander] MCP客户端不可用，交易功能将降级")

# World Model 降级策略配置
WORLD_MODEL_FALLBACK_ACTION = config.get("trading.world_model_fallback", "hold")
WORLD_MODEL_SUCCESS_THRESHOLD = config.get("trading.world_model_threshold", 0.3)


# ═══════════════════════════════════════════════════════════════
# Phase4: 多角色Prompt标准化（固定提示词，禁止动态拼接）
# ═══════════════════════════════════════════════════════════════

COMMANDER_ROLE_PROMPT = """【角色】AI交易指挥官
【职责边界】
1. 你是加密货币交易模块的专属指挥官，负责监控市场、调度子代理、执行风控干预
2. 你不直接对外与用户对话，所有决策与状态必须逐层异步汇总到主AI
3. 你的决策具有强制约束力：pause/close/emergency_close 必须立即执行
【决策规范】
- 每次干预必须记录reason，并通过event_bus.publish回流到主AI
- 风险评估结果以JSON格式输出，包含action/target_symbols/reasoning/confidence
- 禁止在没有reason的情况下执行任何交易操作
【消息规范】
- 所有通知通过commander.notification事件发送到主事件总线
- 交易结果通过commander.report事件汇报
"""

TRADING_AUX_PROMPT = """【角色】交易附属AI
【职责边界】
1. 你是指挥官的量化分析助手，负责市场数据分析、策略评估、交易信号生成
2. 你禁止直接调用交易执行接口，所有建议必须通过指挥官审批
3. 你的输出必须包含confidence和risk_assessment两个字段
【分析规范】
- 多维度分析：技术+消息+情绪+资金
- 必须给出明确的action：buy/sell/hold
- 必须给出reasoning，解释决策逻辑
- 高风险场景必须触发指挥官风控干预
"""

SUBAGENT_ROLE_PROMPT = """【角色】交易子代理
【职责边界】
1. 你是指挥官下辖的单一币种执行单元，负责指定symbol的盯盘与执行
2. 你接受指挥官的pause/resume/close_all/emergency_close指令，必须立即响应
3. 你的所有决策必须上报指挥官，禁止越级直接向主AI汇报
【执行规范】
- 开仓前必须确认指挥官未处于paused状态
- 每笔交易必须记录到trading_memory
- 异常状态（风控触发/连接断开）必须立即上报指挥官
"""


@dataclass
class SubAgentStatus:
    """子代理状态快照"""
    runtime_id: str
    symbol: str
    is_running: bool
    is_paused: bool
    current_position: dict | None
    bar_count: int
    last_ai_decision: dict | None
    profit_loss: float
    uptime: float

    def to_dict(self) -> dict:
        return {
            "runtime_id": self.runtime_id,
            "symbol": self.symbol,
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "current_position": self.current_position,
            "bar_count": self.bar_count,
            "last_ai_decision": self.last_ai_decision,
            "profit_loss": self.profit_loss,
            "uptime": self.uptime,
        }


@dataclass
class CommanderReport:
    """指挥官报告"""
    timestamp: float
    active_agents: int
    total_positions: int
    daily_pnl: float
    risk_exposure: str
    recent_decisions: list[dict]
    market_sentiment: str
    ai_thoughts: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "active_agents": self.active_agents,
            "total_positions": self.total_positions,
            "daily_pnl": self.daily_pnl,
            "risk_exposure": self.risk_exposure,
            "recent_decisions": self.recent_decisions,
            "market_sentiment": self.market_sentiment,
            "ai_thoughts": self.ai_thoughts,
        }

    def to_markdown(self) -> str:
        return f"""# AI交易指挥官报告
- 时间: {datetime.fromtimestamp(self.timestamp)}
- 活跃代理: {self.active_agents}
- 总持仓: {self.total_positions}
- 日盈亏: {self.daily_pnl:.2f}
- 风险敞口: {self.risk_exposure}
- 市场情绪: {self.market_sentiment}

## AI思考
{self.ai_thoughts}
"""


class AITradingCommander:
    """
    AI交易指挥官 - MCP协议标准版
    """

    def __init__(
        self,
        user_id: str = None,
        symbols: list[str] = None,
        auto_start: bool = True,
        report_interval: int = 300,
        auto_execute: bool = True,
        ai_check_interval: int = None,
        risk_profile: str = None,
        executor: Any = None,
    ):
        self.user_id = user_id or "anonymous"
        self.symbols = symbols or ["BTC"]
        self.auto_start = auto_start
        self.report_interval = report_interval
        self.auto_execute = auto_execute
        self.ai_check_interval = ai_check_interval
        self.risk_profile = risk_profile
        self.executor = executor

        # 子代理管理
        self.subagents: dict[str, TradingSubAgent] = {}

        # 消息监控
        self.news_monitor: NewsMonitor | None = None

        # 运行状态
        self._running = False
        self._paused = False
        self._stop_event = asyncio.Event()
        self._start_time = 0.0

        # 统计
        self.decision_history: list[dict] = []
        self.event_counter: dict[str, int] = {}

        # 最新报告
        self.latest_report: CommanderReport | None = None

        # 订阅句柄
        self._subscribers: list[Any] = []

        # AI思考缓存
        self.ai_thoughts_cache: str = ""
        self.last_thought_time: float = 0

        # 交易统计
        self.total_trades = 0
        self.total_pnl = 0.0

        # 活跃交易追踪
        self._active_trades: dict[str, dict] = {}

        # 后台任务注册表（治理：消灭野任务）
        self._task_registry = BackgroundTaskRegistry(f"commander_{self.user_id}")

        # Phase4: 量化引擎已迁移至MCP，本地不再持有实例
        self.quant_mode = "mcp"
        self.current_strategy: str | None = None

        logger.info(f"[AITradingCommander] [{self.user_id}] MCP标准版初始化完成，监控币种: {self.symbols}")

    @property
    def is_running(self) -> bool:
        """外部查询运行状态"""
        return self._running

    async def initialize(self):
        """初始化 - Phase4: 全部通过MCP协议连接"""
        # 【治理】全局 EventBus 由应用生命周期管理器控制，指挥官只订阅，不启动
        pass

        # 初始化交易记忆
        self.trading_memory = get_trading_memory()
        logger.info("[AITradingCommander] 交易记忆已连接")

        # 订阅交易事件
        self._subscribe_events()

        # 启动消息监控
        if self.symbols:
            self.news_monitor = await start_news_monitor(symbols=self.symbols)
            logger.info(f"[AITradingCommander] 消息监控已启动: {self.symbols}")

        self._start_time = time.time()
        self._running = True
        logger.info("[AITradingCommander] 初始化完成（MCP协议模式）")

    def _subscribe_events(self):
        """订阅事件总线"""
        self._subscribers = [
            event_bus.subscribe(EventType.AI_DECISION, self._on_ai_decision),
            event_bus.subscribe(EventType.RISK_WARNING, self._on_risk_event),
            event_bus.subscribe(EventType.RISK_CRITICAL, self._on_critical_risk),
            event_bus.subscribe(EventType.NEWS_RISK, self._on_risk_news),
        ]

    async def _on_ai_decision(self, event: TradingEvent):
        """处理AI决策事件"""
        logger.info(f"[AITradingCommander] 收到AI决策: {event.data}")

    async def _on_risk_event(self, event: TradingEvent):
        """处理风险事件"""
        level = event.data.get("level", "medium")
        self.event_counter[f"risk_{level}"] = self.event_counter.get(f"risk_{level}", 0) + 1

        if level in ["high", "critical"]:
            await self._evaluate_risk_response(event)

    async def _on_critical_risk(self, event: TradingEvent):
        """处理严重风险"""
        self.event_counter["risk_critical"] = self.event_counter.get("risk_critical", 0) + 1
        logger.error(f"[AITradingCommander] 严重风险: {event.data}")
        await self.intervene("emergency_close", reason=f"严重风险: {event.data.get('message', '')}")

    async def _on_risk_news(self, event: TradingEvent):
        """处理风险新闻"""
        logger.warning(f"[AITradingCommander] 风险新闻: {event.data.get('title', '')}")
        await self._evaluate_news_impact(event)

    async def _evaluate_risk_response(self, risk_event: TradingEvent):
        """
        AI评估风险响应 - Phase4: 通过MCP调用AI推理，禁止裸调ai_client
        """
        context = await self._build_risk_context(risk_event)
        prompt = f"""{COMMANDER_ROLE_PROMPT}

## 风险事件
{json.dumps(risk_event.data, indent=2, ensure_ascii=False)}

## 当前状态
{json.dumps(context, indent=2, ensure_ascii=False)}

## 可选操作
1. pause_all - 暂停所有交易
2. close_risky - 关闭高风险持仓
3. reduce_size - 降低仓位
4. monitor - 继续监控

请返回JSON格式：
{{
    "action": "pause_all|close_risky|reduce_size|monitor",
    "target_symbols": ["BTC", "ETH"],
    "reasoning": "决策理由",
    "confidence": 0.8
}}
"""
        try:
            response = await self._call_mcp_tool(
                server="ai",
                tool="chat",
                args={"prompt": prompt, "system": COMMANDER_ROLE_PROMPT}
            )

            if not response or not response.get("success"):
                logger.warning("[AITradingCommander] MCP AI风险评估返回空或失败")
                return

            text = response.get("data", "")
            if isinstance(text, dict):
                text = json.dumps(text, ensure_ascii=False)

            import re
            json_match = re.search(r'\{[^}]*\}', text, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())
                action = decision.get("action")
                if action in ["pause_all", "close_risky", "reduce_size"]:
                    targets = decision.get("target_symbols", self.symbols)
                    await self.intervene(action, targets, decision.get("reasoning", ""))
                    publish_ai_decision(
                        decision_type="risk_response",
                        decision_data=decision,
                        reasoning=f"风险响应: {risk_event.data.get('message', '')}"
                    )
        except Exception as e:
            logger.error(f"[AITradingCommander] 风险评估失败: {e}")

    async def _evaluate_news_impact(self, news_event: TradingEvent):
        """AI评估新闻影响"""
        logger.info(f"[AITradingCommander] 评估新闻影响: {news_event.data.get('title', '')[:50]}...")
        for _symbol, agent in self.subagents.items():
            if agent._running and not agent._paused:
                agent.recent_news.append({
                    "timestamp": news_event.timestamp,
                    "title": news_event.data.get("title"),
                    "tags": news_event.data.get("tags", []),
                })

    async def _build_risk_context(self, risk_event: TradingEvent) -> dict:
        """构建风险上下文"""
        return {
            "timestamp": time.time(),
            "active_symbols": list(self.subagents.keys()),
            "positions": {
                symbol: agent.current_position
                for symbol, agent in self.subagents.items()
            },
            "recent_decisions": self.decision_history[-5:],
            "event_stats": self.event_counter,
        }

    async def start(self) -> asyncio.Task:
        """启动指挥官主循环

        Returns:
            asyncio.Task: 主循环任务，调用方可 await 等待其完成
        """
        await self.initialize()
        logger.info("[AITradingCommander] 启动主循环")
        # 【治理】通过注册表启动，返回 Task 供调用方等待
        task = await self._task_registry.register("commander_loop", self._commander_loop())
        return task

    async def _commander_loop(self):
        """指挥官主循环"""
        # 启动后立即生成一份初始报告，避免前端"假死"
        if self._running:
            try:
                await self._generate_report()
            except Exception as e:
                logger.error(f"[AITradingCommander] 初始报告生成失败: {e}")

        while self._running:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.report_interval)
                break
            except asyncio.TimeoutError:
                if not self._paused:
                    try:
                        await self._generate_report()
                    except Exception as e:
                        logger.error(f"[AITradingCommander] 生成报告失败: {e}")

    async def start_subagent(self, symbol: str) -> TradingSubAgent:
        """启动交易子代理（携带用户配置）"""
        if symbol in self.subagents:
            logger.warning(f"[AITradingCommander] {symbol} 子代理已存在")
            return self.subagents[symbol]

        logger.info(f"[AITradingCommander] 启动 {symbol} 子代理")

        # 获取用户交易所配置
        exchange_config = None
        try:
            from api.exchange_config_api import get_exchange_config_manager
            from core.btc_integration.exchange_config import ExchangeType
            manager = get_exchange_config_manager()
            active_cfg = manager.get_active_config(self.user_id, ExchangeType.OKX)
            if active_cfg:
                exchange_config = {
                    'id': str(active_cfg.id),
                    'exchange': active_cfg.exchange.value if hasattr(active_cfg.exchange, 'value') else str(active_cfg.exchange),
                    'mode': active_cfg.mode.value if hasattr(active_cfg.mode, 'value') else str(active_cfg.mode),
                    'api_key': active_cfg.api_key,
                    'api_secret': active_cfg.api_secret,
                    'passphrase': active_cfg.passphrase,
                    'testnet': active_cfg.testnet,
                }
                logger.info(f"[AITradingCommander] 已加载用户 {self.user_id} 的交易所配置")
        except Exception as e:
            logger.warning(f"[AITradingCommander] 获取用户配置失败，使用模拟盘: {e}")

        agent, task = await start_trading_subagent(
            symbol=symbol,
            user_id=self.user_id,
            exchange_config=exchange_config,
            auto_execute=self.auto_execute,
        )
        self.subagents[symbol] = agent
        # 【治理】保存 task 引用，便于后续健康检查和优雅关闭
        self._task_registry._tasks[f"subagent_{symbol}"] = task
        return agent

    async def stop_subagent(self, symbol: str):
        """停止交易子代理"""
        if symbol not in self.subagents:
            return
        logger.info(f"[AITradingCommander] 停止 {symbol} 子代理")
        agent = self.subagents.pop(symbol)
        agent.stop()

    async def intervene(
        self,
        action: str,
        symbols: list[str] = None,
        reason: str = ""
    ):
        """
        人工/AI干预
        """
        symbols = symbols or list(self.subagents.keys())
        logger.info(f"[AITradingCommander] 执行干预: {action} -> {symbols}, 原因: {reason}")

        for symbol in symbols:
            if symbol not in self.subagents:
                continue
            agent = self.subagents[symbol]
            if action == "pause":
                agent._paused = True
            elif action == "resume":
                agent._paused = False
            elif action == "close_all":
                await agent.close_all_positions(f"指挥官干预: {reason}")
            elif action == "emergency_close":
                await agent.emergency_close_all(f"指挥官紧急干预: {reason}")
            elif action == "reduce_size":
                pass

        publish_ai_intervention(
            command=action,
            params={"symbols": symbols, "reason": reason},
            reason=reason
        )

    async def _generate_report(self):
        """生成AI报告"""
        active_count = sum(1 for a in self.subagents.values() if a._running)

        # 计算总持仓和日盈亏：模拟盘优先从 SimulationExecutor 获取真实模拟数据
        total_positions = 0
        daily_pnl = 0.0
        for agent in self.subagents.values():
            executor = getattr(agent, 'executor', None)
            is_simulation = (
                executor is not None and
                hasattr(executor, '__class__') and
                'Simulation' in executor.__class__.__name__
            )
            if is_simulation:
                try:
                    sim_positions = await executor.get_positions()
                    total_positions += len(sim_positions)
                    daily_pnl += sum(p.get('unrealized_pnl', 0.0) for p in sim_positions)
                except Exception as e:
                    logger.warning(f"[AITradingCommander] 获取模拟持仓失败: {e}")
                    # 降级到 agent.current_position
                    if agent.current_position is not None:
                        total_positions += 1
            else:
                if agent.current_position is not None:
                    total_positions += 1

        # 若模拟盘无数据，回退到累计 realized_pnl
        if daily_pnl == 0.0:
            daily_pnl = self.total_pnl

        ai_thoughts = await self._generate_ai_thoughts()

        report = CommanderReport(
            timestamp=time.time(),
            active_agents=active_count,
            total_positions=total_positions,
            daily_pnl=daily_pnl,
            risk_exposure=await self._assess_overall_risk(),
            recent_decisions=list(self.decision_history[-5:]),
            market_sentiment=await self._analyze_market_sentiment(),
            ai_thoughts=ai_thoughts
        )

        self.latest_report = report
        await self._save_report(report)

        # 【P3新增】推送指挥官报告事件到主事件总线
        try:
            from core.sync.event_bus import event_bus as main_event_bus
            main_event_bus.emit("commander_report", {
                "timestamp": report.timestamp,
                "active_agents": report.active_agents,
                "total_positions": report.total_positions,
                "daily_pnl": report.daily_pnl,
                "risk_exposure": report.risk_exposure,
                "recent_decisions": report.recent_decisions,
                "market_sentiment": report.market_sentiment,
                "ai_thoughts": report.ai_thoughts,
            })
        except Exception as e:
            logger.debug(f"[AITradingCommander] 推送 commander_report 事件失败: {e}")

        await self._notify_user("info", f"AI指挥官报告已生成 | 活跃代理: {active_count} | 持仓: {total_positions}")

    async def _send_thought_step(self, step_type: str, content: str, details: dict = None):
        """发送思维步骤"""
        logger.debug(f"[Thought][{step_type}] {content}")

    async def analyze_and_allocate(self, symbol: str, market_data: dict) -> dict:
        """
        AI决策核心 - Phase4: 通过MCP调用量化决策
        """
        if not MCP_AVAILABLE:
            logger.warning("[AITradingCommander] MCP不可用，无法执行量化分析")
            return {"error": "mcp_not_available", "action": "hold"}
        return await self._analyze_mcp(symbol, market_data)

    async def _analyze_mcp(self, symbol: str, market_data: dict) -> dict:
        """MCP量化分析"""
        await self._send_thought_step("market_analysis", f"开始分析 {symbol} 市场数据...", {
            "price": market_data.get("price", 0),
            "change_24h": market_data.get("price_change_24h", 0)
        })

        # 通过MCP调用量化引擎决策
        # 【集成】优先调用 shadow_analyze 获取真实回测信号
        shadow_signal = None
        try:
            from pathlib import Path
            project_dir = Path(__file__).parent.parent.parent
            shadow_resp = await self._call_mcp_tool(
                server="trading",
                tool="shadow_analyze",
                args={"project_dir": str(project_dir)},
                symbol=symbol
            )

            if shadow_resp and shadow_resp.get("success"):
                raw = shadow_resp.get("data", {})
                # MCP 返回格式: {"content": [{"type": "text", "text": "json_string"}]}
                if isinstance(raw, dict) and "content" in raw:
                    text_content = raw["content"][0].get("text", "{}") if raw["content"] else "{}"
                    import json
                    shadow_signal = json.loads(text_content)
                    logger.info(f"[AITradingCommander] shadow_analyze 成功: symbols={shadow_signal.get('symbols', [])}")
                else:
                    shadow_signal = raw
        except Exception as e:
            logger.warning(f"[AITradingCommander] shadow_analyze 调用失败: {e}")

        # 如果 shadow_analyze 成功获取信号，直接基于信号构造决策
        if shadow_signal and shadow_signal.get("ok"):
            try:
                symbols_data = shadow_signal.get("symbols", {})
                sym_key = symbol.lower()
                if sym_key in symbols_data:
                    sym_data = symbols_data[sym_key]
                    desired = sym_data.get("desired_signal", {})
                    action_map = {"long": "open_long", "short": "open_short", "flat": "close"}
                    action = action_map.get(desired.get("side", "").lower(), "hold")
                    sizing = sym_data.get("sizing", {})
                    confidence = 0.85 if action != "hold" else 0.5
                    reasoning = f"[shadow_analyze] 回测信号: {desired.get('side')} | 分仓: {sizing}"

                    decision_record = {
                        "timestamp": time.time(),
                        "symbol": symbol,
                        "quant_mode": "mcp_shadow",
                        "action": action,
                        "confidence": confidence,
                        "reasoning": reasoning[:200],
                    }
                    self.decision_history.append(decision_record)

                    logger.info(f"[AITradingCommander] MCP shadow 决策: {symbol} {action}")
                    return {
                        "action": action,
                        "confidence": confidence,
                        "reasoning": reasoning,
                        "sizing": sizing,
                        "shadow_signal": shadow_signal,
                    }
            except Exception as e:
                logger.warning(f"[AITradingCommander] shadow 信号解析失败: {e}")

        try:
            decision = await self._call_mcp_tool(
                server="trading",
                tool="make_decision",
                args={
                    "symbol": symbol,
                    "market_data": market_data,
                    "system_prompt": TRADING_AUX_PROMPT
                }
            )

            if not decision or not decision.get("success"):
                logger.warning("[AITradingCommander] MCP量化决策返回失败，降级为hold")
                return {"action": "hold", "confidence": 0.0, "reasoning": "MCP决策失败，保守持有"}

            result = decision.get("data", {})
            action = result.get("action", "hold")
            confidence = result.get("confidence", 0.5)
            reasoning = result.get("reasoning", "")

            # World Model 预交易验证（通过MCP）
            prediction = None
            try:
                pred_resp = await self._call_mcp_tool(
                    server="trading",
                    tool="predict_trade_outcome",
                    args={"decision": result, "market_data": market_data}
                )
                if pred_resp and pred_resp.get("success"):
                    prediction = pred_resp.get("data", {})
                    success_prob = prediction.get("success_probability", 0.5)
                    if success_prob < WORLD_MODEL_SUCCESS_THRESHOLD:
                        logger.warning(f"[AITradingCommander] World Model成功率过低 ({success_prob:.2f})")
                        if WORLD_MODEL_FALLBACK_ACTION == "hold":
                            action = "hold"
                            reasoning += f" [World Model: 成功率{success_prob:.2f}过低，降级为hold]"
                        elif WORLD_MODEL_FALLBACK_ACTION == "reduce":
                            confidence *= success_prob
            except Exception as e:
                logger.warning(f"[AITradingCommander] World Model预测失败: {e}")

            decision_record = {
                "timestamp": time.time(),
                "symbol": symbol,
                "quant_mode": "mcp",
                "action": action,
                "confidence": confidence,
                "reasoning": reasoning[:200],
            }
            if prediction:
                decision_record["world_model_prediction"] = {
                    "success_probability": prediction.get("success_probability"),
                    "expected_pnl": prediction.get("expected_pnl"),
                    "risk_score": prediction.get("risk_score"),
                }

            self.decision_history.append(decision_record)
            self.decision_history = self.decision_history[-100:]

            action_text = {"buy": "买入", "sell": "卖出", "hold": "持仓"}.get(action, action)
            await self._send_thought_step("decision",
                f"AI决策: {action_text} {symbol} | 置信度: {confidence:.1%}", {
                    "action": action,
                    "confidence": confidence,
                    "reasoning": reasoning[:100]
                })

            try:
                publish_ai_decision(
                    decision_type="trade",
                    decision_data={
                        "symbol": symbol,
                        "action": action,
                        "confidence": confidence,
                    },
                    reasoning=reasoning
                )
            except Exception as e:
                logger.error(f"[AITradingCommander] 发布AI决策事件失败: {e}")

            return result

        except Exception as e:
            logger.error(f"[AITradingCommander] MCP量化分析失败: {e}")
            return {"action": "hold", "confidence": 0.0, "reasoning": f"异常: {str(e)}"}

    async def record_trade_result(self, symbol: str, strategy_id: str, pnl: float,
                                   market_data: dict = None, decision=None):
        """记录交易结果 - Phase4: 通过MCP回流"""
        if not MCP_AVAILABLE:
            return

        try:
            # 通过MCP记录交易执行
            await self._call_mcp_tool(
                server="trading",
                tool="record_execution",
                args={
                    "symbol": symbol,
                    "strategy_id": strategy_id,
                    "pnl": pnl,
                    "market_data": market_data or {},
                    "decision": decision,
                }
            )

            # Reflector 交易后反思（通过MCP）
            try:
                reflection = await self._call_mcp_tool(
                    server="trading",
                    tool="reflect_on_trade",
                    args={
                        "symbol": symbol,
                        "pnl": pnl,
                        "strategy_id": strategy_id,
                        "market_data": market_data or {},
                    }
                )
                if reflection and reflection.get("success"):
                    ref_data = reflection.get("data", {})
                    if ref_data.get("should_evolve") and ref_data.get("new_params"):
                        logger.info(f"[AITradingCommander] 策略进化建议: {ref_data.get('improvement_suggestion', '')}")
                        await self._call_mcp_tool(
                            server="trading",
                            tool="record_strategy_evolution",
                            args={
                                "symbol": symbol,
                                "old_params": decision.get("strategy_params", {}) if decision else {},
                                "new_params": ref_data["new_params"],
                                "reason": ref_data.get("improvement_suggestion", ""),
                                "performance_delta": pnl
                            }
                        )

                    await self._call_mcp_tool(
                        server="trading",
                        tool="record_trade_experience",
                        args={
                            "symbol": symbol,
                            "pnl": pnl,
                            "reflection": ref_data,
                        }
                    )
            except Exception as e:
                logger.warning(f"[AITradingCommander] Reflector反思失败: {e}")

        except Exception as e:
            logger.error(f"[AITradingCommander] 记录交易结果失败: {e}")

    async def _generate_ai_thoughts(self) -> str:
        """AI生成当前思考"""
        if time.time() - self.last_thought_time < 60:
            return self.ai_thoughts_cache

        lines = ["【AI量化指挥官思考】", "量化引擎: MCP协议模式", ""]

        # 通过MCP获取策略排名（如有）
        if MCP_AVAILABLE:
            try:
                ranking_resp = await self._call_mcp_tool(
                    server="trading",
                    tool="get_strategy_ranking",
                    args={}
                )
                if ranking_resp and ranking_resp.get("success"):
                    ranking_data = ranking_resp.get("data", {})
                    # 适配 MCP 嵌套返回结构 {"success": True, "data": [...]}
                    if isinstance(ranking_data, dict) and ranking_data.get("success"):
                        rankings = ranking_data.get("data", [])
                    elif isinstance(ranking_data, list):
                        rankings = ranking_data
                    else:
                        rankings = []
                    lines.append("【策略表现排名】")
                    for i, r in enumerate(rankings[:5], 1):
                        name = r.get("name", "unknown")
                        score = r.get("score", 0)
                        trades = r.get("trades", 0)
                        lines.append(f"  {i}. {name:25s} 评分={score:5.1f} 交易={trades}次")
                    lines.append("")
            except Exception as e:
                logger.warning(f"[AITradingCommander] 获取策略排名失败: {e}")

        lines.append(f"【活跃交易对】 {', '.join(self.subagents.keys())}")
        lines.append(f"【风险事件统计】 {self.event_counter}")
        lines.append("")

        if self.decision_history:
            lines.append("【近期决策】")
            for dec in self.decision_history[-3:]:
                lines.append(f"  {dec.get('symbol', '?'):5s} | {dec.get('action', '?'):10s} | 置信{dec.get('confidence', 0):.0%}")

        thoughts = "\n".join(lines)
        self.ai_thoughts_cache = thoughts
        self.last_thought_time = time.time()
        return thoughts

    async def _assess_overall_risk(self) -> str:
        """评估整体风险"""
        if self.event_counter.get("risk_critical", 0) > 0:
            return "CRITICAL"
        if self.event_counter.get("risk_high", 0) > 3:
            return "HIGH"
        if self.event_counter.get("risk_high", 0) > 0:
            return "MEDIUM"
        return "LOW"

    async def _analyze_market_sentiment(self) -> str:
        """分析市场情绪 - Phase4: 通过MCP获取"""
        if not MCP_AVAILABLE:
            return "监控中"
        try:
            resp = await self._call_mcp_tool(
                server="trading",
                tool="analyze_market_sentiment",
                args={"symbols": self.symbols}
            )
            if resp and resp.get("success"):
                return resp.get("data", "监控中")
        except Exception:
            pass
        return "监控中"

    async def _save_report(self, report: CommanderReport):
        """保存报告 - Phase4: 用asyncio.to_thread替代run_in_executor"""
        report_path = Path(".runtime/ai_commander_report.json")
        await asyncio.to_thread(report_path.parent.mkdir, parents=True, exist_ok=True)
        async with aiofiles.open(report_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

        md_path = Path(".runtime/ai_commander_report.md")
        await asyncio.to_thread(md_path.write_text, report.to_markdown(), encoding='utf-8')

    async def _notify_user(self, level: str, message: str):
        """通知用户 - 逐层异步汇总到主AI"""
        logger.info(f"[通知-{level}] {message}")
        try:
            from core.sync.event_bus import event_bus as main_event_bus
            main_event_bus.emit("commander.notification", {
                "level": level,
                "message": message,
                "user_id": self.user_id,
                "timestamp": time.time()
            })
        except Exception as e:
            logger.debug(f"[AITradingCommander] 主事件总线通知失败(非阻塞): {e}")

    async def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "subagents": {
                symbol: SubAgentStatus(
                    runtime_id=agent.runtime_id,
                    symbol=symbol,
                    is_running=agent._running,
                    is_paused=agent._paused,
                    current_position=agent.current_position,
                    bar_count=agent.bar_count,
                    last_ai_decision=agent.decision_history[-1].__dict__ if agent.decision_history else None,
                    profit_loss=0.0,
                    uptime=time.time() - agent.runtime_id.split('_')[-1] if agent.runtime_id else 0,
                ).to_dict()
                for symbol, agent in self.subagents.items()
            },
            "event_stats": self.event_counter,
            "latest_report": self.latest_report.to_dict() if self.latest_report else None,
        }

    async def analyze_and_decide(self, user_request: str) -> str:
        """分析用户请求并生成决策报告"""
        status = await self.get_status()
        report = self.latest_report

        if report is None:
            report = CommanderReport(
                timestamp=time.time(),
                active_agents=status.get("active_agents", len(self.subagents)),
                total_positions=sum(1 for s in self.subagents.values() if s.current_position),
                daily_pnl=status.get("daily_pnl", 0.0),
                risk_exposure=await self._assess_overall_risk(),
                recent_decisions=list(self.decision_history[-5:]),
                market_sentiment=await self._analyze_market_sentiment(),
                ai_thoughts=self.ai_thoughts_cache or "指挥官正在监控市场..."
            )
            self.latest_report = report
            await self._save_report(report)

        try:
            from core.sync.event_bus import event_bus as main_event_bus
            main_event_bus.emit("commander.report", {
                "user_id": self.user_id,
                "report": report.to_dict(),
                "query": user_request,
                "timestamp": time.time()
            })
        except Exception as e:
            logger.debug(f"[AITradingCommander] 汇报事件发送失败(非阻塞): {e}")

        return report.to_markdown()

    # ═══════════════════════════════════════════════════════════════
    # 交易执行接口 - Phase4: 全部改为MCP标准对接
    # ═══════════════════════════════════════════════════════════════

    async def execute_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        leverage: int = 1
    ) -> dict:
        """
        执行交易 - 通过MCP调用交易执行服务
        """
        if not MCP_AVAILABLE:
            return {"error": "MCP客户端未初始化"}

        try:
            order = await self._call_mcp_tool(
                server="trading",
                tool="execute_order",
                args={
                    "symbol": symbol,
                    "side": side.lower(),
                    "quantity": quantity,
                    "order_type": order_type.lower(),
                    "price": price,
                    "leverage": leverage
                }
            )

            if not order or not order.get("success"):
                err = (order or {}).get("error_message", "MCP交易执行返回失败")
                logger.error(f"[AITradingCommander] 交易执行失败: {err}")
                return {"error": err}

            data = order.get("data", {})
            self.total_trades += 1

            self._active_trades[symbol] = {
                "entry_price": data.get("avg_price", 0),
                "quantity": data.get("quantity", 0),
                "side": side,
                "strategy_id": self.current_strategy or "unknown",
                "decision": None,
                "entry_time": time.time()
            }

            logger.info(
                f"[AITradingCommander] [{self.user_id}] 交易执行: "
                f"{symbol} {side} {quantity}, 策略={self.current_strategy or 'unknown'}"
            )

            side_text = "买入" if side.lower() == "buy" else "卖出"
            await self._send_thought_step("execution",
                f"订单执行成功: {side_text} {symbol} @ {data.get('avg_price', 0):.2f} (数量: {data.get('quantity', 0)})", {
                    "symbol": symbol,
                    "action": side,
                    "price": data.get("avg_price"),
                    "quantity": data.get("quantity"),
                    "order_id": data.get("id"),
                    "is_simulation": data.get("is_simulation", False)
                })

            return {
                "success": True,
                "order_id": data.get("id"),
                "symbol": data.get("symbol"),
                "side": data.get("side"),
                "quantity": data.get("quantity"),
                "price": data.get("avg_price"),
                "status": data.get("status"),
                "is_simulation": data.get("is_simulation", False)
            }

        except Exception as e:
            logger.error(f"[AITradingCommander] [{self.user_id}] 交易执行失败: {e}")
            return {"error": str(e)}

    async def close_position(
        self,
        symbol: str,
        quantity: float | None = None
    ) -> dict:
        """
        平仓 - 通过MCP调用交易执行服务
        """
        if not MCP_AVAILABLE:
            return {"error": "MCP客户端未初始化"}

        try:
            order = await self._call_mcp_tool(
                server="trading",
                tool="close_position",
                args={"symbol": symbol, "quantity": quantity}
            )

            if not order or not order.get("success"):
                return {"success": False, "message": "平仓失败或 MCP 返回空"}

            data = order.get("data", {})
            pnl = data.get("pnl", 0)

            trade_info = self._active_trades.pop(symbol, {})
            strategy_id = trade_info.get("strategy_id", "unknown")

            market_data = {"price": data.get("avg_price"), "symbol": symbol}
            await self._task_registry.register(
                f"record_result_{symbol}_{int(time.time())}",
                self.record_trade_result(
                    symbol=symbol,
                    strategy_id=strategy_id,
                    pnl=pnl,
                    market_data=market_data,
                    decision=trade_info.get("decision")
                )
            )

            self.total_pnl += pnl
            logger.info(f"[AITradingCommander] [{self.user_id}] 平仓完成: {symbol} 盈亏={pnl:.2f}")

            return {
                "success": True,
                "order_id": data.get("id"),
                "symbol": data.get("symbol"),
                "closed_qty": data.get("filled_qty"),
                "pnl": pnl,
                "is_simulation": data.get("is_simulation", False)
            }

        except Exception as e:
            logger.error(f"[AITradingCommander] [{self.user_id}] 平仓失败: {e}")
            return {"error": str(e)}

    async def read_autopilot_report(self, user_id: str = None) -> dict:
        """读取全自动量化机器人报告"""
        user_id = user_id or self.user_id
        report_paths = [
            Path(f"core/btc_integration/engine/.runtime/{user_id}/report_latest.txt"),
            Path("core/btc_integration/engine/.runtime/report_latest.txt"),
            Path.home() / "Downloads" / "okx_demo_report_latest.txt"
        ]

        report_file = None
        for path in report_paths:
            if path.exists():
                report_file = path
                break

        if not report_file:
            return {
                "report_found": False,
                "message": "未找到机器人报告"
            }

        try:
            async with aiofiles.open(report_file, encoding='utf-8') as f:
                content = await f.read()
            analysis = await self._analyze_autopilot_report(content)
            return {
                "report_found": True,
                "raw_content": content[:2000] if len(content) > 2000 else content,
                "analysis": analysis
            }
        except Exception as e:
            logger.error(f"[AITradingCommander] 读取机器人报告失败: {e}")
            return {"report_found": False, "error": str(e)}

    async def _analyze_autopilot_report(self, content: str) -> dict:
        """分析机器人报告"""
        analysis = {
            "status": "unknown",
            "pnl": 0.0,
            "risk_level": "normal",
            "suggestion": ""
        }

        if "当前状态:" in content:
            status_match = content.split("当前状态:")[1].split("\n")[0].strip()
            analysis["status"] = status_match

        if "策略当前总收益:" in content:
            try:
                pnl_line = content.split("策略当前总收益:")[1].split("\n")[0].strip()
                pnl_str = pnl_line.replace("U", "").replace(",", "").strip()
                analysis["pnl"] = float(pnl_str)
            except (ValueError, IndexError):
                pass

        if analysis["pnl"] < -100:
            analysis["risk_level"] = "high"
        elif analysis["pnl"] < -50:
            analysis["risk_level"] = "medium"
        else:
            analysis["risk_level"] = "low"

        suggestions = []
        if analysis["status"] == "运行中":
            if analysis["risk_level"] == "high":
                suggestions.append("⚠️ 策略亏损较大，建议暂停全自动量化，切换为AI辅助模式")
            elif analysis["pnl"] > 50:
                suggestions.append("✅ 策略表现良好，建议保持运行并设置止盈线")
            else:
                suggestions.append("⏸️ 策略运行平稳，建议继续观察")
        elif "暂停" in analysis["status"]:
            suggestions.append("⏸️ 策略处于暂停状态，建议确认是否为风控触发")
        else:
            suggestions.append("❓ 策略状态异常，建议查看详细日志")

        analysis["suggestion"] = "\n".join(suggestions)
        return analysis

    async def get_account_info(self) -> dict:
        """获取账户信息 - MCP标准对接"""
        if not MCP_AVAILABLE:
            return {"error": "MCP客户端未初始化"}
        try:
            account = await self._call_mcp_tool(
                server="trading",
                tool="get_account",
                args={}
            )
            position = None
            if self.symbols:
                pos_resp = await self._call_mcp_tool(
                    server="trading",
                    tool="get_position",
                    args={"symbol": self.symbols[0]}
                )
                if pos_resp and pos_resp.get("success"):
                    position = pos_resp.get("data")

            acc_data = account.get("data", {}) if account and account.get("success") else {}

            return {
                "success": True,
                "user_id": self.user_id,
                "mode": "模拟盘" if acc_data.get("is_simulation") else "实盘",
                "exchange": acc_data.get("exchange_type", "unknown"),
                "total_equity": acc_data.get("total_equity", 0),
                "available_balance": acc_data.get("available_balance", 0),
                "unrealized_pnl": acc_data.get("unrealized_pnl", 0),
                "position": {
                    "symbol": position.get("symbol") if position else None,
                    "side": position.get("side") if position else "none",
                    "quantity": position.get("quantity", 0) if position else 0,
                    "entry_price": position.get("entry_price", 0) if position else 0,
                    "unrealized_pnl": position.get("unrealized_pnl", 0) if position else 0
                } if position else None,
            }
        except Exception as e:
            logger.error(f"[AITradingCommander] [{self.user_id}] 获取账户信息失败: {e}")
            return {"error": str(e)}

    async def get_position(self, symbol: str) -> dict | None:
        """获取持仓信息 - MCP标准对接"""
        if not MCP_AVAILABLE:
            return None
        try:
            resp = await self._call_mcp_tool(
                server="trading",
                tool="get_position",
                args={"symbol": symbol}
            )
            if resp and resp.get("success"):
                data = resp.get("data", {})
                return {
                    "symbol": data.get("symbol"),
                    "side": data.get("side"),
                    "quantity": data.get("quantity"),
                    "entry_price": data.get("entry_price"),
                    "mark_price": data.get("mark_price"),
                    "unrealized_pnl": data.get("unrealized_pnl"),
                    "leverage": data.get("leverage")
                }
            return None
        except Exception as e:
            logger.error(f"[AITradingCommander] [{self.user_id}] 获取持仓失败: {e}")
            return None

    async def shutdown(self):
        """关闭指挥官"""
        logger.info(f"[AITradingCommander] [{self.user_id}] 请求关闭")
        await self.stop()

    async def cleanup(self):
        """清理资源"""
        self._running = False
        for _symbol, agent in list(self.subagents.items()):
            agent.stop()
        self.subagents.clear()

        if self.news_monitor:
            await self.news_monitor.stop()

        for unsub in self._subscribers:
            unsub()
        self._subscribers.clear()

        # 【P0修复】删除 event_bus.stop()，子系统不应停止全局事件总线
        logger.info(f"[AITradingCommander] [{self.user_id}] 已清理")

    async def pause(self):
        """暂停指挥官和所有子代理"""
        logger.info(f"[AITradingCommander] [{self.user_id}] 请求暂停")
        self._paused = True
        for symbol, agent in self.subagents.items():
            if agent._running:
                agent._paused = True
                logger.info(f"[AITradingCommander] 已暂停 {symbol} 子代理")
        await self._notify_user("info", "AI指挥官已暂停，不再开新仓")

    async def resume(self):
        """恢复指挥官和所有子代理"""
        logger.info(f"[AITradingCommander] [{self.user_id}] 请求恢复")
        self._paused = False
        for symbol, agent in self.subagents.items():
            if agent._running:
                agent._paused = False
                logger.info(f"[AITradingCommander] 已恢复 {symbol} 子代理")
        await self._notify_user("info", "AI指挥官已恢复运行")

    async def stop(self):
        """停止指挥官"""
        logger.info("[AITradingCommander] 请求停止")
        self._running = False
        self._stop_event.set()
        # 【治理】取消所有后台任务并等待完成
        await self._task_registry.cancel_all(timeout=15.0)

    # ═══════════════════════════════════════════════════════════════
    # Phase4: MCP调用辅助方法
    # ═══════════════════════════════════════════════════════════════

    async def _call_mcp_tool(self, server: str, tool: str, args: dict[str, Any], symbol: str = None) -> dict | None:
        """
        统一MCP工具调用封装

        【P2修复】所有MCP工具调用统一包裹 mcp_call_start / mcp_call_complete 事件，
        确保前端能看见所有MCP调用状态（而非仅 shadow_analyze）。

        Args:
            server: MCP服务器名称
            tool: 工具名称
            args: 调用参数
            symbol: 交易对符号（可选，用于事件推送）

        Returns:
            MCP标准结果字典，或None（客户端不可用时）
        """
        if not MCP_AVAILABLE:
            logger.warning(f"[AITradingCommander] MCP不可用，跳过调用 {server}/{tool}")
            return None

        mcp_start_time = time.time()
        # 推送 MCP 调用开始事件
        try:
            from core.sync.event_bus import event_bus as main_event_bus
            main_event_bus.emit("mcp_call_start", {
                "tool_name": tool,
                "symbol": symbol,
                "timestamp": mcp_start_time,
            })
        except Exception as e:
            logger.debug(f"[AITradingCommander] 推送 MCP 开始事件失败: {e}")

        try:
            result = await mcp_client.call_tool(server, tool, args)
            mcp_duration_ms = int((time.time() - mcp_start_time) * 1000)
            logger.debug(f"[MCP] {server}/{tool} 调用成功")

            # 推送 MCP 调用完成事件（成功）
            try:
                from core.sync.event_bus import event_bus as main_event_bus
                result_summary = "success"
                if isinstance(result, dict):
                    result_summary = f"keys={list(result.keys())}"
                main_event_bus.emit("mcp_call_complete", {
                    "tool_name": tool,
                    "success": True,
                    "duration_ms": mcp_duration_ms,
                    "result_summary": result_summary,
                    "symbol": symbol,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.debug(f"[AITradingCommander] 推送 MCP 完成事件失败: {e}")

            return {
                "success": True,
                "data": result
            }
        except Exception as e:
            mcp_duration_ms = int((time.time() - mcp_start_time) * 1000)
            logger.error(f"[MCP] {server}/{tool} 调用失败: {e}")

            # 推送 MCP 调用完成事件（失败）
            try:
                from core.sync.event_bus import event_bus as main_event_bus
                main_event_bus.emit("mcp_call_complete", {
                    "tool_name": tool,
                    "success": False,
                    "duration_ms": mcp_duration_ms,
                    "result_summary": f"error: {str(e)[:50]}",
                    "symbol": symbol,
                    "timestamp": time.time(),
                })
            except Exception as emit_err:
                logger.debug(f"[AITradingCommander] 推送 MCP 失败事件失败: {emit_err}")

            return {
                "success": False,
                "error_message": str(e)
            }


# 便捷函数
async def start_ai_trading_commander(
    symbols: list[str] = None,
    auto_start: bool = True
) -> AITradingCommander:
    """启动AI交易指挥官"""
    commander = AITradingCommander(symbols=symbols, auto_start=auto_start)
    await commander._task_registry.register("start", commander.start())
    return commander


if __name__ == "__main__":
    async def test():
        commander = await start_ai_trading_commander(symbols=["BTC"])
        await asyncio.sleep(60)
        status = await commander.get_status()
        print(json.dumps(status, indent=2, default=str))
        await commander.stop()

    # Phase4: 禁止同步桥接，测试入口由外部异步框架调度
