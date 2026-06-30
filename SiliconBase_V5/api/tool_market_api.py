#!/usr/bin/env python3
"""
本地工具市场 API
提供本地客户端访问云端工具市场的接口

作者: SiliconBase Team
版本: 1.0.0
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

# 导入认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

    async def get_current_user() -> str | None:
        return "default_user"

# 导入工具市场客户端
try:
    from core.tool.tool_market_client import InstallStatus, tool_market_client
    TOOL_MARKET_AVAILABLE = True
except ImportError:
    TOOL_MARKET_AVAILABLE = False
    tool_market_client = None

# 导入日志
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tool-market", tags=["tool-market"])

# ============================================================================
# 数据模型
# ============================================================================

class InstallRequest(BaseModel):
    """安装请求"""
    tool_id: str = Field(..., description="工具ID")
    version: str = Field(default="latest", description="版本号")


class InstallResponse(BaseModel):
    """安装响应"""
    success: bool
    task_id: str
    message: str


class TaskResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    tool_id: str
    version: str
    status: str
    progress: int
    message: str
    error: str | None = None


class InstalledToolResponse(BaseModel):
    """已安装工具响应"""
    tool_id: str
    name: str
    version: str
    description: str
    author: str
    category: str
    install_date: str
    source: str
    auto_update: bool


class UpdatesResponse(BaseModel):
    """更新列表响应"""
    updates: list[dict[str, Any]]
    count: int


# ============================================================================
# API端点
# ============================================================================

@router.post("/install", response_model=InstallResponse)
async def install_tool(
    request: InstallRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """
    安装云端工具

    - **tool_id**: 工具ID
    - **version**: 版本号（默认最新）
    """
    if not TOOL_MARKET_AVAILABLE:
        raise HTTPException(503, "工具市场客户端未初始化")

    try:
        # 创建安装任务
        task = await tool_market_client.install_tool(
            request.tool_id,
            request.version
        )

        return InstallResponse(
            success=task.status != InstallStatus.FAILED,
            task_id=task.task_id,
            message=task.message or "安装任务已创建"
        )

    except Exception as e:
        logger.error(f"[ToolMarketAPI] 安装工具失败: {e}")
        raise HTTPException(500, f"安装失败: {str(e)}") from e


@router.get("/task/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user)
):
    """获取安装任务状态"""
    if not TOOL_MARKET_AVAILABLE:
        raise HTTPException(503, "工具市场客户端未初始化")

    task = tool_market_client.get_install_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    return TaskResponse(
        task_id=task.task_id,
        tool_id=task.tool_id,
        version=task.version,
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        error=task.error
    )


@router.get("/installed", response_model=list[InstalledToolResponse])
async def get_installed_tools(
    user_id: str = Depends(get_current_user)
):
    """获取已安装工具列表"""
    if not TOOL_MARKET_AVAILABLE:
        return []

    tools = tool_market_client.get_installed_tools()
    return [
        InstalledToolResponse(
            tool_id=t.tool_id,
            name=t.name,
            version=t.version,
            description=t.description,
            author=t.author,
            category=t.category,
            install_date=t.install_date.isoformat(),
            source=t.source,
            auto_update=t.auto_update
        )
        for t in tools
    ]


@router.post("/uninstall/{tool_id}")
async def uninstall_tool_endpoint(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """卸载工具"""
    if not TOOL_MARKET_AVAILABLE:
        raise HTTPException(503, "工具市场客户端未初始化")

    success = await tool_market_client.uninstall_tool(tool_id)
    if not success:
        raise HTTPException(500, "卸载失败")

    return {
        "success": True,
        "message": f"工具 {tool_id} 已卸载"
    }


@router.post("/update/{tool_id}")
async def update_tool_endpoint(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """更新工具到最新版本"""
    if not TOOL_MARKET_AVAILABLE:
        raise HTTPException(503, "工具市场客户端未初始化")

    try:
        task = await tool_market_client.update_tool(tool_id)
        return {
            "success": task.status != InstallStatus.FAILED,
            "task_id": task.task_id,
            "status": task.status.value,
            "message": task.message
        }
    except Exception as e:
        raise HTTPException(500, f"更新失败: {str(e)}") from e


@router.post("/check-updates", response_model=UpdatesResponse)
async def check_updates_endpoint(
    user_id: str = Depends(get_current_user)
):
    """检查已安装工具的更新"""
    if not TOOL_MARKET_AVAILABLE:
        return UpdatesResponse(updates=[], count=0)

    updates = await tool_market_client.check_updates()
    return UpdatesResponse(
        updates=updates,
        count=len(updates)
    )


@router.post("/auto-update")
async def auto_update_all_endpoint(
    user_id: str = Depends(get_current_user)
):
    """自动更新所有可更新的工具"""
    if not TOOL_MARKET_AVAILABLE:
        raise HTTPException(503, "工具市场客户端未初始化")

    tasks = await tool_market_client.auto_update_all()
    return {
        "success": True,
        "tasks": [
            {
                "task_id": t.task_id,
                "tool_id": t.tool_id,
                "version": t.version,
                "status": t.status.value
            }
            for t in tasks
        ],
        "count": len(tasks)
    }


@router.get("/is-installed/{tool_id}")
async def is_tool_installed(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """检查工具是否已安装"""
    if not TOOL_MARKET_AVAILABLE:
        return {"installed": False}

    installed = tool_market_client.is_installed(tool_id)
    info = tool_market_client.get_installed_tool(tool_id) if installed else None

    return {
        "installed": installed,
        "version": info.version if info else None
    }


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    'router',
    'InstallRequest',
    'InstallResponse',
    'TaskResponse',
    'InstalledToolResponse',
    'UpdatesResponse'
]
