"""
兼容层：旧入口 core.realtime_sync 已迁移至 core.sync.realtime_sync。
保留此模块防止遗留代码/测试导入失败。
"""
from core.sync.realtime_sync import (
    RealtimeSyncManager,
    SyncEvent,
    get_realtime_sync_manager,
)

__all__ = ["RealtimeSyncManager", "SyncEvent", "get_realtime_sync_manager"]
