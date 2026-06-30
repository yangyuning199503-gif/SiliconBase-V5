"""
弱连接系统API路由
处理弱连接提议的接受和配置
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.weak_connection import get_weak_connection_engine
from core.work_mode_manager import get_work_mode_manager

router = APIRouter(prefix="/weak-connection", tags=["weak-connection"])
logger = logging.getLogger(__name__)


class AcceptProposalRequest(BaseModel):
    anchor_id: str
    message: str


class WeakConnectionConfig(BaseModel):
    enabled: bool = True
    daily_mode_only: bool = True
    cooldown_minutes: int = 10
    session_min_interval: int = 300  # 5分钟
    auto_hide_seconds: int = 30


@router.post("/accept")
async def accept_proposal(request: AcceptProposalRequest):
    """
    用户接受弱连接提议
    切换为Focus模式，恢复锚点上下文，创建任务

    【P1-修复】统一调用 WeakConnectionEngine.accept_proposal()，
    确保反馈闭环（表达引擎 update_drive）被正确触发。
    """
    try:
        weak_connection_engine = get_weak_connection_engine()
        result = weak_connection_engine.accept_proposal(
            anchor_id=request.anchor_id,
            message=request.message
        )
        return {
            "success": True,
            "message": "已接受提议，切换到专注模式",
            "mode": "FOCUS",
            "anchor_id": request.anchor_id,
            "task_id": result.get("task_id")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WeakConnection] 接受提议失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/config")
async def get_config():
    """获取弱连接配置"""
    weak_connection_engine = get_weak_connection_engine()
    return getattr(weak_connection_engine, 'config', {})


@router.post("/config")
async def update_config(config: WeakConnectionConfig):
    """更新弱连接配置"""
    weak_connection_engine = get_weak_connection_engine()
    weak_connection_engine.config.update(config.dict())
    return getattr(weak_connection_engine, 'config', {})


@router.get("/status")
async def get_status():
    """获取弱连接状态"""
    weak_connection_engine = get_weak_connection_engine()
    work_mode_manager = get_work_mode_manager()
    return {
        "enabled": getattr(weak_connection_engine, 'config', {}).get("enabled", True),
        "current_mode": work_mode_manager.get_current_mode().value if hasattr(work_mode_manager.get_current_mode(), 'value') else str(work_mode_manager.get_current_mode()),
        "can_trigger": False  # 简化处理
    }
