#!/usr/bin/env python3
"""
统计API路由 - SiliconBase V5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 失败统计数据查询
  ✓ 每日报告生成
  ✓ 失败记录（供AgentLoop调用）

Author: SiliconBase Team
"""

import logging
from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# 导入失败分析模块
try:
    from core.monitoring.failure_analytics import failure_analytics
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False
    logging.warning("[StatsAPI] FailureAnalytics 模块不可用")

router = APIRouter(prefix="/stats", tags=["statistics"])


# ========== CamelCase基类 ==========

class CamelCaseModel(BaseModel):
    """自动将snake_case字段转换为camelCase的Pydantic模型基类"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


T = TypeVar('T')

class ResponseWrapper(CamelCaseModel, Generic[T]):
    """统一API响应包装器"""
    success: bool = True
    data: T | None = None
    message: str | None = None
    error: str | None = None


# ========== 请求/响应模型 ==========

class RecordFailureRequest(CamelCaseModel):
    """记录失败请求模型"""
    task_type: str
    task_name: str
    root_cause: str = Field(..., description="1=提示词, 2=工具选择, 3=参数配置, 4=缺少技能, 5=其他")
    confidence: float = Field(..., ge=0, le=1)
    explanation: str
    prompt_version: str
    suggested_fix: str | None = None
    prompt_patch: str | None = None


class RecordFailureResponse(CamelCaseModel):
    """记录失败响应模型"""
    success: bool
    id: str | None = None
    warning: str | None = None


class FailureStatsData(CamelCaseModel):
    """失败统计数据"""
    period_days: int = 0
    total_failures: int = 0
    by_cause: dict[str, Any] = {}
    by_version: dict[str, Any] = {}
    top_failing_tasks: list = []
    generated_at: str = ""
    message: str | None = None  # 无数据时的提示消息


class HealthCheckResponse(CamelCaseModel):
    """健康检查响应"""
    success: bool
    analytics_available: bool
    timestamp: str


# ========== API端点 ==========

@router.get("/failures", response_model=ResponseWrapper[FailureStatsData])
async def get_failure_stats(days: int = Query(default=7, ge=1, le=90)):
    """
    获取失败统计数据

    Args:
        days: 统计天数（1-90天）

    Returns:
        失败统计报告（自动转换为camelCase）
    """
    if not ANALYTICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="失败分析模块不可用")

    try:
        stats = failure_analytics.get_stats(days=days)

        # 处理无数据情况
        # 返回空数据但包含消息，否则展开统计字段
        response_data = FailureStatsData(message=stats["message"]) if "message" in stats else FailureStatsData(**stats)

        return ResponseWrapper(success=True, data=response_data)
    except Exception as e:
        logging.error(f"[StatsAPI] 获取失败统计失败: {e}")
        # 返回空数据而不是抛出异常
        return ResponseWrapper(
            success=True,
            data=FailureStatsData(message=f"获取统计失败: {str(e)}"),
            warning=str(e)
        )


@router.get("/daily-report", response_model=ResponseWrapper[dict[str, str]])
async def generate_daily_report():
    """
    生成每日失败分析报告

    Returns:
        Markdown格式的分析报告
    """
    if not ANALYTICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="失败分析模块不可用")

    try:
        report = failure_analytics.generate_daily_report()
        return ResponseWrapper(success=True, data={"report": report})
    except Exception as e:
        logging.error(f"[StatsAPI] 生成每日报告失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/record-failure", response_model=RecordFailureResponse)
async def record_failure(request: RecordFailureRequest):
    """
    记录一次失败（供AgentLoop调用）

    Args:
        request: 失败记录数据

    Returns:
        记录ID
    """
    if not ANALYTICS_AVAILABLE:
        return RecordFailureResponse(
            success=False,
            warning="失败分析模块不可用",
            id=None
        )

    try:
        record_id = failure_analytics.record_failure(
            task_type=request.task_type,
            task_name=request.task_name,
            root_cause=request.root_cause,
            confidence=request.confidence,
            explanation=request.explanation,
            prompt_version=request.prompt_version,
            suggested_fix=request.suggested_fix,
            prompt_patch=request.prompt_patch
        )
        return RecordFailureResponse(success=True, id=record_id)
    except Exception as e:
        logging.error(f"[StatsAPI] 记录失败失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """健康检查"""
    return HealthCheckResponse(
        success=True,
        analytics_available=ANALYTICS_AVAILABLE,
        timestamp=datetime.now().isoformat()
    )
