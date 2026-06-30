#!/usr/bin/env python3
"""
SiliconBase V5 - 统一启动程序（落地版本）
整合功能：HTTP API + WebSocket + 语音系统 + 心跳循环 + 状态监控
"""

import json
import os
import sys

# ========== DPI 感知设置（必须在任何 GUI/截图操作之前）==========
if sys.platform == "win32":
    try:
        from core.vision.dpi import set_process_dpi_aware
        set_process_dpi_aware()
    except Exception:
        pass

# 【P0修复】屏蔽 ONNX Runtime 图优化警告（模型格式兼容性提示，不影响推理）
os.environ["ORT_DISABLE_GRAPH_OPTIMIZATION_WARNINGS"] = "1"

# 【P1修复】WebSocket 心跳参数从环境变量读取，避免后端忙时误断
WS_PING_INTERVAL = float(os.getenv("UVICORN_WS_PING_INTERVAL", "30.0"))
WS_PING_TIMEOUT = float(os.getenv("UVICORN_WS_PING_TIMEOUT", "60.0"))

import asyncio
import atexit
import contextlib
import io
import shutil
import signal
import socket
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 【P0-ENV修复】ChromaDB 服务器自动启动
# ═══════════════════════════════════════════════════════════════════════════════
_chromadb_process = None  # type: Optional[subprocess.Popen]


def _is_port_open(host: str, port: int) -> bool:
    """检查端口是否已监听"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _start_chromadb_server() -> bool:
    """
    启动 ChromaDB 服务器（若未运行）。
    返回 True 表示服务器可用（已运行或成功启动）。
    """
    global _chromadb_process

    if _is_port_open("127.0.0.1", 8000):
        print("[ChromaDB] 127.0.0.1:8000 已监听，跳过启动")
        return True

    chroma_exe = shutil.which("chroma")
    if not chroma_exe:
        venv_chroma = BASE_DIR / ".venv" / "Scripts" / "chroma.exe"
        if venv_chroma.exists():
            chroma_exe = str(venv_chroma)

    if not chroma_exe:
        print("[ChromaDB 警告] 未找到 chroma CLI，跳过启动。向量同步将不可用。", file=sys.stderr)
        return False

    chroma_db_path = BASE_DIR / "data" / "chroma_db"
    chroma_db_path.mkdir(parents=True, exist_ok=True)

    try:
        _chromadb_process = subprocess.Popen(
            [
                chroma_exe,
                "run",
                "--path", str(chroma_db_path),
                "--host", "127.0.0.1",
                "--port", "8000",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR),
        )
        print(f"[ChromaDB] 已启动 ChromaDB 服务器，PID: {_chromadb_process.pid}")
    except Exception as e:
        print(f"[ChromaDB 警告] 启动失败: {e}", file=sys.stderr)
        return False

    # 轮询等待，最多 10 秒
    for _ in range(20):
        time.sleep(0.5)
        if _is_port_open("127.0.0.1", 8000):
            print("[ChromaDB] 服务器就绪，端口 8000")
            return True

    print("[ChromaDB 警告] 等待超时，服务器可能未正常启动", file=sys.stderr)
    return False


def _stop_chromadb_server() -> None:
    """关闭 ChromaDB 子进程"""
    global _chromadb_process
    if _chromadb_process is not None:
        try:
            _chromadb_process.terminate()
            _chromadb_process.wait(timeout=5)
            print("[ChromaDB] 服务器已关闭", file=sys.stderr)
        except Exception:
            with contextlib.suppress(Exception):
                _chromadb_process.kill()
        _chromadb_process = None


# 注册 atexit 清理（必须在进程退出前关闭子进程）
atexit.register(_stop_chromadb_server)


async def _warmup_ollama_models(config, logger) -> None:
    """
    后台异步预热 Ollama 模型（文本+视觉）。
    Ollama 是懒加载的，首次调用时如果模型不在内存会返回"尚未加载"。
    我们在系统启动时发一个轻量请求，让模型提前驻留 GPU。
    """
    try:
        # 只处理 Ollama 后端
        ollama_url = config.get("ai.ollama.base_url", "http://localhost:11434")
        if ":11434" not in ollama_url:
            logger.info("[Warmup] 后端非 Ollama，跳过预热")
            return

        import aiohttp

        # ── 1. 预热文本模型（AgentLoop 主 LLM）────────────────────
        # 【P0修复】配置键兼容：支持多种配置方式
        text_model = config.get("ai.text.model")
        _used_key = "ai.text.model"
        if not text_model:
            text_model = config.get("ai.model")
            _used_key = "ai.model"
        if not text_model:
            text_model = config.get("ai.default_model")
            _used_key = "ai.default_model"
        if not text_model:
            backend = config.get("ai.default_backend", "ollama")
            text_model = config.get(f"ai.backends.{backend}.model")
            _used_key = f"ai.backends.{backend}.model"
        if not text_model:
            text_model = config.get("ai.ollama.model")
            _used_key = "ai.ollama.model"

        if text_model:
            logger.info(f"[Warmup] 使用配置键 '{_used_key}'，正在预热 Ollama 文本模型: {text_model}...")
            try:
                async with aiohttp.ClientSession() as session, session.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": text_model,
                        "prompt": "hi",
                        "stream": False,
                        "options": {"num_predict": 2},
                    },
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"[Warmup] 文本模型 {text_model} 预热成功")
                    else:
                        body = await resp.text()
                        logger.warning(f"[Warmup] 文本模型预热 HTTP {resp.status}: {body[:200]}")
            except Exception as e:
                logger.warning(f"[Warmup] 文本模型预热失败: {e}")
        else:
            logger.info("[Warmup] 未配置文本模型，跳过预热")

        # ── 2. 预热视觉模型 ─────────────────────────────────────
        vision_model = config.get("ai.vision.model")
        if not vision_model:
            vision_model = config.get("ai.vision_model")
        if not vision_model:
            backend = config.get("ai.vision.default_backend", "ollama-vision")
            vision_model = config.get(f"ai.vision.backends.{backend}.model")

        if not vision_model:
            logger.info("[Warmup] 未配置视觉模型，跳过预热")
            return

        logger.info(f"[Warmup] 正在预热 Ollama 视觉模型: {vision_model}...")

        # 方式1：优先用 HTTP API 预热（纯文本，避免触发 qwen3-vl SmartResize panic）
        # 【修复】qwen3-vl 的 image processor 在图片尺寸 < 32px 时会 panic。
        # 预热只加载 text decoder，vision encoder 在首次带图调用时自动加载。
        try:
            async with aiohttp.ClientSession() as session, session.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": vision_model,
                    "prompt": "hi",
                    "stream": False,
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    logger.info(f"[Warmup] 视觉模型 {vision_model} 预热成功（text decoder）")
                else:
                    body = await resp.text()
                    logger.warning(f"[Warmup] 视觉模型预热 HTTP {resp.status}: {body[:200]}")
            return
        except ImportError:
            pass  # aiohttp 未安装，降级到 CLI

        # 方式2：降级用 ollama CLI 预热
        proc = await asyncio.create_subprocess_exec(
            "ollama", "run", vision_model,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc.stdin.write(b"/bye\n")
        await proc.stdin.drain()
        try:
            await asyncio.wait_for(proc.wait(), timeout=60)
            logger.info(f"[Warmup] 视觉模型 {vision_model} CLI 预热完成")
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("[Warmup] 视觉模型 CLI 预热超时")

    except Exception as e:
        logger.warning(f"[Warmup] 模型预热失败: {e}")


# 【P0修复】在导入任何项目模块之前加载 .env，确保环境变量正确
# 项目模块（如 core/db/connection_pool.py）在导入时就读取环境变量，
# 如果 .env 未加载，会读取到系统残留的错误值（如 POSTGRES_PASSWORD=siliconbase123）
try:
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).parent / '.env'
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path, interpolate=True, override=True)
        print(f"[EnvFix] .env 已加载: {_dotenv_path}")
except ImportError:
    pass

# ========== Windows 事件循环策略修复（P1） ==========
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print("[WindowsFix] 已设置 WindowsSelectorEventLoopPolicy")
# ========== Windows 事件循环策略修复 END ==========

# ========== 后台线程未捕获异常全局捕获 ==========
def _custom_threading_excepthook(args):
    """捕获所有后台线程的未捕获异常，写入独立文件，避免依赖 logging 模块"""
    try:
        crash_log_path = Path(__file__).parent / ".runtime" / "crash_dump.log"
        crash_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[THREAD CRASH] {datetime.now().isoformat()}\n")
            f.write(f"Thread: {args.thread.name if args.thread else 'unknown'}\n")
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=f)
            f.write(f"{'='*60}\n")
        # 同时打印到 stderr
        print(f"\n[CRITICAL ERROR] 后台线程 '{args.thread.name if args.thread else 'unknown'}' 发生未捕获异常，详情已写入: {crash_log_path}", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)
    except Exception as dump_err:
        # 如果连写入文件都失败，至少打印到 stderr
        print(f"[CRITICAL ERROR] 后台线程未捕获异常，且 crash dump 写入失败: {dump_err}", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)

threading.excepthook = _custom_threading_excepthook
# ========== 后台线程未捕获异常全局捕获 END ==========

# 强制UTF-8编码
# 【修复】使用 reconfigure() 原生修改编码，不创建新 TextIOWrapper，
# 避免旧对象 GC 时 close() 关闭共享底层 buffer 导致 segfault。
# 兼容 Python 3.7+；若不存在则回退到保留引用的旧方案。
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
else:
    _start_unified_original_stdout = sys.stdout
    _start_unified_original_stderr = sys.stderr
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ========== 基础配置 ==========
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ========== 全局状态 ==========
_shutdown_event = threading.Event()
_heartbeat_thread = None
_status_server = None
_voice_instance = None


def setup_signal_handlers():
    """设置信号处理器"""
    def signal_handler(signum, frame):
        print(f"\n[Signal] 收到信号 {signum}，正在优雅关闭...")
        _shutdown_event.set()
        shutdown_system()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):  # Windows
        signal.signal(signal.SIGBREAK, signal_handler)


async def init_core_systems():
    """初始化核心系统（不依赖HTTP服务）"""
    print("[Unified] 初始化核心系统...")

    # 1. 加载配置
    try:
        from dotenv import load_dotenv
        dotenv_path = BASE_DIR / '.env'
        if dotenv_path.exists():
            load_dotenv(dotenv_path, interpolate=True)
            print(f"[Unified] 环境变量加载完成: {dotenv_path}")
    except ImportError:
        print("[Unified 警告] python-dotenv 未安装")

    # 2. 初始化配置和日志
    from core.config import config
    from core.logger import logger

    # 3. 初始化数据库和记忆系统
    # NOTE: 旧模块 vector_memory/memory.py 已废弃。MemoryService 采用延迟初始化，
    #       首次调用 get_memory_service() 时自动完成。
    # 4. 初始化工具管理器
    from core.tool_manager import tool_manager
    print(f"[Unified] 工具管理器初始化完成，共 {len(tool_manager.tools)} 个工具")

    # 5. 初始化对话管理器
    from core.dialog.dialogue_manager import dialogue_manager
    print("[Unified] 对话管理器初始化完成")

    # 6. 初始化工作模式管理器
    from core.work_mode_manager import get_work_mode_manager
    get_work_mode_manager()
    print("[Unified] 工作模式管理器初始化完成")

    # 7. 初始化新版 ModelBus（复活 core.ai_models）
    try:
        from core.ai.ai_model_bridge import init_model_bus
        bus = await init_model_bus()
        if bus:
            stats = bus.get_stats()
            print(f"[Unified] 新版 ModelBus 初始化完成: {stats}")
        else:
            print("[Unified 警告] 新版 ModelBus 初始化返回 None（可能事件循环已运行）")
    except Exception as e:
        print(f"[Unified 警告] 新版 ModelBus 初始化失败: {e}")

    return config, logger, dialogue_manager


def start_voice_system(dialogue_manager):
    """启动语音系统（唤醒词+播报）"""
    global _voice_instance
    try:
        from core.agent.agent_loop import set_voice_for_tts
        from core.config import config
        from core.global_state import set_voice_interface
        from voice import VoiceInterface

        speaker_wav = config.get("voice.speaker_wav", None)
        voice = VoiceInterface(tts_engine=None, speaker_wav=speaker_wav)

        # 检查语音引擎
        if voice._piper_voice is None:
            print("[Unified 警告] Piper TTS 不可用")
        else:
            print("[Unified] Piper TTS 引擎已就绪")

        # 注册到全局
        set_voice_for_tts(voice)
        set_voice_interface(voice)
        dialogue_manager.voice = voice
        # 【Fix】防御性检查：确保 voice.loop 已正确初始化
        if hasattr(voice, 'loop') and voice.loop is not None:
            dialogue_manager.loop = voice.loop
        else:
            print("[Unified 警告] VoiceInterface.loop 未初始化，跳过绑定到 dialogue_manager")
            dialogue_manager.loop = None

        # 【关键】启动语音监听（唤醒词功能）
        voice.start()
        _voice_instance = voice

        print("[Unified] 语音监听已启动，唤醒词功能已启用")
        print("[Unified] AI回复语音播报已启用")

        # 启动播报
        def startup_announcement():
            time.sleep(2)
            from voice.voice_prompts import SystemAnnouncements
            voice.speak(SystemAnnouncements.LISTENING, is_system=True)
        threading.Thread(target=startup_announcement, daemon=True).start()

        return True
    except Exception as e:
        print(f"[Unified 错误] 语音系统启动失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def heartbeat_loop():
    """心跳循环 - 处理任务队列（Phase 8 异步化改造）

    使用原生 async/await 替代线程内 new_event_loop() + run_until_complete() 反模式。
    """
    from core.agent.agent_loop import run_agent_loop_async
    from core.config import config
    from core.task.task_queue import task_queue
    from core.work_mode_manager import get_work_mode_manager

    work_mode_mgr = get_work_mode_manager()
    interval = config.get("heartbeat.interval", 0.1)

    print(f"[Unified] 心跳循环启动，轮询间隔 {interval} 秒")

    while not _shutdown_event.is_set():
        try:
            # 自动模式切换检查
            work_mode_mgr.auto_revert_if_needed()

            # 处理任务
            task = await task_queue.pop_async()
            if task:
                # 【修复】标记任务执行路径，用于断点续传时区分调度路径
                if hasattr(task, 'metadata') and isinstance(task.metadata, dict):
                    task.metadata["execution_path"] = "task_queue"
                print(f"[Unified] 处理任务: {task.id[:8]} 类型={task.type}")

                if task.type == "user":
                    task.intent.get("raw", "")
                    session_id = task.session_id

                    # 通知工作模式管理器
                    work_mode_mgr.on_user_input()

                    # 运行Agent循环（异步版）— 原生 await，无需手动事件循环

                    # 向经验总线发布任务开始执行事件（中间步骤）
                    try:
                        from core.consciousness.Consciousness import get_consciousness
                        from core.consciousness.experience_bus import ExperienceEvent
                        consciousness = get_consciousness()
                        if consciousness and getattr(consciousness, 'experience_bus', None):
                            asyncio.create_task(consciousness.experience_bus.publish(ExperienceEvent(
                                source="task_scheduler", event_type="task_started",
                                timestamp=time.time(), context={"task_id": task.id, "source": task.metadata.get("source", "unknown")},
                                action="execute_task", outcome=0.5
                            )))
                    except Exception:
                        pass

                    try:
                        final_answer, _ = await run_agent_loop_async(
                            task=task,
                            max_rounds=config.get("agent.max_rounds", 15),
                            chat_history=[],
                            chat_count=0,
                            session_id=session_id,
                            db_session_id=None,
                            voice_instance=_voice_instance,
                            mode=work_mode_mgr.get_current_mode().value
                        )

                        await task_queue.complete_async({
                            "result": final_answer or "任务处理完成",
                            "success": True
                        })

                        # 向经验总线发布任务执行完成事件
                        try:
                            from core.consciousness.Consciousness import get_consciousness
                            from core.consciousness.experience_bus import ExperienceEvent
                            consciousness = get_consciousness()
                            if consciousness and getattr(consciousness, 'experience_bus', None):
                                asyncio.create_task(consciousness.experience_bus.publish(ExperienceEvent(
                                    source="task_scheduler", event_type="task_completed",
                                    timestamp=time.time(), context={"task_id": task.id, "source": task.metadata.get("source", "unknown")},
                                    action="execute_task", outcome=1.0
                                )))
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"[Unified 错误] Agent循环失败: {e}")
                        await task_queue.fail_async(str(e), "AGENT_ERROR")

                        # 向经验总线发布任务执行失败事件
                        try:
                            from core.consciousness.Consciousness import get_consciousness
                            from core.consciousness.experience_bus import ExperienceEvent
                            consciousness = get_consciousness()
                            if consciousness and getattr(consciousness, 'experience_bus', None):
                                asyncio.create_task(consciousness.experience_bus.publish(ExperienceEvent(
                                    source="task_scheduler", event_type="task_failed",
                                    timestamp=time.time(), context={"task_id": task.id, "source": task.metadata.get("source", "unknown")},
                                    action="execute_task", outcome=0.0
                                )))
                        except Exception:
                            pass

            # 异步友好的间隔等待
            await asyncio.sleep(interval)

        except Exception as e:
            print(f"[Unified 错误] 心跳循环异常: {e}")
            await asyncio.sleep(1)

    print("[Unified] 心跳循环已停止")


def start_heartbeat():
    """启动心跳循环（独立线程 + asyncio.run 统一管理）"""
    global _heartbeat_thread

    def _run_heartbeat():
        asyncio.run(heartbeat_loop())

    _heartbeat_thread = threading.Thread(target=_run_heartbeat, daemon=True)
    _heartbeat_thread.start()
    print("[Unified] 心跳循环线程已启动")


def shutdown_system():
    """优雅关闭系统"""
    print("\n[Unified] 正在关闭系统...")

    # 1. 停止心跳循环
    _shutdown_event.set()
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        _heartbeat_thread.join(timeout=5)

    # 2. 停止语音系统
    if _voice_instance:
        try:
            _voice_instance.stop()
            print("[Unified] 语音系统已停止")
        except RuntimeError as e:
            print(f"[Unified 警告] 语音系统停止失败 (运行时错误): {e}")
        except AttributeError as e:
            print(f"[Unified 警告] 语音系统停止失败 (属性错误): {e}")
        except Exception as e:
            print(f"[Unified 警告] 语音系统停止失败 (未知错误): {e}")

    # 3. 停止状态服务器
    if _status_server:
        try:
            _status_server.stop()
            print("[Unified] 状态服务器已停止")
        except RuntimeError as e:
            print(f"[Unified 警告] 状态服务器停止失败 (运行时错误): {e}")
        except AttributeError as e:
            print(f"[Unified 警告] 状态服务器停止失败 (属性错误): {e}")
        except Exception as e:
            print(f"[Unified 警告] 状态服务器停止失败 (未知错误): {e}")

    print("[Unified] 系统关闭完成")


def start_http_server(host="0.0.0.0", port=8600):
    """启动HTTP服务器（uvicorn）"""
    import uvicorn

    print(f"[Unified] 启动HTTP服务: http://{host}:{port}")

    # 配置uvicorn
    # 【修复】禁用 access_log 避免 Windows 控制台关闭时 stdout 句柄已失效导致 ValueError
    config = uvicorn.Config(
        "api.cloud_api:app",
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        ws_ping_interval=WS_PING_INTERVAL,
        ws_ping_timeout=WS_PING_TIMEOUT,
    )

    server = uvicorn.Server(config)

    # 在独立线程中运行（非阻塞）
    def run_server():
        # [Phase 8] 使用 asyncio.run 统一管理事件循环生命周期
        # run_server() 运行在独立线程中，无主事件循环，asyncio.run() 完全安全
        asyncio.run(server.serve())

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    print(f"[Unified] HTTP服务已启动: http://{host}:{port}")
    print(f"[Unified] API文档: http://{host}:{port}/docs")

    return server, server_thread


def _load_dormant_modules():
    """【复活死文件】加载所有沉睡的核心模块"""
    from core.feature_manager import AppStatus, feature_manager

    modules_loaded = []

    modules_to_load = [
        ("core.adapter.agent_loop_adapter", "AgentLoopAdapter"),
        ("core.experiment.experiment_manager", "ExperimentManager"),
        ("core.model_upgrade.orchestrator", "ModelUpgradeOrchestrator"),
        ("core.platform_adapter.factory", "PlatformFactory"),
        ("core.memory.data_lifecycle", "get_lifecycle_manager"),
        ("core.memory.recall_memory", "ActiveRecall"),
        ("core.consciousness.subconscious_engine", "SubconsciousEngine"),
    ]

    for module_path, class_name in modules_to_load:
        while feature_manager.get_app_status() == AppStatus.PAUSED:
            time.sleep(1)  # 暂停时等待
        if feature_manager.get_app_status() == AppStatus.STOPPED:
            print("[Bootstrap] 全局停止，终止模块加载")
            break

        try:
            module = __import__(module_path, fromlist=[class_name])
            obj = getattr(module, class_name)
            _ = obj()
            modules_loaded.append(class_name)
        except Exception:
            pass  # 静默失败，不阻塞启动

    if modules_loaded:
        print(f"[Unified] 已复活 {len(modules_loaded)} 个死文件模块: {', '.join(modules_loaded)}")


async def main():
    """主入口"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║              SiliconBase V5 - 统一启动程序                 ║
    ║                   落地版本 / Production                    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  HTTP API:  http://0.0.0.0:8600/docs                     ║
    ║  WebSocket: ws://0.0.0.0:8600/ws/{user_id}              ║
    ║  唤醒词:    元旦 / 你好元旦                               ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # 1. 设置信号处理
    setup_signal_handlers()
    atexit.register(shutdown_system)

    # 2. 初始化核心系统
    config, logger, dialogue_manager = await init_core_systems()

    # 【预热】后台异步预热 Ollama 视觉模型，避免首次调用时的"未加载"延迟
    asyncio.create_task(_warmup_ollama_models(config, logger))

    # 【P0-ENV修复】启动 ChromaDB 服务器（向量同步依赖）
    chroma_ready = _start_chromadb_server()
    if chroma_ready:
        logger.info("[ChromaDB] 向量存储后端已就绪")
    else:
        logger.warning("[ChromaDB] 向量存储后端未就绪，向量同步功能将不可用")

    # 3. 启动HTTP服务（独立线程）
    http_server, http_thread = start_http_server(
        host=config.get("server.host", "0.0.0.0"),
        port=config.get("server.port", 8600)
    )

    # 4. 等待HTTP服务就绪
    await asyncio.sleep(2)

    # 5. WebSocket服务器已由 cloud_api lifespan 启动，避免重复


    # 7. 启动语音系统（唤醒词+播报）
    # 【修复】api/cloud_api.py 的 FastAPI lifespan 已完整初始化语音系统（含超时保护），
    # 此处跳过重复初始化，避免 Vosk C++ 扩展多实例加载导致 segfault 崩溃。
    print("[Unified] 语音系统由 CloudAPI lifespan 初始化，跳过重复启动")
    # start_voice_system(dialogue_manager)

    # 【复活死文件】加载沉睡模块
    _load_dormant_modules()

    # 【紧急手术】启动数据生命周期自动维护后台协程（每小时一次）
    async def _lifecycle_maintenance_loop():
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时执行一次
                from core.memory.data_lifecycle import get_lifecycle_manager
                manager = get_lifecycle_manager()
                if manager:
                    result = await asyncio.to_thread(manager.auto_cleanup_all)
                    logger.info(f"[DataLifecycleManager] 自动维护完成: 压缩={len(result.get('compressed', {}))} 项, 节省空间={result.get('total_space_saved_bytes', 0)} 字节")
            except Exception as e:
                logger.warning(f"[DataLifecycleManager] 自动维护周期失败: {e}")

    asyncio.create_task(_lifecycle_maintenance_loop())

    # ========== 启动硅基生命意识核心 ==========
    # 【P0-017】由 FeatureManager 统一控制启停
    try:
        from core.feature_manager import feature_manager
        if feature_manager.is_enabled("consciousness"):
            feature = feature_manager.get_feature("consciousness")
            if feature is not None:
                feature.initialize()  # 触发 _do_initialize → _init_consciousness
                logger.info("[Bootstrap] 硅基生命意识核心已启动")
            else:
                logger.warning("[Bootstrap] 意识核心 Feature 未注册")
        else:
            logger.info("[Bootstrap] 意识核心已在配置中禁用，跳过启动")
    except Exception as _e:
        logger.error(f"[Bootstrap] 意识核心启动失败: {_e}", exc_info=True)

    # 【P0-VISION修复】自动启动实时视觉监控后台流水线
    # 原代码：实时监控仅在 handle_text_input(mode="start_monitor") 时启动
    # 修复：系统启动时自动启动，为意识线程提供视觉数据
    try:
        from core.dialog.dialogue_manager import dialogue_manager
        asyncio.create_task(dialogue_manager._start_realtime_monitor("default", "default_session"))
        logger.info("[Bootstrap] 实时视觉监控后台流水线已启动")
    except Exception as _e:
        logger.warning(f"[Bootstrap] 实时视觉监控启动失败: {_e}")

    # 【修复】启动时自动恢复中断任务
    try:
        _cp_dir = BASE_DIR / "data" / "checkpoints"
        if _cp_dir.exists():
            _interrupted_count = 0
            for _user_dir in _cp_dir.iterdir():
                if not _user_dir.is_dir():
                    continue
                for _cp_file in _user_dir.glob("*.json"):
                    if _cp_file.name.endswith(".tmp"):
                        continue
                    try:
                        with open(_cp_file, encoding='utf-8') as f:
                            _cp_data = json.load(f)
                        if _cp_data.get("status") == "interrupted":
                            _task_id = _cp_data.get("task_id")
                            if _task_id:
                                from core.agent.checkpoint_manager import checkpoint_manager
                                await checkpoint_manager.resume_task_async(_task_id)

                                # 【修复】根据执行路径做路由恢复
                                _execution_path = _cp_data.get("global_context", {}).get("execution_path", "direct")
                                if _execution_path == "task_queue":
                                    # 重建 Task 对象并推入任务队列，由 heartbeat_loop 调度执行
                                    from core.task.task_queue import Task, task_queue
                                    restored_task = Task(
                                        type="user",
                                        intent={"raw": _cp_data.get("global_context", {}).get("user_instruction", "")},
                                        session_id=_cp_data.get("task_id", ""),
                                        user_id=_cp_data.get("user_id", "default"),
                                        priority=5,
                                        metadata={
                                            "restored_from_checkpoint": True,
                                            "task_id": _task_id,
                                            "execution_path": "task_queue"
                                        }
                                    )
                                    await task_queue.push_async(restored_task)
                                    logger.info(f"[Startup] 已恢复中断任务并入队: {_task_id}")
                                else:
                                    # WebSocket 直接调用路径：恢复状态和对话历史，等待用户重新发起请求时由 resume_from_checkpoint 处理
                                    logger.info(f"[Startup] 已恢复中断任务状态: {_task_id} (direct路径，等待用户重连)")
                                _interrupted_count += 1
                    except Exception as e:
                        logger.warning(f"[Startup] 恢复检查点失败 {_cp_file.name}: {e}")
            if _interrupted_count > 0:
                logger.info(f"[Startup] 共恢复{_interrupted_count}个中断任务")
    except Exception as e:
        logger.warning(f"[Startup] 检查点扫描失败: {e}")

    # 8. 启动心跳循环（任务处理）
    start_heartbeat()

    # 9. 启动完成
    print("\n" + "="*60)
    print("[Unified] ✅ 系统启动完成！所有功能已就绪")
    print("="*60 + "\n")

    # 10. 保持主线程运行
    try:
        while not _shutdown_event.is_set():
            await asyncio.sleep(1)   # 【P0-LOOP修复】异步挂起，释放事件循环调度其他Task
    except KeyboardInterrupt:
        print("\n[Unified] 收到键盘中断")
        shutdown_system()


if __name__ == "__main__":
    # 【调试】启用 faulthandler，若 C 扩展 segfault 可打印 traceback 到 stderr
    import faulthandler
    faulthandler.enable()
    asyncio.run(main())
