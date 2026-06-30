#!/usr/bin/env python3
"""
语音状态同步模块
负责将语音状态变化通过WebSocket发送到前端

需要同步的状态:
1. 唤醒状态: awake=True/False
2. 播报状态: is_speaking=True/False
3. 系统播报保护期: system_speaking_until
4. 识别状态: listening=True/False
"""

import asyncio
import threading
import time
from enum import Enum
from typing import Any

from core.logger import logger


class VoiceState(Enum):
    """语音状态枚举"""
    IDLE = "idle"           # 空闲状态
    AWAKE = "awake"         # 唤醒状态（正在倾听）
    SPEAKING = "speaking"   # 播报状态
    LISTENING = "listening" # 识别状态


class VoiceStateSync:
    """
    语音状态同步器
    单例模式，用于统一管理语音状态并发送WebSocket事件

    【治理】使用 threading.Lock() 保护单例创建，防止竞态条件。
    """
    _instance = None
    _creation_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._creation_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 当前状态
        self._current_state = VoiceState.IDLE
        self._awake = False
        self._is_speaking = False
        self._is_listening = False
        self._system_speaking_until = 0.0

        # WebSocket连接管理器缓存
        self._connection_manager = None

        logger.info("[VoiceStateSync] 语音状态同步器初始化完成")

    def _get_connection_manager(self):
        """获取WebSocket连接管理器（延迟导入避免循环依赖）"""
        if self._connection_manager is None:
            try:
                from api.cloud_api import ConnectionManager
                self._connection_manager = ConnectionManager()
            except ImportError as e:
                logger.error(f"[VoiceStateSync] 导入ConnectionManager失败: {e}")
                return None
        return self._connection_manager

    async def _send_state_change(self, state: VoiceState, data: dict[str, Any] | None = None):
        """
        发送状态变化事件到前端

        Args:
            state: 新状态
            data: 附加数据
        """
        try:
            manager = self._get_connection_manager()
            if manager is None:
                return

            # 构造消息
            message = {
                "type": "voice_state_change",
                "state": state.value,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data or {}
            }

            # 添加保护期信息（如果存在）
            if self._system_speaking_until > time.time():
                message["data"]["protected_until"] = int(self._system_speaking_until * 1000)  # 毫秒时间戳

            # 发送给所有在线用户
            sent_count = 0
            for user_id in ["user_admin", "voice", "default"]:
                try:
                    connections = manager.get_user_connections(user_id)
                    if connections > 0:
                        await manager.send_to_user(user_id, message)
                        sent_count += 1
                        logger.debug(f"[VoiceStateSync] 状态 '{state.value}' 已发送给用户 {user_id}")
                except Exception as e:
                    logger.error(f"[VoiceStateSync] 发送给用户 {user_id} 失败: {e}")

            if sent_count == 0:
                logger.debug(f"[VoiceStateSync] 没有在线用户接收状态 '{state.value}'")
            else:
                logger.info(f"[VoiceStateSync] 状态变化: {state.value} -> {sent_count} 个用户")

        except Exception as e:
            logger.error(f"[VoiceStateSync] 发送状态变化失败: {e}", exc_info=True)

    def _sync_send_state_change(self, state: VoiceState, data: dict[str, Any] | None = None):
        """同步方式发送状态变化（用于非异步上下文）"""
        try:
            # 尝试获取事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果已经在事件循环中，创建任务
                asyncio.create_task(self._send_state_change(state, data))
            except RuntimeError:
                # 没有运行中的事件循环，尝试获取或创建
                try:
                    # 尝试获取当前线程的事件循环
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._send_state_change(state, data),
                            loop
                        )
                    else:
                        # 如果循环未运行，无法发送
                        logger.debug(f"[VoiceStateSync] 事件循环未运行，跳过发送状态 '{state.value}'")
                except RuntimeError:
                    # 【修复】子线程中没有事件循环，静默跳过
                    # 这是正常现象，因为语音播报在后台线程中
                    logger.debug(f"[VoiceStateSync] 子线程无事件循环，跳过发送状态 '{state.value}'")
                except Exception as e:
                    logger.error(f"[VoiceStateSync] 同步发送失败: {e}")
        except Exception as e:
            logger.error(f"[VoiceStateSync] 同步发送状态变化失败: {e}", exc_info=True)

    def update_state(self,
                     awake: bool | None = None,
                     is_speaking: bool | None = None,
                     is_listening: bool | None = None,
                     system_speaking_until: float | None = None):
        """
        更新语音状态并发送WebSocket事件

        Args:
            awake: 唤醒状态
            is_speaking: 播报状态
            is_listening: 识别状态
            system_speaking_until: 系统播报保护期结束时间（秒级时间戳）
        """
        # 更新内部状态
        if awake is not None:
            self._awake = awake
        if is_speaking is not None:
            self._is_speaking = is_speaking
        if is_listening is not None:
            self._is_listening = is_listening
        if system_speaking_until is not None:
            self._system_speaking_until = system_speaking_until

        # 计算新状态
        new_state = self._calculate_state()

        # 如果状态变化，发送事件
        if new_state != self._current_state:
            self._current_state = new_state

            # 准备附加数据
            data = {
                "awake": self._awake,
                "is_speaking": self._is_speaking,
                "is_listening": self._is_listening,
            }

            if self._system_speaking_until > time.time():
                data["protected_until"] = int(self._system_speaking_until * 1000)

            self._sync_send_state_change(new_state, data)
            logger.info(f"[VoiceStateSync] 状态更新: {new_state.value} (awake={self._awake}, speaking={self._is_speaking})")

    def _calculate_state(self) -> VoiceState:
        """根据内部状态计算当前状态"""
        # 优先级: speaking > listening > awake > idle
        if self._is_speaking:
            return VoiceState.SPEAKING
        elif self._is_listening:
            return VoiceState.LISTENING
        elif self._awake:
            return VoiceState.AWAKE
        else:
            return VoiceState.IDLE

    # ========== 便捷方法 ==========

    def on_wake(self):
        """唤醒时调用"""
        self.update_state(awake=True)

    def on_sleep(self):
        """休眠时调用"""
        self.update_state(awake=False, is_listening=False)

    def on_start_speaking(self, protected_duration: float = 0.0):
        """
        开始播报时调用

        Args:
            protected_duration: 保护期时长（秒）
        """
        protected_until = time.time() + protected_duration if protected_duration > 0 else 0.0
        self.update_state(is_speaking=True, system_speaking_until=protected_until)

    def on_stop_speaking(self):
        """停止播报时调用"""
        self.update_state(is_speaking=False)

    def on_start_listening(self):
        """开始识别时调用"""
        self.update_state(is_listening=True)

    def on_stop_listening(self):
        """停止识别时调用"""
        self.update_state(is_listening=False)

    def get_current_state(self) -> dict[str, Any]:
        """获取当前状态信息"""
        return {
            "state": self._current_state.value,
            "awake": self._awake,
            "is_speaking": self._is_speaking,
            "is_listening": self._is_listening,
            "system_speaking_until": self._system_speaking_until if self._system_speaking_until > time.time() else None,
            "is_protected": self._system_speaking_until > time.time()
        }


# 全局状态同步器实例
_voice_state_sync: VoiceStateSync | None = None


def get_voice_state_sync() -> VoiceStateSync:
    """获取语音状态同步器实例"""
    global _voice_state_sync
    if _voice_state_sync is None:
        _voice_state_sync = VoiceStateSync()
    return _voice_state_sync
