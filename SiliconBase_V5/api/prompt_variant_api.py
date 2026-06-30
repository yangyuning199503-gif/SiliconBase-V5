#!/usr/bin/env python3
"""
提示词变体API路由 - SiliconBase V5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 获取模块变体列表
  ✓ 切换变体
  ✓ 变体内容管理

Author: SiliconBase Team
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# 注意：使用 /prompt-variants 前缀避免与 /prompt 冲突
router = APIRouter(prefix="/prompt-variants", tags=["prompt-variants"])


# ========== CamelCase基类 ==========

class CamelCaseModel(BaseModel):
    """自动将snake_case字段转换为camelCase的Pydantic模型基类"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ========== 请求/响应模型 ==========

class VariantSwitchRequest(CamelCaseModel):
    """变体切换请求"""
    variant_id: str
    user_id: str | None = "default"


class PromptVariantResponse(CamelCaseModel):
    """提示词变体响应"""
    id: str
    name: str
    description: str
    token_count: int
    failure_rate: float
    is_default: bool
    content: str | None = None


class VariantListResponse(CamelCaseModel):
    """变体列表响应"""
    success: bool = True
    module_id: str
    variants: list[PromptVariantResponse]


class VariantSwitchResponse(CamelCaseModel):
    """变体切换响应"""
    success: bool = True
    module_id: str
    variant_id: str
    content: str
    token_count: int


class VariantContentResponse(CamelCaseModel):
    """变体内容响应"""
    success: bool = True
    module_id: str
    variant_id: str
    content: str
    token_count: int


class UserSelectionsResponse(CamelCaseModel):
    """用户选择记录响应"""
    success: bool = True
    user_id: str
    selections: dict[str, str]


# ========== 数据存储（临时内存存储，后续应迁移到数据库）==========

VARIANTS_DB: dict[str, list[dict]] = {
    "three_views": [
        {
            "id": "default",
            "name": "默认版",
            "description": "标准提示词模板",
            "token_count": 800,
            "failure_rate": 0.05,
            "is_default": True,
            "content": "【三观提示词系统 - 你的价值导向体系】\n\n三观系统由三个维度构成..."
        },
        {
            "id": "concise",
            "name": "精简版",
            "description": "精简后的提示词，减少Token使用",
            "token_count": 200,
            "failure_rate": 0.08,
            "is_default": False,
            "content": "【核心准则】安全>隐私>成长。禁止高危操作..."
        },
        {
            "id": "coding",
            "name": "编程专用",
            "description": "针对编程任务优化的提示词",
            "token_count": 400,
            "failure_rate": 0.03,
            "is_default": False,
            "content": "【核心准则】代码安全>性能>可读性..."
        }
    ],
    "identity": [
        {
            "id": "default",
            "name": "默认版",
            "description": "标准身份定位",
            "token_count": 300,
            "failure_rate": 0.02,
            "is_default": True,
            "content": "你是SiliconBase，一个硅基生命..."
        },
        {
            "id": "concise",
            "name": "精简版",
            "description": "精简身份描述",
            "token_count": 100,
            "failure_rate": 0.04,
            "is_default": False,
            "content": "你是AI助手SiliconBase..."
        }
    ]
}

# 用户变体选择记录
USER_VARIANT_SELECTIONS: dict[str, dict[str, str]] = {}


def _convert_to_variant_response(variant_data: dict) -> PromptVariantResponse:
    """将原始数据转换为CamelCase响应模型"""
    return PromptVariantResponse(
        id=variant_data["id"],
        name=variant_data["name"],
        description=variant_data["description"],
        token_count=variant_data.get("token_count", 0),
        failure_rate=variant_data.get("failure_rate", 0.0),
        is_default=variant_data.get("is_default", False),
        content=variant_data.get("content")
    )


# ========== API端点 ==========

@router.get("/{module_id}", response_model=VariantListResponse)
async def get_module_variants(module_id: str):
    """
    获取模块的变体列表

    Args:
        module_id: 模块ID

    Returns:
        变体列表（自动转换为camelCase）
    """
    try:
        variants_data = VARIANTS_DB.get(module_id, [])

        if not variants_data:
            variants_data = [{
                "id": "default",
                "name": "默认版",
                "description": "标准提示词模板",
                "token_count": 0,
                "failure_rate": 0,
                "is_default": True
            }]

        variants = [_convert_to_variant_response(v) for v in variants_data]
        return VariantListResponse(module_id=module_id, variants=variants)
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 获取变体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{module_id}/switch", response_model=VariantSwitchResponse)
async def switch_variant(module_id: str, request: VariantSwitchRequest):
    """
    切换模块变体

    Args:
        module_id: 模块ID
        request: { variant_id: str, user_id: str }

    Returns:
        切换后的变体内容（自动转换为camelCase）
    """
    try:
        variants = VARIANTS_DB.get(module_id, [])
        target_variant = next((v for v in variants if v["id"] == request.variant_id), None)

        if not target_variant:
            raise HTTPException(status_code=404, detail=f"变体 {request.variant_id} 不存在")

        user_key = f"{request.user_id or 'default'}"
        if user_key not in USER_VARIANT_SELECTIONS:
            USER_VARIANT_SELECTIONS[user_key] = {}
        USER_VARIANT_SELECTIONS[user_key][module_id] = request.variant_id

        logging.info(f"[PromptVariantAPI] 用户 {user_key} 切换 {module_id} 到变体 {request.variant_id}")

        return VariantSwitchResponse(
            module_id=module_id,
            variant_id=request.variant_id,
            content=target_variant.get("content", ""),
            token_count=target_variant.get("token_count", 0)
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 切换变体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{module_id}/content", response_model=VariantContentResponse)
async def get_variant_content(module_id: str, variant_id: str = "default", user_id: str = "default"):
    """
    获取特定变体的内容

    Args:
        module_id: 模块ID
        variant_id: 变体ID（默认default）
        user_id: 用户ID

    Returns:
        变体内容（自动转换为camelCase）
    """
    try:
        user_key = f"{user_id or 'default'}"
        user_selected = USER_VARIANT_SELECTIONS.get(user_key, {}).get(module_id)
        if user_selected:
            variant_id = user_selected

        variants = VARIANTS_DB.get(module_id, [])
        variant = next((v for v in variants if v["id"] == variant_id), None)

        if not variant:
            variant = next((v for v in variants if v.get("is_default")), variants[0] if variants else None)

        if not variant:
            raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

        return VariantContentResponse(
            module_id=module_id,
            variant_id=variant["id"],
            content=variant.get("content", ""),
            token_count=variant.get("token_count", 0)
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 获取变体内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/user/{user_id}/selections", response_model=UserSelectionsResponse)
async def get_user_variant_selections(user_id: str):
    """
    获取用户的变体选择记录

    Args:
        user_id: 用户ID

    Returns:
        用户选择的变体映射
    """
    selections = USER_VARIANT_SELECTIONS.get(user_id, {})
    return UserSelectionsResponse(user_id=user_id, selections=selections)


# ========== 用户自定义内容管理（恢复默认功能）==========

# 用户自定义内容存储：{user_key: {module_id: content}}
USER_CUSTOM_CONTENTS: dict[str, dict[str, str]] = {}


class SaveContentRequest(CamelCaseModel):
    """保存内容请求"""
    content: str
    user_id: str | None = "default"


class SaveContentResponse(CamelCaseModel):
    """保存内容响应"""
    success: bool
    module_id: str
    message: str


class ResetToDefaultResponse(CamelCaseModel):
    """恢复默认响应"""
    success: bool
    module_id: str
    content: str
    message: str


@router.post("/{module_id}/save", response_model=SaveContentResponse)
async def save_module_content(module_id: str, request: SaveContentRequest):
    """
    保存用户对模块内容的自定义修改

    Args:
        module_id: 模块ID
        request: {content: str, user_id: str}

    Returns:
        保存结果
    """
    try:
        user_key = f"{request.user_id or 'default'}"

        # 确保用户有存储空间
        if user_key not in USER_CUSTOM_CONTENTS:
            USER_CUSTOM_CONTENTS[user_key] = {}

        # 保存用户自定义内容
        USER_CUSTOM_CONTENTS[user_key][module_id] = request.content

        logging.info(f"[PromptVariantAPI] 用户 {user_key} 保存 {module_id} 自定义内容")

        return SaveContentResponse(
            success=True,
            module_id=module_id,
            message="内容保存成功"
        )
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 保存内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{module_id}/reset", response_model=ResetToDefaultResponse)
async def reset_to_default(module_id: str, user_id: str = "default"):
    """
    恢复模块内容到默认（从VARIANTS_DB读取默认内容）

    Args:
        module_id: 模块ID
        user_id: 用户ID

    Returns:
        默认内容
    """
    try:
        user_key = f"{user_id or 'default'}"

        # 获取默认变体的内容
        variants = VARIANTS_DB.get(module_id, [])
        default_variant = next((v for v in variants if v.get("is_default")), variants[0] if variants else None)

        if not default_variant:
            raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在默认内容")

        default_content = default_variant.get("content", "")

        # 清除用户的自定义内容（如果有）
        if user_key in USER_CUSTOM_CONTENTS and module_id in USER_CUSTOM_CONTENTS[user_key]:
            del USER_CUSTOM_CONTENTS[user_key][module_id]
            logging.info(f"[PromptVariantAPI] 用户 {user_key} 重置 {module_id} 到默认")

        return ResetToDefaultResponse(
            success=True,
            module_id=module_id,
            content=default_content,
            message="已恢复默认内容"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 恢复默认失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{module_id}/content", response_model=VariantContentResponse)
async def get_variant_content_with_custom(
    module_id: str,
    variant_id: str = "default",
    user_id: str = "default",
    use_custom: bool = True  # 是否使用用户自定义内容
):
    """
    获取变体内容（支持用户自定义覆盖）

    Args:
        module_id: 模块ID
        variant_id: 变体ID（默认default）
        user_id: 用户ID
        use_custom: 是否优先使用用户自定义内容

    Returns:
        变体内容（自动转换为camelCase）
    """
    try:
        user_key = f"{user_id or 'default'}"

        # 检查是否有用户自定义内容
        if use_custom and user_key in USER_CUSTOM_CONTENTS:
            custom_content = USER_CUSTOM_CONTENTS[user_key].get(module_id)
            if custom_content is not None:
                return VariantContentResponse(
                    module_id=module_id,
                    variant_id="custom",
                    content=custom_content,
                    token_count=len(custom_content) // 4  # 简单估算
                )

        # 否则返回默认变体内容
        user_selected = USER_VARIANT_SELECTIONS.get(user_key, {}).get(module_id)
        if user_selected:
            variant_id = user_selected

        variants = VARIANTS_DB.get(module_id, [])
        variant = next((v for v in variants if v["id"] == variant_id), None)

        if not variant:
            variant = next((v for v in variants if v.get("is_default")), variants[0] if variants else None)

        if not variant:
            raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

        return VariantContentResponse(
            module_id=module_id,
            variant_id=variant["id"],
            content=variant.get("content", ""),
            token_count=variant.get("token_count", 0)
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[PromptVariantAPI] 获取变体内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
