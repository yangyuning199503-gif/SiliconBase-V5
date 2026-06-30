#!/usr/bin/env python3
"""
提示词管理API
提供前端接口用于：
1. 获取可用提示词模块
2. 保存/加载模块选择
3. 预览提示词效果
4. 切换角色
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.logger import logger
from core.prompt.prompt_builder_v2 import get_prompt_builder
from core.prompt.prompt_debugger import estimate_tokens, get_last_prompt, get_last_prompt_preview

# 导入认证依赖（SEC-003修复）
try:
    from api.cloud_api import get_current_user
except ImportError:
    async def get_current_user() -> str:
        return "default_user"

router = APIRouter(
    prefix="/prompt",
    tags=["提示词管理"],
    dependencies=[Depends(get_current_user)]
)


# ============ 数据模型 ============

class ModuleInfo(BaseModel):
    id: str
    name: str
    description: str
    optional: bool
    default: bool
    order: int
    category: str
    content: str | None = None  # 模块内容（可选）


class RoleInfo(BaseModel):
    id: str
    name: str
    description: str


class SaveSelectionRequest(BaseModel):
    user_id: str
    selected_modules: list[str]


class BuildPromptRequest(BaseModel):
    role: str = "assistant"
    selected_modules: list[str] | None = None
    user_id: str | None = None
    variables: dict[str, str] | None = None


class PromptResponse(BaseModel):
    prompt: str
    modules_used: list[str]
    estimated_tokens: int
    variables_used: dict[str, str]


class PreviewRequest(BaseModel):
    module_id: str


# ============ API端点 ============

@router.get("/modules")
async def get_modules(role: str = "assistant"):
    """
    获取所有可用的提示词模块

    Args:
        role: 角色ID，用于过滤模块

    Returns:
        统一格式响应，data字段包含模块列表
    """
    try:
        builder = get_prompt_builder()
        modules = builder.get_available_modules(role)
        # 返回统一格式 {success, data}
        return {
            "success": True,
            "data": [ModuleInfo(**m).model_dump() for m in modules]
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取模块失败: {e}")
        return {
            "success": False,
            "data": [],
            "message": str(e)
        }


@router.get("/roles")
async def get_roles():
    """获取所有可用角色"""
    try:
        builder = get_prompt_builder()
        roles = builder.get_roles()
        # 返回统一格式 {success, data}
        return {
            "success": True,
            "data": [RoleInfo(**r).model_dump() for r in roles]
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取角色失败: {e}")
        return {
            "success": False,
            "data": [],
            "message": str(e)
        }


@router.get("/default-modules/{role}")
async def get_default_modules(role: str):
    """获取角色的默认模块选择"""
    try:
        builder = get_prompt_builder()
        modules = builder.get_role_default_modules(role)
        return {"role": role, "default_modules": modules}
    except Exception as e:
        logger.error(f"[PromptAPI] 获取默认模块失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/user-selection/{user_id}")
async def get_user_selection(user_id: str, role: str = "assistant"):
    """获取用户的模块选择偏好"""
    try:
        builder = get_prompt_builder()
        modules = builder.get_user_selection(user_id, role)
        return {"user_id": user_id, "selected_modules": modules}
    except Exception as e:
        logger.error(f"[PromptAPI] 获取用户选择失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/modules/{module_id}/default")
async def get_module_default_content(module_id: str):
    """
    获取模块的默认内容（用于恢复默认）

    Args:
        module_id: 模块ID

    Returns:
        模块的默认内容
    """
    try:
        builder = get_prompt_builder()

        # 从系统模块或可选模块中查找
        default_content = None
        if module_id in builder._system_modules:
            default_content = builder._system_modules[module_id].content
        elif module_id in builder._optional_modules:
            default_content = builder._optional_modules[module_id].content

        if default_content is None:
            raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

        return {
            "success": True,
            "module_id": module_id,
            "content": default_content,
            "message": "默认内容获取成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PromptAPI] 获取默认内容失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/save-selection")
async def save_selection(request: SaveSelectionRequest):
    """保存用户的模块选择偏好"""
    try:
        builder = get_prompt_builder()
        builder.save_user_selection(request.user_id, request.selected_modules)
        return {
            "success": True,
            "message": f"已保存用户 {request.user_id} 的模块选择",
            "selected_modules": request.selected_modules
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 保存选择失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/build", response_model=PromptResponse)
async def build_prompt(request: BuildPromptRequest):
    """
    构建提示词（用于预览）

    Args:
        role: 角色
        selected_modules: 选中的模块（如果为null则使用用户保存的偏好）
        user_id: 用户ID
        variables: 变量替换

    Returns:
        构建的提示词及元数据
    """
    try:
        builder = get_prompt_builder()
        result = builder.build_prompt_with_metadata(
            role=request.role,
            selected_modules=request.selected_modules,
            user_id=request.user_id,
            variables=request.variables
        )
        return PromptResponse(**result)
    except Exception as e:
        logger.error(f"[PromptAPI] 构建提示词失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/preview-module")
async def preview_module(request: PreviewRequest):
    """预览单个模块的内容"""
    try:
        builder = get_prompt_builder()
        content = builder.preview_module(request.module_id)
        if content is None:
            raise HTTPException(status_code=404, detail=f"模块 {request.module_id} 不存在")
        return {"module_id": request.module_id, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PromptAPI] 预览模块失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/reload")
async def reload_config():
    """热重载 roles.yaml 配置（管理员用）"""
    try:
        builder = get_prompt_builder()
        builder.reload_config()
        return {"success": True, "message": "配置已热重载"}
    except Exception as e:
        logger.error(f"[PromptAPI] 热重载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ============ 提示词调试API ============

class LastPromptResponse(BaseModel):
    """最后一次提示词响应"""
    full_prompt: str
    components: list[dict]
    timestamp: float
    formatted_time: str
    total_tokens: int
    preview: str
    query: str | None = None
    session_id: str | None = None


@router.get("/debug/last-prompt")
async def get_last_prompt_api(user=Depends(get_current_user)):
    """
    获取最后一次发送给AI的完整system_prompt

    包括：基础提示词 + 记忆注入 + 经验注入 + 三观提示词 + 层级提示等
    """
    try:
        user_id = user if isinstance(user, str) else getattr(user, 'id', 'default_user')
        debug_info = get_last_prompt(user_id)

        if not debug_info:
            return {
                "success": False,
                "message": "暂无提示词记录，请先进行一次对话",
                "data": None
            }

        return {
            "success": True,
            "data": debug_info
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取最后提示词失败: {e}")
        return {
            "success": False,
            "message": f"获取失败: {str(e)}",
            "data": None
        }


@router.get("/debug/last-prompt-preview")
async def get_last_prompt_preview_api(max_length: int = 500, user=Depends(get_current_user)):
    """获取最后一次提示词的预览（简短版本）"""
    try:
        user_id = user if isinstance(user, str) else getattr(user, 'id', 'default_user')
        preview = get_last_prompt_preview(user_id, max_length)

        if not preview:
            return {
                "success": False,
                "message": "暂无提示词记录",
                "data": None
            }

        return {
            "success": True,
            "data": {
                "preview": preview,
                "token_count": estimate_tokens(preview)
            }
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取提示词预览失败: {e}")
        return {
            "success": False,
            "message": f"获取失败: {str(e)}",
            "data": None
        }


@router.post("/debug/estimate-tokens")
async def estimate_tokens_api(request: dict):
    """估算文本的token数量"""
    try:
        text = request.get("text", "")
        return {
            "success": True,
            "data": {
                "text_length": len(text),
                "estimated_tokens": estimate_tokens(text)
            }
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "data": None
        }


# ============ 模块管理API ============

class SaveModuleRequest(BaseModel):
    """保存模块请求"""
    module_id: str
    content: str
    mode: str = "user"  # 'user' 或 'global'


@router.post("/modules")
async def save_module(request: SaveModuleRequest, user=Depends(get_current_user)):
    """保存模块内容（支持用户级覆盖）"""
    try:
        from core.config import config
        if request.mode == "global":
            # 全局模式需要检查管理员权限（简化实现）
            pass
        success = config.set_user_prompt_module(user, request.module_id, request.content)
        return {
            "success": success,
            "message": f"模块 {request.module_id} 已保存" if success else "保存失败",
            "module_id": request.module_id
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 保存模块失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/user-module-config/{module_id}")
async def get_user_module_config(module_id: str, user=Depends(get_current_user)):
    """获取用户模块级覆盖配置"""
    try:
        from core.config import config
        content = config.get_user_prompt_module(user, module_id)
        has_override = content is not None
        return {
            "success": True,
            "module_id": module_id,
            "config": {"content": content} if content else {},
            "has_override": has_override
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取用户模块配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/user-module-config/{module_id}")
async def delete_user_module_config(module_id: str, user=Depends(get_current_user)):
    """删除用户模块级覆盖配置（恢复全局默认）"""
    try:
        from core.config import config
        success = config.delete_user_prompt_module(user, module_id)
        return {
            "success": success,
            "message": "已恢复全局默认" if success else "无需恢复",
            "module_id": module_id
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 删除用户模块配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/check-admin")
async def check_admin(user=Depends(get_current_user)):
    """检查当前用户是否为管理员"""
    is_admin = user in ["admin", "root", "siliconbase"] or "admin" in str(user).lower()
    return {"success": True, "is_admin": is_admin}


# ============ 前端快捷API ============

@router.get("/config-for-frontend")
async def get_config_for_frontend(user_id: str | None = None, role: str = "assistant"):
    """
    获取前端需要的完整配置

    一次性返回：
    - 所有可用模块
    - 所有角色
    - 用户的当前选择

    Returns:
        统一格式响应，data字段包含完整配置
    """
    try:
        builder = get_prompt_builder()

        # 获取模块列表，统一使用 ModuleInfo 序列化（与 /modules 端点一致）
        modules = builder.get_available_modules(role)
        roles = builder.get_roles()

        # 将模块按 category 分组为 system 和 optional
        system_modules = [ModuleInfo(**m).model_dump() for m in modules if m.get("category") == "system" or not m.get("optional", False)]
        optional_modules = [ModuleInfo(**m).model_dump() for m in modules if m.get("category") == "optional" or m.get("optional", False)]

        return {
            "success": True,
            "data": {
                "modules": {
                    "system": system_modules,
                    "optional": optional_modules
                },
                "roles": [RoleInfo(**r).model_dump() for r in roles],
                "user_selection": builder.get_user_selection(user_id, role) if user_id else builder.get_role_default_modules(role),
                "role_default": {
                    r["id"]: builder.get_role_default_modules(r["id"])
                    for r in roles
                }
            }
        }
    except Exception as e:
        logger.error(f"[PromptAPI] 获取前端配置失败: {e}")
        import traceback
        logger.error(f"[PromptAPI] 堆栈: {traceback.format_exc()}")
        return {
            "success": False,
            "data": {
                "modules": {"system": [], "optional": []},
                "roles": [],
                "user_selection": [],
                "role_default": {}
            },
            "message": str(e)
        }
