#!/usr/bin/env python3
"""
MCP 工具包装器 - 将 MCP 工具转换为 SiliconBase 工具
"""

import json
import logging
from typing import Any

from core.mcp.client import MCPClient, MCPTool
from core.tool.base_tool import BaseTool

logger = logging.getLogger(__name__)


class MCPToolWrapper(BaseTool):
    """
    MCP 工具包装器

    将 MCP 工具包装为 SiliconBase 原生工具，实现无缝集成
    """

    def __init__(self, mcp_tool: MCPTool, mcp_client: MCPClient):
        # 设置工具属性
        self.tool_id = f"mcp_{mcp_tool.server_name}_{mcp_tool.name}"
        self.name = f"[MCP] {mcp_tool.name}"
        self.description = mcp_tool.description
        self.input_schema = mcp_tool.input_schema
        self.version = "1.0.0"
        self.timeout = 60
        self.require_confirmation = False

        # MCP 相关
        self._mcp_tool = mcp_tool
        self._mcp_client = mcp_client
        self._server_name = mcp_tool.server_name

        super().__init__()

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        执行 MCP 工具（同步入口，已禁止同步桥接）

        [Phase 2] 已删除 asyncio.new_event_loop() + loop.run_until_complete() 桥接。
        MCP 工具只支持异步执行，请使用 await tool.run_async() 或 await tool._execute_async()。
        """
        raise RuntimeError(
            f"[MCPToolWrapper] {self.tool_id} 已禁止同步执行。"
            f"请使用 await tool.run_async() 或在异步上下文中 await tool._execute_async()。"
        )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """异步执行"""
        try:
            result = await self._mcp_client.call_tool(
                self._server_name,
                self._mcp_tool.name,
                kwargs
            )

            # 转换 MCP 结果为 SiliconBase 格式
            return {
                "success": True,
                "error_code": "",
                "error_message": "",
                "user_message": self._format_result(result),
                "data": result
            }

        except Exception as e:
            logger.error(f"[MCPTool] {self.tool_id} 异步执行失败: {e}")
            return {
                "success": False,
                "error_code": "MCP_EXECUTION_ERROR",
                "error_message": str(e),
                "data": None
            }

    def _format_result(self, result: Any) -> str:
        """格式化结果为可读文本"""
        if isinstance(result, dict):
            # MCP 标准结果格式
            if "content" in result:
                content = result["content"]
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                texts.append(item.get("text", ""))
                            elif item.get("type") == "image":
                                texts.append("[图片]")
                            elif item.get("type") == "resource":
                                texts.append(f"[资源: {item.get('resource', {}).get('uri', '')}]")
                        else:
                            texts.append(str(item))
                    return "\n".join(texts)
                return str(content)

            # 其他格式
            return json.dumps(result, ensure_ascii=False, indent=2)

        return str(result)


def wrap_mcp_tools(mcp_client: MCPClient) -> dict[str, MCPToolWrapper]:
    """
    包装所有 MCP 工具

    Returns:
        Dict[str, MCPToolWrapper]: tool_id -> wrapper
    """
    wrappers = {}

    for mcp_tool in mcp_client.get_tools():
        try:
            wrapper = MCPToolWrapper(mcp_tool, mcp_client)
            wrappers[wrapper.tool_id] = wrapper
            logger.debug(f"[MCPTools] 包装工具: {wrapper.tool_id}")
        except Exception as e:
            logger.error(f"[MCPTools] 包装工具 {mcp_tool.name} 失败: {e}")

    logger.info(f"[MCPTools] 共包装 {len(wrappers)} 个 MCP 工具")
    return wrappers
