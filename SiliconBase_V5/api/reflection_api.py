#!/usr/bin/env python3
"""
反思系统 API

为前端 ReflectionPanel 提供：
- 反思系统状态/配置管理
- 反思记录 CRUD、归档、反馈
- 反思统计与手动触发

当前使用内存存储，重启后重置；后续可迁移到数据库。
"""

import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from core.logger import logger

# 认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

if not AUTH_AVAILABLE:
    async def _fallback_user():
        return "default"
    get_current_user = _fallback_user

router = APIRouter(prefix="", tags=["reflection"])

# ============================================================================
# 数据模型
# ============================================================================

REFLECTION_TYPES = ["success", "failure", "optimization", "insight"]


class ReflectionConfig(BaseModel):
    enabled: bool = True
    auto_reflect: bool = True
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    max_reflections_per_day: int = Field(default=100, ge=1)
    reflection_types: list[str] = Field(default_factory=lambda: REFLECTION_TYPES.copy())


class ReflectionStatusResponse(BaseModel):
    enabled: bool
    config: dict


class ReflectionRecord(BaseModel):
    id: str
    type: str
    task_id: str | None = None
    session_id: str | None = None
    lesson: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    context: dict | None = None
    user_rating: float | None = Field(default=None, ge=1.0, le=5.0)
    user_feedback: str | None = None
    applied_count: int = 0
    created_at: str
    updated_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_archived: bool = False


class ReflectionFeedbackRequest(BaseModel):
    rating: float = Field(..., ge=1.0, le=5.0)
    feedback: str | None = None


class ReflectionTriggerRequest(BaseModel):
    task_id: str | None = None


class ReflectionsListResponse(BaseModel):
    success: bool
    data: dict


class ReflectionStats(BaseModel):
    total: int
    by_type: dict
    avg_confidence: float
    avg_user_rating: float
    recent_count: int


# ============================================================================
# 内存存储
# ============================================================================

_CONFIG = ReflectionConfig()

_REFLECTIONS: dict[str, ReflectionRecord] = {}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _seed_reflections():
    """预置示例反思数据"""
    if _REFLECTIONS:
        return
    samples = [
        {
            "type": "success",
            "lesson": "在调用 launch_app 前先确认应用名称的精确匹配，可减少一次失败重试。",
            "confidence": 0.85,
            "tags": ["tool_call", "launch_app"],
        },
        {
            "type": "failure",
            "lesson": "当视觉模型返回空响应时，应优先检查截图分辨率是否超过模型上下文。",
            "confidence": 0.78,
            "tags": ["vision", "qwen3-vl"],
        },
        {
            "type": "optimization",
            "lesson": "对单步工具任务，在工具成功后立即注入完成提示，避免重复调用。",
            "confidence": 0.92,
            "tags": ["agent_loop", "single_step"],
        },
        {
            "type": "insight",
            "lesson": "用户在晚间更倾向使用语音交互，可在该时段降低文本确认频率。",
            "confidence": 0.65,
            "tags": ["user_behavior", "voice"],
        },
    ]
    for i, s in enumerate(samples):
        rid = str(uuid.uuid4())
        _REFLECTIONS[rid] = ReflectionRecord(
            id=rid,
            type=s["type"],
            task_id=f"task_{i+1:03d}",
            lesson=s["lesson"],
            confidence=s["confidence"],
            created_at=(datetime.now() - timedelta(hours=i * 2)).isoformat(),
            tags=s["tags"],
        )


_seed_reflections()


# ============================================================================
# API 端点：系统状态与配置
# ============================================================================

@router.get("/reflection/status", response_model=dict)
async def get_reflection_status(current_user: str = Depends(get_current_user)):
    """获取反思系统状态"""
    return {
        "success": True,
        "data": ReflectionStatusResponse(
            enabled=_CONFIG.enabled,
            config=_CONFIG.dict()
        ).dict()
    }


@router.put("/reflection/status", response_model=dict)
async def update_reflection_status(
    request: dict,
    current_user: str = Depends(get_current_user)
):
    """更新反思系统状态"""
    _CONFIG.enabled = request.get("enabled", _CONFIG.enabled)
    return {"success": True, "message": "反思系统状态已更新"}


@router.get("/reflection/config", response_model=dict)
async def get_reflection_config(current_user: str = Depends(get_current_user)):
    """获取反思系统配置"""
    return {"success": True, "data": _CONFIG.dict()}


@router.put("/reflection/config", response_model=dict)
async def update_reflection_config(
    request: ReflectionConfig,
    current_user: str = Depends(get_current_user)
):
    """更新反思系统配置"""
    global _CONFIG
    _CONFIG = request
    return {"success": True, "data": _CONFIG.dict()}


# ============================================================================
# API 端点：反思记录
# ============================================================================

@router.get("/reflections", response_model=dict)
async def list_reflections(
    task_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: str = Depends(get_current_user)
):
    """获取反思记录列表"""
    items = list(_REFLECTIONS.values())
    if task_id:
        items = [r for r in items if r.task_id == task_id]
    if session_id:
        items = [r for r in items if r.session_id == session_id]
    if type:
        items = [r for r in items if r.type == type]
    if status == "active":
        items = [r for r in items if not r.is_archived]
    elif status == "archived":
        items = [r for r in items if r.is_archived]

    items.sort(key=lambda r: r.created_at, reverse=True)
    total = len(items)
    page = items[offset:offset + limit]

    return {
        "success": True,
        "data": {
            "reflections": [r.dict() for r in page],
            "total": total
        }
    }


@router.get("/reflections/{reflection_id}", response_model=dict)
async def get_reflection(
    reflection_id: str = FastApiPath(..., description="反思ID"),
    current_user: str = Depends(get_current_user)
):
    """获取单个反思详情"""
    r = _REFLECTIONS.get(reflection_id)
    if not r:
        raise HTTPException(status_code=404, detail="反思记录不存在")
    return {"success": True, "data": r.dict()}


@router.post("/reflections/{reflection_id}/feedback", response_model=dict)
async def submit_feedback(
    request: ReflectionFeedbackRequest,
    reflection_id: str = FastApiPath(..., description="反思ID"),
    current_user: str = Depends(get_current_user)
):
    """提交反思反馈"""
    r = _REFLECTIONS.get(reflection_id)
    if not r:
        raise HTTPException(status_code=404, detail="反思记录不存在")
    r.user_rating = request.rating
    r.user_feedback = request.feedback
    r.updated_at = _now_iso()
    return {
        "success": True,
        "message": "反馈已提交",
        "updated_reflection": r.dict()
    }


@router.post("/reflections/{reflection_id}/archive", response_model=dict)
async def archive_reflection(
    reflection_id: str = FastApiPath(..., description="反思ID"),
    current_user: str = Depends(get_current_user)
):
    """归档反思"""
    r = _REFLECTIONS.get(reflection_id)
    if not r:
        raise HTTPException(status_code=404, detail="反思记录不存在")
    r.is_archived = True
    r.updated_at = _now_iso()
    return {"success": True, "message": "反思已归档"}


class BatchArchiveRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1)


@router.post("/reflections/batch-archive", response_model=dict)
async def batch_archive_reflections(
    request: BatchArchiveRequest,
    current_user: str = Depends(get_current_user)
):
    """批量归档反思"""
    archived = 0
    for rid in request.ids:
        r = _REFLECTIONS.get(rid)
        if r:
            r.is_archived = True
            r.updated_at = _now_iso()
            archived += 1
    return {"success": True, "archived": archived}


@router.post("/reflections/{reflection_id}/unarchive", response_model=dict)
async def unarchive_reflection(
    reflection_id: str = FastApiPath(..., description="反思ID"),
    current_user: str = Depends(get_current_user)
):
    """取消归档反思"""
    r = _REFLECTIONS.get(reflection_id)
    if not r:
        raise HTTPException(status_code=404, detail="反思记录不存在")
    r.is_archived = False
    r.updated_at = _now_iso()
    return {"success": True, "message": "反思已取消归档"}


@router.get("/reflections/stats", response_model=dict)
async def get_reflection_stats(current_user: str = Depends(get_current_user)):
    """获取反思统计"""
    items = list(_REFLECTIONS.values())
    by_type = dict.fromkeys(REFLECTION_TYPES, 0)
    for r in items:
        by_type[r.type] = by_type.get(r.type, 0) + 1

    avg_confidence = sum(r.confidence for r in items) / len(items) if items else 0.0
    rated = [r for r in items if r.user_rating is not None]
    avg_user_rating = sum(r.user_rating for r in rated) / len(rated) if rated else 0.0
    recent = [r for r in items if datetime.fromisoformat(r.created_at) > datetime.now() - timedelta(days=7)]

    stats = ReflectionStats(
        total=len(items),
        by_type=by_type,
        avg_confidence=round(avg_confidence, 2),
        avg_user_rating=round(avg_user_rating, 2),
        recent_count=len(recent)
    )
    return {"success": True, "data": stats.dict()}


@router.post("/reflections/trigger", response_model=dict)
async def trigger_reflection(
    request: ReflectionTriggerRequest,
    current_user: str = Depends(get_current_user)
):
    """手动触发一次反思"""
    if not _CONFIG.enabled:
        raise HTTPException(status_code=400, detail="反思系统已禁用")

    rid = str(uuid.uuid4())
    reflection = ReflectionRecord(
        id=rid,
        type=random.choice(REFLECTION_TYPES),
        task_id=request.task_id,
        lesson="手动触发反思：已记录当前任务上下文，后续将基于执行结果生成学习要点。",
        confidence=round(random.uniform(0.6, 0.95), 2),
        created_at=_now_iso(),
        tags=["manual"],
    )
    _REFLECTIONS[rid] = reflection
    logger.info(f"[ReflectionAPI] 用户 {current_user} 手动触发反思 {rid}")
    return {"success": True, "reflection_id": rid}


@router.delete("/reflections/{reflection_id}", response_model=dict)
async def delete_reflection(
    reflection_id: str = FastApiPath(..., description="反思ID"),
    current_user: str = Depends(get_current_user)
):
    """删除反思记录"""
    if reflection_id not in _REFLECTIONS:
        raise HTTPException(status_code=404, detail="反思记录不存在")
    del _REFLECTIONS[reflection_id]
    return {"success": True, "message": "反思已删除"}
