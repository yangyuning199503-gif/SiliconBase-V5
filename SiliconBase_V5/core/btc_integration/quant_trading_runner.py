#!/usr/bin/env python3
"""
量化交易运行器 (QuantTradingRunner)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
替代 okx_demo_autopilot 子进程模式，
通过 ShadowSignalProvider 复用复杂回测逻辑，
用 TradeExecutor 统一执行层下单。
"""

import asyncio
import contextlib
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from core.btc_integration.event_bus import (
    publish_position_update,
    publish_quant_signal,
    publish_risk_warning,
)
from core.btc_integration.market_data import (
    OKXMarketDataProvider,
    calculate_adx,
    calculate_bollinger_bandwidth,
    classify_market_state,
)
from core.btc_integration.shadow_signal_provider import QuantSignal, ShadowSignalProvider
from core.btc_integration.trade_executor import OrderSide, TradeExecutor, create_default_executor, create_executor
from core.diagnostic import safe_create_task
from core.estimation.state_estimator import ParticleFilter
from core.logger import logger


@dataclass
class RunnerState:
    """运行器状态"""
    is_running: bool = False
    cycle_count: int = 0
    last_signal_time: float = 0.0
    last_error: str = ""


class QuantTradingRunner:
    """
    量化交易运行器

    - 定时调用 ShadowSignalProvider 获取策略信号
    - 用 TradeExecutor 执行订单
    - 发布 EventBus 事件供 AI 和其他模块观测
    """

    def __init__(
        self,
        user_id: str,
        symbols: list[str],
        project_dir: str,
        exchange_config: dict[str, Any] | None = None,
        bar_interval: int = 900,  # 15分钟
        grace_seconds: int = 20,
    ):
        self.user_id = user_id
        self.symbols = [s.lower() for s in symbols]
        self.project_dir = Path(project_dir)
        self.exchange_config = exchange_config or {}
        self.bar_interval = bar_interval
        self.grace_seconds = grace_seconds

        self.signal_provider = ShadowSignalProvider(project_dir, user_id)
        self.market_provider = OKXMarketDataProvider()
        self.executor: TradeExecutor | None = None
        self.state = RunnerState()

        # ── PF：信号置信度粒子滤波（LeJEPA 多假设追踪）────────────────────
        self.signal_confidence_pf = ParticleFilter(
            num_particles=100,
            state_dim=1,
            initial_state_sampler=lambda: np.array([np.random.beta(2, 2)])
        )
        self._pending_signals = deque(maxlen=10)  # 待评估的信号队列

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

        logger.info(f"[QuantTradingRunner] 初始化: user={user_id} symbols={symbols}")

    async def start(self):
        """启动定时循环"""
        if self.state.is_running:
            logger.warning("[QuantTradingRunner] 已在运行")
            return

        # 初始化执行器
        await self._init_executor()

        self.state.is_running = True
        self._stop_event.clear()
        self._task = safe_create_task(self._run_loop(), name="_run_loop")
        logger.info("[QuantTradingRunner] 已启动")

    async def stop(self):
        """停止循环"""
        if not self.state.is_running:
            return

        self.state.is_running = False
        self._stop_event.set()

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        logger.info("[QuantTradingRunner] 已停止")

    async def _init_executor(self):
        """初始化交易执行器"""
        try:
            if self.exchange_config and self.exchange_config.get('api_key'):
                self.executor = create_executor(self.user_id, self.exchange_config)
                logger.info(
                    f"[QuantTradingRunner] 执行器: "
                    f"{'模拟' if self.executor.is_simulation else '实盘'}"
                )
            else:
                self.executor = create_default_executor(self.user_id)
                logger.info("[QuantTradingRunner] 执行器: 默认模拟盘")
        except Exception as e:
            logger.error(f"[QuantTradingRunner] 初始化执行器失败: {e}")
            self.executor = create_default_executor(self.user_id)

    async def _run_loop(self):
        """主循环"""
        while self.state.is_running and not self._stop_event.is_set():
            try:
                await self.run_single_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[QuantTradingRunner] 周期错误: {e}")
                self.state.last_error = str(e)

            # 等待下一个周期
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(5, self.bar_interval - self.grace_seconds)
                )
            except asyncio.TimeoutError:
                continue

    async def run_single_cycle(self):
        """执行单轮量化交易"""
        logger.info("[QuantTradingRunner] ===== 开始新一轮信号计算 =====")

        # -1. 评估上一个周期信号的实际表现，更新 PF
        await self._evaluate_pending_signals()

        # 0. 获取市场状态（ADX + 布林带宽度）
        market_states = {}
        for symbol in self.symbols:
            try:
                klines = await self.market_provider.get_klines(symbol, interval="15m", limit=50)
                if klines and len(klines) >= 21:
                    adx = calculate_adx(klines, period=14)
                    bb = calculate_bollinger_bandwidth(klines, period=20)
                    market_states[symbol] = classify_market_state(adx, bb["bandwidth_pct"])
                    logger.info(
                        f"[QuantTradingRunner] {symbol} 市场状态: {market_states[symbol]} "
                        f"(ADX={adx:.1f}, BBW={bb['bandwidth_pct']:.4f})"
                    )
            except Exception as e:
                logger.debug(f"[QuantTradingRunner] 获取 {symbol} 市场状态失败: {e}")

        # 1. 获取信号
        signals = await self.signal_provider.generate_signal()
        self.state.cycle_count += 1
        self.state.last_signal_time = time.time()

        if not signals:
            logger.warning("[QuantTradingRunner] 未获取到信号")
            return

        # 1.5 根据市场状态调整仓位（LeJEPA 状态推断引擎）
        for sym, signal in signals.items():
            state = market_states.get(sym.lower(), "normal")
            if state == "ranging":
                signal.target_notional_usdt *= 0.3
                signal.risk_override["market_state"] = "ranging_reduce_70pct"
                logger.info(f"[QuantTradingRunner] {sym} 震荡市，仓位降至30%")
            elif state == "breaking":
                signal.target_notional_usdt *= 0.5
                signal.risk_override["market_state"] = "breaking_caution_50pct"
                logger.info(f"[QuantTradingRunner] {sym} 突破市，仓位降至50%")
            elif state == "trending":
                signal.risk_override["market_state"] = "trending_normal"

        # 1.6 PF 信号置信度调整（LeJEPA 多假设追踪）
        confidence = self._get_signal_confidence()
        if confidence < 0.3:
            logger.warning(
                f"[QuantTradingRunner] PF 信号置信度过低({confidence:.2f})，跳过执行"
            )
            return
        elif confidence < 0.6:
            for signal in signals.values():
                signal.target_notional_usdt *= confidence
            logger.info(
                f"[QuantTradingRunner] PF 信号置信度中等({confidence:.2f})，仓位按比例调整"
            )
        else:
            logger.info(
                f"[QuantTradingRunner] PF 信号置信度高({confidence:.2f})，正常执行"
            )

        # 2. 发布信号事件（供 AI 观测）
        for _sym, signal in signals.items():
            trace_id = f"qtr_{uuid.uuid4().hex[:12]}_{int(time.time())}"
            publish_quant_signal(
                user_id=self.user_id,
                symbol=signal.symbol,
                signal_data={
                    "desired_side": signal.desired_side,
                    "desired_side_num": signal.desired_side_num,
                    "target_notional_usdt": signal.target_notional_usdt,
                    "target_leverage": signal.target_leverage,
                    "action_plan": signal.action_plan,
                    "report_ok": signal.report_ok,
                    "report_reason": signal.report_reason,
                    "pnl": signal.pnl_snapshot,
                    "trace_id": trace_id,
                },
                trace_id=trace_id
            )

        # 3. 执行交易
        if not self.executor:
            logger.warning("[QuantTradingRunner] 无执行器，跳过执行")
            return

        for sym, signal in signals.items():
            try:
                await self._execute_signal(signal)
            except Exception as e:
                logger.error(f"[QuantTradingRunner] 执行 {sym} 信号失败: {e}")

        # 4. 记录当前信号供下一周期 PF 评估
        for sym, signal in signals.items():
            try:
                price_data = await self.market_provider.get_price(sym)
                entry_price = price_data.price if price_data else 0.0
            except Exception:
                entry_price = 0.0
            self._pending_signals.append({
                "symbol": sym,
                "desired_side": signal.desired_side,
                "entry_price": entry_price,
                "timestamp": time.time()
            })

    async def _evaluate_pending_signals(self):
        """评估上一个周期的信号，用实际结果更新 PF"""
        if not self._pending_signals:
            return

        pending = self._pending_signals.popleft()
        try:
            price_data = await self.market_provider.get_price(pending["symbol"])
            if not price_data:
                return

            current_price = price_data.price
            entry_price = pending.get("entry_price", current_price)

            if entry_price == 0:
                return

            price_change_pct = (current_price - entry_price) / entry_price
            desired_side = pending["desired_side"]

            was_correct = False
            if desired_side == "long" and price_change_pct > 0.005 or desired_side == "short" and price_change_pct < -0.005 or desired_side == "flat" and abs(price_change_pct) < 0.005:
                was_correct = True

            self._update_signal_pf(was_correct)
            logger.info(
                f"[QuantTradingRunner] PF 信号评估: {pending['symbol']} "
                f"side={desired_side} change={price_change_pct:+.2%} correct={was_correct}"
            )
        except Exception as e:
            logger.debug(f"[QuantTradingRunner] 评估信号失败: {e}")

    def _update_signal_pf(self, was_correct: bool):
        """用信号执行结果更新粒子滤波"""
        def transition(x):
            # 准确率缓慢漂移，加小噪声
            return np.clip(x + np.random.randn(*x.shape) * 0.03, 0.01, 0.99)

        self.signal_confidence_pf.predict(transition)

        def likelihood(particle, obs):
            acc = np.clip(particle[0], 0.01, 0.99)
            return float(acc if obs[0] > 0.5 else (1 - acc))

        obs = np.array([1.0 if was_correct else 0.0])
        self.signal_confidence_pf.update(obs, likelihood)
        self.signal_confidence_pf.resample()

    def _get_signal_confidence(self) -> float:
        """获取当前信号置信度估计"""
        try:
            mean, cov = self.signal_confidence_pf.estimate()
            return float(np.clip(mean[0, 0], 0.0, 1.0))
        except Exception:
            return 0.5

    async def _execute_signal(self, signal: QuantSignal):
        """根据信号执行交易"""
        if not signal.report_ok:
            logger.warning(f"[QuantTradingRunner] {signal.symbol} 信号报告异常: {signal.report_reason}")
            return

        # 【治理】生成链路追踪ID
        trace_id = f"qtr_{uuid.uuid4().hex[:12]}_{int(time.time())}"

        # 获取当前持仓
        current_pos = await self.executor.get_position(signal.symbol)
        current_side = None
        if current_pos:
            current_side = str(current_pos.side.value).lower()  # "long" or "short"

        # 目标方向
        desired_side = signal.desired_side  # "long", "short", "flat"

        logger.info(
            f"[QuantTradingRunner] [{trace_id}] {signal.symbol}: "
            f"current={current_side} desired={desired_side} "
            f"notional={signal.target_notional_usdt} leverage={signal.target_leverage}"
        )

        # 方向已对齐，无需操作
        if desired_side == "flat":
            if current_pos and current_pos.quantity > 0:
                logger.info(f"[QuantTradingRunner] [{trace_id}] {signal.symbol} 平仓")
                await self.executor.close_position(signal.symbol)
                publish_position_update(
                    symbol=signal.symbol,
                    position_data={"action": "close", "reason": "quant_signal_flat"},
                    trace_id=trace_id
                )
            return

        if current_side == desired_side and current_pos and current_pos.quantity > 0:
            logger.info(f"[QuantTradingRunner] [{trace_id}] {signal.symbol} 方向已对齐，hold")
            return

        # 方向不一致，需要调整
        # 先平仓（如果有反向持仓）
        if current_pos and current_pos.quantity > 0 and current_side != desired_side:
            logger.info(f"[QuantTradingRunner] [{trace_id}] {signal.symbol} 先平反向仓")
            await self.executor.close_position(signal.symbol)

        # 开新仓
        if desired_side == "long":
            order_side = OrderSide.BUY
        elif desired_side == "short":
            order_side = OrderSide.SELL
        else:
            return

        # 计算数量（简单按名义金额/当前价格估算）
        quantity = signal.target_notional_usdt / 50000.0  # 用 50k 作为价格估算
        quantity = max(quantity, 0.001)  # 最小数量

        try:
            order = await self.executor.execute_order(
                symbol=signal.symbol,
                side=order_side,
                quantity=quantity,
                leverage=int(signal.target_leverage) if signal.target_leverage.isdigit() else 1,
                trace_id=trace_id,
            )
            logger.info(f"[QuantTradingRunner] [{trace_id}] {signal.symbol} 下单成功: {order.id if order else 'N/A'}")
            publish_position_update(
                symbol=signal.symbol,
                position_data={
                    "action": "open",
                    "direction": desired_side,
                    "size": quantity,
                    "leverage": signal.target_leverage,
                    "reason": "quant_signal",
                },
                trace_id=trace_id
            )
        except Exception as e:
            logger.error(f"[QuantTradingRunner] [{trace_id}] {signal.symbol} 下单失败: {e}")
            publish_risk_warning(
                level="high",
                message=f"量化下单失败: {e}",
                data={"symbol": signal.symbol, "side": desired_side},
                trace_id=trace_id
            )
