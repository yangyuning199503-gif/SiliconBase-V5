"""
Tools API - 工具管理接口
提供工具分类、查询、测试、注册等功能

【安全修复记录】
  - 2026-03-01: 添加认证保护 (SEC-003)
    - 所有端点需要JWT认证
    - 未认证访问返回401

【功能增强记录】
  - 2026-03-08: 添加工具手册层级API (L1/L2/L3)
    - L1层：工具类别列表
    - L2层：类别下工具列表
    - L3层：工具详情
    - 支持层级切换语音播报
"""

import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.logger import logger

# 导入认证依赖
try:
    from api.cloud_api import get_current_user, user_auth_store
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .cloud_api import get_current_user, user_auth_store
        AUTH_AVAILABLE = True
    except ImportError:
        AUTH_AVAILABLE = False
        user_auth_store = None

        # 定义一个fallback依赖函数
        async def get_current_user() -> str | None:
            # 开发环境下返回默认用户
            return "default_user"

router = APIRouter(prefix="/tools", tags=["tools"])

# 废弃工具ID列表 - 这些工具会标记为deprecated但仍返回给前端
# 注意：用户自己添加的工具必须看得见，后端不过滤，只添加状态标记
# 2026-03-09 清理：已移除 clipboard_get 和 clipboard_set，它们是独立工具，不应标记为废弃
DEPRECATED_TOOLS = {
    # 当前无废弃工具
}


def _get_tool_status(tool_id: str, tool, user_id: str = None) -> dict:
    """
    获取工具的完整状态信息（支持云端+本地双版本管控）

    返回包含以下字段的字典:
    - enabled: bool - 是否启用
    - deprecated: bool - 是否废弃
    - deprecated_reason: str - 废弃原因
    - is_duplicate: bool - 是否功能重复
    - duplicate_of: str - 被哪个工具替代
    - owner: str - 工具所有者 (system/user/custom/platform)
    - executable: bool - 是否可执行（根据部署模式计算）
    - exec_restriction: str|None - 执行限制原因
    - warning: str|None - 警告信息

    【修复】添加异常处理，禁止静默失败
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        # 使用 tool_manager.get_tool_info 获取完整信息（含权限计算）
        from core.tool.tool_manager import tool_manager
        tool_info = tool_manager.get_tool_info(tool_id, user_id)

        if tool_info:
            # 返回完整信息，包括云端/本地权限计算结果
            return {
                'enabled': getattr(tool, 'enabled', True),
                'deprecated': tool_info.get('deprecated', False),
                'deprecated_reason': tool_info.get('deprecated_reason', ''),
                'is_duplicate': getattr(tool, 'is_duplicate', False) or tool_info.get('deprecated', False),
                'duplicate_of': tool_info.get('duplicate_of', ''),
                'owner': tool_info.get('owner', 'system'),
                'executable': tool_info.get('executable', True),
                'exec_restriction': tool_info.get('exec_restriction'),
                'warning': tool_info.get('warning')
            }
    except Exception as e:
        # 【修复】记录错误日志，不静默失败
        logger.error(f"[_get_tool_status] 获取工具信息失败 tool_id={tool_id}: {e}", exc_info=True)
        # 继续执行后备方案

    # 后备方案：直接读取工具属性
    try:
        # 检查是否在废弃列表中
        is_deprecated = tool_id in DEPRECATED_TOOLS
        deprecated_reason = DEPRECATED_TOOLS.get(tool_id, '') if is_deprecated else ''

        # 检查是否标记为重复（工具自身的属性优先）
        is_duplicate = getattr(tool, 'is_duplicate', False)
        if is_deprecated and not is_duplicate:
            is_duplicate = True

        # 获取被替代的工具ID
        duplicate_of = getattr(tool, 'duplicate_of', '')

        # 获取所有者
        owner = getattr(tool, 'tool_owner', 'system')

        # 获取部署模式（支持动态配置）
        try:
            from core.config import config
            deploy_mode = config.get_deploy_mode()
        except Exception as e:
            logger.error(f"[_get_tool_status] 获取部署模式失败: {e}", exc_info=True)
            deploy_mode = "local"  # 默认使用local模式

        # 根据部署模式计算执行权限
        if deploy_mode == "local":
            executable = True
            exec_restriction = None
            warning = None
        elif deploy_mode == "cloud":
            if is_deprecated and owner != "custom":
                executable = False
                exec_restriction = f"此工具已废弃，请使用 '{duplicate_of}' 替代" if duplicate_of else "此工具已废弃"
                warning = exec_restriction
            else:
                executable = True
                exec_restriction = None
                warning = None
        else:
            # hybrid 模式
            executable = owner == "custom" or not is_deprecated
            exec_restriction = None if executable else "此工具在当前模式下不可执行"
            warning = deprecated_reason if is_deprecated else None

        return {
            'enabled': getattr(tool, 'enabled', True),
            'deprecated': is_deprecated or getattr(tool, 'deprecated', False),
            'deprecated_reason': getattr(tool, 'deprecated_reason', deprecated_reason),
            'is_duplicate': is_duplicate,
            'duplicate_of': duplicate_of,
            'owner': owner,
            'executable': executable,
            'exec_restriction': exec_restriction,
            'warning': warning
        }
    except Exception as e:
        # 【修复】后备方案也失败时，记录ERROR日志并抛出异常
        logger.error(f"[_get_tool_status] 后备方案也失败 tool_id={tool_id}: {e}", exc_info=True)
        raise RuntimeError(f"无法获取工具状态: {tool_id}") from e


class ToolTestRequest(BaseModel):
    """工具测试请求模型"""
    params: dict[str, Any]


class ToolRegisterRequest(BaseModel):
    """工具注册请求模型"""
    name: str
    description: str
    code: str
    skip_sandbox: bool = False


class ToolExecuteRequest(BaseModel):
    """工具执行请求模型"""
    tool_id: str
    params: dict[str, Any]


class ToolValidateRequest(BaseModel):
    """工具验证请求模型"""
    tool_id: str
    params: dict[str, Any]


# ============ 工具手册层级API数据模型 ============

class ToolManualSwitchRequest(BaseModel):
    """工具手册层级切换请求模型"""
    target_layer: str  # "l1", "l2", "l3"
    context: dict[str, Any]  # { "category": "...", "tool_id": "..." }


class ToolManualL2Response(BaseModel):
    """L2层响应模型"""
    category: str
    tools: list[dict[str, Any]]
    total: int
    prompt_text: str


class ToolManualL3Response(BaseModel):
    """L3层响应模型"""
    tool_id: str
    name: str
    description: str
    parameters: list[dict[str, Any]]
    examples: list[str]
    prompt_text: str


# ============ 工具手册层级缓存 ============
_tool_manual_cache: dict[str, Any] = {}
_tool_manual_cache_time: float = 0
_TOOL_MANUAL_CACHE_TTL = 300  # 缓存5分钟


def _get_cache_key(*args) -> str:
    """生成缓存键"""
    key_str = json.dumps(args, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def _get_cached_data(key: str) -> Any | None:
    """获取缓存数据"""
    global _tool_manual_cache, _tool_manual_cache_time
    current_time = time.time()

    # 检查缓存是否过期
    if current_time - _tool_manual_cache_time > _TOOL_MANUAL_CACHE_TTL:
        _tool_manual_cache.clear()
        _tool_manual_cache_time = current_time
        return None

    return _tool_manual_cache.get(key)


def _set_cached_data(key: str, data: Any):
    """设置缓存数据"""
    global _tool_manual_cache, _tool_manual_cache_time
    if not _tool_manual_cache_time:
        _tool_manual_cache_time = time.time()
    _tool_manual_cache[key] = data


def _speak_querying():
    """触发语音播报'正在查询中，请稍后'"""
    try:
        from core.services.voice_service import speak
        from voice.voice_prompts import SystemAnnouncements
        speak(SystemAnnouncements.QUERYING, wait=False)
    except Exception:
        # 语音播报失败不影响主流程
        pass


# ============ 基础工具API ============

# 1. GET /api/tools - 获取所有工具列表
@router.get("/")
async def get_tools(
    user_id: str = Depends(get_current_user)
):
    """
    获取所有工具列表（支持云端+本地双版本管控）

    - **需要认证**: 需要有效的Bearer Token
    - **返回**: 所有工具的列表（包含废弃工具，但会标记状态）

    返回字段说明:
    - enabled: bool - 是否启用
    - deprecated: bool - 是否废弃
    - deprecated_reason: str - 废弃原因
    - is_duplicate: bool - 是否功能重复
    - owner: str - 工具所有者 (system/user/custom/platform)
    - executable: bool - 是否可执行（根据部署模式计算）
    - exec_restriction: str|None - 执行限制原因
    - warning: str|None - 警告信息
    """
    from core.tool.tool_manager import tool_manager
    tools = []
    for tool_id, tool in tool_manager.tools.items():
        # 获取工具状态（包含权限计算）
        status = _get_tool_status(tool_id, tool, user_id)
        tools.append({
            "id": tool_id,
            "name": getattr(tool, 'name', tool_id),
            "description": getattr(tool, 'description', ''),
            "category": getattr(tool, 'category', 'other'),
            **status
        })
    return {"success": True, "data": {"tools": tools}}


# 2. POST /api/tools/execute - 执行指定工具
@router.post("/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    user_id: str = Depends(get_current_user)
):
    """
    执行指定工具

    - **需要认证**: 需要有效的Bearer Token
    - **请求体**: tool_id(工具ID) + params(执行参数)
    - **返回**: 工具执行结果
    """
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(request.tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    try:
        result = await tool.run_async(**request.params)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# 3. GET /api/tools/categories - 获取工具分类
# 【重要】此路由必须在 /{tool_id} 之前定义，否则会被动态路由覆盖
@router.get("/categories")
async def get_tool_categories(
    user_id: str = Depends(get_current_user)
):
    """
    获取所有工具分类（支持云端+本地双版本管控）

    - **需要认证**: 需要有效的Bearer Token
    - **返回**: 按分类组织的工具列表（包含废弃工具，但会标记状态）

    【修复】添加异常处理，记录ERROR日志，禁止静默失败
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from core.tool.tool_manager import tool_manager

        # 检查 tool_manager 是否可用
        if not tool_manager:
            logger.error("[get_tool_categories] tool_manager 未初始化")
            raise HTTPException(status_code=500, detail="Tool manager not initialized")

        categories = {}
        tools_dict = tool_manager.tools

        # 检查 tools 是否可迭代
        if tools_dict is None:
            logger.error("[get_tool_categories] tool_manager.tools 返回 None")
            raise HTTPException(status_code=500, detail="Tool manager tools not available")

        for tool_id, tool in tools_dict.items():
            try:
                # 不过滤废弃工具，只添加状态标记
                cat = getattr(tool, 'category', 'other')
                if cat not in categories:
                    categories[cat] = []

                # 获取工具状态（包含权限计算）
                status = _get_tool_status(tool_id, tool, user_id)
                categories[cat].append({
                    "id": tool_id,
                    "name": getattr(tool, 'name', tool_id),
                    "description": getattr(tool, 'description', ''),
                    **status
                })
            except Exception as e:
                # 【修复】记录单个工具的错误，但继续处理其他工具
                logger.error(f"[get_tool_categories] 处理工具失败 tool_id={tool_id}: {e}", exc_info=True)
                continue

        # 转换为前端期望的格式
        result = [
            {"name": cat_name, "count": len(tools), "tools": tools}
            for cat_name, tools in categories.items()
        ]

        return {"success": True, "data": {"categories": result}}

    except HTTPException:
        raise
    except Exception as e:
        # 【修复】记录ERROR日志并抛出异常，禁止静默失败
        logger.error(f"[get_tool_categories] 获取工具分类失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get tool categories: {str(e)}") from e


# 4. GET /api/tools/search - 搜索工具
# 【重要】此路由必须在 /{tool_id} 之前定义，否则会被动态路由覆盖
@router.get("/search")
async def search_tools(
    query: str | None = None,  # 改为可选，同时支持 query 和 q
    q: str | None = None,      # 支持前端使用的 q 参数
    include_deprecated: bool = True,  # 是否包含废弃工具，默认包含
    user_id: str = Depends(get_current_user)
):
    """
    搜索工具

    - **需要认证**: 需要有效的Bearer Token
    - **查询参数**: query 或 q - 搜索关键词
    - **查询参数**: include_deprecated - 是否包含废弃工具（默认true）
    - **返回**: 匹配的工具列表（包含废弃工具，但会标记状态）
    """
    from core.tool.tool_manager import tool_manager

    # 优先使用 query 参数，如果为空则使用 q 参数
    search_term = query or q

    if not search_term:
        return {
            "success": True,
            "results": [],
            "message": "请提供搜索关键词 (query 或 q)"
        }

    results = []
    query_lower = search_term.lower()
    for tool_id, tool in tool_manager.tools.items():
        name = getattr(tool, 'name', tool_id).lower()
        desc = getattr(tool, 'description', '').lower()
        if query_lower in name or query_lower in desc:
            # 获取工具状态（包含权限计算）
            status = _get_tool_status(tool_id, tool, user_id)

            # 如果include_deprecated为false，则过滤掉废弃工具
            if not include_deprecated and status['deprecated']:
                continue

            results.append({
                "id": tool_id,
                "name": getattr(tool, 'name', tool_id),
                "description": getattr(tool, 'description', ''),
                **status
            })
    return {
        "success": True,
        "data": {
            "results": results,
            "query": search_term,
            "include_deprecated": include_deprecated
        }
    }


# 5. GET /api/tools/category/{category} - 获取分类下工具
# 【重要】此路由必须在 /{tool_id} 之前定义，否则会被动态路由覆盖
@router.get("/category/{category}")
async def get_tools_by_category(
    category: str,
    include_deprecated: bool = True,  # 是否包含废弃工具，默认包含
    user_id: str = Depends(get_current_user)
):
    '''
    获取指定分类的工具列表

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: category - 分类名称
    - **查询参数**: include_deprecated - 是否包含废弃工具（默认true）
    - **返回**: 该分类下的工具列表（包含废弃工具，但会标记状态）
    '''
    from core.tool.tool_manager import tool_manager
    tools = []
    for tool_id, tool in tool_manager.tools.items():
        if getattr(tool, 'category', 'other') == category:
            # 获取工具状态（包含权限计算）
            status = _get_tool_status(tool_id, tool, user_id)

            # 如果include_deprecated为false，则过滤掉废弃工具
            if not include_deprecated and status['deprecated']:
                continue

            tools.append({
                "id": tool_id,
                "name": getattr(tool, 'name', tool_id),
                "description": getattr(tool, 'description', ''),
                **status
            })
    return {"success": True, "data": {"category": category, "tools": tools, "include_deprecated": include_deprecated}}


# 6. GET /api/tools/{tool_id} - 获取工具详情
# 【注意】此动态路由必须在所有静态路由之后定义
@router.get("/{tool_id}")
async def get_tool(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    获取工具详情（支持云端+本地双版本管控）

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    - **返回**: 工具的详细信息，包含执行权限
    """
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")

    # 获取完整工具信息（含权限计算）
    tool_info = tool_manager.get_tool_info(tool_id, user_id)

    # 【静默失败阻断】tool_info为None时禁止崩溃，但记录ERROR
    if tool_info is None:
        logger.error(f"[SILENT_FAILURE_BLOCKED][ToolsAPI] get_tool_info返回None: tool_id={tool_id}, user_id={user_id}")
        # 使用默认值继续，但标记为降级模式
        tool_info = {}

    return {
        "success": True,
        "data": {
            "id": tool_id,
            "name": getattr(tool, 'name', tool_id),
            "description": getattr(tool, 'description', ''),
            "category": getattr(tool, 'category', 'other'),
            "schema": getattr(tool, 'input_schema', {}),
            "enabled": getattr(tool, 'enabled', True),
            "is_duplicate": getattr(tool, 'is_duplicate', False),
            "duplicate_of": getattr(tool, 'duplicate_of', ''),
            # 云端+本地双版本管控字段
            "owner": tool_info.get('owner', 'system'),
            "deprecated": tool_info.get('deprecated', False),
            "deprecated_reason": tool_info.get('deprecated_reason', ''),
            "executable": tool_info.get('executable', True),
            "exec_restriction": tool_info.get('exec_restriction'),
            "warning": tool_info.get('warning')
        }
    }


# 7. POST /api/tools/{tool_id}/execute - 执行特定工具
@router.post("/{tool_id}/execute")
async def execute_tool_by_id(
    tool_id: str,
    request: ToolTestRequest,
    user_id: str = Depends(get_current_user)
):
    """
    执行特定工具

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    - **请求体**: params(执行参数)
    - **返回**: 工具执行结果
    """
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    try:
        result = await tool.run_async(**request.params)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# 8. POST /api/tools/validate - 验证工具参数
@router.post("/validate")
async def validate_tool(
    request: ToolValidateRequest,
    user_id: str = Depends(get_current_user)
):
    """
    验证工具参数

    - **需要认证**: 需要有效的Bearer Token
    - **请求体**: tool_id(工具ID) + params(待验证参数)
    - **返回**: 验证结果
    """
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(request.tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")

    # 获取工具的输入schema
    schema = getattr(tool, 'input_schema', {})
    required_params = schema.get('required', [])
    schema.get('properties', {})

    # 验证必需参数
    missing_params = []
    for param in required_params:
        if param not in request.params:
            missing_params.append(param)

    if missing_params:
        return {
            "valid": False,
            "error": f"缺少必需参数: {', '.join(missing_params)}"
        }

    return {"valid": True, "message": "参数验证通过"}


# 9. GET /api/tools/schema/{tool_id} - 获取工具参数schema
@router.get("/schema/{tool_id}")
async def get_tool_schema(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    获取工具参数schema

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    - **返回**: 工具的输入参数schema定义
    """
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    return {
        "tool_id": tool_id,
        "name": getattr(tool, 'name', tool_id),
        "schema": getattr(tool, 'input_schema', {})
    }


# 保留原有端点以保持向后兼容性



# GET /api/tools/detail/{tool_id} - 获取工具详情(向后兼容)
@router.get("/detail/{tool_id}")
async def get_tool_detail(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    '''
    获取工具详细信息(向后兼容)

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    '''
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    return {
        "id": tool_id,
        "name": getattr(tool, 'name', tool_id),
        "description": getattr(tool, 'description', ''),
        "category": getattr(tool, 'category', 'other'),
        "schema": getattr(tool, 'input_schema', {}),
        "enabled": getattr(tool, 'enabled', True),
        "is_duplicate": getattr(tool, 'is_duplicate', False),
        "duplicate_of": getattr(tool, 'duplicate_of', '')
    }


# POST /api/tools/test/{tool_id} - 测试工具(向后兼容)
@router.post("/test/{tool_id}")
async def test_tool(
    tool_id: str,
    request: ToolTestRequest,
    user_id: str = Depends(get_current_user)
):
    '''
    测试工具执行(向后兼容)

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    '''
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    try:
        result = await tool.run_async(**request.params)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# POST /api/tools/toggle/{tool_id} - 启用/禁用工具
@router.post("/toggle/{tool_id}")
async def toggle_tool(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    '''
    切换工具启用状态

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    '''
    from core.tool.tool_manager import tool_manager
    tool = tool_manager.get_tool(tool_id)
    if not tool:
        raise HTTPException(404, "工具不存在")
    current = getattr(tool, 'enabled', True)
    tool.enabled = not current
    return {"success": True, "enabled": tool.enabled}


# POST /api/tools/delete/{tool_id} - 删除工具
@router.post("/delete/{tool_id}")
async def delete_tool(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    '''
    删除工具

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    '''
    from core.tool.tool_manager import tool_manager
    if tool_id not in tool_manager.tools:
        raise HTTPException(404, "工具不存在")
    del tool_manager.tools[tool_id]
    return {"success": True}


# POST /api/tools/register - 注册新工具
@router.post("/register")
async def register_tool(
    request: ToolRegisterRequest,
    user_id: str = Depends(get_current_user)
):
    '''
    注册新工具

    - **需要认证**: 需要有效的Bearer Token
    - **请求体**: 工具注册信息
    '''
    # 执行AST安全检查
    from core.safety.ast_security_checker import check_code_safety
    from core.tool.tool_manager import tool_manager
    is_safe, message = check_code_safety(request.code)
    if not is_safe:
        raise HTTPException(400, f"代码安全检查失败: {message}")

    # 真正注册：沙箱测试 + 持久化
    result = tool_manager.register_tool_from_code(
        code=request.code,
        skip_sandbox=request.skip_sandbox
    )

    if not result.get("success"):
        raise HTTPException(400, result.get("error", "工具注册失败"))

    return {
        "success": True,
        "tool_id": result.get("tool_id"),
        "message": f"工具 {result.get('tool_id')} 已热注册并持久化",
        "warnings": result.get("warnings", [])
    }


# ============ 工具手册层级API (L1/L2/L3) ============

# 1. GET /api/tools/tool-manual/l1 - 获取工具类别列表（L1层）
@router.get("/tool-manual/l1")
async def get_tool_manual_l1(
    user_id: str = Depends(get_current_user)
):
    """
    获取L1层概览 - 所有工具类别

    - **需要认证**: 需要有效的Bearer Token
    - **返回**: 工具类别列表和每个类别的工具数量
    """
    from core.tool.tool_manager import tool_manager

    # 检查缓存
    cache_key = _get_cache_key("l1", user_id)
    cached = _get_cached_data(cache_key)
    if cached:
        return {"success": True, "data": cached, "cached": True}

    try:
        # 按类别分组统计
        categories = {}
        for tool_id, tool in tool_manager.tools.items():
            cat = getattr(tool, 'category', 'other')
            if cat not in categories:
                categories[cat] = {
                    "name": cat,
                    "description": _get_category_description(cat),
                    "count": 0,
                    "tools": []
                }
            categories[cat]["count"] += 1
            categories[cat]["tools"].append({
                "id": tool_id,
                "name": getattr(tool, 'name', tool_id)
            })

        # 构建响应数据
        result = {
            "layer": "l1",
            "title": "工具手册 - 类别概览",
            "categories": list(categories.values()),
            "total_categories": len(categories),
            "total_tools": sum(c["count"] for c in categories.values())
        }

        # 设置缓存
        _set_cached_data(cache_key, result)

        return {"success": True, "data": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取L1层数据失败: {str(e)}") from e


# 2. GET /api/tools/tool-manual/l2/{category} - 获取工具手册L2层
@router.get("/tool-manual/l2/{category}")
async def get_tool_manual_l2(
    category: str,
    user_id: str = Depends(get_current_user)
):
    """
    获取L2层工具手册内容

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: category - 工具类别（file/app/web/memory等）
    - **返回**: 该类别下所有工具的简要说明
    """
    from core.tool.tool_manager import tool_manager

    # 检查缓存
    cache_key = _get_cache_key("l2", category, user_id)
    cached = _get_cached_data(cache_key)
    if cached:
        return {"success": True, "data": cached, "cached": True}

    try:
        # 获取该类别下的所有工具
        tools = []
        for tool_id, tool in tool_manager.tools.items():
            if getattr(tool, 'category', 'other') == category:
                # 构建参数摘要
                params_summary = []
                input_schema = getattr(tool, 'input_schema', {})
                if input_schema and 'properties' in input_schema:
                    required = set(input_schema.get('required', []))
                    for pname, pinfo in input_schema['properties'].items():
                        is_required = pname in required
                        ptype = pinfo.get('type', 'any')
                        params_summary.append({
                            "name": pname,
                            "type": ptype,
                            "required": is_required,
                            "description": pinfo.get('description', '')
                        })

                tools.append({
                    "id": tool_id,
                    "name": getattr(tool, 'name', tool_id),
                    "description": getattr(tool, 'description', ''),
                    "version": getattr(tool, 'version', '1.0.0'),
                    "timeout": getattr(tool, 'timeout', 30),
                    "params_count": len(params_summary),
                    "params_summary": params_summary
                })

        if not tools:
            raise HTTPException(status_code=404, detail=f"类别 '{category}' 不存在或没有工具")

        # 生成提示词文本
        prompt_lines = [
            f"📚 【工具手册 - {category}】",
            f"类别描述: {_get_category_description(category)}",
            f"工具数量: {len(tools)} 个",
            "",
            "📋 工具列表：",
            "─" * 50
        ]

        for tool in tools:
            prompt_lines.append(f"\n🔧 {tool['name']} ({tool['id']})")
            prompt_lines.append(f"   描述: {tool['description']}")
            if tool['params_summary']:
                prompt_lines.append(f"   参数: {len(tool['params_summary'])} 个")
                for p in tool['params_summary'][:3]:  # 只显示前3个参数
                    req_mark = "【必】" if p['required'] else "【选】"
                    prompt_lines.append(f"     - {p['name']}{req_mark}: {p['type']}")
                if len(tool['params_summary']) > 3:
                    prompt_lines.append(f"     ... 还有 {len(tool['params_summary']) - 3} 个参数")
            else:
                prompt_lines.append("   参数: 无")
            prompt_lines.append("")

        prompt_text = "\n".join(prompt_lines)

        # 构建响应数据
        result = {
            "layer": "l2",
            "category": category,
            "category_description": _get_category_description(category),
            "tools": tools,
            "total": len(tools),
            "prompt_text": prompt_text
        }

        # 设置缓存
        _set_cached_data(cache_key, result)

        return {"success": True, "data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取L2层数据失败: {str(e)}") from e


# 3. GET /api/tools/tool-manual/l3/{tool_id} - 获取工具详情L3层
@router.get("/tool-manual/l3/{tool_id}")
async def get_tool_manual_l3(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    获取L3层工具详情

    - **需要认证**: 需要有效的Bearer Token
    - **路径参数**: tool_id - 工具ID
    - **返回**: 工具的完整参数说明和使用示例
    """
    from core.tool.tool_manager import tool_manager

    # 检查缓存
    cache_key = _get_cache_key("l3", tool_id, user_id)
    cached = _get_cached_data(cache_key)
    if cached:
        return {"success": True, "data": cached, "cached": True}

    try:
        # 获取工具实例
        tool = tool_manager.get_tool(tool_id)
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具 '{tool_id}' 不存在")

        # 获取完整的参数信息
        input_schema = getattr(tool, 'input_schema', {})
        parameters = []

        if input_schema and 'properties' in input_schema:
            required = set(input_schema.get('required', []))
            for pname, pinfo in input_schema['properties'].items():
                param_info = {
                    "name": pname,
                    "type": pinfo.get('type', 'any'),
                    "description": pinfo.get('description', ''),
                    "required": pname in required,
                }
                # 添加可选字段
                if 'default' in pinfo:
                    param_info['default'] = pinfo['default']
                if 'enum' in pinfo:
                    param_info['enum'] = pinfo['enum']
                if 'minimum' in pinfo:
                    param_info['minimum'] = pinfo['minimum']
                if 'maximum' in pinfo:
                    param_info['maximum'] = pinfo['maximum']
                if 'pattern' in pinfo:
                    param_info['pattern'] = pinfo['pattern']

                parameters.append(param_info)

        # 生成使用示例
        examples = _generate_tool_examples(tool_id, tool, parameters)

        # 生成详细提示词文本
        prompt_lines = [
            f"📖 【工具详情 - {getattr(tool, 'name', tool_id)}】",
            f"工具ID: {tool_id}",
            f"版本: {getattr(tool, 'version', '1.0.0')}",
            f"分类: {getattr(tool, 'category', 'other')}",
            f"超时时间: {getattr(tool, 'timeout', 30)}秒",
            "",
            "📝 描述：",
            f"   {getattr(tool, 'description', '无描述')}",
            "",
        ]

        # 添加参数说明
        if parameters:
            prompt_lines.extend([
                "🔧 参数列表：",
                "─" * 50
            ])
            for p in parameters:
                req_mark = "【必需】" if p['required'] else "【可选】"
                prompt_lines.append(f"\n  • {p['name']} {req_mark}")
                prompt_lines.append(f"    类型: {p['type']}")
                prompt_lines.append(f"    描述: {p['description']}")
                if 'default' in p:
                    prompt_lines.append(f"    默认值: {p['default']}")
                if 'enum' in p:
                    prompt_lines.append(f"    可选值: {', '.join(map(str, p['enum']))}")
                if 'minimum' in p:
                    prompt_lines.append(f"    最小值: {p['minimum']}")
                if 'maximum' in p:
                    prompt_lines.append(f"    最大值: {p['maximum']}")
        else:
            prompt_lines.append("🔧 参数: 无参数")

        # 添加使用示例
        prompt_lines.extend([
            "",
            "💡 使用示例：",
            "─" * 50
        ])
        for i, example in enumerate(examples, 1):
            prompt_lines.append(f"\n  示例{i}:")
            prompt_lines.append(f"    {example}")

        # 添加注意事项
        if getattr(tool, 'require_confirmation', False):
            prompt_lines.extend([
                "",
                "⚠️ 注意事项：",
                "   此工具执行需要用户确认，请谨慎使用。"
            ])

        prompt_text = "\n".join(prompt_lines)

        # 构建响应数据
        result = {
            "layer": "l3",
            "tool_id": tool_id,
            "name": getattr(tool, 'name', tool_id),
            "description": getattr(tool, 'description', ''),
            "category": getattr(tool, 'category', 'other'),
            "version": getattr(tool, 'version', '1.0.0'),
            "timeout": getattr(tool, 'timeout', 30),
            "require_confirmation": getattr(tool, 'require_confirmation', False),
            "parameters": parameters,
            "examples": examples,
            "output_schema": getattr(tool, 'output_schema', {}),
            "prompt_text": prompt_text
        }

        # 设置缓存
        _set_cached_data(cache_key, result)

        return {"success": True, "data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取L3层数据失败: {str(e)}") from e


# 4. POST /api/tools/tool-manual/switch - 切换层级
@router.post("/tool-manual/switch")
async def switch_tool_manual_layer(
    request: ToolManualSwitchRequest,
    user_id: str = Depends(get_current_user)
):
    """
    切换工具手册层级

    - **需要认证**: 需要有效的Bearer Token
    - **触发语音播报**: "正在查询中，请稍后"
    - **返回**: 目标层级的提示词内容

    Args:
        target_layer: 目标层级 ("l1", "l2", "l3")
        context: 上下文信息 { "category": "...", "tool_id": "..." }
    """
    # 触发语音播报
    _speak_querying()

    try:
        target = request.target_layer.lower()
        context = request.context or {}

        if target == "l1":
            # 调用L1层接口
            result = await get_tool_manual_l1(user_id)
            return {
                "success": True,
                "data": {
                    "layer": "l1",
                    "content": result.get("data", {}),
                    "cached": result.get("cached", False)
                },
                "voice_triggered": True
            }

        elif target == "l2":
            category = context.get("category", "other")
            result = await get_tool_manual_l2(category, user_id)
            return {
                "success": True,
                "data": {
                    "layer": "l2",
                    "content": result.get("data", {}),
                    "cached": result.get("cached", False)
                },
                "voice_triggered": True
            }

        elif target == "l3":
            tool_id = context.get("tool_id", "")
            if not tool_id:
                raise HTTPException(status_code=400, detail="切换到L3层需要提供tool_id")
            result = await get_tool_manual_l3(tool_id, user_id)
            return {
                "success": True,
                "data": {
                    "layer": "l3",
                    "content": result.get("data", {}),
                    "cached": result.get("cached", False)
                },
                "voice_triggered": True
            }

        else:
            raise HTTPException(status_code=400, detail=f"无效的层级: {target}，可选值: l1, l2, l3")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"层级切换失败: {str(e)}") from e


# ============ 辅助函数 ============

def _get_category_description(category: str) -> str:
    """获取类别描述"""
    category_descriptions = {
        "file": "文件操作类工具，提供文件读写、复制、移动、删除等功能",
        "app": "应用操作类工具，用于启动、搜索、管理应用程序",
        "web": "网络通信类工具，支持网页搜索、HTTP请求、数据抓取等",
        "memory": "记忆管理类工具，用于添加、搜索、更新、删除记忆",
        "system": "系统控制类工具，提供系统信息查询、进程管理等功能",
        "input": "输入控制类工具，模拟键盘鼠标操作",
        "vision": "视觉识别类工具，支持截图、OCR、图像识别等功能",
        "media": "媒体处理类工具，处理图片、音频、视频等多媒体内容",
        "task": "任务管理类工具，创建和管理定时任务",
        "code": "代码开发类工具，辅助代码生成和执行",
        "data": "数据处理类工具，数据分析和转换",
        "security": "安全工具类，加密、哈希、安全检查等功能",
        "network": "网络通信类工具，VPN、网络诊断等",
        "other": "其他未分类工具"
    }
    return category_descriptions.get(category, f"{category}类别工具")


def _generate_tool_examples(tool_id: str, tool, parameters: list[dict]) -> list[str]:
    """生成工具使用示例"""
    examples = []

    # 基础示例：使用必需参数
    required_params = [p for p in parameters if p.get('required')]
    if required_params:
        example_params = []
        for p in required_params:
            ptype = p.get('type', 'any')
            if ptype == 'string':
                example_value = f'"{p["name"]}_value"'
            elif ptype == 'integer':
                example_value = '42'
            elif ptype == 'number':
                example_value = '3.14'
            elif ptype == 'boolean':
                example_value = 'true'
            elif ptype == 'array':
                example_value = '[]'
            elif ptype == 'object':
                example_value = '{}'
            else:
                example_value = f'"{p["name"]}"'
            example_params.append(f'{p["name"]}={example_value}')

        examples.append(f'{tool_id}({", ".join(example_params)})')
    else:
        examples.append(f'{tool_id}()')

    # 如果有可选参数，添加一个完整示例
    optional_params = [p for p in parameters if not p.get('required')]
    if optional_params and len(parameters) <= 5:  # 参数不多时添加完整示例
        all_params = []
        for p in parameters:
            ptype = p.get('type', 'any')
            if ptype == 'string':
                example_value = f'"{p["name"]}_value"'
            elif ptype == 'integer':
                example_value = '42'
            elif ptype == 'number':
                example_value = '3.14'
            elif ptype == 'boolean':
                example_value = 'true'
            elif ptype == 'array':
                example_value = '[]'
            elif ptype == 'object':
                example_value = '{}'
            else:
                example_value = f'"{p["name"]}"'
            all_params.append(f'{p["name"]}={example_value}')

        examples.append(f'{tool_id}({", ".join(all_params)})')

    # 如果没有生成示例，添加一个通用示例
    if not examples:
        examples.append(f'{tool_id}()')

    return examples


# ============ 缓存管理API ============

@router.post("/tool-manual/clear-cache")
async def clear_tool_manual_cache(
    user_id: str = Depends(get_current_user)
):
    """
    清除工具手册缓存

    - **需要认证**: 需要有效的Bearer Token
    - **用途**: 工具更新后刷新缓存
    """
    global _tool_manual_cache, _tool_manual_cache_time
    _tool_manual_cache.clear()
    _tool_manual_cache_time = 0
    return {"success": True, "message": "工具手册缓存已清除"}


@router.get("/tool-manual/cache-status")
async def get_tool_manual_cache_status(
    user_id: str = Depends(get_current_user)
):
    """
    获取工具手册缓存状态

    - **需要认证**: 需要有效的Bearer Token
    """
    global _tool_manual_cache, _tool_manual_cache_time
    current_time = time.time()

    return {
        "success": True,
        "data": {
            "cache_enabled": True,
            "cache_ttl_seconds": _TOOL_MANUAL_CACHE_TTL,
            "cached_keys": list(_tool_manual_cache.keys()),
            "cache_count": len(_tool_manual_cache),
            "cache_age_seconds": current_time - _tool_manual_cache_time if _tool_manual_cache_time else None,
            "is_expired": (current_time - _tool_manual_cache_time > _TOOL_MANUAL_CACHE_TTL) if _tool_manual_cache_time else True
        }
    }
