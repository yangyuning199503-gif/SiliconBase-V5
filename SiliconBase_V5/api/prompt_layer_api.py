#!/usr/bin/env python3
"""
提示词层级切换API - 游戏化L1/L2/L3层级系统

提供API端点用于：
1. 获取指定层级提示词 (L1概览/L2手册/L3详情)
2. 切换层级并触发语音播报
3. 获取工具分类和工具列表

【大纲规则3】切换时语音播报"正在查询中，请稍后"
"""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.logger import logger
from core.prompt.prompt_builder import (
    get_layered_prompt_builder,
)
from core.tool.tool_manager import tool_manager

# 导入认证依赖
try:
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    security = HTTPBearer(auto_error=False)
    HAS_AUTH = True
except ImportError:
    HAS_AUTH = False
    security = None

# 可选认证依赖
async def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security) if security else None) -> str:
    """可选认证，返回用户ID或default_user"""
    if not HAS_AUTH or credentials is None:
        return "default_user"
    try:
        from api.cloud_api import get_current_user as get_user
        return await get_user(credentials)
    except Exception:
        return "default_user"

router = APIRouter(
    prefix="/prompt/layer",
    tags=["提示词层级切换"]
)


# ============ 数据模型 ============

class LayerInfo(BaseModel):
    """层级信息"""
    layer: str = Field(..., description="层级标识: L1_OVERVIEW, L2_MANUAL, L3_TOOL_DETAIL")
    name: str = Field(..., description="层级名称")
    description: str = Field(..., description="层级描述")


class ToolCategory(BaseModel):
    """工具分类"""
    name: str = Field(..., description="分类名称")
    description: str = Field(..., description="分类描述")
    icon: str = Field(..., description="分类图标")
    count: int = Field(..., description="工具数量")


class ToolBrief(BaseModel):
    """工具简要信息（L2层使用）"""
    id: str = Field(..., description="工具ID")
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")


class ToolDetail(BaseModel):
    """工具详情（L3层使用）"""
    id: str = Field(..., description="工具ID")
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: dict = Field(default={}, description="参数定义")
    required: list[str] = Field(default=[], description="必填参数")
    example: dict | None = Field(default=None, description="使用示例")


class LayerPromptResponse(BaseModel):
    """层级提示词响应"""
    success: bool
    layer: str
    prompt: str
    data: dict
    voice_announcement: str = "正在查询中，请稍后"


class SwitchLayerRequest(BaseModel):
    """切换层级请求"""
    command: str = Field(..., description="切换命令: 首页/手册/返回/工具名")
    category: str | None = Field(default=None, description="L2层分类（可选）")
    tool_id: str | None = Field(default=None, description="L3层工具ID（可选）")


class LayerState(BaseModel):
    """当前层级状态"""
    current_layer: str
    current_tool: str | None
    available_commands: list[str]


# ============ API端点 ============

@router.get("/info", response_model=dict)
async def get_layer_info(user_id: str = Depends(get_current_user_optional)):
    """
    获取L1/L2/L3层级系统信息

    Returns:
        层级系统介绍和可用命令
    """
    return {
        "success": True,
        "data": {
            "layers": [
                {
                    "id": "L1_OVERVIEW",
                    "name": "L1概览层",
                    "description": "系统概览和工具分类列表",
                    "enter_commands": ["首页", "home", "概览", "overview"],
                    "features": ["显示8大工具分类", "显示各类别工具数量", "快速导航入口"]
                },
                {
                    "id": "L2_MANUAL",
                    "name": "L2工具手册层",
                    "description": "分类下的工具列表",
                    "enter_commands": ["手册", "manual", "目录", "menu", "工具列表"],
                    "features": ["按分类显示工具", "工具简要说明", "支持搜索筛选"],
                    "return_commands": ["首页", "home", "返回首页"]
                },
                {
                    "id": "L3_TOOL_DETAIL",
                    "name": "L3工具详情层",
                    "description": "具体工具的完整参数和使用示例",
                    "enter_commands": ["输入工具名称"],
                    "features": ["完整参数列表", "使用示例", "参数说明"],
                    "return_commands": ["手册", "manual", "返回手册", "返回"]
                }
            ],
            "voice_announcement": "正在查询中，请稍后",
            "navigation_tips": "输入'首页'进入L1，'手册'进入L2，工具名进入L3"
        }
    }


@router.get("/l1", response_model=LayerPromptResponse)
async def get_layer1(
    include_voice: bool = Query(default=True, description="是否触发语音播报"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    获取L1概览层提示词

    显示所有工具类别和各类别工具数量
    """
    try:
        builder = get_layered_prompt_builder()

        # 切换到L1层
        try:
            layer, prompt = builder.handle_layer_command("首页")
        except Exception as cmd_err:
            logger.error(f"[PromptLayerAPI] handle_layer_command 失败: {cmd_err}")
            import traceback
            logger.error(f"[PromptLayerAPI] handle_layer_command 堆栈: {traceback.format_exc()}")
            raise

        # 获取分类信息
        try:
            categories = tool_manager.get_tool_categories(use_functional=True)
            logger.debug(f"[PromptLayerAPI] 获取到 {len(categories)} 个分类")
            category_list = []
            for cat_name, info in sorted(categories.items()):
                if isinstance(info, dict):
                    category_list.append({
                        "name": cat_name,
                        "description": info.get("description", ""),
                        "icon": info.get("icon", ""),
                        "count": info.get("count", 0)
                    })
                else:
                    logger.warning(f"[PromptLayerAPI] 分类 '{cat_name}' 的信息不是字典: {type(info)} = {info}")
        except Exception as cat_err:
            logger.error(f"[PromptLayerAPI] 获取分类信息失败: {cat_err}")
            import traceback
            logger.error(f"[PromptLayerAPI] 分类信息堆栈: {traceback.format_exc()}")
            category_list = []

        return {
            "success": True,
            "layer": "L1_OVERVIEW",
            "prompt": prompt,
            "data": {
                "categories": category_list,
                "total_categories": len(category_list),
                "navigation": {
                    "current": "L1概览层",
                    "next": "L2手册层",
                    "enter_command": "手册"
                }
            },
            "voice_announcement": "正在查询中，请稍后"
        }
    except Exception as e:
        import traceback
        logger.error(f"[PromptLayerAPI] 获取L1层失败: {e}")
        logger.error(f"[PromptLayerAPI] 堆栈跟踪: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取L1层失败: {str(e)}") from e


@router.get("/l2", response_model=LayerPromptResponse)
async def get_layer2(
    category: str | None = Query(default=None, description="指定分类，不指定则显示所有"),
    include_voice: bool = Query(default=True, description="是否触发语音播报"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    获取L2工具手册层提示词

    显示指定分类或所有分类下的工具列表
    """
    try:
        builder = get_layered_prompt_builder()

        # 切换到L2层
        layer, prompt = builder.handle_layer_command("手册")

        # 获取工具列表
        if category:
            tools_by_cat = tool_manager.get_tools_by_category_v2(category)
        else:
            # 获取所有分类的工具
            tools_by_cat = {}
            categories = tool_manager.get_tool_categories(use_functional=True)
            for cat_name in categories:
                cat_tools = tool_manager.get_tools_by_category_v2(cat_name)
                tools_by_cat.update(cat_tools)

        # 格式化工具列表（带错误保护）
        formatted_tools = {}
        for cat_name, tools in tools_by_cat.items():
            formatted_tools[cat_name] = []
            if not isinstance(tools, list):
                logger.warning(f"[PromptLayerAPI] 分类 '{cat_name}' 的工具不是列表: {type(tools)}")
                continue
            for i, tool in enumerate(tools):
                try:
                    if not isinstance(tool, dict):
                        logger.warning(f"[PromptLayerAPI] 工具第{i}项不是字典: {type(tool)}")
                        continue
                    formatted_tools[cat_name].append({
                        "id": tool.get("id", "unknown"),
                        "name": tool.get("name", "未知"),
                        "description": tool.get("description", "")[:50] + "..."
                            if len(tool.get("description", "")) > 50
                            else tool.get("description", "")
                    })
                except Exception as tool_err:
                    logger.warning(f"[PromptLayerAPI] 格式化工具第{i}项失败: {tool_err}")
                    continue

        total_tools = sum(len(tools) for tools in formatted_tools.values())

        return {
            "success": True,
            "layer": "L2_MANUAL",
            "prompt": prompt,
            "data": {
                "category": category or "所有分类",
                "tools_by_category": formatted_tools,
                "total_tools": total_tools,
                "navigation": {
                    "current": "L2工具手册层",
                    "prev": "L1概览层",
                    "next": "L3工具详情层",
                    "return_command": "首页",
                    "enter_command": "输入工具名称"
                }
            },
            "voice_announcement": "正在查询中，请稍后"
        }
    except Exception as e:
        import traceback
        logger.error(f"[PromptLayerAPI] 获取L2层失败: {e}")
        logger.error(f"[PromptLayerAPI] 堆栈跟踪: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取L2层失败: {str(e)}") from e


@router.get("/l3/{tool_id}", response_model=LayerPromptResponse)
async def get_layer3(
    tool_id: str,
    include_voice: bool = Query(default=True, description="是否触发语音播报"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    获取L3工具详情层提示词

    显示指定工具的完整参数和使用示例
    """
    try:
        builder = get_layered_prompt_builder()

        # 切换到L3层
        layer, prompt = builder.handle_layer_command(tool_id)

        # 获取工具详情
        detail = tool_manager.get_tool_detail(tool_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"工具 '{tool_id}' 未找到")

        return {
            "success": True,
            "layer": "L3_TOOL_DETAIL",
            "prompt": prompt,
            "data": {
                "tool": {
                    "id": tool_id,
                    "name": detail.get("name", ""),
                    "description": detail.get("description", ""),
                    "parameters": detail.get("parameters", {}),
                    "required": detail.get("required", []),
                    "example": detail.get("example", {}),
                    "category": detail.get("category", ""),
                    "rarity": detail.get("rarity", "common")
                },
                "navigation": {
                    "current": "L3工具详情层",
                    "prev": "L2工具手册层",
                    "return_command": "手册",
                    "home_command": "首页"
                }
            },
            "voice_announcement": "正在查询中，请稍后"
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[PromptLayerAPI] 获取L3层失败: {e}")
        logger.error(f"[PromptLayerAPI] 堆栈跟踪: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取L3层失败: {str(e)}") from e


@router.post("/switch", response_model=LayerPromptResponse)
async def switch_layer(
    request: SwitchLayerRequest,
    include_voice: bool = Query(default=True, description="是否触发语音播报"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    切换提示词层级

    根据命令切换到指定层级并触发语音播报

    Args:
        request: 切换请求，包含command（首页/手册/返回/工具名）

    Returns:
        新层级的提示词和相关信息
    """
    try:
        builder = get_layered_prompt_builder()

        # 处理切换命令
        command = request.command
        layer, prompt = builder.handle_layer_command(command)

        # 构建响应数据
        layer_str = layer.value if hasattr(layer, 'value') else str(layer)

        # 根据当前层获取额外数据
        data = {
            "command": command,
            "navigation": {}
        }

        if layer_str == "L1_OVERVIEW":
            categories = tool_manager.get_tool_categories(use_functional=True)
            data["categories_count"] = len(categories)
            data["navigation"] = {
                "current": "L1概览层",
                "next": "L2手册层",
                "enter_command": "手册"
            }
        elif layer_str == "L2_MANUAL":
            data["navigation"] = {
                "current": "L2工具手册层",
                "prev": "L1概览层",
                "next": "L3工具详情层",
                "return_command": "首页",
                "enter_command": "输入工具名称"
            }
        elif layer_str == "L3_TOOL_DETAIL":
            current_tool = builder.get_current_tool()
            data["current_tool"] = current_tool
            data["navigation"] = {
                "current": "L3工具详情层",
                "prev": "L2工具手册层",
                "return_command": "手册",
                "home_command": "首页"
            }

        return {
            "success": True,
            "layer": layer_str,
            "prompt": prompt,
            "data": data,
            "voice_announcement": "正在查询中，请稍后"
        }
    except Exception as e:
        logger.error(f"[PromptLayerAPI] 切换层级失败: {e}")
        raise HTTPException(status_code=500, detail=f"切换层级失败: {str(e)}") from e


@router.get("/state", response_model=LayerState)
async def get_layer_state(user_id: str = Depends(get_current_user_optional)):
    """
    获取当前层级状态

    Returns:
        当前层级、选中工具和可用命令
    """
    try:
        builder = get_layered_prompt_builder()
        current_layer = builder.get_current_layer()
        current_tool = builder.get_current_tool()

        # 根据当前层确定可用命令
        available_commands = []
        layer_str = current_layer.value if hasattr(current_layer, 'value') else str(current_layer)

        if layer_str == "L1_OVERVIEW":
            available_commands = ["手册", "manual", "目录", "menu"]
        elif layer_str == "L2_MANUAL":
            available_commands = ["首页", "home", "返回首页", "<工具名称>"]
        elif layer_str == "L3_TOOL_DETAIL":
            available_commands = ["手册", "manual", "返回手册", "返回", "back", "首页", "home"]

        return {
            "current_layer": layer_str,
            "current_tool": current_tool,
            "available_commands": available_commands
        }
    except Exception as e:
        logger.error(f"[PromptLayerAPI] 获取层级状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取层级状态失败: {str(e)}") from e


@router.get("/categories", response_model=dict)
async def get_categories(user_id: str = Depends(get_current_user_optional)):
    """
    获取所有工具分类

    Returns:
        8大功能分类及其描述和工具数量
    """
    try:
        categories = tool_manager.get_tool_categories(use_functional=True)
        return {
            "success": True,
            "data": [
                {
                    "name": cat_name,
                    "description": info.get("description", ""),
                    "icon": info.get("icon", ""),
                    "count": info.get("count", 0)
                }
                for cat_name, info in sorted(categories.items())
            ]
        }
    except Exception as e:
        logger.error(f"[PromptLayerAPI] 获取分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取分类失败: {str(e)}") from e


@router.get("/tools", response_model=dict)
async def get_tools_by_category_api(
    category: str | None = Query(default=None, description="分类名称，不指定返回所有"),
    search: str | None = Query(default=None, description="搜索关键词"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    获取工具列表

    可按分类筛选或搜索
    """
    try:
        if category:
            tools_by_cat = tool_manager.get_tools_by_category_v2(category)
        else:
            tools_by_cat = {}
            categories = tool_manager.get_tool_categories(use_functional=True)
            for cat_name in categories:
                cat_tools = tool_manager.get_tools_by_category_v2(cat_name)
                tools_by_cat.update(cat_tools)

        # 搜索过滤
        if search:
            search_lower = search.lower()
            filtered = {}
            for cat_name, tools in tools_by_cat.items():
                filtered_tools = [
                    tool for tool in tools
                    if search_lower in tool["id"].lower() or search_lower in tool["name"].lower()
                ]
                if filtered_tools:
                    filtered[cat_name] = filtered_tools
            tools_by_cat = filtered

        total_tools = sum(len(tools) for tools in tools_by_cat.values())

        return {
            "success": True,
            "data": {
                "tools_by_category": tools_by_cat,
                "total_tools": total_tools,
                "filter": {
                    "category": category,
                    "search": search
                }
            }
        }
    except Exception as e:
        logger.error(f"[PromptLayerAPI] 获取工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}") from e
