"""memory module

⚠️ DEPRECATED (2026-05-09):
  本包下的 `memory` / `Memory` / `MemoryManager` 已迁移至 `core/memory/memory_service.py`。
  请使用：
    from core.memory.memory_service import get_memory_service
    ms = await get_memory_service()
    result = await ms.query_memories(user_id, ...)
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 新入口（推荐）
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .memory_service import (
        MemoryRetrievalError,
        MemoryService,
        MemoryStorageError,
        get_memory_service,
    )
    MEMORY_SERVICE_AVAILABLE = True
except Exception:
    MEMORY_SERVICE_AVAILABLE = False
    get_memory_service = None
    MemoryService = None
    MemoryRetrievalError = None
    MemoryStorageError = None

# ═══════════════════════════════════════════════════════════════════════════════
# 向后兼容：旧模块导出（待深层调用链迁移完成后彻底移除）
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .memory import (
        Memory,
        MemoryQuery,
        memory,
    )
    MEMORY_AVAILABLE = True
except Exception:
    MEMORY_AVAILABLE = False
    memory = None
    Memory = None
    MemoryQuery = None

# 重新导出阶段锚点
try:
    from .phase_anchor import (
        PhaseAnchor,
        PhaseAnchorManager,
        get_phase_anchor_manager,
        save_anchor,
    )
    PHASE_ANCHOR_AVAILABLE = True
except ImportError:
    PHASE_ANCHOR_AVAILABLE = False
    PhaseAnchorManager = None
    PhaseAnchor = None
    save_anchor = None
    get_phase_anchor_manager = None

__all__ = [
    # 新入口（推荐）
    "get_memory_service",
    "MemoryService",
    "MemoryRetrievalError",
    "MemoryStorageError",
    "MEMORY_SERVICE_AVAILABLE",
    # 向后兼容（废弃）
    "memory",
    "Memory",
    "MemoryQuery",
    "MEMORY_AVAILABLE",
    # 阶段锚点
    "PhaseAnchorManager",
    "PhaseAnchor",
    "save_anchor",
    "get_phase_anchor_manager",
    "PHASE_ANCHOR_AVAILABLE",
]
