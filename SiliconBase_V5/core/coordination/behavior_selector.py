#!/usr/bin/env python3
"""
BehaviorSelector - 行为选择器（基底节）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：多个任务/意图同时存在时，决定先执行哪个、后执行哪个、哪个要暂停。
需要 LLM 辅助做语义判断，但选择逻辑本身是本地规则。

核心规则：
1. 用户直接指令 > 视觉告警 > 自主任务
2. 弹窗出现时：系统错误弹窗必须处理，广告弹窗可忽略
3. 同一时刻只执行一个主要任务，其他排队
4. 紧急事件可中断非保护任务，但需保存上下文以便恢复
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


class TaskSource(Enum):
    USER = "user"            # 用户直接指令
    VISION_ALERT = "vision"  # 视觉告警
    CONSCIOUSNESS = "consciousness"  # 意识系统自主提议
    SYSTEM = "system"        # 系统级事件（如定时任务）


class TaskPriority(Enum):
    CRITICAL = 0     # 紧急：系统错误、安全风险
    HIGH = 1         # 高：用户直接指令
    NORMAL = 2       # 正常：常规任务
    LOW = 3          # 低：背景任务、自主探索
    BACKGROUND = 4   # 背景：数据整理、索引更新


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class BehaviorTask:
    task_id: str
    source: TaskSource
    priority: TaskPriority
    status: TaskStatus
    description: str           # 人类可读描述
    intent: str                # 结构化意图（如 "open_app:netease_music"）
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    resumed_at: float | None = None
    # 可中断性
    interruptible: bool = True
    # 被中断时的保存点
    checkpoint: dict[str, Any] | None = None


class BehaviorSelector:
    """
    行为选择器 - 单例

    所有任务在进入执行前，应先提交给选择器。选择器决定：
    - 立即执行
    - 排队等待
    - 暂停当前任务，切换新任务
    """
    _instance: Optional["BehaviorSelector"] = None

    def __new__(cls) -> "BehaviorSelector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: dict[str, BehaviorTask] = {}
        self._current_task_id: str | None = None
        self._lock = asyncio.Lock()
        self._subscriptions_setup = False

        # 来源优先级映射（数字越小越优先）
        self._source_priority = {
            TaskSource.SYSTEM: 0,
            TaskSource.VISION_ALERT: 1,
            TaskSource.USER: 2,
            TaskSource.CONSCIOUSNESS: 3,
        }

    def setup_subscriptions(self) -> None:
        """订阅 SystemState 变化"""
        if self._subscriptions_setup or not _SYSTEM_STATE_AVAILABLE or system_state is None:
            return
        self._subscriptions_setup = True
        try:
            system_state.subscribe("vision.alert", self._on_vision_alert)
            system_state.subscribe("consciousness.intent", self._on_consciousness_intent)
            logger.info("[BehaviorSelector] SystemState 订阅已建立")
        except Exception as e:
            logger.warning(f"[BehaviorSelector] 订阅失败: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # 任务提交与调度
    # ═══════════════════════════════════════════════════════════════════

    async def submit(self, task_id: str, source: TaskSource, description: str,
                     intent: str, priority: TaskPriority = TaskPriority.NORMAL,
                     context: dict[str, Any] | None = None,
                     interruptible: bool = True) -> BehaviorTask:
        """
        提交一个新任务。选择器根据当前任务队列，决定该任务的状态。

        返回的 BehaviorTask 中 status 字段表示决定：
            RUNNING = 立即执行
            PENDING = 排队等待
            PAUSED = 当前有其他任务在跑，先排队（如需插队会内部处理）
        """
        async with self._lock:
            task = BehaviorTask(
                task_id=task_id,
                source=source,
                priority=priority,
                status=TaskStatus.PENDING,
                description=description,
                intent=intent,
                context=context or {},
                interruptible=interruptible,
            )
            self._tasks[task_id] = task

            # 调度决策
            await self._schedule(task)

            # 写入 SystemState
            if _SYSTEM_STATE_AVAILABLE and system_state is not None:
                with contextlib.suppress(Exception):
                    await system_state.set(f"selector.task.{task_id}", {
                        "source": source.value,
                        "priority": priority.value,
                        "status": task.status.value,
                        "description": description,
                        "intent": intent,
                    })

            return task

    async def _schedule(self, new_task: BehaviorTask) -> str:
        """调度逻辑。返回决策描述。"""
        current = self._get_current_task()

        # 如果没有当前任务，直接执行
        if current is None:
            new_task.status = TaskStatus.RUNNING
            self._current_task_id = new_task.task_id
            logger.info(f"[BehaviorSelector] {new_task.task_id} 立即执行（无当前任务）")
            return "immediate"

        # 比较优先级
        new_score = self._score(new_task)
        current_score = self._score(current)

        # 新任务优先级更高，且当前任务可中断
        if new_score < current_score and current.interruptible:
            # 暂停当前任务
            current.status = TaskStatus.PAUSED
            current.checkpoint = {"paused_at": time.time(), "reason": f"被 {new_task.task_id} 抢占"}

            # 切换到新任务
            new_task.status = TaskStatus.RUNNING
            self._current_task_id = new_task.task_id

            logger.info(f"[BehaviorSelector] {current.task_id} 被暂停，{new_task.task_id} 抢占执行")

            # 通知 SystemState
            if _SYSTEM_STATE_AVAILABLE and system_state is not None:
                with contextlib.suppress(Exception):
                    await system_state.set("selector.current_task", {
                        "task_id": new_task.task_id,
                        "preempted": current.task_id,
                    })

            return "preempt"

        # 新任务排队
        new_task.status = TaskStatus.PENDING
        logger.info(f"[BehaviorSelector] {new_task.task_id} 排队等待（当前: {current.task_id}）")
        return "queue"

    def _score(self, task: BehaviorTask) -> int:
        """计算任务得分，数字越小越优先"""
        source_score = self._source_priority.get(task.source, 99)
        priority_score = task.priority.value
        # 时间加分：等待越久优先级微升（防饿死）
        age_bonus = int((time.time() - task.created_at) / 60)  # 每分钟+1
        return source_score * 100 + priority_score * 10 - min(age_bonus, 50)

    async def complete(self, task_id: str) -> BehaviorTask | None:
        """标记任务完成，自动调度下一个任务"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.COMPLETED

            if self._current_task_id == task_id:
                self._current_task_id = None
                # 寻找下一个可执行的任务
                next_task = await self._pick_next()
                if next_task:
                    next_task.status = TaskStatus.RUNNING
                    self._current_task_id = next_task.task_id
                    next_task.resumed_at = time.time()
                    logger.info(f"[BehaviorSelector] {task_id} 完成，切换到 {next_task.task_id}")

            return task

    async def _pick_next(self) -> BehaviorTask | None:
        """从 pending 任务中选出优先级最高的"""
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if not pending:
            return None
        pending.sort(key=lambda t: self._score(t))
        return pending[0]

    async def pause(self, task_id: str, reason: str = "") -> bool:
        """暂停指定任务"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return False
            task.status = TaskStatus.PAUSED
            task.checkpoint = {"paused_at": time.time(), "reason": reason}
            if self._current_task_id == task_id:
                self._current_task_id = None
            return True

    async def resume(self, task_id: str) -> bool:
        """恢复指定任务。如果当前有其他任务在跑，会先暂停那个任务。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.PAUSED:
                return False

            current = self._get_current_task()
            if current and current.interruptible:
                current.status = TaskStatus.PAUSED
                current.checkpoint = {"paused_at": time.time(), "reason": f"恢复 {task_id}"}

            task.status = TaskStatus.RUNNING
            self._current_task_id = task_id
            task.resumed_at = time.time()
            logger.info(f"[BehaviorSelector] {task_id} 恢复执行")
            return True

    async def cancel(self, task_id: str, reason: str = "") -> bool:
        """取消任务"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.CANCELLED
            if self._current_task_id == task_id:
                self._current_task_id = None
                # 调度下一个
                next_task = await self._pick_next()
                if next_task:
                    next_task.status = TaskStatus.RUNNING
                    self._current_task_id = next_task.task_id
            logger.info(f"[BehaviorSelector] {task_id} 已取消: {reason}")
            return True

    def _get_current_task(self) -> BehaviorTask | None:
        if self._current_task_id is None:
            return None
        return self._tasks.get(self._current_task_id)

    async def get_current(self) -> BehaviorTask | None:
        async with self._lock:
            return self._get_current_task()

    async def list_tasks(self, status_filter: TaskStatus | None = None) -> list[BehaviorTask]:
        async with self._lock:
            if status_filter is None:
                return list(self._tasks.values())
            return [t for t in self._tasks.values() if t.status == status_filter]

    # ═══════════════════════════════════════════════════════════════════
    # 语义判断（需要 LLM 辅助，但选择逻辑是本地规则）
    # ═══════════════════════════════════════════════════════════════════

    async def classify_alert(self, alert: dict[str, Any]) -> TaskPriority:
        """
        对视觉告警进行分类。返回优先级。

        简单规则（未来可接入 LLM 做语义判断）：
        - 错误弹窗/系统告警 → CRITICAL
        - 用户相关通知 → HIGH
        - 广告/推广 → LOW（可忽略）
        """
        alert.get("type", "").lower() if isinstance(alert, dict) else ""
        alert_text = alert.get("text", "").lower() if isinstance(alert, dict) else ""

        critical_keywords = ["错误", "失败", "error", "failed", "critical", "danger", "崩溃"]
        ad_keywords = ["广告", "推广", "ad", "promotion", "subscribe", "会员"]

        if any(k in alert_text for k in critical_keywords):
            return TaskPriority.CRITICAL
        if any(k in alert_text for k in ad_keywords):
            return TaskPriority.LOW

        return TaskPriority.HIGH

    # ═══════════════════════════════════════════════════════════════════
    # SystemState 订阅回调
    # ═══════════════════════════════════════════════════════════════════

    async def _on_vision_alert(self, path: str, value: Any) -> None:
        """视觉告警 → 提交高优先级任务"""
        if value is None:
            return

        alert_id = value.get("id", f"alert_{int(time.time())}") if isinstance(value, dict) else f"alert_{int(time.time())}"
        priority = await self.classify_alert(value)

        if priority == TaskPriority.LOW:
            logger.info(f"[BehaviorSelector] 视觉告警 {alert_id} 被判定为广告/低优先级，忽略")
            return

        await self.submit(
            task_id=alert_id,
            source=TaskSource.VISION_ALERT,
            description=f"视觉告警: {value.get('text', '未知')}" if isinstance(value, dict) else "视觉告警",
            intent="handle_alert",
            priority=priority,
            context={"alert": value},
            interruptible=True,
        )

    async def _on_consciousness_intent(self, path: str, value: Any) -> None:
        """意识系统产生的新意图 → 提交任务"""
        if value is None:
            return

        intent_str = value.get("intent", "explore") if isinstance(value, dict) else str(value)
        task_id = value.get("task_id", f"consciousness_{int(time.time())}") if isinstance(value, dict) else f"consciousness_{int(time.time())}"

        await self.submit(
            task_id=task_id,
            source=TaskSource.CONSCIOUSNESS,
            description=f"意识提议: {intent_str}",
            intent=intent_str,
            priority=TaskPriority.LOW,  # 意识任务默认低优，可被用户指令抢占
            context=value if isinstance(value, dict) else {},
            interruptible=True,
        )


# 全局单例
def get_behavior_selector() -> BehaviorSelector:
    return BehaviorSelector()
