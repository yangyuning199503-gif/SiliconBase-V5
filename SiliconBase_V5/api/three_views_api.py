#!/usr/bin/env python3
"""
三观配置API
提供获取模板列表、获取/保存用户三观配置的接口
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from api.cloud_api import get_current_user
except ImportError:
    async def get_current_user():
        return {"user_id": "default"}
from core.logger import logger
from core.reflector.three_views_generator import ThreeViewsGenerator, get_three_views_generator

router = APIRouter(prefix="/three-views", tags=["three-views"])


class ThreeViewsConfigRequest(BaseModel):
    """三观配置请求"""
    template_name: str = "balanced"
    world_view: dict[str, Any] = {}
    life_view: dict[str, Any] = {}
    value_system: dict[str, Any] = {}


class ThreeViewsConfigResponse(BaseModel):
    """三观配置响应"""
    success: bool
    message: str
    config: dict[str, Any] = {}


class ThreeViewsPreviewResponse(BaseModel):
    """三观预览响应"""
    template_name: str
    moral_view: str
    value_view: str
    world_view: str
    full_prompt: str


@router.get("/templates")
async def get_templates(user: str = Depends(get_current_user)):
    """获取所有可用三观模板"""
    try:
        templates = ThreeViewsGenerator.get_available_templates()
        return {
            "success": True,
            "templates": templates
        }
    except Exception as e:
        logger.error(f"[ThreeViewsAPI] 获取模板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/config")
async def get_user_config(user: str = Depends(get_current_user)):
    """获取当前用户三观配置"""
    try:
        user_id = user if user else "default"
        generator = get_three_views_generator(user_id)

        return {
            "success": True,
            "config": {
                "template_name": generator.user_config.get("template_name", "balanced"),
                "world_view": generator.template.get("world_view", {}),
                "life_view": generator.template.get("life_view", {}),
                "value_system": generator.template.get("value_system", {})
            }
        }
    except Exception as e:
        logger.error(f"[ThreeViewsAPI] 获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/config")
async def save_user_config(
    config_data: ThreeViewsConfigRequest,
    user: str = Depends(get_current_user)
):
    """保存用户三观配置"""
    try:
        user_id = user if user else "default"
        generator = get_three_views_generator(user_id)

        # 构建配置
        save_data = {
            "template_name": config_data.template_name,
            "world_view": config_data.world_view,
            "life_view": config_data.life_view,
            "value_system": config_data.value_system
        }

        success = generator.update_user_config(save_data)

        if success:
            return {
                "success": True,
                "message": "三观配置已保存",
                "config": save_data
            }
        else:
            raise HTTPException(status_code=500, detail="保存失败")
    except Exception as e:
        logger.error(f"[ThreeViewsAPI] 保存配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/preview")
async def preview_three_views(
    template_name: str = "balanced",
    user: str = Depends(get_current_user)
):
    """预览指定模板的三观提示词"""
    try:
        generator = ThreeViewsGenerator(user_id="preview")
        generator.template = generator._get_template(template_name)

        # 生成预览
        moral = generator.generate_moral_view()
        value = generator.generate_value_view()
        world = generator.generate_world_view()
        full = generator.generate_all()

        return {
            "success": True,
            "template_name": template_name,
            "moral_view": moral,
            "value_view": value,
            "world_view": world,
            "full_prompt": full
        }
    except Exception as e:
        logger.error(f"[ThreeViewsAPI] 预览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
