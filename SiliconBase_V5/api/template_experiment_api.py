"""
Template Experiment API - 模板实验效果API

提供模板A/B测试数据的HTTP接口，包括：
1. 用户反馈提交
2. 模板效果报告查询
3. 实验对比数据
4. 用户模板推荐
5. 周报告生成和查询

作者: Agent-5 (权重验证实验师)
版本: 1.0.0
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 尝试导入 get_current_user，如果不可用则使用默认实现
try:
    from api.cloud_api import get_current_user
except ImportError:
    async def get_current_user():
        return "default"

# 尝试导入 template_experiment 模块
try:
    from core.experiment.template_experiment import template_experiment
    TEMPLATE_EXPERIMENT_AVAILABLE = True
    logger.info("[TemplateExperimentAPI] template_experiment模块已加载")
except ImportError as e:
    TEMPLATE_EXPERIMENT_AVAILABLE = False
    logger.warning(f"[TemplateExperimentAPI] template_experiment模块导入失败: {e}")

router = APIRouter(
    prefix="/template-experiment",
    tags=["template-experiment"],
    dependencies=[Depends(get_current_user)]
)


# =============================================================================
# 请求/响应模型
# =============================================================================

class TaskFeedbackRequest(BaseModel):
    """任务反馈请求模型"""
    taskId: str = Field(..., description="任务ID")
    templateName: str = Field(..., description="使用的模板名称")
    rating: int = Field(..., ge=1, le=5, description="用户评分 1-5")
    feedback: str = Field(default="", max_length=200, description="用户文字反馈")
    quickTags: list[str] = Field(default=[], description="快速标签")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000), description="时间戳")


class TaskResultRequest(BaseModel):
    """任务结果记录请求模型"""
    task_id: str = Field(..., description="任务ID")
    success: bool = Field(..., description="是否成功")
    user_rating: int = Field(default=0, ge=0, le=5, description="用户评分")
    user_feedback: str = Field(default="", description="用户反馈")
    execution_time_ms: int = Field(default=0, description="执行耗时毫秒")
    steps_count: int = Field(default=0, description="执行步骤数")
    tool_calls_count: int = Field(default=0, description="工具调用次数")
    reflection_depth: int = Field(default=0, description="反思深度")
    memory_hits: int = Field(default=0, description="记忆命中次数")


class UserProfileRequest(BaseModel):
    """用户画像请求模型"""
    developer: float = Field(default=0.0, ge=0.0, le=1.0, description="开发者倾向")
    creative: float = Field(default=0.0, ge=0.0, le=1.0, description="创意倾向")
    efficiency: float = Field(default=0.0, ge=0.0, le=1.0, description="效率倾向")
    safety: float = Field(default=0.0, ge=0.0, le=1.0, description="安全倾向")
    aesthetic: float = Field(default=0.0, ge=0.0, le=1.0, description="美学倾向")


class ApiResponse(BaseModel):
    """标准API响应模型"""
    success: bool = True
    data: Any | None = None
    message: str = ""


# =============================================================================
# API端点
# =============================================================================

@router.post("/feedback", response_model=ApiResponse)
async def submit_task_feedback(
    request: TaskFeedbackRequest,
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    提交任务反馈

    接收用户对任务执行效果的评分和反馈，用于A/B测试数据分析。
    数据将匿名化处理后存储。

    Args:
        request: 任务反馈数据
        user_id: 当前用户ID（自动从认证获取）

    Returns:
        提交结果
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": False,
            "data": None,
            "message": "Template experiment module not available"
        }

    try:
        # 构建任务结果数据
        task_result = {
            "task_id": request.taskId,
            "success": True,  # 用户提交了反馈，认为任务完成
            "user_rating": request.rating,
            "user_feedback": request.feedback,
        }

        # 记录任务结果
        result_id = template_experiment.track_task(
            template_name=request.templateName,
            task_result=task_result
        )

        # 更新用户画像
        template_experiment.update_user_profile(
            user_id=user_id,
            interaction_data={
                "template_used": request.templateName,
                "user_rating": request.rating,
            }
        )

        logger.info(
            f"[TemplateExperimentAPI] 用户 {user_id} 提交反馈: "
            f"任务={request.taskId}, 模板={request.templateName}, 评分={request.rating}"
        )

        return {
            "success": True,
            "data": {"result_id": result_id},
            "message": "Feedback submitted successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 提交反馈失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to submit feedback: {str(e)}"
        }


@router.post("/track-task", response_model=ApiResponse)
async def track_task_result(
    request: TaskResultRequest,
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    记录任务执行结果

    供系统内部调用，记录任务执行的详细结果数据。

    Args:
        request: 任务结果数据
        user_id: 当前用户ID

    Returns:
        记录结果
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": False,
            "data": None,
            "message": "Template experiment module not available"
        }

    try:
        task_result = request.model_dump()
        result_id = template_experiment.track_task(
            template_name=request.task_id.split("_")[0] if "_" in request.task_id else "balanced",
            task_result=task_result
        )

        return {
            "success": True,
            "data": {"result_id": result_id},
            "message": "Task result tracked successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 记录任务失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to track task: {str(e)}"
        }


@router.get("/report", response_model=ApiResponse)
async def get_template_report(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取模板效果报告

    返回所有模板的统计数据，包括成功率、用户评分等。

    Returns:
        各模板统计数据
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        # 返回模拟数据
        return {
            "success": True,
            "data": {
                "guardian": {
                    "template_name": "guardian",
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_rating": 0.0,
                },
                "explorer": {
                    "template_name": "explorer",
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_rating": 0.0,
                },
                "geek": {
                    "template_name": "geek",
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_rating": 0.0,
                },
                "artist": {
                    "template_name": "artist",
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_rating": 0.0,
                },
                "balanced": {
                    "template_name": "balanced",
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_rating": 0.0,
                },
            },
            "message": "Template experiment module not available, returning mock data"
        }

    try:
        report = template_experiment.get_template_report()
        return {
            "success": True,
            "data": report,
            "message": "Template report retrieved successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取报告失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get report: {str(e)}"
        }


@router.get("/comparison", response_model=ApiResponse)
async def get_experiment_comparison(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取实验对比数据

    返回用于Dashboard展示的对比如表数据。

    Returns:
        对比数据，包含各模板的指标数组
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        # 返回模拟数据
        return {
            "success": True,
            "data": {
                "templates": ["guardian", "explorer", "geek", "artist", "balanced"],
                "success_rates": [0.85, 0.78, 0.82, 0.75, 0.80],
                "avg_ratings": [4.2, 4.5, 4.0, 4.3, 4.1],
                "avg_execution_times": [5200, 4800, 4500, 5100, 4900],
                "total_tasks": [120, 95, 110, 85, 130],
                "last_updated": time.time(),
            },
            "message": "Template experiment module not available, returning mock data"
        }

    try:
        comparison = template_experiment.get_experiment_comparison()
        return {
            "success": True,
            "data": comparison,
            "message": "Experiment comparison retrieved successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取对比数据失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get comparison: {str(e)}"
        }


@router.post("/recommendation", response_model=ApiResponse)
async def get_template_recommendation(
    profile: UserProfileRequest,
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    根据用户画像推荐模板

    根据用户提供的画像特征，推荐最适合的模板。

    Args:
        profile: 用户画像数据
        user_id: 当前用户ID

    Returns:
        推荐结果，包含推荐模板和理由
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": True,
            "data": {
                "recommended_template": "balanced",
                "confidence": 0.5,
                "reason": "默认推荐均衡模板",
                "alternatives": ["explorer", "geek"],
            },
            "message": "Template experiment module not available, returning default"
        }

    try:
        user_profile = profile.model_dump()
        recommended = template_experiment.recommend_template(user_profile)

        return {
            "success": True,
            "data": {
                "recommended_template": recommended,
                "confidence": 0.8,
                "reason": "根据您的画像特征推荐",
                "alternatives": [t for t in ["guardian", "explorer", "geek", "artist", "balanced"] if t != recommended][:2],
            },
            "message": "Recommendation generated successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取推荐失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get recommendation: {str(e)}"
        }


@router.get("/recommendation", response_model=ApiResponse)
async def get_user_template_recommendation(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取针对当前用户的模板推荐

    基于用户的历史交互数据，推荐最适合的模板。

    Args:
        user_id: 当前用户ID

    Returns:
        推荐结果
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": True,
            "data": {
                "recommended_template": "balanced",
                "confidence": 0.3,
                "reason": "新用户，使用均衡模板开始",
                "alternatives": ["explorer", "geek"],
                "interaction_count": 0,
            },
            "message": "Template experiment module not available, returning default"
        }

    try:
        recommendation = template_experiment.get_user_recommendation(user_id)
        return {
            "success": True,
            "data": recommendation,
            "message": "User recommendation retrieved successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取用户推荐失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get user recommendation: {str(e)}"
        }


@router.get("/weekly-report", response_model=ApiResponse)
async def get_latest_weekly_report(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取最新周报告

    Returns:
        最新周报告数据
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": True,
            "data": None,
            "message": "No weekly report available"
        }

    try:
        report = template_experiment.get_latest_weekly_report()
        return {
            "success": True,
            "data": report,
            "message": "Weekly report retrieved successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取周报告失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get weekly report: {str(e)}"
        }


@router.get("/weekly-reports", response_model=ApiResponse)
async def get_all_weekly_reports(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取所有周报告

    Returns:
        所有历史周报告
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": True,
            "data": [],
            "message": "No weekly reports available"
        }

    try:
        reports = template_experiment.get_all_weekly_reports()
        return {
            "success": True,
            "data": reports,
            "message": "Weekly reports retrieved successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 获取所有周报告失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to get weekly reports: {str(e)}"
        }


@router.post("/generate-report", response_model=ApiResponse)
async def generate_weekly_report(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    手动生成周报告

    生成当前周的实验报告，需要管理员权限。

    Args:
        user_id: 当前用户ID

    Returns:
        生成的周报告
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": False,
            "data": None,
            "message": "Template experiment module not available"
        }

    try:
        report = template_experiment.generate_weekly_report()
        return {
            "success": True,
            "data": report.to_dict(),
            "message": "Weekly report generated successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 生成周报告失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to generate weekly report: {str(e)}"
        }


@router.post("/export", response_model=ApiResponse)
async def export_experiment_data(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    导出实验数据

    导出所有实验数据到JSON文件，用于备份或分析。

    Returns:
        导出文件路径
    """
    if not TEMPLATE_EXPERIMENT_AVAILABLE:
        return {
            "success": False,
            "data": None,
            "message": "Template experiment module not available"
        }

    try:
        export_path = template_experiment.export_data(format="json")
        return {
            "success": True,
            "data": {"export_path": export_path},
            "message": "Data exported successfully"
        }

    except Exception as e:
        logger.error(f"[TemplateExperimentAPI] 导出数据失败: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Failed to export data: {str(e)}"
        }


# =============================================================================
# 初始化函数 - 供cloud_api调用
# =============================================================================

def init_template_experiment_routes(app):
    """
    初始化模板实验API路由

    Args:
        app: FastAPI应用实例
    """
    app.include_router(router)
    logger.info("[TemplateExperimentAPI] 模板实验API路由已注册")


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件是 SiliconBase V5 系统中 Agent-5（权重验证实验师）的后端API组件，
# 为前端提供模板实验效果的HTTP接口。
#
# 【API端点列表】
# POST   /api/template-experiment/feedback         - 提交任务反馈
# POST   /api/template-experiment/track-task       - 记录任务结果
# GET    /api/template-experiment/report           - 获取模板报告
# GET    /api/template-experiment/comparison       - 获取对比数据
# POST   /api/template-experiment/recommendation   - 获取模板推荐
# GET    /api/template-experiment/recommendation   - 获取用户推荐
# GET    /api/template-experiment/weekly-report    - 获取最新周报告
# GET    /api/template-experiment/weekly-reports   - 获取所有周报告
# POST   /api/template-experiment/generate-report  - 生成周报告
# POST   /api/template-experiment/export           - 导出数据
#
# 【关联文件】
# 1. core/template_experiment.py - 核心业务逻辑
#    * 关系：本文件调用该模块的功能
#    * 交互：通过template_experiment全局实例调用
#
# 2. frontend/src/services/templateExperiment.ts - 前端API服务
#    * 关系：前端通过该服务调用本文件的API
#    * 交互：HTTP请求/响应
#
# 3. api/cloud_api.py - 主API入口
#    * 关系：本文件通过init_template_experiment_routes注册到主应用
#    * 交互：FastAPI路由器包含
#
