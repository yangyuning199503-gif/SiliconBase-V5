#!/usr/bin/env python3
"""
ModeSwitchCoordinator - 统一的状态管理协调器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1 Week 2 - 任务1：实现统一的状态管理协调器

核心职责：
1. 在模式切换前保存所有相关状态（Snapshot机制）
2. 在模式切换后恢复或创建新状态
3. 协调5个状态管理器的统一操作
4. 提供降级方案，确保状态不丢失

关联组件：
- StateRegistry: 状态注册表
- WorkingMemory: 工作记忆
- DialogueManager: 对话管理器
- WorkModeManager: 工作模式管理器
- CheckpointManager: 断点管理器

WebSocket事件：
- mode_switching: 模式切换前发送，包含即将保存的快照信息
- mode_switched: 模式切换后发送，包含恢复的状态摘要
"""

import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from core.logger import logger


class ModeSwitchStatus(Enum):
    """模式切换状态"""
    IDLE = "idle"                    # 空闲状态
    PREPARING = "preparing"          # 准备切换（保存状态中）
    SWITCHING = "switching"          # 切换中
    RESTORING = "restoring"          # 恢复状态中
    COMPLETED = "completed"          # 切换完成
    FAILED = "failed"                # 切换失败


class WorkMode(Enum):
    """工作模式定义"""
    CHAT = "chat"                    # 聊天模式
    TASK = "task"                    # 任务模式
    DAILY = "daily"                  # 日常模式
    FOCUS = "focus"                  # 专注模式


@dataclass
class ModeSwitchSnapshot:
    """
    模式切换快照

    保存模式切换时的完整状态，用于后续恢复或审计
    """
    snapshot_id: str
    timestamp: str
    from_mode: str
    to_mode: str

    # 各状态管理器的状态
    working_memory: dict[str, Any] | None = None
    dialogue_state: dict[str, Any] | None = None
    work_mode_state: dict[str, Any] | None = None
    checkpoint_state: dict[str, Any] | None = None
    registry_state: dict[str, Any] | None = None

    # 附加信息
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ModeSwitchSnapshot':
        """从字典创建"""
        return cls(**data)


@dataclass
class ModeSwitchResult:
    """
    模式切换结果

    记录模式切换的完整结果，包括成功/失败状态和恢复的信息
    """
    success: bool
    from_mode: str
    to_mode: str
    snapshot_id: str
    message: str
    restored_components: list[str] = field(default_factory=list)
    failed_components: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class ModeSwitchCoordinator:
    """
    模式切换协调器

    统一协调多个状态管理器，确保模式切换时状态不丢失。

    设计原则：
    1. 单一职责：只负责状态保存和恢复，不处理业务逻辑
    2. 容错设计：任何组件失败都要有降级方案
    3. 不可静默失败：所有错误必须记录并上报
    4. 可审计：所有切换操作都有完整记录

    使用示例：
        coordinator = ModeSwitchCoordinator()

        # 模式切换前
        snapshot = coordinator.before_mode_switch("chat", "task", context={"user_id": "user_001"})

        # 执行模式切换...

        # 模式切换后
        result = coordinator.after_mode_switch("task", snapshot)
    """

    _instance: Optional['ModeSwitchCoordinator'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化协调器"""
        if self._initialized:
            return
        self._initialized = True

        # 状态管理器缓存（延迟加载）
        self._state_registry = None
        self._working_memory = None
        self._dialogue_manager = None
        self._work_mode_manager = None
        self._checkpoint_manager = None

        # 快照存储
        self._snapshots: dict[str, ModeSwitchSnapshot] = {}
        self._snapshots_lock = threading.RLock()

        # 存储目录
        self._storage_dir = Path("data/mode_switch_snapshots")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # 当前状态
        self._current_status = ModeSwitchStatus.IDLE
        self._status_lock = threading.Lock()

        # 回调函数
        self._before_switch_callbacks: list[Callable] = []
        self._after_switch_callbacks: list[Callable] = []

        # WebSocket发送函数（外部注入）
        self._websocket_sender: Callable | None = None

        logger.info("[ModeSwitchCoordinator] 模式切换协调器初始化完成")

    # ═══════════════════════════════════════════════════════════════
    # 延迟加载状态管理器
    # ═══════════════════════════════════════════════════════════════

    def _get_state_registry(self):
        """获取StateRegistry（延迟加载）"""
        if self._state_registry is None:
            try:
                from core.session.state_registry import get_state_registry
                self._state_registry = get_state_registry()
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 加载StateRegistry失败: {e}")
        return self._state_registry

    def _get_working_memory(self):
        """获取WorkingMemory（延迟加载）"""
        if self._working_memory is None:
            try:
                # WorkingMemory不是单例，需要外部提供或创建新的
                self._working_memory = None  # 标记为未获取
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 加载WorkingMemory失败: {e}")
        return self._working_memory

    def _get_dialogue_manager(self):
        """获取DialogueManager（延迟加载）"""
        if self._dialogue_manager is None:
            try:
                from core.dialog.dialogue_manager import DialogueManager
                self._dialogue_manager = DialogueManager()
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 加载DialogueManager失败: {e}")
        return self._dialogue_manager

    def _get_work_mode_manager(self):
        """获取WorkModeManager（延迟加载）"""
        if self._work_mode_manager is None:
            try:
                from core.work_mode_manager import get_work_mode_manager
                self._work_mode_manager = get_work_mode_manager()
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 加载WorkModeManager失败: {e}")
        return self._work_mode_manager

    def _get_checkpoint_manager(self):
        """获取CheckpointManager（延迟加载）"""
        if self._checkpoint_manager is None:
            try:
                from core.agent.checkpoint_manager import get_checkpoint_manager
                self._checkpoint_manager = get_checkpoint_manager()
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 加载CheckpointManager失败: {e}")
        return self._checkpoint_manager

    # ═══════════════════════════════════════════════════════════════
    # WebSocket集成
    # ═══════════════════════════════════════════════════════════════

    def set_websocket_sender(self, sender: Callable):
        """
        设置WebSocket发送函数

        Args:
            sender: 发送函数，接收(event_type, data)参数
        """
        self._websocket_sender = sender
        logger.debug("[ModeSwitchCoordinator] WebSocket发送函数已设置")

    def _send_websocket_event(self, event_type: str, data: dict[str, Any]):
        """
        发送WebSocket事件

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if self._websocket_sender:
            try:
                self._websocket_sender(event_type, data)
                logger.debug(f"[ModeSwitchCoordinator] WebSocket事件已发送: {event_type}")
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 发送WebSocket事件失败: {e}")
        else:
            logger.debug(f"[ModeSwitchCoordinator] WebSocket发送器未设置，跳过发送: {event_type}")

    # ═══════════════════════════════════════════════════════════════
    # 核心API：模式切换前
    # ═══════════════════════════════════════════════════════════════

    def before_mode_switch(self, from_mode: str, to_mode: str,
                          context: dict[str, Any] | None = None,
                          working_memory_instance=None) -> ModeSwitchSnapshot:
        """
        模式切换前：保存所有状态

        这是模式切换的第一步，负责捕获所有状态管理器的当前状态，
        创建一个完整的快照用于后续恢复。

        Args:
            from_mode: 源模式
            to_mode: 目标模式
            context: 切换上下文信息（如user_id, session_id等）
            working_memory_instance: 当前的WorkingMemory实例（如果有）

        Returns:
            ModeSwitchSnapshot: 保存的快照对象

        Raises:
            SnapshotError: 如果保存失败且无法降级
        """
        context = context or {}
        snapshot_id = str(uuid.uuid4())

        with self._status_lock:
            self._current_status = ModeSwitchStatus.PREPARING

        logger.info(f"[ModeSwitchCoordinator] 开始模式切换准备: {from_mode} -> {to_mode}")

        # 发送 mode_switching 事件
        self._send_websocket_event("mode_switching", {
            "snapshot_id": snapshot_id,
            "from_mode": from_mode,
            "to_mode": to_mode,
            "timestamp": datetime.now().isoformat()
        })

        # 创建快照对象
        snapshot = ModeSwitchSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now().isoformat(),
            from_mode=from_mode,
            to_mode=to_mode,
            context=context.copy()
        )

        # 保存各状态管理器状态（带降级方案）
        failed_components = []

        # 1. 保存 WorkingMemory 状态
        try:
            snapshot.working_memory = self._capture_working_memory(working_memory_instance)
            logger.debug("[ModeSwitchCoordinator] WorkingMemory状态已保存")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 保存WorkingMemory失败: {e}")
            failed_components.append("working_memory")
            snapshot.working_memory = None

        # 2. 保存 DialogueManager 状态
        try:
            snapshot.dialogue_state = self._capture_dialogue_state(context)
            logger.debug("[ModeSwitchCoordinator] DialogueManager状态已保存")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 保存DialogueManager状态失败: {e}")
            failed_components.append("dialogue_manager")
            snapshot.dialogue_state = None

        # 3. 保存 WorkModeManager 状态
        try:
            snapshot.work_mode_state = self._capture_work_mode_state()
            logger.debug("[ModeSwitchCoordinator] WorkModeManager状态已保存")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 保存WorkModeManager状态失败: {e}")
            failed_components.append("work_mode_manager")
            snapshot.work_mode_state = None

        # 4. 保存 CheckpointManager 状态
        try:
            snapshot.checkpoint_state = self._capture_checkpoint_state(context)
            logger.debug("[ModeSwitchCoordinator] CheckpointManager状态已保存")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 保存CheckpointManager状态失败: {e}")
            failed_components.append("checkpoint_manager")
            snapshot.checkpoint_state = None

        # 5. 保存 StateRegistry 状态
        try:
            snapshot.registry_state = self._capture_registry_state()
            logger.debug("[ModeSwitchCoordinator] StateRegistry状态已保存")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 保存StateRegistry状态失败: {e}")
            failed_components.append("state_registry")
            snapshot.registry_state = None

        # 记录失败组件
        snapshot.metadata["failed_components"] = failed_components
        snapshot.metadata["capture_success"] = len(failed_components) == 0

        # 保存快照到内存和磁盘
        self._save_snapshot(snapshot)

        with self._status_lock:
            self._current_status = ModeSwitchStatus.SWITCHING

        logger.info(f"[ModeSwitchCoordinator] 模式切换准备完成: snapshot_id={snapshot_id}, "
                   f"失败组件: {failed_components if failed_components else '无'}")

        # 触发前置回调
        self._trigger_before_callbacks(snapshot)

        return snapshot

    # ═══════════════════════════════════════════════════════════════
    # 核心API：模式切换后
    # ═══════════════════════════════════════════════════════════════

    def after_mode_switch(self, to_mode: str, snapshot: ModeSwitchSnapshot,
                         working_memory_instance=None) -> ModeSwitchResult:
        """
        模式切换后：恢复或创建新状态

        这是模式切换的第二步，根据目标模式决定如何恢复状态：
        - task模式：完整恢复WorkingMemory状态
        - chat模式：只恢复基本上下文（goal, context）

        Args:
            to_mode: 目标模式
            snapshot: 之前保存的快照
            working_memory_instance: 当前的WorkingMemory实例（如果有）

        Returns:
            ModeSwitchResult: 切换结果
        """
        with self._status_lock:
            self._current_status = ModeSwitchStatus.RESTORING

        logger.info(f"[ModeSwitchCoordinator] 开始模式切换恢复: -> {to_mode}")

        result = ModeSwitchResult(
            success=True,
            from_mode=snapshot.from_mode,
            to_mode=to_mode,
            snapshot_id=snapshot.snapshot_id,
            message="模式切换完成"
        )

        # 根据目标模式执行不同的恢复策略
        try:
            if to_mode == "task":
                self._restore_for_task_mode(snapshot, working_memory_instance, result)
            elif to_mode == "chat":
                self._restore_for_chat_mode(snapshot, working_memory_instance, result)
            else:
                # 默认恢复策略
                self._restore_default(snapshot, working_memory_instance, result)
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 恢复状态失败: {e}")
            result.success = False
            result.message = f"恢复状态失败: {e}"
            result.failed_components.append("restore_process")

        # 发送 mode_switched 事件
        self._send_websocket_event("mode_switched", {
            "snapshot_id": snapshot.snapshot_id,
            "from_mode": snapshot.from_mode,
            "to_mode": to_mode,
            "success": result.success,
            "restored_components": result.restored_components,
            "timestamp": datetime.now().isoformat(),
            "context_summary": self._get_context_summary(snapshot)
        })

        with self._status_lock:
            self._current_status = ModeSwitchStatus.COMPLETED if result.success else ModeSwitchStatus.FAILED

        # 触发后置回调
        self._trigger_after_callbacks(snapshot, result)

        logger.info(f"[ModeSwitchCoordinator] 模式切换恢复完成: success={result.success}, "
                   f"已恢复组件: {result.restored_components}")

        return result

    # ═══════════════════════════════════════════════════════════════
    # 状态捕获方法（私有）
    # ═══════════════════════════════════════════════════════════════

    def _capture_working_memory(self, working_memory_instance=None) -> dict[str, Any] | None:
        """捕获WorkingMemory状态"""
        if working_memory_instance is not None:
            # 使用提供的实例
            return working_memory_instance.to_dict()

        # 尝试从外部获取
        try:
            from core.global_state import get_working_memory
            wm = get_working_memory()
            if wm:
                return wm.to_dict()
        except Exception as e:
            logger.debug(f"[ModeSwitchCoordinator] 从global_state获取WorkingMemory失败: {e}")

        return None

    def _capture_dialogue_state(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """捕获DialogueManager状态"""
        dm = self._get_dialogue_manager()
        if not dm:
            return None

        user_id = context.get("user_id", "default")
        session_id = context.get("session_id")

        state = {
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }

        # 如果有会话ID，获取会话详情
        if session_id:
            try:
                session = dm.get_session(user_id, session_id)
                if session:
                    state["session"] = session.to_dict()
            except Exception as e:
                logger.warning(f"[ModeSwitchCoordinator] 获取会话详情失败: {e}")

        return state

    def _capture_work_mode_state(self) -> dict[str, Any] | None:
        """捕获WorkModeManager状态"""
        wmm = self._get_work_mode_manager()
        if not wmm:
            return None

        try:
            return {
                "current_mode": wmm.get_current_mode().value,
                "mode_info": wmm.get_mode_info(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.warning(f"[ModeSwitchCoordinator] 捕获WorkModeManager状态失败: {e}")
            return None

    def _capture_checkpoint_state(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """捕获CheckpointManager状态"""
        cpm = self._get_checkpoint_manager()
        if not cpm:
            return None

        user_id = context.get("user_id", "default")

        try:
            # 获取用户的活跃任务
            active_tasks = cpm.get_user_tasks(user_id, status_filter=["pending", "running", "paused"])
            return {
                "user_id": user_id,
                "active_task_count": len(active_tasks),
                "active_tasks": [t.task_id for t in active_tasks],
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.warning(f"[ModeSwitchCoordinator] 捕获CheckpointManager状态失败: {e}")
            return None

    def _capture_registry_state(self) -> dict[str, Any] | None:
        """捕获StateRegistry状态"""
        sr = self._get_state_registry()
        if not sr:
            return None

        try:
            return {
                "registry_info": sr.get_registry_info(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.warning(f"[ModeSwitchCoordinator] 捕获StateRegistry状态失败: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # 状态恢复方法（私有）
    # ═══════════════════════════════════════════════════════════════

    def _restore_for_task_mode(self, snapshot: ModeSwitchSnapshot,
                               working_memory_instance, result: ModeSwitchResult):
        """
        为任务模式恢复状态

        完整恢复WorkingMemory状态
        """
        logger.debug("[ModeSwitchCoordinator] 为TASK模式恢复状态")

        # 恢复 WorkingMemory
        if snapshot.working_memory and working_memory_instance is not None:
            try:
                from core.memory.working_memory import WorkingMemory
                restored_wm = WorkingMemory.from_dict(snapshot.working_memory)
                # 复制恢复的属性到现有实例
                for key, value in restored_wm.to_dict().items():
                    if hasattr(working_memory_instance, key):
                        setattr(working_memory_instance, key, value)
                result.restored_components.append("working_memory")
                logger.debug("[ModeSwitchCoordinator] WorkingMemory已恢复")
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 恢复WorkingMemory失败: {e}")
                result.failed_components.append("working_memory")
                result.warnings.append(f"WorkingMemory恢复失败: {e}")

        # 恢复对话上下文
        if snapshot.dialogue_state:
            result.restored_components.append("dialogue_context")

        # 恢复检查点状态
        if snapshot.checkpoint_state:
            result.restored_components.append("checkpoint_state")

    def _restore_for_chat_mode(self, snapshot: ModeSwitchSnapshot,
                              working_memory_instance, result: ModeSwitchResult):
        """
        为聊天模式恢复状态

        只恢复基本上下文（goal, context）
        """
        logger.debug("[ModeSwitchCoordinator] 为CHAT模式恢复状态")

        if snapshot.working_memory and working_memory_instance is not None:
            try:
                # 只恢复基本字段
                basic_fields = ["goal", "context", "key_context", "user_intent_snapshot"]
                for field in basic_fields:
                    if field in snapshot.working_memory and hasattr(working_memory_instance, field):
                        setattr(working_memory_instance, field, snapshot.working_memory[field])
                result.restored_components.append("working_memory_basic")
                logger.debug("[ModeSwitchCoordinator] WorkingMemory基本字段已恢复")
            except Exception as e:
                logger.error(f"[ModeSwitchCoordinator] 恢复WorkingMemory基本字段失败: {e}")
                result.warnings.append(f"基本上下文恢复失败: {e}")

        # 恢复对话上下文
        if snapshot.dialogue_state:
            result.restored_components.append("dialogue_context")

    def _restore_default(self, snapshot: ModeSwitchSnapshot,
                        working_memory_instance, result: ModeSwitchResult):
        """默认恢复策略"""
        logger.debug("[ModeSwitchCoordinator] 使用默认恢复策略")
        # 尝试恢复尽可能多的状态
        self._restore_for_task_mode(snapshot, working_memory_instance, result)

    # ═══════════════════════════════════════════════════════════════
    # 快照存储和加载
    # ═══════════════════════════════════════════════════════════════

    def _save_snapshot(self, snapshot: ModeSwitchSnapshot):
        """
        保存快照到内存和磁盘

        双存储策略确保数据安全
        """
        # 内存存储
        with self._snapshots_lock:
            self._snapshots[snapshot.snapshot_id] = snapshot

        # 磁盘存储
        try:
            filename = self._storage_dir / f"snapshot_{snapshot.snapshot_id}.json"
            temp_filename = filename.with_suffix('.json.tmp')

            with open(temp_filename, 'w', encoding='utf-8') as f:
                json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)
                f.flush()
                import os
                os.fsync(f.fileno())

            # 原子重命名
            import os
            os.replace(temp_filename, filename)

            logger.debug(f"[ModeSwitchCoordinator] 快照已保存到磁盘: {filename}")

        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 快照磁盘保存失败: {e}")
            # 内存中仍有数据，继续执行

    def load_snapshot(self, snapshot_id: str) -> ModeSwitchSnapshot | None:
        """
        加载指定快照

        优先从内存加载，失败则从磁盘加载
        """
        # 尝试内存加载
        with self._snapshots_lock:
            if snapshot_id in self._snapshots:
                return self._snapshots[snapshot_id]

        # 尝试磁盘加载
        try:
            filename = self._storage_dir / f"snapshot_{snapshot_id}.json"
            if filename.exists():
                with open(filename, encoding='utf-8') as f:
                    data = json.load(f)
                snapshot = ModeSwitchSnapshot.from_dict(data)
                # 缓存到内存
                with self._snapshots_lock:
                    self._snapshots[snapshot_id] = snapshot
                return snapshot
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 加载快照失败 {snapshot_id}: {e}")

        return None

    def list_snapshots(self, limit: int = 50) -> list[ModeSwitchSnapshot]:
        """列出所有可用的快照"""
        snapshots = []

        # 从内存获取
        with self._snapshots_lock:
            snapshots.extend(self._snapshots.values())

        # 从磁盘获取更多
        try:
            for filename in self._storage_dir.glob("snapshot_*.json"):
                try:
                    with open(filename, encoding='utf-8') as f:
                        data = json.load(f)
                    snapshot = ModeSwitchSnapshot.from_dict(data)
                    # 去重
                    if snapshot.snapshot_id not in [s.snapshot_id for s in snapshots]:
                        snapshots.append(snapshot)
                        # 缓存到内存
                        with self._snapshots_lock:
                            self._snapshots[snapshot.snapshot_id] = snapshot
                except Exception as e:
                    logger.warning(f"[ModeSwitchCoordinator] 读取快照文件失败 {filename}: {e}")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 列出快照失败: {e}")

        # 按时间排序，返回最新的
        snapshots.sort(key=lambda x: x.timestamp, reverse=True)
        return snapshots[:limit]

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """删除指定快照"""
        success = True

        # 删除内存中的
        with self._snapshots_lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]

        # 删除磁盘上的
        try:
            filename = self._storage_dir / f"snapshot_{snapshot_id}.json"
            if filename.exists():
                filename.unlink()
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 删除快照文件失败: {e}")
            success = False

        return success

    def cleanup_old_snapshots(self, keep_days: int = 7) -> int:
        """
        清理旧快照

        Args:
            keep_days: 保留最近几天的快照

        Returns:
            删除的快照数量
        """
        cutoff = datetime.now().timestamp() - (keep_days * 24 * 3600)
        count = 0

        # 清理内存中的
        with self._snapshots_lock:
            to_delete = [
                sid for sid, snap in self._snapshots.items()
                if datetime.fromisoformat(snap.timestamp).timestamp() < cutoff
            ]
            for sid in to_delete:
                del self._snapshots[sid]
                count += 1

        # 清理磁盘上的
        try:
            for filename in self._storage_dir.glob("snapshot_*.json"):
                try:
                    if filename.stat().st_mtime < cutoff:
                        filename.unlink()
                        count += 1
                except Exception as e:
                    logger.warning(f"[ModeSwitchCoordinator] 删除旧快照失败 {filename}: {e}")
        except Exception as e:
            logger.error(f"[ModeSwitchCoordinator] 清理旧快照失败: {e}")

        logger.info(f"[ModeSwitchCoordinator] 清理了 {count} 个旧快照")
        return count

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _get_context_summary(self, snapshot: ModeSwitchSnapshot) -> dict[str, Any]:
        """获取上下文摘要（用于WebSocket事件）"""
        summary = {
            "has_working_memory": snapshot.working_memory is not None,
            "has_dialogue_state": snapshot.dialogue_state is not None,
            "goal": None,
            "completed_steps": 0
        }

        if snapshot.working_memory:
            summary["goal"] = snapshot.working_memory.get("goal")
            summary["completed_steps"] = len(snapshot.working_memory.get("completed", []))

        return summary

    def _trigger_before_callbacks(self, snapshot: ModeSwitchSnapshot):
        """触发模式切换前回调"""
        for callback in self._before_switch_callbacks:
            try:
                callback(snapshot)
            except Exception as e:
                logger.warning(f"[ModeSwitchCoordinator] 前置回调执行失败: {e}")

    def _trigger_after_callbacks(self, snapshot: ModeSwitchSnapshot, result: ModeSwitchResult):
        """触发模式切换后回调"""
        for callback in self._after_switch_callbacks:
            try:
                callback(snapshot, result)
            except Exception as e:
                logger.warning(f"[ModeSwitchCoordinator] 后置回调执行失败: {e}")

    def register_before_callback(self, callback: Callable[[ModeSwitchSnapshot], None]):
        """注册模式切换前回调"""
        self._before_switch_callbacks.append(callback)

    def register_after_callback(self, callback: Callable[[ModeSwitchSnapshot, ModeSwitchResult], None]):
        """注册模式切换后回调"""
        self._after_switch_callbacks.append(callback)

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> dict[str, Any]:
        """获取当前状态"""
        with self._status_lock:
            status = self._current_status

        with self._snapshots_lock:
            snapshot_count = len(self._snapshots)

        return {
            "status": status.value,
            "snapshot_count": snapshot_count,
            "storage_dir": str(self._storage_dir),
            "has_websocket_sender": self._websocket_sender is not None
        }

    def get_latest_snapshot(self) -> ModeSwitchSnapshot | None:
        """获取最新的快照"""
        snapshots = self.list_snapshots(limit=1)
        return snapshots[0] if snapshots else None


# ═══════════════════════════════════════════════════════════════
# 全局实例和便捷函数
# ═══════════════════════════════════════════════════════════════

_coordinator_instance: ModeSwitchCoordinator | None = None


def get_mode_switch_coordinator() -> ModeSwitchCoordinator:
    """获取ModeSwitchCoordinator单例"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = ModeSwitchCoordinator()
    return _coordinator_instance


def before_mode_switch(from_mode: str, to_mode: str,
                      context: dict[str, Any] | None = None,
                      working_memory_instance=None) -> ModeSwitchSnapshot:
    """
    便捷函数：模式切换前保存状态

    Args:
        from_mode: 源模式
        to_mode: 目标模式
        context: 切换上下文
        working_memory_instance: WorkingMemory实例

    Returns:
        ModeSwitchSnapshot: 保存的快照
    """
    coordinator = get_mode_switch_coordinator()
    return coordinator.before_mode_switch(from_mode, to_mode, context, working_memory_instance)


def after_mode_switch(to_mode: str, snapshot: ModeSwitchSnapshot,
                     working_memory_instance=None) -> ModeSwitchResult:
    """
    便捷函数：模式切换后恢复状态

    Args:
        to_mode: 目标模式
        snapshot: 之前保存的快照
        working_memory_instance: WorkingMemory实例

    Returns:
        ModeSwitchResult: 切换结果
    """
    coordinator = get_mode_switch_coordinator()
    return coordinator.after_mode_switch(to_mode, snapshot, working_memory_instance)


def perform_mode_switch(from_mode: str, to_mode: str,
                       context: dict[str, Any] | None = None,
                       working_memory_instance=None) -> ModeSwitchResult:
    """
    便捷函数：执行完整的模式切换

    包括保存状态和恢复状态的完整流程

    Args:
        from_mode: 源模式
        to_mode: 目标模式
        context: 切换上下文
        working_memory_instance: WorkingMemory实例

    Returns:
        ModeSwitchResult: 切换结果
    """
    coordinator = get_mode_switch_coordinator()

    # 保存状态
    snapshot = coordinator.before_mode_switch(from_mode, to_mode, context, working_memory_instance)

    # 执行切换（这里可以插入业务逻辑）
    # ...

    # 恢复状态
    result = coordinator.after_mode_switch(to_mode, snapshot, working_memory_instance)

    return result


# ═══════════════════════════════════════════════════════════════
# WebSocket集成辅助函数
# ═══════════════════════════════════════════════════════════════

def setup_websocket_integration(websocket_sender: Callable):
    """
    设置WebSocket集成

    Args:
        websocket_sender: WebSocket发送函数
    """
    coordinator = get_mode_switch_coordinator()
    coordinator.set_websocket_sender(websocket_sender)
    logger.info("[ModeSwitchCoordinator] WebSocket集成已设置")


# ═══════════════════════════════════════════════════════════════
# 别名导出（向后兼容）
# ═══════════════════════════════════════════════════════════════

# 为测试兼容性提供别名
AgentMode = WorkMode
ModeSwitchState = ModeSwitchStatus

# ═══════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"模式切换协调器"，负责在模式切换时
# 统一保存和恢复所有相关状态，确保状态不丢失。
#
# 【主要组件】
# 1. ModeSwitchSnapshot: 模式切换快照数据类
# 2. ModeSwitchResult: 模式切换结果数据类
# 3. ModeSwitchCoordinator: 核心协调器类
#
# 【状态管理器协调】
# - StateRegistry: 状态注册表状态捕获
# - WorkingMemory: 工作记忆保存/恢复
# - DialogueManager: 对话状态捕获
# - WorkModeManager: 工作模式状态捕获
# - CheckpointManager: 断点状态捕获
#
# 【恢复策略】
# - TASK模式: 完整恢复WorkingMemory
# - CHAT模式: 只恢复基本上下文
#
# 【WebSocket事件】
# - mode_switching: 切换前发送
# - mode_switched: 切换后发送
#
# 【异常处理】
# - 所有保存/恢复操作都有降级方案
# - 错误必须记录，不能静默失败
# - 双存储策略：内存 + 磁盘
# ═══════════════════════════════════════════════════════════════
