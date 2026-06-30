"""
21 板块注册表 - 思维线程对板块的统一调度入口

- 维护每个板块的元数据（名称、状态、命令主题）。
- 思维线程不直接调用板块内部 API，而是通过注册表发送命令。
- 板块通过事件总线 `plate:{plate_id}:command` 接收命令，或提供直接回调。
"""
from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from core.protocol import MSG_PLATE_COMMAND
from core.sync.event_bus import event_bus

logger = logging.getLogger(__name__)


# 初始 21 板块静态列表（与当前系统模块对应）
DEFAULT_PLATES = [
    ("vision", "视觉感知"),
    ("weak_connection", "弱连接引擎"),
    ("trading", "BTC/交易指挥官"),
    ("memory", "记忆系统"),
    ("global_view", "全局视野"),
    ("voice", "语音系统"),
    ("goal_system", "目标系统"),
    ("reflector", "反思器"),
    ("experience", "经验系统"),
    ("evolution", "进化引擎"),
    ("world_model", "世界模型"),
    ("safety", "安全守卫"),
    ("intervention", "实时干预"),
    ("dialogue", "对话管理"),
    ("task_scheduler", "任务调度"),
    ("mode", "工作模式"),
    ("cost", "成本管理"),
    ("perception", "感知总线"),
    ("inner_monologue", "内心独白"),
    ("intrinsic_motivation", "内在动机"),
    ("consciousness_self", "自我意识"),
]


class PlateRegistry:
    """板块注册表，线程安全由 GIL + 单线程调用保证。"""

    def __init__(self):
        self._plates: dict[str, dict[str, Any]] = {}
        self._command_handlers: dict[str, Callable] = {}
        for pid, name in DEFAULT_PLATES:
            self.register_plate(pid, name)

    def register_plate(
        self,
        plate_id: str,
        name: str,
        status: str = "active",
        command_topic: str | None = None,
        handler: Callable | None = None,
    ) -> None:
        """注册/更新一个板块。"""
        if command_topic is None:
            command_topic = f"plate:{plate_id}:command"
        self._plates[plate_id] = {
            "id": plate_id,
            "name": name,
            "status": status,  # active / hibernating / error / unknown
            "command_topic": command_topic,
            "registered_at": time.time(),
            "updated_at": time.time(),
        }
        if handler is not None:
            self._command_handlers[plate_id] = handler

    def list_plates(self) -> list[dict[str, Any]]:
        return list(self._plates.values())

    def get_plate(self, plate_id: str) -> dict[str, Any] | None:
        return self._plates.get(plate_id)

    def get_status(self, plate_id: str) -> str:
        return self._plates.get(plate_id, {}).get("status", "unknown")

    def set_status(self, plate_id: str, status: str) -> None:
        if plate_id in self._plates:
            self._plates[plate_id]["status"] = status
            self._plates[plate_id]["updated_at"] = time.time()
        else:
            logger.warning(f"[PlateRegistry] 尝试设置未知板块状态: {plate_id}")

    def send_command(
        self,
        plate_id: str,
        action: str,
        params: dict[str, Any] | None = None,
        source: str = "consciousness",
        trace_id: str = "",
    ) -> bool:
        """
        向板块发送调度命令。
        优先调用注册的直接 handler，否则通过事件总线广播。
        """
        plate = self._plates.get(plate_id)
        if plate is None:
            logger.warning(f"[PlateRegistry] 无法向未知板块发命令: {plate_id}")
            return False

        payload = {
            "plate_id": plate_id,
            "action": action,
            "params": params or {},
            "source": source,
            "timestamp": time.time(),
            "trace_id": trace_id,
        }

        # 1. 如果板块注册了直接回调，优先同步调用
        handler = self._command_handlers.get(plate_id)
        if handler is not None:
            try:
                if asyncio_coro(handler):
                    # 异步 handler 需要外部事件循环调度
                    import asyncio
                    with contextlib.suppress(RuntimeError):
                        asyncio.get_running_loop().create_task(handler(payload))
                else:
                    handler(payload)
                return True
            except Exception as e:
                logger.error(f"[PlateRegistry] 板块 {plate_id} 直接命令失败: {e}", exc_info=True)
                # 失败后仍尝试事件总线

        # 2. 通过事件总线发布
        try:
            event_bus.emit_async(
                MSG_PLATE_COMMAND,
                {"topic": plate["command_topic"], "payload": payload},
                source=source,
                trace_id=trace_id,
            )
            # 同时发布到专用 topic，便于板块订阅
            event_bus.emit_async(
                plate["command_topic"],
                payload,
                source=source,
                trace_id=trace_id,
            )
            logger.info(f"[PlateRegistry] 发送命令 [{plate_id}/{action}] 到 {plate['command_topic']}")
            return True
        except Exception as e:
            logger.error(f"[PlateRegistry] 事件总线发送命令失败: {e}", exc_info=True)
            return False

    def all_active(self) -> list[str]:
        return [pid for pid, p in self._plates.items() if p.get("status") == "active"]

    def all_hibernating(self) -> list[str]:
        return [pid for pid, p in self._plates.items() if p.get("status") == "hibernating"]


def asyncio_coro(obj):
    """简单判断对象是否是协程函数或协程对象。"""
    import inspect
    if inspect.iscoroutinefunction(obj):
        return True
    if inspect.iscoroutine(obj):
        return True
    return bool(callable(obj) and inspect.iscoroutinefunction(obj.__call__))


# 全局单例
_plate_registry_instance: PlateRegistry | None = None


def get_plate_registry() -> PlateRegistry:
    global _plate_registry_instance
    if _plate_registry_instance is None:
        _plate_registry_instance = PlateRegistry()
    return _plate_registry_instance
