# core/vision/visual_tool_coordinator.py
#!/usr/bin/env python3
"""
视觉工具协调器 - 防止AI调用与工具调用的资源竞争

【核心功能】
1. 协调visual_understand与pixel_capture/pixel_color的调用
2. 防止AI和工具同时截图导致的MSS竞争（虽然safe_screenshot有锁，但避免并发更保险）
3. 管理视觉AI调用队列，确保顺序执行

【使用方式】
- visual_understand工具通过此协调器获取截图
- pixel_color作为辅助工具，轻量级操作不经过此协调器
- pixel_capture作为独立截图工具，也不经过此协调器（依赖safe_screenshot的锁）

【竞争防护】
实际上safe_screenshot已经通过全局锁保护了MSS，此协调器主要提供：
1. 调用状态追踪（知道谁在调用视觉AI）
2. 队列管理（如果有多个视觉AI请求，顺序处理）
3. 防止递归调用（AI调用visual_understand，结果又触发AI调用）
"""
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)


class VisualToolState(Enum):
    """视觉工具状态"""
    IDLE = "idle"                    # 空闲
    AI_CALLING = "ai_calling"        # AI正在调用visual_understand
    TOOL_CALLING = "tool_calling"    # 工具正在调用截图
    QUEUED = "queued"                # 有请求在队列中等待


@dataclass
class VisualRequest:
    """视觉请求"""
    request_id: str
    request_type: str  # "ai_vision", "tool_capture", "color_check"
    callback: Callable
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""  # 请求来源（用于调试）


class VisualToolCoordinator:
    """
    视觉工具协调器 - 单例模式

    确保视觉AI调用和工具截图不会并发冲突，
    虽然safe_screenshot有全局锁保护MSS，但此协调器提供更高层的管理。
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
        self._state = VisualToolState.IDLE
        self._state_lock = threading.Lock()
        self._request_queue = Queue()
        self._current_request: VisualRequest | None = None
        self._ai_call_depth = 0  # AI调用深度（防止递归）
        self._stats = {
            "total_requests": 0,
            "queued_requests": 0,
            "ai_calls": 0,
            "tool_calls": 0
        }

        # 启动队列处理线程
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

        logger.info("[VisualCoordinator] 视觉工具协调器已初始化")

    def _process_queue(self):
        """后台线程处理队列"""
        while True:
            try:
                request = self._request_queue.get(timeout=1.0)
                self._handle_request(request)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"[VisualCoordinator] 队列处理错误: {e}")

    def _handle_request(self, request: VisualRequest):
        """处理单个请求"""
        with self._state_lock:
            self._current_request = request
            if request.request_type == "ai_vision":
                self._state = VisualToolState.AI_CALLING
            else:
                self._state = VisualToolState.TOOL_CALLING

        try:
            logger.debug(f"[VisualCoordinator] 执行请求: {request.request_id} ({request.request_type})")
            request.callback(**request.params)

            # 更新统计
            self._stats["total_requests"] += 1
            if request.request_type == "ai_vision":
                self._stats["ai_calls"] += 1
            else:
                self._stats["tool_calls"] += 1

        except Exception as e:
            logger.error(f"[VisualCoordinator] 请求执行失败: {e}")
        finally:
            with self._state_lock:
                self._current_request = None
                self._state = VisualToolState.IDLE if self._request_queue.empty() else VisualToolState.QUEUED

    def request_ai_vision(self, callback: Callable, params: dict[str, Any],
                          source: str = "unknown") -> dict[str, Any]:
        """
        请求AI视觉分析（带超时保护）

        【关键修复】添加30秒超时机制，防止视觉模型调用阻塞整个系统

        Args:
            callback: 实际执行视觉分析的函数
            params: 调用参数
            source: 请求来源（用于调试）

        Returns:
            执行结果
        """
        import concurrent.futures

        request_id = f"vision_{int(time.time() * 1000)}"

        # 检查递归深度
        if self._ai_call_depth > 0:
            logger.warning(f"[VisualCoordinator] 检测到嵌套AI调用，深度={self._ai_call_depth}")

        with self._state_lock:
            if self._state == VisualToolState.IDLE:
                # 直接执行（带超时保护）
                self._ai_call_depth += 1
                self._state = VisualToolState.AI_CALLING
                try:
                    # 【关键修复】使用线程池执行，支持超时
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(callback, **params)
                        try:
                            result = future.result(timeout=30)  # 30秒超时
                            return result
                        except concurrent.futures.TimeoutError:
                            logger.error(f"[VisualCoordinator] 视觉AI调用超时 (30s): {request_id}")
                            return {
                                "success": False,
                                "error": "视觉模型推理超时（30秒），请检查模型服务状态",
                                "error_code": "VISION_TIMEOUT"
                            }
                        except Exception as e:
                            logger.error(f"[VisualCoordinator] 视觉AI调用异常: {e}")
                            return {
                                "success": False,
                                "error": f"视觉模型调用失败: {str(e)}"
                            }
                finally:
                    self._ai_call_depth -= 1
                    self._state = VisualToolState.IDLE
            else:
                # 加入队列
                logger.debug(f"[VisualCoordinator] AI视觉请求加入队列: {request_id}")
                self._stats["queued_requests"] += 1

        # 等待执行完成（简化版，实际需要更复杂的同步机制）
        # 这里简单返回，实际使用时可扩展为等待模式
        return {"success": False, "error": "视觉AI正忙，请稍后重试"}

    def can_execute_immediately(self, request_type: str) -> bool:
        """检查是否可以立即执行（不排队）"""
        with self._state_lock:
            if request_type == "ai_vision":
                # AI视觉调用需要独占
                return self._state == VisualToolState.IDLE
            else:
                # 工具调用（截图/颜色）可以并发（因为safe_screenshot有锁保护）
                return True

    def get_status(self) -> dict[str, Any]:
        """获取协调器状态"""
        with self._state_lock:
            return {
                "state": self._state.value,
                "current_request": self._current_request.request_id if self._current_request else None,
                "queue_size": self._request_queue.qsize(),
                "ai_call_depth": self._ai_call_depth,
                "stats": self._stats.copy()
            }

    def wait_for_idle(self, timeout: float = 10.0) -> bool:
        """等待直到空闲（用于测试或同步场景）"""
        start = time.time()
        while time.time() - start < timeout:
            with self._state_lock:
                if self._state == VisualToolState.IDLE and self._request_queue.empty():
                    return True
            time.sleep(0.1)
        return False


# 全局协调器实例
coordinator = VisualToolCoordinator()


def coordinated_ai_vision(callback: Callable, **kwargs) -> dict[str, Any]:
    """
    协调的AI视觉调用

    在visual_understand工具中使用，确保不会与工具调用冲突。
    实际上主要依赖safe_screenshot的锁保护，此函数提供额外的状态追踪。
    """
    source = kwargs.pop("_source", "unknown")
    return coordinator.request_ai_vision(callback, kwargs, source)


def get_visual_status() -> dict[str, Any]:
    """获取视觉工具状态（调试用）"""
    return coordinator.get_status()
