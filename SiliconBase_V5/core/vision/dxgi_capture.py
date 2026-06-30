"""
DXGI 桌面捕获模块 - Windows Desktop Duplication API 封装

功能：
- 全局桌面实时帧捕获，不依赖游戏 API，不注入任何进程
- 支持全屏游戏、窗口化软件、桌面任意画面
- 捕获延迟低于 5ms
- 如果 DXGI 不可用，降级为 PIL ImageGrab

依赖（按优先级排序）：
- dxcam   : 首选，2026 年活跃维护，DXGI Desktop Duplication，~240 FPS
- dxshot  : 次选，功能类似但维护状态不明
- d3dshot : 备选，已停止维护（2022 年 archive），存在 gc.collect() 导致的
            fatal access violation 风险，仅作兼容性兜底
- PIL ImageGrab : 最终降级方案，稳定但性能最低
"""

import threading
import time

import numpy as np
from PIL import ImageGrab


class DXGICapture:
    """Windows DXGI Desktop Duplication 封装"""

    def __init__(self, monitor_index: int = 0, capture_rate: int = 30):
        """
        初始化 DXGI 捕获器

        Args:
            monitor_index: 捕获哪个显示器（从0开始）
            capture_rate: 每秒捕获帧数
        """
        self.monitor_index = monitor_index
        self.capture_rate = capture_rate
        self._capture_interval = 1.0 / max(capture_rate, 1)
        self._latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._capture_impl = None
        self._use_fallback = False
        self._impl_manages_thread = False  # dxcam / d3dshot 自己管理后台线程
        self._logger = None

    def _get_logger(self):
        """延迟获取 logger"""
        if self._logger is None:
            try:
                from core.logger import logger
                self._logger = logger
            except Exception:
                import logging
                self._logger = logging.getLogger("DXGICapture")
        return self._logger

    def _init_capture(self) -> bool:
        """初始化底层捕获实现，返回是否成功"""
        # 1) 首选：dxcam（2026 年活跃维护，性能最好，无已知 fatal crash）
        try:
            import dxcam

            self._capture_impl = dxcam.create(output_idx=self.monitor_index)
            self._impl_manages_thread = True
            self._get_logger().info(
                f"[DXGICapture] 使用 dxcam 进行捕获, monitor={self.monitor_index}"
            )
            return True
        except Exception:
            pass

        # 2) 次选：dxshot
        try:
            import dxshot

            self._capture_impl = dxshot.create()
            self._get_logger().info(
                f"[DXGICapture] 使用 dxshot 进行捕获, monitor={self.monitor_index}"
            )
            return True
        except Exception:
            pass

        # 3) 备选：d3dshot（已停止维护，存在 gc.collect() 导致的 access violation
        #    风险，仅作为兼容性兜底）
        try:
            import d3dshot

            self._capture_impl = d3dshot.create(capture_output="numpy")
            self._impl_manages_thread = True
            self._get_logger().warning(
                f"[DXGICapture] 使用 d3dshot 进行捕获（已弃用，建议迁移到 dxcam）, "
                f"monitor={self.monitor_index}"
            )
            return True
        except Exception:
            pass

        # 4) 降级为 PIL ImageGrab
        self._use_fallback = True
        self._get_logger().warning(
            "[DXGICapture] DXGI 库不可用（dxcam/dxshot/d3dshot 未安装或初始化失败），"
            "降级为 PIL ImageGrab 截图"
        )
        return False

    def _capture_frame(self) -> np.ndarray | None:
        """执行单帧捕获"""
        try:
            if self._use_fallback:
                # PIL ImageGrab 降级方案（PIL 返回 RGB，转为 BGR 统一下游格式）
                img = ImageGrab.grab()
                frame = np.array(img)
                if frame is not None and frame.ndim == 3 and frame.shape[2] == 3:
                    import cv2
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                return frame

            if self._capture_impl is None:
                return None

            # dxcam / d3dshot 自己管理后台线程，直接取最新帧
            if self._impl_manages_thread:
                frame = self._capture_impl.get_latest_frame()
                if frame is not None:
                    if isinstance(frame, np.ndarray):
                        # dxcam 返回 RGB，d3dshot 返回 BGR。统一转为 BGR。
                        if frame.ndim == 3 and frame.shape[2] == 3:
                            # 检测：如果平均 R > 平均 B，大概率是 RGB（正常屏幕 B 通常 > R）
                            # 简单策略：dxcam 明确是 RGB，d3dshot 明确是 BGR
                            impl_name = type(self._capture_impl).__name__.lower()
                            if "dxcam" in impl_name or "dxcamera" in impl_name:
                                import cv2
                                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        return frame
                    # 兼容 PIL Image（Singleton 可能返回旧实例）
                    arr = np.array(frame)
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        import cv2
                        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                    return arr
                return None

            # dxshot 捕获（需要主动抓帧）
            if hasattr(self._capture_impl, "grab"):
                frame = self._capture_impl.grab()
            elif hasattr(self._capture_impl, "screenshot"):
                frame = self._capture_impl.screenshot()
            else:
                frame = None

            if frame is not None and isinstance(frame, np.ndarray):
                return frame
            elif frame is not None:
                return np.array(frame)
            return None

        except Exception as e:
            self._get_logger().warning(f"[DXGICapture] 单帧捕获异常: {e}")
            return None

    def _capture_loop(self):
        """后台捕获线程主循环（仅用于 dxshot / PIL fallback）"""
        while not self._stop_event.is_set():
            start_time = time.time()
            frame = self._capture_frame()
            if frame is not None:
                with self._lock:
                    self._latest_frame = frame
            elapsed = time.time() - start_time
            sleep_time = self._capture_interval - elapsed
            if sleep_time > 0:
                # 使用小步长睡眠以便及时响应停止事件
                while sleep_time > 0 and not self._stop_event.is_set():
                    time.sleep(min(sleep_time, 0.01))
                    sleep_time -= 0.01

    def start(self):
        """启动捕获线程"""
        if self._thread is not None and self._thread.is_alive():
            self._get_logger().warning("[DXGICapture] 捕获线程已在运行")
            return

        self._init_capture()

        # dxcam / d3dshot 自己管理后台捕获线程
        if self._impl_manages_thread and self._capture_impl is not None:
            try:
                # 区分 dxcam(start) 与 d3dshot(capture)
                if hasattr(self._capture_impl, "start"):
                    self._capture_impl.start(target_fps=self.capture_rate)
                elif hasattr(self._capture_impl, "capture"):
                    self._capture_impl.capture()
                else:
                    raise RuntimeError(
                        "捕获实现既无 start() 也无 capture()，无法启动后台线程"
                    )

                self._get_logger().info(
                    f"[DXGICapture] 后台捕获已启动, rate={self.capture_rate}fps"
                )
                # 验证是否能真的捕获到帧
                time.sleep(0.5)
                test_frame = self._capture_impl.get_latest_frame()
                if test_frame is None:
                    raise RuntimeError(
                        "后台捕获启动后 frame_buffer 仍为空，Desktop Duplication 可能不可用"
                    )
                self._get_logger().info(
                    f"[DXGICapture] 验证通过，已获取首帧，"
                    f"shape={getattr(test_frame, 'shape', 'N/A')}"
                )
                return
            except Exception as e:
                self._get_logger().warning(
                    f"[DXGICapture] 后台捕获验证失败: {e}，降级到 PIL"
                )
                # 降级到 PIL
                self._use_fallback = True
                self._impl_manages_thread = False
                try:
                    if hasattr(self._capture_impl, "stop"):
                        self._capture_impl.stop()
                except Exception:
                    pass
                self._capture_impl = None

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self._get_logger().info(
            f"[DXGICapture] 捕获线程已启动, rate={self.capture_rate}fps"
        )

    def stop(self):
        """停止捕获线程"""
        # 停止 dxcam / d3dshot 自带的后台捕获
        if self._impl_manages_thread and self._capture_impl is not None:
            try:
                if hasattr(self._capture_impl, "stop"):
                    self._capture_impl.stop()
            except Exception:
                pass
            self._capture_impl = None
            self._impl_manages_thread = False
            with self._lock:
                self._latest_frame = None
            self._get_logger().info("[DXGICapture] 后台捕获已停止")
            return

        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._latest_frame = None
        self._get_logger().info("[DXGICapture] 捕获线程已停止")

    def get_latest_frame(self) -> np.ndarray | None:
        """获取最新一帧画面（统一返回 BGR，兼容 OpenCV 生态）"""
        # dxcam / d3dshot 自己管理帧缓冲，直接读取
        if self._impl_manages_thread and self._capture_impl is not None:
            try:
                frame = self._capture_impl.get_latest_frame()
                if frame is not None:
                    if isinstance(frame, np.ndarray):
                        frame = frame.copy()
                        if frame.ndim == 3 and frame.shape[2] == 3:
                            impl_name = type(self._capture_impl).__name__.lower()
                            if "dxcam" in impl_name or "dxcamera" in impl_name:
                                import cv2
                                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        return frame
                    # 兼容 PIL Image（Singleton 可能返回旧实例）
                    arr = np.array(frame)
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        import cv2
                        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                    return arr
            except Exception as e:
                self._get_logger().warning(f"[DXGICapture] 后台取帧异常: {e}")

        # 非后台管理模式：PIL fallback 或读取内部缓冲
        if self._use_fallback:
            try:
                img = ImageGrab.grab()
                frame = np.array(img)
                if frame is not None and frame.ndim == 3 and frame.shape[2] == 3:
                    import cv2
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                return frame
            except Exception as e:
                self._get_logger().warning(f"[DXGICapture] PIL 截图异常: {e}")
                return None

        with self._lock:
            if self._latest_frame is None:
                return None
            # 返回副本，避免外部修改影响内部状态
            return self._latest_frame.copy()

    def __del__(self):
        """析构时确保资源释放"""
        self.stop()
