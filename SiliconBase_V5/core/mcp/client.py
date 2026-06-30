#!/usr/bin/env python3
"""
MCP (Model Context Protocol) 客户端
兼容 Anthropic MCP 规范
"""

import asyncio
import json
import logging
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MCPTransportType(Enum):
    """MCP 传输类型"""
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


@dataclass
class MCPServerConfig:
    """MCP 服务器配置"""
    name: str
    transport: MCPTransportType
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    timeout: int = 30
    enabled: bool = True
    cwd: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerConfig":
        """从字典创建配置"""
        transport = MCPTransportType(data.get("transport", "stdio"))
        return cls(
            name=data["name"],
            transport=transport,
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            timeout=data.get("timeout", 30),
            enabled=data.get("enabled", True),
            cwd=data.get("cwd")
        )


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class MCPConnection:
    """MCP 服务器连接"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self._subprocess: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stdout_queue: asyncio.Queue | None = None
        self._shutdown_event = threading.Event()
        self.tools: list[MCPTool] = []
        self._initialized = False
        self._request_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """建立连接"""
        if self.config.transport == MCPTransportType.STDIO:
            return await self._connect_stdio()
        elif self.config.transport == MCPTransportType.SSE:
            return await self._connect_sse()
        else:
            logger.error(f"[MCP] 不支持的传输类型: {self.config.transport}")
            return False

    async def _connect_stdio(self) -> bool:
        """通过 stdio 连接（Windows兼容版，使用 threading + subprocess.Popen）"""
        try:
            import os
            import sys

            env = {**os.environ, **self.config.env}

            def _create_process():
                """在线程池中创建子进程，避免阻塞事件循环"""
                if sys.platform == 'win32':
                    command = self.config.command
                    args = self.config.args
                    if command in ['npx', 'npm', 'node']:
                        cmd_str = f"{command} {' '.join(args)}"
                        logger.debug(f"[MCP] Windows subprocess.Popen shell: {cmd_str}")
                        return subprocess.Popen(
                            cmd_str,
                            shell=True,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=env,
                            text=False,
                            bufsize=0,
                        )
                    else:
                        return subprocess.Popen(
                            [command] + list(args),
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=env,
                            cwd=self.config.cwd,
                            text=False,
                            bufsize=0,
                        )
                else:
                    return subprocess.Popen(
                        [self.config.command] + list(self.config.args),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        cwd=self.config.cwd,
                        text=False,
                        bufsize=0,
                    )

            # 【修复】在线程池中创建子进程，避免阻塞事件循环
            self._subprocess = await asyncio.to_thread(_create_process)

            # 启动 stdout 读取线程
            self._shutdown_event.clear()
            self._stdout_queue = asyncio.Queue()
            event_loop = asyncio.get_event_loop()
            self._reader_thread = threading.Thread(
                target=self._stdout_reader,
                args=(self._subprocess.stdout, self._stdout_queue, event_loop),
                daemon=True,
                name=f"MCP-{self.config.name}-reader",
            )
            self._reader_thread.start()

            # 等待进程启动
            await asyncio.sleep(0.5)

            if self._subprocess.poll() is not None:
                # 【修复】在线程池中读取 stderr，避免阻塞事件循环
                stderr_bytes = b""
                if self._subprocess.stderr:
                    try:
                        stderr_bytes = await asyncio.wait_for(
                            asyncio.to_thread(self._subprocess.stderr.read),
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"[MCP] {self.config.name} stderr 读取超时")
                stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
                if stderr:
                    logger.error(f"[MCP] {self.config.name} stderr: {stderr[:500]}")
                logger.error(f"[MCP] 进程启动失败: {self.config.command} {' '.join(self.config.args)}")
                return False

            # 发送初始化请求
            init_request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "siliconbase-mcp-client",
                        "version": "1.0.0"
                    }
                }
            }

            await self._send_message(init_request)
            response = await self._read_response(timeout=self.config.timeout)

            if response and "result" in response:
                self._initialized = True
                logger.info(f"[MCP] 服务器 {self.config.name} 初始化成功")

                # 发送 initialized 通知
                await self._send_message({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized"
                })

                # 获取工具列表
                await self._fetch_tools()
                return True
            else:
                error_msg = response.get("error", {}).get("message", "未知错误") if response else "无响应"
                logger.error(f"[MCP] 服务器 {self.config.name} 初始化失败: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"[MCP] 连接服务器 {self.config.name} 失败: {e}", exc_info=True)
            return False

    def _stdout_reader(self, stdout, queue: asyncio.Queue, event_loop):
        """独立线程读取 stdout，通过 event_loop.call_soon_threadsafe 写入 asyncio Queue"""
        while not self._shutdown_event.is_set():
            try:
                line_bytes = stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    data = {"_raw": line}

                if event_loop is not None and not event_loop.is_closed():
                    event_loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception as e:
                logger.debug(f"[MCP] {self.config.name} stdout reader error: {e}")
                break

    async def _connect_sse(self) -> bool:
        """通过 SSE 连接（待实现）"""
        logger.warning("[MCP] SSE 传输暂未实现")
        return False

    async def _send_message(self, message: dict):
        """发送消息"""
        if not self._subprocess or self._subprocess.stdin is None:
            raise RuntimeError("MCP 连接未建立")

        async with self._request_lock:
            data = (json.dumps(message) + "\n").encode('utf-8')
            self._subprocess.stdin.write(data)
            self._subprocess.stdin.flush()

    async def _read_response(self, timeout: int = 30) -> dict | None:
        """读取响应（Windows兼容版，使用 asyncio.Queue）

        跳过服务器启动日志等非 JSON 行，直到拿到真正的 JSON-RPC 消息。
        """
        if not self._stdout_queue:
            return None

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(f"[MCP] 读取响应超时 ({timeout}s)")
                return None
            try:
                data = await asyncio.wait_for(self._stdout_queue.get(), timeout=remaining)
                if isinstance(data, dict) and "_raw" not in data:
                    return data
                # _raw 行是服务器日志，继续等待下一个 JSON-RPC 消息
                logger.debug(f"[MCP] 忽略服务器日志: {data.get('_raw', '')[:200]}")
            except asyncio.TimeoutError:
                logger.warning(f"[MCP] 读取响应超时 ({timeout}s)")
                return None
            except Exception as e:
                logger.error(f"[MCP] 读取响应出错: {e}")
                return None

    async def _fetch_tools(self):
        """获取工具列表"""
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list"
        }

        await self._send_message(request)
        response = await self._read_response(timeout=self.config.timeout)

        if response and "result" in response:
            tools_data = response["result"].get("tools", [])
            self.tools = [
                MCPTool(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                    server_name=self.config.name
                )
                for tool in tools_data
            ]
            logger.info(f"[MCP] 服务器 {self.config.name} 提供 {len(self.tools)} 个工具")
        else:
            logger.warning(f"[MCP] 获取工具列表失败: {response}")

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用工具"""
        if not self._initialized:
            raise RuntimeError("MCP 连接未初始化")

        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params
            }
        }

        await self._send_message(request)
        response = await self._read_response(timeout=self.config.timeout)

        if response:
            if "result" in response:
                return response["result"]
            elif "error" in response:
                error = response["error"]
                raise RuntimeError(f"MCP 工具调用失败: {error.get('message', '未知错误')}")

        raise RuntimeError("MCP 调用无响应")

    async def disconnect(self):
        """断开连接"""
        self._shutdown_event.set()
        if self._subprocess:
            try:
                self._subprocess.terminate()
                try:
                    self._subprocess.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._subprocess.kill()
                    self._subprocess.wait()
            except Exception as e:
                logger.warning(f"[MCP] 断开连接时出错: {e}")
            finally:
                self._subprocess = None
                if self._reader_thread:
                    self._reader_thread.join(timeout=2)
                    self._reader_thread = None
                self._initialized = False


class MCPClient:
    """MCP 客户端管理器"""

    _instance = None
    _creation_lock = threading.Lock()  # 【治理】仅保护 __new__，不保护异步操作

    def __new__(cls):
        if cls._instance is None:
            with cls._creation_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 【治理】异步资源锁，保护并发连接/调用操作
        self._async_lock = asyncio.Lock()

        self.connections: dict[str, MCPConnection] = {}
        self._configs: dict[str, MCPServerConfig] = {}

        logger.info("[MCPClient] MCP 客户端初始化完成")

    def load_config(self, configs: list[dict]):
        """加载服务器配置"""
        for config_data in configs:
            config = MCPServerConfig.from_dict(config_data)
            self._configs[config.name] = config
            logger.debug(f"[MCPClient] 加载配置: {config.name}")

    async def connect_all(self) -> dict[str, bool]:
        """连接所有服务器"""
        async with self._async_lock:
            results = {}
            has_node_server = False

            for name, config in self._configs.items():
                if not config.enabled:
                    logger.debug(f"[MCPClient] 跳过禁用服务器: {name}")
                    continue

                if config.command in ('node', 'npx', 'npm'):
                    has_node_server = True

                conn = MCPConnection(config)
                success = await conn.connect()

                if success:
                    self.connections[name] = conn
                else:
                    # 优雅降级：连接失败后禁用该服务器，避免重复报错
                    config.enabled = False

                results[name] = success

            success_count = sum(results.values())
            total = len([c for c in self._configs.values() if c.enabled])
            logger.info(f"[MCPClient] 已连接 {success_count}/{total} 个服务器")

            if success_count == 0 and has_node_server and self._configs:
                logger.warning(
                    "[MCP] 所有 MCP 服务器连接失败。"
                    "若需使用 MCP 功能，请安装 Node.js 并运行 `npm install` 安装 MCP 服务器包。"
                )

            return results

    async def connect(self, server_name: str) -> bool:
        """连接指定服务器"""
        async with self._async_lock:
            if server_name in self.connections:
                return True

            if server_name not in self._configs:
                logger.error(f"[MCPClient] 未找到配置: {server_name}")
                return False

            config = self._configs[server_name]
            conn = MCPConnection(config)
            success = await conn.connect()

            if success:
                self.connections[server_name] = conn

            return success

    def get_tools(self) -> list[MCPTool]:
        """获取所有可用工具"""
        tools = []
        for conn in self.connections.values():
            tools.extend(conn.tools)
        return tools

    async def call_tool(self, server_name: str, tool_name: str,
                        params: dict[str, Any]) -> dict[str, Any]:
        """调用指定服务器的工具"""
        async with self._async_lock:
            if server_name not in self.connections:
                raise ValueError(f"MCP 服务器未连接: {server_name}")

            conn = self.connections[server_name]
            return await conn.call_tool(tool_name, params)

    async def disconnect_all(self):
        """断开所有连接"""
        async with self._async_lock:
            for name, conn in list(self.connections.items()):
                await conn.disconnect()
                logger.debug(f"[MCPClient] 已断开: {name}")

            self.connections.clear()

    def is_connected(self, server_name: str) -> bool:
        """检查服务器是否已连接"""
        return server_name in self.connections and self.connections[server_name]._initialized


# 全局实例
mcp_client = MCPClient()
