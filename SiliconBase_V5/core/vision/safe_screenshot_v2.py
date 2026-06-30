#!/usr/bin/env python3
"""
线程安全的截图工具 V2 - 增强版，防止卡死/死锁

【关键修复 V2】
1. 全局锁 + 超时保护（防止死锁）
2. 截图间隔限制（最小100ms间隔，防止GPU过载）
3. 单例MSS实例（减少资源占用）
4. 显存检查
5. 截图队列（避免并发冲突）

MSS底层使用Windows GDI API，多线程同时调用可能导致：
- 显卡驱动崩溃（蓝屏）
- 死锁（卡死）
- GPU资源耗尽
"""

import asyncio
import io
import logging
import sys
import threading
import time
from typing import Any

import aiofiles

from core.vision.dpi import logical_to_physical

logger = logging.getLogger(__name__)

# 【魔法数字修复】导入全局常量
try:
    from core.constants import ScreenshotConfig
except ImportError as e:
    logger.error(f"[SafeScreenshotV2] 导入ScreenshotConfig常量失败: {e}")
    # 定义 fallback 常量值
    class ScreenshotConfig:
        MIN_INTERVAL = 0.1       # 最小截图间隔(秒)
        DEFAULT_TIMEOUT = 10.0   # 默认超时(秒)

# =============================================================================
# V2 增强保护机制
# =============================================================================

# 全局MSS锁 - 确保同一时间只有一个线程使用MSS
_mss_global_lock = threading.Lock()

# 单例MSS实例（V2改进：全局单例而非每线程一个，减少资源占用）
_mss_instance = None
_mss_instance_lock = threading.Lock()

# 全局状态锁（保护_last_screenshot_time）
_time_lock = threading.Lock()
_last_screenshot_time = 0
_screenshot_interval = ScreenshotConfig.MIN_INTERVAL  # 最小截图间隔100ms

# 截图超时时间
SCREENSHOT_TIMEOUT = ScreenshotConfig.DEFAULT_TIMEOUT  # 秒


def _get_mss_instance():
    """获取全局单例MSS实例（V2：单例模式减少资源占用）"""
    global _mss_instance
    if _mss_instance is None:
        with _mss_instance_lock:
            if _mss_instance is None:
                try:
                    import mss
                    _mss_instance = mss.mss()
                    logger.info("[SafeScreenshotV2] MSS全局单例已创建")
                except Exception as e:
                    logger.error(f"[SafeScreenshotV2] MSS初始化失败: {e}")
                    raise
    return _mss_instance


def _check_screenshot_interval() -> bool:
    """检查截图间隔，防止过于频繁（线程安全）"""
    global _last_screenshot_time

    with _time_lock:  # 加锁保护全局状态
        current_time = time.time()
        elapsed = current_time - _last_screenshot_time
        sleep_time = max(0, _screenshot_interval - elapsed)
        # 预占时间戳，避免释放锁后其他线程插队导致实际间隔更小
        _last_screenshot_time = current_time + sleep_time if sleep_time > 0 else current_time

    # 【蓝屏修复】必须在释放锁后再 sleep，否则所有截图线程排队睡眠，链式阻塞
    if sleep_time > 0:
        logger.debug(f"[SafeScreenshotV2] 截图间隔限制，等待{sleep_time:.3f}s")
        time.sleep(sleep_time)

    return True


def _close_mss_instance():
    """关闭MSS实例（程序退出时调用）"""
    global _mss_instance
    if _mss_instance is not None:
        try:
            _mss_instance.close()
            print("[SafeScreenshotV2] MSS实例已关闭", file=sys.stderr)
        except Exception as e:
            print(f"[CRITICAL ERROR][SafeScreenshotV2] 关闭MSS实例时出错: {e}", file=sys.stderr)
        finally:
            _mss_instance = None


def safe_screenshot_v2(monitor: int = 1, region: dict | None = None, timeout: int = SCREENSHOT_TIMEOUT) -> tuple[Any | None, str | None]:
    """
    线程安全的截图函数 V2（带超时保护）

    Args:
        monitor: 显示器索引（1=主屏幕）
        region: 区域坐标 {left, top, width, height}
        timeout: 超时时间（秒）

    Returns:
        (screenshot对象, 错误信息)
    """
    # 检查截图间隔
    _check_screenshot_interval()

    # 使用全局锁，带超时
    acquired = _mss_global_lock.acquire(timeout=timeout)
    if not acquired:
        return None, f"截图超时：无法获取截图锁（{timeout}秒）"

    try:
        sct = _get_mss_instance()

        if region:
            # 区域截图（逻辑坐标 → 物理像素）
            physical_region = logical_to_physical(region)
            monitor_dict = {
                "left": physical_region.get("left", 0),
                "top": physical_region.get("top", 0),
                "width": physical_region.get("width", 1920),
                "height": physical_region.get("height", 1080)
            }
            screenshot = sct.grab(monitor_dict)
        else:
            # 全屏截图
            if monitor < len(sct.monitors):
                screenshot = sct.grab(sct.monitors[monitor])
            else:
                return None, f"显示器索引{monitor}超出范围"

        return screenshot, None

    except Exception as e:
        error_msg = f"截图失败: {str(e)}"
        logger.error(f"[SafeScreenshotV2] {error_msg}")
        return None, error_msg
    finally:
        _mss_global_lock.release()


def safe_screenshot_to_pil_v2(monitor: int = 1, region: dict | None = None, timeout: int = SCREENSHOT_TIMEOUT):
    """
    线程安全的截图，返回PIL Image（V2带超时保护）
    【蓝屏修复】返回独立副本并释放中间资源

    Returns:
        PIL.Image 或 None
    """
    import gc

    from PIL import Image

    screenshot, error = safe_screenshot_v2(monitor, region, timeout)
    if error or screenshot is None:
        logger.warning(f"[SafeScreenshotV2] 截图失败: {error}")
        return None

    try:
        # MSS截图转PIL
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        result = img.copy()
        return result
    except Exception as e:
        logger.error(f"[SafeScreenshotV2] 转换为PIL失败: {e}")
        return None
    finally:
        if 'img' in locals():
            img.close()
            del img
        gc.collect()


def safe_screenshot_to_numpy_v2(monitor: int = 1, region: dict | None = None, timeout: int = SCREENSHOT_TIMEOUT):
    """
    线程安全的截图，返回NumPy数组（V2带超时保护）

    Returns:
        numpy.ndarray 或 None
    """
    import numpy as np

    screenshot, error = safe_screenshot_v2(monitor, region, timeout)
    if error or screenshot is None:
        logger.warning(f"[SafeScreenshotV2] 截图失败: {error}")
        return None

    try:
        img_array = np.array(screenshot)
        # BGR to RGB if needed
        if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
            img_array = img_array[:, :, :3][:, :, ::-1]
        return img_array
    except Exception as e:
        logger.error(f"[SafeScreenshotV2] 转换为NumPy失败: {e}")
        return None


# 向后兼容：V1 API调用V2实现
safe_screenshot = safe_screenshot_v2
safe_screenshot_to_pil = safe_screenshot_to_pil_v2
safe_screenshot_to_numpy = safe_screenshot_to_numpy_v2


# 程序退出时清理
import atexit

atexit.register(_close_mss_instance)


# =============================================================================
# ThreadSafePixelCapture 类 - 线程安全的像素捕获辅助类
# =============================================================================

class ThreadSafePixelCapture:
    """
    线程安全的像素捕获辅助类

    使用ResourceCoordinator确保全局只有一个截图操作在执行，
    防止MSS库的GDI资源冲突
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._coordinator = None
        try:
            from core.resource_coordinator import coordinator
            self._coordinator = coordinator
        except ImportError as e:
            logger.error(f"[ThreadSafePixelCapture] 无法导入ResourceCoordinator: {e}")
            # 降级到本地锁
            self._coordinator = None

    def capture(self, monitor: int = 1, region: dict | None = None,
                timeout: float = 10.0) -> tuple[Any | None, str | None]:
        """
        线程安全地捕获屏幕截图

        Args:
            monitor: 显示器编号
            region: 截图区域 {left, top, width, height}
            timeout: 超时时间（秒）

        Returns:
            (PIL Image, None) 或 (None, 错误信息)
        """
        try:
            if self._coordinator:
                # 使用ResourceCoordinator (V3)
                from .safe_screenshot import safe_screenshot_to_pil_v3
                result = safe_screenshot_to_pil_v3(monitor, region, timeout)
                if result is None:
                    return None, "截图失败: safe_screenshot_to_pil_v3返回None"
                return result, None
            else:
                # 降级到本地锁 (V2)
                result = safe_screenshot_to_pil_v2(monitor, region, timeout)
                if result is None:
                    return None, "截图失败: safe_screenshot_to_pil_v2返回None"
                return result, None
        except Exception as e:
            error_msg = f"[ThreadSafePixelCapture] 截图失败: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    async def capture_async(self, monitor: int = 1, region: dict | None = None,
                            timeout: float = 10.0) -> tuple[Any | None, str | None]:
        """异步捕获屏幕截图（to_thread桥接）"""
        return await asyncio.to_thread(self.capture, monitor, region, timeout)

    def capture_to_numpy(self, monitor: int = 1, region: dict | None = None,
                         timeout: float = 10.0) -> tuple[Any | None, str | None]:
        """
        线程安全地捕获屏幕截图并转换为numpy数组

        Args:
            monitor: 显示器编号
            region: 截图区域 {left, top, width, height}
            timeout: 超时时间（秒）

        Returns:
            (numpy数组, None) 或 (None, 错误信息)
        """
        try:
            pil_image, error = self.capture(monitor, region, timeout)
            if error:
                return None, error
            if pil_image is None:
                error_msg = "[ThreadSafePixelCapture] 截图返回None"
                logger.error(error_msg)
                return None, error_msg
            import numpy as np
            return np.array(pil_image), None
        except Exception as e:
            error_msg = f"[ThreadSafePixelCapture] 转换为numpy失败: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    def capture_to_file(self, filepath: str, monitor: int = 1,
                        region: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """
        线程安全地捕获屏幕截图并保存到文件

        Args:
            filepath: 保存文件路径
            monitor: 显示器编号
            region: 截图区域 {left, top, width, height}
            timeout: 超时时间（秒）

        Returns:
            {"success": True, "path": filepath} 或 {"success": False, "error": 错误信息}
        """
        try:
            pil_image, error = self.capture(monitor, region, timeout)
            if error or pil_image is None:
                error_msg = error or "截图返回None"
                logger.error(f"[ThreadSafePixelCapture] capture_to_file失败: {error_msg}")
                return {"success": False, "error": error_msg}

            # 确保目录存在
            import os
            save_dir = os.path.dirname(filepath)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            # 保存文件
            pil_image.save(filepath)
            return {"success": True, "path": filepath}

        except Exception as e:
            error_msg = f"[ThreadSafePixelCapture] 保存文件失败: {e}"
            logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    async def capture_to_file_async(self, filepath: str, monitor: int = 1,
                                    region: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """
        异步捕获屏幕截图并保存到文件。
        截图使用 capture_async（to_thread 桥接 MSS），文件保存使用 aiofiles 原生异步。

        Args:
            filepath: 保存文件路径
            monitor: 显示器编号
            region: 截图区域 {left, top, width, height}
            timeout: 超时时间（秒）

        Returns:
            {"success": True, "path": filepath} 或 {"success": False, "error": 错误信息}
        """
        try:
            pil_image, error = await self.capture_async(monitor, region, timeout)
            if error or pil_image is None:
                error_msg = error or "截图返回None"
                logger.error(f"[ThreadSafePixelCapture] capture_to_file_async 失败: {error_msg}")
                return {"success": False, "error": error_msg}

            # 确保目录存在（同步 os.makedirs 可接受，仅创建目录）
            import os
            save_dir = os.path.dirname(filepath)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            # 原生异步保存文件
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(buffer.getvalue())

            return {"success": True, "path": filepath}

        except Exception as e:
            error_msg = f"[ThreadSafePixelCapture] capture_to_file_async 保存失败: {e}"
            logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}


def get_safe_capture() -> ThreadSafePixelCapture:
    """
    获取ThreadSafePixelCapture单例实例

    Returns:
        ThreadSafePixelCapture实例
    """
    global _safe_capture_instance
    try:
        return _safe_capture_instance
    except NameError:
        _safe_capture_instance = ThreadSafePixelCapture()
        return _safe_capture_instance
