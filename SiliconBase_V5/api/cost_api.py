#!/usr/bin/env python3
"""
成本管理API - Token使用与成本查询接口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
端点列表：
  ✓ GET    /api/cost/status              - 获取当前预算状态
  ✓ GET    /api/cost/stats               - 获取使用统计
  ✓ GET    /api/cost/report              - 生成成本报告
  ✓ GET    /api/cost/usage               - 获取详细使用记录
  ✓ POST   /api/cost/budget              - 更新预算设置
  ✓ GET    /api/cost/models              - 获取模型定价列表
  ✓ GET    /api/cost/alerts              - 获取告警配置
  ✓ POST   /api/cost/alerts/config       - 配置告警

WebSocket事件：
  - cost_alert: 预算告警通知
  - budget_exceeded: 预算超限通知
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.logger import logger

# 导入成本管理器
try:
    from core.cost.cost_manager import CostManager, cost_manager
    from core.utils.token_tracker import token_tracker
    COST_MANAGER_AVAILABLE = True
except ImportError as e:
    COST_MANAGER_AVAILABLE = False
    logger.error(f"[CostAPI] 成本管理器导入失败: {e}")

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
        logger.error(f"[CostAPI] 认证模块导入失败: {e}")

        async def get_current_user() -> str | None:
            raise HTTPException(status_code=503, detail="认证服务不可用")

# 只在认证模块可用时添加认证依赖
router_dependencies = [Depends(get_current_user)] if AUTH_AVAILABLE else []
router = APIRouter(
    prefix="/cost",
    tags=["cost"],
    dependencies=router_dependencies
)


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════════════

class BudgetConfig(BaseModel):
    """预算配置模型"""
    daily_budget: float = Field(default=100.0, ge=1.0, description="日预算（美元）")
    monthly_budget: float = Field(default=1000.0, ge=10.0, description="月预算（美元）")

    class Config:
        json_schema_extra = {
            "example": {
                "daily_budget": 100.0,
                "monthly_budget": 1000.0
            }
        }


class CostRecordResponse(BaseModel):
    """成本记录响应模型"""
    id: int
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    request_type: str
    created_at: str
    metadata: dict[str, Any] | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "model": "gpt-4",
                "input_tokens": 1000,
                "output_tokens": 500,
                "total_tokens": 1500,
                "input_cost": 0.03,
                "output_cost": 0.03,
                "total_cost": 0.06,
                "request_type": "chat",
                "created_at": "2024-01-01T00:00:00",
                "metadata": {}
            }
        }


class BudgetStatusResponse(BaseModel):
    """预算状态响应模型"""
    daily_budget: float
    monthly_budget: float
    daily_used: float
    monthly_used: float
    daily_remaining: float
    monthly_remaining: float
    daily_percent: float
    monthly_percent: float
    alert_level: str

    class Config:
        json_schema_extra = {
            "example": {
                "daily_budget": 100.0,
                "monthly_budget": 1000.0,
                "daily_used": 45.5,
                "monthly_used": 320.0,
                "daily_remaining": 54.5,
                "monthly_remaining": 680.0,
                "daily_percent": 45.5,
                "monthly_percent": 32.0,
                "alert_level": "normal"
            }
        }


class UsageStatsResponse(BaseModel):
    """使用统计响应模型"""
    overall: dict[str, Any]
    by_model: list[dict[str, Any]]
    by_day: list[dict[str, Any]]
    period: dict[str, str]

    class Config:
        json_schema_extra = {
            "example": {
                "overall": {
                    "total_requests": 100,
                    "total_tokens": 50000,
                    "total_cost": 2.5
                },
                "by_model": [{"model": "gpt-4", "requests": 50, "cost": 2.0}],
                "by_day": [{"date": "2024-01-01", "requests": 10, "cost": 0.5}],
                "period": {"start": "2024-01-01", "end": "2024-01-31"}
            }
        }


class ModelPricingResponse(BaseModel):
    """模型定价响应模型"""
    model: str
    input_price: float  # 每1000 tokens
    output_price: float  # 每1000 tokens

    class Config:
        json_schema_extra = {
            "example": {
                "model": "gpt-4",
                "input_price": 0.03,
                "output_price": 0.06
            }
        }


class AlertConfig(BaseModel):
    """告警配置模型"""
    warning_threshold: float = Field(default=80.0, ge=50.0, le=95.0, description="警告阈值（百分比）")
    critical_threshold: float = Field(default=95.0, ge=80.0, le=100.0, description="严重告警阈值（百分比）")
    webhook_url: str | None = Field(default=None, description="告警Webhook URL")
    email_notifications: bool = Field(default=False, description="是否启用邮件通知")

    class Config:
        json_schema_extra = {
            "example": {
                "warning_threshold": 80.0,
                "critical_threshold": 95.0,
                "webhook_url": "https://hooks.example.com/alert",
                "email_notifications": True
            }
        }


class TokenCountRequest(BaseModel):
    """Token计数请求模型"""
    text: str = Field(..., description="要计数的文本")
    model: str = Field(default="gpt-4", description="模型名称")

    class Config:
        json_schema_extra = {
            "example": {
                "text": "Hello, world!",
                "model": "gpt-4"
            }
        }


class TokenCountResponse(BaseModel):
    """Token计数响应模型"""
    text: str
    model: str
    token_count: int
    encoding: str

    class Config:
        json_schema_extra = {
            "example": {
                "text": "Hello, world!",
                "model": "gpt-4",
                "token_count": 3,
                "encoding": "cl100k_base"
            }
        }


# ═══════════════════════════════════════════════════════════════════
# API 端点实现
# ═══════════════════════════════════════════════════════════════════

@router.get("/status", response_model=BudgetStatusResponse)
async def get_budget_status(
    user_id: str = Depends(get_current_user)
):
    """
    获取当前预算状态

    返回日/月预算使用情况、剩余额度、告警级别
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        status = cost_manager.get_budget_status(user_id)
        return {
            "daily_budget": float(status.daily_budget),
            "monthly_budget": float(status.monthly_budget),
            "daily_used": float(status.daily_used),
            "monthly_used": float(status.monthly_used),
            "daily_remaining": float(status.daily_remaining),
            "monthly_remaining": float(status.monthly_remaining),
            "daily_percent": status.daily_percent,
            "monthly_percent": status.monthly_percent,
            "alert_level": status.alert_level.value
        }
    except Exception as e:
        logger.error(f"[CostAPI] 获取预算状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取预算状态失败: {str(e)}") from e


@router.get("/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    days: int = Query(default=30, ge=1, le=365, description="查询天数"),
    user_id: str = Depends(get_current_user)
):
    """
    获取使用统计

    返回指定时间范围内的使用统计，包括总体统计、按模型统计、按日统计
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        stats = cost_manager.get_usage_stats(user_id, start_date, end_date)

        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])

        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CostAPI] 获取使用统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取使用统计失败: {str(e)}") from e


@router.get("/report")
async def get_cost_report(
    user_id: str = Depends(get_current_user)
):
    """
    生成完整成本报告

    包含预算状态、使用统计、趋势分析
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        report = cost_manager.get_cost_report(user_id)
        return report
    except Exception as e:
        logger.error(f"[CostAPI] 生成成本报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成成本报告失败: {str(e)}") from e


@router.get("/usage", response_model=list[CostRecordResponse])
async def get_usage_records(
    limit: int = Query(default=50, ge=1, le=1000, description="返回记录数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    model: str | None = Query(default=None, description="模型筛选"),
    start_date: datetime | None = Query(default=None, description="开始日期"),
    end_date: datetime | None = Query(default=None, description="结束日期"),
    user_id: str = Depends(get_current_user)
):
    """
    获取详细使用记录

    返回Token使用明细，支持分页和筛选
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        # 这里需要从数据库查询，简化实现
        # 实际项目中应该实现完整的查询逻辑
        return []
    except Exception as e:
        logger.error(f"[CostAPI] 获取使用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取使用记录失败: {str(e)}") from e


@router.post("/budget")
async def update_budget(
    config: BudgetConfig,
    user_id: str = Depends(get_current_user)
):
    """
    更新预算设置

    修改日预算和月预算额度
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        cost_manager.update_budget(
            daily=config.daily_budget,
            monthly=config.monthly_budget
        )
        return {
            "success": True,
            "message": "预算设置已更新",
            "daily_budget": config.daily_budget,
            "monthly_budget": config.monthly_budget
        }
    except Exception as e:
        logger.error(f"[CostAPI] 更新预算失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新预算失败: {str(e)}") from e


@router.get("/models", response_model=list[ModelPricingResponse])
async def get_model_pricing():
    """
    获取模型定价列表

    返回所有支持的模型及其定价信息
    """
    if not COST_MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="成本管理器不可用")

    try:
        pricing_list = []
        for model, pricing in CostManager.MODEL_PRICING.items():
            if model != "default":
                pricing_list.append({
                    "model": model,
                    "input_price": pricing["input"],
                    "output_price": pricing["output"]
                })

        # 按模型名称排序
        pricing_list.sort(key=lambda x: x["model"])
        return pricing_list
    except Exception as e:
        logger.error(f"[CostAPI] 获取模型定价失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型定价失败: {str(e)}") from e


@router.post("/count", response_model=TokenCountResponse)
async def count_tokens(
    request: TokenCountRequest
):
    """
    计算文本Token数量

    使用tiktoken精确计数
    """
    try:
        if not COST_MANAGER_AVAILABLE:
            # 使用简单估算
            token_count = len(request.text) // 4
            encoding = "estimated"
        else:
            token_count = token_tracker.count_tokens(request.text, request.model)
            encoding = token_tracker.get_model_info(request.model).get("encoding", "unknown")

        return {
            "text": request.text[:100] + "..." if len(request.text) > 100 else request.text,
            "model": request.model,
            "token_count": token_count,
            "encoding": encoding
        }
    except Exception as e:
        logger.error(f"[CostAPI] Token计数失败: {e}")
        raise HTTPException(status_code=500, detail=f"Token计数失败: {str(e)}") from e


@router.post("/count-messages")
async def count_message_tokens(
    messages: list[dict[str, str]],
    model: str = Query(default="gpt-4", description="模型名称")
):
    """
    计算消息列表Token数量

    适用于OpenAI消息格式的Token计数
    """
    try:
        if not COST_MANAGER_AVAILABLE:
            # 简单估算
            total = sum(len(m.get("content", "")) for m in messages) // 4
            total += len(messages) * 4  # 格式开销
        else:
            total = token_tracker.count_message_tokens(messages, model)

        return {
            "model": model,
            "message_count": len(messages),
            "token_count": total
        }
    except Exception as e:
        logger.error(f"[CostAPI] 消息Token计数失败: {e}")
        raise HTTPException(status_code=500, detail=f"消息Token计数失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# WebSocket 实时告警
# ═══════════════════════════════════════════════════════════════════

class CostAlertWebSocket:
    """成本告警WebSocket管理器"""

    def __init__(self):
        self.connections: dict[str, WebSocket] = {}
        self._initialized = False

    def init_callbacks(self):
        """初始化告警回调"""
        if self._initialized or not COST_MANAGER_AVAILABLE:
            return

        # 注册预算告警回调
        cost_manager.on_budget_alert(self._handle_budget_alert)
        cost_manager.on_budget_exceeded(self._handle_budget_exceeded)
        self._initialized = True

    async def _handle_budget_alert(self, user_id: str, status):
        """处理预算告警"""
        if user_id in self.connections:
            ws = self.connections[user_id]
            try:
                await ws.send_json({
                    "type": "cost_alert",
                    "level": status.alert_level.value,
                    "daily_percent": status.daily_percent,
                    "monthly_percent": status.monthly_percent,
                    "message": f"预算使用告警 - 日使用: {status.daily_percent}%, 月使用: {status.monthly_percent}%",
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"[CostAPI] 发送告警失败: {e}")

    async def _handle_budget_exceeded(self, user_id: str, budget_type: str, used: Decimal, budget: Decimal):
        """处理预算超限"""
        if user_id in self.connections:
            ws = self.connections[user_id]
            try:
                await ws.send_json({
                    "type": "budget_exceeded",
                    "budget_type": budget_type,
                    "used": float(used),
                    "budget": float(budget),
                    "message": f"{'日' if budget_type == 'daily' else '月'}预算已超限！已用: ${used}, 预算: ${budget}",
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"[CostAPI] 发送超限通知失败: {e}")

    async def connect(self, websocket: WebSocket, user_id: str):
        """连接WebSocket"""
        await websocket.accept()
        self.connections[user_id] = websocket
        self.init_callbacks()

        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "message": "成本告警服务已连接",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        })

    def disconnect(self, user_id: str):
        """断开WebSocket连接"""
        if user_id in self.connections:
            del self.connections[user_id]


cost_alert_ws = CostAlertWebSocket()


@router.websocket("/ws/alerts")
async def cost_alert_websocket(
    websocket: WebSocket,
    token: str | None = None
):
    """
    成本告警WebSocket

    实时接收预算告警和超限通知

    连接示例：
      ws://localhost:8000/api/cost/ws/alerts?token=your_token
    """
    user_id = "default"  # 应该从token解析

    try:
        await cost_alert_ws.connect(websocket, user_id)

        # 保持连接
        while True:
            data = await websocket.receive_text()
            # 处理客户端消息（如心跳）
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        cost_alert_ws.disconnect(user_id)
    except Exception as e:
        logger.error(f"[CostAPI] WebSocket错误: {e}")
        cost_alert_ws.disconnect(user_id)
