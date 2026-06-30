#!/usr/bin/env python3
"""
交易模式管理API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持三种模式：全自动量化 / AI辅助交易 / 手动交易

端点:
- GET    /api/trading/mode/status          获取当前模式状态
- POST   /api/trading/mode/switch          切换交易模式

全自动量化模式:
- POST   /api/trading/mode/auto/start      启动全自动量化
- POST   /api/trading/mode/auto/stop       停止全自动量化
- GET    /api/trading/mode/auto/status     获取全自动量化状态

AI辅助交易模式:
- POST   /api/trading/mode/ai/start        启动AI指挥官
- POST   /api/trading/mode/ai/stop         停止AI指挥官
- POST   /api/trading/mode/ai/pause        暂停AI指挥官
- POST   /api/trading/mode/ai/resume       恢复AI指挥官
- POST   /api/trading/mode/ai/intervene    人工干预AI指挥官
- GET    /api/trading/mode/ai/status       获取AI指挥官状态

手动交易模式:
- POST   /api/trading/mode/manual/order    手动下单
- GET    /api/trading/mode/manual/positions 获取持仓
"""

import asyncio
import contextlib
import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.diagnostic import safe_create_task
from core.logger import logger

try:
    from core.btc_integration.quant_trading_runner import QuantTradingRunner
    QUANT_RUNNER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[TradingModeAPI] QuantTradingRunner 不可用: {e}")
    QUANT_RUNNER_AVAILABLE = False


# 认证依赖（从 exchange_config_api 导入，避免重复代码）
try:
    from api.exchange_config_api import get_user_id
except ImportError:
    from fastapi import Depends
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    security = HTTPBearer(auto_error=False)

    async def get_user_id(
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> str:
        """获取当前用户ID，认证失败返回 'anonymous'"""
        return "anonymous"

# ═══════════════════════════════════════════════════════════════
# TradeExecutor 导入（手动交易实盘支持）
# 目的：手动交易直接调用交易所API，而非模拟
# ═══════════════════════════════════════════════════════════════
try:
    from core.btc_integration.trade_executor import (
        OrderSide,
        OrderType,
        TradeExecutor,
        create_default_executor,
        create_executor,
    )
    TRADE_EXECUTOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[TradingModeAPI] TradeExecutor 不可用: {e}")
    TRADE_EXECUTOR_AVAILABLE = False

# 用户执行器缓存（手动交易使用）
# key: user_id, value: TradeExecutor实例
_manual_executors: dict[str, TradeExecutor] = {}

def _get_manual_executor(user_id: str) -> TradeExecutor:
    """
    获取用户的手动交易执行器

    为什么：每个用户需要独立的执行器实例，根据用户配置选择模拟/实盘
    目的：无配置时自动使用模拟执行器，有配置时使用用户指定的交易所
    """
    if user_id in _manual_executors:
        return _manual_executors[user_id]

    # 尝试获取用户配置
    exchange_config = None
    try:
        from core.btc_integration.exchange_config import ExchangeType, get_exchange_config_manager
        manager = get_exchange_config_manager()
        active_config = manager.get_active_config(user_id, ExchangeType.OKX)
        if active_config:
            exchange_config = {
                'id': str(active_config.id),
                'exchange': active_config.exchange.value if hasattr(active_config.exchange, 'value') else str(active_config.exchange),
                'mode': active_config.mode.value if hasattr(active_config.mode, 'value') else str(active_config.mode),
                'api_key': active_config.api_key,
                'api_secret': active_config.api_secret,
                'passphrase': active_config.passphrase,
                'testnet': active_config.testnet
            }
    except Exception as e:
        logger.warning(f"[TradingModeAPI] 获取用户 {user_id} 配置失败: {e}")

    # 创建执行器
    if exchange_config:
        executor = create_executor(user_id, exchange_config)
        logger.info(f"[TradingModeAPI] 用户 {user_id} 手动交易使用 {'实盘' if not executor.is_simulation else '模拟'} 模式")
    else:
        executor = create_default_executor(user_id)
        logger.info(f"[TradingModeAPI] 用户 {user_id} 无配置，使用默认模拟执行器")

    _manual_executors[user_id] = executor
    return executor

# 创建路由
router = APIRouter(prefix="/trading/mode", tags=["trading_mode"])


# ═══════════════════════════════════════════════════════════════
# 枚举和模型定义
# ═══════════════════════════════════════════════════════════════

class TradingMode(str, Enum):
    """交易模式枚举"""
    AUTO = "auto"      # 全自动量化
    AI = "ai"          # AI辅助交易
    MANUAL = "manual"  # 手动交易


class RiskProfile(str, Enum):
    """风险偏好枚举"""
    CONSERVATIVE = "conservative"  # 保守
    MODERATE = "moderate"          # 稳健
    AGGRESSIVE = "aggressive"      # 激进


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class ModeSwitchRequest(BaseModel):
    """模式切换请求"""
    mode: TradingMode = Field(..., description="目标模式")
    config: dict[str, Any] | None = Field(default=None, description="模式配置")


class AutoTradingConfigRequest(BaseModel):
    """全自动量化配置请求"""
    symbols: list[str] = Field(default=["BTC", "ETH"], description="交易币种")
    strategy: str = Field(default="stage46_aggressive", description="策略名称")
    demo_mode: bool = Field(default=True, description="是否为模拟模式")
    leverage: int = Field(default=3, description="杠杆倍数")
    risk_profile: RiskProfile = Field(default=RiskProfile.MODERATE, description="风险偏好")


class AITradingConfigRequest(BaseModel):
    """AI辅助交易配置请求"""
    symbols: list[str] = Field(default=["BTC", "ETH"], description="交易币种")
    ai_check_interval: int = Field(default=4, description="AI检查间隔（周期数）")
    risk_profile: RiskProfile = Field(default=RiskProfile.MODERATE, description="风险偏好")
    auto_execute: bool = Field(default=False, description="是否自动执行AI决策")


class ManualOrderRequest(BaseModel):
    """手动下单请求"""
    symbol: str = Field(..., description="交易对，如 BTC-USDT-SWAP")
    side: str = Field(..., description="买卖方向: buy/sell")
    order_type: str = Field(default="market", description="订单类型: market/limit")
    amount: float = Field(..., description="数量")
    price: float | None = Field(default=None, description="价格（限价单必填）")
    leverage: int = Field(default=1, description="杠杆倍数")


class AIInterveneRequest(BaseModel):
    """AI干预请求"""
    action: str = Field(..., description="干预动作: pause/resume/close_all")
    reason: str = Field(..., description="干预原因")


class ConfirmDecisionRequest(BaseModel):
    """确认AI决策请求"""
    pending_id: str = Field(..., description="待确认决策ID")


class RejectDecisionRequest(BaseModel):
    """拒绝AI决策请求"""
    pending_id: str = Field(..., description="待确认决策ID")


class PendingDecisionItem(BaseModel):
    """待确认决策项"""
    pending_id: str
    symbol: str
    action: str
    direction: str | None = None
    size: float | None = None
    leverage: int | None = None
    reasoning: str = ""
    confidence: float = 0.0
    timestamp: float = 0.0


class PendingDecisionResponse(BaseModel):
    """待确认决策列表响应"""
    success: bool = Field(default=True)
    count: int = Field(default=0)
    decisions: list[PendingDecisionItem] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 响应模型
# ═══════════════════════════════════════════════════════════════

class ModeStatusResponse(BaseModel):
    """模式状态响应"""
    success: bool = Field(default=True)
    mode: TradingMode = Field(..., description="当前模式")
    is_active: bool = Field(..., description="是否活跃")
    status_message: str = Field(default="", description="状态消息")

    # 全自动量化模式状态
    auto_pid: int | None = Field(default=None, description="全自动量化进程ID")
    auto_runtime: float | None = Field(default=None, description="运行时间（秒）")
    auto_strategy: str | None = Field(default=None, description="当前策略")

    # AI辅助模式状态
    ai_decision_count: int | None = Field(default=None, description="AI决策次数")
    ai_last_decision_time: float | None = Field(default=None, description="最后决策时间")
    ai_confidence: float | None = Field(default=None, description="当前置信度")

    # 手动模式状态
    manual_position_count: int | None = Field(default=None, description="持仓数量")

    # 交易环境状态
    is_simulation: bool | None = Field(default=None, description="是否为模拟盘")


class AutoTradingStatusResponse(BaseModel):
    """全自动量化状态响应"""
    success: bool = Field(default=True)
    is_running: bool = Field(..., description="是否运行中")
    pid: int | None = Field(default=None, description="进程ID")
    runtime: float | None = Field(default=None, description="运行时间（秒）")
    state: dict[str, Any] = Field(default_factory=dict, description="状态数据")
    report: dict[str, Any] = Field(default_factory=dict, description="报告数据")
    # 盈亏数据（从报告解析）
    pnl: float | None = Field(default=None, description="累计盈亏（USDT）")
    pnl_percent: float | None = Field(default=None, description="盈亏百分比（%）")


class AITradingStatusResponse(BaseModel):
    """AI辅助交易状态响应"""
    success: bool = Field(default=True)
    is_running: bool = Field(..., description="是否运行中")
    mode: str = Field(default="idle", description="当前模式: idle/ai/paused/error")
    symbols: list[str] = Field(default_factory=list, description="交易币种")
    decision_count: int = Field(default=0, description="决策次数")
    last_decision_time: float | None = Field(default=None, description="最后决策时间")
    error_message: str | None = Field(default=None, description="错误信息")


class OrderResponse(BaseModel):
    """下单响应"""
    success: bool = Field(...)
    order_id: str | None = Field(default=None, description="订单ID")
    status: str | None = Field(default=None, description="订单状态")
    message: str | None = Field(default=None, description="消息")


class TradingPredictionRequest(BaseModel):
    """交易预测请求"""
    symbol: str = Field(default="BTC", description="交易币种")
    action: str = Field(default="buy", description="预测动作: buy/sell/hold")


class TradingPredictionResponse(BaseModel):
    """交易预测响应"""
    success: bool = Field(default=True)
    success_probability: float = Field(default=0.5, description="成功概率 0-1")
    expected_pnl: float = Field(default=0.0, description="预期收益")
    risk_score: float = Field(default=0.5, description="风险评分 0-1")
    recommended_action: str = Field(default="hold", description="建议行动")
    reasoning: str = Field(default="", description="推理说明")
    available: bool = Field(default=True, description="预测是否可用")


# ═══════════════════════════════════════════════════════════════
# 认证依赖（延迟导入避免循环导入）
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 进程管理器（用于全自动量化模式）
# ═══════════════════════════════════════════════════════════════

class AutoTradingProcessManager:
    """全自动量化运行管理器 - 用户隔离"""

    def __init__(self):
        # user_id -> QuantTradingRunner
        self._runners: dict[str, QuantTradingRunner] = {}
        # user_id -> start_time
        self._start_times: dict[str, float] = {}
        # user_id -> config (用于重建状态)
        self._configs: dict[str, AutoTradingConfigRequest] = {}

    async def start(self, user_id: str, config: AutoTradingConfigRequest) -> dict[str, Any]:
        """启动全自动量化（QuantTradingRunner模式）"""
        if not QUANT_RUNNER_AVAILABLE:
            return {
                "success": False,
                "error": "QuantTradingRunner 不可用"
            }

        # 检查是否已有运行中的 runner
        if user_id in self._runners:
            runner = self._runners[user_id]
            if runner.state.is_running:
                return {
                    "success": False,
                    "error": "全自动量化已在运行",
                }

        # 获取用户交易所配置
        exchange_config = None
        try:
            from api.exchange_config_api import get_exchange_config_manager
            from core.btc_integration.exchange_config import ExchangeType
            manager = get_exchange_config_manager()
            active_cfg = manager.get_active_config(user_id, ExchangeType.OKX)
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
        except Exception as e:
            logger.warning(f"[AutoTradingProcessManager] 获取用户 {user_id} 配置失败: {e}")

        # 生成项目目录（兼容旧配置）
        project_root = Path(__file__).parent.parent

        try:
            runner = QuantTradingRunner(
                user_id=user_id,
                symbols=config.symbols,
                project_dir=str(project_root),
                exchange_config=exchange_config,
            )
            await runner.start()

            self._runners[user_id] = runner
            self._start_times[user_id] = time.time()
            self._configs[user_id] = config

            logger.info(f"[AutoTradingProcessManager] 用户 {user_id} 启动全自动量化（QuantTradingRunner）")

            return {
                "success": True,
                "status": "running"
            }

        except Exception as e:
            logger.error(f"[AutoTradingProcessManager] 启动失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def stop(self, user_id: str) -> dict[str, Any]:
        """停止全自动量化"""
        if user_id not in self._runners:
            return {
                "success": False,
                "error": "没有运行中的全自动量化"
            }

        runner = self._runners[user_id]

        if not runner.state.is_running:
            del self._runners[user_id]
            if user_id in self._start_times:
                del self._start_times[user_id]
            return {
                "success": True,
                "status": "already_stopped"
            }

        try:
            await runner.stop()
            del self._runners[user_id]
            if user_id in self._start_times:
                del self._start_times[user_id]

            logger.info(f"[AutoTradingProcessManager] 用户 {user_id} 停止全自动量化")

            return {
                "success": True,
                "status": "stopped"
            }

        except Exception as e:
            logger.error(f"[AutoTradingProcessManager] 停止失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_status(self, user_id: str) -> dict[str, Any]:
        """获取全自动量化状态"""
        user_runtime_dir = Path(f"core/btc_integration/engine/.runtime/{user_id}")
        state_file = user_runtime_dir / "state.json"
        report_file = user_runtime_dir / "report_latest.txt"

        # 检查 runner 状态
        is_running = False
        runtime = None

        if user_id in self._runners:
            runner = self._runners[user_id]
            is_running = runner.state.is_running
            if is_running and user_id in self._start_times:
                runtime = time.time() - self._start_times[user_id]

        # 读取状态文件（兼容旧模式）
        state = {}
        if state_file.exists():
            try:
                with open(state_file, encoding='utf-8') as f:
                    state = json.load(f)
            except Exception as e:
                logger.warning(f"[AutoTradingProcessManager] 读取状态文件失败: {e}")

        # 从 QuantTradingRunner 内存状态补充实时数据
        latest_signal = None
        if user_id in self._runners:
            runner = self._runners[user_id]
            state["cycle_count"] = runner.state.cycle_count
            state["last_signal_time"] = runner.state.last_signal_time
            state["last_error"] = runner.state.last_error

            # 尝试读取 shadow_exec 报告（shadow_exec 的 project_dir 是 engine 目录）
            project_dir = getattr(runner, 'project_dir', None)
            if project_dir:
                engine_dir = Path(project_dir) / "core" / "btc_integration" / "engine"
                shadow_report_path = engine_dir / ".runtime" / "okx_demo_shadow_exec_latest.json"
                if shadow_report_path.exists():
                    try:
                        with open(shadow_report_path, encoding='utf-8') as f:
                            shadow_report = json.load(f)
                    except Exception as e:
                        logger.warning(f"[AutoTradingProcessManager] 读取shadow报告失败: {e}")
                        shadow_report = None
                else:
                    shadow_report = None
            else:
                shadow_report = None
        else:
            shadow_report = None

        # 读取报告文件（简化处理）
        report = {}
        pnl = None
        pnl_percent = None

        # 优先使用 shadow_exec 报告
        if shadow_report:
            report["shadow_exec"] = shadow_report
            # 提取最新信号
            plan = shadow_report.get("plan", {})
            signals = plan.get("signals", []) if isinstance(plan, dict) else []
            if signals:
                latest_signal = signals[0]
            # 提取盈亏
            account = shadow_report.get("account", {})
            if isinstance(account, dict):
                pnl = account.get("pnl")
                pnl_percent = account.get("pnl_percent")

        # 兜底：旧报告文件
        if not report and report_file.exists():
            try:
                with open(report_file, encoding='utf-8') as f:
                    content = f.read()
                    report = {"content_preview": content[:500] if len(content) > 500 else content}

                    # 解析盈亏数据
                    try:
                        if "策略当前总收益:" in content:
                            pnl_line = content.split("策略当前总收益:")[1].split("\n")[0].strip()
                            pnl_str = pnl_line.replace("U", "").replace(",", "").strip()
                            pnl = float(pnl_str)

                        # 尝试解析盈亏百分比（如果有）
                        if "收益率:" in content:
                            pnl_percent_line = content.split("收益率:")[1].split("\n")[0].strip()
                            pnl_percent_str = pnl_percent_line.replace("%", "").replace(",", "").strip()
                            pnl_percent = float(pnl_percent_str)
                    except Exception as parse_err:
                        logger.warning(f"[AutoTradingProcessManager] 解析盈亏数据失败: {parse_err}")

            except Exception as e:
                logger.warning(f"[AutoTradingProcessManager] 读取报告文件失败: {e}")

        return {
            "is_running": is_running,
            "pid": os.getpid(),
            "runtime": runtime,
            "state": state,
            "report": report,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "latest_signal": latest_signal
        }

    def _generate_shadow_config(self, config: AutoTradingConfigRequest) -> dict[str, Any]:
        """生成shadow.yml配置"""
        return {
            "exchange": "okx",
            "mode": "shadow" if config.demo_mode else "live",
            "symbols": config.symbols,
            "strategy": config.strategy,
            "leverage": config.leverage,
            "risk_profile": config.risk_profile.value,
        }


# 全局进程管理器实例
auto_trading_manager = AutoTradingProcessManager()


# ═══════════════════════════════════════════════════════════════
# API端点
# ═══════════════════════════════════════════════════════════════

@router.get("/status", response_model=ModeStatusResponse)
async def get_mode_status(user_id: str = Depends(get_user_id)):
    """
    获取当前交易模式状态

    返回用户当前选择的交易模式及各模式的运行状态
    """
    # 获取全自动量化状态
    auto_status = auto_trading_manager.get_status(user_id)

    # 获取AI交易状态
    ai_status = None
    try:
        from core.btc_integration.ai_trading_manager import get_ai_trading_status
        ai_status = get_ai_trading_status(user_id)
    except ImportError:
        pass

    # 确定当前模式
    current_mode = TradingMode.MANUAL
    if auto_status.get("is_running"):
        current_mode = TradingMode.AUTO
    elif ai_status and ai_status.is_running:
        current_mode = TradingMode.AI

    # 判断是否为模拟盘（检查 OKX 和 Binance）
    is_simulation = True
    try:
        from core.btc_integration.exchange_config import ExchangeType, get_exchange_config_manager
        manager = get_exchange_config_manager()
        # 尝试获取 OKX 或 Binance 的活跃配置
        active_config = manager.get_active_config(user_id, ExchangeType.OKX)
        if not active_config:
            active_config = manager.get_active_config(user_id, ExchangeType.BINANCE)
        if active_config:
            mode_str = active_config.mode.value if hasattr(active_config.mode, 'value') else str(active_config.mode)
            is_simulation = mode_str == 'demo'
        else:
            is_simulation = True
    except Exception:
        is_simulation = True

    return ModeStatusResponse(
        success=True,
        mode=current_mode,
        is_active=auto_status.get("is_running") or (ai_status and ai_status.is_running),
        status_message="运行正常",
        auto_pid=auto_status.get("pid"),
        auto_runtime=auto_status.get("runtime"),
        auto_strategy=auto_status.get("state", {}).get("strategy"),
        ai_decision_count=ai_status.decision_count if ai_status else 0,
        ai_last_decision_time=ai_status.last_decision_time if ai_status else None,
        is_simulation=is_simulation,
    )


@router.post("/switch", response_model=ModeStatusResponse)
async def switch_mode(
    request: ModeSwitchRequest,
    user_id: str = Depends(get_user_id)
):
    """
    切换交易模式

    - auto: 启动全自动量化
    - ai: 启动AI指挥官
    - manual: 切换到手动交易模式（停止其他模式）
    """
    # 先停止当前运行的模式
    auto_status = auto_trading_manager.get_status(user_id)
    if auto_status.get("is_running"):
        await auto_trading_manager.stop(user_id)

    try:
        from core.btc_integration.ai_trading_manager import stop_ai_trading
        await stop_ai_trading(user_id)
    except ImportError:
        pass

    # 启动新模式
    if request.mode == TradingMode.AUTO:
        # 全自动量化需要额外配置
        return ModeStatusResponse(
            success=True,
            mode=TradingMode.AUTO,
            is_active=False,
            status_message="请使用 /auto/start 端点启动全自动量化"
        )

    elif request.mode == TradingMode.AI:
        # AI辅助交易需要额外配置
        return ModeStatusResponse(
            success=True,
            mode=TradingMode.AI,
            is_active=False,
            status_message="请使用 /ai/start 端点启动AI辅助交易"
        )

    else:  # MANUAL
        return ModeStatusResponse(
            success=True,
            mode=TradingMode.MANUAL,
            is_active=False,
            status_message="已切换到手动交易模式"
        )


# ═══════════════════════════════════════════════════════════════
# 全自动量化模式API
# ═══════════════════════════════════════════════════════════════

@router.post("/auto/start", response_model=AutoTradingStatusResponse)
async def start_auto_trading(
    request: AutoTradingConfigRequest,
    user_id: str = Depends(get_user_id)
):
    """
    启动全自动量化

    通过subprocess启动okx_demo_autopilot独立进程
    """
    result = await auto_trading_manager.start(user_id, request)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return AutoTradingStatusResponse(
        success=True,
        is_running=True,
        pid=result.get("pid"),
        status_message="全自动量化已启动"
    )


@router.post("/auto/stop", response_model=AutoTradingStatusResponse)
async def stop_auto_trading(user_id: str = Depends(get_user_id)):
    """
    停止全自动量化

    发送停止信号给独立进程
    """
    result = await auto_trading_manager.stop(user_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return AutoTradingStatusResponse(
        success=True,
        is_running=False,
        status_message="全自动量化已停止"
    )


@router.get("/auto/status", response_model=AutoTradingStatusResponse)
async def get_auto_trading_status(user_id: str = Depends(get_user_id)):
    """
    获取全自动量化状态

    读取.runtime/目录下的状态文件
    """
    status = auto_trading_manager.get_status(user_id)

    return AutoTradingStatusResponse(
        success=True,
        is_running=status.get("is_running", False),
        pid=status.get("pid"),
        runtime=status.get("runtime"),
        state=status.get("state", {}),
        report=status.get("report", {}),
        pnl=status.get("pnl"),
        pnl_percent=status.get("pnl_percent")
    )


# ═══════════════════════════════════════════════════════════════
# AI辅助模式API
# ═══════════════════════════════════════════════════════════════

@router.post("/ai/start", response_model=AITradingStatusResponse)
async def start_ai_trading(
    request: AITradingConfigRequest,
    user_id: str = Depends(get_user_id)
):
    """
    启动AI指挥官

    创建AITradingCommander实例，开始交易循环
    """
    try:
        from core.btc_integration.ai_trading_manager import start_ai_trading

        config_dict = {
            "symbols": request.symbols,
            "ai_check_interval": request.ai_check_interval,
            "risk_profile": request.risk_profile.value,
            "auto_execute": request.auto_execute
        }

        success = await start_ai_trading(user_id, config_dict)

        if not success:
            raise HTTPException(status_code=400, detail="AI指挥官启动失败")

        return AITradingStatusResponse(
            success=True,
            is_running=True,
            mode="ai",
            symbols=request.symbols
        )

    except ImportError as e:
        logger.error(f"[TradingModeAPI] AI交易模块不可用: {e}")
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from e


@router.post("/ai/stop", response_model=AITradingStatusResponse)
async def stop_ai_trading_api(user_id: str = Depends(get_user_id)):
    """
    停止AI指挥官
    """
    try:
        from core.btc_integration.ai_trading_manager import stop_ai_trading

        success = await stop_ai_trading(user_id)

        return AITradingStatusResponse(
            success=success,
            is_running=False,
            mode="stopped"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc


@router.post("/ai/pause", response_model=AITradingStatusResponse)
async def pause_ai_trading(user_id: str = Depends(get_user_id)):
    """
    暂停AI指挥官

    AI停止决策，但保持连接
    """
    try:
        from core.btc_integration.ai_trading_manager import pause_ai_trading

        success = await pause_ai_trading(user_id)

        return AITradingStatusResponse(
            success=success,
            is_running=success,
            mode="paused" if success else "error"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc


@router.post("/ai/resume", response_model=AITradingStatusResponse)
async def resume_ai_trading(user_id: str = Depends(get_user_id)):
    """
    恢复AI指挥官
    """
    try:
        from core.btc_integration.ai_trading_manager import resume_ai_trading

        success = await resume_ai_trading(user_id)

        return AITradingStatusResponse(
            success=success,
            is_running=success,
            mode="ai" if success else "error"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc


@router.post("/ai/intervene", response_model=AITradingStatusResponse)
async def ai_intervene(
    request: AIInterveneRequest,
    user_id: str = Depends(get_user_id)
):
    """
    人工干预AI指挥官

    action: pause（暂停AI）/ resume（恢复AI）/ close_all（平仓）
    """
    try:
        from core.btc_integration.ai_trading_manager import ai_trading_manager

        success = await ai_trading_manager.intervene(user_id, request.action, request.reason)

        return AITradingStatusResponse(
            success=success,
            status_message=f"干预{ '成功' if success else '失败' }: {request.action}"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc


@router.post("/ai/confirm", response_model=AITradingStatusResponse)
async def confirm_ai_decision(
    request: ConfirmDecisionRequest,
    user_id: str = Depends(get_user_id)
):
    """
    确认AI待执行决策

    用户在半自动模式下确认执行AI建议的交易
    """
    try:
        from core.btc_integration.ai_trading_manager import ai_trading_manager

        commander = ai_trading_manager.get_commander(user_id)
        if not commander:
            return AITradingStatusResponse(
                success=False,
                is_running=False,
                mode="idle",
                error_message="AI指挥官未启动"
            )

        # 遍历所有子代理，找到包含该 pending_id 的代理
        confirmed = False
        for _symbol, agent in commander.subagents.items():
            if hasattr(agent, 'confirm_decision') and agent.confirm_decision(request.pending_id):
                confirmed = True
                break

        if not confirmed:
            return AITradingStatusResponse(
                success=False,
                is_running=True,
                mode="ai",
                error_message=f"未找到待确认决策: {request.pending_id}"
            )

        return AITradingStatusResponse(
            success=True,
            is_running=True,
            mode="ai",
            status_message=f"决策已确认: {request.pending_id}"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc
    except Exception as e:
        logger.error(f"[TradingModeAPI] 确认决策失败: {e}")
        return AITradingStatusResponse(
            success=False,
            is_running=True,
            mode="ai",
            error_message=str(e)
        )


@router.post("/ai/reject", response_model=AITradingStatusResponse)
async def reject_ai_decision(
    request: RejectDecisionRequest,
    user_id: str = Depends(get_user_id)
):
    """
    拒绝AI待执行决策

    用户在半自动模式下拒绝执行AI建议的交易
    """
    try:
        from core.btc_integration.ai_trading_manager import ai_trading_manager

        commander = ai_trading_manager.get_commander(user_id)
        if not commander:
            return AITradingStatusResponse(
                success=False,
                is_running=False,
                mode="idle",
                error_message="AI指挥官未启动"
            )

        rejected = False
        for _symbol, agent in commander.subagents.items():
            if hasattr(agent, 'reject_decision') and agent.reject_decision(request.pending_id):
                rejected = True
                break

        if not rejected:
            return AITradingStatusResponse(
                success=False,
                is_running=True,
                mode="ai",
                error_message=f"未找到待确认决策: {request.pending_id}"
            )

        return AITradingStatusResponse(
            success=True,
            is_running=True,
            mode="ai",
            status_message=f"决策已拒绝: {request.pending_id}"
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc
    except Exception as e:
        logger.error(f"[TradingModeAPI] 拒绝决策失败: {e}")
        return AITradingStatusResponse(
            success=False,
            is_running=True,
            mode="ai",
            error_message=str(e)
        )


@router.get("/ai/pending", response_model=PendingDecisionResponse)
async def get_pending_decisions(user_id: str = Depends(get_user_id)):
    """
    获取AI待确认决策列表

    返回当前等待用户确认的所有AI交易建议
    """
    try:
        from core.btc_integration.ai_trading_manager import ai_trading_manager

        commander = ai_trading_manager.get_commander(user_id)
        if not commander:
            return PendingDecisionResponse(success=True, count=0, decisions=[])

        decisions: list[PendingDecisionItem] = []
        for symbol, agent in commander.subagents.items():
            if hasattr(agent, '_pending_decisions'):
                for pending_id, pending in agent._pending_decisions.items():
                    dec = pending.get("decision", {})
                    decisions.append(PendingDecisionItem(
                        pending_id=pending_id,
                        symbol=symbol,
                        action=dec.get("action", "unknown"),
                        direction=dec.get("direction"),
                        size=dec.get("size"),
                        leverage=dec.get("leverage"),
                        reasoning=dec.get("reasoning", ""),
                        confidence=dec.get("confidence", 0.0),
                        timestamp=pending.get("context", {}).get("timestamp", 0.0),
                    ))

        return PendingDecisionResponse(
            success=True,
            count=len(decisions),
            decisions=decisions
        )

    except ImportError:
        return PendingDecisionResponse(success=False, count=0, decisions=[])
    except Exception as e:
        logger.error(f"[TradingModeAPI] 获取待确认决策失败: {e}")
        return PendingDecisionResponse(success=False, count=0, decisions=[])


@router.get("/ai/status", response_model=AITradingStatusResponse)
async def get_ai_trading_status(user_id: str = Depends(get_user_id)):
    """
    获取AI指挥官状态
    """
    try:
        from core.btc_integration.ai_trading_manager import get_ai_trading_status

        status = get_ai_trading_status(user_id)

        if status is None:
            return AITradingStatusResponse(
                success=True,
                is_running=False,
                mode="idle",
                status_message="AI指挥官未启动"
            )

        return AITradingStatusResponse(
            success=True,
            is_running=status.is_running,
            mode=status.mode,
            symbols=status.symbols,
            decision_count=status.decision_count,
            last_decision_time=status.last_decision_time,
            error_message=status.error_message
        )

    except ImportError as _exc:
        raise HTTPException(status_code=503, detail="AI交易模块不可用") from _exc


# ═══════════════════════════════════════════════════════════════
# 手动模式API
# ═══════════════════════════════════════════════════════════════

@router.post("/manual/order", response_model=OrderResponse)
async def place_manual_order(
    request: ManualOrderRequest,
    user_id: str = Depends(get_user_id)
):
    """
    手动下单

    为什么：用户需要直接控制交易，而非通过AI或全自动
    目的：1. 根据用户配置选择模拟/实盘 2. 调用交易所API执行 3. 返回真实结果
    """
    if not TRADE_EXECUTOR_AVAILABLE:
        raise HTTPException(status_code=503, detail="交易执行器不可用")

    try:
        # ═══════════════════════════════════════════════════════════════
        # 获取用户执行器（根据配置自动选择模拟/实盘）
        # ═══════════════════════════════════════════════════════════════
        executor = _get_manual_executor(user_id)

        # 转换参数
        order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
        order_type = OrderType.LIMIT if request.order_type.lower() == "limit" else OrderType.MARKET

        # ═══════════════════════════════════════════════════════════════
        # 执行交易（真实调用交易所API或模拟执行）
        # ═══════════════════════════════════════════════════════════════
        order = await executor.execute_order(
            symbol=request.symbol,
            side=order_side,
            quantity=request.amount,
            order_type=order_type,
            price=request.price,
            leverage=request.leverage
        )

        logger.info(
            f"[TradingModeAPI] [user={user_id}] 手动下单成功: "
            f"{request.symbol} {request.side} {request.amount}, "
            f"模式={'模拟' if executor.is_simulation else '实盘'}"
        )

        return OrderResponse(
            success=True,
            order_id=order.id,
            status=order.status,
            message=f"订单已提交（{'模拟' if executor.is_simulation else '实盘'}）"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TradingModeAPI] [user={user_id}] 手动下单失败: {e}")
        return OrderResponse(
            success=False,
            message=f"下单失败: {str(e)}"
        )


@router.get("/manual/positions")
async def get_manual_positions(
    symbol: str | None = None,
    user_id: str = Depends(get_user_id)
):
    """
    获取手动交易持仓

    为什么：用户需要实时了解持仓状态
    目的：1. 获取真实持仓 2. 计算盈亏 3. 支持决策
    """
    if not TRADE_EXECUTOR_AVAILABLE:
        raise HTTPException(status_code=503, detail="交易执行器不可用")

    try:
        executor = _get_manual_executor(user_id)

        # 如果指定了币种，获取该币种持仓
        if symbol:
            position = await executor.get_position(symbol)
            if position:
                return {
                    "success": True,
                    "positions": [{
                        "symbol": position.symbol,
                        "side": position.side.value,
                        "quantity": position.quantity,
                        "entry_price": position.entry_price,
                        "mark_price": position.mark_price,
                        "unrealized_pnl": position.unrealized_pnl,
                        "leverage": position.leverage
                    }]
                }
            else:
                return {"success": True, "positions": []}

        # 否则获取账户信息（简化版本）
        account = await executor.get_account()
        return {
            "success": True,
            "total_equity": account.total_equity,
            "available_balance": account.available_balance,
            "unrealized_pnl": account.unrealized_pnl,
            "mode": "模拟" if executor.is_simulation else "实盘"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TradingModeAPI] [user={user_id}] 获取持仓失败: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# World Model 预测API
# ═══════════════════════════════════════════════════════════════

@router.get("/prediction", response_model=TradingPredictionResponse)
async def get_trading_prediction(
    symbol: str = "BTC",
    action: str = "buy",
    user_id: str = Depends(get_user_id)
):
    """
    获取交易预测（World Model）

    为什么：用户需要了解AI对当前市场的判断
    目的：1. 预测成功率 2. 预期收益 3. 风险评估
    """
    try:
        # 尝试导入并获取AI指挥官的预测能力
        from core.btc_integration.intelligence_integration import TradingIntelligenceIntegration

        # 初始化智能集成
        intelligence = TradingIntelligenceIntegration()

        # 构建简化市场上下文和交易决策（避免完整 dataclass 必填字段）
        from types import SimpleNamespace
        market_context = SimpleNamespace(symbol=symbol)

        strategy_params = SimpleNamespace(to_dict=lambda: {"confidence": 0.7})
        decision = SimpleNamespace(action=action, strategy_params=strategy_params)

        # 获取预测
        prediction = await intelligence.predict_trade_outcome(decision, market_context)

        if prediction:
            return TradingPredictionResponse(
                success=True,
                success_probability=prediction.success_probability,
                expected_pnl=prediction.expected_pnl,
                risk_score=prediction.risk_score,
                recommended_action=prediction.recommended_action,
                reasoning=prediction.reasoning,
                available=True
            )
        else:
            # World Model 不可用，返回默认预测
            return TradingPredictionResponse(
                success=True,
                success_probability=0.5,
                expected_pnl=0.0,
                risk_score=0.5,
                recommended_action="hold",
                reasoning="World Model 暂时不可用，建议观望",
                available=False
            )

    except ImportError as e:
        logger.warning(f"[TradingModeAPI] 智能集成模块不可用: {e}")
        return TradingPredictionResponse(
            success=True,
            success_probability=0.5,
            expected_pnl=0.0,
            risk_score=0.5,
            recommended_action="hold",
            reasoning="预测模块加载失败",
            available=False
        )
    except Exception as e:
        logger.error(f"[TradingModeAPI] 获取预测失败: {e}")
        return TradingPredictionResponse(
            success=False,
            success_probability=0.5,
            expected_pnl=0.0,
            risk_score=0.5,
            recommended_action="hold",
            reasoning=f"预测失败: {str(e)}",
            available=False
        )


# ═══════════════════════════════════════════════════════════════
# WebSocket端点（用于实时推送）
# ═══════════════════════════════════════════════════════════════

@router.websocket("/ws/{mode}")
async def trading_mode_websocket(websocket: WebSocket, mode: str):
    """
    WebSocket连接（用于实时推送交易数据）

    mode: ai / auto / manual

    【治理】增加了心跳机制（ping/pong），网络闪断后60秒内可检测并清理资源。
    """
    await websocket.accept()

    # 获取用户ID
    user_id = "anonymous"  # TODO: 实际应该从token中解析

    last_pong = time.time()
    connection_alive = True

    async def heartbeat():
        """心跳协程：每30秒发送ping，60秒未收到pong则关闭连接"""
        nonlocal connection_alive
        while connection_alive:
            await asyncio.sleep(30)
            if time.time() - last_pong > 60:
                logger.warning(f"[TradingModeAPI] WebSocket心跳超时: user={user_id}, mode={mode}")
                connection_alive = False
                try:
                    await websocket.close()
                except Exception as e:
                    logger.warning(f"[TradingModeAPI] WebSocket关闭失败: {e}", exc_info=True)
                return
            try:
                await websocket.send_json({"type": "ping", "timestamp": int(time.time() * 1000)})
            except Exception as e:
                logger.warning(f"[TradingModeAPI] WebSocket发送ping失败: {e}", exc_info=True)
                connection_alive = False
                return

    heartbeat_task = safe_create_task(heartbeat(), name="heartbeat")

    try:
        if mode == "ai":
            # 注册WebSocket到AI交易管理器
            try:
                from core.btc_integration.ai_trading_manager import ai_trading_manager
                await ai_trading_manager.register_websocket(user_id, websocket)

                # 保持连接
                while connection_alive:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=65)
                    msg = json.loads(data)
                    if msg.get("type") == "pong":
                        last_pong = time.time()
                        continue
                    # 处理前端消息（如确认AI决策）

            except ImportError:
                await websocket.send_json({
                    "type": "error",
                    "message": "AI交易模块不可用"
                })

        elif mode == "auto":
            # 全自动量化模式：推送状态更新
            while connection_alive:
                status = auto_trading_manager.get_status(user_id)
                await websocket.send_json({
                    "type": "auto_status",
                    "data": status,
                    "timestamp": int(time.time() * 1000)
                })
                await asyncio.sleep(5)  # 每5秒更新一次

        elif mode == "manual":
            # 手动模式：推送价格更新
            while connection_alive:
                # 这里应该获取实时价格
                await websocket.send_json({
                    "type": "price_update",
                    "data": {},
                    "timestamp": int(time.time() * 1000)
                })
                await asyncio.sleep(1)  # 每秒更新

    except asyncio.TimeoutError:
        logger.warning(f"[TradingModeAPI] WebSocket接收超时: user={user_id}, mode={mode}")
    except WebSocketDisconnect:
        logger.info(f"[TradingModeAPI] 用户 {user_id} WebSocket断开, mode={mode}")
    except Exception as e:
        logger.error(f"[TradingModeAPI] WebSocket错误: {e}")
    finally:
        connection_alive = False
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        if mode == "ai":
            try:
                from core.btc_integration.ai_trading_manager import ai_trading_manager
                await ai_trading_manager.unregister_websocket(user_id)
            except ImportError:
                pass
