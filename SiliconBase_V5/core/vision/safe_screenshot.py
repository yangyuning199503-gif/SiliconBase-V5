#!/usr/bin/env python3
"""
线程安全截图 V3 - 集成资源协调器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
通过ResourceCoordinator统一管理截图资源，
确保所有截图操作串行执行，避免MSS冲突。
"""

import contextlib
import logging
from typing import Any

from core.vision.dpi import logical_to_physical

logger = logging.getLogger(__name__)


def safe_screenshot_v3(monitor: int = 1, region: dict | None = None, timeout: float = 10.0) -> tuple[Any | None, str | None]:
    """
    线程安全截图 V3 - 使用资源协调器

    【改进】
    - 截图请求加入资源队列
    - 串行执行，避免并发冲突
    - 超时保护
    - 【P0修复】显式释放GDI资源，避免句柄累积

    Args:
        monitor: 显示器索引
        region: 区域坐标
        timeout: 超时时间

    Returns:
        (screenshot对象, 错误信息)
    """
    import threading

    from core.resource_coordinator import Priority, ResourceType, coordinator

    result_container = {"screenshot": None, "error": None}
    event = threading.Event()

    def do_screenshot(monitor, region):
        """实际截图操作"""
        try:
            # 使用原版safe_screenshot_v2的实现
            import mss

            with mss.mss() as sct:
                if region:
                    # 【P0修复】DPI缩放：外部传入逻辑坐标，内部转换为物理像素
                    physical_region = logical_to_physical(region)
                    monitor_dict = {
                        "left": physical_region.get("left", 0),
                        "top": physical_region.get("top", 0),
                        "width": physical_region.get("width", 1920),
                        "height": physical_region.get("height", 1080)
                    }
                    screenshot = sct.grab(monitor_dict)
                else:
                    if monitor < len(sct.monitors):
                        screenshot = sct.grab(sct.monitors[monitor])
                    else:
                        result_container["error"] = f"显示器索引{monitor}超出范围"
                        event.set()
                        return

                result_container["screenshot"] = screenshot

        except Exception as e:
            result_container["error"] = f"截图失败: {e}"
            logger.error(f"[SafeScreenshotV3] {e}")

        finally:
            event.set()

    # 请求资源
    success = coordinator.request_resource(
        resource_type=ResourceType.SCREENSHOT,
        callback=do_screenshot,
        params={"monitor": monitor, "region": region},
        priority=Priority.HIGH,
        timeout=timeout
    )

    if not success:
        return None, "无法加入截图队列"

    # 等待完成
    if event.wait(timeout=timeout):
        result = result_container["screenshot"], result_container["error"]
        # 【P0修复】显式释放GDI句柄引用，避免累积
        if result_container["screenshot"] is not None:
            with contextlib.suppress(Exception):
                del result_container["screenshot"]
        return result
    else:
        return None, f"截图超时({timeout}秒)"


def safe_screenshot_to_pil_v3(monitor: int = 1, region: dict | None = None, timeout: float = 10.0):
    """截图返回PIL Image"""
    import gc
    screenshot, error = safe_screenshot_v3(monitor, region, timeout)
    if error or screenshot is None:
        logger.warning(f"[SafeScreenshotV3] 截图失败: {error}")
        return None

    try:
        from PIL import Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        # 【P0修复】返回独立副本，避免GDI数据残留影响后续处理
        result = img.copy()
        # 显式关闭原始图像，释放资源
        img.close()
        del img
        gc.collect()
        return result
    except Exception as e:
        logger.error(f"[SafeScreenshotV3] 转换PIL失败: {e}")
        return None
    finally:
        # 【P0修复】强制释放MSS截图对象的GDI资源
        try:
            del screenshot
            gc.collect()
        except Exception:
            pass


def safe_screenshot_to_numpy_v3(monitor: int = 1, region: dict | None = None, timeout: float = 10.0):
    """截图返回NumPy数组"""
    import gc

    import numpy as np

    screenshot, error = safe_screenshot_v3(monitor, region, timeout)
    if error or screenshot is None:
        logger.warning(f"[SafeScreenshotV3] 截图失败: {error}")
        return None

    try:
        img_array = np.array(screenshot)
        if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
            # 【P0修复】使用ascontiguousarray确保连续内存的独立副本
            img_array = np.ascontiguousarray(img_array[:, :, :3][:, :, ::-1])
        gc.collect()
        return img_array
    except Exception as e:
        logger.error(f"[SafeScreenshotV3] 转换NumPy失败: {e}")
        return None
    finally:
        # 【P0修复】强制释放MSS截图对象
        try:
            del screenshot
            gc.collect()
        except Exception:
            pass


# 向后兼容
safe_screenshot = safe_screenshot_v3
safe_screenshot_to_pil = safe_screenshot_to_pil_v3
safe_screenshot_to_numpy = safe_screenshot_to_numpy_v3
