#!/usr/bin/env python3
"""
工具手册工具 - 游戏化L1/L2/L3分层查询系统

支持三种查询模式：
- L1: 概览层 - 显示所有工具类别和数量
- L2: 工具手册层 - 显示某类别下的工具列表
- L3: 工具详情层 - 显示具体工具的完整参数

【大纲规则3】切换时语音播报"正在查询中，请稍后"
"""
import asyncio

from core.base_tool import BaseTool
from core.work_mode_manager import get_work_mode_manager


class GetToolManual(BaseTool):
    """基础工具手册 - 返回所有工具信息"""
    tool_id = "get_tool_manual"
    name = "获取工具手册"
    description = (
        "返回当前模式下所有可用工具的详细信息，包括工具ID、名称、描述、参数列表（含名称、类型、是否必需等）。"
        "返回结构化JSON，便于解析。同时提供文本摘要供快速阅读。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "可选，按工具ID或名称关键词过滤"
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        from core.tool_manager import tool_manager

        filter_keyword = kwargs.get("filter", "").strip().lower()
        mode = get_work_mode_manager().get_current_mode().value

        all_tools = tool_manager.list_tools_structured(mode=mode)

        if filter_keyword:
            all_tools = [
                t for t in all_tools
                if filter_keyword in t["id"].lower() or filter_keyword in t["name"].lower()
            ]

        summary_lines = [f"当前模式 {mode} 下有 {len(all_tools)} 个可用工具："]
        for t in all_tools[:10]:
            params_desc = ", ".join([
                f"{p['name']}({p['type']}){'必' if p['required'] else '选'}"
                for p in t["params"]
            ])
            summary_lines.append(f"- {t['id']}: {t['name']} - 参数: {params_desc}")
        if len(all_tools) > 10:
            summary_lines.append(f"... 还有 {len(all_tools)-10} 个工具，请查看完整JSON。")

        return {
            "success": True,
            "error_code": None,
            "user_message": f"已返回 {len(all_tools)} 个工具的详细手册",
            "data": {
                "tools": all_tools,
                "summary": "\n".join(summary_lines),
                "count": len(all_tools)
            }
        }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetToolCategoriesL1(BaseTool):
    """
    L1概览层 - 获取工具分类概览

    显示所有工具类别和各类别工具数量
    输入"首页"或"概览"进入此层
    """
    tool_id = "get_tool_categories_l1"
    name = "L1工具分类概览"
    description = (
        "【L1概览层】显示所有工具类别的概览信息，包括类别名称、描述和工具数量。"
        "返回8大功能分类：📋 任务管理、📁 文件操作、🔧 系统控制、🌐 网络通信、"
        "📊 数据处理、🎵 媒体处理、💻 代码开发、🔐 安全工具。"
        "使用示例：输入'首页'或'概览'查看工具分类总览。"
    )
    input_schema = {
        "type": "object",
        "properties": {}
    }

    def _execute(self, **kwargs) -> dict:
        from core.tool_manager import tool_manager

        try:
            categories = tool_manager.get_tool_categories(use_functional=True)

            category_list = []
            summary_lines = ["【L1概览层】工具分类总览：\n"]

            for cat_name, info in sorted(categories.items()):
                cat_data = {
                    "name": cat_name,
                    "description": info.get("description", ""),
                    "icon": info.get("icon", cat_name.split()[0] if " " in cat_name else "📦"),
                    "count": info.get("count", 0)
                }
                category_list.append(cat_data)
                summary_lines.append(f"  {cat_data['icon']} {cat_name}: {cat_data['count']}个工具")

            total_tools = sum(c.get("count", 0) for c in category_list)

            summary_lines.append(f"\n共计 {len(category_list)} 个分类，{total_tools} 个工具")
            summary_lines.append("\n【操作指引】输入'手册'进入L2查看工具列表")

            return {
                "success": True,
                "error_code": None,
                "user_message": f"当前共有 {len(category_list)} 个工具分类，{total_tools} 个工具。输入'手册'查看详细列表。",
                "data": {
                    "categories": category_list,
                    "total_categories": len(category_list),
                    "total_tools": total_tools,
                    "layer": "L1_OVERVIEW",
                    "summary": "\n".join(summary_lines),
                    "voice_announcement": "正在查询中，请稍后"
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "user_message": f"获取工具分类失败: {str(e)}"
            }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetToolsByCategoryL2(BaseTool):
    """
    L2工具手册层 - 按分类获取工具列表

    显示指定类别下的所有工具简要信息
    输入"手册"或"目录"进入此层
    """
    tool_id = "get_tools_by_category_l2"
    name = "L2分类工具列表"
    description = (
        "【L2工具手册层】按分类显示工具列表，每个工具显示ID、名称和简要描述。"
        "支持查看所有分类或指定分类。"
        "使用示例：输入'手册'查看所有工具，或指定分类如'📁 文件操作'。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "分类名称（如'📁 文件操作'），不指定则显示所有分类"
            },
            "search": {
                "type": "string",
                "description": "搜索关键词，按工具ID或名称过滤"
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        from core.tool_manager import tool_manager

        try:
            category = kwargs.get("category", "").strip()
            search = kwargs.get("search", "").strip().lower()

            # 获取工具列表
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
                filtered = {}
                for cat_name, tools in tools_by_cat.items():
                    filtered_tools = [
                        tool for tool in tools
                        if search in tool.get("id", "").lower()
                        or search in tool.get("name", "").lower()
                    ]
                    if filtered_tools:
                        filtered[cat_name] = filtered_tools
                tools_by_cat = filtered

            # 格式化输出
            result = {}
            summary_lines = ["【L2工具手册层】工具列表：\n"]
            total_tools = 0

            for cat_name, tools in sorted(tools_by_cat.items()):
                result[cat_name] = []
                summary_lines.append(f"\n【{cat_name}】")

                for tool in tools:
                    tool_data = {
                        "id": tool.get("id", ""),
                        "name": tool.get("name", ""),
                        "description": tool.get("description", "")[:60] + "..."
                                      if len(tool.get("description", "")) > 60
                                      else tool.get("description", "")
                    }
                    result[cat_name].append(tool_data)
                    summary_lines.append(f"  • {tool_data['id']}: {tool_data['name']}")

                total_tools += len(tools)

            summary_lines.append(f"\n共计 {total_tools} 个工具")
            summary_lines.append("\n【操作指引】输入工具名查看详情(L3)，输入'首页'返回L1")

            return {
                "success": True,
                "error_code": None,
                "user_message": f"找到 {total_tools} 个工具。输入工具名称查看详情，或输入'首页'返回概览。",
                "data": {
                    "category": category or "所有分类",
                    "tools_by_category": result,
                    "total_tools": total_tools,
                    "layer": "L2_MANUAL",
                    "summary": "\n".join(summary_lines),
                    "voice_announcement": "正在查询中，请稍后"
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "user_message": f"获取工具列表失败: {str(e)}"
            }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetToolDetailL3(BaseTool):
    """
    L3工具详情层 - 获取单个工具的详细信息

    显示具体工具的完整参数、使用示例等
    输入工具名称进入此层
    """
    tool_id = "get_tool_detail_l3"
    name = "L3工具详情查询"
    description = (
        "【L3工具详情层】获取指定工具的完整信息，包括功能描述、参数列表、"
        "必填参数和使用示例。输入工具ID或名称查看详情。"
        "使用示例：输入'screenshot'查看截图工具的详细参数。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "tool_id": {
                "type": "string",
                "description": "工具ID或名称（如'screenshot'、'file_manager'等）"
            }
        },
        "required": ["tool_id"]
    }

    def _execute(self, **kwargs) -> dict:
        import json

        from core.tool_manager import tool_manager

        try:
            tool_id = kwargs.get("tool_id", "").strip()
            if not tool_id:
                return {
                    "success": False,
                    "error_code": "INVALID_PARAMS",
                    "user_message": "请输入工具名称或ID",
                    "data": None
                }

            detail = tool_manager.get_tool_detail(tool_id)
            if not detail:
                # 尝试搜索匹配
                all_tools = tool_manager.list_tools()
                matches = [
                    t for t in all_tools
                    if tool_id.lower() in t.get("id", "").lower()
                    or tool_id.lower() in t.get("name", "").lower()
                ]

                if matches:
                    suggestions = ", ".join([t.get("id", "") for t in matches[:5]])
                    return {
                        "success": False,
                        "error_code": "TOOL_NOT_FOUND",
                        "user_message": f"未找到工具 '{tool_id}'。您是否想找：{suggestions}？",
                        "data": {"suggestions": [t.get("id", "") for t in matches[:5]]}
                    }
                else:
                    return {
                        "success": False,
                        "error_code": "TOOL_NOT_FOUND",
                        "user_message": f"未找到工具 '{tool_id}'。输入'手册'查看所有工具。",
                        "data": None
                    }

            # 格式化参数信息
            params_str = ""
            parameters = detail.get("parameters", {})
            if parameters:
                for param_name, param_info in parameters.items():
                    if isinstance(param_info, dict):
                        desc = param_info.get("description", "无描述")
                        param_type = param_info.get("type", "any")
                        required = "必填" if param_info.get("required", False) else "可选"
                        params_str += f"  • {param_name} ({param_type}, {required}): {desc}\n"
                    else:
                        params_str += f"  • {param_name}: {param_info}\n"
            else:
                params_str = "  (该工具无需参数)"

            # 格式化示例
            example = detail.get("example", {})
            example_str = json.dumps(example, ensure_ascii=False, indent=2) if example else "暂无示例"

            summary_lines = [
                f"【L3工具详情层】{detail.get('name', tool_id)}",
                f"\n工具ID: {tool_id}",
                f"描述: {detail.get('description', '无描述')}",
                "\n【参数说明】",
                params_str,
                "\n【使用示例】",
                example_str,
                "\n\n【操作指引】输入'手册'返回L2，输入'首页'返回L1"
            ]

            return {
                "success": True,
                "error_code": None,
                "user_message": f"已显示 '{detail.get('name', tool_id)}' 的详细信息。输入'手册'返回工具列表。",
                "data": {
                    "tool_id": tool_id,
                    "name": detail.get("name", ""),
                    "description": detail.get("description", ""),
                    "parameters": detail.get("parameters", {}),
                    "required": detail.get("required", []),
                    "example": example,
                    "category": detail.get("category", ""),
                    "rarity": detail.get("rarity", "common"),
                    "layer": "L3_TOOL_DETAIL",
                    "summary": "\n".join(summary_lines),
                    "voice_announcement": "正在查询中，请稍后"
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": "EXECUTION_ERROR",
                "user_message": f"获取工具详情失败: {str(e)}",
                "data": None
            }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class SwitchPromptLayer(BaseTool):
    """
    提示词层级切换工具

    统一处理L1/L2/L3层级切换，自动触发语音播报
    【大纲规则3】切换时语音播报"正在查询中，请稍后"
    """
    tool_id = "switch_prompt_layer"
    name = "切换提示词层级"
    description = (
        "在游戏化提示词系统的L1/L2/L3三层之间切换。"
        "L1概览层显示工具分类，L2手册层显示工具列表，L3详情层显示工具参数。"
        "切换命令：'首页'(L1)、'手册'(L2)、'返回'(L2)、工具名(L3)。"
        "【注意】切换时会自动播报'正在查询中，请稍后'"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "切换命令：首页/手册/返回/工具名"
            },
            "tool_id": {
                "type": "string",
                "description": "可选，切换到L3时指定的工具ID"
            }
        },
        "required": ["command"]
    }

    def _execute(self, **kwargs) -> dict:
        from core.prompt_builder import get_layered_prompt_builder


        try:
            command = kwargs.get("command", "").strip()
            tool_id = kwargs.get("tool_id", "").strip()

            if not command:
                return {
                    "success": False,
                    "error_code": "INVALID_PARAMS",
                    "user_message": "请输入切换命令：首页/手册/返回/工具名",
                    "data": None
                }

            builder = get_layered_prompt_builder()

            # 如果提供了tool_id，优先使用
            if tool_id:
                command = tool_id

            # 处理切换命令
            layer, prompt = builder.handle_layer_command(command)
            layer_str = layer.value if hasattr(layer, 'value') else str(layer)

            # 确定层级名称
            layer_names = {
                "L1_OVERVIEW": "L1概览层",
                "L2_MANUAL": "L2工具手册层",
                "L3_TOOL_DETAIL": "L3工具详情层"
            }
            layer_name = layer_names.get(layer_str, layer_str)

            # 构建响应
            nav_data = {}
            if layer_str == "L3_TOOL_DETAIL":
                nav_data = {
                    "current_tool": builder.get_current_tool(),
                    "navigation": {
                        "prev": "L2工具手册层",
                        "commands": ["手册", "返回"]
                    }
                }
            elif layer_str == "L2_MANUAL":
                nav_data = {
                    "navigation": {
                        "prev": "L1概览层",
                        "next": "L3工具详情层",
                        "commands": ["首页", "<工具名>"]
                    }
                }
            else:  # L1
                nav_data = {
                    "navigation": {
                        "next": "L2工具手册层",
                        "commands": ["手册"]
                    }
                }

            return {
                "success": True,
                "error_code": None,
                "user_message": f"已切换到{layer_name}",
                "data": {
                    "layer": layer_str,
                    "layer_name": layer_name,
                    "prompt": prompt,
                    "voice_announcement": "正在查询中，请稍后",
                    **nav_data
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error_code": "EXECUTION_ERROR",
                "user_message": f"层级切换失败: {str(e)}",
                "data": None
            }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


# 工具导出列表
__all__ = [
    "GetToolManual",
    "GetToolCategoriesL1",
    "GetToolsByCategoryL2",
    "GetToolDetailL3",
    "SwitchPromptLayer"
]
