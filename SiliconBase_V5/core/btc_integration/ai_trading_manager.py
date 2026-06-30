#!/usr/bin/env python3
"""
AI交易管理器 (AITradingManager)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
管理所有用户的AI指挥官实例，支持用户隔离

特性:
- 用户级隔离：每个用户独立的AI指挥官
- 线程安全：使用asyncio.Lock保护共享资源
- WebSocket集成：实时推送AI决策到前端
- 资源管理：自动清理已停止的指挥官
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.diagnostic import safe_create_task

try:
    from fastapi import WebSocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    WebSocket = Any  # type: ignore

import contextlib

from core.logger import logger


@dataclass
class AICommanderState:
    """AI指挥官状态"""
    user_id: str
    is_running: bool = False
    start_time: float | None = None
    last_decision_time: float | None = None
    decision_count: int = 0
    symbols: list = field(default_factory=list)
    mode: str = "ai"  # ai, paused, stopped
    error_message: str | None = None


class AITradingManager:
    """
    AI交易管理器 - 单例模式
    管理所有用户的AI指挥官实例
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        # 用户ID -> AITradingCommander 映射
        self._commanders: dict[str, Any] = {}
        # 用户ID -> WebSocket 映射
        self._websockets: dict[str, WebSocket] = {}
        # 用户ID -> 状态 映射
        self._states: dict[str, AICommanderState] = {}
        # 用户ID -> 运行任务 映射（防止垃圾回收）
        self._tasks: dict[str, asyncio.Task] = {}
        # 内部锁
        self._manager_lock = asyncio.Lock()

        # 用户数据目录
        self._data_dir = Path("data/trading/ai")
        self._data_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[AITradingManager] AI交易管理器已初始化")

    async def start_commander(
        self,
        user_id: str,
        config_dict: dict[str, Any],
        websocket: WebSocket | None = None
    ) -> bool:
        """
        启动用户的AI指挥官

        Args:
            user_id: 用户ID（隔离）
            config_dict: 配置参数
            websocket: WebSocket连接（可选，用于推送决策）

        Returns:
            bool: 是否成功启动
        """
        async with self._manager_lock:
            # 检查是否已有运行中的指挥官
            if user_id in self._commanders:
                commander = self._commanders[user_id]
                if hasattr(commander, 'is_running') and commander.is_running:
                    logger.warning(f"[AITradingManager] 用户 {user_id} AI指挥官已在运行")
                    return False

            try:
                # 导入并创建指挥官实例
                from core.btc_integration.ai_trading_commander import AITradingCommander

                commander = AITradingCommander(
                    user_id=user_id,
                    symbols=config_dict.get('symbols', ['BTC', 'ETH']),
                    ai_check_interval=config_dict.get('ai_check_interval', 4),
                    risk_profile=config_dict.get('risk_profile', 'moderate'),
                    auto_execute=config_dict.get('auto_execute', True)
                )

                # 保存WebSocket引用
                if websocket and WEBSOCKET_AVAILABLE:
                    self._websockets[user_id] = websocket

                # 保存指挥官实例
                self._commanders[user_id] = commander

                # 初始化状态
                self._states[user_id] = AICommanderState(
                    user_id=user_id,
                    is_running=True,
                    start_time=time.time(),
                    symbols=config_dict.get('symbols', ['BTC', 'ETH']),
                    mode='ai'
                )

                # 启动指挥官（异步任务）
                # 【治理】通过 _run_commander 包装生命周期，保存任务引用
                self._tasks[user_id] = safe_create_task(self._run_commander(user_id, commander), name="_run_commander")

                logger.info(f"[AITradingManager] 用户 {user_id} AI指挥官已启动")
                return True

            except Exception as e:
                logger.error(f"[AITradingManager] 启动用户 {user_id} AI指挥官失败: {e}")
                if user_id in self._states:
                    self._states[user_id].error_message = str(e)
                return False

    async def _run_commander(self, user_id: str, commander: Any) -> None:
        """
        运行指挥官并处理异常

        【关键修复】AITradingCommander 没有 run() 方法，只有 start()。
        start() 返回主循环 Task，我们需要 await 这个 Task 直到完成。

        Args:
            user_id: 用户ID
            commander: 指挥官实例
        """
        main_task = None
        try:
            # 启动指挥官并获取主循环任务
            main_task = await commander.start()

            # 【修复】启动 TradingSubAgent，触发市场数据收集和 MCP 调用
            try:
                symbols = getattr(commander, 'symbols', ['BTC', 'ETH'])
                for symbol in symbols:
                    await commander.start_subagent(symbol)
                    logger.info(f"[AITradingManager] 已启动 {symbol} 交易子代理")
            except Exception as subagent_e:
                logger.error(f"[AITradingManager] 启动交易子代理失败: {subagent_e}")

            # 等待主循环完成（阻塞直到 commander 停止）
            if main_task:
                await main_task
        except asyncio.CancelledError:
            logger.info(f"[AITradingManager] 用户 {user_id} AI指挥官已取消")
            if main_task and not main_task.done():
                main_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await main_task
        except Exception as e:
            logger.error(f"[AITradingManager] 用户 {user_id} AI指挥官运行错误: {e}")
            if user_id in self._states:
                self._states[user_id].error_message = str(e)
                self._states[user_id].is_running = False
                self._states[user_id].mode = 'error'
        finally:
            # 清理任务引用
            if user_id in self._tasks:
                del self._tasks[user_id]

    async def stop_commander(self, user_id: str) -> bool:
        """
        停止用户的AI指挥官

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否成功停止
        """
        async with self._manager_lock:
            if user_id not in self._commanders:
                logger.warning(f"[AITradingManager] 用户 {user_id} 没有运行中的AI指挥官")
                return False

            try:
                commander = self._commanders[user_id]

                # 停止指挥官
                if hasattr(commander, 'stop'):
                    await commander.stop()

                # 更新状态
                if user_id in self._states:
                    self._states[user_id].is_running = False
                    self._states[user_id].mode = 'stopped'

                # 清理引用
                del self._commanders[user_id]
                if user_id in self._websockets:
                    del self._websockets[user_id]

                logger.info(f"[AITradingManager] 用户 {user_id} AI指挥官已停止")
                return True

            except Exception as e:
                logger.error(f"[AITradingManager] 停止用户 {user_id} AI指挥官失败: {e}")
                return False

    async def pause_commander(self, user_id: str) -> bool:
        """
        暂停用户的AI指挥官

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否成功暂停
        """
        async with self._manager_lock:
            if user_id not in self._commanders:
                return False

            try:
                commander = self._commanders[user_id]
                if hasattr(commander, 'pause'):
                    await commander.pause()

                if user_id in self._states:
                    self._states[user_id].mode = 'paused'

                logger.info(f"[AITradingManager] 用户 {user_id} AI指挥官已暂停")
                return True

            except Exception as e:
                logger.error(f"[AITradingManager] 暂停用户 {user_id} AI指挥官失败: {e}")
                return False

    async def resume_commander(self, user_id: str) -> bool:
        """
        恢复用户的AI指挥官

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否成功恢复
        """
        async with self._manager_lock:
            if user_id not in self._commanders:
                return False

            try:
                commander = self._commanders[user_id]
                if hasattr(commander, 'resume'):
                    await commander.resume()

                if user_id in self._states:
                    self._states[user_id].mode = 'ai'

                logger.info(f"[AITradingManager] 用户 {user_id} AI指挥官已恢复")
                return True

            except Exception as e:
                logger.error(f"[AITradingManager] 恢复用户 {user_id} AI指挥官失败: {e}")
                return False

    async def send_decision(self, user_id: str, decision: dict[str, Any]) -> bool:
        """
        向用户推送AI决策

        Args:
            user_id: 用户ID
            decision: 决策数据

        Returns:
            bool: 是否成功发送
        """
        if user_id not in self._websockets:
            return False

        try:
            websocket = self._websockets[user_id]

            if WEBSOCKET_AVAILABLE and hasattr(websocket, 'send_json'):
                await websocket.send_json({
                    "type": "ai_decision",
                    "mode": "ai",
                    "data": decision,
                    "timestamp": int(time.time() * 1000)
                })

                # 更新状态
                if user_id in self._states:
                    self._states[user_id].last_decision_time = time.time()
                    self._states[user_id].decision_count += 1

                return True

        except Exception as e:
            logger.error(f"[AITradingManager] 向用户 {user_id} 发送决策失败: {e}")
            # WebSocket可能已断开，移除引用
            if user_id in self._websockets:
                del self._websockets[user_id]
            return False

        return False

    async def send_decision_blocked(self, user_id: str, data: dict):
        """向指定用户的AI交易WebSocket推送决策被拦截事件"""
        ws = self._websockets.get(user_id)
        if ws:
            with contextlib.suppress(Exception):
                await ws.send_json({
                    "type": "ai_decision_blocked",
                    "data": data
                })

    async def send_thought_step(self, user_id: str, step_type: str, content: str, details: dict = None) -> bool:
        """
        向用户推送思维流步骤

        Args:
            user_id: 用户ID
            step_type: 步骤类型 (market_analysis, news_check, indicator_check, risk_assessment, decision, execution)
            content: 步骤内容
            details: 详细数据

        Returns:
            bool: 是否成功发送
        """
        if user_id not in self._websockets:
            return False

        try:
            websocket = self._websockets[user_id]

            if WEBSOCKET_AVAILABLE and hasattr(websocket, 'send_json'):
                await websocket.send_json({
                    "type": step_type,
                    "mode": "ai",
                    "data": {
                        "content": content,
                        "details": details or {}
                    },
                    "timestamp": int(time.time() * 1000)
                })
                return True

        except Exception as e:
            logger.error(f"[AITradingManager] 向用户 {user_id} 发送思维流失败: {e}")
            if user_id in self._websockets:
                del self._websockets[user_id]
            return False

        return False

    def get_status(self, user_id: str) -> AICommanderState | None:
        """
        获取用户AI指挥官状态

        Args:
            user_id: 用户ID

        Returns:
            AICommanderState: 状态对象，如果不存在则返回None
        """
        return self._states.get(user_id)

    def get_commander(self, user_id: str) -> Any | None:
        """获取用户的AI指挥官实例"""
        return self._commanders.get(user_id)

    def get_all_status(self) -> dict[str, AICommanderState]:
        """
        获取所有AI指挥官状态

        Returns:
            Dict[str, AICommanderState]: 用户ID到状态的映射
        """
        return self._states.copy()

    async def register_websocket(self, user_id: str, websocket: WebSocket) -> bool:
        """
        注册WebSocket连接

        Args:
            user_id: 用户ID
            websocket: WebSocket连接

        Returns:
            bool: 是否成功注册
        """
        async with self._manager_lock:
            self._websockets[user_id] = websocket
            logger.info(f"[AITradingManager] 用户 {user_id} WebSocket已注册")
            return True

    async def unregister_websocket(self, user_id: str) -> bool:
        """
        注销WebSocket连接

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否成功注销
        """
        async with self._manager_lock:
            if user_id in self._websockets:
                del self._websockets[user_id]
                logger.info(f"[AITradingManager] 用户 {user_id} WebSocket已注销")
            return True

    async def intervene(self, user_id: str, action: str, reason: str) -> bool:
        """
        人工干预AI指挥官

        Args:
            user_id: 用户ID
            action: 干预动作（pause, resume, close_all）
            reason: 干预原因

        Returns:
            bool: 是否成功干预
        """
        async with self._manager_lock:
            if user_id not in self._commanders:
                logger.warning(f"[AITradingManager] 用户 {user_id} 没有运行中的AI指挥官，无法干预")
                return False

            try:
                commander = self._commanders[user_id]

                if action == 'pause':
                    if hasattr(commander, 'pause'):
                        await commander.pause()
                    if user_id in self._states:
                        self._states[user_id].mode = 'paused'

                elif action == 'resume':
                    if hasattr(commander, 'resume'):
                        await commander.resume()
                    if user_id in self._states:
                        self._states[user_id].mode = 'ai'

                elif action == 'close_all':
                    if hasattr(commander, 'close_all_positions'):
                        await commander.close_all_positions(reason)

                logger.info(f"[AITradingManager] 用户 {user_id} 干预成功: {action}, 原因: {reason}")
                return True

            except Exception as e:
                logger.error(f"[AITradingManager] 用户 {user_id} 干预失败: {e}")
                return False


# 全局管理器实例
ai_trading_manager = AITradingManager()


# 便捷函数
async def start_ai_trading(user_id: str, config: dict[str, Any], websocket: WebSocket | None = None) -> bool:
    """启动AI交易"""
    return await ai_trading_manager.start_commander(user_id, config, websocket)

async def stop_ai_trading(user_id: str) -> bool:
    """停止AI交易"""
    return await ai_trading_manager.stop_commander(user_id)

async def pause_ai_trading(user_id: str) -> bool:
    """暂停AI交易"""
    return await ai_trading_manager.pause_commander(user_id)

async def resume_ai_trading(user_id: str) -> bool:
    """恢复AI交易"""
    return await ai_trading_manager.resume_commander(user_id)

def get_ai_trading_status(user_id: str) -> AICommanderState | None:
    """获取AI交易状态"""
    return ai_trading_manager.get_status(user_id)
