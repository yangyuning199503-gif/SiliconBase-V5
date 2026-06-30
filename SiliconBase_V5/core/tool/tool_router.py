#!/usr/bin/env python3
"""
工具路由层 - 统一管理原生工具和 MCP 工具
"""

import logging

from core.mcp.client import mcp_client
from core.mcp.tools import MCPToolWrapper, wrap_mcp_tools
from core.tool.base_tool import BaseTool

logger = logging.getLogger(__name__)


class ToolRouter:
    """
    工具路由器

    统一管理和路由原生工具和 MCP 工具
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._native_tools: dict[str, BaseTool] = {}
        self._mcp_tools: dict[str, MCPToolWrapper] = {}
        self._mcp_enabled = False

        logger.info("[ToolRouter] 工具路由器初始化完成")

    def register_native_tools(self, tools: dict[str, BaseTool]):
        """注册原生工具"""
        self._native_tools.update(tools)
        logger.info(f"[ToolRouter] 注册 {len(tools)} 个原生工具")

    async def enable_mcp(self, configs: list[dict]) -> dict[str, bool]:
        """
        启用 MCP 支持

        Args:
            configs: MCP 服务器配置列表

        Returns:
            Dict[str, bool]: 连接结果
        """
        mcp_client.load_config(configs)
        results = await mcp_client.connect_all()

        if any(results.values()):
            self._mcp_tools = wrap_mcp_tools(mcp_client)
            self._mcp_enabled = True
            logger.info(f"[ToolRouter] MCP 已启用，共 {len(self._mcp_tools)} 个工具")
        else:
            logger.debug("[ToolRouter] 没有成功连接的 MCP 服务器")

        return results

    async def disable_mcp(self) -> None:
        """禁用 MCP 支持，断开所有连接并清理工具"""
        if not self._mcp_enabled:
            return
        try:
            await mcp_client.disconnect_all()
        except Exception as e:
            logger.warning(f"[ToolRouter] 断开 MCP 连接时出错: {e}")
        self._mcp_tools.clear()
        self._mcp_enabled = False
        logger.info("[ToolRouter] MCP 已禁用")

    def get_tool(self, tool_id: str) -> BaseTool | None:
        """
        获取工具

        优先查找原生工具，其次 MCP 工具
        """
        # 1. 精确匹配原生工具
        if tool_id in self._native_tools:
            return self._native_tools[tool_id]

        # 2. 精确匹配 MCP 工具
        if self._mcp_enabled and tool_id in self._mcp_tools:
            return self._mcp_tools[tool_id]

        # 3. 尝试模糊匹配 MCP 工具（支持短名称）
        if self._mcp_enabled:
            # 移除 mcp_ 前缀尝试匹配
            if tool_id.startswith("mcp_"):
                short_id = tool_id[4:]
                for mcp_tool_id, tool in self._mcp_tools.items():
                    if short_id in mcp_tool_id or mcp_tool_id.endswith(f"_{short_id}"):
                        return tool

            # 尝试直接匹配 MCP 工具名称
            for mcp_tool_id, tool in self._mcp_tools.items():
                if tool_id in mcp_tool_id or mcp_tool_id.endswith(f"_{tool_id}"):
                    return tool

        return None

    def list_tools(self, source: str | None = None) -> dict[str, list[dict]]:
        """
        列出所有工具

        Args:
            source: 筛选来源 ('native', 'mcp', None 表示全部)

        Returns:
            {
                "native": [...],
                "mcp": [...]
            }
        """
        result = {}

        if source in (None, "native"):
            native_list = [
                {
                    "id": tid,
                    "name": tool.name,
                    "description": tool.description,
                    "source": "native"
                }
                for tid, tool in self._native_tools.items()
            ]
            result["native"] = native_list

        if source in (None, "mcp") and self._mcp_enabled:
            mcp_list = [
                {
                    "id": tid,
                    "name": tool.name,
                    "description": tool.description,
                    "source": "mcp",
                    "server": tool._server_name
                }
                for tid, tool in self._mcp_tools.items()
            ]
            result["mcp"] = mcp_list

        return result

    def get_all_tools(self) -> dict[str, BaseTool]:
        """获取所有工具（原生 + MCP）"""
        all_tools = dict(self._native_tools)
        all_tools.update(self._mcp_tools)
        return all_tools

    def is_mcp_enabled(self) -> bool:
        """MCP 是否已启用"""
        return self._mcp_enabled

    def get_mcp_tools_by_server(self, server_name: str) -> list[MCPToolWrapper]:
        """获取指定服务器的 MCP 工具"""
        if not self._mcp_enabled:
            return []

        return [
            tool for tool in self._mcp_tools.values()
            if tool._server_name == server_name
        ]

    def get_tool_categories(self) -> dict[str, list[str]]:
        """获取工具分类"""
        categories = {
            "native": list(self._native_tools.keys()),
        }

        if self._mcp_enabled:
            # 按服务器分组 MCP 工具
            for tool_id, tool in self._mcp_tools.items():
                server = tool._server_name
                if server not in categories:
                    categories[server] = []
                categories[server].append(tool_id)

        return categories


# 全局实例
tool_router = ToolRouter()
