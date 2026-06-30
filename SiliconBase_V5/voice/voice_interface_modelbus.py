#!/usr/bin/env python3
"""
VoiceInterface的ModelBus适配版本

保持原有接口，内部使用ModelBus架构
实现渐进式迁移，不破坏现有功能

作者: 修复代理2
"""
import asyncio
import contextlib
import queue
import threading
import time
from typing import Any

from core.ai_models.exceptions import RecognitionException, SynthesisException
from core.logger import logger

# 导入ModelBus相关
from voice.model_bus_adapter import VoiceModelBusAdapter, get_voice_adapter

# 导入原有组件以保持兼容性
from voice.protected_speak_queue import ProtectedSpeakQueue
from voice.state_sync import get_voice_state_sync
from voice.wake_word_handler import WakeWordHandler


class VoiceInterfaceModelBus:
    """
    VoiceInterface的ModelBus适配实现

    保持与原有VoiceInterface相同的API，
    内部通过VoiceModelBusAdapter使用ModelBus架构

    主要特性：
    - ASR语音识别（通过ModelBus）
    - TTS语音合成（通过ModelBus）
    - 唤醒词检测（复用原有逻辑）
    - 播报队列（复用ProtectedSpeakQueue）
    - pyttsx3降级（保留）
    """

    def __init__(self, config: dict[str, Any] = None):
        """
        初始化语音接口

        Args:
            config: 配置字典，与原有接口兼容
        """
        self.config = config or {}
        self._adapter: VoiceModelBusAdapter | None = None
        self._initialized = False

        # 保留原有属性以兼容旧代码
        self.vosk_model = None  # 旧属性，保持兼容
        self._piper_voice = None  # 旧属性，保持兼容

        # ---------- 线程锁 ----------
        self._state_lock = threading.Lock()
        self._timer_lock = threading.Lock()
        self._speaking_lock = threading.RLock()

        # ---------- 唤醒词配置 ----------
        self._init_wake_words()

        # ---------- 播报队列 ----------
        self._speak_queue = ProtectedSpeakQueue()
        self._current_speak_priority = 0
        self._current_speak_protected = False
        self._should_stop_current = False

        # 播报工作线程
        self._speak_thread = threading.Thread(target=self._speak_worker, daemon=True)
        self._speak_thread.start()

        # ---------- 状态管理 ----------
        self._is_listening = False
        self.is_speaking = False
        self.awake = False
        self.awake_timeout = self.config.get("voice", {}).get("awake_timeout", 300)
        self._awake_timer = None
        self._awake_by_ptt = False

        # Talk Mode
        self.in_talk_mode = False
        self._talk_mode_lock = threading.Lock()
        self._talk_mode_round = 0
        self._talk_mode_max_round = 10
        self._talk_mode_silence_threshold = 8.0
        self._last_user_speak_time = 0

        # PTT模式
        self.push_to_talk = False
        self._ptt_session_active = False
        self.ptt_timeout = self.config.get("voice", {}).get("ptt_timeout", 60)

        # 唤醒词处理器
        self._wake_word_handler = WakeWordHandler(self.wake_words)

        # 播报去重
        self._last_announce_text = ""
        self._last_announce_time = 0

        # 降级引擎
        self._fallback_engine = None
        self._init_fallback()

        # 音频资源
        self._last_spoken_text = ""
        self._last_speak_time = 0
        self._is_system_speaking = False

        # 事件循环（用于异步回调）
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        logger.info("[VoiceInterfaceModelBus] 实例已创建")

    def _init_wake_words(self):
        """初始化唤醒词配置"""
        voice_config = self.config.get("voice", {})
        wake_words = voice_config.get("wake_words")

        if wake_words is None:
            # 尝试旧键
            old_wake_word = self.config.get("wake_word")
            if old_wake_word is not None:
                import warnings
                warnings.warn(
                    "配置项 'wake_word' 已弃用，请使用 'voice.wake_words'",
                    DeprecationWarning,
                    stacklevel=2
                )
                wake_words = [old_wake_word] if isinstance(old_wake_word, str) else old_wake_word
            else:
                wake_words = ["元旦", "你好元旦"]

        # 确保是列表
        if isinstance(wake_words, str):
            wake_words = [wake_words]

        self.wake_words = wake_words
        logger.info(f"[VoiceInterfaceModelBus] 唤醒词配置: {self.wake_words}")

    def _init_fallback(self):
        """初始化pyttsx3降级引擎"""
        try:
            import pyttsx3
            self._fallback_engine = pyttsx3.init()
            self._fallback_engine.setProperty('rate', 180)
            self._fallback_engine.setProperty('volume', 0.9)

            voices = self._fallback_engine.getProperty('voices')
            for voice in voices:
                if 'hui' in voice.name.lower() or 'chinese' in str(voice.languages).lower():
                    self._fallback_engine.setProperty('voice', voice.id)
                    logger.info(f"[VoiceInterfaceModelBus] 降级引擎选择语音: {voice.name}")
                    break
        except ImportError:
            self._fallback_engine = None
            logger.warning("[VoiceInterfaceModelBus] pyttsx3未安装，降级功能不可用")
        except Exception as e:
            self._fallback_engine = None
            logger.error(f"[VoiceInterfaceModelBus] pyttsx3初始化失败: {e}")

    def _run_loop(self):
        """运行事件循环"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 事件循环异常: {e}")

    # ========== 属性访问器（线程安全） ==========

    @property
    def is_listening(self) -> bool:
        """线程安全地获取is_listening状态"""
        with self._state_lock:
            return self._is_listening

    @is_listening.setter
    def is_listening(self, value: bool):
        """线程安全地设置is_listening状态"""
        with self._state_lock:
            self._is_listening = value

    # ========== 初始化 ==========

    async def initialize(self) -> bool:
        """
        初始化语音系统（ModelBus方式）

        Returns:
            bool: 初始化是否成功
        """
        if self._initialized:
            return True

        try:
            # 获取或创建ModelBus适配器
            self._adapter = get_voice_adapter()

            # 转换配置格式
            modelbus_config = self._convert_config(self.config)

            # 初始化适配器
            success = await self._adapter.initialize(modelbus_config)

            if success:
                self._initialized = True
                logger.info("[VoiceInterfaceModelBus] 初始化成功")
                return True
            else:
                logger.error("[VoiceInterfaceModelBus] 适配器初始化失败")
                return False

        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 初始化失败: {e}", exc_info=True)
            return False

    def _convert_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        将旧配置格式转换为ModelBus配置格式

        Args:
            config: 旧格式配置

        Returns:
            ModelBus格式配置
        """
        voice_config = config.get("voice", {})

        modelbus_config = {
            "voice.model_path": voice_config.get("model_path", "assets/models/vosk-model-cn-0.22"),
            "voice.tts_engine": voice_config.get("tts_engine", "piper"),
            "voice.piper.model_path": voice_config.get("piper", {}).get("model_path",
                "assets/models/piper/zh_CN-huayan-medium.onnx"),
            "voice.piper.config_path": voice_config.get("piper", {}).get("config_path"),
        }

        return modelbus_config

    # ========== ASR语音识别 ==========

    async def recognize(self, audio_data: bytes) -> str:
        """
        语音识别（ModelBus方式）

        Args:
            audio_data: PCM音频数据 (16kHz, 16bit, mono)

        Returns:
            识别文本
        """
        if not self._initialized and not await self.initialize():
            logger.error("[VoiceInterfaceModelBus] 无法初始化，识别失败")
            return ""

        try:
            text = await self._adapter.recognize(audio_data)
            return text
        except RecognitionException as e:
            logger.error(f"[VoiceInterfaceModelBus] 识别失败: {e}")
            return ""
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 识别异常: {e}")
            return ""

    # ========== TTS语音合成 ==========

    async def synthesize(self, text: str) -> bytes:
        """
        语音合成（ModelBus方式）

        Args:
            text: 要合成的文本

        Returns:
            WAV格式音频字节数据
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("语音系统未初始化")

        try:
            audio_data = await self._adapter.synthesize(text)
            return audio_data
        except SynthesisException as e:
            logger.error(f"[VoiceInterfaceModelBus] 合成失败: {e}")
            raise
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 合成异常: {e}")
            raise SynthesisException(f"语音合成失败: {e}") from e

    # ========== 播报功能 ==========

    def speak(self, text: str, wait: bool = True, is_system: bool = None,
              protected: bool = None, priority: int = None):
        """
        语音播报（使用队列避免重叠）

        Args:
            text: 要播报的文本
            wait: 是否等待播报完成
            is_system: 是否是系统音
            protected: 是否受保护
            priority: 优先级（0=最高，数值越大优先级越低）
        """
        if not text:
            return

        # 去重检查
        current_time = time.time()
        if (text == self._last_announce_text and
            current_time - self._last_announce_time < 5.0):
            logger.debug(f"[VoiceInterfaceModelBus] 跳过重复播报: {text[:30]}...")
            return

        self._last_announce_text = text
        self._last_announce_time = current_time

        # 过滤内容
        text = self._filter_speak_content(text)
        if not text:
            return

        # 自动判断
        if is_system is None:
            system_keywords = ["底座", "系统", "启动", "初始化", "等待指令", "就绪"]
            is_system = any(kw in text for kw in system_keywords)

        if protected is None:
            protected_keywords = ["系统启动", "初始化完成", "错误", "警告", "紧急"]
            protected = is_system or any(kw in text for kw in protected_keywords)

        if priority is None:
            priority = 1 if is_system else 0

        # 智能中断
        with self._speaking_lock:
            current_priority = self._current_speak_priority
            current_protected = self._current_speak_protected
            is_currently_speaking = self.is_speaking

        if (is_currently_speaking and
            priority < current_priority and
            not current_protected):
            logger.info("[VoiceInterfaceModelBus] 高优先级打断低优先级")
            self._interrupt_current_playback(smooth=True)

        # 记录播报信息用于回声检测
        with self._speaking_lock:
            self._is_system_speaking = is_system
            self._last_spoken_text = text
            self._last_speak_time = time.time()

        # 加入队列
        self._speak_queue.enqueue(text, wait, priority, protected)

        # 状态同步
        try:
            state_sync = get_voice_state_sync()
            protected_duration = 5.0 if is_system else 0.0
            state_sync.on_start_speaking(protected_duration)
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

    def _speak_worker(self):
        """播报工作线程"""
        logger.info("[VoiceInterfaceModelBus] 播报工作线程启动")

        while True:
            try:
                item = self._speak_queue.get(timeout=1.0)

                if item is None:  # 停止信号
                    break

                # 设置当前播报状态
                with self._speaking_lock:
                    self._current_speak_priority = -item.priority  # 转换回原始优先级
                    self._current_speak_protected = item.protected
                    self.is_speaking = True
                    self._should_stop_current = False

                try:
                    # 合成并播放
                    asyncio.run_coroutine_threadsafe(
                        self._synthesize_and_play(item.text),
                        self.loop
                    ).result(timeout=60)

                except Exception as e:
                    logger.error(f"[VoiceInterfaceModelBus] 播报失败: {e}")
                    # 降级到pyttsx3
                    self._fallback_speak(item.text)

                finally:
                    with self._speaking_lock:
                        self.is_speaking = False
                    self._speak_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[VoiceInterfaceModelBus] 播报工作线程异常: {e}")

    async def _synthesize_and_play(self, text: str):
        """合成并播放音频"""
        try:
            audio_data = await self.synthesize(text)
            await self._play_audio(audio_data)
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 合成播放失败: {e}")
            raise

    async def _play_audio(self, audio_data: bytes):
        """播放音频数据"""
        try:
            import io
            import wave

            import pyaudio

            # 解析WAV数据
            with wave.open(io.BytesIO(audio_data), 'rb') as wf:
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True
                )

                # 播放
                chunk_size = 1024
                data = wf.readframes(chunk_size)

                while data:
                    # 检查中断标志
                    if self._should_stop_current:
                        logger.info("[VoiceInterfaceModelBus] 播报被中断")
                        break

                    stream.write(data)
                    data = wf.readframes(chunk_size)

                stream.stop_stream()
                stream.close()
                p.terminate()

        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 播放音频失败: {e}")
            raise

    def _fallback_speak(self, text: str):
        """pyttsx3降级播报（带超时，防止 runAndWait 在 Windows 上无限阻塞）"""
        if not self._fallback_engine:
            return

        full_text = text.strip() if text else ""
        if not full_text:
            return

        try:
            self._fallback_engine.say(full_text)

            # pyttsx3.runAndWait() 在 Windows 上可能无限阻塞，使用带超时的线程避免卡死
            _run_event = threading.Event()
            _run_exc = None

            def _run_and_wait():
                nonlocal _run_exc
                try:
                    self._fallback_engine.runAndWait()
                except Exception as _e:
                    _run_exc = _e
                finally:
                    _run_event.set()

            _run_thread = threading.Thread(target=_run_and_wait, daemon=True)
            _run_thread.start()

            # 根据文本长度动态超时：最少8秒，每字0.15秒，最多25秒
            _timeout = min(max(8.0, len(full_text) * 0.15), 25.0)
            _run_event.wait(timeout=_timeout)

            if _run_thread.is_alive():
                logger.warning(f"[VoiceInterfaceModelBus] runAndWait() 超时（{_timeout}s），强制停止引擎")
                try:
                    self._fallback_engine.stop()
                except Exception as _stop_err:
                    logger.debug(f"[VoiceInterfaceModelBus] stop() 失败: {_stop_err}")
            elif _run_exc:
                raise _run_exc

            # 重置引擎状态
            with contextlib.suppress(Exception):
                self._fallback_engine.stop()

        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 降级播报失败: {e}")
            # 尝试重新初始化引擎，避免僵尸状态
            try:
                self._init_fallback()
            except Exception as reinit_err:
                logger.debug(f"[VoiceInterfaceModelBus] 引擎重新初始化失败: {reinit_err}")

    def stop_speaking(self, clear_unprotected_only: bool = True):
        """停止播报"""
        with self._speaking_lock:
            if self._current_speak_protected and clear_unprotected_only:
                logger.warning("[VoiceInterfaceModelBus] 当前播报受保护，保留播放")
                self._should_stop_current = True
                cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=True)
                if cleared > 0:
                    print(f"[VoiceInterfaceModelBus] 播报队列已清空，移除 {cleared} 个待播报项")
                return

            self._should_stop_current = True
            self.is_speaking = False

        cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=clear_unprotected_only)
        if cleared > 0 or protected > 0:
            print(f"[VoiceInterfaceModelBus] 播报队列已处理，移除 {cleared} 个，保留 {protected} 个")

        # 状态同步
        try:
            state_sync = get_voice_state_sync()
            state_sync.on_stop_speaking()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

    def _interrupt_current_playback(self, smooth: bool = True):
        """中断当前播报"""
        if smooth:
            self._should_stop_current = True
        else:
            self._should_stop_current = True
            self.stop_speaking(clear_unprotected_only=True)

    def _filter_speak_content(self, text: str) -> str:
        """过滤播报内容"""
        import ast
        import json
        import re

        if not text:
            return text

        # 移除代码块
        text_clean = re.sub(r'```json\s*.*?\s*```', '', text, flags=re.DOTALL)
        text_clean = re.sub(r'```\s*.*?\s*```', '', text_clean, flags=re.DOTALL)

        # 提取JSON内容
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    data = ast.literal_eval(json_str)

                if isinstance(data, dict):
                    if 'reply_to_user' in data and data['reply_to_user']:
                        return data['reply_to_user']
                    if data.get('action') == 'final_answer' and 'content' in data:
                        return data['content']
                    if 'content' in data and data['content']:
                        return data['content']
        except Exception:
            pass

        return text_clean.strip() or text.strip()

    # ========== 唤醒词检测 ==========

    def _is_wake_word(self, text: str) -> bool:
        """
        唤醒词检测

        Args:
            text: 要检测的文本

        Returns:
            是否是唤醒词
        """
        text_normalized = text.lower().replace(" ", "").replace("，", "").replace("。", "")

        for wake in self.wake_words:
            wake_normalized = wake.lower().replace(" ", "")

            # 精确匹配
            if wake_normalized in text_normalized:
                return True

            # 模糊匹配
            if abs(len(wake_normalized) - len(text_normalized)) <= 2:
                import difflib
                ratio = difflib.SequenceMatcher(None, wake_normalized, text_normalized).ratio()
                if ratio > 0.9:
                    return True

        return False

    def is_wake_word(self, text: str) -> bool:
        """公开接口：检查是否是唤醒词"""
        return self._is_wake_word(text)

    # ========== 唤醒状态管理 ==========

    def _set_awake(self, state: bool, enter_talk_mode: bool = False):
        """设置唤醒状态"""
        with self._state_lock:
            self.awake = state

            if state:
                self._awake_by_ptt = False
                self._reset_awake_timer()

                with self._talk_mode_lock:
                    if enter_talk_mode:
                        self.in_talk_mode = True
                        self._talk_mode_round = 0
                        self._last_user_speak_time = time.time()
            else:
                self._cancel_awake_timer()
                with self._talk_mode_lock:
                    self.in_talk_mode = False
                    self._talk_mode_round = 0

        # 状态同步
        try:
            state_sync = get_voice_state_sync()
            if state:
                state_sync.on_wake()
            else:
                state_sync.on_sleep()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

    def _reset_awake_timer(self):
        """重置唤醒定时器"""
        self._start_awake_timer(self.awake_timeout)

    def _start_awake_timer(self, timeout: float):
        """启动唤醒定时器"""
        with self._timer_lock:
            if self._awake_timer is not None:
                self._awake_timer.cancel()

            self._awake_timer = threading.Timer(timeout, self._timeout_sleep)
            self._awake_timer.daemon = True
            self._awake_timer.start()

    def _cancel_awake_timer(self):
        """取消唤醒定时器"""
        with self._timer_lock:
            if self._awake_timer is not None:
                self._awake_timer.cancel()
                self._awake_timer = None

    def _timeout_sleep(self):
        """超时后自动休眠"""
        with self._state_lock:
            with self._talk_mode_lock:
                in_talk_mode_now = self.in_talk_mode

            if in_talk_mode_now:
                silence_time = time.time() - self._last_user_speak_time
                if silence_time >= self._talk_mode_silence_threshold:
                    self._talk_mode_round += 1
                    if self._talk_mode_round >= self._talk_mode_max_round:
                        self.exit_talk_mode(reason="max_rounds")
                    else:
                        prompts = [
                            "还有什么可以帮您的吗？",
                            "还有其他问题吗？",
                            "需要我继续帮忙吗？",
                        ]
                        prompt = prompts[self._talk_mode_round % len(prompts)]
                        self.speak(prompt, is_system=True, priority=1)
                        self._last_user_speak_time = time.time()
                        self._reset_awake_timer()
                    return
                else:
                    self._reset_awake_timer()
                    return

            self.awake = False
            self._awake_by_ptt = False
            print("⏳ 唤醒超时，进入休眠")

        # 状态同步
        try:
            state_sync = get_voice_state_sync()
            state_sync.on_sleep()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

    # ========== Talk Mode ==========

    def enter_talk_mode(self):
        """进入Talk Mode"""
        from voice.voice_prompts import SystemAnnouncements
        logger.info("[VoiceInterfaceModelBus] 进入连续对话模式")
        self._set_awake(True, enter_talk_mode=True)
        self.speak(SystemAnnouncements.CONVERSATION_MODE_ON, is_system=True, priority=0)

    def exit_talk_mode(self, reason: str = "timeout"):
        """退出Talk Mode"""
        from voice.voice_prompts import SystemAnnouncements
        with self._talk_mode_lock:
            if not self.in_talk_mode:
                return

            logger.info(f"[VoiceInterfaceModelBus] 退出连续对话模式，原因: {reason}")
            self.in_talk_mode = False

            if reason == "timeout":
                self.speak(SystemAnnouncements.CONVERSATION_TIMEOUT, is_system=True)
            elif reason == "user_exit":
                self.speak(SystemAnnouncements.CONVERSATION_GOODBYE, is_system=True)
            elif reason == "max_rounds":
                self.speak(SystemAnnouncements.CONVERSATION_REST, is_system=True)

        # 延迟休眠
        threading.Timer(3.0, lambda: self._set_awake(False)).start()

    def _is_exit_talk_mode_command(self, text: str) -> bool:
        """检测退出命令"""
        exit_words = ["再见", "拜拜", "结束", "退出", "没有了", "谢谢", "退下", "休息"]
        return any(word in text.lower() for word in exit_words)

    def _is_enter_talk_mode_command(self, text: str) -> bool:
        """检测进入命令"""
        enter_words = ["进入对话模式", "连续对话", "聊聊", "我们聊聊", "对话模式"]
        text_normalized = text.lower().replace(" ", "").replace("，", "").replace("。", "")
        return any(word in text_normalized for word in enter_words)

    # ========== PTT模式 ==========

    def start_ptt_session(self):
        """开始PTT会话"""
        self.push_to_talk = True
        self._ptt_session_active = True
        self.awake = True
        self._awake_by_ptt = True
        self._cancel_awake_timer()

        try:
            state_sync = get_voice_state_sync()
            state_sync.on_start_listening()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

        print("[MIC] 进入免唤醒模式")

    def end_ptt_session(self):
        """结束PTT会话"""
        self._ptt_session_active = False

        try:
            state_sync = get_voice_state_sync()
            state_sync.on_stop_listening()
        except Exception as e:
            logger.error(f"[VoiceInterfaceModelBus] 状态同步失败: {e}")

        def delayed_sleep():
            time.sleep(self.ptt_timeout)
            if not self._ptt_session_active:
                self.push_to_talk = False
                if self._awake_by_ptt:
                    self.awake = False
                    self._awake_by_ptt = False
                    print("⏳ 免唤醒会话结束")
                    try:
                        state_sync = get_voice_state_sync()
                        state_sync.on_sleep()
                    except Exception:
                        pass

        threading.Thread(target=delayed_sleep, daemon=True).start()

    # ========== 监听控制（占位） ==========

    def start(self):
        """启动语音监听（占位，实际监听由外部处理）"""
        logger.info("[VoiceInterfaceModelBus] start() 被调用（占位）")
        # ModelBus架构下，监听逻辑可能由专门的Provider处理
        # 这里保持接口兼容
        self.is_listening = True

    def stop(self):
        """停止语音监听"""
        logger.info("[VoiceInterfaceModelBus] stop() 被调用")
        self.is_listening = False

    def close(self):
        """关闭语音接口"""
        logger.info("[VoiceInterfaceModelBus] 关闭语音接口...")

        self.stop()

        # 停止播报线程
        self._speak_queue.put_stop_signal()
        if self._speak_thread and self._speak_thread.is_alive():
            self._speak_thread.join(timeout=2)

        # 停止事件循环
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=1)

        # 清理适配器
        if self._adapter:
            asyncio.run_coroutine_threadsafe(
                self._adapter.cleanup(),
                self.loop
            )

        logger.info("[VoiceInterfaceModelBus] 语音接口已关闭")

    # ========== 健康检查 ==========

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        if not self._initialized:
            return {"initialized": False, "status": "未初始化"}

        return await self._adapter.health_check()
