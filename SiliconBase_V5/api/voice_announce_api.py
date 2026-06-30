#!/usr/bin/env python3
"""
语音播报配置API
提供前端接口用于获取和设置语音播报配置

功能：
1. 获取语音播报配置
2. 更新语音播报配置（运行时热更新，不持久化到文件）
3. 获取语音播报状态
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.logger import logger

# 导入配置中心
try:
    from core.config import config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    config = None

# 导入认证依赖
try:
    from api.cloud_api import get_current_user_optional
    HAS_AUTH = True
except ImportError:
    HAS_AUTH = False

    # 备用认证依赖
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    security = HTTPBearer(auto_error=False)

    async def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security) if security else None) -> str:
        """可选认证，返回用户ID或default_user"""
        return "default_user"

router = APIRouter(
    prefix="/voice",
    tags=["语音播报配置"]
)


# ============ 数据模型 ============

class VoiceAnnounceConfig(BaseModel):
    """语音播报配置模型"""
    enabled: bool = Field(default=True, description="是否启用语音播报")
    ai_output: bool = Field(default=True, description="是否播报AI输出")
    process: dict[str, Any] = Field(default_factory=dict, description="过程播报配置")
    priority: dict[str, Any] = Field(default_factory=dict, description="优先级播报配置")


class VoiceAnnounceConfigResponse(BaseModel):
    """语音播报配置响应"""
    enabled: bool
    ai_output: bool
    process: dict[str, Any]
    priority: dict[str, Any]


class VoiceAnnounceStatusResponse(BaseModel):
    """语音播报状态响应"""
    enabled: bool
    ai_output_enabled: bool
    process_enabled: bool | None = None


class UpdateConfigResponse(BaseModel):
    """更新配置响应"""
    status: str
    config: dict[str, Any]


# ============ API端点 ============

@router.get("/announce/config", response_model=VoiceAnnounceConfigResponse)
async def get_voice_announce_config(
    user_id: str = Depends(get_current_user_optional)
) -> dict[str, Any]:
    """
    获取语音播报配置

    返回当前的语音播报配置，包括：
    - enabled: 是否启用语音播报
    - ai_output: 是否播报AI输出
    - process: 过程播报配置
    - priority: 优先级播报配置

    Returns:
        语音播报配置字典
    """
    try:
        if not CONFIG_AVAILABLE:
            # 配置中心不可用，返回默认配置
            return {
                "enabled": True,
                "ai_output": True,
                "process": {},
                "priority": {}
            }

        # 从配置中心获取语音播报配置
        announce_config = config.get_voice_announce_config()

        # 确保返回完整的配置结构
        result = {
            "enabled": announce_config.get("enabled", True),
            "ai_output": announce_config.get("ai_output", True),
            "process": announce_config.get("process", {}),
            "priority": announce_config.get("priority", {})
        }

        logger.debug(f"[VoiceAnnounceAPI] 获取语音播报配置: {result}")
        return result

    except Exception as e:
        logger.error(f"[VoiceAnnounceAPI] 获取语音播报配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}") from e


@router.post("/announce/config", response_model=UpdateConfigResponse)
async def update_voice_announce_config(
    cfg: VoiceAnnounceConfig,
    user_id: str = Depends(get_current_user_optional)
) -> dict[str, Any]:
    """
    更新语音播报配置（运行时热更新）

    更新语音播报配置，仅影响运行时，不持久化到配置文件。
    支持热更新，修改后立即生效。

    Args:
        cfg: 语音播报配置

    Returns:
        更新结果和当前配置
    """
    try:
        if not CONFIG_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="配置中心不可用"
            )

        # 获取当前voice配置（如果不存在则创建）
        voice_config = config._global_config.get("voice", {})
        if not isinstance(voice_config, dict):
            voice_config = {}
            config._global_config["voice"] = voice_config

        # 更新announce配置
        new_announce_config = cfg.dict()
        voice_config["announce"] = new_announce_config

        logger.info(f"[VoiceAnnounceAPI] 语音播报配置已更新: user={user_id}, config={new_announce_config}")

        return {
            "status": "success",
            "config": new_announce_config
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VoiceAnnounceAPI] 更新语音播报配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}") from e


@router.get("/announce/status", response_model=VoiceAnnounceStatusResponse)
async def get_voice_announce_status(
    user_id: str = Depends(get_current_user_optional)
) -> dict[str, Any]:
    """
    获取语音播报状态

    返回简化的语音播报状态，用于前端快速检查。

    Returns:
        语音播报状态字典
    """
    try:
        if not CONFIG_AVAILABLE:
            # 配置中心不可用，返回默认状态
            return {
                "enabled": True,
                "ai_output_enabled": True,
                "process_enabled": None
            }

        # 获取各项配置状态
        enabled = config.get_voice_announce_config("enabled", True)
        ai_output_enabled = config.get_voice_announce_config("ai_output", True)
        process_enabled = config.get_voice_announce_config("process.enabled")

        return {
            "enabled": enabled,
            "ai_output_enabled": ai_output_enabled,
            "process_enabled": process_enabled
        }

    except Exception as e:
        logger.error(f"[VoiceAnnounceAPI] 获取语音播报状态失败: {e}")
        # 返回默认状态
        return {
            "enabled": True,
            "ai_output_enabled": True,
            "process_enabled": None
        }


@router.patch("/announce/config")
async def patch_voice_announce_config(
    updates: dict[str, Any],
    user_id: str = Depends(get_current_user_optional)
) -> dict[str, Any]:
    """
    部分更新语音播报配置（运行时热更新）

    部分更新语音播报配置，只更新提供的字段，不影响其他字段。
    仅影响运行时，不持久化到配置文件。

    Args:
        updates: 要更新的配置字段字典

    Returns:
        更新结果和当前完整配置
    """
    try:
        if not CONFIG_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="配置中心不可用"
            )

        # 获取当前voice配置
        voice_config = config._global_config.get("voice", {})
        if not isinstance(voice_config, dict):
            voice_config = {}
            config._global_config["voice"] = voice_config

        # 获取当前announce配置
        announce_config = voice_config.get("announce", {})
        if not isinstance(announce_config, dict):
            announce_config = {}

        # 验证并更新允许的字段
        allowed_fields = {"enabled", "ai_output", "process", "priority"}
        for key, value in updates.items():
            if key in allowed_fields:
                announce_config[key] = value
            else:
                logger.warning(f"[VoiceAnnounceAPI] 忽略未知配置字段: {key}")

        # 更新配置
        voice_config["announce"] = announce_config

        logger.info(f"[VoiceAnnounceAPI] 语音播报配置已部分更新: user={user_id}, updates={updates}")

        return {
            "status": "success",
            "config": announce_config
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VoiceAnnounceAPI] 部分更新语音播报配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}") from e
