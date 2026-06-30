#!/usr/bin/env python3
"""
ActionCoordinator - 动作协调器（小脑）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：协调同时运行的多个动作，管理时序、资源冲突、优先级。
不决策"做什么"，只决策"怎么做"和"什么时候做"。

核心规则：
1. 语音播报期间，鼠标移动自动分片（每步检查中断）
2. 工具执行期间，语音播报标记 protected（避免被低优任务打断）
3. 视觉告警发生时，所有非紧急动作暂停
4. 冲突动作按优先级排队，不抢占已 protected 的播报
"""
import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.logger import logger

try:
    from core.runtime import system_state
    _SYSTEM_STATE_AVAILABLE = True
except Exception:
    _SYSTEM_STATE_AVAILABLE = False
    system_state = None  # type: ignore


class ActionStatus(Enum):
    PENDING = "pending"      # 等待协调器调度
    RUNNING = "running"      # 正在执行
    PAUSED = "paused"        # 被协调器暂停
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消


class ActionType(Enum):
    SPEECH = "speech"        # 语音播报
    MOUSE = "mouse"          # 鼠标操作
    KEYBOARD = "keyboard"    # 键盘操作
    TOOL = "tool"            # 通用工具
    SYSTEM = "system"        # 系统级操作


@dataclass
class ActionSlot:
    action_id: str
    action_type: ActionType
    status: ActionStatus
    priority: int = 5          # 数字越小越优先
    start_time: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)
    # 协调器注入的约束
    fragment_size: int | None = None   # 分片大小（如鼠标每移动多少像素检查一次）
    protected: bool = False                # 是否受保护（不被打断）
    speed_ratio: float = 1.0               # 速度倍率（1.0=正常，0.5=降速）


class ActionCoordinator:
    """
    动作协调器 - 单例

    所有需要协调的动作，在执行前应先向协调器注册。
    协调器根据当前系统状态，返回执行约束（分片/速度/保护）。
    """
    _instance: Optional["ActionCoordinator"] = None

    def __new__(cls) -> "ActionCoordinator":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._actions: dict[str, ActionSlot] = {}
        self._lock = asyncio.Lock()
        self._subscriptions_setup = False

        # 协调规则配置
        self._rules = {
            # 语音播报期间，鼠标移动分片大小
            "speech_mouse_fragment": 100,
            # 语音播报期间，鼠标速度倍率
            "speech_mouse_speed": 0.5,
            # 工具执行期间，语音自动保护
            "tool_protects_speech": True,
            # 视觉告警期间，非紧急动作暂停
            "vision_alert_pause_non_urgent": True,
        }

        # 类型冲突矩阵：哪些类型不能同时满速运行
        self._conflict_matrix: dict[ActionType, list[ActionType]] = {
            ActionType.SPEECH: [ActionType.MOUSE, ActionType.KEYBOARD],
            ActionType.MOUSE: [ActionType.SPEECH],
            ActionType.KEYBOARD: [ActionType.SPEECH],
        }

    def setup_subscriptions(self) -> None:
        """订阅 SystemState 变化（应在事件循环启动后调用一次）"""
        if self._subscriptions_setup or not _SYSTEM_STATE_AVAILABLE or system_state is None:
            return
        self._subscriptions_setup = True

        try:
            system_state.subscribe("speech.", self._on_speech_state_change)
            system_state.subscribe("vision.alert", self._on_vision_alert)
            system_state.subscribe("action.", self._on_action_state_change)
            logger.info("[ActionCoordinator] SystemState 订阅已建立")
        except Exception as e:
            logger.warning(f"[ActionCoordinator] 订阅失败: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # 动作注册与管理
    # ═══════════════════════════════════════════════════════════════════

    async def register(self, action_id: str, action_type: ActionType, priority: int = 5,
                       payload: dict[str, Any] | None = None) -> ActionSlot:
        """
        注册一个新动作。协调器根据当前系统状态，返回执行约束。

        调用方应读取返回的 ActionSlot，按约束执行：
            slot = await coordinator.register("move_1", ActionType.MOUSE, priority=3)
            if slot.status == ActionStatus.PAUSED:
                await asyncio.sleep(0.1)  # 等待协调
            # 按 slot.fragment_size 和 slot.speed_ratio 执行
        """
        async with self._lock:
            # 清理已完成/已取消的动作
            expired = [k for k, v in self._actions.items()
                       if v.status in (ActionStatus.COMPLETED, ActionStatus.CANCELLED)]
            for k in expired:
                del self._actions[k]

            # 计算约束
            constraints = await self._compute_constraints(action_type, priority)

            slot = ActionSlot(
                action_id=action_id,
                action_type=action_type,
                status=ActionStatus.PENDING,
                priority=priority,
                payload=payload or {},
                fragment_size=constraints.get("fragment_size"),
                protected=constraints.get("protected", False),
                speed_ratio=constraints.get("speed_ratio", 1.0),
            )

            # 如果有视觉告警且非紧急，直接暂停
            if await self._has_vision_alert() and priority > 2:
                slot.status = ActionStatus.PAUSED
                logger.info(f"[ActionCoordinator] {action_id} 因视觉告警被暂停")
            else:
                slot.status = ActionStatus.RUNNING

            self._actions[action_id] = slot

            # 反向通知 SystemState
            if _SYSTEM_STATE_AVAILABLE and system_state is not None:
                with contextlib.suppress(Exception):
                    await system_state.set(f"coordination.slot.{action_id}", {
                        "type": action_type.value,
                        "status": slot.status.value,
                        "priority": priority,
                        "protected": slot.protected,
                        "speed_ratio": slot.speed_ratio,
                    })

            return slot

    async def update(self, action_id: str, status: ActionStatus | None = None,
                     payload_update: dict[str, Any] | None = None) -> ActionSlot | None:
        """更新动作状态"""
        async with self._lock:
            slot = self._actions.get(action_id)
            if slot is None:
                return None
            if status is not None:
                slot.status = status
            if payload_update:
                slot.payload.update(payload_update)
            return slot

    async def complete(self, action_id: str) -> None:
        """标记动作完成"""
        await self.update(action_id, ActionStatus.COMPLETED)
        if _SYSTEM_STATE_AVAILABLE and system_state is not None:
            with contextlib.suppress(Exception):
                await system_state.delete(f"coordination.slot.{action_id}")

    def register_sync(self, action_id: str, action_type: ActionType, priority: int = 5,
                      payload: dict[str, Any] | None = None) -> ActionSlot:
        """同步版本的 register，供非异步上下文（如 TTS Worker 线程）调用"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.register(action_id, action_type, priority, payload), loop
                )
                return future.result(timeout=1.0)
            return loop.run_until_complete(
                self.register(action_id, action_type, priority, payload)
            )
        except RuntimeError:
            return asyncio.run(
                self.register(action_id, action_type, priority, payload)
            )

    def complete_sync(self, action_id: str) -> None:
        """同步版本的 complete，供非异步上下文调用"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.complete(action_id), loop
                )
                future.result(timeout=1.0)
                return
            loop.run_until_complete(self.complete(action_id))
        except RuntimeError:
            asyncio.run(self.complete(action_id))

    async def cancel(self, action_id: str, reason: str = "") -> bool:
        """取消动作"""
        async with self._lock:
            slot = self._actions.get(action_id)
            if slot is None:
                return False
            slot.status = ActionStatus.CANCELLED
            logger.info(f"[ActionCoordinator] {action_id} 已取消，原因: {reason}")
            return True

    async def get_active(self, action_type: ActionType | None = None) -> list[ActionSlot]:
        """获取当前活跃动作"""
        async with self._lock:
            result = []
            for slot in self._actions.values():
                if slot.status != ActionStatus.RUNNING:
                    continue
                if action_type is None or slot.action_type == action_type:
                    result.append(slot)
            return result

    # ═══════════════════════════════════════════════════════════════════
    # 约束计算
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_constraints(self, action_type: ActionType, priority: int) -> dict[str, Any]:
        """根据当前系统状态，计算新动作的执行约束"""
        constraints: dict[str, Any] = {"speed_ratio": 1.0, "protected": False}

        if not _SYSTEM_STATE_AVAILABLE or system_state is None:
            return constraints

        # 检查是否有语音正在播报
        try:
            is_speaking = system_state.get_sync("speech.is_speaking", False)
            if is_speaking and action_type in (ActionType.MOUSE, ActionType.KEYBOARD):
                constraints["speed_ratio"] = self._rules["speech_mouse_speed"]
                constraints["fragment_size"] = self._rules["speech_mouse_fragment"]
        except Exception:
            pass

        # 检查是否有工具正在执行
        try:
            tool_status = system_state.get_sync("action.status", "idle")
            if tool_status == "running" and action_type == ActionType.SPEECH:
                constraints["protected"] = self._rules["tool_protects_speech"]
        except Exception:
            pass

        return constraints

    async def _has_vision_alert(self) -> bool:
        """检查是否有视觉告警"""
        if not _SYSTEM_STATE_AVAILABLE or system_state is None:
            return False
        try:
            alert = system_state.get_sync("vision.alert")
            return alert is not None
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════
    # SystemState 订阅回调
    # ═══════════════════════════════════════════════════════════════════

    async def _on_speech_state_change(self, path: str, value: Any) -> None:
        """语音状态变化时，调整动作约束"""
        if path == "speech.is_speaking":
            async with self._lock:
                for slot in self._actions.values():
                    if slot.status != ActionStatus.RUNNING:
                        continue
                    if value and slot.action_type in (ActionType.MOUSE, ActionType.KEYBOARD):
                        # 语音开始播报，降速
                        slot.speed_ratio = self._rules["speech_mouse_speed"]
                        slot.fragment_size = self._rules["speech_mouse_fragment"]
                        logger.info(f"[ActionCoordinator] {slot.action_id} 因语音播报降速")
                    elif not value and slot.action_type in (ActionType.MOUSE, ActionType.KEYBOARD):
                        # 语音结束，恢复
                        slot.speed_ratio = 1.0
                        slot.fragment_size = None
                        logger.info(f"[ActionCoordinator] {slot.action_id} 恢复全速")

    async def _on_vision_alert(self, path: str, value: Any) -> None:
        """视觉告警发生时，暂停非紧急动作"""
        if value is None:
            # 告警解除，恢复暂停的动作
            async with self._lock:
                for slot in self._actions.values():
                    if slot.status == ActionStatus.PAUSED and slot.priority > 2:
                        slot.status = ActionStatus.RUNNING
                        logger.info(f"[ActionCoordinator] {slot.action_id} 视觉告警解除，恢复执行")
            return

        # 新告警到来
        alert_level = value.get("level", "L1") if isinstance(value, dict) else "L1"
        async with self._lock:
            for slot in self._actions.values():
                if slot.status != ActionStatus.RUNNING:
                    continue
                # L2 及以上告警，暂停 priority > 2 的动作
                if alert_level in ("L2", "L3", "CRITICAL") and slot.priority > 2:
                    slot.status = ActionStatus.PAUSED
                    logger.warning(f"[ActionCoordinator] {slot.action_id} 因视觉告警({alert_level})暂停")

    async def _on_action_state_change(self, path: str, value: Any) -> None:
        """动作状态变化时的联动"""
        if path == "action.status" and value == "running":
            # 新工具开始执行，保护当前语音
            async with self._lock:
                for slot in self._actions.values():
                    if slot.action_type == ActionType.SPEECH and slot.status == ActionStatus.RUNNING:
                        slot.protected = True
                        logger.info(f"[ActionCoordinator] {slot.action_id} 因工具执行被保护")

    # ═══════════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════════

    async def pause_all(self, reason: str = "") -> list[str]:
        """暂停所有非保护动作，返回被暂停的 action_id 列表"""
        paused: list[str] = []
        async with self._lock:
            for slot in self._actions.values():
                if slot.status == ActionStatus.RUNNING and not slot.protected:
                    slot.status = ActionStatus.PAUSED
                    paused.append(slot.action_id)
        if paused:
            logger.info(f"[ActionCoordinator] 暂停 {len(paused)} 个动作，原因: {reason}")
        return paused

    async def resume_all(self, except_ids: list[str] | None = None) -> None:
        """恢复所有暂停的动作"""
        except_ids = except_ids or []
        async with self._lock:
            for slot in self._actions.values():
                if slot.status == ActionStatus.PAUSED and slot.action_id not in except_ids:
                    slot.status = ActionStatus.RUNNING
        logger.info("[ActionCoordinator] 恢复所有暂停动作")


# 全局单例
def get_action_coordinator() -> ActionCoordinator:
    return ActionCoordinator()
