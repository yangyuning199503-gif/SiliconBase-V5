#!/usr/bin/env python3
"""
CheckpointMemoryBridge - 检查点与记忆桥接系统 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【Phase 4.4 核心组件】

【核心功能】
  ✓ 保存检查点时自动关联记忆
  ✓ 恢复检查点时重建记忆上下文
  ✓ 维护检查点到记忆的索引
  ✓ 支持记忆锚点的创建与解析

【架构设计】
  ┌─────────────────────────────────────────┐
  │         CheckpointMemoryBridge          │
  │  ┌─────────────┐  ┌─────────────────┐   │
  │  │ Checkpoint  │  │   Memory        │   │
  │  │  Manager    │◄─┤   Context       │   │
  │  └─────────────┘  └─────────────────┘   │
  │           ▲              ▲              │
  │           └──────────────┘              │
  │              MemoryAnchorManager        │
  └─────────────────────────────────────────┘

【依赖组件】
  - CheckpointManager: core.agent.checkpoint_manager
  - MemoryManager: core.memory.memory_manager
  - PhaseAnchorManager: core.memory.phase_anchor

【使用示例】
  >>> from core.memory.checkpoint_memory_bridge import checkpoint_memory_bridge
  >>>
  >>> # 保存增强检查点
  >>> checkpoint_id = await bridge.save_workflow_checkpoint(
  ...     task_id="task_001",
  ...     execution_state={...},
  ...     checkpoint_type="auto"
  ... )
  >>>
  >>> # 恢复检查点并重建记忆上下文
  >>> state, memory_context = await bridge.restore_workflow_checkpoint(checkpoint_id)
"""

import asyncio
import json

# 日志记录器
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from core.diagnostic import safe_create_task

# 日志记录器

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 常量定义
# ═══════════════════════════════════════════════════════════════

# 检查点存储目录
BASE_DIR = Path(__file__).parent.parent.parent
CHECKPOINT_DIR = BASE_DIR / "data" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# 检查点-记忆索引目录
CHECKPOINT_MEMORY_INDEX_DIR = BASE_DIR / "data" / "checkpoint_memory_index"
CHECKPOINT_MEMORY_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# 默认配置
DEFAULT_RELATED_MEMORY_LIMIT = 5
DEFAULT_MIN_IMPORTANCE = 0.5
DEFAULT_MAX_ANCHORS_PER_CHECKPOINT = 10


# ═══════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class MemoryAnchor:
    """
    记忆锚点数据类

    用于在检查点和长期记忆之间建立关联。

    Attributes:
        anchor_id: 锚点唯一标识
        anchor_type: 锚点类型 (workflow/task/decision/perception)
        task_context: 任务上下文数据
        created_at: 创建时间
        related_memory_ids: 关联的记忆ID列表
        metadata: 额外元数据
    """
    anchor_id: str
    anchor_type: str
    task_context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    related_memory_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于JSON序列化）"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'MemoryAnchor':
        """从字典创建实例（反序列化）"""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class CheckpointMemoryIndex:
    """
    检查点-记忆索引数据类

    维护检查点到相关记忆的映射关系。

    Attributes:
        checkpoint_id: 检查点ID
        task_id: 任务ID
        memory_anchors: 记忆锚点ID列表
        related_memory_ids: 相关记忆ID列表
        created_at: 创建时间
        updated_at: 更新时间
    """
    checkpoint_id: str
    task_id: str
    memory_anchors: list[str] = field(default_factory=list)
    related_memory_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'CheckpointMemoryIndex':
        """从字典创建实例"""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class EnhancedCheckpointState:
    """
    增强型检查点状态数据类

    包含基础执行状态和记忆增强字段。

    Attributes:
        base_state: 基础执行状态
        memory_anchors: 记忆锚点列表
        related_memories: 相关记忆ID列表
        perception_history: 感知历史
        checkpoint_metadata: 检查点元数据
    """
    base_state: dict[str, Any] = field(default_factory=dict)
    memory_anchors: list[str] = field(default_factory=list)
    related_memories: list[str] = field(default_factory=list)
    perception_history: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'EnhancedCheckpointState':
        """从字典创建实例"""
        return cls(
            base_state=data.get("base_state", {}),
            memory_anchors=data.get("memory_anchors", []),
            related_memories=data.get("related_memories", []),
            perception_history=data.get("perception_history", []),
            checkpoint_metadata=data.get("checkpoint_metadata", {})
        )


# ═══════════════════════════════════════════════════════════════
# MemoryAnchorManager 类
# ═══════════════════════════════════════════════════════════════

class MemoryAnchorManager:
    """
    记忆锚点管理器

    职责：
    1. 为任务上下文创建锚点
    2. 解析锚点，重建上下文
    3. 管理锚点与记忆的关联

    【单例模式】
    全局唯一实例通过 get_memory_anchor_manager() 访问
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式创建"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器"""
        if self._initialized:
            return
        self._initialized = True

        # 锚点内存缓存
        self._anchors: dict[str, MemoryAnchor] = {}
        self._anchors_lock = asyncio.Lock()

        # 持久化目录
        self._persist_dir = BASE_DIR / "data" / "memory_anchors"
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        # 阶段锚点管理器引用（延迟加载）
        self._phase_anchor_manager = None

        logger.info("[MemoryAnchorManager] 记忆锚点管理器初始化完成")

    def _get_phase_anchor_manager(self):
        """获取阶段锚点管理器（延迟加载）"""
        if self._phase_anchor_manager is None:
            try:
                from core.memory.phase_anchor import get_phase_anchor_manager
                self._phase_anchor_manager = get_phase_anchor_manager()
            except ImportError as e:
                logger.warning(f"[MemoryAnchorManager] 阶段锚点管理器导入失败: {e}")
        return self._phase_anchor_manager

    async def create_anchor(
        self,
        task_context: dict[str, Any],
        anchor_type: str = "generic",
        user_id: str = "default",
        task_id: str = "",
        related_memories: list[str] = None
    ) -> str:
        """
        为任务上下文创建记忆锚点

        【核心功能】创建锚点时：
        1. 生成唯一锚点ID
        2. 关联相关记忆
        3. 保存到持久化存储

        Args:
            task_context: 任务上下文数据
            anchor_type: 锚点类型 (workflow/task/decision/perception)
            user_id: 用户ID
            task_id: 任务ID
            related_memories: 关联的记忆ID列表

        Returns:
            anchor_id: 创建的锚点ID
        """
        async with self._anchors_lock:
            # 生成锚点ID
            anchor_id = f"anchor_{uuid.uuid4().hex[:16]}"

            # 创建锚点对象
            anchor = MemoryAnchor(
                anchor_id=anchor_id,
                anchor_type=anchor_type,
                task_context=task_context,
                related_memory_ids=related_memories or [],
                metadata={
                    "user_id": user_id,
                    "task_id": task_id,
                    "created_by": "checkpoint_memory_bridge"
                }
            )

            # 保存到内存缓存
            self._anchors[anchor_id] = anchor

            # 保存到阶段锚点管理器（如果可用）
            phase_mgr = self._get_phase_anchor_manager()
            if phase_mgr:
                try:
                    await phase_mgr.save(
                        anchor_type,
                        {
                            "anchor_id": anchor_id,
                            "task_context": task_context,
                            "related_memories": related_memories or []
                        },
                        user_id=user_id,
                        task_id=task_id
                    )
                except Exception as e:
                    logger.warning(f"[MemoryAnchorManager] 保存到阶段锚点管理器失败: {e}")

            # 异步持久化
            self._persist_async(anchor)

            logger.debug(f"[MemoryAnchorManager] 创建锚点: {anchor_id}, 类型: {anchor_type}")
            return anchor_id

    async def resolve_anchors(
        self,
        anchor_ids: list[str],
        include_related_memories: bool = True
    ) -> dict[str, Any]:
        """
        解析锚点，重建上下文

        【核心功能】解析锚点时：
        1. 加载锚点数据
        2. 获取关联记忆
        3. 重建完整上下文

        Args:
            anchor_ids: 锚点ID列表
            include_related_memories: 是否包含关联记忆

        Returns:
            重建的上下文字典
        """
        context = {
            "anchors": [],
            "task_contexts": [],
            "related_memories": [],
            "resolved_at": datetime.now().isoformat()
        }

        async with self._anchors_lock:
            for anchor_id in anchor_ids:
                # 尝试从内存加载
                anchor = self._anchors.get(anchor_id)

                # 如果不在内存，尝试从磁盘加载
                if anchor is None:
                    anchor = await self._load_from_disk(anchor_id)
                    if anchor:
                        self._anchors[anchor_id] = anchor

                if anchor:
                    context["anchors"].append(anchor.to_dict())
                    context["task_contexts"].append(anchor.task_context)

                    if include_related_memories:
                        context["related_memories"].extend(anchor.related_memory_ids)

        # 去重关联记忆ID
        context["related_memories"] = list(set(context["related_memories"]))

        logger.debug(f"[MemoryAnchorManager] 解析锚点: {len(anchor_ids)} 个, "
                    f"关联记忆: {len(context['related_memories'])} 条")
        return context

    async def get_anchor(self, anchor_id: str) -> MemoryAnchor | None:
        """
        获取单个锚点

        Args:
            anchor_id: 锚点ID

        Returns:
            MemoryAnchor对象，不存在返回None
        """
        async with self._anchors_lock:
            # 先查内存
            anchor = self._anchors.get(anchor_id)
            if anchor:
                return anchor

            # 从磁盘加载
            anchor = await self._load_from_disk(anchor_id)
            if anchor:
                self._anchors[anchor_id] = anchor
            return anchor

    async def delete_anchor(self, anchor_id: str) -> bool:
        """
        删除锚点

        Args:
            anchor_id: 锚点ID

        Returns:
            是否删除成功
        """
        async with self._anchors_lock:
            if anchor_id not in self._anchors:
                return False

            del self._anchors[anchor_id]
            self._delete_from_disk(anchor_id)
            return True

    def _persist_async(self, anchor: MemoryAnchor):
        """异步持久化锚点到磁盘（Phase 7.2：asyncio.create_task + aiofiles）"""
        async def _async_save():
            try:
                file_path = self._persist_dir / f"{anchor.anchor_id}.json"
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(anchor.to_dict(), ensure_ascii=False, indent=2))
            except Exception as e:
                logger.error(f"[MemoryAnchorManager] 持久化失败: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_save())
        except RuntimeError:
            # 无运行中的事件循环，直接同步保存（不重开线程+事件循环）
            try:
                file_path = self._persist_dir / f"{anchor.anchor_id}.json"
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(anchor.to_dict(), f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"[MemoryAnchorManager] 同步持久化降级失败: {e}")

    async def _load_from_disk(self, anchor_id: str) -> MemoryAnchor | None:
        """从磁盘加载锚点（Phase 7.2 aiofiles）"""
        file_path = self._persist_dir / f"{anchor_id}.json"

        try:
            if not await asyncio.to_thread(file_path.exists):
                return None

            async with aiofiles.open(file_path, encoding='utf-8') as f:
                content = await f.read()

            data = json.loads(content)
            return MemoryAnchor.from_dict(data)
        except Exception as e:
            logger.error(f"[MemoryAnchorManager] 加载锚点失败 {anchor_id}: {e}")
            return None

    def _delete_from_disk(self, anchor_id: str):
        """从磁盘删除锚点"""
        try:
            file_path = self._persist_dir / f"{anchor_id}.json"
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"[MemoryAnchorManager] 删除磁盘文件失败: {e}")


# ═══════════════════════════════════════════════════════════════
# CheckpointMemoryBridge 类
# ═══════════════════════════════════════════════════════════════

class CheckpointMemoryBridge:
    """
    检查点与记忆桥接器

    【融合核心】实现：
    - 保存检查点时自动关联记忆
    - 恢复检查点时重建记忆上下文
    - 维护检查点到记忆的索引

    【使用方式】
    单例模式，通过 checkpoint_memory_bridge 全局实例访问
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式创建"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化桥接器"""
        if self._initialized:
            return
        self._initialized = True

        # 依赖组件（延迟加载）
        self._checkpoint_manager = None
        self._memory_manager = None
        self._anchor_manager = None

        # 索引缓存
        self._index_cache: dict[str, CheckpointMemoryIndex] = {}
        self._index_lock = asyncio.Lock()

        logger.info("[CheckpointMemoryBridge] 检查点记忆桥接器初始化完成")

    def _get_checkpoint_manager(self):
        """获取检查点管理器（延迟加载）"""
        if self._checkpoint_manager is None:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                self._checkpoint_manager = checkpoint_manager
            except ImportError as e:
                logger.error(f"[CheckpointMemoryBridge] 检查点管理器导入失败: {e}")
        return self._checkpoint_manager

    def _get_memory_manager(self):
        """获取记忆管理器（延迟加载）"""
        if self._memory_manager is None:
            try:
                from core.memory.memory_manager import memory_manager
                self._memory_manager = memory_manager
            except ImportError as e:
                logger.error(f"[CheckpointMemoryBridge] 记忆管理器导入失败: {e}")
        return self._memory_manager

    def _get_anchor_manager(self):
        """获取锚点管理器（延迟加载）"""
        if self._anchor_manager is None:
            self._anchor_manager = MemoryAnchorManager()
        return self._anchor_manager

    async def save_workflow_checkpoint(
        self,
        task_id: str,
        execution_state: dict[str, Any],
        checkpoint_type: str = "auto",
        user_id: str = "default",
        slot_id: int | None = None,
        create_anchor: bool = True
    ) -> str:
        """
        保存工作流检查点（增强版）

        【核心功能】保存检查点时：
        1. 创建记忆锚点
        2. 查询相关记忆
        3. 收集感知历史
        4. 保存增强状态
        5. 更新检查点-记忆索引

        【增强字段】
        - memory_anchors: 记忆锚点ID列表
        - related_memories: 相关长期记忆ID列表
        - perception_history: 感知历史摘要
        - checkpoint_metadata: 检查点元数据

        Args:
            task_id: 任务ID
            execution_state: 执行状态字典
            checkpoint_type: 检查点类型 (auto/manual/breakpoint)
            user_id: 用户ID
            slot_id: 槽位ID（可选）
            create_anchor: 是否创建记忆锚点

        Returns:
            checkpoint_id: 检查点ID
        """
        checkpoint_id = f"checkpoint_{task_id}_{uuid.uuid4().hex[:8]}"

        try:
            # 1. 创建记忆锚点（如果需要）
            anchor_ids = []
            if create_anchor:
                try:
                    anchor_id = await self._get_anchor_manager().create_anchor(
                        task_context={
                            "task_id": task_id,
                            "task_description": execution_state.get("description", ""),
                            "variables": execution_state.get("variables", {}),
                            "key_decisions": execution_state.get("decisions", [])
                        },
                        anchor_type=checkpoint_type,
                        user_id=user_id,
                        task_id=task_id
                    )
                    anchor_ids.append(anchor_id)
                except Exception as e:
                    logger.warning(f"[CheckpointMemoryBridge] 创建记忆锚点失败: {e}")

            # 2. 查询相关长期记忆
            related_memories = []
            task_description = execution_state.get("description", "")
            if task_description:
                try:
                    related_memories = await self._query_related_memories(
                        query=task_description,
                        user_id=user_id,
                        limit=DEFAULT_RELATED_MEMORY_LIMIT
                    )
                except Exception as e:
                    logger.warning(f"[CheckpointMemoryBridge] 查询相关记忆失败: {e}")

            # 3. 收集感知历史
            perception_history = self._extract_perception_history(execution_state)

            # 4. 构建增强状态
            enhanced_state = EnhancedCheckpointState(
                base_state=execution_state,
                memory_anchors=anchor_ids,
                related_memories=related_memories,
                perception_history=perception_history,
                checkpoint_metadata={
                    "checkpoint_id": checkpoint_id,
                    "type": checkpoint_type,
                    "task_id": task_id,
                    "user_id": user_id,
                    "slot_id": slot_id,
                    "created_at": datetime.now().isoformat(),
                    "version": "1.0"
                }
            )

            # 5. 保存检查点（使用CheckpointManager async接口）
            cm = self._get_checkpoint_manager()
            if cm:
                # 调用CheckpointManager保存基础检查点（Phase 7.2 async化）
                if hasattr(cm, 'save_checkpoint_async'):
                    await cm.save_checkpoint_async(
                        task_id=task_id,
                        checkpoint_name=checkpoint_type
                    )
                else:
                    await cm.save_checkpoint_async(
                        task_id=task_id,
                        checkpoint_name=checkpoint_type
                    )

                # 获取当前任务状态并增强（纯内存操作，无需 to_thread）
                task_state = cm.get_task(task_id)
                if task_state:
                    # 将增强状态附加到全局上下文
                    if not hasattr(task_state, 'global_context'):
                        task_state.global_context = {}
                    task_state.global_context["_enhanced_checkpoint"] = enhanced_state.to_dict()

                    # 重新持久化
                    if hasattr(cm, '_persist_task_state_async'):
                        await cm._persist_task_state_async(task_state)

            # 6. 保存到JSON文件（降级和备份）
            await self._save_enhanced_state_to_file(checkpoint_id, enhanced_state)

            # 7. 更新检查点-记忆索引（Phase 7.2 async化）
            await self._update_checkpoint_memory_index(
                checkpoint_id=checkpoint_id,
                task_id=task_id,
                anchor_ids=anchor_ids,
                memory_ids=related_memories
            )

            logger.info(f"[CheckpointMemoryBridge] 保存增强检查点: {checkpoint_id}, "
                       f"锚点: {len(anchor_ids)}, 相关记忆: {len(related_memories)}")
            return checkpoint_id

        except Exception as e:
            logger.error(f"[CheckpointMemoryBridge] 保存增强检查点失败: {e}", exc_info=True)
            # 降级：返回基础检查点ID
            return checkpoint_id

    async def restore_workflow_checkpoint(
        self,
        checkpoint_id: str,
        include_memory_context: bool = True
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """
        恢复工作流检查点（增强版）

        【核心功能】恢复检查点时：
        1. 加载检查点
        2. 解析记忆锚点
        3. 加载相关记忆
        4. 重建记忆上下文

        【返回值】
        - base_state: 基础执行状态
        - memory_context: 重建的记忆上下文
            - anchor_context: 锚点解析上下文
            - related_memories: 加载的相关记忆
            - perception_summary: 感知历史摘要

        Args:
            checkpoint_id: 检查点ID
            include_memory_context: 是否包含记忆上下文

        Returns:
            (base_state, memory_context) 元组，失败返回None
        """
        try:
            # 1. 加载增强状态（优先从文件）
            enhanced_state = await self._load_enhanced_state_from_file(checkpoint_id)

            # 如果文件不存在，尝试从CheckpointManager加载
            if enhanced_state is None:
                cm = self._get_checkpoint_manager()
                if cm:
                    # 尝试从task_id推断
                    task_id = self._extract_task_id_from_checkpoint_id(checkpoint_id)
                    if task_id:
                        task_state = cm.get_task(task_id)
                        if task_state and hasattr(task_state, 'global_context'):
                            enhanced_data = task_state.global_context.get("_enhanced_checkpoint")
                            if enhanced_data:
                                enhanced_state = EnhancedCheckpointState.from_dict(enhanced_data)

            if enhanced_state is None:
                logger.warning(f"[CheckpointMemoryBridge] 检查点不存在: {checkpoint_id}")
                return None

            base_state = enhanced_state.base_state
            memory_context = {
                "anchor_context": {},
                "related_memories": [],
                "perception_summary": []
            }

            if include_memory_context:
                # 2. 解析记忆锚点
                anchor_ids = enhanced_state.memory_anchors
                if anchor_ids:
                    try:
                        anchor_context = await self._get_anchor_manager().resolve_anchors(
                            anchor_ids=anchor_ids,
                            include_related_memories=True
                        )
                        memory_context["anchor_context"] = anchor_context
                    except Exception as e:
                        logger.warning(f"[CheckpointMemoryBridge] 解析锚点失败: {e}")

                # 3. 加载相关记忆
                memory_ids = enhanced_state.related_memories
                if memory_ids:
                    try:
                        loaded_memories = await self._load_memories_by_ids(memory_ids)
                        memory_context["related_memories"] = loaded_memories
                    except Exception as e:
                        logger.warning(f"[CheckpointMemoryBridge] 加载相关记忆失败: {e}")

                # 4. 生成感知摘要
                memory_context["perception_summary"] = self._summarize_perceptions(
                    enhanced_state.perception_history
                )

            logger.info(f"[CheckpointMemoryBridge] 恢复检查点: {checkpoint_id}, "
                       f"锚点: {len(enhanced_state.memory_anchors)}, "
                       f"相关记忆: {len(memory_context['related_memories'])}")

            return base_state, memory_context

        except Exception as e:
            logger.error(f"[CheckpointMemoryBridge] 恢复检查点失败: {e}", exc_info=True)
            return None

    async def _query_related_memories(
        self,
        query: str,
        user_id: str,
        limit: int = DEFAULT_RELATED_MEMORY_LIMIT
    ) -> list[str]:
        """
        查询相关记忆

        Args:
            query: 查询文本
            user_id: 用户ID
            limit: 返回数量限制

        Returns:
            相关记忆ID列表
        """
        memory_ids = []

        # 使用 MemoryService 查询（替代 AsyncMemory.retrieve_memories）
        try:
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()
            ctx = await memory_service.retrieve_context(user_id=user_id, query=query)
            # 从 l1(PG) + l2/l3/l4(VectorStore) 提取记忆ID，去重
            seen = set()
            for result in (ctx.l1 or []):
                mem_id = result.get("id")
                if mem_id and mem_id not in seen:
                    seen.add(mem_id)
                    memory_ids.append(mem_id)
            for results in (ctx.l2 or []), (ctx.l3 or []), (ctx.l4 or []):
                for sr in results:
                    mem_id = sr.id
                    if mem_id and mem_id not in seen:
                        seen.add(mem_id)
                        memory_ids.append(mem_id)
            if len(memory_ids) > limit:
                memory_ids = memory_ids[:limit]
        except Exception as e:
            logger.warning(f"[CheckpointMemoryBridge] MemoryService 查询失败（非阻塞）: {e}")
            # 降级：同步MemoryManager查询
            mm = self._get_memory_manager()
            if mm and query:
                try:
                    results = await mm.retrieve_memory(
                        query=query,
                        layer=None,
                        limit=limit,
                        use_vector=True
                    )
                    for result in results:
                        mem_id = result.get("id")
                        if mem_id:
                            memory_ids.append(mem_id)
                except Exception as e2:
                    logger.warning(f"[CheckpointMemoryBridge] MemoryManager降级查询也失败: {e2}")

        # 使用向量记忆查询
        if query and len(memory_ids) < limit:
            try:
                ms = await get_memory_service()
                results = await ms.vector_store.search(
                    collection="knowledge",
                    query=query,
                    limit=limit - len(memory_ids)
                )

                for result in results:
                    mem_id = result.id
                    if mem_id and mem_id not in memory_ids:
                        memory_ids.append(mem_id)
            except Exception as e:
                logger.warning(f"[CheckpointMemoryBridge] 向量记忆查询失败: {e}")

        return memory_ids[:limit]

    async def _load_memories_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """
        根据ID加载记忆（Phase 7.2 async化）

        Args:
            memory_ids: 记忆ID列表

        Returns:
            记忆数据列表
        """
        memories = []

        mm = self._get_memory_manager()
        if mm:
            for mem_id in memory_ids:
                try:
                    mem = await mm.get_by_id("global", mem_id)
                    if mem:
                        memories.append(mem)
                except Exception as e:
                    logger.debug(f"[CheckpointMemoryBridge] 加载记忆失败 {mem_id}: {e}")

        return memories

    def _extract_perception_history(self, execution_state: dict[str, Any]) -> list[dict[str, Any]]:
        """
        从执行状态中提取感知历史

        Args:
            execution_state: 执行状态

        Returns:
            感知历史列表
        """
        perception_history = []

        # 从step_results中提取
        step_results = execution_state.get("step_results", {})
        if isinstance(step_results, dict):
            for step_id, result in step_results.items():
                if isinstance(result, dict) and "perception" in result:
                    perception_history.append({
                        "step_id": step_id,
                        **result["perception"]
                    })

        # 从perception_history字段直接获取
        if "perception_history" in execution_state:
            direct_history = execution_state["perception_history"]
            if isinstance(direct_history, list):
                perception_history.extend(direct_history)

        return perception_history[:20]  # 限制数量

    def _summarize_perceptions(self, perception_history: list[dict[str, Any]]) -> str:
        """
        生成感知历史摘要

        Args:
            perception_history: 感知历史列表

        Returns:
            摘要文本
        """
        if not perception_history:
            return ""

        summaries = []
        for i, perception in enumerate(perception_history[-5:]):  # 最近5条
            step_id = perception.get("step_id", f"step_{i}")
            summary = perception.get("summary", str(perception)[:100])
            summaries.append(f"[{step_id}] {summary}")

        return "\n".join(summaries)

    async def _save_enhanced_state_to_file(
        self,
        checkpoint_id: str,
        enhanced_state: EnhancedCheckpointState
    ):
        """保存增强状态到JSON文件（Phase 7.2 aiofiles）"""
        try:
            file_path = CHECKPOINT_DIR / f"{checkpoint_id}_enhanced.json"
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(enhanced_state.to_dict(), ensure_ascii=False, indent=2))
        except Exception as e:
            logger.error(f"[CheckpointMemoryBridge] 保存增强状态失败: {e}")

    async def _load_enhanced_state_from_file(
        self,
        checkpoint_id: str
    ) -> EnhancedCheckpointState | None:
        """从JSON文件加载增强状态（Phase 7.2 aiofiles）"""
        try:
            file_path = CHECKPOINT_DIR / f"{checkpoint_id}_enhanced.json"
            if not await asyncio.to_thread(file_path.exists):
                return None

            async with aiofiles.open(file_path, encoding='utf-8') as f:
                content = await f.read()
            data = json.loads(content)

            return EnhancedCheckpointState.from_dict(data)
        except Exception as e:
            logger.error(f"[CheckpointMemoryBridge] 加载增强状态失败: {e}")
            return None

    async def _update_checkpoint_memory_index(
        self,
        checkpoint_id: str,
        task_id: str,
        anchor_ids: list[str],
        memory_ids: list[str]
    ):
        """更新检查点-记忆索引（Phase 7.2 async化）"""
        async with self._index_lock:
            index = CheckpointMemoryIndex(
                checkpoint_id=checkpoint_id,
                task_id=task_id,
                memory_anchors=anchor_ids,
                related_memory_ids=memory_ids
            )
            self._index_cache[checkpoint_id] = index

            # 异步保存到文件（Phase 7.2：asyncio.create_task + aiofiles）
            async def _async_save_index():
                try:
                    file_path = CHECKPOINT_MEMORY_INDEX_DIR / f"{checkpoint_id}.json"
                    async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(index.to_dict(), ensure_ascii=False, indent=2))
                except Exception as e:
                    logger.error(f"[CheckpointMemoryBridge] 保存索引失败: {e}")

            safe_create_task(_async_save_index(), name="_async_save_index")

    def _extract_task_id_from_checkpoint_id(self, checkpoint_id: str) -> str | None:
        """从检查点ID中提取任务ID"""
        # 格式: checkpoint_{task_id}_{hash}
        parts = checkpoint_id.split("_")
        if len(parts) >= 2:
            return parts[1]
        return None

    async def get_checkpoint_memory_index(self, checkpoint_id: str) -> CheckpointMemoryIndex | None:
        """
        获取检查点-记忆索引（Phase 7.2 async化）

        Args:
            checkpoint_id: 检查点ID

        Returns:
            CheckpointMemoryIndex对象
        """
        async with self._index_lock:
            # 先查缓存
            if checkpoint_id in self._index_cache:
                return self._index_cache[checkpoint_id]

            # 从磁盘加载（异步）
            try:
                file_path = CHECKPOINT_MEMORY_INDEX_DIR / f"{checkpoint_id}.json"
                if await asyncio.to_thread(file_path.exists):
                    async with aiofiles.open(file_path, encoding='utf-8') as f:
                        content = await f.read()
                    data = json.loads(content)
                    index = CheckpointMemoryIndex.from_dict(data)
                    self._index_cache[checkpoint_id] = index
                    return index
            except Exception as e:
                logger.error(f"[CheckpointMemoryBridge] 加载索引失败: {e}")

            return None

    async def list_checkpoints_by_task(self, task_id: str) -> list[str]:
        """
        获取任务的所有检查点（Phase 7.2 async化）

        Args:
            task_id: 任务ID

        Returns:
            检查点ID列表
        """
        checkpoint_ids = []

        try:
            # 扫描索引目录（Phase 7.2：to_thread 桥接同步 glob）
            files = await asyncio.to_thread(
                lambda: list(CHECKPOINT_MEMORY_INDEX_DIR.glob("*.json"))
            )
            for file_path in files:
                try:
                    async with aiofiles.open(file_path, encoding='utf-8') as f:
                        content = await f.read()
                    data = json.loads(content)
                    if data.get("task_id") == task_id:
                        checkpoint_ids.append(data.get("checkpoint_id"))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[CheckpointMemoryBridge] 列出检查点失败: {e}")

        return checkpoint_ids


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

checkpoint_memory_bridge = None

try:
    checkpoint_memory_bridge = CheckpointMemoryBridge()
    print("【成功】 CheckpointMemoryBridge (检查点记忆桥接器) 初始化成功")
except Exception as e:
    print(f"[ERROR] CheckpointMemoryBridge 初始化失败: {e}")
    checkpoint_memory_bridge = None


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_checkpoint_memory_bridge() -> CheckpointMemoryBridge | None:
    """获取检查点记忆桥接器实例"""
    return checkpoint_memory_bridge


def get_memory_anchor_manager() -> MemoryAnchorManager:
    """获取记忆锚点管理器实例"""
    return MemoryAnchorManager()


async def save_checkpoint_with_memory(
    task_id: str,
    execution_state: dict[str, Any],
    checkpoint_type: str = "auto",
    user_id: str = "default"
) -> str:
    """
    便捷函数：保存带记忆关联的检查点

    Args:
        task_id: 任务ID
        execution_state: 执行状态
        checkpoint_type: 检查点类型
        user_id: 用户ID

    Returns:
        检查点ID
    """
    if checkpoint_memory_bridge is None:
        raise RuntimeError("CheckpointMemoryBridge 未初始化")

    return await checkpoint_memory_bridge.save_workflow_checkpoint(
        task_id=task_id,
        execution_state=execution_state,
        checkpoint_type=checkpoint_type,
        user_id=user_id
    )


async def restore_checkpoint_with_memory(
    checkpoint_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """
    便捷函数：恢复带记忆上下文的检查点

    Args:
        checkpoint_id: 检查点ID

    Returns:
        (base_state, memory_context) 元组
    """
    if checkpoint_memory_bridge is None:
        raise RuntimeError("CheckpointMemoryBridge 未初始化")

    return await checkpoint_memory_bridge.restore_workflow_checkpoint(checkpoint_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件是 SiliconBase V5 系统 Phase 4.4 的核心实现，
# 提供检查点与记忆之间的桥接功能。
#
# 【核心组件】
# 1. MemoryAnchor: 记忆锚点数据类
# 2. MemoryAnchorManager: 记忆锚点管理器（单例）
# 3. CheckpointMemoryIndex: 检查点-记忆索引数据类
# 4. EnhancedCheckpointState: 增强型检查点状态数据类
# 5. CheckpointMemoryBridge: 检查点记忆桥接器（单例）
#
# 【主要流程】
#   save_workflow_checkpoint():
#     1. 创建记忆锚点
#     2. 查询相关记忆
#     3. 收集感知历史
#     4. 保存增强状态
#     5. 更新检查点-记忆索引
#
#   restore_workflow_checkpoint():
#     1. 加载检查点
#     2. 解析记忆锚点
#     3. 加载相关记忆
#     4. 重建记忆上下文
#
# 【使用入口】
#   from core.memory.checkpoint_memory_bridge import checkpoint_memory_bridge
#   checkpoint_id = await checkpoint_memory_bridge.save_workflow_checkpoint(...)
#
# ═══════════════════════════════════════════════════════════════════════════════
