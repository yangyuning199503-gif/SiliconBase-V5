#!/usr/bin/env python3
"""
交易所配置 API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供交易所配置的RESTful接口

端点:
- GET    /api/exchange/configs          获取用户所有配置
- POST   /api/exchange/configs          创建新配置
- PUT    /api/exchange/configs/{id}     更新配置
- DELETE /api/exchange/configs/{id}     删除配置
- POST   /api/exchange/configs/{id}/validate  验证配置
- GET    /api/exchange/mode             获取当前交易模式
- POST   /api/exchange/mode             切换交易模式

作者: SiliconBase Team
日期: 2026-04-09
"""


from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr

from core.logger import logger

# 认证依赖
security = HTTPBearer(auto_error=False)

async def get_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """获取当前用户ID，认证失败返回 'anonymous'"""
    try:
        from api.cloud_api import get_current_user_optional
        user = await get_current_user_optional(credentials)
        return user or "anonymous"
    except ImportError:
        return "anonymous"
    except Exception:
        return "anonymous"

# 配置管理器
try:
    from core.btc_integration.exchange_config import ExchangeType, TradingMode, get_exchange_config_manager
    CONFIG_AVAILABLE = True
except ImportError as e:
    CONFIG_AVAILABLE = False
    logger.error(f"[ExchangeConfigAPI] 配置管理器不可用: {e}")


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class ExchangeConfigCreate(BaseModel):
    """创建配置请求"""
    exchange: str = Field(..., description="交易所类型: okx/binance")
    name: str = Field(..., min_length=1, max_length=50, description="配置名称")
    mode: str = Field(..., description="交易模式: demo/live")
    api_key: SecretStr = Field(..., min_length=1, description="API Key")
    api_secret: SecretStr = Field(..., min_length=1, description="API Secret")
    passphrase: SecretStr = Field(default=SecretStr(""), description="Passphrase (OKX需要)")
    testnet: bool = Field(default=True, description="是否使用测试网")


class ExchangeConfigUpdate(BaseModel):
    """更新配置请求"""
    name: str | None = Field(None, max_length=50)
    api_key: SecretStr | None = None
    api_secret: SecretStr | None = None
    passphrase: SecretStr | None = None
    is_active: bool | None = None
    testnet: bool | None = None


class ExchangeConfigResponse(BaseModel):
    """配置响应"""
    id: str
    name: str
    exchange: str
    mode: str
    is_active: bool
    is_validated: bool
    testnet: bool
    created_at: float
    updated_at: float


class TradingModeResponse(BaseModel):
    """交易模式响应"""
    mode: str
    available_modes: list[str]
    has_live_config: bool
    message: str


class ValidationResponse(BaseModel):
    """验证响应"""
    valid: bool
    message: str


# ═══════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════

router = APIRouter(prefix="/exchange", tags=["exchange_config"])


@router.get("/configs", response_model=list[ExchangeConfigResponse])
async def get_configs(user_id: str = Depends(get_user_id)):
    """
    获取用户所有交易所配置

    返回的配置不包含敏感信息（API Key等）
    """
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        manager = get_exchange_config_manager()
        configs = manager.get_user_configs(user_id)

        return [cfg.to_safe_dict() for cfg in configs]

    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 获取配置失败: {e}")
        raise HTTPException(500, f"获取配置失败: {str(e)}") from e


@router.post("/configs", response_model=ExchangeConfigResponse)
async def create_config(
    data: ExchangeConfigCreate,
    user_id: str = Depends(get_user_id)
):
    """
    创建新的交易所配置

    - exchange: okx 或 binance
    - mode: demo(模拟盘) 或 live(实盘)
    - api_key: 交易所API Key
    - api_secret: 交易所API Secret
    - passphrase: OKX交易所需要
    """
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        # 验证交易所类型
        try:
            exchange = ExchangeType(data.exchange)
        except ValueError as _exc:
            raise HTTPException(400, f"不支持的交易所类型: {data.exchange}") from _exc

        # 验证交易模式
        try:
            mode = TradingMode(data.mode)
        except ValueError as _exc:
            raise HTTPException(400, f"不支持的交易模式: {data.mode}") from _exc

        # OKX 需要 passphrase
        if exchange == ExchangeType.OKX and not data.passphrase.get_secret_value():
            raise HTTPException(400, "OKX交易所需要提供Passphrase")

        manager = get_exchange_config_manager()

        cfg = manager.create_config(
            user_id=user_id,
            exchange=exchange,
            name=data.name,
            mode=mode,
            api_key=data.api_key.get_secret_value(),
            api_secret=data.api_secret.get_secret_value(),
            passphrase=data.passphrase.get_secret_value(),
            testnet=data.testnet
        )

        logger.info(f"[ExchangeConfigAPI] [user={user_id}] 创建配置: {data.name}")
        return cfg.to_safe_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 创建配置失败: {e}")
        raise HTTPException(500, f"创建配置失败: {str(e)}") from e


@router.put("/configs/{config_id}", response_model=ExchangeConfigResponse)
async def update_config(
    config_id: str,
    data: ExchangeConfigUpdate,
    user_id: str = Depends(get_user_id)
):
    """更新交易所配置"""
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        manager = get_exchange_config_manager()

        # 检查配置是否存在
        existing = manager.get_config(user_id, config_id)
        if not existing:
            raise HTTPException(404, "配置不存在")

        # 构建更新数据（SecretStr 字段需解包真实值）
        updates = {}
        for key, val in data.model_dump(exclude_unset=True).items():
            field_val = getattr(data, key)
            if hasattr(field_val, 'get_secret_value'):
                updates[key] = field_val.get_secret_value() if field_val else ""
            else:
                updates[key] = val

        cfg = manager.update_config(user_id, config_id, **updates)

        logger.info(f"[ExchangeConfigAPI] [user={user_id}] 更新配置: {config_id}")
        return cfg.to_safe_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 更新配置失败: {e}")
        raise HTTPException(500, f"更新配置失败: {str(e)}") from e


@router.delete("/configs/{config_id}")
async def delete_config(
    config_id: str,
    user_id: str = Depends(get_user_id)
):
    """删除交易所配置"""
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        manager = get_exchange_config_manager()

        success = manager.delete_config(user_id, config_id)

        if not success:
            raise HTTPException(404, "配置不存在")

        logger.info(f"[ExchangeConfigAPI] [user={user_id}] 删除配置: {config_id}")
        return {"success": True, "message": "配置已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 删除配置失败: {e}")
        raise HTTPException(500, f"删除配置失败: {str(e)}") from e


@router.post("/configs/{config_id}/validate", response_model=ValidationResponse)
async def validate_config(
    config_id: str,
    user_id: str = Depends(get_user_id)
):
    """
    验证交易所配置

    检查配置是否有效，尝试连接交易所API
    """
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        manager = get_exchange_config_manager()

        result = manager.validate_config(user_id, config_id)

        logger.info(f"[ExchangeConfigAPI] [user={user_id}] 验证配置: {config_id}, 结果={result['valid']}")
        return result

    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 验证配置失败: {e}")
        raise HTTPException(500, f"验证配置失败: {str(e)}") from e


@router.get("/mode", response_model=TradingModeResponse)
async def get_trading_mode(user_id: str = Depends(get_user_id)):
    """
    获取当前交易模式

    根据用户的配置自动判断:
    - 如果有有效的实盘配置，返回 live
    - 否则返回 demo
    """
    if not CONFIG_AVAILABLE:
        return TradingModeResponse(
            mode="demo",
            available_modes=["demo", "live"],
            has_live_config=False,
            message="配置管理器不可用，使用模拟盘模式"
        )

    try:
        manager = get_exchange_config_manager()

        default_mode = manager.get_default_mode(user_id)
        configs = manager.get_user_configs(user_id)

        has_live = any(
            c.mode == TradingMode.LIVE and c.is_validated
            for c in configs
        )

        return TradingModeResponse(
            mode=default_mode.value,
            available_modes=["demo", "live"],
            has_live_config=has_live,
            message=f"当前使用{ '实盘' if default_mode == TradingMode.LIVE else '模拟盘' }模式"
        )

    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 获取交易模式失败: {e}")
        return TradingModeResponse(
            mode="demo",
            available_modes=["demo", "live"],
            has_live_config=False,
            message="获取模式失败，默认使用模拟盘"
        )


@router.post("/configs/{config_id}/activate")
async def activate_config(
    config_id: str,
    user_id: str = Depends(get_user_id)
):
    """激活指定配置（同时禁用同交易所的其他配置）"""
    if not CONFIG_AVAILABLE:
        raise HTTPException(503, "配置管理器不可用")

    try:
        manager = get_exchange_config_manager()

        cfg = manager.get_config(user_id, config_id)
        if not cfg:
            raise HTTPException(404, "配置不存在")

        # 禁用同交易所的其他配置
        for other_cfg in manager.get_user_configs(user_id):
            if other_cfg.exchange == cfg.exchange and other_cfg.id != config_id:
                manager.update_config(user_id, other_cfg.id, is_active=False)

        # 激活当前配置
        manager.update_config(user_id, config_id, is_active=True)

        logger.info(f"[ExchangeConfigAPI] [user={user_id}] 激活配置: {config_id}")
        return {"success": True, "message": f"已激活配置: {cfg.name}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExchangeConfigAPI] [user={user_id}] 激活配置失败: {e}")
        raise HTTPException(500, f"激活配置失败: {str(e)}") from e


@router.get("/exchanges")
async def get_supported_exchanges():
    """获取支持的交易所列表"""
    return {
        "exchanges": [
            {
                "id": "okx",
                "name": "OKX",
                "logo": "/assets/exchanges/okx.png",
                "features": ["现货", "合约", "期权"],
                "requires_passphrase": True,
                "testnet_available": True
            },
            {
                "id": "binance",
                "name": "Binance",
                "logo": "/assets/exchanges/binance.png",
                "features": ["现货", "合约"],
                "requires_passphrase": False,
                "testnet_available": True
            }
        ]
    }
