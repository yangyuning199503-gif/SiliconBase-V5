#!/usr/bin/env python3
"""
活着的交易系统 - Living Trading System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
整合已有代码，实现三层架构：
  感知层: BTCProcessManager (已有) + 数据获取
  阈值层: RiskMonitor (已有) - 扩展触发机制
  决策层: AutoTradingScheduler (已有) - 改造按需唤醒

使用：
    from core.btc_integration.living_system import LivingTradingSystem

    system = LivingTradingSystem()
    await system.start()  # 启动活着的AI
"""

import asyncio
import threading
from typing import Any

from core.diagnostic import safe_create_task
from core.logger import logger

from .auto_trading_scheduler import get_auto_trading_scheduler

# 导入已有组件
from .process_manager import ProcessStatus, get_btc_process_manager
from .resource_monitor import create_default_monitor
from .risk_monitor import RiskLevel, get_risk_monitor


class LivingTradingSystem:
    """
    活着的交易系统

    像机器人一样运行：
    - 身体(感知层): 24h轻量监控进程和状态
    - 反射(阈值层): RiskMonitor判断是否需要决策
    - 大脑(决策层): AutoTradingScheduler按需唤醒
    """

    def __init__(self):
        # 三层组件（已有代码）
        self.sensor = get_btc_process_manager()  # 感知层
        self.reflex = get_risk_monitor()          # 阈值层
        self.brain = get_auto_trading_scheduler() # 决策层

        # 辅助组件（已有代码）
        self.guardian = None
        self.resource_monitor = create_default_monitor()

        # 状态
        self._running = False
        self._status_lock = threading.Lock()

        # 配置
        self._check_interval = 10  # 感知层检查间隔（秒）
        self._risk_check_interval = 60  # 阈值层检查间隔（秒）

        self._log_prefix = "[LivingSystem]"

    def _log(self, level: str, message: str):
        """记录日志"""
        log_func = getattr(logger, level, logger.info)
        log_func(f"{self._log_prefix} {message}")

    # ═══════════════════════════════════════════════════════════════
    # 启动/停止
    # ═══════════════════════════════════════════════════════════════

    async def start(
        self,
        symbol: str = "BTC",
        budget: float = 1000.0,
        risk_tolerance: str = "medium",
        auto_mode: bool = True
    ):
        """
        启动活着的交易系统

        Args:
            symbol: 交易标的
            budget: 预算
            risk_tolerance: 风险偏好
            auto_mode: 是否自动模式（跳过人工确认）
        """
        if self._running:
            self._log("warning", "系统已在运行中")
            return

        print("=" * 70)
        print("🤖 启动活着的交易系统")
        print("=" * 70)
        print()

        self._running = True

        # 1. 启动感知层（身体）- 24h轻量运行
        print("[1/3] 启动感知层（身体）...")
        print("      组件: BTCProcessManager")
        print("      职责: 监控进程状态，轻量数据采集")
        print()

        # 启动资源监控
        self.resource_monitor.start_monitoring()
        print("      ✓ 资源监控已启动")

        # 2. 配置阈值层（反射）
        print("[2/3] 配置阈值层（反射）...")
        print("      组件: RiskMonitor")
        print("      职责: 判断是否需要唤醒大脑")
        print()

        # 注册风险事件回调 - 关键连接点！
        self.reflex.register_event_callback(self._on_risk_event)
        self.reflex.register_intervention_callback(self._on_intervention)

        # 启动风险监控循环
        self.reflex.start_monitoring(interval=self._risk_check_interval)
        print("      ✓ 风险监控已启动")
        print()

        # 3. 准备决策层（大脑）- 平时休眠
        print("[3/3] 准备决策层（大脑）...")
        print("      组件: AutoTradingScheduler")
        print("      状态: 休眠中，等待阈值触发")
        print()

        # 修改调度器配置为按需模式
        self._configure_brain_for_on_demand()

        print("=" * 70)
        print("✅ 系统已启动，像生命一样运行：")
        print("   • 身体(感知层): 24h轻量监控")
        print("   • 反射(阈值层): 持续评估风险")
        print("   • 大脑(决策层): 按需唤醒")
        print("=" * 70)
        print()

        # 启动主循环
        await self._main_loop()

    def stop(self):
        """停止系统"""
        print("\n" + "=" * 70)
        print("正在停止系统...")

        self._running = False

        # 停止各层
        self.reflex.stop_monitoring()
        self.resource_monitor.stop_monitoring()

        if self.brain.is_running():
            safe_create_task(self.brain.stop(), name="stop")

        print("✅ 系统已停止")
        print("=" * 70)

    # ═══════════════════════════════════════════════════════════════
    # 三层连接逻辑
    # ═══════════════════════════════════════════════════════════════

    def _on_risk_event(self, event):
        """
        阈值层触发的事件

        这是反射层的关键：决定是否唤醒大脑
        """
        # 只有高风险才唤醒大脑
        if event.level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            self._log("warning", f"🚨 高风险事件: {event.message}")

            # 唤醒大脑做决策
            safe_create_task(self._wake_up_brain(event), name="_wake_up_brain")
        else:
            # 低风险只记录，不唤醒
            self._log("info", f"📊 风险事件: {event.message}")

    def _on_intervention(self, event, action):
        """干预执行"""
        self._log("warning", f"⚡ 干预执行: {action} - {event.message}")

        if action == "HALT" and self.brain.is_running():
            # 熔断 - 停止大脑
            safe_create_task(self.brain.pause(), name="pause")

    async def _wake_up_brain(self, risk_event):
        """
        唤醒大脑做决策

        这是从阈值层到决策层的关键调用
        """
        self._log("info", "🧠 唤醒决策大脑...")

        try:
            # 如果大脑已经在运行，检查是否需要调整
            if self.brain.is_running():
                self._log("info", "大脑已在运行，评估当前状态...")
                # 可以在这里实现动态调整策略
                return

            # 启动大脑进行决策
            # 这里复用已有的调度器逻辑，但改为按需启动
            await self.brain.start_24h_trading(
                symbol="BTC",
                budget=1000.0,
                risk_tolerance="medium"
            )

        except Exception as e:
            self._log("error", f"唤醒大脑失败: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 主循环（轻量）
    # ═══════════════════════════════════════════════════════════════

    async def _main_loop(self):
        """主循环 - 轻量级，只协调三层"""
        self._log("info", "主循环启动")

        while self._running:
            try:
                # 1. 感知层：更新进程状态（轻量）
                process_state = self.sensor.get_state()

                # 2. 更新风险监控器的账户状态（供阈值层使用）
                self._update_risk_state(process_state)

                # 3. 检查大脑状态
                if self.brain.is_halted() and self.reflex.should_resume_trading(
                    self.brain._circuit_breaker_time.timestamp() if self.brain._circuit_breaker_time else None,
                    cooldown_minutes=30
                ):
                    self._log("info", "风险降低，恢复大脑运行")
                    await self.brain.resume()

                # 4. 等待下一次检查
                await asyncio.sleep(self._check_interval)

            except Exception as e:
                self._log("error", f"主循环异常: {e}")
                await asyncio.sleep(5)

        self._log("info", "主循环结束")

    def _update_risk_state(self, process_state):
        """更新风险监控器的状态"""
        # 将进程状态转换为风险监控器能理解的格式
        account_state = {
            "margin_ratio": 100.0,  # 这里应该从实际数据源获取
            "daily_pnl_pct": process_state.pnl_today,
        }

        self.reflex.update_account_state(account_state)

    # ═══════════════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════════════

    def _configure_brain_for_on_demand(self):
        """配置大脑为按需唤醒模式"""
        # 修改调度器的配置，使其更适合按需唤醒
        # 而不是定时触发

        # 设置更长的间隔，因为主要是由阈值层触发
        self.brain._config["interval_minutes"] = 3600  # 1小时（作为保底）
        self.brain._config["auto_confirm"] = True       # 自动确认
        self.brain._config["auto_renew"] = False        # 不由调度器自动续约，由阈值层控制

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> dict[str, Any]:
        """获取系统状态"""
        return {
            "running": self._running,
            "layers": {
                "sensor": {
                    "component": "BTCProcessManager",
                    "status": "running" if self.sensor.get_state().status == ProcessStatus.RUNNING else "idle"
                },
                "reflex": {
                    "component": "RiskMonitor",
                    "monitoring": self.reflex._monitoring
                },
                "brain": {
                    "component": "AutoTradingScheduler",
                    "status": self.brain.status.value
                }
            },
            "resource": self.resource_monitor.get_current_status()
        }


# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

_living_system: LivingTradingSystem | None = None


def get_living_system() -> LivingTradingSystem:
    """获取活着的交易系统单例"""
    global _living_system
    if _living_system is None:
        _living_system = LivingTradingSystem()
    return _living_system
