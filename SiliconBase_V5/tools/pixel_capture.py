# tools/pixel_capture.py
#!/usr/bin/env python3
"""
像素级截图工具 - 线程安全版本（蓝屏修复）

【关键修复】
- 使用core/vision/safe_screenshot中的线程安全封装
- 消除MSS多实例冲突导致的蓝屏风险
- 作为VisualUnderstand的辅助工具，不直接竞争视觉AI资源

注意：此工具只截图，不执行AI分析。
如需AI分析屏幕，请使用 visual_understand 工具。
"""
import asyncio
import logging
import os
import traceback

import numpy as np
from PIL import Image

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error, format_success

# 导入安全截图函数
try:
    from core.vision.safe_screenshot import (
        safe_screenshot_to_numpy,
        safe_screenshot_to_pil,
    )
except ImportError as e:
    logging.error(f"[PixelCapture] 无法导入safe_screenshot: {e}")
    raise RuntimeError("PixelCapture工具依赖safe_screenshot，但导入失败") from e

# 导入ThreadSafePixelCapture类
try:
    from core.vision.safe_screenshot_v2 import ThreadSafePixelCapture
except ImportError as e:
    logging.error(f"[PixelCapture] 无法导入ThreadSafePixelCapture: {e}")
    raise RuntimeError("PixelCapture工具依赖ThreadSafePixelCapture，但导入失败") from e

logger = logging.getLogger(__name__)


class PixelCapture(BaseTool):
    tool_id = "pixel_capture"
    name = "像素级截图"
    description = "【仅截图】高性能屏幕截图，支持区域捕获和原始像素数据获取。不执行AI分析，如需AI理解屏幕请使用 visual_understand。"
    version = "2.0.0-threadsafe"  # 版本升级，标记为线程安全
    timeout = 15

    input_schema = {
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "description": "捕获区域，不传则全屏",
                "properties": {
                    "left": {"type": "integer", "minimum": 0},
                    "top": {"type": "integer", "minimum": 0},
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1}
                },
                "required": ["left", "top", "width", "height"]
            },
            "monitor": {
                "type": "integer",
                "default": 1,
                "minimum": 0,
                "description": "显示器编号，1为主屏，0为所有屏幕"
            },
            "output_format": {
                "type": "string",
                "enum": ["pil", "numpy", "bytes", "file"],
                "default": "pil",
                "description": "输出格式：pil(PIL.Image), numpy数组, bytes原始数据, 或保存到文件"
            },
            "save_path": {
                "type": "string",
                "description": "保存路径（output_format为file时必需）"
            }
        }
    }

    output_schema = {
        "type": "object",
        "properties": {
            "size": {"type": "array", "items": {"type": "integer"}},
            "mode": {"type": "string"},
            "data_sample": {"type": "string"}
        }
    }

    def __init__(self):
        super().__init__()
        # 【蓝屏修复】不再缓存MSS实例，每次通过safe_screenshot获取
        self._capture_helper = ThreadSafePixelCapture()
        logger.debug("PixelCapture instance created (thread-safe version)")

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步执行截图 - 显式桥接到线程池

        截图操作（MSS/pyautogui）本质上是同步的系统调用，无法真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        """
        执行截图 - 使用线程安全封装
        """
        try:
            # 提取参数
            monitor_idx = kwargs.get("monitor", 1)
            region = kwargs.get("region")
            save_path = kwargs.get("save_path")
            output_format = kwargs.get("output_format", "file" if save_path else "pil")

            logger.debug(
                f"[PixelCapture] Screenshot request: monitor={monitor_idx}, "
                f"region={region}, format={output_format}"
            )

            # 【蓝屏修复】使用线程安全截图
            if output_format == "file":
                if not save_path:
                    return format_error(
                        TOOL_EXECUTION_ERROR,
                        detail="file格式需要save_path参数"
                    )
                return self._capture_to_file(save_path, monitor_idx, region)

            # 获取图像数据
            if output_format == "pil":
                img = safe_screenshot_to_pil(monitor_idx, region)
                if img is None:
                    return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")
                return self._format_pil_result(img, region)

            elif output_format == "numpy":
                arr = safe_screenshot_to_numpy(monitor_idx, region)
                if arr is None:
                    return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")
                return self._format_numpy_result(arr, region)

            elif output_format == "bytes":
                img = safe_screenshot_to_pil(monitor_idx, region)
                if img is None:
                    return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")
                import gc
                import io
                buffer = io.BytesIO()
                try:
                    img.save(buffer, format="PNG")
                    return self._format_bytes_result(buffer.getvalue(), img.size, region)
                finally:
                    buffer.close()
                    img.close()
                    del img
                    gc.collect()
            else:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"不支持的格式: {output_format}"
                )

        except Exception as e:
            error_msg = f"截图工具执行异常: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"{error_msg}\n堆栈跟踪:\n{traceback.format_exc()}"
            )

    def _capture_to_file(self, save_path: str, monitor: int, region: dict | None) -> dict:
        """截图并保存到文件"""
        # 确保目录存在
        save_dir = os.path.dirname(save_path)
        if save_dir and not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)
                logger.debug(f"[PixelCapture] Created directory: {save_dir}")
            except Exception as e:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"无法创建保存目录: {e}"
                )

        # 使用线程安全截图
        result = self._capture_helper.capture_to_file(save_path, monitor, region)

        if result.get("success"):
            return format_success({
                "path": save_path,
                "format": "file",
                "region": region if region else "full"
            }, msg=f"截图已保存: {save_path}")
        else:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=result.get("error", "保存文件失败")
            )

    def _format_pil_result(self, img: Image.Image, region: dict | None) -> dict:
        """格式化PIL结果"""
        return format_success({
            "size": img.size,
            "format": "pil",
            "region": region if region else "full",
            "image": img,
            "mode": img.mode
        }, msg=f"截图成功 {img.size[0]}x{img.size[1]}")

    def _format_numpy_result(self, arr: np.ndarray, region: dict | None) -> dict:
        """格式化NumPy结果"""
        return format_success({
            "size": (arr.shape[1], arr.shape[0]),
            "format": "numpy",
            "region": region if region else "full",
            "image": arr,
            "shape": arr.shape
        }, msg=f"截图成功 {arr.shape[1]}x{arr.shape[0]}")

    def _format_bytes_result(self, data: bytes, size: tuple[int, int], region: dict | None) -> dict:
        """格式化bytes结果"""
        return format_success({
            "size": size,
            "format": "bytes",
            "region": region if region else "full",
            "data": data,
            "bytes_length": len(data)
        }, msg=f"截图成功 {size[0]}x{size[1]}, {len(data)} bytes")
