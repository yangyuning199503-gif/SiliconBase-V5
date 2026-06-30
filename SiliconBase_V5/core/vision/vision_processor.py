#!/usr/bin/env python3
"""
Vision Processor - SiliconBase V5
[Refactored] Migrated from agent_loop.py
"""

import asyncio
import atexit
import queue as thread_queue
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.config import config
from core.diagnostic import diagnostic_except_handler, safe_create_task
from core.logger import logger
from core.vision.visual_analysis_cache import get_visual_analysis_cache


class VisionError(Exception):
    """Base exception for vision perception"""
    pass


class ScreenshotError(VisionError):
    """Screenshot capture failed"""
    pass


class VisionModelError(VisionError):
    """Vision model invocation failed"""
    pass


class VisionTimeoutError(VisionError):
    """Vision model call timed out"""
    pass


def get_vision_timeout() -> int:
    """Get vision model timeout dynamically"""
    timeout = config.get("timeouts.vision", 60)
    if isinstance(timeout, str) and timeout.startswith("${"):
        return int(timeout.split(":")[-1].rstrip("}"))
    return int(timeout)


VISION_TIMEOUT = get_vision_timeout()

_vision_retries_raw = config.get("vision.max_retries", 1)
if isinstance(_vision_retries_raw, str) and _vision_retries_raw.startswith("${"):
    VISION_MAX_RETRIES = int(_vision_retries_raw.split(":")[-1].rstrip("}"))
else:
    VISION_MAX_RETRIES = int(_vision_retries_raw)

MAX_USER_INSTRUCTION_LEN = 200

VISION_CACHE_TTL = 300  # 5分钟缓存有效期（秒）
VISION_CACHE_TTL_EXTENDED = 600  # 降级模式下延长到10分钟（秒）

VISION_RUNTIME_ENABLED = True

# 【修复】跟踪视觉模型Provider不可用状态，避免重复调用和日志刷屏
_vision_provider_unavailable: dict[str, bool] = {}
_VISION_UNAVAILABLE_TTL = 300  # 5分钟后可重试
_vision_unavailable_timestamp: dict[str, float] = {}


def set_vision_enabled(enabled: bool) -> None:
    """Enable/disable vision perception at runtime"""
    global VISION_RUNTIME_ENABLED
    VISION_RUNTIME_ENABLED = enabled
    logger.info(f"[Vision] Runtime state: enabled={enabled}")


def is_vision_enabled() -> bool:
    """Check if vision perception is enabled"""
    return VISION_RUNTIME_ENABLED


def _is_vision_provider_unavailable(user_id: str) -> bool:
    """检查视觉模型Provider是否已确认不可用（带TTL）"""
    if user_id not in _vision_provider_unavailable:
        return False
    timestamp = _vision_unavailable_timestamp.get(user_id, 0)
    if time.time() - timestamp > _VISION_UNAVAILABLE_TTL:
        # TTL过期，清除标记
        _vision_provider_unavailable.pop(user_id, None)
        _vision_unavailable_timestamp.pop(user_id, None)
        return False
    return True


def _mark_vision_provider_unavailable(user_id: str) -> None:
    """标记视觉模型Provider为不可用"""
    _vision_provider_unavailable[user_id] = True
    _vision_unavailable_timestamp[user_id] = time.time()


# 【蓝屏修复】max_workers 从 2 改为 1，与 visual_understand._vision_gpu_semaphore(1) 保持一致，
# 避免一个 worker 抢到 GPU 推理、另一个 worker 阻塞占着名额导致线程池饱和僵尸任务
_vision_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision_worker")
_vision_executor_shutdown = False


def cleanup_vision_executor(timeout: float = 5.0) -> None:
    """Cleanup vision model thread pool"""
    global _vision_executor_shutdown

    if _vision_executor_shutdown:
        print("[Vision] Thread pool already shutdown", file=sys.stderr)
        return

    try:
        print("[Vision] Shutting down vision thread pool...", file=sys.stderr)
        _vision_executor.shutdown(wait=True, cancel_futures=False)
        _vision_executor_shutdown = True
        print("[Vision] Vision thread pool shutdown successfully", file=sys.stderr)
    except Exception as e:
        print(f"[CRITICAL ERROR][Vision] Error during shutdown: {e}", file=sys.stderr)
        try:
            _vision_executor.shutdown(wait=False, cancel_futures=True)
            _vision_executor_shutdown = True
            print("[Vision] Thread pool force shutdown", file=sys.stderr)
        except Exception as e2:
            print(f"[CRITICAL ERROR][Vision] Force shutdown failed: {e2}", file=sys.stderr)


atexit.register(cleanup_vision_executor)


def _check_gpu_memory():
    """检查GPU显存，如果使用率过高则抛出异常"""
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                allocated = torch.cuda.memory_allocated(i) / 1024**3  # GB
                torch.cuda.memory_reserved(i) / 1024**3  # GB
                total = torch.cuda.get_device_properties(i).total_memory / 1024**3  # GB
                usage_percent = (allocated / total) * 100 if total > 0 else 0

                # 【蓝屏修复】如果显存使用率超过90%，拒绝新任务
                if usage_percent > 90:
                    logger.error(f"[GPU] GPU{i}显存使用率{usage_percent:.1f}%过高，拒绝视觉模型调用以防止崩溃")
                    return False, f"GPU{i}显存不足({usage_percent:.1f}%)"
                logger.debug(f"[GPU] GPU{i}显存: {allocated:.1f}/{total:.1f}GB ({usage_percent:.1f}%)")
    except Exception as e:
        logger.error(f"[GPU] 显存检查失败: {e}", exc_info=True)
        return False, f"显存检查异常: {e}"


async def call_vision_model_async(vision_tool, image_source: str, question: str, timeout: int = None):
    """
    Async vision model call with timeout

    Args:
        vision_tool: VisualUnderstand instance
        image_source: Image source (e.g., "screenshot")
        question: Question to ask
        timeout: Timeout in seconds, default from config

    Returns:
        dict: Vision model result

    Raises:
        TimeoutError: If call times out
        RuntimeError: If call fails
    """
    # 【蓝屏修复】检查GPU显存
    gpu_ok, gpu_msg = _check_gpu_memory()
    if not gpu_ok:
        raise RuntimeError(f"[Vision] GPU显存不足，跳过视觉模型调用: {gpu_msg}")

    actual_timeout = timeout or get_vision_timeout()
    asyncio.get_event_loop()

    try:
        vision_result = await asyncio.wait_for(
            vision_tool.run_async(image_source=image_source, question=question),
            timeout=actual_timeout
        )

        if not vision_result:
            error_msg = "[Vision] Vision model returned None"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        if not vision_result.get("success"):
            error_msg = f"[Vision] Vision model failed: {vision_result.get('error', 'unknown')}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        return vision_result

    except asyncio.TimeoutError as _exc:
        error_msg = f"[Vision] Vision model timeout ({actual_timeout}s)"
        logger.error(error_msg)
        raise TimeoutError(error_msg) from _exc
    except Exception as e:
        error_msg = f"[Vision] Vision model exception: {e}"
        logger.error(error_msg, exc_info=True)
        raise


# ── PixelCapture 可用性检测 ─────────────────────────────────────────────
try:
    from tools.pixel_capture import PixelCapture
    PIXEL_CAPTURE_AVAILABLE = True
except ImportError:
    PIXEL_CAPTURE_AVAILABLE = False
    logger.warning("[Vision] PixelCapture不可用")

try:
    from tools.visual_understand import VisualUnderstand
    VISUAL_UNDERSTAND_AVAILABLE = True
except ImportError:
    VISUAL_UNDERSTAND_AVAILABLE = False
    logger.warning("[Vision] VisualUnderstand不可用")

# 模块级单例，避免循环内重复初始化导致资源抖动
_screenshot_tool_singleton = None
_vision_tool_singleton = None

# ── LeJEPA 全局异步标注队列（后台深度理解，AgentLoop 不直接调用）──
_annotation_queue: thread_queue.Queue = thread_queue.Queue(maxsize=10)
_annotation_task: asyncio.Task | None = None
_annotation_lock = asyncio.Lock()


def _get_pixel_capture():
    global _screenshot_tool_singleton
    if _screenshot_tool_singleton is None:
        _screenshot_tool_singleton = PixelCapture()
        logger.info("[Vision] PixelCapture 单例初始化完成")
    else:
        logger.debug("[Vision] PixelCapture 单例复用")
    return _screenshot_tool_singleton


def _get_visual_understand():
    global _vision_tool_singleton
    if _vision_tool_singleton is None:
        _vision_tool_singleton = VisualUnderstand()
        logger.info("[Vision] VisualUnderstand 单例初始化完成")
    else:
        logger.debug("[Vision] VisualUnderstand 单例复用")
    return _vision_tool_singleton


def _inject_vision_to_working_memory(
    last_vision_description: str | None,
    vision_cache_timestamp: float,
    working_memory: Any,
) -> tuple[str | None, float]:
    """将视觉描述安全注入 working_memory，处理缓存过期和清理。"""
    if not last_vision_description:
        return last_vision_description, vision_cache_timestamp

    cache_age = time.time() - vision_cache_timestamp
    if cache_age < VISION_CACHE_TTL:
        try:
            from core.utils.security import sanitize_vision_description
            safe_description = sanitize_vision_description(last_vision_description)
            vision_prompt = f"【屏幕状态】{safe_description}"
            working_memory.append({
                "role": "system",
                "content": vision_prompt,
                "_category": "screen_state",
                "_overwrite": True
            })
            logger.info("[Vision] 视觉描述已安全注入Prompt")
        except Exception as e:
            error_msg = f"[SECURITY] 视觉描述清理失败: {e}"
            logger.error(error_msg)
            last_vision_description = None
    else:
        logger.debug("[Vision] 视觉缓存已过期")
        last_vision_description = None

    return last_vision_description, vision_cache_timestamp


async def process_vision_perception(
    user_instruction: str,
    change_detector,
    last_vision_description: str | None,
    vision_cache_timestamp: float,
    working_memory: Any,
    user_id: str,
    vision_enabled: bool = True,
    loop_state: Any | None = None,
) -> tuple[str | None, float]:
    """同步版视觉感知处理（与 agent_loop 内联逻辑行为一致）。

    返回 (updated_last_vision_description, updated_vision_cache_timestamp)
    """
    if not VISION_RUNTIME_ENABLED:
        logger.debug("[Vision] 视觉感知已运行时禁用")
        return last_vision_description, vision_cache_timestamp

    if not vision_enabled or not change_detector:
        return last_vision_description, vision_cache_timestamp

    try:
        logger.debug("[Vision] 开始截图...")

        if not PIXEL_CAPTURE_AVAILABLE:
            raise ScreenshotError("PixelCapture不可用")

        screenshot_tool = _get_pixel_capture()
        screenshot_result = await screenshot_tool.run_async(output_format="pil")
        current_screenshot = screenshot_result.get("data", {}).get("image")

        if current_screenshot:
            logger.debug(f"[Vision] 截图成功: {current_screenshot.size}")
        else:
            logger.warning("[Vision] 截图失败: 未获取到图像")

        if current_screenshot:
            screen_changed = change_detector.has_changed(current_screenshot)

            if screen_changed:
                logger.info("[Vision] 屏幕检测到变化，异步调用视觉模型...")

                try:
                    from core.utils.security import escape_user_instruction
                    safe_instruction = escape_user_instruction(user_instruction)
                except Exception as e:
                    error_msg = f"[SECURITY] 用户指令转义失败: {e}"
                    logger.error(error_msg)
                    return last_vision_description, vision_cache_timestamp

                try:
                    if not VISUAL_UNDERSTAND_AVAILABLE:
                        raise VisionModelError("VisualUnderstand不可用")

                    vision_tool = _get_visual_understand()
                    vision_timeout = get_vision_timeout()
                    vision_result = await asyncio.wait_for(
                        vision_tool.run_async(
                            image_source="screenshot",
                            question=f"用户请求：{safe_instruction}。请描述当前屏幕内容，是否显示用户需要的信息？"
                        ),
                        timeout=vision_timeout
                    )

                    if vision_result and vision_result.get("success"):
                        last_vision_description = vision_result["data"]["description"]
                        vision_cache_timestamp = time.time()
                        logger.info(f"[Vision] ✅ 视觉描述已更新: {last_vision_description[:80]}...")
                    else:
                        error_msg = vision_result.get("error", "未知错误") if vision_result else "返回None"
                        logger.error(f"[Vision] ❌ 视觉模型调用失败: {error_msg}，将降级继续")
                        last_vision_description = None

                except TimeoutError:
                    actual_timeout = get_vision_timeout()
                    logger.error(f"[Vision] ❌ 视觉模型调用超时({actual_timeout}秒)，保留缓存继续任务")
                    if not last_vision_description:
                        logger.error("[Vision] ❌ 无可用视觉缓存，任务可能受影响，将降级继续")
                        last_vision_description = None

                except Exception as e:
                    error_msg = f"[Vision] 视觉模型调用失败: {e}"
                    logger.error(error_msg)
                    last_vision_description = None
            else:
                logger.debug("[AgentLoop] 屏幕无变化，使用视觉缓存")

        # 注入 Prompt
        last_vision_description, vision_cache_timestamp = _inject_vision_to_working_memory(
            last_vision_description, vision_cache_timestamp, working_memory
        )

    except ScreenshotError as e:
        logger.error(f"[Vision] 截图错误: {e}")
        last_vision_description = None

    except VisionTimeoutError as e:
        logger.error(f"[Vision] 视觉模型超时: {e}")

    except VisionModelError as e:
        logger.error(f"[Vision] 视觉模型错误: {e}")

    except VisionError as e:
        logger.error(f"[Vision] 视觉处理错误: {e}")
        last_vision_description = None

    except Exception as e:
        error_msg = f"[Vision] 未预期错误: {type(e).__name__}: {e}"
        logger.error(error_msg)
        instruction_snippet = user_instruction[:MAX_USER_INSTRUCTION_LEN] if user_instruction else "N/A"
        logger.error(f"[Vision] 错误上下文: user_id={user_id}, instruction={instruction_snippet}")
        import traceback
        logger.error(f"[Vision] 堆栈跟踪: {traceback.format_exc()}")
        last_vision_description = None

    return last_vision_description, vision_cache_timestamp


async def process_vision_perception_async(
    user_instruction: str,
    change_detector,
    last_vision_description: str | None,
    vision_cache_timestamp: float,
    working_memory: Any,
    user_id: str,
    vision_enabled: bool = True,
    loop_state: Any | None = None,
) -> tuple[str | None, float]:
    """异步版视觉感知处理（与 agent_loop 异步内联逻辑行为一致）。

    返回 (updated_last_vision_description, updated_vision_cache_timestamp)
    """
    if not VISION_RUNTIME_ENABLED:
        logger.debug("[Vision] 异步版视觉感知已运行时禁用")
        return last_vision_description, vision_cache_timestamp

    # 【修复】如果视觉模型Provider已确认不可用，直接跳过
    if _is_vision_provider_unavailable(user_id):
        logger.debug(f"[Vision] 视觉模型Provider已标记为不可用(user={user_id})，跳过视觉验证")
        return last_vision_description, vision_cache_timestamp

    if not vision_enabled or not change_detector:
        return last_vision_description, vision_cache_timestamp

    try:
        logger.debug("[Vision] 异步版开始截图...")

        if not PIXEL_CAPTURE_AVAILABLE:
            raise ScreenshotError("PixelCapture不可用")

        screenshot_tool = _get_pixel_capture()
        screenshot_result = await screenshot_tool.run_async(output_format="pil")
        current_screenshot = screenshot_result.get("data", {}).get("image")

        if current_screenshot:
            logger.debug(f"[Vision] 异步版截图成功: {current_screenshot.size}")
        else:
            logger.warning("[Vision] 异步版截图失败: 未获取到图像")

        if current_screenshot:
            screen_changed = await asyncio.to_thread(
                change_detector.has_changed,
                current_screenshot
            )

            if screen_changed:
                logger.info("[Vision] 异步版检测到屏幕变化，调用视觉模型...")

                try:
                    from core.utils.security import escape_user_instruction
                    safe_instruction = escape_user_instruction(user_instruction)
                except Exception as e:
                    error_msg = f"[SECURITY] 用户指令转义失败: {e}"
                    logger.error(error_msg)
                    return last_vision_description, vision_cache_timestamp

                try:
                    if not VISUAL_UNDERSTAND_AVAILABLE:
                        raise VisionModelError("VisualUnderstand不可用")

                    vision_tool = _get_visual_understand()
                    # 【修复】AI服务不可用时缩短视觉超时到5秒
                    actual_timeout = get_vision_timeout()
                    if _is_vision_provider_unavailable(user_id):
                        actual_timeout = min(actual_timeout, 5)
                    vision_result = await call_vision_model_async(
                        vision_tool,
                        image_source="screenshot",
                        question=f"用户请求：{safe_instruction}。请描述当前屏幕内容，是否显示用户需要的信息？",
                        timeout=actual_timeout
                    )

                    if vision_result and vision_result.get("success"):
                        last_vision_description = vision_result["data"]["description"]
                        vision_cache_timestamp = time.time()
                        logger.info(f"[Vision] 异步版视觉描述已更新: {last_vision_description[:80]}...")
                    else:
                        error_msg = vision_result.get("error", "未知错误") if vision_result else "返回None"
                        # 【修复】日志级别从ERROR降为WARNING
                        logger.warning(f"[Vision] 视觉模型调用失败: {error_msg}，降级继续")
                        last_vision_description = None

                except TimeoutError:
                    # 【修复】日志级别从ERROR降为WARNING
                    logger.warning(f"[Vision] 视觉模型调用超时({actual_timeout}秒)，保留缓存继续任务")
                    if not last_vision_description:
                        logger.warning("[Vision] 无可用视觉缓存，任务可能受影响，降级继续")
                        last_vision_description = None

                except Exception as e:
                    error_str = str(e)
                    # 【修复】检测AI Provider不可用，标记状态避免后续重复调用
                    is_provider_unavailable = any(kw in error_str for kw in [
                        "服务不可用", "不可用", "Connection refused", "ConnectionError",
                        "ModelRoutingError", "所有AI模型都不可用", "Provider不可用"
                    ])
                    if is_provider_unavailable:
                        _mark_vision_provider_unavailable(user_id)
                        logger.warning(f"[Vision] 视觉模型Provider不可用，已标记跳过后续调用: {e}")
                    else:
                        # 【修复】非Provider不可用错误仍用WARNING
                        logger.warning(f"[Vision] 视觉模型调用失败: {e}")
                    last_vision_description = None
            else:
                logger.debug("[AgentLoop] 异步版屏幕无变化，使用视觉缓存")

            # 注入 Prompt
            last_vision_description, vision_cache_timestamp = _inject_vision_to_working_memory(
                last_vision_description, vision_cache_timestamp, working_memory
            )

    except ScreenshotError as e:
        logger.warning(f"[Vision] 截图错误: {e}")
        last_vision_description = None

    except VisionTimeoutError as e:
        logger.warning(f"[Vision] 视觉模型超时: {e}")

    except VisionModelError as e:
        error_str = str(e)
        is_provider_unavailable = any(kw in error_str for kw in [
            "服务不可用", "不可用", "Connection refused", "ConnectionError",
            "ModelRoutingError", "所有AI模型都不可用", "Provider不可用"
        ])
        if is_provider_unavailable:
            _mark_vision_provider_unavailable(user_id)
            logger.warning(f"[Vision] 视觉模型Provider不可用，已标记跳过后续调用: {e}")
        else:
            logger.warning(f"[Vision] 视觉模型错误: {e}")

    except VisionError as e:
        logger.warning(f"[Vision] 视觉处理错误: {e}")
        last_vision_description = None

    except Exception as e:
        error_msg = f"[Vision] 未预期错误: {type(e).__name__}: {e}"
        logger.warning(error_msg)
        instruction_snippet = user_instruction[:MAX_USER_INSTRUCTION_LEN] if user_instruction else "N/A"
        logger.debug(f"[Vision] 错误上下文: user_id={user_id}, instruction={instruction_snippet}")
        last_vision_description = None

    return last_vision_description, vision_cache_timestamp


# ═════════════════════════════════════════════════════════════════════════════
# LeJEPA 全局异步标注队列（后台深度理解，供 DesktopMonitor 入队）
# ═════════════════════════════════════════════════════════════════════════════

def enqueue_frame_for_annotation(screenshot, element_map=None):
    """供 DesktopMonitor 调用，把变化帧加入大模型深度标注队列

    线程安全：同步函数，可在任意线程调用。
    队列满时丢弃最旧帧，防止积压。
    """
    try:
        item = (screenshot, element_map or [])
        if _annotation_queue.full():
            try:
                _annotation_queue.get_nowait()
                logger.debug("[VisionProcessor] 标注队列已满，丢弃最旧帧")
            except thread_queue.Empty:
                pass
        _annotation_queue.put_nowait(item)
    except Exception as e:
        logger.debug(f"[VisionProcessor] 入队失败: {e}")


async def _annotation_loop():
    """后台标注循环：消费队列，调大模型做深度理解，写入共享缓存"""
    logger.info("[VisionProcessor] 后台标注任务启动")
    while True:
        # 【架构修复】检查独立视觉学习开关，关闭时不做标注
        # 感知开关只控制决策时是否看屏幕，学习开关控制后台标注/训练
        try:
            from core.config import config
            if not config.get("perception.learning_enabled", True):
                await asyncio.sleep(5.0)
                continue
        except Exception:
            pass

        try:
            # 阻塞取帧（超时 1 秒以便检查任务是否被取消）
            item = await asyncio.to_thread(
                _annotation_queue.get, timeout=1.0
            )
            # 【紧急手术】空值保护：防止队列中混入 None 导致解包崩溃
            if item is None:
                continue
            screenshot, element_map = item
        except thread_queue.Empty:
            continue
        except Exception as e:
            logger.warning(f"[VisionProcessor] 取帧异常: {e}", exc_info=True)
            diagnostic_except_handler(e, context="[VisionProcessor] 取帧异常", logger_instance=logger)
            await asyncio.sleep(1.0)
            continue

        try:
            if not VISUAL_UNDERSTAND_AVAILABLE:
                continue

            vision_tool = _get_visual_understand()
            if vision_tool is None:
                continue

            # PIL → Base64（纯内存，不碰文件系统）
            import base64
            import io
            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            image_b64 = base64.b64encode(buffer.getvalue()).decode()
            buffer.close()

            question = "请详细描述当前屏幕内容，识别所有 UI 元素、功能区域和用户可能的操作意图。"
            result = await call_vision_model_async(
                vision_tool,
                image_source=image_b64,
                question=question,
                timeout=get_vision_timeout(),
            )

            if result and result.get("success"):
                description = result["data"]["description"]
                # 写入 VisualAnalysisCache（rich description）
                try:
                    cache = get_visual_analysis_cache()
                    cache.cache_latest(
                        "default", "_global_perception_rich",
                        {
                            "type": "vision",
                            "content": description,
                            "timestamp": time.time(),
                            "confidence": 0.95,
                            "metadata": {
                                "source": "vision_processor_annotation",
                                "element_map": element_map,
                            },
                            "trigger_reason": "periodic",
                        },
                        ttl=30.0,
                    )
                    logger.info(f"[VisionProcessor] 深度标注完成: {description[:60]}...")
                except Exception as e:
                    logger.warning(f"[VisionProcessor] 缓存写入失败: {e}", exc_info=True)
                    diagnostic_except_handler(e, context="[VisionProcessor] 缓存写入失败", logger_instance=logger)
            del image_b64

        except Exception as e:
            logger.warning(f"[VisionProcessor] 标注异常: {e}", exc_info=True)
            diagnostic_except_handler(e, context="[VisionProcessor] 标注异常", logger_instance=logger)


async def ensure_annotation_worker():
    """惰性启动后台标注任务（并发安全）"""
    global _annotation_task
    async with _annotation_lock:
        if _annotation_task is not None and not _annotation_task.done():
            return
        _annotation_task = safe_create_task(_annotation_loop(), name="_annotation_loop")
        logger.info("[VisionProcessor] 后台标注 worker 已启动")


def stop_annotation_worker():
    """停止后台标注任务"""
    global _annotation_task
    if _annotation_task is not None and not _annotation_task.done():
        _annotation_task.cancel()
        logger.info("[VisionProcessor] 后台标注 worker 已取消")


__all__ = [
    "VisionError",
    "ScreenshotError",
    "VisionModelError",
    "VisionTimeoutError",
    "get_vision_timeout",
    "VISION_TIMEOUT",
    "VISION_MAX_RETRIES",
    "set_vision_enabled",
    "is_vision_enabled",
    "cleanup_vision_executor",
    "_vision_executor",
    "call_vision_model_async",
    "process_vision_perception",
    "process_vision_perception_async",
]
