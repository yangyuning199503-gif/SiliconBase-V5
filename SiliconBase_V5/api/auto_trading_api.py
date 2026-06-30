#!/usr/bin/env python3
"""
24小时自动交易管理API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供自动交易的管理接口

端点:
- POST /auto-trading/start: 启动24小时自动交易
- POST /auto-trading/stop: 停止自动交易
- GET /auto-trading/status: 获取运行状态
- POST /auto-trading/pause: 暂停（保持持仓）
- POST /auto-trading/resume: 恢复
- GET /auto-trading/logs: 获取运行日志
- GET /auto-trading/stats: 获取统计数据
- POST /auto-trading/cleanup: 强制资源清理

作者: SiliconBase V5 AI Agent
日期: 2026-04-09
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.btc_integration.auto_trading_scheduler import AutoTradingStatus, get_auto_trading_scheduler
from core.logger import logger

# 创建路由
router = APIRouter(prefix="/auto-trading", tags=["auto-trading"])


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class StartAutoTradingRequest(BaseModel):
    """启动自动交易请求"""
    symbol: str = Field(default="BTC", description="交易标的")
    budget: float = Field(default=1000.0, description="预算金额(USDT)")
    risk_tolerance: str = Field(default="medium", description="风险偏好")
    strategy: str | None = Field(default=None, description="指定策略(空则自动)")


class AutoTradingResponse(BaseModel):
    """自动交易响应"""
    success: bool
    message: str
    data: dict[str, Any] | None = None


class AutoTradingStatusResponse(BaseModel):
    """状态响应"""
    status: str
    current_session: dict[str, Any] | None
    stats: dict[str, Any]
    circuit_breaker: dict[str, Any]
    config: dict[str, Any]


class LogEntry(BaseModel):
    """日志条目"""
    timestamp: str
    level: str
    message: str
    data: dict[str, Any]


# ═══════════════════════════════════════════════════════════════
# API端点
# ═══════════════════════════════════════════════════════════════

@router.post("/start", response_model=AutoTradingResponse)
async def start_auto_trading(request: StartAutoTradingRequest):
    """
    启动24小时自动交易

    系统会自动:
    - 每小时分析市场并选择策略
    - 自动启动交易会话
    - 会话到期前自动续约
    - 风险过高时自动熔断
    - 进程崩溃后自动重启
    """
    try:
        scheduler = get_auto_trading_scheduler()

        # 检查是否已在运行
        if scheduler.is_running():
            return AutoTradingResponse(
                success=False,
                message="自动交易已在运行中",
                data={"status": scheduler.status.value}
            )

        # 启动
        success = await scheduler.start_24h_trading(
            symbol=request.symbol,
            budget=request.budget,
            risk_tolerance=request.risk_tolerance,
            strategy=request.strategy
        )

        if success:
            return AutoTradingResponse(
                success=True,
                message="24小时自动交易已启动",
                data={
                    "symbol": request.symbol,
                    "budget": request.budget,
                    "status": AutoTradingStatus.RUNNING.value
                }
            )
        else:
            return AutoTradingResponse(
                success=False,
                message="启动失败，请检查日志",
                data={"status": scheduler.status.value}
            )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 启动失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}") from e


@router.post("/stop", response_model=AutoTradingResponse)
async def stop_auto_trading():
    """停止自动交易"""
    try:
        scheduler = get_auto_trading_scheduler()

        if scheduler.status == AutoTradingStatus.STOPPED:
            return AutoTradingResponse(
                success=True,
                message="自动交易已处于停止状态"
            )

        success = await scheduler.stop()

        return AutoTradingResponse(
            success=success,
            message="自动交易已停止" if success else "停止失败",
            data={"status": scheduler.status.value}
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 停止失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止失败: {str(e)}") from e


@router.get("/status", response_model=AutoTradingStatusResponse)
async def get_auto_trading_status():
    """获取自动交易状态"""
    try:
        scheduler = get_auto_trading_scheduler()
        status = scheduler.get_status()

        return AutoTradingStatusResponse(
            status=status["status"],
            current_session=status["current_session"],
            stats=status["stats"],
            circuit_breaker=status["circuit_breaker"],
            config=status["config"]
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 获取状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}") from e


@router.post("/pause", response_model=AutoTradingResponse)
async def pause_auto_trading():
    """
    暂停自动交易

    暂停后会保持当前持仓，不再开新仓
    """
    try:
        scheduler = get_auto_trading_scheduler()

        success = await scheduler.pause()

        return AutoTradingResponse(
            success=success,
            message="自动交易已暂停" if success else "暂停失败",
            data={"status": scheduler.status.value}
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 暂停失败: {e}")
        raise HTTPException(status_code=500, detail=f"暂停失败: {str(e)}") from e


@router.post("/resume", response_model=AutoTradingResponse)
async def resume_auto_trading():
    """
    恢复自动交易

    从暂停或熔断状态恢复
    """
    try:
        scheduler = get_auto_trading_scheduler()

        success = await scheduler.resume()

        return AutoTradingResponse(
            success=success,
            message="自动交易已恢复" if success else "恢复失败",
            data={"status": scheduler.status.value}
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 恢复失败: {e}")
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}") from e


@router.get("/logs")
async def get_auto_trading_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    level: str | None = Query(default=None, description="过滤日志级别")
):
    """
    获取自动交易日志

    Args:
        limit: 返回日志条数
        level: 过滤级别 (info/warning/error)
    """
    try:
        scheduler = get_auto_trading_scheduler()
        logs = scheduler.get_logs(limit=limit)

        # 过滤级别
        if level:
            logs = [log for log in logs if log["level"].lower() == level.lower()]

        return {
            "logs": logs,
            "total": len(logs),
            "filtered": level is not None
        }

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 获取日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志失败: {str(e)}") from e


@router.get("/stats")
async def get_auto_trading_stats():
    """获取自动交易统计"""
    try:
        scheduler = get_auto_trading_scheduler()
        status = scheduler.get_status()

        return {
            "stats": status["stats"],
            "current_status": status["status"],
            "circuit_breaker": status["circuit_breaker"]
        }

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}") from e


@router.get("/sessions")
async def get_session_history(
    limit: int = Query(default=10, ge=1, le=100)
):
    """获取会话历史"""
    try:
        scheduler = get_auto_trading_scheduler()
        sessions = scheduler.get_session_history()

        return {
            "sessions": sessions[-limit:],
            "total": len(sessions)
        }

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 获取会话历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话历史失败: {str(e)}") from e


@router.post("/cleanup", response_model=AutoTradingResponse)
async def force_cleanup():
    """
    强制资源清理

    手动触发内存清理和垃圾回收
    """
    try:
        scheduler = get_auto_trading_scheduler()
        result = await scheduler._cleanup_resources()

        return AutoTradingResponse(
            success=True,
            message="资源清理完成",
            data={"result": result}
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 清理失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}") from e


@router.post("/restart", response_model=AutoTradingResponse)
async def restart_auto_trading(request: StartAutoTradingRequest):
    """重启自动交易（停止后重新启动）"""
    try:
        scheduler = get_auto_trading_scheduler()

        # 先停止
        await scheduler.stop()

        # 等待一秒确保清理完成
        import asyncio
        await asyncio.sleep(1)

        # 重新启动
        success = await scheduler.start_24h_trading(
            symbol=request.symbol,
            budget=request.budget,
            risk_tolerance=request.risk_tolerance,
            strategy=request.strategy
        )

        return AutoTradingResponse(
            success=success,
            message="自动交易已重启" if success else "重启失败",
            data={"status": scheduler.status.value}
        )

    except Exception as e:
        logger.error(f"[AutoTradingAPI] 重启失败: {e}")
        raise HTTPException(status_code=500, detail=f"重启失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════
# 健康检查端点
# ═══════════════════════════════════════════════════════════════

@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        scheduler = get_auto_trading_scheduler()

        return {
            "healthy": True,
            "status": scheduler.status.value,
            "is_running": scheduler.is_running(),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
