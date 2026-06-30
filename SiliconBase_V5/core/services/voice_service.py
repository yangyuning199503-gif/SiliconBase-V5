#!/usr/bin/env python3
"""
Voice服务层 - 统一 voice 实例管理
硅基生命底座架构改进
"""

import threading
from typing import Any

from core.logger import logger


class VoiceService:
    """
    Voice统一服务层 - 单例

    职责：
    1. 统一管理 voice 实例生命周期
    2. 提供统一的 voice 获取接口
    3. 处理 voice 不可用时的降级策略
    4. 维护 voice 状态（可用/不可用）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._voice_instance: Any | None = None
        self._voice_available: bool = False
        self._voice_lock = threading.RLock()

        logger.info("[VoiceService] 初始化完成")

    def register_voice(self, voice_instance: Any) -> bool:
        """注册voice实例（系统启动时调用）"""
        with self._voice_lock:
            if voice_instance is None:
                logger.warning("[VoiceService] 尝试注册None voice")
                return False

            self._voice_instance = voice_instance
            self._voice_available = True
            logger.info("[VoiceService] voice实例已注册")
            return True

    def get_voice(self) -> Any | None:
        """获取voice实例（统一入口）"""
        with self._voice_lock:
            if not self._voice_available or self._voice_instance is None:
                self._try_restore_voice()

            return self._voice_instance if self._voice_available else None

    def _try_restore_voice(self) -> bool:
        """尝试从其他来源恢复voice（向后兼容）"""
        try:
            from core.global_state import get_voice_interface
            voice = get_voice_interface()
            if voice:
                self._voice_instance = voice
                self._voice_available = True
                logger.info("[VoiceService] 从global_state恢复voice")
                return True
        except Exception as e:
            logger.debug(f"[VoiceService] 从global_state恢复失败: {e}")

        try:
            from core.dialog.dialogue_manager import get_dialogue_manager
            dm = get_dialogue_manager()
            if hasattr(dm, "voice") and dm.voice:
                self._voice_instance = dm.voice
                self._voice_available = True
                logger.info("[VoiceService] 从dialogue_manager恢复voice")
                return True
        except Exception as e:
            logger.debug(f"[VoiceService] 从dialogue_manager恢复失败: {e}")

        return False

    def is_voice_available(self) -> bool:
        """检查voice是否可用"""
        with self._voice_lock:
            return self._voice_available and self._voice_instance is not None

    def speak(self, text: str, wait: bool = False) -> bool:
        """统一语音播报接口"""
        voice = self.get_voice()
        if not voice:
            logger.debug(f"[VoiceService] voice不可用，跳过播报: {text[:30]}...")
            return False

        try:
            if hasattr(voice, "speak"):
                voice.speak(text, wait=wait)
                return True
            elif hasattr(voice, "say"):
                voice.say(text, wait=wait)
                return True
            else:
                logger.warning("[VoiceService] voice实例没有speak/say方法")
                return False
        except Exception as e:
            logger.warning(f"[VoiceService] 语音播报失败: {e}")
            self._voice_available = False
            return False

    def shutdown(self):
        """关闭voice服务（系统退出时调用）"""
        with self._voice_lock:
            if self._voice_instance and hasattr(self._voice_instance, "shutdown"):
                try:
                    self._voice_instance.shutdown()
                except Exception as e:
                    logger.error(f"[VoiceService] 关闭voice失败: {e}")

            self._voice_instance = None
            self._voice_available = False
            logger.info("[VoiceService] 已关闭")


# 全局便捷函数
_voice_service = None

def get_voice_service() -> VoiceService:
    """获取Voice服务单例"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service


def speak(text: str, wait: bool = False) -> bool:
    """便捷函数：语音播报"""
    return get_voice_service().speak(text, wait=wait)
