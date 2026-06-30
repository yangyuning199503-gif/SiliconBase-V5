#!/usr/bin/env python3
"""
语音唤醒处理器 - 修复4个关键Bug

Bug清单:
1. 双重重置竞争条件（voice/interface.py:1061 和 2316）
2. 部分识别未检查系统播报状态（L1112-1129）
3. 唤醒词检测后重置不彻底
4. 唤醒词文本可能包含在传给AI的内容中

修复方案:
- 使用单一锁保护重置操作，避免竞争条件
- 系统播报期间跳过部分识别
- 三重重置确保缓冲区彻底清除
- 智能过滤唤醒词文本
"""

import re
import threading
import time
from collections.abc import Callable

from core.config import config
from core.logger import logger


class WakeWordHandler:
    """
    语音唤醒处理器

    职责:
    1. 管理唤醒词检测后的重置操作（线程安全）
    2. 控制系统播报期间的部分识别
    3. 从用户输入中过滤唤醒词
    """
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, wake_words: list[str] = None):
        if self._initialized:
            return
        self._initialized = True
        """
        初始化唤醒处理器

        Args:
            wake_words: 唤醒词列表，用于过滤用户输入
        """
        # Bug #1修复: 使用锁保护重置操作，避免竞争条件
        self._reset_lock = threading.RLock()

        # Bug #2修复: 系统播报时间戳
        self._system_speaking_until = 0.0

        # 唤醒词配置：优先使用传入值，其次从配置读取，最后使用默认
        config_wake_words = config.get("voice.wake_words", None)
        if wake_words:
            self.wake_words = wake_words
        elif config_wake_words:
            if isinstance(config_wake_words, str):
                self.wake_words = [config_wake_words]
            else:
                self.wake_words = list(config_wake_words)
        else:
            self.wake_words = ["硅基"]

        # 重置状态追踪
        self._last_reset_time = 0.0
        self._reset_in_progress = False

        # 唤醒词过滤相关
        self._wake_word_variants = self._build_wake_word_variants()

        # 调试计数器
        self._reset_count = 0
        self._skip_due_to_speaking_count = 0

        logger.info(f"[WakeWordHandler] 初始化完成，唤醒词: {self.wake_words}")

    def _build_wake_word_variants(self) -> list[str]:
        """
        构建唤醒词变体列表，用于更精确的过滤

        Returns:
            List[str]: 唤醒词变体列表（包括带标点、空格等变体）
        """
        variants = set()
        for word in self.wake_words:
            # 原始形式
            variants.add(word)
            # 小写形式
            variants.add(word.lower())
            # 去除空格
            variants.add(word.replace(" ", ""))
            # 带逗号
            variants.add(word + "，")
            variants.add(word + ",")
            # 带句号
            variants.add(word + "。")
            variants.add(word + ".")
        return list(variants)

    def on_wake_word_detected(self,
                              stop_speaking_func: Callable[[], None],
                              recognizer,
                              play_feedback_func: Callable[[], None]) -> bool:
        """
        唤醒词检测到时的处理流程（Bug #1, #3修复）

        Args:
            stop_speaking_func: 停止播报的函数
            recognizer: Vosk识别器实例
            play_feedback_func: 播放唤醒反馈的函数

        Returns:
            bool: 处理是否成功
        """
        with self._reset_lock:
            try:
                logger.info("[WakeWordHandler] 唤醒词检测，开始处理流程")

                # 1. 立即停止当前播报
                try:
                    stop_speaking_func()
                    logger.debug("[WakeWordHandler] 已停止当前播报")
                except Exception as e:
                    logger.error(f"[WakeWordHandler] 停止播报失败: {e}")
                    # 继续处理，不阻断唤醒流程

                # 2. 设置系统播报保护期（Bug #2修复）
                # 5秒内部分识别将被跳过，避免识别"我在"等反馈音
                self._system_speaking_until = time.time() + 5.0
                logger.debug(f"[WakeWordHandler] 系统播报保护期设置，直到 {self._system_speaking_until}")

                # 3. 执行三重重置（Bug #3修复）
                self._triple_reset_recognizer(recognizer)

                # 4. 播放唤醒反馈
                try:
                    play_feedback_func()
                    logger.info("[WakeWordHandler] 唤醒反馈播放完成")
                except Exception as e:
                    logger.error(f"[WakeWordHandler] 播放唤醒反馈失败: {e}")
                    # 播放失败不影响唤醒状态

                logger.info(f"[WakeWordHandler] 唤醒处理完成，总计重置次数: {self._reset_count}")
                return True

            except Exception as e:
                logger.error(f"[WakeWordHandler] 唤醒处理异常: {e}", exc_info=True)
                return False

    def _triple_reset_recognizer(self, recognizer) -> None:
        """
        三重重置识别器（Bug #3修复）

        执行三次Reset操作，每次间隔50ms，确保缓冲区彻底清除

        Args:
            recognizer: Vosk识别器实例
        """
        if recognizer is None:
            logger.error("[WakeWordHandler] 识别器为空，无法重置")
            raise ValueError("Recognizer is None")

        self._reset_in_progress = True
        self._last_reset_time = time.time()
        self._reset_count += 1  # 增加重置计数

        try:
            for i in range(3):
                recognizer.Reset()
                logger.debug(f"[WakeWordHandler] 识别器重置 #{i+1}/3")
                if i < 2:  # 前两次之后休眠
                    time.sleep(0.05)  # 50ms间隔

            logger.info("[WakeWordHandler] 三重重置完成")
        except Exception as e:
            logger.error(f"[WakeWordHandler] 识别器重置失败: {e}", exc_info=True)
            raise  # 重置失败不静默，抛出异常
        finally:
            self._reset_in_progress = False

    def on_partial_result(self, text: str) -> str | None:
        """
        部分识别结果处理（Bug #2修复）

        Args:
            text: 部分识别文本

        Returns:
            Optional[str]: 处理后的文本，如果在系统播报期间则返回None
        """
        # Bug #2修复: 系统播报期间跳过部分识别
        if time.time() < self._system_speaking_until:
            self._skip_due_to_speaking_count += 1
            if self._skip_due_to_speaking_count % 10 == 0:  # 每10次记录一次日志
                logger.debug(f"[WakeWordHandler] 系统播报期间跳过部分识别（累计{self._skip_due_to_speaking_count}次）")
            return None

        return text

    def should_skip_partial_due_to_speaking(self) -> bool:
        """
        检查是否应该跳过部分识别（因为系统正在播报）

        Returns:
            bool: 如果系统正在播报返回True
        """
        return time.time() < self._system_speaking_until

    def filter_wake_words(self, text: str) -> str:
        """
        从文本中过滤唤醒词（Bug #4修复）

        Args:
            text: 原始识别文本

        Returns:
            str: 过滤后的文本
        """
        if not text:
            return text

        original_text = text
        filtered_text = text

        # 去除首尾唤醒词（最常见的情况）
        for variant in sorted(self._wake_word_variants, key=len, reverse=True):
            # 去除开头的唤醒词+标点
            pattern = f"^{re.escape(variant)}\\s*[，,。.]?\\s*"
            filtered_text = re.sub(pattern, "", filtered_text, flags=re.IGNORECASE)

            # 去除结尾的唤醒词+标点
            pattern = f"\\s*[，,。.]?\\s*{re.escape(variant)}$"
            filtered_text = re.sub(pattern, "", filtered_text, flags=re.IGNORECASE)

        # 清理多余空格
        filtered_text = filtered_text.strip()

        if filtered_text != original_text:
            logger.info(f"[WakeWordHandler] 已过滤唤醒词: '{original_text}' -> '{filtered_text}'")

        return filtered_text

    def end_system_speaking_period(self) -> None:
        """
        手动结束系统播报保护期
        在系统播报提前结束时调用
        """
        self._system_speaking_until = 0.0
        logger.debug("[WakeWordHandler] 系统播报保护期已手动结束")

    def get_stats(self) -> dict:
        """
        获取处理器统计信息

        Returns:
            dict: 包含各种计数器的字典
        """
        return {
            "reset_count": self._reset_count,
            "skip_due_to_speaking_count": self._skip_due_to_speaking_count,
            "system_speaking_until": self._system_speaking_until,
            "time_until_speaking_ends": max(0, self._system_speaking_until - time.time()),
            "reset_in_progress": self._reset_in_progress,
            "last_reset_time": self._last_reset_time,
        }

    def reset_stats(self) -> None:
        """重置统计计数器"""
        self._reset_count = 0
        self._skip_due_to_speaking_count = 0
        logger.info("[WakeWordHandler] 统计计数器已重置")
