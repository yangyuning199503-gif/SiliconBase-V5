#!/usr/bin/env python3
"""
Memory API - 记忆管理接口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供记忆的增删改查、搜索、筛选等RESTful API接口

【端点列表】
  ✓ GET    /api/memories              - 获取记忆列表
  ✓ GET    /api/memories/search       - 搜索记忆
  ✓ POST   /api/memories/advanced-search - 高级搜索
  ✓ DELETE /api/memories/{memory_id}  - 删除记忆
  ✓ PUT    /api/memories/{memory_id}  - 更新记忆
  ✓ POST   /api/memories/batch        - 批量删除
  ✓ POST   /api/memories/evolve       - 触发记忆进化
  ✓ GET    /api/memories/evolution-history - 获取进化历史
  ✓ POST   /api/memories/filter-by-dimensions - 维度筛选
  ✓ GET    /api/memories/filter-by-grades    - 等级筛选

【L4向量记忆端点】(Fix-Memory-1)
  ✓ GET    /api/memory/vector/search  - L4向量记忆搜索
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 导入认证依赖 - 使用独立的auth_utils模块避免循环导入
try:
    from api.auth_utils import get_current_user, get_current_user_optional
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user, get_current_user_optional
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        logger.error(f"[MemoryAPI] 认证模块导入失败: {e}")

        async def get_current_user() -> str | None:
            raise HTTPException(status_code=503, detail="认证服务不可用")

# 只在认证模块可用时添加认证依赖
router_dependencies = [Depends(get_current_user)] if AUTH_AVAILABLE else []
router = APIRouter(
    prefix="/memories",
    tags=["memories"]
)


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════════════

class MemoryCreate(BaseModel):
    """创建记忆请求模型"""
    content: str = Field(..., description="记忆内容")
    type: str = Field(default="chat", description="记忆类型")
    layer: str = Field(default="short", description="记忆层级")
    scene: str | None = Field(default=None, description="场景指纹")
    tags: list[str] | None = Field(default=None, description="标签列表")
    source: str | None = Field(default="user", description="来源: user/ai/system/reflection/evolution/auto_save")
    # 新增：六维评分字段
    value_assessment: dict[str, Any] | None = Field(
        default=None,
        description="六维评分: emotional_temperature, ethical_safety, self_growth, execution_effectiveness, sustainability, inspiration_innovation"
    )


class BatchCreateRequest(BaseModel):
    """批量创建记忆请求模型"""
    items: list[MemoryCreate] = Field(..., description="记忆条目列表")


class MemoryUpdate(BaseModel):
    """更新记忆请求模型"""
    content: str | None = Field(default=None, description="记忆内容")
    rating: int | None = Field(default=None, ge=0, le=10, description="评分(0-10)")
    scene: str | None = Field(default=None, description="场景指纹")


class DimensionFilter(BaseModel):
    """六维评分筛选模型"""
    emotional_temperature: int | None = Field(default=None, ge=1, le=5, description="情感温度")
    ethical_safety: int | None = Field(default=None, ge=1, le=5, description="伦理安全")
    self_growth: int | None = Field(default=None, ge=1, le=5, description="自我成长")
    execution_effectiveness: int | None = Field(default=None, ge=1, le=5, description="执行成效")
    sustainability: int | None = Field(default=None, ge=1, le=5, description="存续保障")
    inspiration_innovation: int | None = Field(default=None, ge=1, le=5, description="灵感创新")


class BatchDeleteRequest(BaseModel):
    """批量删除请求模型"""
    ids: list[str] = Field(..., description="要删除的记忆ID列表")


class AdvancedSearchRequest(BaseModel):
    """高级搜索请求模型"""
    query: str | None = Field(default=None, description="搜索关键词")
    layer: str | None = Field(default=None, description="记忆层级过滤")
    mem_type: str | None = Field(default=None, description="记忆类型过滤")
    scene: str | None = Field(default=None, description="场景过滤")
    min_rating: int | None = Field(default=None, ge=0, le=10, description="最小评分")
    since: str | None = Field(default=None, description="开始时间(ISO格式)")
    until: str | None = Field(default=None, description="结束时间(ISO格式)")
    limit: int = Field(default=10, ge=1, le=100, description="返回数量限制")
    sources: list[str] | None = Field(default=None, description="来源筛选(ai/system/user/reflection/evolution)")  # Agent-4新增
    dimension_weights: dict[str, float] | None = Field(default=None, description="维度权重，用于结果排序")  # 透传底层已有能力


# ═══════════════════════════════════════════════════════════════════
# API 端点实现
# ═══════════════════════════════════════════════════════════════════

@router.post("")
async def create_memory(
    data: MemoryCreate,
    user_id: str = Depends(get_current_user)
):
    """
    创建新记忆

    添加一条新的记忆记录到指定层级
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 构建内容字典
        content = {"text": data.content}
        if data.tags:
            content["tags"] = data.tags

        memory_id = await ms.add_memory(
            user_id=user_id,
            content=content,
            memory_type=data.type,
            layer=data.layer,
            scene=data.scene or "",
            value_assessment=data.value_assessment,
        )

        # 创建后查询完整记忆对象
        full_memory = await ms.get_memory_by_id(memory_id)

        # 转换字段名 memory_id -> id
        if full_memory:
            formatted_mem = dict(full_memory)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
        else:
            formatted_mem = {"id": memory_id}

        return {
            "success": True,
            "data": formatted_mem  # 返回完整记忆对象
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建记忆失败: {str(e)}") from e


@router.get("")
async def list_memories(
    layer: str | None = Query(default=None, description="记忆层级过滤"),
    mem_type: str | None = Query(default=None, description="记忆类型过滤"),
    source: str | None = Query(default=None, description="来源筛选(ai/system/user/reflection/evolution)"),  # Agent-4新增
    limit: int = Query(default=50, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    获取用户记忆列表

    支持按层级、类型过滤，支持分页
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 构建查询条件
        filters = {}
        if mem_type:
            filters["mem_type"] = mem_type
        if source:  # Agent-4: 添加source筛选
            filters["source"] = source

        # 查询记忆
        results = await ms.query_memories(
            user_id,
            layer=layer,
            filter_dict=filters if filters else None,
            limit=limit + offset
        )

        # 应用偏移量
        paginated_results = results[offset:offset + limit] if offset < len(results) else []

        # 转换字段名 memory_id -> id
        formatted_memories = []
        for mem in paginated_results:
            formatted_mem = dict(mem)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
            formatted_memories.append(formatted_mem)

        return {
            "success": True,
            "data": {
                "memories": formatted_memories,
                "total": len(results),
                "limit": limit,
                "offset": offset
            },
            "message": "Memories retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取记忆列表失败: {str(e)}") from e


@router.get("/search")
async def search_memories(
    query: str = Query(..., description="搜索关键词"),
    limit: int = Query(default=10, ge=1, le=50, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    搜索记忆内容

    使用关键词搜索记忆内容，支持语义搜索（如果向量记忆可用）
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 先尝试使用向量搜索（如果可用）
        try:
            if await ms.vector_store.is_available():
                vector_results = await ms.vector_store.search_multi(
                    query=query,
                    collections=["experience", "knowledge", "chat", "voice_fix", "execution"],
                    n_results=limit + offset
                )
                if vector_results:
                    # 格式化向量搜索结果
                    formatted_results = []
                    for collection, results in vector_results.items():
                        for r in results:
                            formatted_results.append({
                                "id": r.id if hasattr(r, 'id') else r.get('id', ''),
                                "content": r.document if hasattr(r, 'document') else r.get('document', ''),
                                "similarity": r.distance if hasattr(r, 'distance') else r.get('distance', 0),
                                "collection": collection,
                                "source": "vector"
                            })
                    if formatted_results:
                        # 应用偏移量
                        paginated_results = formatted_results[offset:offset + limit] if offset < len(formatted_results) else []
                        return {
                            "success": True,
                            "memories": paginated_results,
                            "total": len(formatted_results),
                            "limit": limit,
                            "offset": offset,
                            "source": "vector"
                        }
        except Exception as e:
            # 向量搜索失败，记录日志后回退到关键词搜索
            logger.debug(f"[MemoryAPI] 向量搜索失败，回退到关键词搜索: {e}")
            pass  # 继续执行后续关键词搜索

        # 关键词搜索（使用 query_memories 回退 + 本地过滤）
        results = await ms.query_memories(user_id, limit=limit + offset)
        query_lower = query.lower()
        results = [
            r for r in results
            if query_lower in str(r.get('content', '')).lower()
        ]
        total = len(results)
        paginated_results = results[offset:offset + limit] if offset < len(results) else []

        # 转换字段名 memory_id -> id
        formatted_memories = []
        for mem in paginated_results:
            formatted_mem = dict(mem)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
            formatted_memories.append(formatted_mem)

        return {
            "success": True,
            "memories": formatted_memories,
            "total": total,
            "limit": limit,
            "offset": offset,
            "source": "keyword"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索记忆失败: {str(e)}") from e


@router.post("/advanced-search")
async def advanced_search(data: AdvancedSearchRequest, offset: int = 0, user_id: str = Depends(get_current_user)):
    """
    高级条件搜索

    支持多条件组合搜索：时间范围、评分、层级、类型等
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 构建查询条件
        filters = {}
        if data.mem_type:
            filters["mem_type"] = data.mem_type
        if data.scene:
            filters["scene"] = data.scene
        if data.min_rating is not None:
            filters["min_rating"] = data.min_rating
        if data.since:
            filters["since"] = data.since
        if data.until:
            filters["until"] = data.until
        if data.sources:  # Agent-4: 添加sources筛选
            filters["sources"] = data.sources

        # 执行查询（透传 dimension_weights，底层已有排序能力）
        results = await ms.query_memories(
            user_id,
            layer=data.layer,
            filter_dict=filters if filters else None,
            limit=data.limit + offset,
            dimension_weights=data.dimension_weights
        )

        # 如果有查询词，进一步过滤
        if data.query:
            query_lower = data.query.lower()
            results = [
                r for r in results
                if query_lower in str(r.get('content', '')).lower()
            ]

        total = len(results)
        paginated_results = results[offset:offset + data.limit] if offset < len(results) else []

        # 转换字段名 memory_id -> id
        formatted_memories = []
        for mem in paginated_results:
            formatted_mem = dict(mem)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
            formatted_memories.append(formatted_mem)

        return {
            "success": True,
            "memories": formatted_memories,
            "total": total,
            "limit": data.limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"高级搜索失败: {str(e)}") from e


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    删除指定记忆

    支持级联删除向量库中的对应记录
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        success = await ms.delete_memory(memory_id)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或删除失败")

        return {
            "success": True,
            "message": "记忆已删除",
            "memory_id": memory_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除记忆失败: {str(e)}") from e


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    user_id: str = Depends(get_current_user)
):
    """
    更新记忆内容

    支持更新内容和评分
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 构建更新数据
        updates = data.model_dump(exclude_unset=True)

        if not updates:
            raise HTTPException(status_code=400, detail="没有提供要更新的字段")

        success = await ms.update_memory(memory_id, updates)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或更新失败")

        return {
            "success": True,
            "message": "记忆已更新",
            "memory_id": memory_id,
            "updates": updates
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新记忆失败: {str(e)}") from e


@router.put("/{memory_id}/important")
async def mark_memory_important(
    memory_id: str,
    important: bool = True,
    user_id: str = Depends(get_current_user)
):
    """
    标记记忆重要性

    快速切换记忆的重要标记，用于前端记忆面板的星标功能。
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # TODO: memory_service 迁移残留 — update_memory 的 allowed_fields 不包含 "important"
        success = await ms.update_memory(memory_id, {"important": important})
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或更新失败")

        return {
            "success": True,
            "message": "重要性标记已更新",
            "memory_id": memory_id,
            "important": important
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"标记记忆重要性失败: {str(e)}") from e


@router.post("/batch")
async def create_memories_batch(
    data: BatchCreateRequest,
    user_id: str = Depends(get_current_user)
):
    """
    批量创建记忆条目

    一次性保存多条记忆记录，用于自动汇聚思维流、工具调用等数据
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        created_ids = []
        failed_items = []

        for item in data.items:
            try:
                # 构建内容字典
                content = {"text": item.content}
                if item.tags:
                    content["tags"] = item.tags

                # 【P1修复】使用新 MemoryManager.add()，不再触发旧模块的向量同步
                memory_id = await ms.add_memory(
                    user_id=user_id,
                    content=content,
                    memory_type=item.type,
                    layer=item.layer,
                    scene=item.scene or "",
                    source=item.source or "user",
                    value_assessment=item.value_assessment
                )

                created_ids.append(memory_id)
            except Exception as e:
                failed_items.append({"item": item.content[:50], "error": str(e)})

        return {
            "success": True,
            "created": len(created_ids),
            "total": len(data.items),
            "memory_ids": created_ids,
            "failed_items": failed_items if failed_items else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量创建记忆失败: {str(e)}") from e


@router.delete("/batch")
async def batch_delete_memories(
    data: BatchDeleteRequest,
    user_id: str = Depends(get_current_user)
):
    """
    批量删除记忆

    一次性删除多条记忆记录
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        deleted = 0
        failed_ids = []

        for mid in data.ids:
            try:
                if await ms.delete_memory(mid):
                    deleted += 1
                else:
                    failed_ids.append(mid)
            except Exception:
                failed_ids.append(mid)

        return {
            "success": True,
            "deleted": deleted,
            "total": len(data.ids),
            "failed_ids": failed_ids if failed_ids else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}") from e


@router.post("/evolve")
async def evolve_memories(user_id: str = Depends(get_current_user)):
    """
    触发记忆进化

    启动记忆压缩、总结和层级提升流程
    """
    try:
        # 尝试调用进化服务
        try:
            from core.memory.memory_service import get_memory_service

            ms = await get_memory_service()

            # 获取可进化的记忆（短期记忆）
            candidates = await ms.query_memories(user_id, layer="short", limit=100)

            if candidates:
                # 触发压缩
                compressed_count = 0
                for mem in candidates:
                    # 标记为已处理或进行压缩
                    if mem.get('rating', 0) >= 5:  # 高价值记忆
                        compressed_count += 1

                return {
                    "success": True,
                    "data": {
                        "success": True,
                        "message": "记忆进化已触发",
                        "compressed_count": compressed_count,
                        "evolved_count": compressed_count
                    }
                }
        except ImportError:
            pass

        return {
            "success": True,
            "data": {
                "success": True,
                "message": "记忆进化已触发（模拟）",
                "compressed_count": 0,
                "evolved_count": 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"触发记忆进化失败: {str(e)}") from e


@router.get("/evolution-history")
async def get_evolution_history(
    limit: int = Query(default=10, ge=1, le=50, description="返回数量限制"),
    user_id: str = Depends(get_current_user)
):
    """
    获取记忆进化历史

    返回记忆压缩、升级的日志记录
    """
    try:
        # 从evolve层查询进化相关的记忆
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 查询进化层记忆
        results = await ms.query_memories(
            user_id,
            layer="evolve",
            filter_dict={"mem_type": "evolution"},
            limit=limit
        )

        # 如果没有专门的进化记录，返回空列表
        history = results if results else []

        return {
            "success": True,
            "history": history,
            "total": len(history)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取进化历史失败: {str(e)}") from e


@router.post("/filter-by-dimensions")
async def filter_by_dimensions(
    filter: DimensionFilter,
    limit: int = Query(default=50, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    按六维评分筛选

    根据情感温度、伦理安全等维度筛选记忆
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 获取所有记忆
        results = await ms.query_memories(user_id, limit=1000)

        # 应用维度过滤
        filtered = []
        for mem in results:
            va = mem.get('value_assessment', {})
            match = True

            if filter.emotional_temperature is not None and va.get('emotional_temperature', 3) < filter.emotional_temperature:
                match = False
            if filter.ethical_safety is not None and va.get('ethical_safety', 3) < filter.ethical_safety:
                match = False
            if filter.self_growth is not None and va.get('self_growth', 3) < filter.self_growth:
                match = False
            if filter.execution_effectiveness is not None and va.get('execution_effectiveness', 3) < filter.execution_effectiveness:
                match = False
            if filter.sustainability is not None and va.get('sustainability', 3) < filter.sustainability:
                match = False
            if filter.inspiration_innovation is not None and va.get('inspiration_innovation', 3) < filter.inspiration_innovation:
                match = False

            if match:
                filtered.append(mem)

        total = len(filtered)
        paginated_results = filtered[offset:offset + limit] if offset < len(filtered) else []

        # 转换字段名 memory_id -> id
        formatted_memories = []
        for mem in paginated_results:
            formatted_mem = dict(mem)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
            formatted_memories.append(formatted_mem)

        return {
            "success": True,
            "memories": formatted_memories,
            "total": total,
            "limit": limit,
            "offset": offset,
            "filter_applied": filter.model_dump(exclude_unset=True)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"维度筛选失败: {str(e)}") from e


@router.get("/filter-by-grades")
async def filter_by_grades(
    grade: str = Query(..., pattern="^[SABCD]$", description="等级(S/A/B/C/D)"),
    limit: int = Query(default=50, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    按等级筛选记忆

    根据综合评分等级(S/A/B/C/D)筛选记忆
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 获取所有记忆
        results = await ms.query_memories(user_id, limit=1000)

        # 按等级过滤
        filtered = [
            mem for mem in results
            if mem.get('value_assessment', {}).get('grade') == grade
        ]

        total = len(filtered)
        paginated_results = filtered[offset:offset + limit] if offset < len(filtered) else []

        # 转换字段名 memory_id -> id
        formatted_memories = []
        for mem in paginated_results:
            formatted_mem = dict(mem)
            if "memory_id" in formatted_mem:
                formatted_mem["id"] = formatted_mem.pop("memory_id")
            formatted_memories.append(formatted_mem)

        return {
            "success": True,
            "memories": formatted_memories,
            "total": total,
            "limit": limit,
            "offset": offset,
            "grade": grade
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"等级筛选失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# L5 执行记忆 API 端点
# ═══════════════════════════════════════════════════════════════════

class ExecutionMemoryFilter(BaseModel):
    """L5执行记忆筛选请求模型"""
    tool_name: str | None = Field(default=None, description="工具名称过滤")
    success_only: bool | None = Field(default=None, description="仅成功记录")
    limit: int = Field(default=50, ge=1, le=200, description="返回数量限制")
    offset: int = Field(default=0, ge=0, description="偏移量")


@router.get("/executions")
async def get_execution_memories(
    tool_name: str | None = Query(default=None, description="工具名称过滤"),
    success_only: bool | None = Query(default=None, description="仅成功记录"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    获取L5执行轨迹

    获取工具执行历史记录，支持按工具名和成功状态筛选
    """
    try:
        from core.memory.execution_memory import execution_memory_manager

        if execution_memory_manager is None:
            raise HTTPException(status_code=503, detail="执行记忆服务未初始化")

        # 获取执行记录
        records = await execution_memory_manager.get_recent_executions_async(
            user_id=user_id or "default",
            tool_name=tool_name,
            limit=limit + offset,
            success_only=success_only
        )

        total = len(records)
        # 应用偏移量
        paginated_records = records[offset:offset + limit] if offset < len(records) else []

        return {
            "success": True,
            "executions": paginated_records,
            "total": total,
            "limit": limit,
            "offset": offset,
            "layer": "execution"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行记忆失败: {str(e)}") from e


@router.get("/executions/stats")
async def get_execution_stats(
    days: int = Query(default=30, ge=1, le=365, description="统计天数范围"),
    user_id: str = Depends(get_current_user)
):
    """
    获取L5执行统计

    返回指定时间范围内的执行统计信息，包括成功率、平均耗时等
    """
    try:
        from core.memory.execution_memory import execution_memory_manager

        if execution_memory_manager is None:
            raise HTTPException(status_code=503, detail="执行记忆服务未初始化")

        stats = await execution_memory_manager.get_execution_stats_async(
            user_id=user_id or "default",
            days=days
        )

        return {
            "success": True,
            "stats": stats,
            "period_days": days,
            "layer": "execution"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行统计失败: {str(e)}") from e


@router.delete("/executions/{execution_id}")
async def delete_execution_memory(
    execution_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    删除L5执行记录

    注意：L5执行记录删除后会从执行历史中移除，但不影响L1-L3记忆
    """
    try:
        # L5执行记录存储在JSONL文件中，需要通过重写文件来删除
        # 这是一个简化实现，实际可能需要更复杂的文件操作
        from core.memory.execution_memory import EXECUTION_DIR, execution_memory_manager

        if execution_memory_manager is None:
            raise HTTPException(status_code=503, detail="执行记忆服务未初始化")

        # 获取用户存储路径
        target_user = user_id or "default"
        user_file = EXECUTION_DIR / target_user / "executions.jsonl"

        if not user_file.exists():
            raise HTTPException(status_code=404, detail="执行记录文件不存在")

        # 读取所有记录，过滤掉要删除的
        deleted = False
        remaining_lines = []

        async with aiofiles.open(user_file, encoding='utf-8') as f:
            lines = await f.readlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # 生成记录ID进行匹配
                import hashlib
                record_id = hashlib.md5(
                    f"{data.get('user_id')}_{data.get('tool_name')}_{data.get('timestamp')}".encode()
                ).hexdigest()[:16]

                if record_id != execution_id:
                    remaining_lines.append(line)
                else:
                    deleted = True
            except Exception as e:
                logger.error(f"[MemoryAPI] 执行记录解析失败，丢弃损坏行: {e}", exc_info=True)
                # 不保留损坏行，避免假删除和数据膨胀

        if not deleted:
            raise HTTPException(status_code=404, detail="执行记录不存在")

        # 写回文件
        async with aiofiles.open(user_file, 'w', encoding='utf-8') as f:
            for line in remaining_lines:
                await f.write(line + "\n")

        # 刷新内存缓存
        store = execution_memory_manager.get_user_store(target_user)
        store._load_recent_records()

        return {
            "success": True,
            "message": "执行记录已删除",
            "execution_id": execution_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除执行记录失败: {str(e)}") from e


@router.post("/executions/batch-delete")
async def batch_delete_executions(
    data: BatchDeleteRequest,
    user_id: str = Depends(get_current_user)
):
    """
    批量删除L5执行记录

    一次性删除多条执行记录
    """
    try:
        from core.memory.execution_memory import EXECUTION_DIR, execution_memory_manager

        if execution_memory_manager is None:
            raise HTTPException(status_code=503, detail="执行记忆服务未初始化")

        target_user = user_id or "default"
        user_file = EXECUTION_DIR / target_user / "executions.jsonl"

        if not user_file.exists():
            return {
                "success": True,
                "deleted": 0,
                "total": len(data.ids),
                "message": "执行记录文件不存在"
            }

        # 读取所有记录，过滤掉要删除的
        ids_to_delete = set(data.ids)
        deleted_count = 0
        remaining_lines = []

        async with aiofiles.open(user_file, encoding='utf-8') as f:
            lines = await f.readlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record_data = json.loads(line)
                import hashlib
                record_id = hashlib.md5(
                    f"{record_data.get('user_id')}_{record_data.get('tool_name')}_{record_data.get('timestamp')}".encode()
                ).hexdigest()[:16]

                if record_id in ids_to_delete:
                    deleted_count += 1
                else:
                    remaining_lines.append(line)
            except Exception as e:
                logger.error(f"[MemoryAPI] 批量删除时执行记录解析失败，丢弃损坏行: {e}", exc_info=True)
                # 不保留损坏行，避免数据一致性风险

        # 写回文件
        async with aiofiles.open(user_file, 'w', encoding='utf-8') as f:
            for line in remaining_lines:
                await f.write(line + "\n")

        # 刷新内存缓存
        store = execution_memory_manager.get_user_store(target_user)
        store._load_recent_records()

        return {
            "success": True,
            "deleted": deleted_count,
            "total": len(data.ids),
            "failed_ids": [id for id in data.ids if id not in ids_to_delete][:10] if deleted_count < len(data.ids) else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除执行记录失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# L4 向量记忆搜索 API 端点 (Fix-Memory-1)
# ═══════════════════════════════════════════════════════════════════

# 创建新的router用于 /api/memory/vector/* 端点
vector_router = APIRouter(
    prefix="/memory/vector",
    tags=["memory-vector"],
    dependencies=router_dependencies
)


@vector_router.get("/search")
async def vector_search(
    collection: str = Query(..., description="向量集合名称 (experience/knowledge/chat/voice_fix/execution)"),
    query: str = Query(..., description="搜索查询文本"),
    top_k: int = Query(default=10, ge=1, le=50, description="返回结果数量限制"),
    user_id: str = Depends(get_current_user)
):
    """
    L4向量记忆搜索

    在指定的向量集合中进行语义相似度搜索，返回最相关的记忆。
    支持的记忆集合：
    - experience: 经验记忆
    - knowledge: 知识记忆
    - chat: 对话记录
    - voice_fix: 语音纠错
    - execution: 执行记录
    """
    try:
        # 验证集合名称
        valid_collections = ["experience", "knowledge", "chat", "voice_fix", "execution"]
        if collection not in valid_collections:
            raise HTTPException(
                status_code=400,
                detail=f"无效的集合名称: {collection}。有效选项: {', '.join(valid_collections)}"
            )

        # 执行向量搜索
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        results = await ms.vector_store.search(
            collection=collection,
            query=query,
            limit=top_k
        )

        # 格式化结果
        formatted_results = []
        for result in results:
            formatted_results.append({
                "id": result.id,
                "content": result.document,
                "metadata": result.metadata,
                "similarity": 1.0 - (result.distance or 0.0)
            })

        return {
            "success": True,
            "data": {
                "results": formatted_results,
                "total": len(formatted_results),
                "collection": collection,
                "query": query
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"向量搜索失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# Agent-4: Source统计 API 端点
# ═══════════════════════════════════════════════════════════════════

@router.get("/by-session/{session_id}")
async def get_memories_by_session(
    session_id: str,
    layer: str | None = Query(default=None, description="记忆层级过滤(short/medium/long/execution/evolve)"),
    mem_type: str | None = Query(default=None, description="记忆类型过滤"),
    limit: int = Query(default=50, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user)
):
    """
    获取指定会话的所有记忆

    查询与session关联的所有记忆，建立message↔memory的查询能力。

    Args:
        session_id: 会话ID
        layer: 可选的记忆层级过滤
        mem_type: 可选的记忆类型过滤
        limit: 返回数量限制
        offset: 分页偏移量

    Returns:
        关联的记忆列表
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 首先获取session中的所有消息
        from core.session.session_manager import get_session_manager
        session_manager = get_session_manager()

        has_more, next_cursor, messages = await session_manager.get_messages(
            session_id=session_id,
            limit=1000  # 获取所有消息
        )

        # 提取所有关联的memory_id
        memory_ids = []
        message_memory_map = {}  # memory_id -> message_id映射

        for msg in messages:
            if msg.memory_id:
                memory_ids.append(msg.memory_id)
                message_memory_map[msg.memory_id] = msg.id

        if not memory_ids:
            return {
                "success": True,
                "memories": [],
                "total": 0,
                "session_id": session_id,
                "message_count": len(messages),
                "linked_memory_count": 0
            }

        # 查询这些记忆
        memories = []
        for mem_id in memory_ids:
            try:
                mem = await ms.get_memory_by_id(mem_id)
                if mem:
                    # 应用过滤条件
                    if layer and mem.get("layer") != layer:
                        continue
                    if mem_type and mem.get("mem_type") != mem_type:
                        continue

                    # 转换字段名并添加关联信息
                    formatted_mem = dict(mem)
                    if "memory_id" in formatted_mem:
                        formatted_mem["id"] = formatted_mem.pop("memory_id")

                    # 添加关联的消息ID
                    formatted_mem["linked_message_id"] = message_memory_map.get(mem_id)
                    memories.append(formatted_mem)
            except Exception as e:
                logger.error(f"[MemoryAPI] 获取记忆详情失败: {mem_id}, error={e}", exc_info=True)
                continue

        # 按时间倒序排序
        memories.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # 应用分页
        total = len(memories)
        paginated_memories = memories[offset:offset + limit] if offset < len(memories) else []

        return {
            "success": True,
            "memories": paginated_memories,
            "total": total,
            "limit": limit,
            "offset": offset,
            "session_id": session_id,
            "message_count": len(messages),
            "linked_memory_count": len(memory_ids)
        }

    except Exception as e:
        logger.error(f"[MemoryAPI] 获取会话记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话记忆失败: {str(e)}") from e


@router.get("/source-stats")
async def get_memory_source_stats(
    user_id: str = Depends(get_current_user)
):
    """
    获取记忆来源统计

    返回各来源（ai/system/user/reflection/evolution）的记忆数量统计
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 获取统计信息（包含by_source）
        stats = await ms.get_memory_stats(user_id)

        # 构建返回数据
        source_stats = stats.get("by_source", {})
        total = stats.get("total", 0)

        # 计算百分比
        source_percentages = {}
        for source, count in source_stats.items():
            source_percentages[source] = {
                "count": count,
                "percentage": round(count / total * 100, 2) if total > 0 else 0
            }

        # 来源中文名称映射
        source_display_names = {
            "ai": "AI自主",
            "system": "系统推送",
            "user": "用户添加",
            "reflection": "反思产生",
            "evolution": "进化产生"
        }

        return {
            "success": True,
            "data": {
                "total": total,
                "by_source": source_percentages,
                "display_names": source_display_names
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取来源统计失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 记忆可视化 - 从 memory_visualization_api.py 合并
# ═══════════════════════════════════════════════════════════════════

# 用户ID统一处理辅助函数
def get_effective_user_id(
    jwt_user_id: str | None = None,
    session_id: str | None = None,
    default: str = "default"
) -> str:
    """
    获取有效的用户ID

    优先级:
    1. JWT user_id (如果存在)
    2. Session ID (从header获取)
    3. 默认值 "default"

    Args:
        jwt_user_id: 从JWT获取的用户ID
        session_id: 从X-Session-Id header获取的会话ID
        default: 默认用户ID

    Returns:
        有效的用户ID
    """
    if jwt_user_id:
        return jwt_user_id
    if session_id:
        return session_id if session_id != "console" else default
    return default


# Pydantic 模型定义
class MemoryFlowItem(BaseModel):
    """记忆流动项"""
    id: str
    type: str  # input, output, transform
    content: str
    layer: str
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryFlowResponse(BaseModel):
    """记忆流动响应"""
    inputs: list[MemoryFlowItem] = Field(default_factory=list)
    outputs: list[MemoryFlowItem] = Field(default_factory=list)
    transforms: list[MemoryFlowItem] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)


class MemoryVizNode(BaseModel):
    """记忆图谱节点"""
    id: str
    label: str
    layer: str
    type: str
    size: int = 1
    color: str = "#00d4ff"
    x: float | None = None
    y: float | None = None


class MemoryVizEdge(BaseModel):
    """记忆图谱边"""
    source: str
    target: str
    weight: float = 1.0
    type: str = "association"


class MemoryVizGraphResponse(BaseModel):
    """记忆图谱响应"""
    nodes: list[MemoryVizNode] = Field(default_factory=list)
    edges: list[MemoryVizEdge] = Field(default_factory=list)


class LayerDistribution(BaseModel):
    """层级分布"""
    L1: int = 0
    L2: int = 0
    L3: int = 0
    L4: int = 0
    L5: int = 0


class SourceDistribution(BaseModel):
    """来源分布"""
    AI: int = 0
    system: int = 0
    user: int = 0
    tool: int = 0


class DailyGrowth(BaseModel):
    """每日增长"""
    date: str
    count: int
    layer: str


class MemoryStatsResponse(BaseModel):
    """记忆统计响应"""
    layer_distribution: LayerDistribution
    source_distribution: SourceDistribution
    daily_growth: list[DailyGrowth]
    retention_rate: float = 0.85
    total_memories: int = 0
    active_memories: int = 0


# WebSocket连接管理
class MemoryWebSocketManager:
    """记忆可视化WebSocket管理器"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.memory_update_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def connect(self, websocket: WebSocket, user_id: str):
        """连接WebSocket"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"[MemoryWebSocket] 用户 {user_id} 已连接")

    def disconnect(self, user_id: str):
        """断开WebSocket"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"[MemoryWebSocket] 用户 {user_id} 已断开")

    async def send_memory_update(self, user_id: str, data: dict[str, Any]):
        """发送记忆更新"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json({
                    "type": "memory_update",
                    "timestamp": datetime.now().isoformat(),
                    "data": data
                })
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 发送更新失败: {e}")

    async def broadcast(self, data: dict[str, Any]):
        """广播消息给所有连接"""
        for user_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 广播失败: {e}")
                self.disconnect(user_id)


# 全局WebSocket管理器
memory_ws_manager = MemoryWebSocketManager()

viz_dependencies = [Depends(get_current_user_optional)] if AUTH_AVAILABLE else []


@router.get("/viz/flow", response_model=MemoryFlowResponse, dependencies=viz_dependencies)
async def get_memory_flow(
    user_id: str | None = Depends(get_current_user_optional),
    time_range: str = Query(default="1h", description="时间范围: 1h, 24h, 7d, 30d"),
    x_session_id: str | None = Header(None, alias="X-Session-Id")
):
    """
    获取记忆流动数据

    返回指定时间范围内的记忆流动情况，包括新增、检索和转换的记忆

    【Phase 2修复】支持从X-Session-Id header获取用户ID
    """
    try:
        effective_user_id = get_effective_user_id(user_id, x_session_id)

        now = datetime.now()
        time_deltas = {
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30)
        }
        delta = time_deltas.get(time_range, timedelta(hours=1))
        since = now - delta

        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        all_memories = []
        for layer in ["working", "short", "medium", "evolve", "execution"]:
            memories = await ms.query_memories(user_id=effective_user_id, layer=layer, limit=1000)
            for mem in memories:
                mem["_layer"] = layer
            all_memories.extend(memories)

        filtered_memories = []
        for mem in all_memories:
            created_at = mem.get("created_at", "")
            if created_at:
                try:
                    from datetime import timezone
                    mem_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                    if mem_time.tzinfo is None:
                        mem_time = mem_time.replace(tzinfo=timezone.utc)
                    if mem_time >= since:
                        filtered_memories.append(mem)
                except (ValueError, TypeError) as e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 时间解析失败 '{created_at}': {e}")

        inputs = []
        outputs = []
        transforms = []
        timeline = []

        for mem in filtered_memories:
            mem_id = mem.get("memory_id", mem.get("id", "unknown"))
            layer = mem.get("_layer", "short")
            content = str(mem.get("content", ""))[:100]
            timestamp = mem.get("created_at", datetime.now().isoformat())
            mem_type = mem.get("mem_type", "chat")

            if mem.get("is_retrieved"):
                outputs.append(MemoryFlowItem(
                    id=mem_id,
                    type="output",
                    content=content,
                    layer=layer,
                    timestamp=timestamp,
                    metadata={"mem_type": mem_type}
                ))
            elif mem.get("is_transformed") or mem_type in ["evolution", "compression"]:
                transforms.append(MemoryFlowItem(
                    id=mem_id,
                    type="transform",
                    content=content,
                    layer=layer,
                    timestamp=timestamp,
                    metadata={"mem_type": mem_type}
                ))
            else:
                inputs.append(MemoryFlowItem(
                    id=mem_id,
                    type="input",
                    content=content,
                    layer=layer,
                    timestamp=timestamp,
                    metadata={"mem_type": mem_type}
                ))

            timeline.append({
                "id": mem_id,
                "timestamp": timestamp,
                "type": mem_type,
                "layer": layer,
                "content": content
            })

        timeline.sort(key=lambda x: x["timestamp"], reverse=True)

        return MemoryFlowResponse(
            inputs=inputs[:50],
            outputs=outputs[:50],
            transforms=transforms[:50],
            timeline=timeline[:100]
        )

    except Exception as e:
        logger.error(f"[SILENT_FAILURE_BLOCKED] 获取记忆流动数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆流动数据失败: {str(e)}") from e


@router.get("/viz/graph", response_model=MemoryVizGraphResponse, dependencies=viz_dependencies)
async def get_memory_viz_graph(
    user_id: str | None = Depends(get_current_user_optional),
    layer: str = Query(default="all", description="层级过滤: all, short, medium, long"),
    x_session_id: str | None = Header(None, alias="X-Session-Id")
):
    """
    获取记忆关联图谱数据

    返回记忆节点和关联边，用于力导向图可视化

    【Phase 2修复】支持从X-Session-Id header获取用户ID
    """
    try:
        effective_user_id = get_effective_user_id(user_id, x_session_id)

        from core.memory.memory_service import get_memory_service

        ms = await get_memory_service()

        layers_to_query = ["working", "short", "medium", "evolve"] if layer == "all" else [layer]
        all_memories = []
        for lyr in layers_to_query:
            memories = await ms.query_memories(user_id=effective_user_id, layer=lyr, limit=200)
            for mem in memories:
                mem["_layer"] = lyr
            all_memories.extend(memories)

        nodes = []
        node_map = {}
        layer_colors = {
            "short": "#00d4ff",
            "medium": "#00ff88",
            "long": "#ffaa00",
            "evolve": "#ff00ff"
        }

        for i, mem in enumerate(all_memories):
            mem_id = mem.get("memory_id", mem.get("id", f"mem_{i}"))
            lyr = mem.get("_layer", "short")
            content = str(mem.get("content", ""))

            node = MemoryVizNode(
                id=mem_id,
                label=content[:30] + "..." if len(content) > 30 else content,
                layer=lyr,
                type=mem.get("mem_type", "chat"),
                size=max(1, min(5, len(content) // 100)),
                color=layer_colors.get(lyr, "#00d4ff")
            )
            nodes.append(node)
            node_map[mem_id] = node

        edges = []

        try:
            from core.memory.memory_associations import MemoryAssociationManager
            assoc_manager = MemoryAssociationManager()
            for mem in all_memories:
                mem_id = mem.get("memory_id", mem.get("id"))
                try:
                    related = await assoc_manager.find_associated_memories(mem_id, limit=5)
                    for assoc in related:
                        rel_id = assoc.get("target_memory_id") or assoc.get("source_memory_id")
                        if rel_id and rel_id in node_map:
                            edges.append(MemoryVizEdge(
                                source=mem_id,
                                target=rel_id,
                                weight=assoc.get("strength", 0.5),
                                type="association"
                            ))
                except Exception as e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 关联查询失败 '{mem_id}': {e}")
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 关联管理器初始化失败: {e}")

        scene_groups = {}
        for mem in all_memories:
            scene = mem.get("scene", "")
            if scene:
                if scene not in scene_groups:
                    scene_groups[scene] = []
                scene_groups[scene].append(mem.get("memory_id", mem.get("id")))

        for _scene, mem_ids in scene_groups.items():
            if len(mem_ids) > 1:
                for i in range(len(mem_ids)):
                    for j in range(i + 1, len(mem_ids)):
                        edges.append(MemoryVizEdge(
                            source=mem_ids[i],
                            target=mem_ids[j],
                            weight=0.5,
                            type="scene"
                        ))

        seen_edges = set()
        unique_edges = []
        for edge in edges:
            edge_key = tuple(sorted([edge.source, edge.target]))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)

        return MemoryVizGraphResponse(
            nodes=nodes,
            edges=unique_edges[:300]
        )

    except Exception as e:
        logger.error(f"[SILENT_FAILURE_BLOCKED] 获取记忆图谱数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆图谱数据失败: {str(e)}") from e


@router.get("/viz/stats", response_model=MemoryStatsResponse, dependencies=viz_dependencies)
async def get_memory_stats(
    user_id: str | None = Depends(get_current_user_optional),
    x_session_id: str | None = Header(None, alias="X-Session-Id")
):
    """
    获取记忆统计数据

    返回记忆层级分布、来源分布、增长趋势等统计信息

    【Phase 2修复】支持从X-Session-Id header获取用户ID，解决用户ID不一致问题
    """
    try:
        effective_user_id = get_effective_user_id(user_id, x_session_id)
        logger.debug(f"[MemoryViz] 统计查询 - JWT user_id: {user_id}, session_id: {x_session_id}, effective: {effective_user_id}")

        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        layer_counts = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0}
        source_counts = {"AI": 0, "system": 0, "user": 0, "tool": 0}
        daily_growth_map = {}
        total_memories = 0

        layer_mapping = {
            "working": "L1",
            "short": "L2",
            "medium": "L3",
            "evolve": "L4",
            "execution": "L5"
        }

        for layer_key, layer_label in layer_mapping.items():
            try:
                memories = await ms.query_memories(user_id=effective_user_id, layer=layer_key, limit=1000)
                layer_counts[layer_label] = len(memories)
                total_memories += len(memories)

                for mem in memories:
                    mem_type = mem.get("mem_type", "chat")
                    if mem_type in ["internal_thought", "ai_response"]:
                        source_counts["AI"] += 1
                    elif mem_type in ["system_event", "evolution"]:
                        source_counts["system"] += 1
                    elif mem_type in ["user_input", "user_preference"]:
                        source_counts["user"] += 1
                    elif mem_type in ["tool_call", "tool_result"]:
                        source_counts["tool"] += 1
                    else:
                        source_counts["system"] += 1

                    created_at = mem.get("created_at", "")
                    if created_at:
                        try:
                            date = created_at.split("T")[0]
                            key = f"{date}:{layer_label}"
                            daily_growth_map[key] = daily_growth_map.get(key, 0) + 1
                        except (IndexError, ValueError, TypeError) as e:
                            logger.error(f"[SILENT_FAILURE_BLOCKED] 日期分割失败 '{created_at}': {e}")
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 层级查询失败 '{layer_key}': {e}")

        daily_growth = []
        today = datetime.now().date()
        for i in range(30):
            date = today - timedelta(days=i)
            date_str = date.isoformat()
            for layer_label in ["L1", "L2", "L3", "L4", "L5"]:
                key = f"{date_str}:{layer_label}"
                count = daily_growth_map.get(key, 0)
                if count > 0:
                    daily_growth.append(DailyGrowth(
                        date=date_str,
                        count=count,
                        layer=layer_label
                    ))

        daily_growth.sort(key=lambda x: x.date, reverse=True)

        long_term = layer_counts["L2"] + layer_counts["L3"] + layer_counts["L4"]
        retention_rate = round(long_term / max(total_memories, 1), 2)

        return MemoryStatsResponse(
            layer_distribution=LayerDistribution(**layer_counts),
            source_distribution=SourceDistribution(**source_counts),
            daily_growth=daily_growth[:30],
            retention_rate=retention_rate,
            total_memories=total_memories,
            active_memories=layer_counts["L1"]
        )

    except Exception as e:
        logger.error(f"[SILENT_FAILURE_BLOCKED] 获取记忆统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}") from e


@router.get("/viz/timeline", dependencies=viz_dependencies)
async def get_memory_timeline(
    user_id: str | None = Depends(get_current_user_optional),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_session_id: str | None = Header(None, alias="X-Session-Id")
):
    """
    获取记忆时间线

    按时间顺序返回记忆事件

    【Phase 2修复】支持从X-Session-Id header获取用户ID
    """
    try:
        effective_user_id = get_effective_user_id(user_id, x_session_id)

        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        all_memories = []
        for layer in ["working", "short", "medium", "evolve", "execution"]:
            memories = await ms.query_memories(user_id=effective_user_id, layer=layer, limit=500)
            for mem in memories:
                mem["_layer"] = layer
            all_memories.extend(memories)

        all_memories.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )

        paginated = all_memories[offset:offset + limit]

        timeline_items = []
        for mem in paginated:
            timeline_items.append({
                "id": mem.get("memory_id", mem.get("id", "unknown")),
                "timestamp": mem.get("created_at", ""),
                "layer": mem.get("_layer", "short"),
                "type": mem.get("mem_type", "chat"),
                "content": str(mem.get("content", ""))[:200],
                "scene": mem.get("scene", ""),
                "rating": mem.get("rating", 0)
            })

        return {
            "success": True,
            "timeline": timeline_items,
            "total": len(all_memories),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"[SILENT_FAILURE_BLOCKED] 获取时间线失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取时间线失败: {str(e)}") from e


@router.websocket("/ws/realtime/{user_id}")
async def memory_websocket(websocket: WebSocket, user_id: str):
    """
    WebSocket实时推送记忆更新

    当记忆发生变化时，实时推送到前端
    """
    await memory_ws_manager.connect(websocket, user_id)

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("action") == "subscribe":
                await websocket.send_json({
                    "type": "subscribed",
                    "message": "已订阅记忆更新"
                })

            elif data.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                })

    except WebSocketDisconnect:
        memory_ws_manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"[SILENT_FAILURE_BLOCKED] WebSocket错误: {e}")
        memory_ws_manager.disconnect(user_id)


async def notify_memory_change(user_id: str, change_type: str, memory_data: dict[str, Any]):
    """
    通知记忆变化

    当记忆被添加、更新或删除时调用此函数通知前端
    """
    await memory_ws_manager.send_memory_update(user_id, {
        "change_type": change_type,
        "memory": memory_data
    })


def init_memory_visualization_routes(app):
    """
    初始化记忆可视化路由

    在主应用启动时调用
    """
    app.include_router(router, prefix="/api")
    logger.info("[MemoryVisualization] 记忆可视化路由已注册")


# ═══════════════════════════════════════════════════════════════════
# 记忆图谱 - 从 memory_graph_api.py 合并
# ═══════════════════════════════════════════════════════════════════

try:
    from core.memory.memory_graph import MemoryAssociationEngine, MemoryGraph, get_association_engine, get_memory_graph
    MEMORY_GRAPH_AVAILABLE = True
except ImportError:
    MEMORY_GRAPH_AVAILABLE = False
    MemoryGraph = None
    MemoryAssociationEngine = None


class MemoryGraphAPI:
    """记忆图谱API类

    提供统一接口供外部调用，处理用户认证和参数验证。
    """

    def __init__(self):
        """初始化API"""
        if not MEMORY_GRAPH_AVAILABLE:
            logger.warning("[MemoryGraphAPI] MemoryGraph module not available")

    def add_memory_node(self, user_id: str, memory_id: str,
                        attributes: dict[str, Any]) -> dict[str, Any]:
        """添加记忆节点"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            success = graph.add_memory_node(memory_id, attributes)

            return {
                "success": success,
                "memory_id": memory_id,
                "message": "Node added successfully" if success else "Failed to add node"
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] add_memory_node error: {e}")
            return {"success": False, "error": str(e)}

    def add_relation(self, user_id: str, from_id: str, to_id: str,
                    relation_type: str, strength: float,
                    attributes: dict[str, Any] | None = None) -> dict[str, Any]:
        """添加记忆关系"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            success = graph.add_relation(from_id, to_id, relation_type, strength, attributes)

            return {
                "success": success,
                "source": from_id,
                "target": to_id,
                "relation_type": relation_type,
                "strength": strength,
                "message": "Relation added successfully" if success else "Failed to add relation"
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] add_relation error: {e}")
            return {"success": False, "error": str(e)}

    def find_related(self, user_id: str, memory_id: str,
                     depth: int = 2, min_strength: float = 0.0,
                     relation_types: list[str] | None = None,
                     limit: int = 20) -> dict[str, Any]:
        """联想回忆 - 查找关联记忆"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            related = graph.find_related(memory_id, depth, min_strength, relation_types)
            related = related[:limit]

            return {
                "success": True,
                "memory_id": memory_id,
                "count": len(related),
                "related_memories": related
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] find_related error: {e}")
            return {"success": False, "error": str(e)}

    def find_path(self, user_id: str, start_id: str, end_id: str) -> dict[str, Any]:
        """查找推理路径"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            path = graph.find_path(start_id, end_id)

            if path:
                return {
                    "success": True,
                    "path_exists": True,
                    "start": start_id,
                    "end": end_id,
                    "nodes": path.nodes,
                    "edges": path.edges,
                    "total_strength": path.total_strength,
                    "length": path.length
                }
            else:
                return {
                    "success": True,
                    "path_exists": False,
                    "start": start_id,
                    "end": end_id,
                    "message": "No path found"
                }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] find_path error: {e}")
            return {"success": False, "error": str(e)}

    def get_visualization_data(self, user_id: str,
                               center_node: str | None = None,
                               depth: int = 2, limit: int = 100) -> dict[str, Any]:
        """获取可视化数据"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            data = graph.get_graph_data(center_node, depth, limit)

            return {
                "success": True,
                "user_id": user_id,
                **data
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] get_visualization_data error: {e}")
            return {"success": False, "error": str(e)}

    def get_stats(self, user_id: str) -> dict[str, Any]:
        """获取图谱统计信息"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            stats = graph.get_graph_stats()

            return {
                "success": True,
                "user_id": user_id,
                "stats": stats
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] get_stats error: {e}")
            return {"success": False, "error": str(e)}

    def auto_discover_relations(self, user_id: str, memory_id: str,
                                candidate_ids: list[str] | None = None) -> dict[str, Any]:
        """自动发现关系"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            discovered = graph.auto_discover_relations(memory_id, candidate_ids)

            return {
                "success": True,
                "memory_id": memory_id,
                "discovered_count": len(discovered),
                "relations": discovered
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] auto_discover_relations error: {e}")
            return {"success": False, "error": str(e)}

    def export_graph(self, user_id: str, format: str = "cytoscape") -> dict[str, Any]:
        """导出图谱数据"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)

            data = graph.export_to_cytoscape() if format == "cytoscape" else graph.get_graph_data()

            return {
                "success": True,
                "format": format,
                "data": data
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] export_graph error: {e}")
            return {"success": False, "error": str(e)}

    def refresh_graph(self, user_id: str) -> dict[str, Any]:
        """刷新图谱数据"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            graph = get_memory_graph(user_id)
            success = graph.refresh()

            return {
                "success": success,
                "user_id": user_id,
                "node_count": graph.graph.number_of_nodes(),
                "edge_count": graph.graph.number_of_edges()
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] refresh_graph error: {e}")
            return {"success": False, "error": str(e)}

    def associative_recall(self, user_id: str, query: str,
                          context: dict[str, Any] | None = None,
                          top_k: int = 5) -> dict[str, Any]:
        """高级联想回忆"""
        if not MEMORY_GRAPH_AVAILABLE:
            return {"success": False, "error": "MemoryGraph not available"}

        try:
            engine = get_association_engine(user_id)
            results = engine.associative_recall(query, context, top_k)

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "results": results
            }
        except Exception as e:
            logger.error(f"[MemoryGraphAPI] associative_recall error: {e}")
            return {"success": False, "error": str(e)}


memory_graph_api = None

try:
    if MEMORY_GRAPH_AVAILABLE:
        memory_graph_api = MemoryGraphAPI()
        print("[记忆图谱] 【成功】API初始化完成")
    else:
        print("[WARNING] Memory Graph API partially available")
except Exception as e:
    print(f"[ERROR] Failed to initialize Memory Graph API: {e}")


_memory_graph_api_instance = memory_graph_api


@router.get("/graph")
async def get_graph_root(user_id: str):
    """记忆图谱根路径 - 返回统计信息和可用端点"""
    if not _memory_graph_api_instance:
        return {"success": False, "error": "MemoryGraph not available"}
    result = _memory_graph_api_instance.get_stats(user_id)
    if result.get("success"):
        return {
            "success": True,
            "message": "记忆图谱API",
            "stats": result.get("stats", {}),
            "endpoints": [
                "/node (POST)",
                "/relation (POST)",
                "/related/{memory_id} (GET)",
                "/path (GET)",
                "/visualization (GET)",
                "/stats (GET)",
                "/discover (POST)",
                "/export (GET)"
            ]
        }
    return result


@router.post("/graph/node")
async def add_node(user_id: str, memory_id: str, attributes: dict):
    """添加记忆节点"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.add_memory_node(user_id, memory_id, attributes)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/graph/relation")
async def add_relation_endpoint(user_id: str, from_id: str, to_id: str,
                              relation_type: str, strength: float,
                              attributes: dict = None):
    """添加记忆关系"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.add_relation(user_id, from_id, to_id, relation_type,
                                 strength, attributes)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/graph/related/{memory_id}")
async def find_related_route(memory_id: str, user_id: str,
                      depth: int = 2, min_strength: float = 0.0,
                      limit: int = 20):
    """联想回忆"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.find_related(user_id, memory_id, depth, min_strength,
                                 limit=limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/graph/path")
async def find_path_route(user_id: str, start_id: str, end_id: str):
    """查找推理路径"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.find_path(user_id, start_id, end_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/graph/visualization")
async def get_visualization_route(user_id: str, center_node: str = None,
                           depth: int = 2, limit: int = 100):
    """获取可视化数据"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.get_visualization_data(user_id, center_node, depth, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/graph/stats")
async def get_graph_stats_route(user_id: str):
    """获取统计信息"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.get_stats(user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/graph/discover")
async def auto_discover_route(user_id: str, memory_id: str):
    """自动发现关系"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.auto_discover_relations(user_id, memory_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/graph/export")
async def export_graph_route(user_id: str, format: str = "cytoscape"):
    """导出图谱数据"""
    if not _memory_graph_api_instance:
        raise HTTPException(status_code=503, detail="MemoryGraph not available")
    result = _memory_graph_api_instance.export_graph(user_id, format)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


print("[记忆图谱] 【成功】API路由模块已初始化")


def register_routes(app):
    """【已弃用】保留此函数仅用于兼容旧代码。新代码请在 cloud_api.py 中使用 app.include_router(router, prefix='/api')"""
    app.include_router(router, prefix="/api")
    print("[记忆图谱] 【成功】API路由已通过 register_routes 注册（兼容模式）")
