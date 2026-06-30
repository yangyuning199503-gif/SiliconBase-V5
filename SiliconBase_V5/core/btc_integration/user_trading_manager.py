#!/usr/bin/env python3
"""
用户交易管理器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
管理每个用户的 AITradingCommander 实例

特性:
- 用户级别指挥官缓存
- 自动执行器切换
- 会话生命周期管理
- 零配置开箱即用

作者: SiliconBase Team
日期: 2026-04-09
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.btc_integration.ai_trading_commander import AITradingCommander
from core.btc_integration.trade_executor import (
    TradeExecutor,
    create_default_executor,
    create_executor,
)
from core.diagnostic import safe_create_task
from core.logger import logger


@dataclass
class UserTradingSession:
    """用户交易会话"""
    user_id: str
    commander: AITradingCommander
    executor: TradeExecutor
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    config_id: str | None = None  # 使用的配置ID


class UserTradingManager:
    """
    用户交易管理器 - 单例模式

    管理所有用户的交易会话，提供统一的访问接口
    """

    _instance: Optional['UserTradingManager'] = None
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
        self._sessions: dict[str, UserTradingSession] = {}
        self._session_timeout = 3600  # 会话超时时间（秒）
        self._cleanup_task: asyncio.Task | None = None

        logger.info("[UserTradingManager] 初始化完成")

    async def start(self):
        """启动管理器"""
        if self._cleanup_task is None:
            self._cleanup_task = safe_create_task(self._cleanup_loop(), name="_cleanup_loop")
            logger.info("[UserTradingManager] 清理任务已启动")

    async def stop(self):
        """停止管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

        # 清理所有会话
        for session in self._sessions.values():
            await self._close_session(session)

        self._sessions.clear()
        logger.info("[UserTradingManager] 已停止")

    async def get_commander(
        self,
        user_id: str,
        exchange_config: dict[str, Any] | None = None
    ) -> AITradingCommander:
        """
        获取用户的交易指挥官

        Args:
            user_id: 用户ID
            exchange_config: 交易所配置，为None时使用默认模拟配置

        Returns:
            AITradingCommander 实例
        """
        # 检查现有会话
        session = self._sessions.get(user_id)

        if session:
            # 检查配置是否变更
            current_config_id = exchange_config.get('id') if exchange_config else None
            if current_config_id != session.config_id:
                logger.info(f"[UserTradingManager] 用户 {user_id} 配置变更，重建会话")
                await self._close_session(session)
                session = None

        if not session:
            # 创建新会话
            session = await self._create_session(user_id, exchange_config)
            self._sessions[user_id] = session

        # 更新活跃时间
        session.last_active = time.time()

        return session.commander

    async def get_executor(
        self,
        user_id: str,
        exchange_config: dict[str, Any] | None = None
    ) -> TradeExecutor:
        """获取用户的交易执行器"""
        session = await self._get_or_create_session(user_id, exchange_config)
        return session.executor

    async def switch_config(
        self,
        user_id: str,
        exchange_config: dict[str, Any] | None
    ) -> AITradingCommander:
        """
        切换用户配置

        用于用户切换模拟盘/实盘或更换交易所配置
        """
        # 关闭现有会话
        if user_id in self._sessions:
            await self._close_session(self._sessions[user_id])
            del self._sessions[user_id]

        # 创建新会话
        session = await self._create_session(user_id, exchange_config)
        self._sessions[user_id] = session

        logger.info(
            f"[UserTradingManager] 用户 {user_id} 已切换配置: "
            f"{exchange_config.get('name', '默认模拟')}"
        )

        return session.commander

    def get_session_info(self, user_id: str) -> dict[str, Any] | None:
        """获取用户会话信息"""
        session = self._sessions.get(user_id)
        if not session:
            return None

        executor = session.executor
        return {
            'user_id': user_id,
            'config_id': session.config_id,
            'is_simulation': executor.is_simulation,
            'exchange_type': executor.exchange_type,
            'created_at': session.created_at,
            'last_active': session.last_active,
            'active_duration': time.time() - session.created_at
        }

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """获取所有会话信息"""
        return [
            self.get_session_info(user_id)
            for user_id in self._sessions
        ]

    async def close_user_session(self, user_id: str):
        """关闭用户会话"""
        if user_id in self._sessions:
            await self._close_session(self._sessions[user_id])
            del self._sessions[user_id]
            logger.info(f"[UserTradingManager] 用户 {user_id} 会话已关闭")

    async def _get_or_create_session(
        self,
        user_id: str,
        exchange_config: dict[str, Any] | None
    ) -> UserTradingSession:
        """获取或创建会话"""
        session = self._sessions.get(user_id)

        if not session:
            session = await self._create_session(user_id, exchange_config)
            self._sessions[user_id] = session

        session.last_active = time.time()
        return session

    async def _create_session(
        self,
        user_id: str,
        exchange_config: dict[str, Any] | None
    ) -> UserTradingSession:
        """创建用户交易会话"""

        # 创建执行器
        if exchange_config:
            executor = create_executor(user_id, exchange_config)
            config_id = exchange_config.get('id')
            logger.info(
                f"[UserTradingManager] 用户 {user_id} 创建执行器: "
                f"{executor.exchange_type} {'模拟盘' if executor.is_simulation else '实盘'}"
            )
        else:
            # 使用默认模拟执行器
            executor = create_default_executor(user_id)
            config_id = None
            logger.info(f"[UserTradingManager] 用户 {user_id} 使用默认模拟执行器")

        # 创建指挥官
        commander = AITradingCommander(
            user_id=user_id,
            executor=executor
        )

        # 初始化指挥官
        await commander.initialize()

        session = UserTradingSession(
            user_id=user_id,
            commander=commander,
            executor=executor,
            config_id=config_id
        )

        logger.info(f"[UserTradingManager] 用户 {user_id} 交易会话已创建")
        return session

    async def _close_session(self, session: UserTradingSession):
        """关闭会话"""
        try:
            await session.commander.shutdown()
        except Exception as e:
            logger.error(f"[UserTradingManager] 关闭会话出错: {e}")

    async def _cleanup_loop(self):
        """清理过期会话的循环"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[UserTradingManager] 清理任务出错: {e}")

    async def _cleanup_expired_sessions(self):
        """清理过期会话"""
        current_time = time.time()
        expired_users = []

        for user_id, session in self._sessions.items():
            if current_time - session.last_active > self._session_timeout:
                expired_users.append(user_id)

        for user_id in expired_users:
            await self.close_user_session(user_id)
            logger.info(f"[UserTradingManager] 过期会话已清理: {user_id}")


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

_user_trading_manager: UserTradingManager | None = None


def get_user_trading_manager() -> UserTradingManager:
    """获取用户交易管理器实例"""
    global _user_trading_manager
    if _user_trading_manager is None:
        _user_trading_manager = UserTradingManager()
    return _user_trading_manager


async def get_user_commander(
    user_id: str,
    exchange_config: dict[str, Any] | None = None
) -> AITradingCommander:
    """
    便捷函数: 获取用户交易指挥官

    这是最常见的使用方式，从管理器获取用户的指挥官实例
    """
    manager = get_user_trading_manager()
    return await manager.get_commander(user_id, exchange_config)


# ═══════════════════════════════════════════════════════════════
# 初始化/关闭
# ═══════════════════════════════════════════════════════════════

async def initialize_user_trading_manager():
    """初始化全局管理器"""
    manager = get_user_trading_manager()
    await manager.start()


async def shutdown_user_trading_manager():
    """关闭全局管理器"""
    global _user_trading_manager
    if _user_trading_manager:
        await _user_trading_manager.stop()
        _user_trading_manager = None
