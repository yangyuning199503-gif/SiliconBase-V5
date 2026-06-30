# tools/pixel_monitor.py
#!/usr/bin/env python3
"""
像素监控工具 - 线程安全版本（蓝屏修复）

【蓝屏修复】
- 使用safe_screenshot_to_numpy替换mss.mss()
- 每次截图使用线程安全封装，避免GDI冲突

功能：持续监控屏幕区域变化，支持颜色变化检测、画面变动检测
"""
import asyncio
import threading
import time
from dataclasses import dataclass

import numpy as np

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error, format_success
from core.vision.safe_screenshot import safe_screenshot_to_numpy


@dataclass
class MonitorTask:
    region: dict
    check_interval: float
    callback_type: str  # "color_change", "motion", "appearance"
    target_color: tuple | None
    tolerance: int
    active: bool = True


class PixelMonitor(BaseTool):
    tool_id = "pixel_monitor"
    name = "像素级监控"
    description = "持续监控屏幕指定区域的像素变化，支持颜色变化、画面变动检测。线程安全版本，不与其他视觉工具竞争资源。"
    version = "2.0.0-threadsafe"
    timeout = 60

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "list"],
                "description": "操作：start开始监控, stop停止, list列出活动监控"
            },
            "monitor_id": {
                "type": "string",
                "description": "监控任务ID（stop时需要）"
            },
            "region": {
                "type": "object",
                "description": "监控区域",
                "properties": {
                    "left": {"type": "integer"},
                    "top": {"type": "integer"},
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1}
                }
            },
            "trigger": {
                "type": "string",
                "enum": ["color_stable", "color_change", "motion_stop", "appearance"],
                "description": "触发条件：color_stable颜色稳定, color_change颜色变化, motion_stop画面静止, appearance出现目标"
            },
            "target_color": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "目标颜色（appearance模式需要）"
            },
            "duration": {
                "type": "number",
                "default": 10,
                "description": "监控持续时间（秒），0为一直监控"
            },
            "interval": {
                "type": "number",
                "default": 0.5,
                "description": "检测间隔（秒）"
            },
            "stability_time": {
                "type": "number",
                "default": 1.0,
                "description": "颜色稳定判定时间（秒）"
            }
        },
        "required": ["action"]
    }

    def __init__(self):
        super().__init__()
        self._monitors: dict[str, threading.Thread] = {}
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _execute(self, **kwargs) -> dict:
        action = kwargs["action"]

        if action == "start":
            return self._start_monitor(kwargs)
        elif action == "stop":
            return self._stop_monitor(kwargs.get("monitor_id"))
        elif action == "list":
            return self._list_monitors()
        else:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"未知操作: {action}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _start_monitor(self, kwargs: dict) -> dict:
        """启动监控任务"""
        region = kwargs.get("region")
        trigger = kwargs.get("trigger")

        if not region or not trigger:
            return format_error(TOOL_EXECUTION_ERROR, detail="start操作需要region和trigger")

        monitor_id = f"monitor_{int(time.time() * 1000)}"

        # 创建监控线程
        thread = threading.Thread(
            target=self._monitor_loop,
            args=(monitor_id, kwargs),
            daemon=True
        )

        with self._lock:
            self._monitors[monitor_id] = thread

        thread.start()

        return format_success({
            "monitor_id": monitor_id,
            "status": "started",
            "region": region,
            "trigger": trigger
        }, msg=f"监控任务 {monitor_id} 已启动")

    def _monitor_loop(self, monitor_id: str, config: dict):
        """监控循环 - 【蓝屏修复】使用线程安全截图"""
        region = config["region"]
        trigger = config["trigger"]
        interval = config.get("interval", 0.5)
        duration = config.get("duration", 10)
        stability_time = config.get("stability_time", 1.0)

        start_time = time.time()
        last_frame = None
        last_color = None
        stable_start = None

        try:
            # 【蓝屏修复】不再使用with mss.mss()，改用safe_screenshot_to_numpy
            monitor_region = {
                "left": region["left"],
                "top": region["top"],
                "width": region["width"],
                "height": region["height"]
            }

            while time.time() - start_time < duration or duration == 0:
                if self.is_interrupted():
                    break

                # 【蓝屏修复】使用线程安全截图
                current_frame = safe_screenshot_to_numpy(region=monitor_region)

                if current_frame is None:
                    # 截图失败，稍后重试
                    time.sleep(interval)
                    continue

                if trigger == "color_stable":
                    # 检测颜色是否稳定
                    current_color = current_frame.mean(axis=(0, 1))

                    if last_color is not None:
                        diff = np.abs(current_color - last_color).mean()
                        if diff < 5:  # 变化很小
                            if stable_start is None:
                                stable_start = time.time()
                            elif time.time() - stable_start >= stability_time:
                                # 稳定时间达到
                                self._results[monitor_id] = {
                                    "triggered": True,
                                    "reason": "color_stable",
                                    "stable_color": current_color.tolist(),
                                    "wait_time": time.time() - start_time
                                }
                                break
                        else:
                            stable_start = None

                    last_color = current_color

                elif trigger == "motion_stop":
                    # 检测画面是否静止
                    if last_frame is not None:
                        diff = np.abs(current_frame.astype(float) - last_frame.astype(float)).mean()
                        if diff < 10:  # 几乎无变化
                            if stable_start is None:
                                stable_start = time.time()
                            elif time.time() - stable_start >= stability_time:
                                self._results[monitor_id] = {
                                    "triggered": True,
                                    "reason": "motion_stop",
                                    "wait_time": time.time() - start_time
                                }
                                break
                        else:
                            stable_start = None

                    last_frame = current_frame.copy()

                elif trigger == "appearance":
                    # 检测目标颜色是否出现
                    target = np.array(config.get("target_color", [255, 255, 255]))
                    tolerance = config.get("tolerance", 10)

                    diff = np.abs(current_frame.astype(int) - target)
                    matches = np.all(diff <= tolerance, axis=2)

                    if matches.any():
                        positions = np.argwhere(matches)
                        y, x = positions[0]
                        self._results[monitor_id] = {
                            "triggered": True,
                            "reason": "appearance",
                            "position": {
                                "x": region["left"] + int(x),
                                "y": region["top"] + int(y)
                            },
                            "wait_time": time.time() - start_time
                        }
                        break

                time.sleep(interval)

            else:
                # 超时未触发
                self._results[monitor_id] = {
                    "triggered": False,
                    "reason": "timeout",
                    "duration": duration
                }

        except Exception as e:
            self._results[monitor_id] = {
                "triggered": False,
                "error": str(e)
            }

        finally:
            with self._lock:
                if monitor_id in self._monitors:
                    del self._monitors[monitor_id]

    def _stop_monitor(self, monitor_id: str) -> dict:
        """停止监控任务"""
        if not monitor_id:
            return format_error(TOOL_EXECUTION_ERROR, detail="stop操作需要monitor_id")

        with self._lock:
            if monitor_id in self._monitors:
                # 线程会在下次循环检查中断标志
                del self._monitors[monitor_id]

        # 获取结果
        result = self._results.get(monitor_id, {"status": "stopped_no_result"})

        return format_success({
            "monitor_id": monitor_id,
            "result": result
        }, msg=f"监控任务 {monitor_id} 已停止")

    def _list_monitors(self) -> dict:
        """列出活动监控"""
        with self._lock:
            active = list(self._monitors.keys())

        return format_success({
            "active_monitors": active,
            "count": len(active)
        }, msg=f"当前有 {len(active)} 个活动监控任务")
