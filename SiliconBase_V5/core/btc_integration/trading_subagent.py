#!/usr/bin/env python3
"""
交易子代理 (TradingSubAgent)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将原okx_demo_autopilot改造为AI驱动的可干预子代理

特性:
- 每个交易周期都请求AI决策
- 实时接收消息/风险事件
- 可被AI随时干预（暂停/平仓/调整）
- 使用记忆系统学习和进化
- 通过事件总线与其他组件通信
"""

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.btc_integration.event_bus import (
    EventPriority,
    EventType,
    TradingEvent,
    event_bus,
    publish_ai_decision,
    publish_position_update,
    publish_risk_warning,
)
from core.logger import logger
from core.task.background_task_registry import BackgroundTaskRegistry

# 导入原有功能（带导入保护）
# 注意: okx_demo_autopilot.py 中没有 AppConfig/BarConfig/CoinglassEnforcement 类
# 这些类在 trading_subagent.py 中独立定义
try:
    from core.btc_integration.engine.tools.okx_demo_autopilot import (
        _coinglass_snapshot,
        _completed_bar_open_ms,
        _due_ts_for_completed_open_ms,
        _free_feeds_snapshot,
        _run_shadow_exec,
    )
    OKX_DEMO_AVAILABLE = True
except ImportError as e:
    OKX_DEMO_AVAILABLE = False
    logger.warning(f"[TradingSubAgent] okx_demo_autopilot 导入失败: {e}")

    def _completed_bar_open_ms(*args, **kwargs):
        return None

    def _due_ts_for_completed_open_ms(*args, **kwargs):
        return None

    async def _coinglass_snapshot(*args, **kwargs):
        logger.warning(
            "[TradingSubAgent] _coinglass_snapshot 使用 fallback 实现: "
            "okx_demo_autopilot 导入失败（通常是 core 初始化链依赖缺失，如 psycopg2）。"
        )
        # 尝试直接从 free_feeds_probe 获取数据（异步化，避免阻塞事件循环）
        try:
            import requests

            from core.btc_integration.engine.tools.free_feeds_probe import (
                probe_binance_crowding,
                probe_blockbeats,
                probe_deribit,
                probe_fng,
            )

            def _fetch_sync():
                session = requests.Session()
                try:
                    bb, bb_notes = probe_blockbeats(session)
                    btc, btc_notes = probe_binance_crowding(session, "BTCUSDT")
                    deribit, deribit_notes = probe_deribit(session)
                    fng, fng_notes = probe_fng(session)
                    return bb, bb_notes, btc, btc_notes, deribit, deribit_notes, fng, fng_notes
                finally:
                    session.close()

            bb, bb_notes, btc, btc_notes, deribit, deribit_notes, fng, fng_notes = await asyncio.to_thread(_fetch_sync)
            logger.info(
                "[TradingSubAgent] _coinglass_snapshot fallback 通过 free_feeds_probe 获取到部分数据"
            )
            return {
                "enabled": True,
                "status": "fallback_partial",
                "notes": bb_notes + btc_notes + deribit_notes + fng_notes,
                "blockbeats": bb,
                "binance": {"BTCUSDT": btc},
                "deribit": deribit,
                "fng": fng,
                "use": "observe_only",
            }
        except Exception as probe_e:
            logger.warning(
                f"[TradingSubAgent] _coinglass_snapshot fallback 尝试 free_feeds_probe 也失败: {probe_e}"
            )
        return {
            "enabled": False,
            "status": "fallback",
            "notes": ["okx_demo_autopilot import failed; free_feeds_probe fallback also failed"],
            "blockbeats": {},
            "binance": {},
            "deribit": {},
            "fng": {},
            "use": "observe_only",
        }

    async def _free_feeds_snapshot(*args, **kwargs):
        logger.warning(
            "[TradingSubAgent] _free_feeds_snapshot 使用 fallback 实现: "
            "okx_demo_autopilot 导入失败（通常是 core 初始化链依赖缺失，如 psycopg2）。"
        )
        # 尝试直接从 free_feeds_probe 获取数据（异步化，避免阻塞事件循环）
        try:
            import requests

            from core.btc_integration.engine.tools.free_feeds_probe import (
                probe_binance_crowding,
                probe_blockbeats,
                probe_deribit,
                probe_fng,
            )

            def _fetch_sync():
                session = requests.Session()
                try:
                    bb, bb_notes = probe_blockbeats(session)
                    btc, btc_notes = probe_binance_crowding(session, "BTCUSDT")
                    deribit, deribit_notes = probe_deribit(session)
                    fng, fng_notes = probe_fng(session)
                    return bb, bb_notes, btc, btc_notes, deribit, deribit_notes, fng, fng_notes
                finally:
                    session.close()

            bb, bb_notes, btc, btc_notes, deribit, deribit_notes, fng, fng_notes = await asyncio.to_thread(_fetch_sync)
            logger.info(
                "[TradingSubAgent] _free_feeds_snapshot fallback 通过 free_feeds_probe 获取到部分数据"
            )
            return {
                "enabled": True,
                "status": "fallback_partial",
                "notes": bb_notes + btc_notes + deribit_notes + fng_notes,
                "blockbeats": bb,
                "binance": {"BTCUSDT": btc},
                "deribit": deribit,
                "fng": fng,
                "use": "observe_only",
            }
        except Exception as probe_e:
            logger.warning(
                f"[TradingSubAgent] _free_feeds_snapshot fallback 尝试 free_feeds_probe 也失败: {probe_e}"
            )
        return {
            "enabled": False,
            "status": "fallback",
            "notes": ["okx_demo_autopilot import failed; free_feeds_probe fallback also failed"],
            "blockbeats": {},
            "binance": {},
            "deribit": {},
            "fng": {},
            "use": "observe_only",
        }

    def _run_shadow_exec(*args, **kwargs):
        logger.warning(
            "[TradingSubAgent] _run_shadow_exec 使用 fallback 实现: "
            "okx_demo_autopilot 导入失败（通常是 core 初始化链依赖缺失，如 psycopg2）。"
        )
        return {"ok": False, "error": "okx_demo_autopilot not available"}

# 独立定义这些类（不从 okx_demo_autopilot 导入）
@dataclass
class AppConfig:
    """应用配置"""
    exchange: str = 'okx'
    symbols: list[str] = field(default_factory=list)
    bar: str = '1h'

@dataclass
class BarConfig:
    """Bar配置"""
    tf: str = '1h'
    run_bars: int = 1
    sleep_sec: int = 5

@dataclass
class CoinglassEnforcement:
    """Coinglass执行配置"""
    mode: str = 'normal'
    reason: str = ''
    until_utc: str = ''
from core.btc_integration.ai_strategy_generator import AIStrategyGenerator
from core.btc_integration.strategy_analyzer import MarketCondition, StrategyAnalyzer

# AI客户端
try:
    from core.ai.ai_client import get_default_client as get_ai_client
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    logger.warning("[TradingSubAgent] AI客户端不可用")

# 记忆系统
try:
    from core.memory.memory_manager import get_memory_manager
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("[TradingSubAgent] 记忆系统不可用")

# 交易专用记忆和 resources
try:
    from core.btc_integration.trading_memory import TradeRecord, get_trading_memory
    TRADING_MEMORY_AVAILABLE = True
except ImportError:
    TRADING_MEMORY_AVAILABLE = False
    logger.warning("[TradingSubAgent] 交易记忆不可用")

try:
    from core.btc_integration.trading_resource_guard import get_trading_resource_guard
    RESOURCE_GUARD_AVAILABLE = True
except ImportError:
    RESOURCE_GUARD_AVAILABLE = False
    logger.warning("[TradingSubAgent] 资源守卫不可用")


@dataclass
class TradingDecision:
    """AI交易决策"""
    action: str  # "open_long", "open_short", "close", "hold", "pause"
    direction: str | None = None  # "long" | "short"
    size: float | None = None     # 仓位大小
    leverage: int | None = None   # 杠杆倍数
    stop_loss: float | None = None   # 止损价
    take_profit: float | None = None # 止盈价
    reasoning: str = ""              # AI reasoning
    confidence: float = 0.0          # 置信度 0-1
    strategy_id: str | None = None # 使用的策略
    should_evolve: bool = False      # 是否需要进化策略
    # 【治理】链路追踪ID，贯穿决策→下单→监控→终态
    trace_id: str = field(default_factory=lambda: f"trd_{uuid.uuid4().hex[:12]}_{int(time.time())}")
    # 【审计】决策时的市场指标
    rsi_14: float | None = None
    volatility: float | None = None
    # 【硅基生命-视觉状态机】预备动作链
    pre_actions: list[str] | None = None
    # 【硅基生命-视觉状态机】页面状态判断结果
    visual_state: str | None = None


@dataclass
class TradingContext:
    """交易上下文"""
    market_data: dict = field(default_factory=dict)
    position: dict | None = None
    recent_news: list[dict] = field(default_factory=list)
    recent_trades: list[dict] = field(default_factory=list)
    recent_risk_events: list[dict] = field(default_factory=list)
    risk_level: str = "low"
    strategy_state: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class TradingSubAgent:
    """
    交易子代理

    改造后的交易机器人，作为AI的子代理运行：
    - AI发起交易任务时创建
    - 每周期向AI请求决策
    - 实时接收消息面/风险面变化
    - 可被AI暂停/平仓/调整参数
    - 使用记忆系统学习
    """

    # 状态 → 动作映射表
    # 键: (state, action) 元组
    # 值: (can_execute: bool, pre_actions: List[str])
    STATE_ACTION_MAP = {
        # open_long / open_short
        ("order", "open_long"):   (True,  []),
        ("order", "open_short"):  (True,  []),
        ("idle", "open_long"):    (False, ["navigate_to_order_page"]),
        ("idle", "open_short"):   (False, ["navigate_to_order_page"]),
        ("confirm", "open_long"): (False, ["handle_existing_confirm_dialog"]),
        ("confirm", "open_short"):(False, ["handle_existing_confirm_dialog"]),
        ("error", "open_long"):   (False, ["dismiss_error_dialog"]),
        ("error", "open_short"):  (False, ["dismiss_error_dialog"]),
        ("holding", "open_long"): (False, []),
        ("holding", "open_short"):(False, []),
        # close
        ("holding", "close"):     (True,  []),
        ("idle", "close"):        (False, []),
        ("order", "close"):       (False, []),
        ("confirm", "close"):     (False, []),
        ("error", "close"):       (False, []),
    }

    def __init__(
        self,
        symbol: str = "BTC",
        config_path: str | None = None,
        ai_check_interval: int = 30,  # 【P0修复】从4改为30，每150秒问一次AI，给视觉模型留出GPU加载窗口
        parent_context: dict | None = None,
        user_id: str | None = None,
        exchange_config: dict | None = None,
        auto_execute: bool = True,
    ):
        self.symbol = symbol.upper()
        self.config_path = config_path or "shadow.yml"
        self.ai_check_interval = ai_check_interval
        self.parent_context = parent_context or {}
        self.user_id = user_id or "anonymous"
        self.exchange_config = exchange_config or {}
        self.auto_execute = auto_execute
        self._pending_decisions: dict[str, Any] = {}
        self._pending_events: dict[str, asyncio.Event] = {}

        # 运行状态
        self._running = False
        self._paused = False
        self._stop_event = asyncio.Event()

        # 配置
        self.app_config: AppConfig | None = None
        self.bar_config: BarConfig | None = None

        # 组件
        self.strategy_analyzer = StrategyAnalyzer()
        self.ai_generator: AIStrategyGenerator | None = None
        self.memory = None
        self.trading_memory = None  # 交易专用记忆
        self.resource_guard = None   # 资源守卫
        self.executor = None         # 交易执行器（模拟/实盘）

        # 状态
        self.current_position: dict | None = None
        self.decision_history: list[TradingDecision] = []
        self.last_ai_check_bar = 0
        self.bar_count = 0

        # 风控状态
        self._consecutive_losses: int = 0
        self._total_loss_pct: float = 0.0

        # 消息缓存
        self.recent_news: list[dict] = []
        self.recent_risk_events: list[dict] = []

        # 订阅句柄
        self._subscribers: list[Callable] = []

        # 后台任务注册表（治理：消灭野任务）
        self._task_registry = BackgroundTaskRegistry(f"trading_{symbol}")

        # 运行时ID
        self.runtime_id = f"trading_{symbol}_{int(time.time())}"

        # 【P0-002修复】交易专用 OllamaProvider 实例，隔离视觉调用防止模型状态污染
        self._trading_provider = None
        if AI_AVAILABLE:
            try:
                from core.providers.ollama_provider import OllamaProvider
                self._trading_provider = OllamaProvider({
                    "base_url": "http://localhost:11434",
                    "model": "qwen3:8b",
                    "timeout": 120,
                    "retry_times": 2
                })
                logger.info("[TradingSubAgent] 交易专用 OllamaProvider 实例已创建")
            except Exception as e:
                logger.warning(f"[TradingSubAgent] 创建交易专用 Provider 失败: {e}")

        logger.info(f"[TradingSubAgent] 初始化完成: {self.runtime_id} user={self.user_id}")

    async def initialize(self):
        """初始化组件"""
        # 加载配置
        self.app_config, self.bar_config = await self._load_config()

        # 初始化交易执行器（模拟/实盘）
        await self._init_executor()

        # 推送模拟/实盘状态到前端
        await self._broadcast_simulation_status()

        # 初始化交易记忆
        if TRADING_MEMORY_AVAILABLE:
            self.trading_memory = get_trading_memory()
            logger.info("[TradingSubAgent] 交易记忆已连接")

        # 初始化资源守卫
        if RESOURCE_GUARD_AVAILABLE:
            self.resource_guard = get_trading_resource_guard()
            await self.resource_guard.start_monitor()
            logger.info("[TradingSubAgent] 资源守卫已启动")

        # 初始化AI生成器
        if AI_AVAILABLE:
            self.ai_generator = AIStrategyGenerator()
            if hasattr(self.ai_generator, 'initialize'):
                await self.ai_generator.initialize()

        # 初始化记忆系统
        if MEMORY_AVAILABLE:
            self.memory = await get_memory_manager()

        # 订阅事件
        self._subscribe_events()

        # 启动事件总线（全局单例，由应用生命周期管理器控制）
        # 子代理只订阅，不启动/停止全局总线
        pass

        logger.info("[TradingSubAgent] 组件初始化完成")

    async def _init_executor(self):
        """初始化交易执行器（根据用户配置选择模拟/实盘）"""
        try:
            from core.btc_integration.trade_executor import (
                create_default_executor,
                create_executor,
            )
            if self.exchange_config and self.exchange_config.get('api_key'):
                self.executor = create_executor(self.user_id, self.exchange_config)
                logger.info(
                    f"[TradingSubAgent] 交易执行器已初始化: "
                    f"{'模拟盘' if self.executor.is_simulation else '实盘'} "
                    f"({self.executor.exchange_type})"
                )
            else:
                self.executor = create_default_executor(self.user_id)
                logger.info("[TradingSubAgent] 交易执行器已初始化: 默认模拟盘")
        except Exception as e:
            logger.error(f"[TradingSubAgent] 初始化交易执行器失败: {e}")
            self.executor = None

    async def _broadcast_simulation_status(self):
        """推送模拟/实盘状态到8602交易WebSocket"""
        try:
            from api.trading_ws import trading_ws_manager
            is_sim = self.executor.is_simulation if self.executor else True
            await trading_ws_manager.broadcast_to_symbol(
                self.symbol,
                {
                    "type": "simulation_status",
                    "is_simulation": is_sim,
                    "executor_type": type(self.executor).__name__ if self.executor else "None",
                    "timestamp": time.time()
                }
            )
        except Exception as e:
            logger.error(f"[TradingSubAgent] 推送模拟状态失败: {e}", exc_info=True)

    async def _load_config(self) -> tuple:
        """加载配置（异步化，避免阻塞事件循环）"""
        import yaml
        config_path = Path(self.config_path)
        if not config_path.exists():
            # 创建默认配置
            return self._create_default_config()

        import asyncio
        def _load_config_file():
            with open(config_path, encoding='utf-8') as f:
                return yaml.safe_load(f)
        data = await asyncio.to_thread(_load_config_file)

        app_config = AppConfig(**data.get('app', {}))
        bar_config = BarConfig(**data.get('bar', {}))

        return app_config, bar_config

    def _create_default_config(self) -> tuple:
        """创建默认配置"""
        app_config = AppConfig(
            exchange='okx',
            symbols=[self.symbol],
            bar='1h',
        )
        bar_config = BarConfig(tf='1h', run_bars=1, sleep_sec=5)
        return app_config, bar_config

    def _subscribe_events(self):
        """订阅相关事件"""
        # 风险事件
        unsub_risk = event_bus.subscribe(
            EventType.RISK_WARNING,
            self._on_risk_event,
            priority_filter=EventPriority.HIGH.value
        )
        self._subscribers.append(unsub_risk)

        # 严重风险
        unsub_critical = event_bus.subscribe(
            EventType.RISK_CRITICAL,
            self._on_critical_risk,
            priority_filter=EventPriority.CRITICAL.value
        )
        self._subscribers.append(unsub_critical)

        # AI干预命令
        unsub_ai = event_bus.subscribe(
            EventType.AI_INTERVENTION,
            self._on_ai_intervention,
            priority_filter=EventPriority.CRITICAL.value
        )
        self._subscribers.append(unsub_ai)

        # 消息
        unsub_news = event_bus.subscribe(
            EventType.NEWS_FLASH,
            self._on_news_event,
            priority_filter=EventPriority.HIGH.value
        )
        self._subscribers.append(unsub_news)

        logger.info("[TradingSubAgent] 已订阅事件")

    async def _on_risk_event(self, event: TradingEvent):
        """风险事件处理"""
        logger.warning(f"[TradingSubAgent] 收到风险警告: {event.data}")
        self.recent_risk_events.append({
            "timestamp": event.timestamp,
            "level": event.data.get("level"),
            "message": event.data.get("message"),
        })
        # 保留最近10条
        self.recent_risk_events = self.recent_risk_events[-10:]

        # 高风险时暂停新仓
        if event.data.get("level") in ["critical", "high"]:
            self._paused = True
            logger.warning("[TradingSubAgent] 因风险事件暂停交易")

    async def _on_critical_risk(self, event: TradingEvent):
        """严重风险 - 紧急平仓"""
        logger.critical(f"[TradingSubAgent] 严重风险！紧急平仓: {event.data}")
        await self.emergency_close_all("严重风险事件")

    async def _on_ai_intervention(self, event: TradingEvent):
        """AI干预命令"""
        command = event.data.get("command")
        params = event.data.get("params", {})
        reason = event.data.get("reason", "")

        logger.info(f"[TradingSubAgent] 收到AI干预: {command}, 原因: {reason}")

        if command == "pause":
            self._paused = True
            logger.info("[TradingSubAgent] 已暂停（AI指令）")

        elif command == "resume":
            self._paused = False
            logger.info("[TradingSubAgent] 已恢复（AI指令）")

        elif command == "close_all":
            await self.close_all_positions(f"AI干预: {reason}")

        elif command == "emergency_close":
            await self.emergency_close_all(f"AI紧急干预: {reason}")

        elif command == "adjust_params":
            await self.adjust_parameters(params)

    async def _on_news_event(self, event: TradingEvent):
        """消息事件处理"""
        news = {
            "timestamp": event.timestamp,
            "source": event.source,
            "title": event.data.get("title", ""),
            "content": event.data.get("content", ""),
            "tags": event.data.get("tags", []),
        }
        self.recent_news.append(news)
        self.recent_news = self.recent_news[-20:]  # 保留最近20条

        # 风险标签触发AI决策
        if "risk" in news.get("tags", []):
            logger.warning("[TradingSubAgent] 收到风险快讯，触发AI决策")
            await self._request_ai_decision(force=True)

    async def run(self):
        """主交易循环"""
        self._running = True
        logger.info(f"[TradingSubAgent] 启动交易循环: {self.symbol}")

        try:
            while self._running and not self._stop_event.is_set():
                try:
                    await self._trading_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    import traceback
                    logger.error(f"[TradingSubAgent] 交易周期错误: {type(e).__name__}: {e}")
                    logger.error(f"[TradingSubAgent] 堆栈: {traceback.format_exc()}")
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("[TradingSubAgent] 收到取消信号")
        finally:
            await self.cleanup()

    async def _trading_cycle(self):
        """单个交易周期"""
        self.bar_count += 1

        # 等待下一个bar完成
        current_complete_open_ms = self._get_completed_bar_open_ms()
        due_ts = self._get_due_ts(current_complete_open_ms)

        wait_sec = max(0, due_ts - time.time())
        if wait_sec > 0:
            logger.info(f"[TradingSubAgent] 等待 {wait_sec:.0f} 秒到下一个bar...")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_sec)
                # 正常超时或事件被触发均继续执行
            if self._stop_event.is_set():
                return

        # 暂停状态检查
        if self._paused:
            logger.info("[TradingSubAgent] 当前处于暂停状态，跳过交易")
            return

        # 收集市场数据
        market_snapshot = await self._collect_market_data()

        # 构建交易上下文
        context = TradingContext(
            market_data=market_snapshot,
            position=self.current_position,
            recent_news=self.recent_news.copy(),
            recent_trades=[],  # TODO: 加载最近交易
            recent_risk_events=getattr(self, 'recent_risk_events', []).copy(),
            risk_level=self._assess_risk_level(),
            strategy_state=self._get_strategy_state(),
        )

        # 决策
        decision = await self._make_decision(context)

        # 注入市场指标到决策（用于审计日志）
        if decision:
            market_condition = self._analyze_market(context.market_data)
            decision.rsi_14 = market_condition.rsi_14
            decision.volatility = market_condition.volatility

        # 执行
        if decision and decision.action != "hold":
            await self._execute_decision(decision, context)

        # 更新状态
        self._save_state()

    async def _make_decision(self, context: TradingContext) -> TradingDecision | None:
        """做出交易决策——主入口，负责编排子步骤"""

        # 1. 市场环境分析
        market_condition = self._analyze_market(context.market_data)

        # 2. 判断是否需要AI决策
        if self._should_ask_ai(context):
            ai_decision = await self._request_ai_decision(context, market_condition)
            self.last_ai_check_bar = self.bar_count

            # 3. 对非hold/pause决策进行视觉上下文确认
            if ai_decision and ai_decision.action not in ("hold", "pause"):
                ai_decision = await self._apply_visual_rules(ai_decision)

            if ai_decision:
                return ai_decision

        # 4. 回落规则引擎
        return self._rule_based_decision(context, market_condition)

    def _should_ask_ai(self, context: TradingContext) -> bool:
        """判断当前周期是否需要请求AI决策"""
        if not AI_AVAILABLE:
            return False
        return (
            self.bar_count - self.last_ai_check_bar >= self.ai_check_interval or
            context.risk_level in ["high", "critical"] or
            len(context.recent_news) > 0 or
            context.position is not None
        )

    async def _apply_visual_rules(self, ai_decision: TradingDecision) -> TradingDecision | None:
        """应用视觉规则层：推送意识核心 + 视觉确认 + 预备动作链"""
        try:
            from core.dialog.dialogue_manager import dialogue_manager
            visual_snapshot = dialogue_manager.get_realtime_snapshot(self.user_id)
            objects = visual_snapshot.get("objects", [])
            dominant_app = visual_snapshot.get("dominant_app", "")

            current_state = self._detect_page_state(objects, dominant_app) if objects else "unknown"

            # 推送给意识核心
            await self._push_trading_visual_state(ai_decision, objects, dominant_app, current_state)

            if not objects:
                logger.warning(f"[TradingSubAgent] 视觉快照无objects，跳过视觉检查: user={self.user_id}")
                return ai_decision

            # 视觉确认
            visual_confirmed, pre_actions = self._confirm_with_visual(ai_decision, objects, dominant_app)
            if visual_confirmed:
                logger.info(f"[TradingSubAgent] 视觉检查通过: action={ai_decision.action}, state={current_state}")
                ai_decision.visual_state = current_state
                return ai_decision

            # 未通过但有预备动作
            if pre_actions:
                logger.info(f"[TradingSubAgent] 视觉状态机触发预备动作: {pre_actions}")
                ai_decision.pre_actions = pre_actions
                ai_decision.visual_state = current_state
                return ai_decision

            # 未通过且无预备动作，拦截
            original_action = ai_decision.action
            logger.warning(
                f"[TradingSubAgent] 视觉检查未通过，放弃AI决策: "
                f"action={ai_decision.action}, state={current_state}"
            )
            await self._notify_decision_blocked(original_action, current_state)
            return None

        except Exception as e:
            logger.error(f"[TradingSubAgent] 视觉规则检查异常，保留AI决策: {e}", exc_info=True)
            return ai_decision

    async def _push_trading_visual_state(
        self,
        ai_decision: TradingDecision,
        objects: list[dict],
        dominant_app: str,
        current_state: str
    ):
        """将交易页面视觉状态推送给意识核心"""
        try:
            from core.consciousness.Consciousness import get_consciousness
            consciousness = get_consciousness()
            if not consciousness or not hasattr(consciousness, 'on_vision_update'):
                return

            trading_tags = []
            for obj in objects[:10]:
                tag = {
                    "class": obj.get("class", "未知"),
                    "source": obj.get("source", "未知"),
                    "level": "L2" if obj.get("source") == "uia" else "L1"
                }
                if obj.get("name"):
                    tag["name"] = obj["name"]
                if obj.get("text"):
                    tag["text"] = obj["text"]
                trading_tags.append(tag)

            consciousness.on_vision_update(
                tags=trading_tags,
                dominant_app=dominant_app,
                layout_summary=(
                    f"[交易场景] 页面状态: {current_state} | "
                    f"动作: {ai_decision.action} | 元素数: {len(objects)}"
                )
            )
            logger.info(
                f"[TradingSubAgent] 已推送交易页面状态至意识核心: "
                f"state={current_state}, elements={len(trading_tags)}, dominant_app={dominant_app}"
            )
        except Exception as e:
            logger.error(f"[TradingSubAgent] 推送交易视觉标签给意识核心失败: {e}", exc_info=True)

    async def _notify_decision_blocked(self, original_action: str, current_state: str):
        """通知前端决策被视觉状态机拦截"""
        try:
            from core.btc_integration.ai_trading_manager import ai_trading_manager
            if ai_trading_manager:
                await self._task_registry.register(
                    "send_decision_blocked",
                    ai_trading_manager.send_decision_blocked(
                        user_id=self.user_id,
                        data={
                            "action": original_action,
                            "reason": "visual_state_mismatch",
                            "current_state": current_state,
                            "timestamp": time.time()
                        }
                    )
                )
        except Exception as e:
            logger.error(f"[TradingSubAgent] 推送拦截事件失败: {e}", exc_info=True)

    async def _request_ai_decision(
        self,
        context: TradingContext | None = None,
        market_condition: Any | None = None,
        force: bool = False
    ) -> TradingDecision:
        """向AI请求决策"""

        # 查询记忆
        similar_cases = []
        if MEMORY_AVAILABLE and context:
            similar_cases = await self._query_memory(context)

        # 构建prompt
        prompt = self._build_decision_prompt(context, market_condition, similar_cases)

        # 调用AI（含指数退避重试，规避Ollama模型切换窗口）
        last_error = None
        for attempt in range(2):
            try:
                # 【P0-002修复】优先使用交易专用 Provider 实例，隔离视觉调用
                if self._trading_provider is not None:
                    response = await self._trading_provider.chat_async([
                        {"role": "user", "content": prompt}
                    ])
                else:
                    ai_client = get_ai_client()
                    response = await ai_client.chat_async([
                        {"role": "user", "content": prompt}
                    ])

                # 解析决策
                decision = self._parse_ai_response(response)

                # 发布AI决策事件
                publish_ai_decision(
                    decision_type="trading",
                    decision_data={
                        "action": decision.action,
                        "direction": decision.direction,
                        "confidence": decision.confidence,
                    },
                    reasoning=decision.reasoning
                )

                # 存入记忆
                if MEMORY_AVAILABLE and context:
                    await self._store_decision_memory(context, decision)

                self.decision_history.append(decision)

                # 【P2修复】防止决策历史无限增长导致内存泄漏
                if len(self.decision_history) > 100:
                    self.decision_history = self.decision_history[-50:]
                    logger.debug("[TradingSubAgent] decision_history 已截断至最近50条")

                return decision

            except Exception as e:
                last_error = e
                error_msg = str(e)
                # 检测到Ollama HTTP 400且为快速拒绝（模型切换窗口）时退避重试
                if "HTTP 400" in error_msg and "Ollama" in error_msg and attempt == 0:
                    backoff = 4 + attempt  # 首次4秒
                    logger.warning(f"[TradingSubAgent] AI决策遇到Ollama 400，{backoff}秒后重试...")
                    await asyncio.sleep(backoff)
                    continue
                # 其他错误直接跳出，降级到规则决策
                break

        logger.error(f"[TradingSubAgent] AI决策失败: {last_error}")
        # 降级到规则决策
        return self._rule_based_decision(context, market_condition)

    def _build_decision_prompt(
        self,
        context: TradingContext | None,
        market_condition: Any | None,
        similar_cases: list[dict]
    ) -> str:
        """构建AI决策prompt"""
        # 【Fix】按统一信息流原则，将 KLine 数据转为紧凑 OHLCV 数组格式，保留全部数据但减少 token
        market_data_display = {}
        if context and context.market_data:
            market_data_display = dict(context.market_data)
            raw_klines = market_data_display.get("klines", [])
            if raw_klines and isinstance(raw_klines, list):
                # 紧凑 OHLCV 数组: [time, open, high, low, close, volume]
                compact = []
                for k in raw_klines:
                    if isinstance(k, dict):
                        compact.append([
                            k.get("time", 0),
                            k.get("open", 0.0),
                            k.get("high", 0.0),
                            k.get("low", 0.0),
                            k.get("close", 0.0),
                            k.get("volume", 0.0),
                        ])
                    elif hasattr(k, "time"):
                        compact.append([k.time, k.open, k.high, k.low, k.close, k.volume])
                market_data_display["klines"] = {
                    "schema": "[time, open, high, low, close, volume]",
                    "count": len(compact),
                    "period": "1h",
                    "data": compact,
                }

        prompt = f"""你是专业的BTC交易员，需要根据市场情况做出交易决策。

## 当前市场情况
{json.dumps(market_data_display, indent=2, ensure_ascii=False)}

## 市场环境评估
{json.dumps(market_condition.to_dict() if market_condition else {}, indent=2, ensure_ascii=False)}

## 当前持仓
{json.dumps(context.position if context else None, indent=2, ensure_ascii=False)}

## 最近消息
{json.dumps(context.recent_news[-5:] if context else [], indent=2, ensure_ascii=False)}

## 风险事件
{json.dumps(context.recent_risk_events[-3:] if context else [], indent=2, ensure_ascii=False)}

## 历史类似情况
{json.dumps(similar_cases, indent=2, ensure_ascii=False)}

## 任务
请做出交易决策，返回JSON格式：
{{
    "action": "open_long|open_short|close|hold|pause",
    "direction": "long|short|null",
    "size": 下单的BTC绝对数量（如0.01表示0.01 BTC）,
    "leverage": 杠杆倍数(1-5),
    "stop_loss": 止损价格,
    "take_profit": 止盈价格,
    "reasoning": "决策理由",
    "confidence": 置信度(0-1),
    "should_evolve": 是否需要进化策略(true/false)
}}

硬性约束（不可违反，违反任一约束则返回{"action":"pause"}）：
1. 当前总持仓价值不得超过账户余额的20%
2. 单笔亏损超过账户余额5%必须立即平仓
3. 连续亏损3次后强制暂停，返回{"action":"pause"}
4. 杠杆不得超过5倍
5. 禁止在已有同向持仓时再次开单加仓
6. size字段填写的是BTC绝对数量（如0.01），不是比例或百分比

注意：
1. 如果有风险快讯，优先考虑风险控制
2. 参考历史类似情况的表现
3. confidence低于0.6时建议hold
4. 必须返回合法JSON，不要添加markdown代码块标记
"""
        return prompt

    def _parse_ai_response(self, response: str | None) -> TradingDecision:
        """解析AI响应——支持嵌套JSON、容错清理"""
        import re

        # 【P0防御】Ollama异步化后可能返回None，增加防御
        if response is None:
            logger.error("[TradingSubAgent] AI响应为None，降级到hold")
            return TradingDecision(action="hold", reasoning="AI响应为空", confidence=0)

        raw = response.strip()
        # 1) 清理 markdown 代码块标记
        raw = re.sub(r'^\s*```(?:json)?\s*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\s*```\s*$', '', raw)
        raw = raw.strip()

        candidates = []

        # 2) 如果整体看起来像 JSON，直接尝试
        if raw.startswith('{') and raw.endswith('}'):
            candidates.append(raw)

        # 3) 使用嵌套感知的括号匹配提取所有 {} 块
        def _extract_json_blocks(text: str) -> list[str]:
            blocks = []
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start != -1:
                        blocks.append(text[start:i + 1])
                        start = -1
            return blocks

        candidates.extend(_extract_json_blocks(raw))

        # 4) 逐个尝试解析并修复常见错误
        for candidate in candidates:
            cleaned = candidate
            # 修复尾部逗号（如 `"key": "value",}`）
            cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
            # 修复单引号键/值（简单替换，不处理嵌套引号场景）
            cleaned = cleaned.replace("'", '"')
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict) and "action" in data:
                    return TradingDecision(
                        action=data.get("action", "hold"),
                        direction=data.get("direction"),
                        size=data.get("size"),
                        leverage=data.get("leverage"),
                        stop_loss=data.get("stop_loss"),
                        take_profit=data.get("take_profit"),
                        reasoning=data.get("reasoning", ""),
                        confidence=data.get("confidence", 0.5),
                        should_evolve=data.get("should_evolve", False),
                    )
            except Exception:
                continue

        # 5) 全部失败则降级
        logger.error(f"[TradingSubAgent] 解析AI响应失败，原始响应前200字: {raw[:200]}")
        return TradingDecision(action="hold", reasoning="解析失败", confidence=0)

    def _rule_based_decision(
        self,
        context: TradingContext | None,
        market_condition: Any | None
    ) -> TradingDecision:
        """基于规则的决策（AI不可用时的降级方案）"""
        # 简单规则：如果有持仓且风险高则平仓
        if context and context.position and context.risk_level in ["high", "critical"]:
            return TradingDecision(
                action="close",
                reasoning="风险过高，规则触发平仓",
                confidence=0.8
            )
        return TradingDecision(action="hold", reasoning="无信号", confidence=0.5)

    def _confirm_with_visual(self, decision, objects, dominant_app):
        """
        基于视觉快照和页面状态机确认AI决策的可执行性。
        返回 (bool, List[str])：
          - bool: True 表示视觉层面通过，False 表示应阻止执行
          - List[str]: 预备动作链
        """
        # 空对象保护
        if not objects:
            logger.warning("[TradingSubAgent] 视觉确认收到空objects，跳过检查")
            logger.info(
                f"[VisualStateMachine] 当前页面状态: unknown | "
                f"AI动作: {decision.action} | 结果: 可执行 | 备注: objects为空跳过检查"
            )
            return True, []

        try:
            state = self._detect_page_state(objects, dominant_app)
            action = decision.action

            # adjust 动作始终放行
            if action == "adjust":
                logger.info(
                    f"[VisualStateMachine] 当前页面状态: {state} | "
                    f"AI动作: {action} | 结果: 可执行 | 备注: adjust默认放行"
                )
                return True, []

            # 查字典获取映射
            map_key = (state, action)
            if map_key in self.STATE_ACTION_MAP:
                can_execute, pre_actions = self.STATE_ACTION_MAP[map_key]
                logger.info(
                    f"[VisualStateMachine] 当前页面状态: {state} | "
                    f"AI动作: {action} | 结果: {'可执行' if can_execute else '不可执行'}"
                    f"{' | 预备动作: ' + str(pre_actions) if not can_execute and pre_actions else ''}"
                )
                return can_execute, pre_actions

            # 未定义映射：默认放行
            logger.info(
                f"[VisualStateMachine] 当前页面状态: {state} | "
                f"AI动作: {action} | 结果: 可执行 | 备注: 无映射默认放行"
            )
            return True, []

        except Exception as e:
            logger.error(
                f"[TradingSubAgent] 视觉确认逻辑异常，默认放行: {e}",
                exc_info=True
            )
            logger.info(
                f"[VisualStateMachine] 当前页面状态: exception | "
                f"AI动作: {decision.action} | 结果: 可执行 | 备注: 异常兜底放行"
            )
            return True, []

    def _detect_page_state(self, objects, dominant_app):
        """
        根据视觉快照中的 objects 判断当前交易页面状态。
        返回: "idle" | "order" | "confirm" | "error" | "holding"
        """
        try:
            if self._is_error_state(objects):
                return "error"
            if self._is_confirm_state(objects):
                return "confirm"
            if self._is_order_state(objects):
                return "order"
            if self._is_holding_state(objects, ""):
                return "holding"
            if self._is_idle_state(objects):
                return "idle"
            return "idle"
        except Exception as e:
            logger.error(
                f"[TradingSubAgent] 页面状态检测异常，默认返回idle: {e}",
                exc_info=True
            )
            return "idle"

    def _is_idle_state(self, objects):
        """检测是否为K线图/行情页（idle状态）"""
        has_chart = any(
            obj.get("source") == "onnx" and
            "chart" in obj.get("class", "").lower()
            for obj in objects
        )
        has_chart_uia = any(
            obj.get("source") == "uia" and
            ("chart" in obj.get("name", "").lower() or "k线" in obj.get("name", ""))
            for obj in objects
        )
        return has_chart or has_chart_uia

    def _is_order_state(self, objects):
        """检测是否为下单页"""
        has_buy_btn = any(
            obj.get("source") == "uia" and
            ("buy" in obj.get("name", "").lower() or "买入" in obj.get("name", ""))
            for obj in objects
        )
        has_sell_btn = any(
            obj.get("source") == "uia" and
            ("sell" in obj.get("name", "").lower() or "卖出" in obj.get("name", ""))
            for obj in objects
        )
        has_quantity = any(
            obj.get("source") == "uia" and
            ("quantity" in obj.get("name", "").lower() or "数量" in obj.get("name", ""))
            for obj in objects
        ) or any(
            obj.get("source") == "ocr" and
            obj.get("text", "").replace(".", "").isdigit()
            for obj in objects
        )
        return has_buy_btn and has_sell_btn and has_quantity

    def _is_confirm_state(self, objects):
        """检测是否存在确认弹窗"""
        has_window = any(
            obj.get("source") == "uia" and
            obj.get("class", "") == "Window" and
            any(kw in obj.get("name", "") for kw in ("确认", "取消", "confirm", "cancel", "ok", "yes"))
            for obj in objects
        )
        has_confirm_btn = any(
            obj.get("source") == "uia" and
            any(kw in obj.get("name", "").lower() for kw in ("确认", "确定", "confirm", "ok", "yes"))
            for obj in objects
        )
        has_cancel_btn = any(
            obj.get("source") == "uia" and
            any(kw in obj.get("name", "").lower() for kw in ("取消", "cancel", "no", "close"))
            for obj in objects
        )
        return has_window or (has_confirm_btn and has_cancel_btn)

    def _is_error_state(self, objects):
        """检测是否存在错误状态"""
        error_keywords = ["余额不足", "网络超时", "insufficient balance", "network timeout",
                         "error", "failed", "失败", "超时", "拒绝"]
        for obj in objects:
            text = ""
            if obj.get("source") == "ocr":
                text = obj.get("text", "")
            elif obj.get("source") == "uia":
                text = obj.get("name", "")
            if text and any(kw.lower() in text.lower() for kw in error_keywords):
                return True
        return False

    def _is_holding_state(self, objects, symbol):
        """检测持仓列表页是否存在当前symbol"""
        if not symbol:
            return False
        return any(
            (symbol.upper() if symbol else "") in obj.get("name", "").upper()
            for obj in objects
            if obj.get("source") == "uia"
        )

    async def _execute_pre_actions(self, pre_actions: list[str]) -> bool:
        """
        执行预备动作链。
        返回 True 表示全部执行成功，False 表示执行失败。
        """
        if not pre_actions:
            return True

        logger.info(f"[TradingSubAgent] 开始执行预备动作链: {pre_actions}")

        try:
            from core.vision.gui_locator import get_gui_locator
            locator = get_gui_locator()
            if not locator:
                logger.error("[TradingSubAgent] GUILocator 不可用，无法执行预备动作")
                return False
        except Exception as e:
            logger.error(f"[TradingSubAgent] 获取 GUILocator 失败: {e}", exc_info=True)
            return False

        for i, action in enumerate(pre_actions):
            logger.info(f"[TradingSubAgent] 执行预备动作 [{i+1}/{len(pre_actions)}]: {action}")

            # 尝试执行，失败时重试一次
            max_attempts = 2
            retry_delay = 1.5  # 秒
            success = False

            for attempt in range(1, max_attempts + 1):
                try:
                    if action == "navigate_to_order_page":
                        success = await self._pre_action_navigate_to_order(locator)
                    elif action == "handle_existing_confirm_dialog":
                        success = await self._pre_action_dismiss_dialog(locator, "confirm")
                    elif action == "dismiss_error_dialog":
                        success = await self._pre_action_dismiss_dialog(locator, "error")
                    else:
                        logger.warning(f"[TradingSubAgent] 未知的预备动作: {action}，跳过")
                        break

                    if success:
                        if attempt > 1:
                            logger.warning(
                                f"[TradingSubAgent] 预备动作 {action} 在第 {attempt} 次尝试后成功"
                            )
                        break
                    else:
                        if attempt < max_attempts:
                            logger.warning(
                                f"[TradingSubAgent] 预备动作 {action} 第 {attempt} 次尝试失败，"
                                f"等待 {retry_delay}s 后重试..."
                            )
                            await asyncio.sleep(retry_delay)
                except Exception as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"[TradingSubAgent] 预备动作 {action} 第 {attempt} 次尝试异常，"
                            f"等待 {retry_delay}s 后重试: {e}"
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(
                            f"[TradingSubAgent] 预备动作 {action} 重试 {max_attempts} 次后仍失败: {e}",
                            exc_info=True
                        )

            if not success:
                logger.error(
                    f"[TradingSubAgent] 预备动作执行失败: {action}，"
                    f"已重试 {max_attempts} 次，中断执行链"
                )
                return False

            await asyncio.sleep(0.5)

        logger.info(f"[TradingSubAgent] 预备动作链执行完成: {pre_actions}")
        return True

    async def _pre_action_navigate_to_order(self, locator) -> bool:
        """导航到下单页：先定位 symbol 输入区，输入交易对，点击跳转"""
        try:
            # 第一步：定位 symbol 选择器或搜索框
            target = await locator.locate(
                screenshot=None,
                description=f"{self.symbol}",
                user_id=self.user_id
            )
            if not target:
                logger.error(f"[TradingSubAgent] 未找到 {self.symbol} 的交易入口")
                return False

            # 第二步：点击交易对选择器
            bbox = target.get("bbox")
            if not bbox or len(bbox) != 4:
                logger.error(f"[TradingSubAgent] GUILocator 返回的 bbox 无效: {bbox}")
                return False

            click_x = (bbox[0] + bbox[2]) / 2
            click_y = (bbox[1] + bbox[3]) / 2

            logger.info(
                f"[TradingSubAgent] 点击交易入口: {target.get('matched_name', 'unknown')} "
                f"at ({click_x:.0f}, {click_y:.0f})"
            )

            # 第三步：执行点击
            await self._perform_click(click_x, click_y)
            await asyncio.sleep(1.0)  # 等待页面跳转

            return True

        except Exception as e:
            logger.error(f"[TradingSubAgent] 导航到下单页失败: {e}", exc_info=True)
            return False

    async def _pre_action_dismiss_dialog(self, locator, dialog_type: str) -> bool:
        """关闭弹窗：定位并点击取消/关闭按钮"""
        try:
            # 根据弹窗类型选择要定位的目标
            description = "取消" if dialog_type == "confirm" else "确定"

            target = await locator.locate(
                screenshot=None,
                description=description,
                user_id=self.user_id
            )
            if not target:
                logger.error(f"[TradingSubAgent] 未找到 {dialog_type} 弹窗的关闭按钮")
                return False

            bbox = target.get("bbox")
            if not bbox or len(bbox) != 4:
                logger.error(f"[TradingSubAgent] GUILocator 返回的 bbox 无效: {bbox}")
                return False

            click_x = (bbox[0] + bbox[2]) / 2
            click_y = (bbox[1] + bbox[3]) / 2

            logger.info(
                f"[TradingSubAgent] 关闭 {dialog_type} 弹窗: "
                f"at ({click_x:.0f}, {click_y:.0f})"
            )

            await self._perform_click(click_x, click_y)
            await asyncio.sleep(1.0)

            return True

        except Exception as e:
            logger.error(f"[TradingSubAgent] 关闭 {dialog_type} 弹窗失败: {e}", exc_info=True)
            return False

    async def _perform_click(self, x: float, y: float):
        """执行鼠标点击。使用项目已有的底层方法。"""
        try:
            # 尝试使用已有的 pixel_click 工具
            from tools.pixel_click import PixelClick
            clicker = PixelClick()
            await clicker._execute_async(mode="position", x=int(x), y=int(y))
        except Exception:
            # 回退：使用 pyautogui 直接点击（异步化，避免阻塞事件循环）
            import pyautogui
            await asyncio.to_thread(pyautogui.click, int(x), int(y))

    async def _execute_decision(self, decision: TradingDecision, context: TradingContext):
        """执行交易决策——通过TradeExecutor下单

        【治理】完整交易链路追踪：
        1. 决策生成时记录完整市场状态（带 trace_id）
        2. 订单提交时记录完整参数（带 trace_id）
        3. 订单监控由 TradeExecutor 负责（带 trace_id）
        4. 风控事件携带 trace_id
        """
        trace_id = decision.trace_id
        market_price = context.market_data.get("price") if context else None

        # 【审计】决策生成日志：完整市场状态
        logger.info(
            f"[TradingSubAgent] [{trace_id}] 决策生成 | "
            f"action={decision.action} | confidence={decision.confidence:.2f} | "
            f"market_price={market_price} | rsi_14={decision.rsi_14:.2f} | "
            f"volatility={decision.volatility:.4f} | position={self.current_position} | "
            f"reasoning={decision.reasoning[:80]}..."
        )

        # 半自动模式：推送待确认决策，等待用户确认
        if not self.auto_execute and decision.action not in ("hold", "pause"):
            pending_id = f"pending_{self.user_id}_{self.symbol}_{int(time.time()*1000)}"
            from core.btc_integration.event_bus import publish_decision_pending
            publish_decision_pending(
                user_id=self.user_id,
                pending_id=pending_id,
                decision={
                    "action": decision.action,
                    "direction": decision.direction,
                    "size": decision.size,
                    "leverage": decision.leverage,
                    "reasoning": decision.reasoning,
                    "confidence": decision.confidence,
                },
                context={
                    "symbol": self.symbol,
                    "price": market_price,
                    "timestamp": time.time(),
                },
                trace_id=trace_id
            )
            event = asyncio.Event()
            self._pending_events[pending_id] = event
            self._pending_decisions[pending_id] = {"decision": decision, "context": context}
            logger.info(f"[TradingSubAgent] [{trace_id}] 决策 {pending_id} 等待用户确认...")
            try:
                await asyncio.wait_for(event.wait(), timeout=300)
            except asyncio.TimeoutError:
                logger.warning(f"[TradingSubAgent] [{trace_id}] 决策 {pending_id} 等待确认超时，跳过执行")
                self._pending_events.pop(pending_id, None)
                self._pending_decisions.pop(pending_id, None)
                return
            # 检查是否已被拒绝（decision 被移除表示拒绝）
            if pending_id not in self._pending_decisions:
                logger.info(f"[TradingSubAgent] [{trace_id}] 决策 {pending_id} 已被拒绝，跳过执行")
                return
            self._pending_events.pop(pending_id, None)
            self._pending_decisions.pop(pending_id, None)
            logger.info(f"[TradingSubAgent] [{trace_id}] 决策 {pending_id} 已确认，继续执行")

        if decision.action == "pause":
            self._paused = True
            return

        if not self.executor:
            logger.warning(f"[TradingSubAgent] [{trace_id}] 无交易执行器，跳过执行")
            return

        from core.btc_integration.trade_executor import OrderSide

        # 【硅基生命-视觉状态机】执行预备动作链
        if decision.pre_actions:
            logger.info(
                f"[TradingSubAgent] [{trace_id}] 检测到预备动作链: {decision.pre_actions}"
            )
            pre_actions_success = await self._execute_pre_actions(decision.pre_actions)

            if not pre_actions_success:
                is_simulation = (
                    self.executor is not None and
                    hasattr(self.executor, '__class__') and
                    'Simulation' in self.executor.__class__.__name__
                )

                if is_simulation:
                    logger.warning(
                        f"[TradingSubAgent] [模拟模式] 预备动作链执行失败，降级放行: "
                        f"action={decision.action}, pre_actions={decision.pre_actions}, "
                        f"原因: 模拟盘无真实UI可供GUI定位"
                    )
                    # 不 return，继续执行原交易动作
                else:
                    logger.error(
                        f"[TradingSubAgent] [实盘模式] 预备动作链执行失败，放弃本次决策: "
                        f"action={decision.action}, pre_actions={decision.pre_actions}"
                    )
                    try:
                        from core.btc_integration.event_bus import publish_risk_warning
                        publish_risk_warning(
                            level="high",
                            message=f"视觉状态机预备动作执行失败: {decision.pre_actions}，"
                                    f"交易动作 {decision.action} 已取消",
                            data={"symbol": self.symbol, "action": decision.action},
                            trace_id=trace_id
                        )
                    except Exception:
                        pass
                    return  # 放弃本次决策

            # 预备动作执行成功后，重新验证页面状态
            is_simulation = (
                self.executor is not None and
                hasattr(self.executor, '__class__') and
                'Simulation' in self.executor.__class__.__name__
            )

            if is_simulation:
                logger.info(
                    f"[TradingSubAgent] [模拟模式] 跳过预备动作后的快照验证，"
                    f"直接执行交易: action={decision.action}"
                )
                # 跳过验证，直接进入下单逻辑
            else:
                try:
                    from core.dialog.dialogue_manager import dialogue_manager
                    visual_snapshot = dialogue_manager.get_realtime_snapshot(self.user_id)
                    objects = visual_snapshot.get("objects", [])
                    dominant_app = visual_snapshot.get("dominant_app", "")

                    current_state = self._detect_page_state(objects, dominant_app)
                    can_execute, _ = self._confirm_with_visual(decision, objects, dominant_app)

                    if not can_execute:
                        logger.error(
                            f"[TradingSubAgent] [{trace_id}] 预备动作执行后页面状态仍不正确: "
                            f"state={current_state}, action={decision.action}"
                        )
                        return  # 放弃本次决策

                    logger.info(
                        f"[TradingSubAgent] [{trace_id}] 预备动作执行成功，页面状态验证通过: "
                        f"state={current_state}"
                    )
                except Exception as e:
                    logger.error(
                        f"[TradingSubAgent] [{trace_id}] 预备动作后验证页面状态失败: {e}",
                        exc_info=True
                    )
                    return  # 验证失败，放弃本次决策

        order = None

        # 【P0-风控硬校验】
        if self._consecutive_losses >= 3:
            logger.error(f"[TradingSubAgent] [{trace_id}] 连续亏损{self._consecutive_losses}次，强制暂停交易")
            self._paused = True
            publish_risk_warning(
                level="critical",
                message=f"连续亏损{self._consecutive_losses}次，交易已强制暂停",
                data={"symbol": self.symbol, "reason": "consecutive_losses_limit"},
                trace_id=trace_id
            )
            return

        if decision.action in ("open_long", "open_short"):
            if decision.leverage and decision.leverage > 5:
                logger.error(f"[TradingSubAgent] [{trace_id}] 杠杆{decision.leverage}超过上限5倍，拒绝执行")
                publish_risk_warning(
                    level="high",
                    message=f"杠杆{decision.leverage}超过上限5倍，订单被拒绝",
                    data={"symbol": self.symbol, "leverage": decision.leverage},
                    trace_id=trace_id
                )
                return
            if decision.size and decision.size > 0.1:
                logger.error(f"[TradingSubAgent] [{trace_id}] 仓位{decision.size}BTC超过上限0.1 BTC，拒绝执行")
                publish_risk_warning(
                    level="high",
                    message=f"仓位{decision.size}BTC超过上限0.1 BTC，订单被拒绝",
                    data={"symbol": self.symbol, "size": decision.size},
                    trace_id=trace_id
                )
                return
            if self.current_position is not None:
                current_side = self.current_position.get("side")
                if (decision.action == "open_long" and current_side == "buy") or \
                   (decision.action == "open_short" and current_side == "sell"):
                    logger.error(f"[TradingSubAgent] [{trace_id}] 已有同向持仓，禁止加仓")
                    publish_risk_warning(
                        level="high",
                        message="已有同向持仓，加仓订单被拒绝",
                        data={"symbol": self.symbol, "current_side": current_side},
                        trace_id=trace_id
                    )
                    return

        try:
            if decision.action == "open_long":
                order = await self.executor.execute_order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    quantity=decision.size or 0.01,
                    leverage=decision.leverage or 1,
                )
                # 将 trace_id 绑定到订单
                if order:
                    order.trace_id = trace_id
                # 更新持仓状态
                pos = await self.executor.get_position(self.symbol)
                if pos:
                    self.current_position = {
                        "symbol": pos.symbol,
                        "side": pos.side.value,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "leverage": pos.leverage,
                    }
                logger.info(
                    f"[TradingSubAgent] [{trace_id}] 开多仓成功 | "
                    f"order_id={order.id if order else 'N/A'} | qty={decision.size or 0.01} | "
                    f"leverage={decision.leverage or 1}"
                )

            elif decision.action == "open_short":
                order = await self.executor.execute_order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    quantity=decision.size or 0.01,
                    leverage=decision.leverage or 1,
                )
                if order:
                    order.trace_id = trace_id
                pos = await self.executor.get_position(self.symbol)
                if pos:
                    self.current_position = {
                        "symbol": pos.symbol,
                        "side": pos.side.value,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "leverage": pos.leverage,
                    }
                logger.info(
                    f"[TradingSubAgent] [{trace_id}] 开空仓成功 | "
                    f"order_id={order.id if order else 'N/A'} | qty={decision.size or 0.01} | "
                    f"leverage={decision.leverage or 1}"
                )

            elif decision.action == "close":
                order = await self.executor.close_position(self.symbol)
                if order:
                    order.trace_id = trace_id
                logger.info(
                    f"[TradingSubAgent] [{trace_id}] 平仓成功 | "
                    f"order_id={order.id if order else '无持仓'}"
                )
                # 平仓后等待并重新查询持仓确认
                await asyncio.sleep(2.0)
                try:
                    pos = await self.executor.get_position(self.symbol)
                    if pos:
                        self.current_position = {
                            "symbol": pos.symbol,
                            "side": pos.side.value,
                            "quantity": pos.quantity,
                            "entry_price": pos.entry_price,
                            "leverage": pos.leverage,
                        }
                        logger.warning(
                            f"[TradingSubAgent] [{trace_id}] 平仓后仍有持仓: "
                            f"side={pos.side.value}, qty={pos.quantity}"
                        )
                    else:
                        self.current_position = None
                        logger.info(f"[TradingSubAgent] [{trace_id}] 平仓后确认无持仓")
                except Exception as pos_e:
                    logger.error(f"[TradingSubAgent] [{trace_id}] 平仓后查询持仓失败: {pos_e}")
                    self.current_position = None

        except Exception as e:
            logger.error(
                f"[TradingSubAgent] [{trace_id}] 交易执行失败 | "
                f"action={decision.action} | error={e}"
            )
            # 【P1修复】局部导入避免 UnboundLocalError
            try:
                from core.btc_integration.event_bus import publish_risk_warning
                publish_risk_warning(
                    level="high",
                    message=f"交易执行失败: {e}",
                    data={"symbol": self.symbol, "action": decision.action},
                    trace_id=trace_id
                )
            except Exception:
                pass
            return

        # 发布持仓更新事件（携带 trace_id）
        publish_position_update(
            symbol=self.symbol,
            position_data={
                "action": decision.action,
                "direction": decision.direction,
                "size": decision.size,
                "timestamp": time.time(),
                "trace_id": trace_id,
            },
            trace_id=trace_id
        )

        # 记录交易到记忆系统
        if self.trading_memory and decision.action in ["open_long", "open_short", "close"]:
            trade = TradeRecord(
                symbol=self.symbol,
                action=decision.action,
                direction=decision.direction,
                size=decision.size or 0.0,
                price=context.market_data.get("price", 0.0),
                leverage=decision.leverage or 1,
                strategy=decision.strategy_id or "default",
                reasoning=decision.reasoning,
                visual_state=decision.visual_state,
            )
            await self.trading_memory.record_trade(trade)
            logger.debug("[TradingSubAgent] 交易已记录到记忆系统")

    async def close_all_positions(self, reason: str):
        """平仓所有持仓"""
        logger.info(f"[TradingSubAgent] 平仓: {reason}")
        if self.executor:
            try:
                await self.executor.close_position(self.symbol)
                logger.info(f"[TradingSubAgent] 通过执行器平仓: {self.symbol}")
            except Exception as e:
                logger.error(f"[TradingSubAgent] 执行器平仓失败: {e}")
        self.current_position = None
        publish_position_update(
            symbol=self.symbol,
            position_data={"action": "close_all", "reason": reason}
        )

    async def emergency_close_all(self, reason: str):
        """紧急平仓"""
        logger.critical(f"[TradingSubAgent] 紧急平仓: {reason}")
        await self.close_all_positions(reason)
        self._paused = True
        publish_risk_warning(
            level="critical",
            message=f"紧急平仓: {reason}",
            data={"symbol": self.symbol, "action": "emergency_close"}
        )

    async def adjust_parameters(self, params: dict):
        """调整交易参数"""
        logger.info(f"[TradingSubAgent] 调整参数: {params}")
        if "leverage" in params:
            self.app_config.leverage = params["leverage"]
        if "ai_check_interval" in params:
            self.ai_check_interval = params["ai_check_interval"]

    async def _collect_market_data(self) -> dict:
        """收集市场数据——接入OKX真实行情"""
        from core.btc_integration.market_data import get_market_data_provider

        provider = get_market_data_provider()

        # 获取实时价格
        price_data = await provider.get_price(self.symbol)

        # 获取K线数据（用于技术指标计算）
        klines = await provider.get_klines(self.symbol, interval="1h", limit=50)

        # 【Fix】将 KLineData 转为纯字典列表，避免下游 JSON 序列化失败
        klines_dicts = [k.__dict__ if hasattr(k, '__dict__') else k for k in klines] if klines else []

        result = {
            "symbol": self.symbol,
            "timestamp": time.time(),
            "price": price_data.price if price_data else 0.0,
            "change_24h": price_data.change_24h if price_data else 0.0,
            "change_24h_percent": price_data.change_24h_percent if price_data else 0.0,
            "high_24h": price_data.high_24h if price_data else 0.0,
            "low_24h": price_data.low_24h if price_data else 0.0,
            "volume_24h": price_data.volume_24h if price_data else 0.0,
            "klines": klines_dicts,
        }

        logger.info(f"[TradingSubAgent] 市场数据已收集: {self.symbol} @ {result['price']:.2f}, change_24h_percent={result['change_24h_percent']:.4f}")

        # 推送市场数据更新到主事件总线（频率限制：不超过1次/秒）
        try:
            now = time.time()
            last_emit = getattr(self, '_last_market_data_emit', 0)
            if now - last_emit >= 1.0:
                from core.sync.event_bus import event_bus as main_event_bus
                main_event_bus.emit("market_data_update", {
                    "symbol": self.symbol,
                    "price": result["price"],
                    "change_24h_percent": result["change_24h_percent"],
                    "source": "okx",
                    "timestamp": now,
                })
                self._last_market_data_emit = now
                logger.info(f"[TradingSubAgent] 已发射 market_data_update: {self.symbol}")
        except Exception as e:
            logger.error(f"[TradingSubAgent] 推送市场数据事件失败: {e}", exc_info=True)

        return result

    def _analyze_market(self, market_data: dict) -> MarketCondition:
        """分析市场环境——基于真实K线计算技术指标"""
        klines = market_data.get("klines", [])
        if not klines or len(klines) < 20:
            # 数据不足时回退到默认值
            return MarketCondition(
                trend="sideways",
                trend_strength=0.5,
                volatility=0.3,
                rsi_14=50.0,
            )

        # 【Fix】兼容 dict 和对象两种形式的 KLine 数据
        def _get_close(k):
            return k["close"] if isinstance(k, dict) else k.close

        closes = [_get_close(k) for k in klines]

        # 计算 RSI(14)
        rsi = self._calculate_rsi(closes, period=14)

        # 计算趋势（短期SMA vs 长期SMA）
        sma_short = self._calculate_sma(closes, period=7)
        sma_long = self._calculate_sma(closes, period=25)

        if sma_short and sma_long:
            if sma_short > sma_long * 1.02:
                trend = "uptrend"
                trend_strength = min(1.0, (sma_short / sma_long - 1) * 50)
            elif sma_short < sma_long * 0.98:
                trend = "downtrend"
                trend_strength = min(1.0, (1 - sma_short / sma_long) * 50)
            else:
                trend = "sideways"
                trend_strength = 0.3
        else:
            trend = "sideways"
            trend_strength = 0.5

        # 计算波动率（最近20根K线收益率标准差）
        volatility = self._calculate_volatility(closes)

        return MarketCondition(
            trend=trend,
            trend_strength=trend_strength,
            volatility=volatility,
            rsi_14=rsi,
        )

    @staticmethod
    def _calculate_rsi(closes: list[float], period: int = 14) -> float:
        """计算RSI指标"""
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calculate_sma(closes: list[float], period: int) -> float | None:
        """计算简单移动平均"""
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    @staticmethod
    def _calculate_volatility(closes: list[float], period: int = 20) -> float:
        """计算波动率（收益率标准差）"""
        if len(closes) < period + 1:
            return 0.3

        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

        if len(returns) < period:
            return 0.3

        recent_returns = returns[-period:]
        mean = sum(recent_returns) / len(recent_returns)
        variance = sum((r - mean) ** 2 for r in recent_returns) / len(recent_returns)
        std = variance ** 0.5

        # 年化波动率（假设每小时一根K线）
        return std * (24 * 365) ** 0.5

    def _assess_risk_level(self) -> str:
        """评估风险等级"""
        if not self.recent_risk_events:
            return "low"

        recent_critical = any(
            e.get("level") == "critical"
            for e in self.recent_risk_events[-5:]
        )
        if recent_critical:
            return "critical"

        recent_high = any(
            e.get("level") in ["critical", "high"]
            for e in self.recent_risk_events[-5:]
        )
        if recent_high:
            return "high"

        return "medium"

    def _get_strategy_state(self) -> dict:
        """获取策略状态"""
        return {
            "bar_count": self.bar_count,
            "last_ai_check": self.last_ai_check_bar,
            "decision_count": len(self.decision_history),
        }

    async def _query_memory(self, context: TradingContext) -> list[dict]:
        """查询记忆"""
        if not self.memory:
            return []

        try:
            results = await self.memory.retrieve_memory(
                query=json.dumps(context.market_data, default=str),
                mem_type="trading_decision",
                limit=3,
                use_vector=True,
            )
            return results
        except Exception as e:
            logger.error(f"[TradingSubAgent] 记忆查询失败: {e}")
            return []

    async def _store_decision_memory(self, context: TradingContext, decision: TradingDecision):
        """存储决策到记忆"""
        if not self.memory:
            return

        try:
            await self.memory.add_memory(
                user_id="default",
                content={
                    "type": "trading_decision",
                    "symbol": self.symbol,
                    "context": context.market_data,
                    "decision": {
                        "action": decision.action,
                        "direction": decision.direction,
                        "confidence": decision.confidence,
                        "reasoning": decision.reasoning,
                    },
                    "timestamp": time.time(),
                },
                memory_type="trading_decision",
            )
        except Exception as e:
            logger.error(f"[TradingSubAgent] 记忆存储失败: {e}")

    def _get_completed_bar_open_ms(self) -> int:
        """获取已完成bar的开盘时间

        根据当前时间和bar周期（如1h），计算上一个已完成bar的开盘时间戳（毫秒）。
        例如：当前10:05，1h周期 → 返回10:00:00的毫秒时间戳
        """
        import datetime
        now = datetime.datetime.now()
        tf = self.bar_config.tf if self.bar_config else "1h"

        if tf.endswith("h"):
            hours = int(tf[:-1])
            current_hour = now.hour
            completed_bar_hour = (current_hour // hours) * hours
            bar_open = now.replace(hour=completed_bar_hour, minute=0, second=0, microsecond=0)
            if bar_open >= now:
                # 当前正好在bar边界，取上一个bar
                bar_open -= datetime.timedelta(hours=hours)
        elif tf.endswith("m"):
            minutes = int(tf[:-1])
            current_minute = now.minute
            completed_bar_minute = (current_minute // minutes) * minutes
            bar_open = now.replace(minute=completed_bar_minute, second=0, microsecond=0)
            if bar_open >= now:
                bar_open -= datetime.timedelta(minutes=minutes)
        elif tf.endswith("d"):
            days = int(tf[:-1])
            bar_open = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if bar_open >= now:
                bar_open -= datetime.timedelta(days=days)
        else:
            # 默认1h
            current_hour = now.hour
            bar_open = now.replace(hour=current_hour, minute=0, second=0, microsecond=0)
            if bar_open >= now:
                bar_open -= datetime.timedelta(hours=1)

        return int(bar_open.timestamp() * 1000)

    def _get_due_ts(self, open_ms: int) -> float:
        """计算下次检查时间

        根据已完成bar的开盘时间，计算下一个bar的开盘时间。
        """
        import datetime
        tf = self.bar_config.tf if self.bar_config else "1h"
        bar_open_dt = datetime.datetime.fromtimestamp(open_ms / 1000.0)

        if tf.endswith("h"):
            hours = int(tf[:-1])
            next_bar_open = bar_open_dt + datetime.timedelta(hours=hours * 2)
        elif tf.endswith("m"):
            minutes = int(tf[:-1])
            next_bar_open = bar_open_dt + datetime.timedelta(minutes=minutes * 2)
        elif tf.endswith("d"):
            days = int(tf[:-1])
            next_bar_open = bar_open_dt + datetime.timedelta(days=days * 2)
        else:
            next_bar_open = bar_open_dt + datetime.timedelta(hours=2)

        due_ts = next_bar_open.timestamp()
        wait_sec = due_ts - time.time()
        if wait_sec < 0:
            # 如果已经错过，等待一个完整周期
            if tf.endswith("h"):
                due_ts = time.time() + int(tf[:-1]) * 3600
            elif tf.endswith("m"):
                due_ts = time.time() + int(tf[:-1]) * 60
            elif tf.endswith("d"):
                due_ts = time.time() + int(tf[:-1]) * 86400
            else:
                due_ts = time.time() + 3600

        logger.info(f"[TradingSubAgent] 下一个bar开盘时间: {next_bar_open.isoformat()}, 等待{wait_sec:.0f}秒")
        return due_ts

    def _save_state(self):
        """保存状态"""
        state = {
            "runtime_id": self.runtime_id,
            "symbol": self.symbol,
            "bar_count": self.bar_count,
            "paused": self._paused,
            "position": self.current_position,
            "decision_history": [
                {
                    "action": d.action,
                    "confidence": d.confidence,
                    "timestamp": time.time(),
                }
                for d in self.decision_history[-10:]
            ],
        }

        state_path = Path(f".runtime/trading_subagent_{self.symbol}.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        from core.utils.file_utils import write_json
        write_json(state_path, state, indent=2)

    def confirm_decision(self, pending_id: str) -> bool:
        """确认待执行决策"""
        if pending_id not in self._pending_events:
            logger.warning(f"[TradingSubAgent] 未找到待确认决策: {pending_id}")
            return False
        self._pending_events[pending_id].set()
        from core.btc_integration.event_bus import publish_decision_confirmed
        publish_decision_confirmed(user_id=self.user_id, pending_id=pending_id)
        logger.info(f"[TradingSubAgent] 决策 {pending_id} 已确认")
        return True

    def reject_decision(self, pending_id: str) -> bool:
        """拒绝待执行决策"""
        if pending_id not in self._pending_events:
            logger.warning(f"[TradingSubAgent] 未找到待确认决策: {pending_id}")
            return False
        # 移除决策记录，让执行线程知道被拒绝
        self._pending_decisions.pop(pending_id, None)
        self._pending_events[pending_id].set()
        from core.btc_integration.event_bus import publish_decision_rejected
        publish_decision_rejected(user_id=self.user_id, pending_id=pending_id)
        logger.info(f"[TradingSubAgent] 决策 {pending_id} 已拒绝")
        return True

    async def cleanup(self):
        """清理资源"""
        self._running = False

        # 取消订阅（只清理自己的订阅，不停止全局总线）
        for unsub in self._subscribers:
            unsub()
        self._subscribers.clear()

        # 保存状态
        self._save_state()

        # 取消所有后台任务（治理：优雅关闭）
        await self._task_registry.cancel_all(timeout=10.0)

        # 【治理】全局 EventBus 由应用生命周期管理器控制，子代理不得停止
        # await event_bus.stop()  # ← 已删除，防止级联故障

        logger.info("[TradingSubAgent] 已清理")

    def stop(self):
        """停止交易"""
        logger.info("[TradingSubAgent] 请求停止")
        self._running = False
        self._stop_event.set()


# 便捷函数
async def start_trading_subagent(
    symbol: str = "BTC",
    config_path: str | None = None,
    user_id: str | None = None,
    exchange_config: dict | None = None,
    auto_execute: bool = True,
) -> tuple[TradingSubAgent, asyncio.Task]:
    """启动交易子代理

    Returns:
        (agent, task) 元组，task 为交易循环的后台任务
        【治理】调用方必须保存 task 引用，防止野任务
    """
    agent = TradingSubAgent(
        symbol=symbol,
        config_path=config_path,
        user_id=user_id,
        exchange_config=exchange_config,
        auto_execute=auto_execute,
    )
    await agent.initialize()

    # 【治理】通过注册表启动交易循环，而非裸 create_task
    task = await agent._task_registry.register("trading_cycle", agent.run())

    return agent, task


if __name__ == "__main__":
    async def test():
        agent, task = await start_trading_subagent()
        await asyncio.sleep(10)
        agent.stop()
        await task  # 等待交易循环结束

    asyncio.run(test())
