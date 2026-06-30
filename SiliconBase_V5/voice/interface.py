#!/usr/bin/env python3
# voice/interface.py
import asyncio
import contextlib
import difflib
import gc
import json
import os
import queue
import random
import sys
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import pyaudio
from vosk import KaldiRecognizer, Model

from core.config import config
from core.dialog.dialogue_manager import InputMode, dialogue_manager
from core.exceptions import TTSInitError, VoiceInitError, VoiceSpeakError
from core.global_state import clear_session_history
from core.logger import logger
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线
from voice.protected_speak_queue import ProtectedSpeakQueue
from voice.state_sync import get_voice_state_sync
from voice.wake_word_handler import WakeWordHandler


def _safe_print(*args, **kwargs):
    """防御性打印：即使 stdout/stderr 已关闭也不崩进程"""
    with contextlib.suppress(ValueError, OSError):
        print(*args, **kwargs)

# Piper TTS 导入
try:
    from piper import PiperVoice
    PIPER_TTS_AVAILABLE = True
except ImportError as e:
    PIPER_TTS_AVAILABLE = False
    logger.error(f"[Voice] Piper TTS 导入失败: {e}", exc_info=True)

class VoiceInterface:
    """
    语音接口类，负责流式语音识别与合成，并与对话管理器交互。
    支持：
      - 流式语音识别（Vosk）
      - 流式语音合成（Pocket TTS / edge-tts / pyttsx3）
      - 唤醒词检测（含部分结果）
      - 语音打断
      - 异步回调处理
      - 唤醒状态机（仅唤醒后响应指令）
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

    def __init__(self, tts_engine=None, speaker_wav=None, output_dir="outputs"):
        if self._initialized:
            return
        self.tts_engine = tts_engine
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        # 默认音色参考音频
        self.speaker_wav = speaker_wav

        # ---------- 【Thread-Safety-Fixer】线程锁保护共享状态 ----------
        self._vosk_lock = threading.Lock()  # 保护_vosk_loaded
        self._timer_lock = threading.Lock()  # 保护_awake_timer
        self._state_lock = threading.Lock()  # 保护is_listening等状态

        # ---------- 初始化 TTS 引擎 ----------
        self._piper_voice = None
        self._fallback_engine = None  # 备用TTS引擎
        self._init_piper_tts()

        # ---------- 唤醒词 ----------
        # P0-005 Fix: 统一配置键为 voice.wake_words（复数形式）
        # 向后兼容：如果旧键 wake_word 存在，给出 deprecation 警告但继续工作
        wake_words = config.get("voice.wake_words")
        _safe_print(f"[WakeWord] 从配置读取 voice.wake_words: {wake_words}")

        if wake_words is None:
            # 尝试读取旧键
            old_wake_word = config.get("wake_word")
            _safe_print(f"[WakeWord] 尝试读取旧键 wake_word: {old_wake_word}")
            if old_wake_word is not None:
                import warnings
                warnings.warn(
                    "配置项 'wake_word' 已弃用，请使用 'voice.wake_words'（列表格式）替代",
                    DeprecationWarning,
                    stacklevel=2
                )
                logger.warning("[Config] 'wake_word' is deprecated, use 'voice.wake_words' instead")
                # 将旧值转换为列表格式
                wake_words = [old_wake_word] if isinstance(old_wake_word, str) else old_wake_word
                _safe_print(f"[WakeWord] 旧配置转换为列表: {wake_words}")
            else:
                wake_words = ["硅基"]
                _safe_print(f"[WakeWord] 使用默认唤醒词: {wake_words}")
        self.wake_words = wake_words

        # 类型检查：确保 wake_words 是列表而非字符串
        # 如果是字符串，遍历时会变成单个字符，导致唤醒词无法正确匹配
        if isinstance(self.wake_words, str):
            _safe_print(f"[WakeWord] [WARN] 唤醒词是字符串而非列表: '{self.wake_words}'，转换为列表")
            self.wake_words = [self.wake_words]

        _safe_print(f"[唤醒词] 【成功】 最终唤醒词配置: {self.wake_words}")

        # ---------- TTS 引擎类型（仅用于初始化时打印，实际使用动态读取）----------
        self.tts_engine_type = config.get("voice.tts_engine", "piper")
        _safe_print(f"[Voice] 初始 TTS 引擎: {self.tts_engine_type}")

        # ---------- 流式识别相关 ----------
        self.vosk_model = None
        self.recognizer = None
        self._is_listening = False  # 【Thread-Safety-Fixer】改为内部私有变量
        self._listen_thread = None
        self._vosk_loading = False
        self._vosk_loaded = False
        # 异步加载 Vosk，避免阻塞主线程
        self._init_vosk_async()

        # ---------- 异步事件循环 ----------
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        # ---------- 备用 TTS ----------
        self._fallback_engine = None
        self._fallback_lock = threading.Lock()
        self._init_fallback()

        # 播放队列（用于异步播放备用 TTS）
        self._play_queue = queue.Queue()
        self._play_thread = threading.Thread(target=self._player_worker, daemon=True)
        self._play_thread.start()

        # ---------- 语音播报队列（避免多个播报重叠）----------
        self._speak_queue = ProtectedSpeakQueue()  # 使用受保护播报队列
        self._speak_thread = threading.Thread(target=self._speak_worker, daemon=True)
        self._speak_thread.start()
        self._current_speak_priority = 0   # 当前播报优先级（0=最高AI输出，1=系统，2=最低过程播报）
        self._current_speak_protected = False  # 当前播报是否受保护

        # 【TTS音频流冲突修复】串行播放锁 - 确保音频设备一次只被一个播报占用
        self._playback_lock = threading.Lock()

        # 【修复代理-11】平滑中断机制
        self._should_stop_current = False  # 中断标志：高优先级打断低优先级时使用

        # ---------- 流式合成相关 ----------
        self._pyaudio = pyaudio.PyAudio()
        self._audio_stream = None
        self._stream_lock = threading.Lock()
        self.is_speaking = False
        self.speaking_lock = threading.RLock()  # 【修复】使用可重入锁避免死锁
        self._stop_event = None
        self._is_system_speaking = False  # 标记是否在播放系统音（避免回声识别）
        self._last_spoken_text = ""       # 最近播报的文本（用于回声检测）
        self._last_speak_time = 0         # 最近播报时间
        self._last_speak_end_time = 0.0   # 最近播报结束时间（回声消除冷却）

        # ---------- 唤醒状态 ----------
        self.awake = False                 # 当前是否处于唤醒状态
        self.awake_timeout = config.get("voice.awake_timeout", 300)  # 唤醒后自动休眠秒数（默认5分钟）
        self._awake_timer = None            # 超时定时器
        self._awake_by_ptt = False         # [P0-006 Fix] 标记awake状态是否由PTT设置

        # 【Talk Mode】连续对话模式状态
        self.in_talk_mode = False           # 是否处于Talk Mode
        self._talk_mode_round = 0           # 对话轮数
        self._talk_mode_max_round = 10      # 最大对话轮数
        self._talk_mode_silence_threshold = 8.0  # 静默检测阈值（秒）
        self._last_user_speak_time = 0      # 上次用户说话时间
        self._talk_mode_prompts = [         # 主动询问提示语
            "还有什么可以帮您的吗？",
            "还有其他问题吗？",
            "需要我继续帮忙吗？",
            "您还想了解什么？"
        ]

        # ---------- 免唤醒模式（前端控制）----------
        self.push_to_talk = False          # 是否处于免唤醒模式（前端点击录音）
        self._ptt_session_active = False   # 当前是否有活跃的PTT会话
        self.ptt_timeout = config.get("voice.ptt_timeout", 60)  # PTT模式超时时间（对话结束后保持时间）

        # ---------- SystemState 反射弧订阅 ----------
        self._system_state_initialized = False
        self._init_system_state_subscriptions()

        # 语音识别回调
        self.callback_on_result = None

        # ---------- 线程健康检查（Thread-Fixer修复）----------
        self._init_thread_health()
        self._health_check_stop_event = threading.Event()  # 【蓝屏修复】健康检查线程停止事件

        # ---------- 关联 dialogue_manager.voice 实例 ----------
        dialogue_manager.voice = self
        _safe_print(f"[WakeWord] DialogueManager voice实例已关联: {dialogue_manager.voice is not None}")

        # 【修复】初始化语音播报去重器（哈希表去重，避免单槽互相冲刷）
        self._speak_dedup = {
            'last_hash': None,
            'last_time': 0,
            'repeat_count': {},
            'window_seconds': 30,  # 30秒去重窗口
            'history': {}  # 按 text_hash 存储最近播报时间
        }

        # 【P1 Fix】初始化语音播报去重属性（5秒间隔去重）
        self._last_announce_text = ""      # 上次播报的文本
        self._last_announce_time = 0       # 上次播报的时间戳

        # 【Phase 1 Week 1 - Bug修复】初始化唤醒词处理器
        self._wake_word_handler = WakeWordHandler(self.wake_words)
        _safe_print("[WakeWord] WakeWordHandler已初始化")

        # 【修复代理-16】添加 Talk Mode 锁
        self._talk_mode_lock = threading.Lock()  # Talk Mode状态锁
        _safe_print("[TalkMode] Talk Mode锁已初始化")

        # 【BUG-4修复】AI回复期间用户输入缓存队列
        # 当AI正在播报时，用户说话内容被缓存，待播报结束后处理
        self._input_buffer = queue.Queue()  # 输入缓存队列
        self._input_buffer_lock = threading.Lock()  # 缓存队列锁
        self._input_buffer_stop_event = threading.Event()  # 线程停止事件（线程安全）
        self._input_buffer_processing = False  # 是否正在处理缓存（用于启动时检查）
        self._input_buffer_thread = None  # 缓存处理线程
        _safe_print("[Voice] 输入缓存队列已初始化")

        # 【Fix】只有全部初始化成功后才标记为已初始化，避免部分初始化导致属性缺失
        self._initialized = True

    # ========== 【Thread-Safety-Fixer】使用property保护共享状态 ==========

    @property
    def vosk_loaded(self) -> bool:
        """线程安全地获取_vosk_loaded状态"""
        with self._vosk_lock:
            return self._vosk_loaded

    @vosk_loaded.setter
    def vosk_loaded(self, value: bool):
        """线程安全地设置_vosk_loaded状态"""
        with self._vosk_lock:
            self._vosk_loaded = value

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

    def _cancel_awake_timer(self):
        """【Thread-Safety-Fixer】原子操作取消定时器"""
        with self._timer_lock:
            if self._awake_timer is not None:
                self._awake_timer.cancel()
                self._awake_timer = None

    def _start_awake_timer(self, timeout: float = None):
        """【Thread-Safety-Fixer】原子操作启动定时器"""
        if timeout is None:
            timeout = self.awake_timeout

        with self._timer_lock:
            # 先取消旧定时器
            if self._awake_timer is not None:
                self._awake_timer.cancel()

            # 启动新定时器
            self._awake_timer = threading.Timer(timeout, self._timeout_sleep)
            self._awake_timer.daemon = True
            self._awake_timer.start()

    # ========== Thread-Fixer: 线程健康检查和自动重启机制 ==========

    def _init_thread_health(self):
        """初始化线程健康检查相关属性"""
        # 线程控制
        self._listen_restart_enabled = True
        self._listen_restart_interval = 5  # 健康检查间隔(秒)
        self._listen_consecutive_errors = 0
        self._listen_max_consecutive_errors = 10  # 熔断阈值
        self._listen_health_check_thread = None
        self._listen_lock = threading.Lock()

    def _start_listen_thread(self) -> bool:
        """
        启动监听线程（内部方法）

        Returns:
            bool: 是否成功启动
        """
        with self._listen_lock:
            # 清理已死亡的线程引用
            if self._listen_thread and not self._listen_thread.is_alive():
                self._listen_thread = None

            # 如果线程已运行，不需要重复启动
            if self._listen_thread and self._listen_thread.is_alive():
                return True

            self.is_listening = True
            self._listen_consecutive_errors = 0
            self._listen_thread = threading.Thread(
                target=self._listen_loop_wrapper,
                daemon=True
            )
            self._listen_thread.start()
            _safe_print("[Voice] 语音监听线程已启动")
            return True

    def _listen_loop_wrapper(self):
        """
        监听循环包装器，增加异常捕获和状态管理
        """
        try:
            self._listen_loop()
        except Exception as e:
            _safe_print(f"[Voice] [FATAL] 监听线程异常退出: {e}")
            traceback.print_exc()
        finally:
            _safe_print("[Voice] 监听线程已退出")
            # 【Thread-Safety-Fixer】确保标志被重置（通过property）
            with self._state_lock:
                self._is_listening = False

    def _listen_health_checker(self):
        """
        健康检查线程 - 自动重启监听线程
        独立运行，定期检查监听线程状态
        【Thread-Safety-Fixer】使用线程安全的方式访问共享状态
        【蓝屏修复】添加停止事件检查，确保线程能正确退出
        """
        _safe_print("[Voice] 健康检查线程已启动")

        while not self._health_check_stop_event.is_set():
            time.sleep(self._listen_restart_interval)

            # 如果禁用了自动重启，跳过检查
            if not getattr(self, '_listen_restart_enabled', False):
                continue

            with self._listen_lock:
                thread_alive = self._listen_thread and self._listen_thread.is_alive()

            # 【Thread-Safety-Fixer】使用property访问is_listening和vosk_loaded
            should_be_listening = self.is_listening
            vosk_ready = self.vosk_loaded

            # 检查是否需要重启
            if should_be_listening and not thread_alive and vosk_ready:
                _safe_print("[Voice] [WARN] 检测到监听线程异常退出，准备自动重启...")
                try:
                    self._start_listen_thread()
                except Exception as e:
                    logger.error(f"[Voice] 自动重启失败: {e}", exc_info=True)

    def _wait_for_vosk_loaded(self, timeout=60) -> bool:
        """
        【Thread-Safety-Fixer】等待 Vosk 模型加载完成 - 使用线程安全的访问方式

        Args:
            timeout: 最大等待时间(秒)

        Returns:
            bool: 是否加载成功
        """
        wait_interval = 2
        total_wait = 0

        _safe_print("[Voice] 等待 Vosk 模型加载...")
        # 【Thread-Safety-Fixer】使用线程安全的属性访问
        while (not self.vosk_loaded and
               getattr(self, '_vosk_loading', False) and
               total_wait < timeout):
            time.sleep(wait_interval)
            total_wait += wait_interval
            _safe_print(f"[Voice] 模型加载中... 已等待 {total_wait} 秒")

        if not self.vosk_loaded:
            if getattr(self, '_vosk_loading', False):
                _safe_print(f"[Voice] 错误: Vosk 模型加载超时（{timeout}秒）")
            else:
                _safe_print("[Voice] 错误: Vosk 模型加载失败")
            return False

        return True

    def restart_listen_thread(self) -> bool:
        """
        手动重启监听线程

        Returns:
            bool: 是否成功重启
        """
        _safe_print("[Voice] 手动重启监听线程...")
        self.stop()
        time.sleep(0.5)
        return self.start()

    def reset_error_counter(self):
        """重置连续错误计数器"""
        self._listen_consecutive_errors = 0
        _safe_print("[Voice] 错误计数器已重置")

    def get_listen_thread_status(self):
        """
        【Thread-Safety-Fixer】获取监听线程状态，用于监控和调试 - 使用线程安全访问

        Returns:
            dict: 包含线程状态的详细信息
        """
        with getattr(self, '_listen_lock', threading.Lock()):
            thread_alive = (self._listen_thread.is_alive()
                          if self._listen_thread else False)

        # 【Thread-Safety-Fixer】使用线程安全的方式访问共享状态
        return {
            "is_listening": self.is_listening,
            "thread_exists": self._listen_thread is not None,
            "thread_alive": thread_alive,
            "vosk_loaded": self.vosk_loaded,
            "vosk_loading": getattr(self, '_vosk_loading', False),
            "consecutive_errors": getattr(self, '_listen_consecutive_errors', 0),
            "restart_enabled": getattr(self, '_listen_restart_enabled', False),
            "health_check_alive": (
                self._listen_health_check_thread.is_alive()
                if getattr(self, '_listen_health_check_thread', None)
                else False
            ),
        }

    def _init_piper_tts(self):
        """初始化 Piper TTS 模型（增强版，带完整错误处理和备用引擎切换）"""
        self._piper_voice = None

        if not PIPER_TTS_AVAILABLE:
            _safe_print("[Voice] Piper TTS 不可用，将使用备用引擎")
            self._ensure_fallback_engine()
            return

        try:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent

            # 从配置读取模型路径，并基于项目根目录解析
            model_rel_path = config.get("voice.piper.model_path", "assets/models/piper/zh_CN-huayan-medium.onnx")
            config_rel_path = config.get("voice.piper.config_path", "assets/models/piper/zh_CN-huayan-medium.onnx.json")

            model_path = str(project_root / model_rel_path)
            config_path = str(project_root / config_rel_path)

            # [修复] 详细的模型文件检查
            model_exists = os.path.exists(model_path)
            config_exists = os.path.exists(config_path)

            if not model_exists and not config_exists:
                logger.error(f"[Voice] Piper TTS 模型文件不存在! 模型路径: {model_path}, 配置文件: {config_path}")
                _safe_print("[Voice] [TIP] 请从 https://github.com/rhasspy/piper/releases 下载中文语音模型")
                _safe_print("[Voice] [TIP] 推荐模型: zh_CN-huayan-medium")
                self._ensure_fallback_engine()
                return

            if not model_exists:
                logger.error(f"[Voice] Piper 模型文件不存在: {model_path}")
                _safe_print("[Voice] [TIP] 请下载模型文件 (.onnx)")
                self._ensure_fallback_engine()
                return

            if not config_exists:
                logger.error(f"[Voice] Piper 配置文件不存在: {config_path}")
                _safe_print("[Voice] [TIP] 请下载配置文件 (.json)")
                self._ensure_fallback_engine()
                return

            _safe_print("[语音] 【成功】 Piper 模型文件检查通过")
            _safe_print(f"[Voice] 正在加载 Piper TTS 模型: {model_path}")
            self._piper_voice = PiperVoice.load(model_path, config_path)
            _safe_print("[语音] 【成功】 Piper TTS 初始化完成")

        except ImportError as e:
            logger.error(f"[Voice] Piper TTS 导入失败: {e}", exc_info=True)
            self._piper_voice = None
            self._ensure_fallback_engine()
        except FileNotFoundError as e:
            logger.error(f"[Voice] Piper TTS 文件未找到: {e}", exc_info=True)
            self._piper_voice = None
            self._ensure_fallback_engine()
        except Exception as e:
            logger.error(f"[Voice] Piper TTS 初始化失败: {e}", exc_info=True)
            self._piper_voice = None
            self._ensure_fallback_engine()

    def _ensure_fallback_engine(self):
        """确保备用 TTS 引擎已初始化"""
        if not self._fallback_engine:
            _safe_print("[Voice] 正在初始化备用 TTS 引擎...")
            self._init_fallback(force_reinit=True)
            if self._fallback_engine:
                _safe_print("[语音] 【成功】 备用 TTS 引擎初始化成功")
            else:
                _safe_print("[Voice] [WARN] 备用 TTS 引擎不可用，语音功能将降级为文本输出")

    def reload_piper_model(self):
        """
        重新加载Piper TTS模型以释放累积内存
        适用于长时间运行后的内存优化
        """
        _safe_print("[Voice] 重新加载Piper TTS模型以释放内存...")
        try:
            # 清理现有模型
            self._piper_voice = None
            gc.collect()

            # 重新初始化
            self._init_piper_tts()

            if self._piper_voice:
                _safe_print("[语音] 【成功】 Piper TTS模型重新加载成功")
                return True
            else:
                _safe_print("[Voice] [WARN] Piper TTS模型重新加载失败，将使用备用引擎")
                return False
        except Exception as e:
            logger.error(f"[Voice] 重新加载Piper模型失败: {e}", exc_info=True)
            return False

    def _init_vosk_async(self):
        """异步初始化 Vosk 语音识别模型（不阻塞主线程）- [修复] 增强模型文件检查"""
        model_path = config.get("voice.model_path", "assets/models/vosk-model-cn-0.22")

        # [修复] 详细的模型文件检查
        if not os.path.exists(model_path):
            logger.error(f"[Voice] Vosk 模型路径不存在: {model_path}")
            _safe_print("[Voice] [TIP] 语音识别功能将不可用，但语音合成仍可正常工作")
            _safe_print("[Voice] [TIP] 请从 https://alphacephei.com/vosk/models 下载中文模型")
            _safe_print(f"[Voice] [TIP] 解压到: {model_path}")
            # 【Thread-Safety-Fixer】使用property设置vosk_loaded
            self.vosk_loaded = False
            self._vosk_loading = False
            return

        # [修复] 检查关键模型文件是否存在
        # Vosk 模型使用两种解码图格式之一：
        # 1. HCLG.fst (单文件解码图 - 标准模型)
        # 2. HCLr.fst + Gr.fst (重打分模式 - 高级模型)
        required_files = ["am/final.mdl"]  # 声学模型是必须的
        missing_files = []
        for req_file in required_files:
            full_path = os.path.join(model_path, req_file)
            if not os.path.exists(full_path):
                missing_files.append(req_file)

        # 检查解码图文件（HCLG.fst 或 HCLr.fst+Gr.fst 至少一种）
        has_hclg = os.path.exists(os.path.join(model_path, "graph/HCLG.fst"))
        has_hclr_gr = os.path.exists(os.path.join(model_path, "graph/HCLr.fst")) and \
                      os.path.exists(os.path.join(model_path, "graph/Gr.fst"))

        if missing_files:
            logger.error(f"[Voice] Vosk 模型文件不完整! 缺失文件: {', '.join(missing_files)}")
            # 【Thread-Safety-Fixer】使用property设置vosk_loaded
            self.vosk_loaded = False
            self._vosk_loading = False
            return

        if not (has_hclg or has_hclr_gr):
            logger.error("[Voice] Vosk 模型缺少解码图文件! 需要 graph/HCLG.fst 或 graph/HCLr.fst+Gr.fst")
            # 【Thread-Safety-Fixer】使用property设置vosk_loaded
            self.vosk_loaded = False
            self._vosk_loading = False
            return

        if has_hclg:
            _safe_print("[Voice] 检测到标准解码图 (HCLG.fst)")
        else:
            _safe_print("[Voice] 检测到重打分解码图 (HCLr.fst + Gr.fst)")

        self._vosk_loading = True
        _safe_print("[Voice] Vosk 模型文件检查通过，正在后台加载中...")

        def load_model():
            # 【修正】Vosk C++ 扩展直接写底层 fd，Python 层 sys.stdout 重定向无效。
            # 且若此时发生 segfault，faulthandler 会将 traceback 写入 devnull 导致看不到。
            # 因此移除重定向，让日志正常输出。
            try:
                self.vosk_model = Model(model_path)
                self.recognizer = KaldiRecognizer(self.vosk_model, 16000)
                self.recognizer.SetWords(True)
                # 【Thread-Safety-Fixer】使用property设置vosk_loaded
                self.vosk_loaded = True
            except Exception as e:
                logger.error(f"[Voice] Vosk 模型加载失败: {e}", exc_info=True)
                # 【Thread-Safety-Fixer】使用property设置vosk_loaded
                self.vosk_loaded = False
            finally:
                self._vosk_loading = False
                if self.vosk_loaded:
                    _safe_print("[语音] 【成功】 Vosk 语音识别模型加载成功")

        # 在后台线程加载模型
        threading.Thread(target=load_model, daemon=True).start()
        _safe_print("[WakeWord] Vosk模型加载线程已启动")

    def _ensure_vosk_loaded(self, timeout=5):
        """【Thread-Safety-Fixer】确保 Vosk 模型已加载，返回是否成功 - 使用线程安全访问"""
        # 【Thread-Safety-Fixer】使用property访问vosk_loaded
        if self.vosk_loaded:
            return True
        if not self._vosk_loading:
            return False

        # 等待加载完成
        import time
        start = time.time()
        while self._vosk_loading and time.time() - start < timeout:
            time.sleep(0.1)
        return self.vosk_loaded

    def _init_vosk(self):
        """初始化 Vosk 语音识别模型（同步版本，已弃用）"""
        # 已改为异步加载，此方法保留用于兼容
        pass

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            _safe_print(f"[FATAL] voice.loop 异常退出: {e}")
            traceback.print_exc()

    def _init_fallback(self, force_reinit=False):
        if force_reinit and self._fallback_engine:
            self._fallback_engine.stop()
            self._fallback_engine = None
        if self._fallback_engine and not force_reinit:
            return
        try:
            import pyttsx3
            self._fallback_engine = pyttsx3.init()
            self._fallback_engine.setProperty('rate', 180)
            self._fallback_engine.setProperty('volume', 0.9)

            voices = self._fallback_engine.getProperty('voices')
            chinese_voice_found = False
            for voice in voices:
                if 'hui' in voice.name.lower() or 'chinese' in voice.languages.__str__().lower():
                    self._fallback_engine.setProperty('voice', voice.id)
                    _safe_print(f"[Voice] 备用引擎已选择中文语音: {voice.name}")
                    chinese_voice_found = True
                    break
            if not chinese_voice_found:
                _safe_print("[Voice] 警告：未找到中文语音包，备用引擎将使用默认语音（可能为英文）。")
        except ImportError as e:
            self._fallback_engine = None
            logger.error(f"[Voice] 备用 TTS 引擎 pyttsx3 未安装: {e}", exc_info=True)
        except Exception as e:
            self._fallback_engine = None
            logger.error(f"[Voice] pyttsx3 初始化失败: {e}", exc_info=True)

    def start(self):
        """
        【Thread-Safety-Fixer】启动语音监听（Thread-Fixer增强版）
        - 集成线程健康检查
        - 自动重启机制
        - 使用线程安全的状态访问
        """
        _safe_print("[WakeWord] 启动语音监听...")
        # 【Thread-Safety-Fixer】使用property访问vosk_loaded
        _safe_print(f"[WakeWord] Vosk模型加载状态: vosk_loaded={self.vosk_loaded}, _vosk_loading={self._vosk_loading}")
        _safe_print(f"[WakeWord] 当前监听状态: is_listening={self.is_listening}")

        # 如果线程已在运行，不需要重复启动
        if self._listen_thread and self._listen_thread.is_alive():
            _safe_print("[Voice] 监听线程已在运行")
            return

        # 等待 Vosk 模型加载完成
        _safe_print("[WakeWord] 等待 Vosk 模型加载完成...")
        if not self._wait_for_vosk_loaded(timeout=60):
            _safe_print("[Voice] 系统将禁用语音功能，仅支持文本交互")
            return

        _safe_print("[唤醒词] 【成功】 Vosk 模型加载完成，继续启动语音监听")
        _safe_print(f"[WakeWord] 唤醒词配置: {self.wake_words}")

        # 启用自动重启
        self._listen_restart_enabled = True

        # 启动监听线程（使用包装器）
        self._start_listen_thread()

        # 启动健康检查线程（如果未运行）
        if (not self._listen_health_check_thread or
            not self._listen_health_check_thread.is_alive()):
            self._listen_health_check_thread = threading.Thread(
                target=self._listen_health_checker,
                daemon=True
            )
            self._listen_health_check_thread.start()

        _safe_print("[Voice] 语音监听已启动（含自动重启保护）")

    def stop(self):
        """
        停止语音监听（Thread-Fixer增强版）
        - 禁用自动重启
        - 清理资源
        - 【蓝屏修复】停止健康检查线程
        """
        _safe_print("[Voice] 正在停止语音监听...")

        # 禁用自动重启（Thread-Fixer）
        if hasattr(self, '_listen_restart_enabled'):
            self._listen_restart_enabled = False

        # 【蓝屏修复】停止健康检查线程
        if hasattr(self, '_health_check_stop_event'):
            self._health_check_stop_event.set()
        if hasattr(self, '_listen_health_check_thread') and self._listen_health_check_thread:
            self._listen_health_check_thread.join(timeout=2)
            # 【静默失败修复】验证线程是否真正停止
            if self._listen_health_check_thread.is_alive():
                logger.error("[Voice] 健康检查线程未在2秒内停止，可能存在资源泄漏")
            else:
                _safe_print("[Voice] 健康检查线程已停止")

        self.is_listening = False

        # 等待线程结束（增加超时时间）
        with self._listen_lock:
            if self._listen_thread and self._listen_thread.is_alive():
                self._listen_thread.join(timeout=3)
                # 【静默失败修复】验证线程是否真正停止
                if self._listen_thread.is_alive():
                    logger.error("[Voice] 监听线程未在3秒内停止，可能存在死锁或资源泄漏")
        self._play_queue.put(None)
        if self._fallback_engine:
            self._fallback_engine.stop()
        with self._stream_lock:
            if self._audio_stream:
                try:
                    self._audio_stream.stop_stream()
                    self._audio_stream.close()
                except Exception as e:
                    logger.error(f"[Voice] 停止音频流失败: {e}", exc_info=True)
                self._audio_stream = None
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception as e:
                logger.error(f"[Voice] 终止 PyAudio 失败: {e}", exc_info=True)
            self._pyaudio = None

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            time.sleep(0.1)
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=1)
            try:
                self.loop.close()
            except Exception as e:
                logger.error(f"[Voice] 关闭事件循环失败: {e}", exc_info=True)

    def close(self):
        """
        关闭语音接口，释放所有资源（内存泄漏修复）

        这是标准的资源释放方法，应在程序退出或不再需要语音功能时调用。
        包含以下清理操作:
        1. 停止语音监听
        2. 停止播报并清空队列
        3. 关闭音频流
        4. 终止PyAudio
        5. 停止事件循环
        6. 等待线程结束
        """
        _safe_print("[Voice] 正在关闭语音接口...")

        try:
            # 1. 停止语音监听（会禁用自动重启）
            self.stop()

            # 1.1 【蓝屏修复】停止输入缓存处理线程
            self.stop_input_buffer_processing()

            # 2. 等待播放线程结束
            if self._play_thread and self._play_thread.is_alive():
                self._play_queue.put(None)  # 发送结束信号
                self._play_thread.join(timeout=2)

            # 3. 等待播报线程结束
            if self._speak_thread and self._speak_thread.is_alive():
                self._speak_queue.put_stop_signal()  # 发送结束信号（ProtectedSpeakQueue无put方法）
                self._speak_thread.join(timeout=2)

            # 4. 释放所有音频资源
            self.release_all_resources()

            # 5. 清理Vosk模型
            if self.vosk_model:
                try:
                    # Vosk模型没有显式关闭方法，设为None让GC回收
                    self.vosk_model = None
                    self.recognizer = None
                    _safe_print("[Voice] Vosk模型已释放")
                except Exception as e:
                    logger.error(f"[Voice] 释放Vosk模型失败: {e}", exc_info=True)

            # 6. 清理Piper TTS
            if self._piper_voice:
                try:
                    self._piper_voice = None
                    import gc
                    gc.collect()
                    _safe_print("[Voice] Piper TTS已释放")
                except Exception as e:
                    logger.error(f"[Voice] 释放Piper TTS失败: {e}", exc_info=True)

            _safe_print("[Voice] 语音接口已完全关闭")

        except Exception as e:
            logger.error(f"[Voice] 关闭语音接口时发生错误: {e}", exc_info=True)

    def _is_wake_word(self, text):
        """
        唤醒词检测
        - 优先精确匹配（去除空格）
        - 模糊匹配仅用于处理语音识别误差，阈值设为0.9更严格
        """
        _safe_print(f"[WakeWord] 检测文本: '{text}'")
        _safe_print(f"[WakeWord] 配置唤醒词列表: {self.wake_words}")

        # 去除所有空格，统一处理
        text_normalized = text.lower().replace(" ", "").replace("，", "").replace("。", "")
        _safe_print(f"[WakeWord] 归一化后文本: '{text_normalized}'")

        for wake in self.wake_words:
            wake_normalized = wake.lower().replace(" ", "")
            _safe_print(f"[WakeWord] 检查唤醒词 '{wake}' (归一化: '{wake_normalized}')")

            # 1. 精确包含匹配（去除空格后）
            if wake_normalized in text_normalized:
                _safe_print(f"[唤醒词] 【成功】 精确匹配成功: '{wake}' 在 '{text_normalized}' 中")
                return True

            # 2. 严格模糊匹配（仅用于处理语音识别误差）
            # 只比较长度相近的文本
            if abs(len(wake_normalized) - len(text_normalized)) <= 2:
                ratio = difflib.SequenceMatcher(None, wake_normalized, text_normalized).ratio()
                _safe_print(f"[WakeWord] 模糊匹配相似度: {ratio:.2f} (阈值: 0.9)")
                if ratio > 0.9:  # 提高阈值到0.9，减少误唤醒
                    logger.debug(f"[Voice] 模糊匹配唤醒词（相似度{ratio:.2f}）：{text}")
                    _safe_print(f"[唤醒词] 【成功】 模糊匹配成功: '{wake}' 相似度 {ratio:.2f}")
                    return True

        logger.debug("[Voice] 未匹配任何唤醒词")
        return False

    def stop_speaking(self, clear_unprotected_only=True):
        """
        停止当前播报并清理资源

        Args:
            clear_unprotected_only: 是否只清空未受保护的播报项（保留受保护项）
        """
        with self.speaking_lock:
            # 【Phase 1 Week 1 Fix】检查当前播报是否受保护
            if self._current_speak_protected and clear_unprotected_only:
                logger.warning("[Voice] 当前播报受保护，保留播放")
                # 仍然停止当前播放，但不清空受保护项
                if hasattr(self, '_stop_event') and self._stop_event:
                    self._stop_event.set()
                self.is_speaking = False
                self._cleanup_audio_resources()
                # 只清空未受保护项
                cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=True)
                if cleared > 0:
                    _safe_print(f"[Voice] 播报队列已清空，移除 {cleared} 个待播报项，保留 {protected} 个受保护项")

                # 【状态同步】停止播报
                try:
                    state_sync = get_voice_state_sync()
                    state_sync.on_stop_speaking()
                except Exception as e:
                    logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)
                return

            if hasattr(self, '_stop_event') and self._stop_event:
                self._stop_event.set()
            self.is_speaking = False
            # 清理音频流
            self._cleanup_audio_resources()
            # 【Phase 1 Week 1 Fix】清空播报队列，保留受保护项
            cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=clear_unprotected_only)
            if cleared > 0 or protected > 0:
                _safe_print(f"[Voice] 播报队列已处理，移除 {cleared} 个待播报项，保留 {protected} 个受保护项")

            # 【状态同步】停止播报
            try:
                state_sync = get_voice_state_sync()
                state_sync.on_stop_speaking()
            except Exception as e:
                logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

    def _clear_speak_queue(self, clear_unprotected_only=True):
        """
        清空播报队列

        Args:
            clear_unprotected_only: 是否只清空未受保护的播报项
        """
        try:
            cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=clear_unprotected_only)
            if cleared > 0 or protected > 0:
                _safe_print(f"[Voice] 播报队列已处理，移除 {cleared} 个待播报项，保留 {protected} 个受保护项")
        except Exception as e:
            logger.error(f"[Voice] 清空播报队列失败: {e}", exc_info=True)

    def release_all_resources(self):
        """释放所有音频资源（程序退出时调用）"""
        _safe_print("[Voice] 释放所有音频资源...")

        # 停止播报（退出时清空所有项，包括受保护项）
        self.stop_speaking(clear_unprotected_only=False)

        # 发送停止信号到队列
        try:
            self._speak_queue.put_stop_signal()
        except Exception as e:
            logger.error(f"[Voice] 发送停止信号失败: {e}", exc_info=True)

        # 清理音频资源
        self._cleanup_audio_resources()

        # 终止 PyAudio
        with self._stream_lock:
            if self._pyaudio:
                try:
                    self._pyaudio.terminate()
                    _safe_print("[Voice] PyAudio 已终止")
                except Exception as e:
                    _safe_print(f"[Voice] 终止 PyAudio 失败: {e}")
                finally:
                    self._pyaudio = None

        _safe_print("[Voice] 所有音频资源已释放")

    # ---------- 唤醒状态管理 ----------
    def _set_awake(self, state: bool, enter_talk_mode: bool = False):
        """
        【Thread-Safety-Fixer】设置唤醒状态，并管理超时定时器 - 使用原子操作
        【Talk Mode】支持进入Talk Mode连续对话模式

        Args:
            state: True=唤醒, False=休眠
            enter_talk_mode: True=进入连续对话模式
        """
        _safe_print(f"[DEBUG] _set_awake called with state={state}, enter_talk_mode={enter_talk_mode}, current awake={self.awake}")

        # 【修复代理-01】【BUG-2 Fix】确保锁的获取顺序：先_state_lock后_talk_mode_lock
        with self._state_lock:
            self.awake = state

            if state:
                self._awake_by_ptt = False  # [P0-006 Fix] 标记为由唤醒词设置，非PTT
                self._reset_awake_timer()
                _safe_print(f"[DEBUG] Timer started with timeout={self.awake_timeout}s")

                # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
                with self._talk_mode_lock:
                    # 【Talk Mode】如果请求进入Talk Mode
                    if enter_talk_mode:
                        self.in_talk_mode = True
                        self._talk_mode_round = 0
                        self._last_user_speak_time = time.time()
                        logger.info("[TalkMode] 进入连续对话模式")

                # 【新增】通知弱连接引擎用户活跃
                try:
                    from core.weak_connection import get_weak_connection_engine
                    weak_engine = get_weak_connection_engine()
                    weak_engine.on_user_input()  # 暂停弱连接，优先响应用户
                except Exception as e:
                    logger.error(f"[Voice] 通知弱连接引擎失败: {e}", exc_info=True)

                # 【新增】通知工作模式管理器用户活跃
                try:
                    from core.work_mode_manager import get_work_mode_manager
                    work_mode_mgr = get_work_mode_manager()
                    work_mode_mgr.on_user_input()
                    logger.debug("[Voice] 已通知工作模式管理器用户输入")
                except Exception as e:
                    logger.error(f"[Voice] 通知工作模式管理器失败: {e}", exc_info=True)
            else:
                # 【Thread-Safety-Fixer】使用原子操作取消定时器
                self._cancel_awake_timer()
                # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
                with self._talk_mode_lock:
                    # 【Talk Mode】退出时清理状态
                    self.in_talk_mode = False
                    self._talk_mode_round = 0

        # 【状态同步】发送唤醒状态变化到前端
        try:
            state_sync = get_voice_state_sync()
            if state:
                state_sync.on_wake()
            else:
                state_sync.on_sleep()
        except Exception as e:
            logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

    def _reset_awake_timer(self):
        """【Thread-Safety-Fixer】重置唤醒超时定时器 - 使用原子操作"""
        self._start_awake_timer(self.awake_timeout)

    def _timeout_sleep(self):
        """
        【Thread-Safety-Fixer】超时后自动休眠 - 定时器回调中自动清理
        【Talk Mode】支持连续对话模式
        """
        _safe_print(f"[DEBUG] _timeout_sleep called, awake was {self.awake}, timer={self._awake_timer}")

        # 【修复代理-02】【BUG-6 Fix】统一锁顺序：先_state_lock后_talk_mode_lock，避免死锁
        with self._state_lock:
            # 【修复代理-02】【BUG-6 Fix】在_state_lock内部安全读取in_talk_mode
            # 【Talk Mode】如果在Talk Mode中，检查是否应该询问用户
            in_talk_mode_now = self.in_talk_mode
            if in_talk_mode_now:
                # 检查用户静默时间
                silence_time = time.time() - self._last_user_speak_time
                if silence_time >= self._talk_mode_silence_threshold:
                    # 用户静默超过阈值，主动询问
                    self._talk_mode_round += 1
                    if self._talk_mode_round >= self._talk_mode_max_round:
                        # 达到最大轮数，退出Talk Mode
                        self.exit_talk_mode(reason="max_rounds")
                    else:
                        # 主动询问用户
                        prompt = random.choice(self._talk_mode_prompts)
                        self.speak(prompt, is_system=True, priority=1)
                        self._last_user_speak_time = time.time()  # 重置时间
                        self._reset_awake_timer()  # 重置定时器，继续等待
                    return
                else:
                    # 用户刚刚说过话，重置定时器继续等待
                    self._reset_awake_timer()
                    return

            # 普通模式：直接休眠
            self.awake = False
            self._awake_by_ptt = False  # [P0-006 Fix] 清除PTT标记
            _safe_print("⏳ 唤醒超时，进入休眠")

        # 【状态同步】发送休眠状态到前端
        try:
            state_sync = get_voice_state_sync()
            state_sync.on_sleep()
        except Exception as e:
            logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

    # ---------- 【Talk Mode】连续对话模式方法 ----------
    def enter_talk_mode(self):
        """进入Talk Mode连续对话模式"""
        logger.info("[TalkMode] 用户请求进入连续对话模式")
        self._set_awake(True, enter_talk_mode=True)
        # 播放进入提示
        from voice.voice_prompts import SystemAnnouncements
        self.speak(SystemAnnouncements.CONVERSATION_MODE_ON,
                   is_system=True, priority=0)

    def exit_talk_mode(self, reason: str = "timeout"):
        """退出Talk Mode"""
        # 【修复代理-01】【BUG-1 Fix】使用锁保护in_talk_mode读写，防止竞态条件
        with self._talk_mode_lock:
            if not self.in_talk_mode:
                # 【SILENT_FAILURE_BLOCKED】防止无效退出操作
                logger.error(f"[TalkMode] [SILENT_FAILURE_BLOCKED] 尝试退出未激活的Talk Mode，原因: {reason}")
                raise RuntimeError(f"[TalkMode] 尝试退出未激活的Talk Mode，原因: {reason}")

            logger.info(f"[TalkMode] 退出连续对话模式，原因: {reason}")
            self.in_talk_mode = False
            from voice.voice_prompts import SystemAnnouncements
            if reason == "timeout":
                self.speak(SystemAnnouncements.CONVERSATION_TIMEOUT, is_system=True)
            elif reason == "user_exit":
                self.speak(SystemAnnouncements.CONVERSATION_GOODBYE, is_system=True)
            elif reason == "max_rounds":
                self.speak(SystemAnnouncements.CONVERSATION_REST, is_system=True)

            # 【修复代理-01】【BUG-1 Fix】延迟休眠前捕获当前状态，防止与用户新唤醒冲突
            exit_timestamp = time.time()

        # 【修复代理-01】【BUG-1 Fix】延迟休眠回调：检查状态是否仍有效
        def _delayed_sleep_with_state_check(timestamp):
            """延迟休眠回调：验证状态一致性后再执行休眠"""
            with self._talk_mode_lock:
                # 检查1: 如果又回到Talk Mode，说明用户已重新进入，取消休眠
                if self.in_talk_mode:
                    logger.info("[TalkMode] 延迟休眠检测到用户已重新进入Talk Mode，取消休眠操作")
                    return

                # 检查2: 如果awake为False，说明已被其他逻辑处理，无需重复操作
                if not self.awake:
                    logger.info("[TalkMode] 延迟休眠检测到系统已处于休眠状态，跳过重复操作")
                    return

            # 【SILENT_FAILURE_BLOCKED】检查3: 验证时间戳一致性（防止极罕见的时序问题）
            time_elapsed = time.time() - timestamp
            if time_elapsed < 2.5:  # 正常情况下至少经过2.5秒
                logger.error(f"[TalkMode] [SILENT_FAILURE_BLOCKED] 延迟休眠时间异常: {time_elapsed:.2f}s，可能存在时序问题")
                # 这里不抛出异常，但记录错误，继续执行以确保用户体验

            logger.info("[TalkMode] 执行延迟休眠操作")
            self._set_awake(False)

        # 启动带状态检查的延迟休眠定时器
        threading.Timer(3.0, lambda: _delayed_sleep_with_state_check(exit_timestamp)).start()

    def _is_exit_talk_mode_command(self, text: str) -> bool:
        """检测用户是否想要退出Talk Mode"""
        exit_words = ["再见", "拜拜", "结束", "退出", "没有了", "谢谢", "退下", "休息"]
        text = text.lower().strip()
        return any(word in text for word in exit_words)

    def _is_enter_talk_mode_command(self, text: str) -> bool:
        """
        【修复代理-16】检测用户是否想要进入 Talk Mode

        Args:
            text: 用户输入文本

        Returns:
            bool: 是否是进入命令
        """
        enter_words = ["进入对话模式", "连续对话", "聊聊", "我们聊聊", "对话模式", "聊天模式"]
        text_normalized = text.lower().strip().replace(" ", "").replace("，", "").replace("。", "")

        return any(word in text_normalized for word in enter_words)

    def on_ai_response_complete(self):
        """
        【修复代理-16】【Talk Mode】AI回复完成后的回调
        由语音播报工作线程调用
        用于在Talk Mode中继续监听用户输入
        """
        # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
        with self._talk_mode_lock:
            if not self.in_talk_mode:
                return

        logger.info("[TalkMode] AI回复完成，继续监听用户输入")
        self._last_user_speak_time = time.time()
        self._reset_awake_timer()  # 重置定时器，给用户时间回应
        _safe_print("🎙️ [TalkMode] AI回复完成，等待您继续说话...")

    # ---------- 免唤醒模式（Push-to-Talk）----------
    def start_ptt_session(self):
        """
        【Thread-Safety-Fixer】开始免唤醒会话（前端点击录音时调用）
        进入此模式后，无需唤醒词直接识别语音
        """
        self.push_to_talk = True
        self._ptt_session_active = True
        self.awake = True  # 强制唤醒
        self._awake_by_ptt = True  # [P0-006 Fix] 标记为由PTT设置的唤醒状态

        # 【Thread-Safety-Fixer】使用原子操作取消现有的休眠定时器
        self._cancel_awake_timer()

        # 【状态同步】开始识别
        try:
            state_sync = get_voice_state_sync()
            state_sync.on_start_listening()
        except Exception as e:
            logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

        # 【新增】通知弱连接引擎进入工作模式
        try:
            from core.weak_connection import get_weak_connection_engine
            weak_engine = get_weak_connection_engine()
            weak_engine.on_work_start()
        except Exception as e:
            logger.error(f"[Voice] 通知弱连接引擎工作开始失败: {e}", exc_info=True)

        _safe_print("[MIC] 进入免唤醒模式（前端录音），直接识别语音")

    def end_ptt_session(self):
        """
        结束免唤醒会话（前端录音结束时调用）
        延迟一段时间后恢复休眠状态
        [P0-006 Fix] 只在PTT设置的唤醒状态下才清除awake，保护唤醒词激活的状态
        """
        self._ptt_session_active = False

        # 【状态同步】停止识别
        try:
            state_sync = get_voice_state_sync()
            state_sync.on_stop_listening()
        except Exception as e:
            logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

        # 【新增】通知弱连接引擎退出工作模式
        try:
            from core.weak_connection import get_weak_connection_engine
            weak_engine = get_weak_connection_engine()
            weak_engine.on_work_end()
        except Exception as e:
            logger.error(f"[Voice] 通知弱连接引擎工作结束失败: {e}", exc_info=True)

        # 延迟休眠，给用户时间回复
        def delayed_sleep():
            time.sleep(self.ptt_timeout)
            if not self._ptt_session_active:  # 确保没有新的PTT会话
                self.push_to_talk = False
                # [P0-006 Fix] 只在PTT设置的唤醒状态下才清除awake
                if self._awake_by_ptt:
                    self.awake = False
                    self._awake_by_ptt = False  # 清除标记
                    _safe_print("⏳ 免唤醒会话结束，恢复休眠状态")
                    # 【状态同步】进入休眠
                    try:
                        state_sync = get_voice_state_sync()
                        state_sync.on_sleep()
                    except Exception as e:
                        logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)
                else:
                    _safe_print("⏳ 免唤醒会话结束，但唤醒词状态保持激活")

        threading.Thread(target=delayed_sleep, daemon=True).start()
        _safe_print(f"[MIC] 免唤醒会话结束，{self.ptt_timeout}秒后恢复休眠")

    def is_voice_active(self) -> bool:
        """检查当前是否处于语音活跃状态（唤醒或PTT模式）"""
        return self.awake or self.push_to_talk

    def _check_echo(self, recognized_text: str) -> bool:
        """
        检查识别文本是否是系统播报的回声
        增强检测：扩大时间窗口并支持唤醒反馈的特殊处理
        """
        if not self._last_spoken_text:
            return False

        import time
        time_since_speak = time.time() - self._last_speak_time

        # 【关键修复】扩大时间窗口到2.5秒，给声音传播和识别缓冲更多时间
        # 唤醒反馈"我在"很短，但声音反射和识别延迟可能导致稍晚才识别到
        max_window = 2.5 if self._last_spoken_text == "我在" else 2.0
        if time_since_speak > max_window:
            return False

        spoken = self._last_spoken_text.lower().replace(" ", "")
        recognized = recognized_text.lower().replace(" ", "")

        # 【关键修复】对常见系统提示音特殊处理
        # 这些短句容易被识别为完整文本，需要特殊匹配
        system_phrases = {
            "我在": ["我", "在"],
            "好的，请稍候": ["好", "请", "稍"],
            "好的请稍候": ["好", "请", "稍"],
        }

        for phrase, keywords in system_phrases.items():
            if (self._last_spoken_text == phrase or spoken == phrase.replace(" ", "").replace("，", "")) and all(kw in recognized for kw in keywords):
                _safe_print(f"[Voice] 检测到系统提示音回声: '{recognized_text}' -> 匹配 '{phrase}'")
                return True

        # 通用相似度检查：降低阈值到60%提高容错
        import difflib
        similarity = difflib.SequenceMatcher(None, spoken, recognized).ratio()

        if similarity > 0.6:  # 60%相似度即视为回声（降低阈值）
            _safe_print(f"[Voice] 检测到回声（相似度{similarity:.2f}）：{recognized_text}")
            return True

        return False

    # ---------- 监听循环 ----------
    def _listen_loop(self):
        """
        语音监听主循环 - Thread-Fixer增强版（含熔断机制）

        修复内容：
        1. 增加连续错误计数和熔断机制
        2. 改进资源清理
        3. 增加详细日志
        """
        if self.vosk_model is None or self.recognizer is None:
            logger.error("[Voice] Vosk 模型未加载，无法启动语音监听")
            return

        # 使用统一的 PyAudio 实例（Thread-Fixer修复）
        p = self._pyaudio if self._pyaudio else pyaudio.PyAudio()


        # 从配置获取输入设备索引，默认为None（使用系统默认设备）
        input_device_index = config.get("voice.input_device_index", None)

        stream = None

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=4000
            )
            _safe_print("[Voice] 正在倾听...")

            # 重置错误计数（Thread-Fixer）
            self._listen_consecutive_errors = 0

            # 【Thread-Safety-Fixer】使用线程安全的方式检查is_listening
            loop_counter = 0
            _safe_print(f"[DEBUG] 进入监听循环，is_listening={self.is_listening}")
            while self.is_listening:
                try:
                    data = stream.read(4000, exception_on_overflow=False)

                    # 调试日志：每1000次循环打印一次状态
                    loop_counter += 1
                    if loop_counter % 1000 == 0:
                        _safe_print(f"[DEBUG] 监听循环运行中... awake={self.awake}, is_speaking={self.is_speaking}")

                    # 【回声消除】播放期间及结束后0.3秒内丢弃音频帧，防止扬声器回灌
                    if self.is_speaking or (time.time() - self._last_speak_end_time < 0.3):
                        continue

                    if self.recognizer.AcceptWaveform(data):
                        result = json.loads(self.recognizer.Result())
                        text = result.get("text", "").strip()
                        if text:
                            _safe_print(f"[DEBUG] AcceptWaveform 返回文本: '{text}', awake={self.awake}, is_speaking={self.is_speaking}")

                            # ========== 【修复代理-16】【修复代理-01】Talk Mode 处理 ==========
                            # 【Talk Mode】如果在Talk Mode中，跳过唤醒词检测，直接处理
                            # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
                            with self._talk_mode_lock:
                                in_talk_mode_now = self.in_talk_mode

                            if in_talk_mode_now:
                                _safe_print(f"[TalkMode] 识别到用户输入: {text}")

                                # 【Talk Mode】识别到用户语音，更新时间戳
                                self._last_user_speak_time = time.time()

                                # 【Talk Mode】检测退出命令
                                if self._is_exit_talk_mode_command(text):
                                    logger.info(f"[TalkMode] 用户请求退出: {text}")
                                    self.exit_talk_mode(reason="user_exit")
                                    continue  # 跳过正常处理，直接继续循环

                                # 【Talk Mode】在Talk Mode中直接处理用户输入
                                if not self.is_speaking:  # 避免在播报期间处理
                                    # 过滤唤醒词
                                    filtered_text = self._wake_word_handler.filter_wake_words(text)
                                    if filtered_text and len(filtered_text.strip()) >= 1:
                                        _safe_print(f"🎤 [TalkMode] 识别到语音: {filtered_text}")
                                        _safe_print("⏳ 正在思考...")
                                        from voice.voice_prompts import SystemAnnouncements
                                        self.speak(SystemAnnouncements.PROCESSING, is_system=True, wait=False)
                                        self._submit_async_handle_result(filtered_text)
                                    continue

                            # ========== 【Phase 1 Week 1 - Bug修复】唤醒词检测处理 ==========
                            # 使用WakeWordHandler处理唤醒词检测，修复4个Bug
                            if self._is_wake_word(text):
                                _safe_print("[唤醒词] 【成功】 唤醒词检测到，准备唤醒...")

                                # 使用WakeWordHandler统一处理唤醒流程（Bug #1, #3修复）
                                success = self._wake_word_handler.on_wake_word_detected(
                                    stop_speaking_func=self.stop_speaking,
                                    recognizer=self.recognizer,
                                    play_feedback_func=lambda: self._play_wake_feedback(skip_reset=True)
                                )

                                if success:
                                    clear_session_history("voice")
                                    _safe_print("[WakeWord] 会话历史已清除")

                                    self._set_awake(True)
                                    _safe_print(f"[WakeWord] 唤醒状态已设置: awake={self.awake}")
                                    # 【ExperienceBus】唤醒词检测成功
                                    with contextlib.suppress(Exception):
                                        event_bus.emit("voice:wake_word_detected", {
                                            "wake_words": self.wake_words,
                                            "detected_text": text,
                                            "timestamp": time.time(),
                                        })
                                else:
                                    _safe_print("[WakeWord] [WARN] 唤醒处理失败，继续监听")

                                continue

                            # ========== 【关键修复】播报期间非唤醒词识别处理 ==========
                            # 当系统正在播报时，麦克风会拾取扬声器的声音
                            # 但唤醒词检测已优先处理，这里只处理非唤醒词
                            # 【BUG-4修复】AI回复期间缓存用户输入，不直接丢弃
                            if self.is_speaking:
                                _safe_print(f"[Voice] 🔇 播报中缓存用户输入: '{text}'")
                                with self._input_buffer_lock:
                                    # 检查缓存队列长度，避免无限增长
                                    if self._input_buffer.qsize() < 5:  # 最多缓存5条
                                        self._input_buffer.put({
                                            'text': text,
                                            'timestamp': time.time(),
                                            'source': 'voice_during_speaking'
                                        })
                                        _safe_print(f"[Voice] ✅ 用户输入已缓存，队列长度: {self._input_buffer.qsize()}")

                                        # 启动缓存处理线程（如果未启动）
                                        if self._input_buffer_thread is None or not self._input_buffer_thread.is_alive():
                                            self._input_buffer_processing = True
                                            self._input_buffer_stop_event.clear()  # 清除停止信号
                                            self._input_buffer_thread = threading.Thread(
                                                target=self._process_input_buffer_worker,
                                                daemon=True
                                            )
                                            self._input_buffer_thread.start()
                                            _safe_print("[Voice] 输入缓存处理线程已启动")
                                    else:
                                        _safe_print(f"[Voice] ⚠️ 输入缓存队列已满，丢弃: '{text}'")
                                continue

                            # 检查是否是系统播报期间的回声（避免自说自听）
                            # 两种检测：1. 正在播报中 2. 3秒内刚播报完且内容相似
                            is_echo = False
                            if self._is_system_speaking:
                                # 正在播报时检测
                                is_echo = self._check_echo(text)
                            elif time.time() - self._last_speak_time < 2.0:
                                # 播报结束后2秒内，检测相似度（缩短窗口提高响应）
                                is_echo = self._check_echo(text)

                            if is_echo:
                                _safe_print(f"[识别到] {text}")
                                _safe_print("🔇 系统播报回声，已忽略")
                                continue

                            _safe_print(f"[识别到] {text}")
                            if len(text) < 2:
                                continue

                            # 处理语音指令：唤醒状态 或 免唤醒模式(PTT)
                            _safe_print(f"[DEBUG] Checking awake status: awake={self.awake}, push_to_talk={self.push_to_talk}")
                            _safe_print(f"[DEBUG] 识别到完整文本: '{text}'，准备处理...")

                            # ========== 【修复代理-16】【修复代理-01】检测进入 Talk Mode 指令 ==========
                            # 【修复代理-01】【BUG-2 Fix】使用局部变量检查Talk Mode状态
                            with self._talk_mode_lock:
                                in_talk_mode_check = self.in_talk_mode

                            if not in_talk_mode_check and self._is_enter_talk_mode_command(text):
                                logger.info(f"[TalkMode] 用户请求进入对话模式: {text}")
                                self.enter_talk_mode()
                                continue

                            if self.awake or self.push_to_talk:
                                _safe_print(f"[WakeWord] 处理语音指令，awake={self.awake}, push_to_talk={self.push_to_talk}")
                                if self.awake:
                                    self._reset_awake_timer()  # 普通唤醒模式重置定时器
                                    _safe_print("[WakeWord] 唤醒定时器已重置")

                                # Bug #4修复: 过滤唤醒词，避免传给AI
                                original_text = text
                                filtered_text = self._wake_word_handler.filter_wake_words(text)
                                if filtered_text != original_text:
                                    _safe_print(f"[WakeWord] 已过滤唤醒词: '{original_text}' -> '{filtered_text}'")
                                    text = filtered_text

                                # 如果过滤后文本为空或过短，忽略
                                if not text or len(text.strip()) < 1:
                                    _safe_print("[WakeWord] 过滤后文本为空，忽略")
                                    continue

                                _safe_print(f"🎤 识别到语音: {text}")
                                # 立即给予用户反馈（播报+显示）
                                _safe_print("⏳ 正在思考...")
                                from voice.voice_prompts import SystemAnnouncements
                                self.speak(SystemAnnouncements.PROCESSING, is_system=True, wait=False)

                                # 使用新的带异常处理的方法
                                self._submit_async_handle_result(text)
                            else:
                                _safe_print("💤 休眠中，忽略语音（可以说唤醒词激活）")
                                _safe_print(f"[DEBUG] 当前状态: awake={self.awake}, push_to_talk={self.push_to_talk}")
                    else:
                        partial = json.loads(self.recognizer.PartialResult())
                        partial_text = partial.get("partial", "")
                        if partial_text:
                            # Bug #2修复: 系统播报期间跳过部分识别
                            filtered_partial = self._wake_word_handler.on_partial_result(partial_text)
                            if filtered_partial is None:
                                # 系统播报期间，不打印日志避免刷屏
                                pass
                            else:
                                _safe_print(f"[部分识别] {partial_text}")
                                # 调试日志：如果在唤醒状态下，打印更多调试信息
                                if self.awake:
                                    _safe_print(f"[DEBUG] 唤醒状态下部分识别: '{partial_text}', awake={self.awake}")

                            # Bug #2修复: 即使检测到唤醒词，也要检查是否在系统播报期间
                            if partial_text and self._is_wake_word(partial_text):
                                # 检查是否在系统播报保护期内
                                if self._wake_word_handler.should_skip_partial_due_to_speaking():
                                    _safe_print("[WakeWord] 系统播报期间，忽略部分识别中的唤醒词")
                                    continue

                                _safe_print("[WakeWord] 部分识别中检测到唤醒词，执行唤醒...")

                                # 使用WakeWordHandler统一处理（Bug #1, #3修复）
                                success = self._wake_word_handler.on_wake_word_detected(
                                    stop_speaking_func=self.stop_speaking,
                                    recognizer=self.recognizer,
                                    play_feedback_func=lambda: self._play_wake_feedback(skip_reset=True)
                                )

                                if success:
                                    self._set_awake(True)
                                    _safe_print(f"[WakeWord] 唤醒状态已设置: awake={self.awake}")
                                    clear_session_history("voice")
                                    _safe_print("[WakeWord] 会话历史已清除")
                                else:
                                    _safe_print("[WakeWord] [WARN] 部分识别唤醒处理失败")
                                continue

                    # 成功处理，重置错误计数（Thread-Fixer）
                    if self._listen_consecutive_errors > 0:
                        self._listen_consecutive_errors = 0

                except Exception as e:
                    # Thread-Fixer: 错误处理和熔断机制
                    self._listen_consecutive_errors += 1
                    error_count = self._listen_consecutive_errors
                    max_errors = getattr(self, '_listen_max_consecutive_errors', 10)

                    _safe_print(f"[Voice] 监听异常 ({error_count}/{max_errors}): {e}")

                    # 熔断机制：连续错误过多，主动退出
                    if error_count >= max_errors:
                        logger.error("[Voice] 连续错误过多，触发熔断，线程将退出")
                        break

                    time.sleep(0.5)  # 增加错误后的休眠时间

        except Exception as e:
            _safe_print(f"[Voice] [FATAL] 监听线程致命错误: {e}")
            traceback.print_exc()
        finally:
            # Thread-Fixer: 确保资源释放
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    logger.error(f"[Voice] 关闭音频流失败: {e}", exc_info=True)

            # 如果不是使用统一的PyAudio实例，才终止
            if p is not self._pyaudio:
                try:
                    p.terminate()
                except Exception as e:
                    logger.error(f"[Voice] 终止 PyAudio 失败: {e}", exc_info=True)

            # 【Thread-Safety-Fixer】使用线程安全的方式重置is_listening
            with self._state_lock:
                self._is_listening = False
            _safe_print("🛑 语音监听已停止")

    async def _async_handle_result(self, text: str):
        """
        语音识别结果回调，转交给 dialogue_manager
        【Talk Mode】支持连续对话模式，更新用户说话时间，检测退出词
        """
        _safe_print(f"[WakeWord] _async_handle_result 被调用，文本: '{text}'")

        if len(text) < 2:
            _safe_print("[WakeWord] 忽略过短文本")
            return

        # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
        with self._talk_mode_lock:
            in_talk_mode_local = self.in_talk_mode

        # 【Talk Mode】更新用户说话时间
        if in_talk_mode_local:
            self._last_user_speak_time = time.time()
            logger.debug(f"[TalkMode] 更新用户说话时间: {self._last_user_speak_time}")

            # 【Talk Mode】检测退出词
            if self._is_exit_talk_mode_command(text):
                logger.info(f"[TalkMode] 检测到退出命令: '{text}'")
                self.exit_talk_mode(reason="user_exit")
                return

        try:
            # 【新增】发送用户语音识别的文本给前端
            await self._send_voice_message_to_frontend("user", text)

            _safe_print("[WakeWord] 调用 dialogue_manager.handle_input AUTO...")
            result = await dialogue_manager.handle_input(
                user_id="voice",
                text=text,
                session_id="voice",
                input_mode=InputMode.AUTO,
                voice_instance=self
            )
            response_text = ""
            if isinstance(result, dict):
                response_text = result.get("content", "") or result.get("chat_reply", "") or result.get("result", "")
            elif result:
                response_text = str(result)
            _safe_print(f"[WakeWord] handle_input 返回结果: {response_text[:100] if response_text else 'None'}...")

            # 【新增】发送AI回复给前端
            if response_text:
                await self._send_voice_message_to_frontend("assistant", response_text)

        except Exception as e:
            logger.error(f"[Voice] 异步处理语音识别结果异常: {e}", exc_info=True)

    async def _send_voice_message_to_frontend(self, role: str, content: str):
        """发送语音消息给前端WebSocket"""
        try:
            # 延迟导入避免循环依赖
            import time

            from api.cloud_api import ConnectionManager

            # 构造消息
            message = {
                "type": "chat_alignment_reply",
                "timestamp": time.time(),
                "data": {
                    "content": content,
                    "role": role,
                    "mode": "voice_chat",
                    "session_id": "voice"
                }
            }

            # 发送给所有在线用户（语音交互使用默认用户"user_admin"）
            manager = ConnectionManager()
            # 尝试发送给常见用户ID
            for user_id in ["user_admin", "voice", "default"]:
                try:
                    connections = manager.get_user_connections(user_id)
                    if connections > 0:
                        await manager.send_to_user(user_id, message)
                        _safe_print(f"[Voice] 已发送{role}消息给前端用户 {user_id}")
                        break
                except Exception as e:
                    logger.error(f"[VoiceAudio] 获取设备 {user_id} 信息失败: {e}", exc_info=True)
                    continue
            else:
                logger.warning("[Voice] 未找到在线用户接收消息")

        except Exception as e:
            logger.error(f"[Voice] 发送消息给前端失败: {e}", exc_info=True)

    def _submit_async_handle_result(self, text: str):
        """提交异步处理任务，带异常回调处理"""
        _safe_print(f"[WakeWord] _submit_async_handle_result 被调用，文本: '{text}'")

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_handle_result(text),
                self.loop
            )

            # 添加异常回调
            def check_exception(fut):
                try:
                    fut.result()
                    _safe_print("[唤醒词] 【成功】 异步任务完成")
                except Exception as e:
                    logger.error(f"[Voice] 异步任务执行异常: {e}", exc_info=True)

            future.add_done_callback(check_exception)
            _safe_print("[唤醒词] 【成功】 异步任务已提交到事件循环")

        except Exception as e:
            logger.error(f"[Voice] 提交异步任务失败: {e}", exc_info=True)

    def _process_input_buffer_worker(self):
        """
        【BUG-4修复】输入缓存处理工作线程

        后台线程，等待AI播报结束后处理缓存的用户输入。
        确保用户说话内容不会被截断丢失。
        """
        logger.info("[Voice] 输入缓存处理线程启动")

        while not self._input_buffer_stop_event.is_set():
            try:
                # 等待一段时间再检查
                time.sleep(0.5)

                # 检查是否正在播报
                if self.is_speaking:
                    continue

                # 检查缓存队列（修复：避免在锁内continue）
                item_to_process = None
                with self._input_buffer_lock:
                    if not self._input_buffer.empty():
                        # 获取缓存的输入
                        item = self._input_buffer.get()
                        cached_text = item.get('text', '')
                        cached_time = item.get('timestamp', 0)

                        # 检查缓存是否过期（超过30秒的输入不再处理）
                        if time.time() - cached_time > 30:
                            _safe_print(f"[Voice] 缓存输入已过期，丢弃: '{cached_text}'")
                        else:
                            item_to_process = item
                            _safe_print(f"[Voice] 处理缓存输入: '{cached_text}'")

                # 在锁外处理输入
                if item_to_process:
                    cached_text = item_to_process.get('text', '')
                    if cached_text:
                        # 检查唤醒状态
                        if self.awake or self.push_to_talk:
                            # 过滤唤醒词
                            filtered_text = self._wake_word_handler.filter_wake_words(cached_text)
                            if filtered_text and len(filtered_text.strip()) >= 1:
                                _safe_print(f"🎤 [缓存] 识别到语音: {filtered_text}")
                                _safe_print("⏳ 正在思考...")
                                from voice.voice_prompts import SystemAnnouncements
                                self.speak(SystemAnnouncements.PROCESSING, is_system=True, wait=False)
                                self._submit_async_handle_result(filtered_text)
                        else:
                            _safe_print(f"[Voice] 系统未唤醒，缓存输入被忽略: '{cached_text}'")

            except Exception as e:
                logger.error(f"[Voice] 输入缓存处理异常: {e}", exc_info=True)
                time.sleep(1)  # 出错后等待1秒再继续

        logger.info("[Voice] 输入缓存处理线程退出")

    def stop_input_buffer_processing(self):
        """
        【BUG-4修复】停止输入缓存处理线程
        """
        self._input_buffer_processing = False
        self._input_buffer_stop_event.set()  # 设置停止信号（线程安全）
        if self._input_buffer_thread and self._input_buffer_thread.is_alive():
            self._input_buffer_thread.join(timeout=2.0)
            # 【修复】检查join是否超时
            if self._input_buffer_thread.is_alive():
                logger.warning("[Voice] 输入缓存处理线程未在2秒内停止")
            else:
                logger.info("[Voice] 输入缓存处理线程已停止")
            # 【修复】清理剩余缓存
            self._cleanup_remaining_buffer()

    def _cleanup_remaining_buffer(self):
        """
        【BUG-4修复】清理剩余缓存
        """
        with self._input_buffer_lock:
            remaining = []
            while not self._input_buffer.empty():
                try:
                    item = self._input_buffer.get_nowait()
                    remaining.append(item)
                except queue.Empty:
                    break
            if remaining:
                logger.warning(f"[Voice] 清理{len(remaining)}条未处理缓存")

    def speak(self, text, wait=True, is_system=None, protected=None, priority=None):
        """
        语音合成播报（使用队列避免重叠）

        【修复代理-11】智能播报中断机制：
        - AI输出（priority=0，高优先级）可以中断过程播报（priority=2，低优先级）
        - 过程播报不能中断AI输出
        - 添加平滑过渡，避免 abrupt 中断

        Args:
            text: 要播报的文本
            wait: 是否等待播报完成
            is_system: 是否是系统音（如果是，会暂停语音识别避免回声）
                     默认自动判断：包含"底座""系统"等关键词视为系统音
            protected: 是否受保护（受保护项不会被中断或清空），None表示自动判断
            priority: 优先级（0=最高AI输出，1=系统，2=最低过程播报），None表示自动判断
                     优先级数值越小，优先级越高
        """
        if not text:
            return

        # 【P1 Fix】去重检查：如果与上一次播报内容相同，且间隔小于5秒，则跳过
        current_time = time.time()
        if (text == self._last_announce_text and
            current_time - self._last_announce_time < 5.0):
            logger.debug(f"[Voice] 跳过重复播报: {text[:30]}...")
            return

        # 更新最后播报记录
        self._last_announce_text = text
        self._last_announce_time = current_time

        # 【修复】过滤播报内容，移除JSON，只保留自然语言
        text = self._filter_speak_content(text)
        if not text:
            return

        # 【修复】智能去重检查
        if not self._should_speak_content(text, is_system):
            return

        # 【治理】长文本智能分段，替代简单截断
        # 每段不超过150字符，按句子边界分割，与优先级/中断机制兼容

        # 自动判断是否为系统音
        if is_system is None:
            system_keywords = ["底座", "系统", "启动", "初始化", "等待指令", "就绪"]
            is_system = any(kw in text for kw in system_keywords)

        # 【Phase 1 Week 1 Fix】自动判断受保护
        if protected is None:
            # 系统音或重要提示自动标记为受保护
            protected_keywords = ["系统启动", "初始化完成", "错误", "警告", "紧急"]
            protected = is_system or any(kw in text for kw in protected_keywords)

        # 【修复代理-11】自动判断优先级
        if priority is None:
            priority = 1 if is_system else 0  # 系统音中等优先级，默认普通播报最高优先级（AI输出）

        # 【修复代理-11】智能播报中断机制
        # 检查当前播报是否可以被中断
        with self.speaking_lock:
            current_priority = self._current_speak_priority
            current_protected = self._current_speak_protected
            is_currently_speaking = self.is_speaking

        # 当前有播报在进行，且新播报优先级更高（数值更小），且当前播报不受保护
        if (is_currently_speaking and
            priority < current_priority and
            not current_protected):
            logger.info(f"[Voice] 高优先级播报({priority})中断低优先级({current_priority}): {text[:30]}...")
            self._interrupt_current_playback(smooth=True)

        # 系统音标志 - 播报期间语音识别会忽略
        with self.speaking_lock:
            self._is_system_speaking = is_system
            # 始终记录播报文本用于回声检测（不只记录系统音）
            self._last_spoken_text = text
            self._last_speak_time = time.time()

        # 【状态同步】开始播报，设置保护期（系统音5秒保护）
        try:
            state_sync = get_voice_state_sync()
            protected_duration = 5.0 if is_system else 0.0
            state_sync.on_start_speaking(protected_duration)
        except Exception as e:
            logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

        # 【Phase 1 Week 1 Fix】使用新的队列接口
        # 长文本分段播报：每段独立入队，只有最后一段使用 wait
        segments = self._split_text_for_tts(text, max_chars=150)
        for idx, segment in enumerate(segments):
            segment_wait = wait if idx == len(segments) - 1 else False
            self._speak_queue.enqueue(segment, segment_wait, priority, protected)

        # 【修复】不再自动打断当前播报，让语音按顺序播放
        # 之前的逻辑会导致语音频繁被截断，用户体验差
        # 现在所有语音都排队顺序播放，除非是用户新的指令（非系统音）
        # if is_system and self.is_speaking:
        #     print(f"[Voice] 系统音打断当前播报: {text[:30]}...")
        #     self.stop_speaking()

    def _cleanup_audio_resources(self):
        """清理音频资源（增强版）
        修复：确保音频流正确停止和关闭，数据被刷新到设备
        """
        with self._stream_lock:
            if self._audio_stream:
                try:
                    # 【关键修复】先停止流，确保缓冲区数据被刷新到设备
                    if self._audio_stream.is_active():
                        self._audio_stream.stop_stream()
                        _safe_print("[VoiceAudio] 音频流已停止")

                    self._audio_stream.close()
                    _safe_print("[VoiceAudio] 音频流已关闭")
                except Exception as e:
                    logger.error(f"[VoiceAudio] 关闭音频流失败: {e}", exc_info=True)
                finally:
                    self._audio_stream = None
                    self.is_speaking = False

    def _interrupt_current_playback(self, smooth: bool = True):
        """
        【修复代理-11】中断当前播报

        实现智能播报中断机制：
        - AI输出（高优先级）可以中断过程播报（低优先级）
        - 过程播报不能中断AI输出
        - 添加平滑过渡，避免 abrupt 中断

        Args:
            smooth: 是否平滑中断（True=设置中断标志让Consumer在当前块后退出；False=立即清理资源）
        """
        if smooth:
            # 平滑中断：设置标志位，让Consumer在当前音频块播放完成后退出
            logger.info("[Voice] 执行平滑中断，等待当前音频块播放完成")
            self._should_stop_current = True

            # 同时设置停止事件，让Producer停止合成
            if self._stop_event:
                self._stop_event.set()
        else:
            # 立即中断：直接清理资源（硬中断）
            logger.info("[Voice] 执行立即中断，强制清理音频资源")
            self._should_stop_current = True
            self._cleanup_audio_resources()

            # 清空队列中未受保护的低优先级项
            try:
                cleared, protected = self._speak_queue.stop_speaking(clear_unprotected_only=True)
                if cleared > 0 or protected > 0:
                    logger.info(f"[Voice] 中断后清理队列: 移除 {cleared} 项, 保留 {protected} 项")
            except Exception as e:
                logger.error(f"[Voice] 中断时清理队列失败: {e}", exc_info=True)

    def _split_text_for_tts(self, text: str, max_chars: int = 150) -> list[str]:
        """
        按句子边界智能分段，确保每段不超过 max_chars

        优先级：
        1. 按段落（\n\n）分割
        2. 按句子结束符（。！？.!?）分割
        3. 按逗号/分号分割
        4. 最后按字符硬截断（保留单词边界）

        【治理】替代简单截断，长文本可分多段播报，
        每段可独立被高优先级播报中断。
        """
        import re

        # 先按段落分割
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]

        segments = []
        for paragraph in paragraphs:
            # 按句子分割（保留分隔符）
            sentences = re.split(r'([。！？.!?]\s*)', paragraph)
            current = ""
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                sep = sentences[i+1] if i+1 < len(sentences) else ""
                candidate = current + sentence + sep
                if len(candidate) > max_chars and current:
                    segments.append(current.strip())
                    current = sentence + sep
                else:
                    current = candidate
            if current.strip():
                segments.append(current.strip())

        # 如果还有超长段（无句子边界），按逗号/分号再分
        final_segments = []
        for seg in segments:
            if len(seg) <= max_chars:
                final_segments.append(seg)
                continue
            # 按逗号/分号分割
            parts = re.split(r'([，,；;]\s*)', seg)
            current = ""
            for i in range(0, len(parts), 2):
                part = parts[i]
                sep = parts[i+1] if i+1 < len(parts) else ""
                candidate = current + part + sep
                if len(candidate) > max_chars and current:
                    final_segments.append(current.strip())
                    current = part + sep
                else:
                    current = candidate
            if current.strip():
                final_segments.append(current.strip())

        # 最后兜底：硬截断
        result = []
        for seg in final_segments:
            if len(seg) <= max_chars:
                result.append(seg)
            else:
                # 在 max_chars 处截断，尽量保留完整词
                truncate_at = max_chars
                while truncate_at > max_chars * 0.7 and seg[truncate_at-1] not in ' \t\n':
                    truncate_at -= 1
                if truncate_at <= max_chars * 0.7:
                    truncate_at = max_chars
                result.append(seg[:truncate_at].strip())
                remainder = seg[truncate_at:].strip()
                if remainder:
                    result.append(remainder)

        return result if result else [text[:max_chars]]

    def _filter_speak_content(self, text: str) -> str:
        """
        过滤播报内容，只保留自然语言
        - 移除JSON代码块
        - 提取reply_to_user/content字段
        - 限制长度避免截断
        """
        import ast  # 用于解析Python字典格式
        import json
        import re

        if not text:
            return text

        # 1. 移除 ```json ... ``` 和 ``` ... ``` 代码块
        text_clean = re.sub(r'```json\s*.*?\s*```', '', text, flags=re.DOTALL)
        text_clean = re.sub(r'```\s*.*?\s*```', '', text_clean, flags=re.DOTALL)

        # 1.1 移除不完整的代码块（没有闭合 ``` 的情况）
        text_clean = re.sub(r'```json\s*[\s\S]*', '', text_clean)
        text_clean = re.sub(r'```\s*[\s\S]*', '', text_clean)

        # 2. 如果内容是纯JSON，尝试提取字段（按优先级）
        try:
            # 尝试提取JSON部分
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    # 先尝试标准JSON解析（双引号）
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    # 如果失败，尝试解析Python字典格式（单引号）
                    try:
                        data = ast.literal_eval(json_str)
                    except (ValueError, SyntaxError):
                        # 如果还是失败，跳过提取
                        raise
                if isinstance(data, dict):
                    # 第一优先级：reply_to_user（专门用于语音播报）
                    if 'reply_to_user' in data and data['reply_to_user']:
                        return data['reply_to_user']
                    # 【修复】第二优先级：支持 action: final_answer + content 格式
                    if data.get('action') == 'final_answer' and 'content' in data:
                        content = data['content']
                        if content and isinstance(content, str):
                            return content
                    # 第三优先级：通用 content 字段
                    if 'content' in data and data['content']:
                        content = data['content']
                        if isinstance(content, str):
                            return content
                    # 最后使用 observation
                    if 'observation' in data and data['observation']:
                        return data['observation']
        except Exception as e:
            logger.error(f"[Voice] 过滤播报内容失败: {e}", exc_info=True)

        # 3. 如果没有提取到有效内容，使用清理后的文本
        text_clean = text_clean.strip()
        if text_clean:
            text = text_clean

        # 4. 限制长度（避免截断），但保留完整句子
        if len(text) > 150:
            # 在句子结束处截断
            truncated = text[:147]
            last_punct = max(truncated.rfind('。'), truncated.rfind('！'),
                           truncated.rfind('？'), truncated.rfind('.'),
                           truncated.rfind('!'), truncated.rfind('?'))
            text = text[:last_punct + 1] if last_punct > 100 else text[:147] + "..."

        return text.strip()

    def _should_speak_content(self, text: str, is_system: bool = False) -> bool:
        """
        智能判断是否应该播报该内容
        - 非错误消息：正常播报
        - 系统消息：正常播报
        - 错误消息：30秒内相同的只播报1次

        Returns:
            bool: True表示应该播报，False表示跳过
        """
        import hashlib
        import time

        # 非错误消息直接播报
        if is_system or not text:
            return True

        # 判断是否是错误消息（包含错误关键词）
        error_keywords = ['失败', '错误', 'error', 'fail', 'exception', '异常']
        is_error = any(kw in text.lower() for kw in error_keywords)

        if not is_error:
            return True

        # 错误消息去重逻辑（哈希表版本）
        # 使用前50个字符计算哈希
        text_hash = hashlib.md5(text[:50].encode('utf-8')).hexdigest()
        now = time.time()
        window = self._speak_dedup['window_seconds']
        history = self._speak_dedup.setdefault('history', {})

        # 检查该哈希是否在窗口期内已有记录
        last_record = history.get(text_hash)
        if last_record:
            time_diff = now - last_record
            if time_diff < window:
                # 在窗口期内，记录重复次数但不播报
                self._speak_dedup['repeat_count'][text_hash] = \
                    self._speak_dedup['repeat_count'].get(text_hash, 0) + 1
                count = self._speak_dedup['repeat_count'][text_hash]
                _safe_print(f"[Voice] 跳过重复错误播报(第{count}次): {text[:50]}...")
                return False

        # 新错误或超过窗口期，允许播报
        self._speak_dedup['last_hash'] = text_hash
        self._speak_dedup['last_time'] = now
        history[text_hash] = now
        # 重置该错误的重复计数
        if text_hash in self._speak_dedup['repeat_count']:
            del self._speak_dedup['repeat_count'][text_hash]
        # LRU 逐出：保留最近 10 条不同错误记录
        if len(history) > 10:
            oldest_hash = min(history, key=history.get)
            del history[oldest_hash]
        return True

    def _speak_with_piper_tts(self, text, wait=True):
        """使用 Piper TTS 进行语音合成（修复音频无声问题）

        修复内容：
        1. 移除双重锁嵌套，避免死锁
        2. 添加音频流刷新机制，确保数据写入设备
        3. 添加扬声器设备选择逻辑
        4. 修复 producer/consumer 数据流冲突
        5. 增强调试日志
        """
        import gc
        import io
        import wave

        _safe_print(f"\n{'='*60}")
        _safe_print("[VoiceAudio] === 开始 Piper TTS 播报 ===")
        _safe_print(f"[VoiceAudio] 文本: {text[:50]}{'...' if len(text) > 50 else ''}")
        _safe_print(f"{'='*60}\n")

        # 设置播报状态
        with self.speaking_lock:
            self.is_speaking = True
        _safe_print("[VoiceAudio] is_speaking set to True")

        # 检查 Piper voice 是否加载
        if not self._piper_voice:
            _safe_print("[VoiceAudio] [WARN] Piper voice 未加载，使用备用引擎")
            self._speak_fallback(text, wait)
            with self.speaking_lock:
                self.is_speaking = False
            return

        # 清理之前的资源
        self._cleanup_audio_resources()

        self._stop_event = threading.Event()
        audio_queue = queue.Queue(maxsize=50)  # 增大缓冲区

        # Piper TTS 使用 22050Hz
        sample_rate = 22050

        # 初始化 PyAudio 并选择输出设备
        output_device_index = None
        try:
            if not self._pyaudio:
                _safe_print("[VoiceAudio] 创建 PyAudio 实例")
                self._pyaudio = pyaudio.PyAudio()

            # 【关键修复】获取并选择输出设备
            output_device_index = self._get_output_device_index()

            if output_device_index is None:
                logger.error("[VoiceAudio] 没有可用的输出设备，切换到备用引擎")
                self._speak_fallback(text, wait)
                return

        except Exception as e:
            logger.error(f"[VoiceAudio] 初始化 PyAudio 失败: {e}", exc_info=True)
            raise TTSInitError(f"初始化 PyAudio 失败: {e}") from e

        # 打开音频流（带设备选择）
        with self._stream_lock:
            try:
                # 关闭旧音频流
                if self._audio_stream is not None:
                    try:
                        if self._audio_stream.is_active():
                            self._audio_stream.stop_stream()
                        self._audio_stream.close()
                        _safe_print("[VoiceAudio] 旧音频流已关闭")
                    except Exception as e:
                        _safe_print(f"[VoiceAudio] 关闭旧音频流失败: {e}")
                    finally:
                        self._audio_stream = None

                # 【关键修复】打开新音频流，指定输出设备
                stream_kwargs = {
                    'format': pyaudio.paInt16,
                    'channels': 1,
                    'rate': sample_rate,
                    'output': True,
                    'frames_per_buffer': 1024
                }

                # 如果指定了设备索引，添加它
                if output_device_index is not None:
                    stream_kwargs['output_device_index'] = output_device_index
                    _safe_print(f"[VoiceAudio] 使用输出设备索引: {output_device_index}")

                self._audio_stream = self._pyaudio.open(**stream_kwargs)
                _safe_print("[VoiceAudio] [OK] 音频流已打开")
                _safe_print(f"[VoiceAudio] 音频流状态: active={self._audio_stream.is_active()}")

            except Exception as e:
                logger.error(f"[VoiceAudio] 打开音频流失败: {e}", exc_info=True)
                self._cleanup_audio_resources()
                raise VoiceSpeakError(f"打开音频流失败: {e}") from e

        # ========== Producer: 合成音频 ==========
        def producer():
            wav_io = None
            try:
                if hasattr(self._piper_voice, 'synthesize'):
                    _safe_print(f"[VoiceAudio] Producer: 开始合成: {text[:30]}...")
                    audio_generator = self._piper_voice.synthesize(text)

                    audio_bytes_list = []
                    total_bytes = 0
                    chunk_count = 0

                    for audio_chunk in audio_generator:
                        if self._stop_event is None or self._stop_event.is_set():
                            _safe_print("[VoiceAudio] Producer: 收到停止信号，中断合成")
                            break

                        if audio_chunk is None or not hasattr(audio_chunk, 'audio_int16_bytes'):
                            continue

                        chunk_bytes = audio_chunk.audio_int16_bytes
                        if not chunk_bytes:
                            continue

                        audio_bytes_list.append(chunk_bytes)
                        total_bytes += len(chunk_bytes)
                        chunk_count += 1

                        # 每收集100KB就处理一次
                        if total_bytes > 100 * 1024:
                            break

                    _safe_print(f"[VoiceAudio] Producer: 合成完成，共 {chunk_count} 块，{total_bytes} bytes")

                    # 检查是否有有效数据
                    if chunk_count == 0 or total_bytes == 0:
                        _safe_print("[VoiceAudio] [WARN] Producer: 合成未产生任何音频数据")
                        audio_queue.put(None)
                        return

                    # 合并音频数据
                    audio_bytes = b''.join(audio_bytes_list)
                    audio_bytes_list = None
                    gc.collect()

                    # 创建内存中的 WAV 文件
                    wav_io = io.BytesIO()
                    with wave.open(wav_io, "wb") as wav_file:
                        wav_file.setframerate(22050)
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.writeframes(audio_bytes)

                    # 读取合成的音频数据
                    wav_io.seek(0)
                    with wave.open(wav_io, "rb") as wav_file:
                        audio_bytes = wav_file.readframes(wav_file.getnframes())

                    wav_io.close()
                    wav_io = None

                    # 转换为 numpy array
                    audio = np.frombuffer(audio_bytes, dtype=np.int16)
                    audio_bytes = None

                    _safe_print(f"[VoiceAudio] Producer: 音频数据总样本数: {len(audio)}")

                    # 分块送入队列
                    chunk_size = 1024 * 4
                    chunks_put = 0
                    for i in range(0, len(audio), chunk_size):
                        if self._stop_event is None or self._stop_event.is_set():
                            _safe_print("[VoiceAudio] Producer: 收到停止信号，中断分块")
                            break
                        chunk = audio[i:i + chunk_size]
                        audio_queue.put(chunk)
                        chunks_put += 1

                    audio = None
                    gc.collect()
                    _safe_print(f"[VoiceAudio] Producer: 已放入队列 {chunks_put} 块")

                else:
                    _safe_print("[VoiceAudio] [WARN] Piper voice 没有 synthesize 方法")
                    audio_queue.put(None)

            except Exception as e:
                logger.error(f"[VoiceAudio] Producer 异常: {e}", exc_info=True)
                traceback.print_exc()
            finally:
                # 确保队列被标记为结束
                try:
                    audio_queue.put(None, block=False)
                    _safe_print("[VoiceAudio] Producer: 发送结束信号到队列")
                except Exception as e:
                    logger.error(f"[VoiceAudio] Producer: 发送结束信号失败: {e}", exc_info=True)
                # 清理资源
                if wav_io:
                    try:
                        wav_io.close()
                    except Exception as e:
                        logger.error(f"[VoiceAudio] Producer: 关闭 WAV IO 失败: {e}", exc_info=True)

        # ========== Consumer: 播放音频 ==========
        def consumer():
            """
            【关键修复】消费者线程 - 播放音频数据
            修复内容：
            1. 移除双重锁嵌套
            2. 添加音频流刷新机制
            3. 增强错误处理和调试日志
            4. 【P0修复】增加重试机制，避免并发播报冲突导致流关闭时消费者停止
            5. 【Phase 1 Week 1 Fix】流关闭时检查受保护状态，受保护播报尝试恢复
            6. 【修复代理-11】添加中断标志检查，支持平滑中断
            """
            chunks_played = 0
            total_bytes = 0
            errors = 0
            stream_was_closed_by_other = False  # 标记流是否被外部关闭
            recovery_attempts = 0  # 恢复尝试次数
            max_recovery_attempts = 5  # 最大恢复尝试次数

            # 从配置读取（如config可用）
            try:
                from core.config import config
                max_errors = config.get("voice.audio.max_errors", 10)
                retry_interval = config.get("voice.audio.retry_interval_ms", 50) / 1000
            except Exception:
                max_errors = 10
                retry_interval = 0.05

            consecutive_unavailable = 0

            _safe_print("[VoiceAudio] Consumer: 播放线程启动")

            try:
                while True:
                    # 【修复代理-11】检查中断标志（高优先级打断低优先级）
                    if self._should_stop_current:
                        logger.info("[VoiceAudio] Consumer: 收到平滑中断信号，停止当前播报")
                        break

                    # 检查停止信号
                    if self._stop_event is not None and self._stop_event.is_set():
                        _safe_print("[VoiceAudio] Consumer: 收到停止信号")
                        break

                    # 从队列获取音频块
                    try:
                        chunk = audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # 结束信号
                    if chunk is None:
                        _safe_print(f"[VoiceAudio] Consumer: 收到结束信号，共播放 {chunks_played} 块")
                        break

                    # 【P0修复】改进的流可用性检查 - 增加重试机制
                    stream_ready = False
                    with self._stream_lock:
                        if self._audio_stream and self._audio_stream.is_active():
                            stream_ready = True
                            consecutive_unavailable = 0
                        else:
                            consecutive_unavailable += 1
                            # 检查流是否被外部关闭
                            stream_exists = self._audio_stream is not None
                            if stream_exists and not self._audio_stream.is_active():
                                stream_was_closed_by_other = True

                            if consecutive_unavailable > 3:
                                errors += 1
                                consecutive_unavailable = 0
                                logger.error(f"[VoiceAudio] Consumer: 音频流连续不可用，错误计数={errors}/{max_errors}, "
                                           f"流存在={stream_exists}, 被外部关闭={stream_was_closed_by_other}")

                    if errors > max_errors:
                        # 【Phase 1 Week 1 Fix】错误次数过多时检查受保护状态
                        with self.speaking_lock:
                            is_protected = self._current_speak_protected
                        if is_protected and recovery_attempts < max_recovery_attempts:
                            logger.warning(f"[VoiceAudio] Consumer: 播报受保护，尝试恢复音频流 ({recovery_attempts+1}/{max_recovery_attempts})")
                            self._cleanup_audio_resources()
                            time.sleep(0.1)
                            recovery_attempts += 1
                            errors = max(0, errors - 3)  # 减少错误计数，给予恢复机会
                            continue
                        logger.error("[VoiceAudio] Consumer 错误次数过多，停止播放")
                        break

                    # 流未就绪时跳过，等待重试
                    if not stream_ready:
                        # 【Phase 1 Week 1 Fix】流未就绪时检查受保护状态
                        with self.speaking_lock:
                            is_protected = self._current_speak_protected
                        if is_protected and recovery_attempts < max_recovery_attempts and stream_was_closed_by_other:
                            logger.warning(f"[VoiceAudio] Consumer: 播报受保护且流被外部关闭，尝试恢复 ({recovery_attempts+1}/{max_recovery_attempts})")
                            self._cleanup_audio_resources()
                            time.sleep(0.1)
                            recovery_attempts += 1
                            consecutive_unavailable = 0
                            continue
                        time.sleep(retry_interval)  # 从配置读取的等待时间，避免CPU 100%
                        continue

                    # 在锁外部写入音频数据（减少锁持有时间）
                    try:
                        chunk_bytes = chunk.tobytes()

                        # 【P0修复】写入时增加异常恢复
                        with self._stream_lock:
                            if not (self._audio_stream and self._audio_stream.is_active()):
                                stream_exists = self._audio_stream is not None
                                stream_was_closed_by_other = stream_exists and not self._audio_stream.is_active()

                                # 【Phase 1 Week 1 Fix】流关闭时检查受保护状态
                                with self.speaking_lock:
                                    is_protected = self._current_speak_protected
                                if is_protected and recovery_attempts < max_recovery_attempts and stream_was_closed_by_other:
                                    logger.warning(f"[VoiceAudio] Consumer: 播报受保护，尝试恢复音频流 ({recovery_attempts+1}/{max_recovery_attempts})")
                                    recovery_attempts += 1
                                    errors = max(0, errors - 1)  # 减少错误计数
                                    continue

                                logger.error(f"[VoiceAudio] Consumer: 写入前流已关闭，流存在={stream_exists}, "
                                           f"被外部关闭={stream_was_closed_by_other}, chunks_played={chunks_played}")
                                errors += 1
                                if errors > max_errors:
                                    logger.error("[VoiceAudio] Consumer 错误次数过多，停止播放")
                                    break
                                continue
                            self._audio_stream.write(chunk_bytes)
                            chunks_played += 1
                            total_bytes += len(chunk_bytes)
                            recovery_attempts = 0  # 成功写入，重置恢复计数

                            # 每10块打印一次进度
                            if chunks_played % 10 == 0:
                                _safe_print(f"[VoiceAudio] Consumer: 已播放 {chunks_played} 块，{total_bytes} bytes")

                    except Exception as e:
                        stream_exists = self._audio_stream is not None if self._audio_stream else False
                        logger.error(f"[VoiceAudio] 播放块失败: {e}, 流存在={stream_exists}, "
                                   f"chunks_played={chunks_played}, total_bytes={total_bytes}", exc_info=True)
                        errors += 1
                        if errors > max_errors:
                            # 【Phase 1 Week 1 Fix】错误次数过多时检查受保护状态
                            with self.speaking_lock:
                                is_protected = self._current_speak_protected
                            if is_protected and recovery_attempts < max_recovery_attempts:
                                logger.warning(f"[VoiceAudio] Consumer: 播报受保护，尝试恢复 ({recovery_attempts+1}/{max_recovery_attempts})")
                                recovery_attempts += 1
                                errors = max(0, errors - 3)
                                continue
                            logger.error("[VoiceAudio] Consumer 错误次数过多，停止播放")
                            break

            except Exception as e:
                logger.error(f"[VoiceAudio] Consumer 异常: {e}", exc_info=True)
                traceback.print_exc()
            finally:
                _safe_print(f"[VoiceAudio] Consumer: 播放线程结束，共播放 {chunks_played} 块")
                # 【修复代理-11】Consumer结束时重置中断标志
                self._should_stop_current = False

        # ========== 播放控制 ==========
        def play_audio():
            _safe_print(f"\n{'='*60}")
            _safe_print("[VoiceAudio] === 开始播放音频 ===")
            _safe_print(f"{'='*60}\n")

            prod_thread = threading.Thread(target=producer, daemon=True, name="PiperProducer")
            cons_thread = threading.Thread(target=consumer, daemon=True, name="PiperConsumer")

            prod_thread.start()
            cons_thread.start()

            _safe_print("[VoiceAudio] Producer 和 Consumer 线程已启动")

            # 等待播放完成
            cons_thread.join(timeout=30)

            if cons_thread.is_alive():
                _safe_print("[VoiceAudio] [WARN] Consumer 线程超时，强制停止")
                self._stop_event.set()
                cons_thread.join(timeout=2)

            # 确保生产者线程也结束
            if prod_thread.is_alive():
                prod_thread.join(timeout=2)

            # 【关键修复】刷新并关闭音频流，确保数据写入设备
            _safe_print("[VoiceAudio] 正在刷新音频流...")
            with self._stream_lock:
                if self._audio_stream:
                    try:
                        # 【关键】停止流，确保所有缓冲区数据被刷新到设备
                        if self._audio_stream.is_active():
                            self._audio_stream.stop_stream()
                            _safe_print("[VoiceAudio] 音频流已停止")

                        self._audio_stream.close()
                        _safe_print("[VoiceAudio] 音频流已关闭")
                    except Exception as e:
                        logger.error(f"[VoiceAudio] 关闭音频流时出错: {e}", exc_info=True)
                    finally:
                        self._audio_stream = None

            # 清理事件对象
            self._stop_event = None

            # 强制垃圾回收
            gc.collect()

            _safe_print(f"\n{'='*60}")
            _safe_print("[VoiceAudio] === 播放结束 ===")
            _safe_print(f"{'='*60}\n")

            # 等待0.8秒让声音消散
            time.sleep(0.8)

            # 重置标志
            with self.speaking_lock:
                self.is_speaking = False
                self._is_system_speaking = False
                self._last_speak_end_time = time.time()
            _safe_print("[VoiceAudio] is_speaking reset to False")

        if wait:
            play_audio()
        else:
            threading.Thread(target=play_audio, daemon=True).start()

    def _get_output_device_index(self):
        """
        获取输出设备索引，支持配置指定或自动选择

        Returns:
            int or None: 设备索引或 None 如果无可用设备
        """
        try:
            device_count = self._pyaudio.get_device_count()
            # [已删除] 音频设备列表打印，减少日志噪音

            # 首先尝试使用配置指定的设备
            config_device_index = config.get("voice.output_device_index", None)
            if config_device_index is not None:
                try:
                    device_info = self._pyaudio.get_device_info_by_index(config_device_index)
                    if device_info['maxOutputChannels'] > 0:
                        _safe_print(f"[VoiceAudio] 使用配置指定的输出设备 {config_device_index}: {device_info['name']}")
                        return config_device_index
                except Exception as e:
                    _safe_print(f"[VoiceAudio] 配置指定的设备 {config_device_index} 不可用: {e}")

            # 列出所有输出设备
            output_devices = []
            for i in range(device_count):
                try:
                    dev = self._pyaudio.get_device_info_by_index(i)
                    if dev['maxOutputChannels'] > 0:
                        output_devices.append((i, dev))
                        # [已删除] 音频设备详情打印，减少日志噪音
                except Exception:
                    continue

            # 尝试获取默认输出设备
            try:
                default_device = self._pyaudio.get_default_output_device_info()
                default_index = None
                for i, dev in output_devices:
                    if dev['name'] == default_device['name']:
                        default_index = i
                        break

                if default_index is not None:
                    _safe_print(f"[VoiceAudio] 使用默认输出设备 {default_index}: {default_device['name']}")
                    return default_index
            except Exception as e:
                _safe_print(f"[VoiceAudio] 获取默认输出设备失败: {e}")

            # 如果没有默认设备，选择第一个有输出通道的设备
            if output_devices:
                idx, dev = output_devices[0]
                _safe_print(f"[VoiceAudio] 使用第一个可用输出设备 {idx}: {dev['name']}")
                return idx

            logger.error("[VoiceAudio] 没有找到可用的输出设备!")
            return None

        except Exception as e:
            logger.error(f"[VoiceAudio] 获取输出设备信息失败: {e}", exc_info=True)
            return None

    def test_audio_output(self, device_index=None):
        """
        测试音频输出设备是否正常工作

        Args:
            device_index: 要测试的设备索引，None 使用默认设备

        Returns:
            bool: 测试是否成功
        """
        _safe_print(f"\n{'='*60}")
        _safe_print("[VoiceAudio] 开始测试音频输出...")
        _safe_print(f"{'='*60}\n")

        try:
            # 生成测试音频（1kHz正弦波，0.5秒）
            sample_rate = 22050
            duration = 0.5
            frequency = 1000

            import numpy as np
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            audio = np.sin(2 * np.pi * frequency * t) * 32767
            audio = audio.astype(np.int16)

            # 确保 PyAudio 已初始化
            if not self._pyaudio:
                self._pyaudio = pyaudio.PyAudio()

            # 打开音频流
            stream_kwargs = {
                'format': pyaudio.paInt16,
                'channels': 1,
                'rate': sample_rate,
                'output': True,
                'frames_per_buffer': 1024
            }

            if device_index is not None:
                stream_kwargs['output_device_index'] = device_index
                _safe_print(f"[VoiceAudio] 使用设备索引: {device_index}")
            else:
                # 使用默认设备
                try:
                    default_device = self._pyaudio.get_default_output_device_info()
                    _safe_print(f"[VoiceAudio] 使用默认设备: {default_device['name']}")
                except Exception as e:
                    _safe_print(f"[VoiceAudio] [WARN] 无法获取默认设备: {e}")

            stream = self._pyaudio.open(**stream_kwargs)

            _safe_print("[VoiceAudio] 播放测试音频...")

            # 写入音频数据
            chunk_size = 1024
            for i in range(0, len(audio), chunk_size):
                chunk = audio[i:i + chunk_size]
                stream.write(chunk.tobytes())

            # 【关键】停止流确保数据被刷新
            stream.stop_stream()
            stream.close()

            _safe_print("[VoiceAudio] [OK] 测试音频播放完成")
            return True

        except Exception as e:
            logger.error(f"[VoiceAudio] 测试音频输出失败: {e}", exc_info=True)
            return False

    def _speak_with_indextts_stream(self, text):
        # 【修复】设置 is_speaking 标志
        with self.speaking_lock:
            self.is_speaking = True
            self._is_system_speaking = True
        _safe_print("[Voice] is_speaking set to True (IndexTTS)")

        with self.speaking_lock:
            if not self.tts_engine or not self.speaker_wav:
                self._speak_fallback(text, True)
                # 【修复】fallback后重置标志
                with self.speaking_lock:
                    self.is_speaking = False
                    self._is_system_speaking = False
                _safe_print("[Voice] is_speaking reset to False (IndexTTS fallback)")
                return

        try:
            self._stop_event = threading.Event()
            audio_queue = queue.Queue(maxsize=20)
            sample_rate = 22050

            with self._stream_lock:
                if self._audio_stream is not None:
                    self._audio_stream.stop_stream()
                    self._audio_stream.close()
                self._audio_stream = self._pyaudio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    output=True,
                    frames_per_buffer=1024
                )

            def producer():
                try:
                    audio_gen = self.tts_engine.infer(
                        spk_audio_prompt=self.speaker_wav,
                        text=text,
                        output_path=None,
                        stream_return=True,
                        num_beams=1,
                        max_mel_tokens=1800,
                        max_text_tokens_per_segment=200,
                        do_sample=False,
                        verbose=False
                    )
                    for audio_chunk in audio_gen:
                        if self._stop_event is None or self._stop_event.is_set():
                            break
                        if hasattr(audio_chunk, 'cpu'):
                            audio_chunk = audio_chunk.cpu().numpy()
                        audio_chunk = np.squeeze(audio_chunk).astype(np.int16)
                        audio_queue.put(audio_chunk)
                except Exception as e:
                    logger.error(f"[Voice] IndexTTS 合成异常: {e}", exc_info=True)
                finally:
                    audio_queue.put(None)

            def consumer():
                errors = 0
                max_errors = 10  # 错误阈值
                recovery_attempts = 0  # 【Phase 1 Week 1 Fix】恢复尝试计数
                max_recovery_attempts = 5

                while True:
                    try:
                        chunk = audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        if self._stop_event is None or self._stop_event.is_set():
                            break
                        time.sleep(0.01)  # 避免忙等
                        continue

                    if chunk is None:
                        break

                    try:  # 添加异常捕获
                        with self._stream_lock:
                            if self._audio_stream and self._audio_stream.is_active():
                                self._audio_stream.write(chunk.tobytes())
                                recovery_attempts = 0  # 成功写入，重置恢复计数
                    except Exception as e:
                        errors += 1
                        # 【Phase 1 Week 1 Fix】检查受保护状态
                        with self.speaking_lock:
                            is_protected = self._current_speak_protected
                        if is_protected and recovery_attempts < max_recovery_attempts and errors > max_errors // 2:
                            logger.warning(f"[VoiceAudio] IndexTTS Consumer: 播报受保护，尝试恢复 ({recovery_attempts+1}/{max_recovery_attempts})")
                            recovery_attempts += 1
                            errors = max(0, errors - 2)
                            time.sleep(0.05)
                            continue
                        logger.error(f"[VoiceAudio] IndexTTS Consumer 播放失败: {e}")  # ERROR日志
                        if errors > max_errors:
                            logger.error("[VoiceAudio] IndexTTS Consumer 错误次数过多，停止")  # ERROR日志
                            break
                with self._stream_lock:
                    if self._audio_stream:
                        try:
                            self._audio_stream.stop_stream()
                            self._audio_stream.close()
                        except Exception as e:
                            logger.error(f"[Voice] IndexTTS 关闭音频流失败: {e}", exc_info=True)
                        self._audio_stream = None
                    # 【修复】释放 PyAudio
                    if self._pyaudio:
                        try:
                            self._pyaudio.terminate()
                        except Exception as e:
                            logger.error(f"[Voice] IndexTTS 终止 PyAudio 失败: {e}", exc_info=True)
                        self._pyaudio = None

            prod_thread = threading.Thread(target=producer, daemon=True)
            cons_thread = threading.Thread(target=consumer, daemon=True)
            prod_thread.start()
            cons_thread.start()
            cons_thread.join()
            prod_thread.join(timeout=1)
            self._stop_event = None

            # 【修复】等待0.8秒让声音消散
            time.sleep(0.8)
        finally:
            # 【修复】确保在任何情况下都重置标志
            with self.speaking_lock:
                self.is_speaking = False
                self._is_system_speaking = False
            _safe_print("[Voice] is_speaking reset to False (IndexTTS)")

    async def _speak_edge(self, text):
        try:
            import edge_tts
            import playsound
            communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            temp_file = os.path.join(self.output_dir, f"temp_edge_{int(time.time())}.mp3")
            # S-3 Fix: 添加30秒超时，防止网络挂起阻塞播报队列
            await asyncio.wait_for(communicate.save(temp_file), timeout=30)
            playsound.playsound(temp_file)
            await asyncio.to_thread(os.remove, temp_file)
        except asyncio.TimeoutError:
            logger.error("[Voice] Edge TTS 超时（30秒），降级到备用引擎")
            self._speak_fallback(text, True)
        except Exception as e:
            logger.error(f"[Voice] Edge TTS 失败: {e}", exc_info=True)
            self._speak_fallback(text, True)

    def _speak_fallback(self, text, wait):
        _safe_print(f"[_speak_fallback] 进入，text={text[:50]}...，wait={wait}")
        _safe_print(f"[_speak_fallback] 引擎实例：{self._fallback_engine is not None}，当前锁状态：{self._fallback_lock.locked()}")

        # 【修复】设置 is_speaking 标志
        with self.speaking_lock:
            self.is_speaking = True
            self._is_system_speaking = True
        _safe_print("[Voice] is_speaking set to True (fallback)")

        if self._fallback_engine:
            try:
                if wait:
                    with self._fallback_lock:
                        try:
                            full_text = text.strip()
                            if not full_text:
                                _safe_print("[WARN] 传入文本为空，跳过播报")
                                return
                            _safe_print(f">>> 调用 say()（文本长度：{len(full_text)}字）")
                            self._fallback_engine.say(full_text)
                            _safe_print(">>> say() 执行完成")
                            _safe_print(">>> 调用 runAndWait()")
                            # 【修复】pyttsx3.runAndWait() 在某些系统上会无限阻塞，使用带超时的线程避免卡死
                            import threading
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
                                _safe_print(f">>> runAndWait() 超时（{_timeout}s），强制停止引擎")
                                try:
                                    self._fallback_engine.stop()
                                except Exception as _stop_err:
                                    _safe_print(f">>> stop() 失败: {_stop_err}")
                            else:
                                _safe_print(">>> runAndWait() 执行完成")
                            if _run_exc:
                                raise _run_exc
                            _safe_print(">>> 调用 stop() 重置引擎")
                            self._fallback_engine.stop()
                            _safe_print(">>> stop() 执行完成，引擎状态重置")

                            # 【内存优化】定期重新初始化引擎以释放累积内存
                            # pyttsx3在某些系统上会有内存泄漏，每10次播报后重新初始化
                            if not hasattr(self, '_fallback_use_count'):
                                self._fallback_use_count = 0
                            self._fallback_use_count += 1
                            if self._fallback_use_count >= 10:
                                _safe_print("[Voice] 备用引擎使用次数达到阈值，重新初始化以释放内存")
                                try:
                                    self._fallback_engine = None
                                    import gc
                                    gc.collect()
                                    self._init_fallback(force_reinit=True)
                                    self._fallback_use_count = 0
                                except Exception as reinit_err:
                                    _safe_print(f"[Voice] 引擎重新初始化失败: {reinit_err}")

                        except Exception as e:
                            logger.error(f"[Voice] 播报过程异常: {e}", exc_info=True)
                            self._fallback_engine.stop()
                            _safe_print(">>> 异常后强制重置引擎")
                else:
                    def _speak_fallback_thread(t, sys_flag):
                        try:
                            self._speak_fallback(t, sys_flag)
                        except Exception as thread_err:
                            _safe_print(f"[CRITICAL ERROR][Voice] speak_fallback 后台线程未捕获异常: {thread_err}", file=sys.stderr)
                    threading.Thread(
                        target=_speak_fallback_thread,
                        args=(text, True),
                        daemon=True
                    ).start()
            except Exception as e:
                logger.error(f"[Voice] _speak_fallback 外层异常: {e}", exc_info=True)
                self._init_fallback(force_reinit=True)
            finally:
                # 【修复】等待0.8秒让声音消散，然后重置标志
                time.sleep(0.8)
                with self.speaking_lock:
                    self.is_speaking = False
                    self._is_system_speaking = False
                _safe_print("[Voice] is_speaking reset to False (fallback)")
        else:
            _safe_print(f"[TTS] {text}")
            # 【修复】没有引擎时也要重置标志
            time.sleep(0.8)
            with self.speaking_lock:
                self.is_speaking = False
                self._is_system_speaking = False
            _safe_print("[Voice] is_speaking reset to False (fallback, no engine)")

    def _player_worker(self):
        while True:
            audio_file = self._play_queue.get()
            if audio_file is None:
                break
            try:
                import playsound
                playsound.playsound(audio_file)
            except Exception as e:
                logger.error(f"[Voice] 播放音频文件失败 '{audio_file}': {e}", exc_info=True)

    def _speak_worker(self):
        """语音播报工作线程 - 实现排队和优先级机制

        【TTS音频流冲突修复】关键修改：
        - 使用 _playback_lock 确保音频设备一次只被一个播报占用
        - 无论 wait=True/False，音频串行播放，防止音频流重叠导致的断断续续
        - wait=False 只影响调用者是否等待，不影响音频本身的串行性
        """
        while True:
            try:
                item = self._speak_queue.get()
                if item is None:
                    break

                # 【Phase 1 Week 1 Fix】使用 SpeakItem 对象
                text = item.text
                wait = item.wait
                priority = -item.priority  # 转回原始优先级（0=最高AI输出，1=系统，2=最低过程播报）
                protected = item.protected

                # 【修复代理-11】处理被中断后的清理
                if self._should_stop_current:
                    logger.debug("[Voice] Worker: 检测到中断标志，清理后处理下一项")
                    self._should_stop_current = False
                    # 短暂等待确保资源清理完成
                    time.sleep(0.1)

                # 【Phase 1 Week 1 Fix】检查是否被高优先级打断，但保护受保护项
                should_skip = False
                with self.speaking_lock:
                    if self.is_speaking and priority < self._current_speak_priority:
                        # 如果当前播报受保护，不允许被打断
                        if self._current_speak_protected:
                            _safe_print(f"[Voice] 当前播报受保护，高优先级项排队: {text[:20]}...")
                            # 重新放入队列稍后再试
                            self._speak_queue.enqueue(text, wait, priority, protected)
                            time.sleep(0.5)  # 短暂等待后重试
                            should_skip = True
                        else:
                            _safe_print(f"[Voice] 低优先级播报被跳过: {text[:20]}...")
                            should_skip = True
                    else:
                        self._current_speak_priority = priority
                        self._current_speak_protected = protected

                # 【TTS音频流冲突修复】如果需要跳过，先标记任务完成再continue
                if should_skip:
                    self._speak_queue.task_done()
                    continue

                # 【TTS音频流冲突修复】获取播放锁，确保音频串行播放
                # 这防止多个播报同时占用音频设备导致的断断续续问题
                acquired_lock = False
                try:
                    # 等待获取播放锁（阻塞直到前一个播报完成）
                    self._playback_lock.acquire()
                    acquired_lock = True
                    logger.debug(f"[Voice] Worker: 获取播放锁，开始播报: {text[:30]}...")

                    # 执行实际播报
                    self._do_speak(text, wait=True, priority=priority, protected=protected)  # 强制wait=True确保锁持有到播放完成

                except Exception as e:
                    logger.error(f"[Voice] Worker: 播报执行异常: {e}", exc_info=True)
                finally:
                    if acquired_lock:
                        self._playback_lock.release()
                        logger.debug("[Voice] Worker: 释放播放锁")

                # 【状态同步】播报完成
                try:
                    state_sync = get_voice_state_sync()
                    state_sync.on_stop_speaking()
                except Exception as e:
                    logger.error(f"[Voice] 状态同步失败: {e}", exc_info=True)

                # 【修复代理-16】【修复代理-01】Talk Mode：AI回复播报完成后触发继续监听
                try:
                    # 【修复代理-01】【BUG-2 Fix】使用_talk_mode_lock保护in_talk_mode读写
                    with self._talk_mode_lock:
                        in_talk_mode_local = self.in_talk_mode

                    if in_talk_mode_local and priority == 0:  # 0=AI输出播报
                        logger.info("[TalkMode] AI回复播报完成，触发继续监听")
                        self.on_ai_response_complete()
                except Exception as e:
                    logger.error(f"[TalkMode] 播报完成回调失败: {e}", exc_info=True)

                finally:
                    # 【Phase 1 Week 1 Fix】标记任务完成并清理当前项
                    self._speak_queue.task_done()
                    self._speak_queue.set_current_item(None)
                    # 【修复】重置当前播报优先级，避免影响后续播报判断
                    with self.speaking_lock:
                        self._current_speak_priority = 0
                        self._current_speak_protected = False

            except Exception as e:
                logger.error(f"[Voice] 播报工作线程异常: {e}", exc_info=True)
                # 【Phase 1 Week 1 Fix】异常时也清理状态
                with contextlib.suppress(Exception):
                    self._speak_queue.task_done()

    def _init_system_state_subscriptions(self):
        """订阅 SystemState 变化，建立反射弧"""
        if self._system_state_initialized:
            return
        try:
            from core.runtime import system_state
            system_state.subscribe("vision.alert", self._on_perception_alert)
            system_state.subscribe("consciousness.life_state", self._on_emotion_change)
            self._system_state_initialized = True
            logger.info("[Voice] SystemState 反射弧订阅已建立")
        except Exception as e:
            logger.warning(f"[Voice] SystemState 订阅失败: {e}")

    def _on_perception_alert(self, path, value):
        """视觉告警反射：立刻打断语音"""
        if value is None:
            return
        try:
            alert_level = value.get("level", "L1") if isinstance(value, dict) else "L1"
            if alert_level in ("L2", "L3", "CRITICAL") and self.is_speaking:
                self._should_stop_current = True
                # 插入紧急打断播报
                self._speak_queue.enqueue("等等——", priority=0, protected=False)
                logger.info(f"[Voice-Reflex] 视觉告警({alert_level})触发语音打断")
        except Exception as e:
            logger.warning(f"[Voice-Reflex] 告警处理异常: {e}")

    def _on_emotion_change(self, path, value):
        """情绪变化反射：调整语音参数（当前只记录，由 _do_speak 读取）"""
        # 情绪状态被写入 system_state，_do_speak 在播报前读取
        pass

    def _apply_emotion_to_speech(self, text: str) -> str:
        """根据 SystemState 中的情绪状态，调整播报文本和参数"""
        try:
            from core.runtime import system_state
            life_state = system_state.get_sync("consciousness.life_state", {})
            energy = life_state.get("energy", 1.0)
            mood = life_state.get("mood", "平静")

            # 能量低时插入填充词、增加停顿
            if energy < 0.3 and not text.startswith("嗯"):
                text = "嗯……" + text
            elif energy < 0.6 and not text.startswith("嗯"):
                text = "让我看看…… " + text

            # 焦虑时降低语速标记（Piper SSML / pyttsx3 rate 由调用方处理）
            # 这里仅做文本层标记，TTS 引擎层在 _speak_with_piper_tts 等中读取
            if mood in ["焦虑", "紧张"]:
                text = text.replace("。", "。<break time='300ms'/>")

            return text
        except Exception:
            return text

    def _do_speak(self, text, wait, priority, protected=False):
        """
        实际的播报逻辑（从原 speak 方法提取，带播放状态检查）

        Args:
            text: 播报文本
            wait: 是否等待播报完成
            priority: 优先级（0=普通，1=系统，2=紧急）
            protected: 是否受保护
        """
        # 【反射弧】情绪驱动的文本预处理
        text = self._apply_emotion_to_speech(text)

        # 写入 SystemState，供动作层读取
        try:
            from core.runtime import system_state
            system_state.set_sync("speech.current_text", text)
            system_state.set_sync("speech.is_speaking", True)
        except Exception:
            pass

        # 【P2a】注册到 ActionCoordinator，让协调器知道语音正在播报
        _coord_slot = None
        try:
            from core.coordination import get_action_coordinator
            from core.coordination.action_coordinator import ActionType
            coordinator = get_action_coordinator()
            if not coordinator._subscriptions_setup:
                coordinator.setup_subscriptions()
            _coord_slot = coordinator.register_sync(
                action_id=f"speech_{id(self)}_{time.time()}",
                action_type=ActionType.SPEECH,
                priority=2,
                payload={"text": text[:50]}
            )
        except Exception as _coord_e:
            logger.debug(f"[Voice] ActionCoordinator 注册失败: {_coord_e}")

        _safe_print("[Voice] === 开始语音播报 ===")
        _safe_print(f"[Voice] 播报内容: {text[:50]}{'...' if len(text) > 50 else ''}")
        _safe_print(f"[Voice] 引擎: {config.get('voice.tts_engine', 'piper')}, 等待: {wait}, 受保护: {protected}")

        # 检查可用的 TTS 引擎
        current_engine = config.get("voice.tts_engine", "piper")
        piper_available = self._piper_voice is not None
        indextts_available = self.tts_engine is not None and self.speaker_wav is not None
        fallback_available = self._fallback_engine is not None

        _safe_print(f"[Voice] 引擎状态 - Piper: {piper_available}, IndexTTS: {indextts_available}, 备用: {fallback_available}")

        # 检查扬声器状态
        try:
            if self._pyaudio:
                try:
                    default_output = self._pyaudio.get_default_output_device_info()
                    _safe_print(f"[Voice] 扬声器设备: {default_output['name']}")
                except Exception as e:
                    logger.warning(f"[Voice] 无法获取扬声器信息: {e}")
        except Exception as e:
            logger.error(f"[Voice] 检查扬声器状态失败: {e}", exc_info=True)

        # 如果没有可用引擎，给出文本提示
        if not piper_available and not indextts_available and not fallback_available:
            _safe_print(f"\n{'='*40}")
            _safe_print(f"[系统提示] 🤖 {text}")
            _safe_print(f"{'='*40}\n")
            _safe_print("[Voice] [WARN] 没有可用的 TTS 引擎，已输出文本提示")
            return False

        success = False
        try:
            if current_engine == "piper" and self._piper_voice:
                _safe_print("[Voice] 使用 Piper TTS 引擎")
                self._speak_with_piper_tts(text, wait)
                _safe_print("[语音] 【成功】 Piper TTS 播报完成")
                success = True
            elif current_engine == "indextts" and self.tts_engine and self.speaker_wav:
                _safe_print("[Voice] 使用 IndexTTS 引擎")
                self._speak_with_indextts_stream(text)
                _safe_print("[语音] 【成功】 IndexTTS 播报完成")
                success = True
            else:
                _safe_print("[Voice] 使用备用 TTS 引擎")
                self._speak_fallback(text, wait)
                _safe_print("[语音] 【成功】 备用引擎播报完成")
                success = True
        except TTSInitError as e:
            logger.error(f"[Voice] TTS初始化失败: {e}", exc_info=True)
            raise VoiceInitError(f"语音初始化失败: {e}") from e
        except VoiceInitError:
            raise
        except VoiceSpeakError:
            raise
        except Exception as e:
            logger.error(f"[Voice] 播报失败 '{text[:50]}...': {e}", exc_info=True)
            # 【ExperienceBus】TTS 播报失败
            with contextlib.suppress(Exception):
                event_bus.emit("voice:tts_failed", {
                    "text": text[:100],
                    "engine": config.get("voice.tts_engine", "piper"),
                    "error": str(e),
                    "timestamp": time.time(),
                })
            raise VoiceSpeakError(f"语音播报失败: {e}") from e
        finally:
            _safe_print(f"[Voice] === 语音播报结束 (状态: {'成功' if success else '失败'}) ===")
            # 【Phase 1 Week 1 Fix】播报完成后重置受保护状态
            with self.speaking_lock:
                self._current_speak_protected = False
            # 反射弧：播报结束，更新 SystemState
            try:
                from core.runtime import system_state
                system_state.set_sync("speech.is_speaking", False)
                system_state.set_sync("speech.current_text", "")
            except Exception:
                pass
            # 【P2a】通知 ActionCoordinator 语音播报结束
            try:
                if _coord_slot:
                    from core.coordination import get_action_coordinator
                    coordinator = get_action_coordinator()
                    coordinator.complete_sync(_coord_slot.action_id)
            except Exception as _coord_e:
                logger.debug(f"[Voice] ActionCoordinator 完成通知失败: {_coord_e}")

        return success

    def _play_wake_feedback(self, skip_reset: bool = False):
        """
        播放唤醒反馈"我在"（带状态检查和确认机制）

        Args:
            skip_reset: 如果为True，跳过识别器重置（由WakeWordHandler已处理）
                       Bug #1修复: 避免双重重置竞争条件
        """  # [P1-001] 符合大纲要求：语音唤醒播报"我在"
        _safe_print("[Voice] 正在播放唤醒反馈: 我在")  # [P1-001] 符合大纲要求

        # 【修复】设置系统播报标志，避免被识别为回声
        # 延长保护时间到3秒，确保声音完全消散
        with self.speaking_lock:
            self._is_system_speaking = True
            self._last_spoken_text = "我在"
            self._last_speak_time = time.time()

        # 确保备用引擎已初始化（如果 Piper 不可用）
        if not self._piper_voice and not self._fallback_engine:
            self._ensure_fallback_engine()

        # 尝试播放唤醒反馈（非阻塞，避免阻塞监听线程）
        from voice.voice_prompts import SystemAnnouncements
        success = self._do_speak(SystemAnnouncements.WAKE_WORD_DETECTED, wait=False, priority=1)  # [P1-001] 符合大纲要求，改为非阻塞：语音唤醒播报

        if success:
            _safe_print("[语音] 【成功】 唤醒反馈播放成功")
        else:
            # 播放失败时给出文本提示
            _safe_print("\n" + "="*40)
            _safe_print("[系统提示] 🤖 我在")  # [P1-001] 符合大纲要求
            _safe_print("="*40 + "\n")
            _safe_print("[Voice] [WARN] 唤醒反馈播放失败，已输出文本提示")

        # 【Phase 1 Week 1 - Bug #1修复】启动延迟线程，5秒后清除系统播报标志
        # 如果skip_reset为True，表示WakeWordHandler已处理重置，这里不再重复
        def delayed_clear():
            time.sleep(5.0)  # 5秒保护窗口

            # Bug #1修复: 根据skip_reset决定是否重置识别器
            # 避免与WakeWordHandler._triple_reset_recognizer的竞争条件
            if not skip_reset and self.recognizer:
                try:
                    # Bug #3修复: 使用与Handler相同的锁保护重置
                    if hasattr(self, '_wake_word_handler') and self._wake_word_handler:
                        with self._wake_word_handler._reset_lock:
                            self.recognizer.Reset()
                    else:
                        self.recognizer.Reset()
                    _safe_print("[Voice] 唤醒反馈保护窗口结束，识别器缓冲区已清空")
                except Exception as e:
                    _safe_print(f"[Voice] 识别器重置失败: {e}")
            elif skip_reset:
                _safe_print("[Voice] 唤醒反馈保护窗口结束（识别器重置已由Handler处理）")

            with self.speaking_lock:
                self._is_system_speaking = False
                self._last_speak_time = time.time()  # 更新时间，让后续检测能继续工作
            _safe_print("[Voice] 唤醒反馈保护窗口结束，恢复语音识别")

        threading.Thread(target=delayed_clear, daemon=True).start()

        return success

    # ========== 输入方式处理：语音唤醒模式和前端语音模式 ==========

    async def handle_wake_word_input(self, text: str):
        """
        语音唤醒模式输入处理
        唤醒后进入聊天对齐需求

        Args:
            text: 用户语音输入文本（已通过唤醒词触发）

        Returns:
            处理结果
        """
        from core.dialog.dialogue_manager import InputMode, dialogue_manager

        logger.info(f"[Voice] 唤醒模式输入: {text}")

        # 确保有当前会话ID
        if not hasattr(self, 'current_session_id') or not self.current_session_id:
            self.current_session_id = f"voice_{int(time.time())}"

        # 唤醒后进入聊天对齐
        return await dialogue_manager.handle_input(
            user_id="default",
            text=text,
            session_id=self.current_session_id,
            input_mode=InputMode.VOICE_WAKE,
            voice_instance=self
        )

    async def handle_frontend_voice_input(self, text: str, session_id: str):
        """
        前端语音输入处理
        点击录音图标，录音完成后发送给AI，进入聊天对齐

        Args:
            text: 用户语音输入文本（已通过前端录音识别）
            session_id: 会话ID

        Returns:
            处理结果
        """
        from core.dialog.dialogue_manager import InputMode, dialogue_manager

        logger.info(f"[Voice] 前端语音输入: {text}")

        # 更新当前会话ID
        self.current_session_id = session_id

        # 前端语音进入聊天对齐（P0：统一走 AUTO，由思维线程裁决）
        return await dialogue_manager.handle_input(
            user_id="default",
            text=text,
            session_id=session_id,
            input_mode=InputMode.AUTO,
            voice_instance=self
        )
