#!/usr/bin/env python3
"""
经验量化 API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供经验注入效果量化的 RESTful API 接口

端点列表:
- GET    /api/experience/ab-test/report          - A/B测试报告
- POST   /api/experience/ab-test/assign          - 分配A/B测试分组
- POST   /api/experience/ab-test/outcome         - 记录任务结果

- GET    /api/experience/effectiveness/global-stats    - 全局统计
- GET    /api/experience/effectiveness/leaderboard      - 效果排行榜
- GET    /api/experience/effectiveness/{exp_id}        - 单条经验统计

- GET    /api/experience/purge/candidates         - 淘汰候选列表
- POST   /api/experience/purge/scan               - 运行淘汰扫描
- POST   /api/experience/purge/execute            - 执行淘汰

Author: Agent-6 Experience Optimizer
Version: 1.0.0
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 导入认证依赖 - 使用独立的auth_utils模块避免循环导入
try:
    from api.auth_utils import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        logger.error(f"[ExperienceAPI] 认证模块导入失败: {e}")

        async def get_current_user() -> str | None:
            raise HTTPException(status_code=503, detail="认证服务不可用")

router_dependencies = [Depends(get_current_user)] if AUTH_AVAILABLE else []
router = APIRouter(
    prefix="/experience",
    tags=["experience-quantification"],
    dependencies=router_dependencies
)


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════════════

class ABTestAssignRequest(BaseModel):
    """A/B测试分组请求"""
    task_description: str = Field(..., description="任务描述")
    task_type: str = Field(..., description="任务类型")
    context: dict[str, Any] | None = Field(default=None, description="上下文信息")


class ABTestAssignResponse(BaseModel):
    """A/B测试分组响应"""
    task_id: str
    group: str  # "A" or "B"
    use_experience: bool


class ABTestOutcomeRequest(BaseModel):
    """A/B测试结果记录请求"""
    task_id: str = Field(..., description="任务ID")
    success: bool = Field(..., description="是否成功")
    execution_time_ms: int | None = Field(default=None, description="执行耗时(毫秒)")
    api_calls_count: int | None = Field(default=None, description="API调用次数")
    user_satisfaction: int | None = Field(default=None, ge=1, le=10, description="用户满意度")
    error_message: str | None = Field(default=None, description="错误信息")


class EffectivenessQueryRequest(BaseModel):
    """效果查询请求"""
    limit: int = Field(default=20, ge=1, le=100, description="返回数量限制")
    min_usage: int = Field(default=3, ge=1, description="最小使用次数")
    task_type: str | None = Field(default=None, description="任务类型过滤")


class PurgeExecuteRequest(BaseModel):
    """淘汰执行请求"""
    experience_ids: list[str] = Field(..., description="要处理的经验ID列表")
    action: str = Field(default="archive", description="操作类型")
    confirm: bool = Field(default=False, description="是否确认执行")


# ═══════════════════════════════════════════════════════════════════
# A/B测试 API
# ═══════════════════════════════════════════════════════════════════

@router.get("/ab-test/report")
async def get_ab_test_report(
    task_type: str | None = Query(default=None, description="任务类型过滤"),
    user_id: str = Depends(get_current_user)
):
    """
    获取A/B测试报告

    对比使用经验注入（A组）vs 不使用（B组）的效果差异
    """
    try:
        from core.experience_quantification.ab_test_framework import get_ab_test_framework

        ab_framework = get_ab_test_framework()
        metrics = ab_framework.get_metrics(task_type)
        report = ab_framework.get_comparison_report(task_type)

        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "report": report
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取A/B测试报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取报告失败: {str(e)}") from e


@router.post("/ab-test/assign")
async def assign_ab_test_group(
    data: ABTestAssignRequest,
    user_id: str = Depends(get_current_user)
):
    """
    为任务分配A/B测试分组

    返回分组信息，用于决定是否使用经验注入
    """
    try:
        from core.experience_quantification.ab_test_framework import ABTestGroup, get_ab_test_framework

        ab_framework = get_ab_test_framework()
        group, task_id = ab_framework.assign_group(
            task_description=data.task_description,
            task_type=data.task_type,
            user_id=user_id,
            context=data.context
        )

        return {
            "success": True,
            "task_id": task_id,
            "group": group.value,
            "use_experience": group == ABTestGroup.TREATMENT
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 分配A/B分组失败: {e}")
        raise HTTPException(status_code=500, detail=f"分配分组失败: {str(e)}") from e


@router.post("/ab-test/outcome")
async def record_ab_test_outcome(
    data: ABTestOutcomeRequest,
    user_id: str = Depends(get_current_user)
):
    """
    记录A/B测试任务结果

    更新相关统计数据
    """
    try:
        from core.experience_quantification.ab_test_framework import get_ab_test_framework

        ab_framework = get_ab_test_framework()
        ab_framework.record_outcome(
            task_id=data.task_id,
            success=data.success,
            execution_time_ms=data.execution_time_ms,
            api_calls_count=data.api_calls_count,
            user_satisfaction=data.user_satisfaction
        )

        return {
            "success": True,
            "message": "结果已记录"
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 记录A/B测试结果失败: {e}")
        raise HTTPException(status_code=500, detail=f"记录结果失败: {str(e)}") from e


@router.get("/ab-test/recent")
async def get_recent_ab_test_records(
    limit: int = Query(default=50, ge=1, le=100, description="返回数量"),
    task_type: str | None = Query(default=None, description="任务类型过滤"),
    user_id: str = Depends(get_current_user)
):
    """获取最近的A/B测试记录"""
    try:
        from core.experience_quantification.ab_test_framework import get_ab_test_framework

        ab_framework = get_ab_test_framework()
        records = ab_framework.get_recent_records(limit=limit, task_type=task_type)

        return {
            "success": True,
            "records": records,
            "total": len(records)
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取A/B测试记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 经验效果追踪 API
# ═══════════════════════════════════════════════════════════════════

@router.get("/effectiveness/global-stats")
async def get_global_effectiveness_stats(
    user_id: str = Depends(get_current_user)
):
    """
    获取经验效果全局统计

    包括总经验数、整体成功率、有效/无效经验数量等
    """
    try:
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker

        tracker = get_effectiveness_tracker()
        stats = tracker.get_global_stats()

        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取全局统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}") from e


@router.get("/effectiveness/leaderboard")
async def get_effectiveness_leaderboard(
    limit: int = Query(default=20, ge=1, le=100, description="返回数量限制"),
    min_usage: int = Query(default=3, ge=1, description="最小使用次数"),
    task_type: str | None = Query(default=None, description="任务类型过滤"),
    user_id: str = Depends(get_current_user)
):
    """
    获取经验效果排行榜

    按贡献度排序，展示最有效的经验
    """
    try:
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker

        tracker = get_effectiveness_tracker()
        leaderboard = tracker.get_effectiveness_leaderboard(
            limit=limit,
            min_usage=min_usage,
            task_type=task_type
        )

        return {
            "success": True,
            "leaderboard": leaderboard,
            "total": len(leaderboard)
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取排行榜失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取排行榜失败: {str(e)}") from e


@router.get("/effectiveness/{experience_id}")
async def get_experience_effectiveness(
    experience_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    获取单条经验的效果统计

    包括成功率、使用次数、贡献度等详细信息
    """
    try:
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker

        tracker = get_effectiveness_tracker()
        stats = tracker.get_experience_stats(experience_id)

        if stats is None:
            raise HTTPException(status_code=404, detail="经验未找到或无使用记录")

        return {
            "success": True,
            "experience_id": experience_id,
            "stats": stats.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取经验统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}") from e


@router.post("/effectiveness/track-usage")
async def track_experience_usage(
    experience_ids: list[str] = Body(..., description="经验ID列表"),
    task_id: str = Body(..., description="任务ID"),
    task_type: str = Body(default="general", description="任务类型"),
    user_id: str = Depends(get_current_user)
):
    """
    记录经验使用

    用于追踪哪些经验被用于当前任务
    """
    try:
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker

        tracker = get_effectiveness_tracker()
        tracker.track_batch_usage(
            experience_ids=experience_ids,
            task_id=task_id,
            task_type=task_type,
            user_id=user_id
        )

        return {
            "success": True,
            "message": f"已记录 {len(experience_ids)} 条经验使用"
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 记录经验使用失败: {e}")
        raise HTTPException(status_code=500, detail=f"记录使用失败: {str(e)}") from e


@router.post("/effectiveness/track-outcome")
async def track_task_outcome(
    task_id: str = Body(..., description="任务ID"),
    success: bool = Body(..., description="是否成功"),
    execution_time_ms: int | None = Body(default=None, description="执行耗时"),
    satisfaction: int | None = Body(default=None, ge=1, le=10, description="满意度"),
    user_id: str = Depends(get_current_user)
):
    """
    记录任务结果

    更新相关经验的效果统计
    """
    try:
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker

        tracker = get_effectiveness_tracker()
        tracker.track_outcome(
            task_id=task_id,
            success=success,
            execution_time_ms=execution_time_ms,
            satisfaction=satisfaction
        )

        return {
            "success": True,
            "message": "任务结果已记录"
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 记录任务结果失败: {e}")
        raise HTTPException(status_code=500, detail=f"记录结果失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 自动淘汰 API
# ═══════════════════════════════════════════════════════════════════

@router.get("/purge/candidates")
async def get_purge_candidates(
    user_id: str = Depends(get_current_user)
):
    """
    获取淘汰候选列表

    返回需要清理的低质量经验
    """
    try:
        from core.experience_quantification.auto_purge_engine import get_auto_purge_engine

        engine = get_auto_purge_engine(dry_run=True)
        candidates = await engine.scan_candidates()

        return {
            "success": True,
            "candidates": [c.to_dict() for c in candidates],
            "total": len(candidates)
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取淘汰候选失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取候选失败: {str(e)}") from e


@router.post("/purge/scan")
async def run_purge_scan(
    user_id: str = Depends(get_current_user)
):
    """
    运行淘汰扫描

    重新扫描并更新淘汰候选列表
    """
    try:
        from core.experience_quantification.auto_purge_engine import get_auto_purge_engine

        engine = get_auto_purge_engine(dry_run=True)
        candidates = engine.scan_candidates()

        return {
            "success": True,
            "candidates": [c.to_dict() for c in candidates],
            "total": len(candidates),
            "message": f"扫描完成，发现 {len(candidates)} 个候选"
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 运行淘汰扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}") from e


@router.post("/purge/execute")
async def execute_purge(
    data: PurgeExecuteRequest,
    user_id: str = Depends(get_current_user)
):
    """
    执行淘汰操作

    对指定的经验执行淘汰/归档/删除等操作
    """
    try:
        from core.experience_quantification.auto_purge_engine import PurgeAction, PurgeCandidate, get_auto_purge_engine

        engine = get_auto_purge_engine(dry_run=not data.confirm)

        # 构建候选列表
        candidates = [
            PurgeCandidate(
                experience_id=exp_id,
                reason="手动执行淘汰",
                reason_code="MANUAL_PURGE",
                success_rate=0.0,
                usage_count=0,
                recommended_action=PurgeAction(data.action)
            )
            for exp_id in data.experience_ids
        ]

        results = engine.execute_purge(candidates, auto_confirm=data.confirm)

        return {
            "success": True,
            "results": [r.to_dict() for r in results],
            "dry_run": not data.confirm,
            "message": f"已处理 {len(results)} 条经验"
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 执行淘汰失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行淘汰失败: {str(e)}") from e


@router.get("/purge/report")
async def get_purge_report(
    days: int = Query(default=30, ge=1, le=365, description="统计天数"),
    user_id: str = Depends(get_current_user)
):
    """
    获取淘汰报告

    展示最近的淘汰操作记录和统计
    """
    try:
        from core.experience_quantification.auto_purge_engine import get_auto_purge_engine

        engine = get_auto_purge_engine(dry_run=True)
        report = engine.get_purge_report(days=days)

        return {
            "success": True,
            "report": report
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取淘汰报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取报告失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 综合仪表盘 API
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_experience_dashboard(
    user_id: str = Depends(get_current_user)
):
    """
    获取经验量化综合仪表盘数据

    聚合所有关键指标，用于前端仪表盘展示
    """
    try:
        # 获取A/B测试数据
        from core.experience_quantification.ab_test_framework import get_ab_test_framework
        ab_framework = get_ab_test_framework()
        ab_metrics = ab_framework.get_metrics()

        # 获取效果统计
        from core.experience_quantification.experience_effectiveness_tracker import get_effectiveness_tracker
        tracker = get_effectiveness_tracker()
        global_stats = tracker.get_global_stats()
        leaderboard = tracker.get_effectiveness_leaderboard(limit=10)

        # 获取淘汰数据
        from core.experience_quantification.auto_purge_engine import get_auto_purge_engine
        purge_engine = get_auto_purge_engine(dry_run=True)
        purge_candidates = await purge_engine.scan_candidates()

        # 计算关键指标
        has_enough_data = ab_metrics.total_tasks >= 10
        experience_effective = has_enough_data and ab_metrics.success_rate_lift > 0.05

        return {
            "success": True,
            "summary": {
                "total_experiences": global_stats.get("total_experiences", 0),
                "total_usage": global_stats.get("total_usage", 0),
                "overall_success_rate": global_stats.get("overall_success_rate", 0),
                "ab_test_samples": ab_metrics.total_tasks,
                "has_enough_data": has_enough_data,
                "experience_effective": experience_effective,
                "success_rate_lift": ab_metrics.success_rate_lift if has_enough_data else None
            },
            "ab_test": ab_metrics.to_dict() if has_enough_data else None,
            "leaderboard": leaderboard,
            "purge_candidates_count": len(purge_candidates),
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[ExperienceAPI] 获取仪表盘数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取仪表盘失败: {str(e)}") from e
