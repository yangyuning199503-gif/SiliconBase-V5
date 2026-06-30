#!/usr/bin/env python3
"""
MCP (Model Context Protocol) 模块

提供与 Anthropic MCP 协议的兼容支持
"""

from core.mcp.client import MCPClient, MCPConnection, MCPServerConfig, MCPTransportType, mcp_client
from core.mcp.tools import MCPToolWrapper, wrap_mcp_tools

__all__ = [
    'MCPClient',
    'MCPConnection',
    'MCPServerConfig',
    'MCPTransportType',
    'MCPToolWrapper',
    'wrap_mcp_tools',
    'mcp_client'
]
