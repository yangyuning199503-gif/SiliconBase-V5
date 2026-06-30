#!/usr/bin/env python3
"""
SystemState - 共享状态空间（黑板）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
所有模块的公共状态池。模块把状态写上来，其他模块从这里读。
不经过 LLM，不经过 Prompt，直接内存共享。

设计约束：
1. 极简：只存 Dict，不存复杂对象
2. 快速：asyncio.Lock 保护，无 IO
3. 可观测：状态变化时推 event_bus，支持订阅回调
4. 有生命周期：支持 TTL 自动清理过期状态
"""
import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any, Optional

from core.diagnostic import safe_create_task
from core.logger import logger

try:
    from core.sync.event_bus import event_bus
    _EVENT_BUS_AVAILABLE = True
except Exception:
    _EVENT_BUS_AVAILABLE = False
    event_bus = None  # type: ignore


class SystemState:
    """
    共享状态空间 - 单例

    使用方式：
        from core.runtime import system_state
        system_state.set("vision.alert", {"level": "L2", "msg": "popup"})
        state = system_state.get("vision.alert")
    """
    _instance: Optional["SystemState"] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> "SystemState":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._state: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[Callable[[str, Any], None]]] = {}
        self._state_lock = asyncio.Lock()

    # ═══════════════════════════════════════════════════════════════════
    # 核心读写
    # ═══════════════════════════════════════════════════════════════════

    async def set(self, path: str, value: Any, ttl: float | None = None) -> None:
        """
        写入状态。path 支持点号分隔，如 "consciousness.mood"

        Args:
            path: 状态路径
            value: 任意可序列化值
            ttl: 过期时间（秒），None 表示永不过期
        """
        async with self._state_lock:
            self._state[path] = {
                "data": value,
                "timestamp": time.time(),
                "ttl": ttl,
            }

        # 推事件（非阻塞）
        if _EVENT_BUS_AVAILABLE and event_bus is not None:
            with contextlib.suppress(Exception):
                event_bus.emit("state.changed", {"path": path, "value": value})

        # 触发订阅回调
        await self._notify_subscribers(path, value)

    def set_sync(self, path: str, value: Any, ttl: float | None = None) -> None:
        """同步写入（供非 async 上下文使用）"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.set(path, value, ttl))
        except RuntimeError:
            # 无事件循环时，直接写（无锁保护，仅用于启动阶段）
            self._state[path] = {
                "data": value,
                "timestamp": time.time(),
                "ttl": ttl,
            }

    async def get(self, path: str, default: Any = None) -> Any:
        """读取状态。如果过期返回 default。"""
        async with self._state_lock:
            entry = self._state.get(path)
            if entry is None:
                return default
            if entry.get("ttl") is not None:
                elapsed = time.time() - entry["timestamp"]
                if elapsed > entry["ttl"]:
                    del self._state[path]
                    return default
            return entry["data"]

    def get_sync(self, path: str, default: Any = None) -> Any:
        """同步读取（供非 async 上下文使用）"""
        entry = self._state.get(path)
        if entry is None:
            return default
        if entry.get("ttl") is not None:
            elapsed = time.time() - entry["timestamp"]
            if elapsed > entry["ttl"]:
                with contextlib.suppress(Exception):
                    del self._state[path]
                return default
        return entry["data"]

    async def delete(self, path: str) -> bool:
        """删除状态。返回是否成功删除。"""
        async with self._state_lock:
            if path in self._state:
                del self._state[path]
                return True
            return False

    async def get_all(self, prefix: str | None = None) -> dict[str, Any]:
        """批量读取，可选前缀过滤。自动清理过期项。"""
        result: dict[str, Any] = {}
        now = time.time()
        expired_keys: list[str] = []

        async with self._state_lock:
            for path, entry in list(self._state.items()):
                if entry.get("ttl") is not None and (now - entry["timestamp"]) > entry["ttl"]:
                    expired_keys.append(path)
                    continue
                if prefix is None or path.startswith(prefix):
                    result[path] = entry["data"]
            for k in expired_keys:
                self._state.pop(k, None)

        return result

    # ═══════════════════════════════════════════════════════════════════
    # 订阅机制（反射弧注册点）
    # ═══════════════════════════════════════════════════════════════════

    def subscribe(self, path_prefix: str, callback: Callable[[str, Any], None]) -> None:
        """
        订阅状态变化。path_prefix 支持通配前缀匹配。

        示例：
            system_state.subscribe("vision.alert", on_vision_alert)
            system_state.subscribe("consciousness.", on_any_consciousness_change)
        """
        self._subscribers.setdefault(path_prefix, []).append(callback)
        logger.info(f"[SystemState] 新订阅: {path_prefix}, 当前订阅数: {len(self._subscribers[path_prefix])}")

    def unsubscribe(self, path_prefix: str, callback: Callable[[str, Any], None]) -> None:
        """取消订阅"""
        if path_prefix in self._subscribers:
            with contextlib.suppress(ValueError):
                self._subscribers[path_prefix].remove(callback)

    async def _notify_subscribers(self, path: str, value: Any) -> None:
        """通知匹配的订阅者"""
        for prefix, callbacks in self._subscribers.items():
            if path.startswith(prefix):
                for cb in callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            safe_create_task(cb(path, value), name="cb")
                        else:
                            cb(path, value)
                    except Exception as e:
                        logger.warning(f"[SystemState] 订阅回调异常 {path}: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # 便捷封装：批量模块状态写入
    # ═══════════════════════════════════════════════════════════════════

    async def update_module_state(self, module: str, states: dict[str, Any], ttl: float | None = None) -> None:
        """批量更新某个模块的状态"""
        for key, value in states.items():
            await self.set(f"{module}.{key}", value, ttl)

    # ═══════════════════════════════════════════════════════════════════
    # 调试与监控
    # ═══════════════════════════════════════════════════════════════════

    async def snapshot(self) -> dict[str, Any]:
        """获取当前完整状态快照（用于监控面板）"""
        return await self.get_all()


# 全局单例
system_state = SystemState()
