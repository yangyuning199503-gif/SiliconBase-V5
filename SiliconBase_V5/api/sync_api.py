#!/usr/bin/env python3
"""
云端同步API - 用户数据同步接口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供用户数据在云端和客户端之间的同步功能

【端点列表】
  ✓ GET    /api/sync/{user_id}/pull           - 从云端拉取数据
  ✓ POST   /api/sync/{user_id}/push           - 推送数据到云端
  ✓ GET    /api/sync/{user_id}/status         - 获取同步状态
  ✓ POST   /api/sync/{user_id}/resolve        - 解决冲突
  ✓ GET    /api/sync/{user_id}/history        - 获取同步历史

【支持的数据类型】
  • memories      - 记忆数据
  • user_configs  - 用户配置
  • user_prompts  - 提示词配置
  • custom_tools  - 自定义工具
  • tasks         - 任务数据

作者: SiliconBase Team
版本: 1.0.0
"""

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 导入认证依赖 - 使用独立的auth_utils模块避免循环导入
# ═══════════════════════════════════════════════════════════════════

try:
    from api.auth_utils import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        logger.error(f"[SyncAPI] 认证模块导入失败: {e}")

        async def get_current_user() -> str | None:
            raise HTTPException(status_code=503, detail="认证服务不可用")

# 只在认证模块可用时添加认证依赖
router_dependencies = [Depends(get_current_user)] if AUTH_AVAILABLE else []
router = APIRouter(
    prefix="/sync",
    tags=["sync"],
    dependencies=router_dependencies
)


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════════════

class DataType(str, Enum):
    """支持的数据类型"""
    MEMORIES = "memories"
    USER_CONFIGS = "user_configs"
    USER_PROMPTS = "user_prompts"
    CUSTOM_TOOLS = "custom_tools"
    TASKS = "tasks"


class PushDataRequest(BaseModel):
    """推送数据请求模型"""
    user_id: str = Field(..., description="用户ID")
    data_type: DataType = Field(..., description="数据类型")
    data: dict[str, Any] = Field(..., description="要推送的数据")
    timestamp: datetime | None = Field(default=None, description="数据时间戳")
    device_id: str | None = Field(default=None, description="设备标识")
    checksum: str | None = Field(default=None, description="数据校验和")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "data_type": "user_configs",
                "data": {
                    "ai.default_model": "qwen3:8b",
                    "voice.wake_words": ["你好"]
                },
                "device_id": "device_001",
                "checksum": "abc123..."
            }
        }


class PushDataResponse(BaseModel):
    """推送数据响应模型"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="响应消息")
    server_timestamp: datetime = Field(default_factory=datetime.now, description="服务器时间戳")
    conflict_detected: bool = Field(default=False, description="是否检测到冲突")
    conflict_resolution: str | None = Field(default=None, description="冲突解决方式")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "数据已保存",
                "server_timestamp": "2024-01-01T00:00:00",
                "conflict_detected": False
            }
        }


class PullDataResponse(BaseModel):
    """拉取数据响应模型"""
    success: bool = Field(..., description="是否成功")
    data: dict[str, Any] | None = Field(default=None, description="拉取的数据")
    checksum: str | None = Field(default=None, description="数据校验和")
    timestamp: datetime | None = Field(default=None, description="数据时间戳")
    has_update: bool = Field(default=False, description="是否有更新")
    message: str = Field(default="", description="响应消息")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {"key": "value"},
                "checksum": "abc123...",
                "has_update": True,
                "message": "数据已返回"
            }
        }


class SyncStatusResponse(BaseModel):
    """同步状态响应模型"""
    success: bool = Field(..., description="是否成功")
    user_id: str = Field(..., description="用户ID")
    data_types: dict[str, dict[str, Any]] = Field(default_factory=dict, description="各数据类型状态")
    last_sync_at: datetime | None = Field(default=None, description="最后同步时间")
    total_devices: int = Field(default=1, description="关联设备数")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "user_id": "user_123",
                "data_types": {
                    "user_configs": {
                        "last_sync": "2024-01-01T00:00:00",
                        "version": 5
                    }
                },
                "total_devices": 2
            }
        }


class ConflictResolutionRequest(BaseModel):
    """冲突解决请求模型"""
    data_type: DataType = Field(..., description="数据类型")
    resolution: str = Field(..., description="解决策略: cloud_first/local_first/merge")
    local_data: dict[str, Any] | None = Field(default=None, description="本地数据（用于合并）")

    class Config:
        json_schema_extra = {
            "example": {
                "data_type": "user_configs",
                "resolution": "cloud_first",
                "local_data": {"key": "value"}
            }
        }


class SyncHistoryItem(BaseModel):
    """同步历史记录项"""
    sync_id: str = Field(..., description="同步记录ID")
    data_type: str = Field(..., description="数据类型")
    operation: str = Field(..., description="操作类型: push/pull")
    timestamp: datetime = Field(..., description="操作时间")
    device_id: str | None = Field(default=None, description="设备标识")
    success: bool = Field(..., description="是否成功")
    conflict_count: int = Field(default=0, description="冲突数量")


class SyncHistoryResponse(BaseModel):
    """同步历史响应模型"""
    success: bool = Field(..., description="是否成功")
    user_id: str = Field(..., description="用户ID")
    history: list[SyncHistoryItem] = Field(default_factory=list, description="历史记录列表")
    total: int = Field(..., description="总记录数")


# ═══════════════════════════════════════════════════════════════════
# 云端数据存储（模拟实现，实际应使用数据库）
# ═══════════════════════════════════════════════════════════════════

class CloudDataStore:
    """
    云端数据存储

    实际部署时应替换为真实的数据库实现（PostgreSQL/MongoDB等）
    """

    def __init__(self):
        # 内存存储（仅用于演示）
        self._data: dict[str, dict[str, Any]] = {}
        self._sync_history: dict[str, list[dict]] = {}
        self._device_registry: dict[str, list[str]] = {}

    def _get_key(self, user_id: str, data_type: str) -> str:
        """生成存储键"""
        return f"{user_id}:{data_type}"

    def get(self, user_id: str, data_type: str) -> dict[str, Any] | None:
        """获取用户数据"""
        key = self._get_key(user_id, data_type)
        return self._data.get(key)

    def set(self, user_id: str, data_type: str, data: dict[str, Any],
            device_id: str | None = None) -> bool:
        """保存用户数据"""
        key = self._get_key(user_id, data_type)

        # 更新数据
        self._data[key] = {
            "data": data,
            "updated_at": datetime.now().isoformat(),
            "version": self._data.get(key, {}).get("version", 0) + 1,
            "device_id": device_id
        }

        # 记录历史
        if user_id not in self._sync_history:
            self._sync_history[user_id] = []

        self._sync_history[user_id].append({
            "sync_id": f"sync_{datetime.now().timestamp()}",
            "data_type": data_type,
            "operation": "push",
            "timestamp": datetime.now().isoformat(),
            "device_id": device_id,
            "success": True
        })

        # 限制历史记录数量
        if len(self._sync_history[user_id]) > 100:
            self._sync_history[user_id] = self._sync_history[user_id][-100:]

        # 注册设备
        if device_id:
            if user_id not in self._device_registry:
                self._device_registry[user_id] = []
            if device_id not in self._device_registry[user_id]:
                self._device_registry[user_id].append(device_id)

        return True

    def get_status(self, user_id: str) -> dict[str, Any]:
        """获取同步状态"""
        data_types = {}

        for key, value in self._data.items():
            if key.startswith(f"{user_id}:"):
                data_type = key.split(":", 1)[1]
                data_types[data_type] = {
                    "last_sync": value.get("updated_at"),
                    "version": value.get("version", 0)
                }

        last_sync = None
        for dt_info in data_types.values():
            dt_sync = dt_info.get("last_sync")
            if dt_sync and (last_sync is None or dt_sync > last_sync):
                last_sync = dt_sync

        return {
            "data_types": data_types,
            "last_sync_at": last_sync,
            "total_devices": len(self._device_registry.get(user_id, []))
        }

    def get_history(self, user_id: str, limit: int = 50) -> list[dict]:
        """获取同步历史"""
        history = self._sync_history.get(user_id, [])
        return history[-limit:]


# 全局数据存储实例
cloud_store = CloudDataStore()


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def compute_checksum(data: Any) -> str:
    """计算数据校验和"""
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(json_str.encode()).hexdigest()


def check_conflict(cloud_data: dict, new_data: dict) -> bool:
    """检查数据冲突"""
    if not cloud_data:
        return False

    cloud_checksum = cloud_data.get("checksum")
    new_checksum = compute_checksum(new_data)

    return cloud_checksum != new_checksum


# ═══════════════════════════════════════════════════════════════════
# API 端点实现
# ═══════════════════════════════════════════════════════════════════

@router.post("/{user_id}/push", response_model=PushDataResponse)
async def push_data(
    user_id: str,
    request: PushDataRequest,
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user)
):
    """
    推送数据到云端

    客户端将本地数据推送到云端存储，支持冲突检测
    """
    try:
        # 权限检查：只能推送自己的数据
        if current_user != user_id and current_user != "admin":
            raise HTTPException(status_code=403, detail="无权访问其他用户数据")

        # 获取云端现有数据
        existing = cloud_store.get(user_id, request.data_type)

        # 冲突检测
        conflict_detected = False
        conflict_resolution = None

        if existing:
            # 简单冲突检测：比较版本号或时间戳
            existing.get("version", 0)
            cloud_time = existing.get("updated_at")

            if request.timestamp and cloud_time:
                # 如果云端数据更新，可能存在冲突
                cloud_dt = datetime.fromisoformat(cloud_time)
                if cloud_dt > request.timestamp:
                    conflict_detected = True
                    conflict_resolution = "detected"

        # 保存数据（实际应用中可能需要更复杂的合并逻辑）
        success = cloud_store.set(
            user_id=user_id,
            data_type=request.data_type,
            data=request.data,
            device_id=request.device_id
        )

        # 后台任务：通知其他设备
        if success:
            background_tasks.add_task(
                _notify_other_devices,
                user_id,
                request.data_type,
                request.device_id
            )

        return PushDataResponse(
            success=success,
            message="数据已保存到云端" if success else "保存失败",
            conflict_detected=conflict_detected,
            conflict_resolution=conflict_resolution
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 推送数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"推送数据失败: {str(e)}") from e


@router.get("/{user_id}/pull", response_model=PullDataResponse)
async def pull_data(
    user_id: str,
    data_type: DataType = Query(..., description="数据类型"),
    last_sync: datetime | None = Query(default=None, description="上次同步时间"),
    current_user: str = Depends(get_current_user)
):
    """
    从云端拉取数据

    客户端从云端获取最新数据，支持增量同步
    """
    try:
        # 权限检查
        if current_user != user_id and current_user != "admin":
            raise HTTPException(status_code=403, detail="无权访问其他用户数据")

        # 获取云端数据
        cloud_data = cloud_store.get(user_id, data_type)

        if not cloud_data:
            return PullDataResponse(
                success=True,
                data=None,
                has_update=False,
                message="云端暂无此类型数据"
            )

        # 检查是否有更新
        has_update = True
        if last_sync:
            cloud_time = datetime.fromisoformat(cloud_data.get("updated_at", "1970-01-01"))
            has_update = cloud_time > last_sync

        data_payload = cloud_data.get("data")

        return PullDataResponse(
            success=True,
            data=data_payload,
            checksum=compute_checksum(data_payload),
            timestamp=datetime.fromisoformat(cloud_data.get("updated_at")),
            has_update=has_update,
            message="数据已返回" if has_update else "无更新"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 拉取数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"拉取数据失败: {str(e)}") from e


@router.get("/{user_id}/status", response_model=SyncStatusResponse)
async def get_sync_status(
    user_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    获取同步状态

    返回用户所有数据类型的同步状态和最后同步时间
    """
    try:
        # 权限检查
        if current_user != user_id and current_user != "admin":
            raise HTTPException(status_code=403, detail="无权访问其他用户数据")

        status = cloud_store.get_status(user_id)

        return SyncStatusResponse(
            success=True,
            user_id=user_id,
            data_types=status.get("data_types", {}),
            last_sync_at=datetime.fromisoformat(status["last_sync_at"]) if status.get("last_sync_at") else None,
            total_devices=status.get("total_devices", 0)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 获取同步状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}") from e


@router.post("/{user_id}/resolve", response_model=PushDataResponse)
async def resolve_conflict(
    user_id: str,
    request: ConflictResolutionRequest,
    current_user: str = Depends(get_current_user)
):
    """
    解决同步冲突

    当检测到数据冲突时，客户端可以选择解决策略
    """
    try:
        # 权限检查
        if current_user != user_id and current_user != "admin":
            raise HTTPException(status_code=403, detail="无权访问其他用户数据")

        # 获取云端数据
        cloud_data = cloud_store.get(user_id, request.data_type)

        if not cloud_data:
            raise HTTPException(status_code=404, detail="云端数据不存在")

        resolved_data = None

        if request.resolution == "cloud_first":
            # 使用云端数据
            resolved_data = cloud_data.get("data")
        elif request.resolution == "local_first":
            # 使用本地数据
            resolved_data = request.local_data
        elif request.resolution == "merge":
            # 合并数据（简单实现）
            resolved_data = _merge_dicts(
                cloud_data.get("data", {}),
                request.local_data or {}
            )
        else:
            raise HTTPException(status_code=400, detail="无效的解决策略")

        # 保存解决后的数据
        success = cloud_store.set(user_id, request.data_type, resolved_data)

        return PushDataResponse(
            success=success,
            message=f"冲突已解决: {request.resolution}",
            conflict_detected=False,
            conflict_resolution=request.resolution
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 解决冲突失败: {e}")
        raise HTTPException(status_code=500, detail=f"解决冲突失败: {str(e)}") from e


@router.get("/{user_id}/history", response_model=SyncHistoryResponse)
async def get_sync_history(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=100, description="返回记录数限制"),
    current_user: str = Depends(get_current_user)
):
    """
    获取同步历史

    返回用户最近的同步操作记录
    """
    try:
        # 权限检查
        if current_user != user_id and current_user != "admin":
            raise HTTPException(status_code=403, detail="无权访问其他用户数据")

        history = cloud_store.get_history(user_id, limit)

        history_items = []
        for h in history:
            try:
                history_items.append(SyncHistoryItem(
                    sync_id=h.get("sync_id", ""),
                    data_type=h.get("data_type", ""),
                    operation=h.get("operation", ""),
                    timestamp=datetime.fromisoformat(h.get("timestamp", datetime.now().isoformat())),
                    device_id=h.get("device_id"),
                    success=h.get("success", True),
                    conflict_count=h.get("conflict_count", 0)
                ))
            except Exception as e:
                logger.warning(f"[SyncAPI] 解析历史记录失败: {e}")
                continue

        return SyncHistoryResponse(
            success=True,
            user_id=user_id,
            history=history_items,
            total=len(history_items)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 获取历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 管理端点（需要管理员权限）
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin/stats")
async def get_sync_statistics(
    current_user: str = Depends(get_current_user)
):
    """
    获取同步服务统计（管理员）

    返回系统级别的同步统计数据
    """
    try:
        # 检查管理员权限
        if current_user != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")

        # 统计信息
        stats = {
            "total_users": len(cloud_store._data),
            "total_records": sum(len(v) for v in cloud_store._sync_history.values()),
            "data_distribution": {}
        }

        # 计算数据类型分布
        for key in cloud_store._data:
            data_type = key.split(":", 1)[1] if ":" in key else "unknown"
            stats["data_distribution"][data_type] = stats["data_distribution"].get(data_type, 0) + 1

        return {
            "success": True,
            "stats": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SyncAPI] 获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _merge_dicts(cloud_dict: dict, local_dict: dict) -> dict:
    """合并两个字典（简单实现）"""
    merged = cloud_dict.copy()

    for key, value in local_dict.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            # 使用较新的值（这里简化处理，实际应该比较时间戳）
            merged[key] = value

    return merged


async def _notify_other_devices(user_id: str, data_type: str, source_device: str | None):
    """
    通知其他设备数据已更新

    实际实现中可以通过WebSocket推送通知
    """
    try:
        devices = cloud_store._device_registry.get(user_id, [])
        for device in devices:
            if device != source_device:
                # 这里可以实现WebSocket推送或发送推送通知
                logger.debug(f"[SyncAPI] 通知设备 {device} 数据已更新: {data_type}")
    except Exception as e:
        logger.warning(f"[SyncAPI] 通知设备失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 健康检查端点
# ═══════════════════════════════════════════════════════════════════

@router.get("/health")
async def sync_health_check():
    """同步服务健康检查"""
    return {
        "status": "ok",
        "service": "sync",
        "timestamp": datetime.now().isoformat()
    }
