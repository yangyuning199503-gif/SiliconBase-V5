#!/usr/bin/env python3
"""
RLHF 反馈 API 路由

提供用户反馈收集接口：
- 对话回复反馈（点赞/点踩）
- 任务执行反馈
- RLHF 统计信息查询

Author: SiliconBase V5
Version: 1.0.0
"""

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.evolution.experience_rlhf_bridge import (
    apply_feedback_to_experiences,
    get_exp_rlhf_bridge,
    record_exp_usage_for_response,
)
from core.evolution.rlhf_feedback import FeedbackType, collect_quick_feedback, rlhf_collector
from core.logger import logger

# 尝试导入认证依赖
try:
    from api.dependencies import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def get_current_user():
        return None

router = APIRouter(prefix="/rlhf", tags=["RLHF反馈"])


# =============================================================================
# 请求/响应模型
# =============================================================================

class ResponseFeedbackRequest(BaseModel):
    """对话回复反馈请求"""
    response_id: str = Field(..., description="回复唯一ID")
    feedback_type: Literal["thumbs_up", "thumbs_down"] = Field(..., description="反馈类型")
    comment: str | None = Field(None, max_length=200, description="可选评论")
    conversation_id: str | None = Field(None, description="对话ID")
    prompt_text: str | None = Field(None, description="原始提示词（用于DPO训练）")
    response_text: str | None = Field(None, description="AI回复内容（用于DPO训练）")


class TaskFeedbackRequest(BaseModel):
    """任务执行反馈请求"""
    task_id: str = Field(..., description="任务唯一ID")
    outcome: Literal["success", "failure", "partial", "cancelled"] = Field(..., description="任务结果")
    score: int | None = Field(None, ge=1, le=5, description="用户评分 1-5")
    comment: str | None = Field(None, max_length=500, description="用户评论")
    execution_steps: list | None = Field(None, description="执行步骤记录")
    duration: float | None = Field(None, description="执行耗时（秒）")


class ExperienceUsageRequest(BaseModel):
    """经验使用记录请求"""
    response_id: str = Field(..., description="回复ID")
    exp_ids: list[str] = Field(..., description="经验ID列表")
    task_hash: str | None = Field(None, description="任务哈希")


class FeedbackResponse(BaseModel):
    """反馈响应"""
    success: bool
    feedback_id: str | None = None
    message: str
    exp_adjustments: dict[str, Any] | None = None


class RLHFStatsResponse(BaseModel):
    """RLHF统计响应"""
    enabled: bool
    response_feedback: dict[str, Any]
    task_feedback: dict[str, Any]
    dpo_pairs: dict[str, Any]
    timeline: dict[str, Any]
    exp_weights: dict[str, Any]
    satisfaction_rate: float | None = None


# =============================================================================
# API 端点
# =============================================================================

@router.post("/feedback/response", response_model=FeedbackResponse)
async def submit_response_feedback(
    request: ResponseFeedbackRequest,
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    提交对话回复反馈（点赞/点踩）

    - 记录用户对AI回复的满意度
    - 自动关联到使用的经验并调整权重
    - 生成DPO训练数据
    """
    try:
        # 转换反馈类型
        feedback_type = (
            FeedbackType.THUMBS_UP
            if request.feedback_type == "thumbs_up"
            else FeedbackType.THUMBS_DOWN
        )

        # 获取用户ID
        user_id = current_user.get("id") if current_user else "anonymous"

        # 收集反馈
        feedback_id = rlhf_collector.collect_response_feedback(
            response_id=request.response_id,
            feedback_type=feedback_type,
            user_comment=request.comment,
            conversation_id=request.conversation_id,
            prompt_text=request.prompt_text,
            response_text=request.response_text,
            metadata={
                "user_id": user_id,
                "source": "web_ui",
                "timestamp": time.time()
            }
        )

        if not feedback_id:
            return FeedbackResponse(
                success=False,
                message="RLHF系统未启用，请在配置中设置 features.rlhf: true"
            )

        # 应用到经验权重
        exp_result = apply_feedback_to_experiences(
            request.response_id,
            feedback_type,
            feedback_id
        )

        logger.info(
            f"[RLHF API] 用户 {user_id} 对回复 {request.response_id} "
            f"给出{'👍' if request.feedback_type == 'thumbs_up' else '👎'}反馈"
        )

        return FeedbackResponse(
            success=True,
            feedback_id=feedback_id,
            message=exp_result.get("message", "反馈已记录"),
            exp_adjustments={
                "affected_count": exp_result.get("affected_experiences", 0),
                "adjustments": exp_result.get("weight_adjustments", [])
            }
        )

    except Exception as e:
        logger.error(f"[RLHF API] 提交反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"提交反馈失败: {str(e)}") from e


@router.post("/feedback/task", response_model=FeedbackResponse)
async def submit_task_feedback(
    request: TaskFeedbackRequest,
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    提交任务执行反馈

    - 记录任务执行的成功/失败结果
    - 用于评估经验效果
    - 生成任务级DPO训练数据
    """
    try:
        from core.evolution.rlhf_feedback import TaskOutcome

        # 转换结果类型
        outcome_map = {
            "success": TaskOutcome.SUCCESS,
            "failure": TaskOutcome.FAILURE,
            "partial": TaskOutcome.PARTIAL,
            "cancelled": TaskOutcome.CANCELLED
        }
        outcome_map.get(request.outcome, TaskOutcome.FAILURE)

        # 获取用户ID
        user_id = current_user.get("id") if current_user else "anonymous"

        # 收集反馈
        feedback_id = rlhf_collector.collect_task_feedback(
            task_id=request.task_id,
            success=request.outcome == "success",
            feedback_score=request.score,
            user_comment=request.comment,
            execution_steps=request.execution_steps or [],
            duration=request.duration,
            metadata={
                "user_id": user_id,
                "source": "web_ui",
                "timestamp": time.time()
            }
        )

        if not feedback_id:
            return FeedbackResponse(
                success=False,
                message="RLHF系统未启用"
            )

        logger.info(
            f"[RLHF API] 用户 {user_id} 对任务 {request.task_id} "
            f"给出 {request.outcome} 评价"
        )

        return FeedbackResponse(
            success=True,
            feedback_id=feedback_id,
            message="任务评价已记录，感谢反馈！"
        )

    except Exception as e:
        logger.error(f"[RLHF API] 提交任务反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"提交任务反馈失败: {str(e)}") from e


@router.post("/experience/usage")
async def record_experience_usage(
    request: ExperienceUsageRequest,
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    记录AI回复使用的经验

    由后端在生成回复时调用，记录哪些经验被用于生成当前回复。
    用于后续反馈时关联到具体经验。
    """
    try:
        record_exp_usage_for_response(
            response_id=request.response_id,
            exp_ids=request.exp_ids,
            task_hash=request.task_hash
        )

        return {
            "success": True,
            "message": f"已记录 {len(request.exp_ids)} 条经验使用"
        }

    except Exception as e:
        logger.error(f"[RLHF API] 记录经验使用失败: {e}")
        raise HTTPException(status_code=500, detail=f"记录失败: {str(e)}") from e


@router.get("/stats", response_model=RLHFStatsResponse)
async def get_rlhf_stats(
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    获取RLHF系统统计信息

    包括：
    - 反馈收集统计
    - DPO数据对数量
    - 经验权重调整情况
    - 时间线统计
    """
    try:
        # 获取基础反馈统计
        stats = rlhf_collector.get_feedback_stats()

        # 获取经验权重统计
        bridge = get_exp_rlhf_bridge()
        exp_stats = bridge.get_weight_stats()

        return RLHFStatsResponse(
            enabled=stats.get("enabled", False),
            response_feedback=stats.get("response_feedback", {}),
            task_feedback=stats.get("task_feedback", {}),
            dpo_pairs=stats.get("dpo_pairs", {}),
            timeline=stats.get("timeline", {}),
            exp_weights=exp_stats,
            satisfaction_rate=stats.get("satisfaction_rate")
        )

    except Exception as e:
        logger.error(f"[RLHF API] 获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}") from e


@router.get("/recent")
async def get_recent_feedback(
    limit: int = 10,
    feedback_type: Literal["response", "task"] | None = "response",
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    获取最近的反馈记录

    用于前端展示最近的反馈历史。
    """
    try:
        recent = rlhf_collector.get_recent_feedback(
            feedback_type=feedback_type or "response",
            limit=limit
        )

        return {
            "success": True,
            "data": recent,
            "count": len(recent)
        }

    except Exception as e:
        logger.error(f"[RLHF API] 获取最近反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}") from e


@router.post("/admin/export-dpo")
async def export_dpo_dataset(
    output_path: str | None = None,
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    导出DPO训练数据集（管理员接口）

    将收集的反馈导出为标准DPO格式，用于模型训练。
    """
    try:
        # 检查权限（简化处理，实际应使用权限系统）
        if current_user and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="权限不足")

        file_path = rlhf_collector.export_dpo_dataset(output_path)

        return {
            "success": True,
            "file_path": file_path,
            "message": f"DPO数据集已导出到 {file_path}"
        }

    except Exception as e:
        logger.error(f"[RLHF API] 导出DPO数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}") from e


# =============================================================================
# 便捷端点
# =============================================================================

@router.post("/quick-feedback")
async def quick_feedback(
    response_id: str,
    is_positive: bool,
    comment: str | None = None,
    current_user: dict | None = Depends(get_current_user) if AUTH_AVAILABLE else None
):
    """
    快速反馈接口（简化版）

    用于快速提交点赞/点踩，无需完整参数。
    """
    try:
        feedback_type = FeedbackType.THUMBS_UP if is_positive else FeedbackType.THUMBS_DOWN

        feedback_id = collect_quick_feedback(
            response_id=response_id,
            is_positive=is_positive,
            comment=comment or ""
        )

        if feedback_id:
            # 应用到经验
            exp_result = apply_feedback_to_experiences(response_id, feedback_type, feedback_id)

            return {
                "success": True,
                "feedback_id": feedback_id,
                "message": exp_result.get("message", "反馈已记录")
            }
        else:
            return {
                "success": False,
                "message": "RLHF系统未启用"
            }

    except Exception as e:
        logger.error(f"[RLHF API] 快速反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"反馈失败: {str(e)}") from e


# =============================================================================
# 模块测试
# =============================================================================

if __name__ == "__main__":
    print("=== RLHF API Routes 测试 ===")
    print("本模块为FastAPI路由，请通过HTTP请求测试")
    print("可用端点:")
    print("  POST /rlhf/feedback/response - 提交回复反馈")
    print("  POST /rlhf/feedback/task - 提交任务反馈")
    print("  POST /rlhf/experience/usage - 记录经验使用")
    print("  GET  /rlhf/stats - 获取统计信息")
    print("  GET  /rlhf/recent - 获取最近反馈")
    print("  POST /rlhf/quick-feedback - 快速反馈")
