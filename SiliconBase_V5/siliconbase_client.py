#!/usr/bin/env python3
"""
SiliconBase V5 - 统一客户端封装
提供简洁的API接口，整合所有核心功能

使用示例:
    >>> from siliconbase_client import SiliconBaseClient
    >>> client = SiliconBaseClient()
    >>> client.chat("帮我打开浏览器")
    '好的，正在为您打开浏览器...'
"""

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 核心导入
from core.agent_loop import AgentLoop
from core.ai_client import AIClient, AIClientError

from core.logger import logger
from core.memory import MemoryManager
from core.tool_manager import tool_manager

# 可选导入（根据配置启用）
try:
    from voice.interface import VoiceInterface
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

try:
    from core.silicon_life_consciousness import SiliconLifeConsciousness
    CONSCIOUSNESS_AVAILABLE = True
except ImportError:
    CONSCIOUSNESS_AVAILABLE = False


@dataclass
class ClientConfig:
    """客户端配置"""
    ai_provider: str = "ollama"  # ollama/openai/anthropic/deepseek
    ai_model: str = "qwen3:8b"
    voice_enabled: bool = True
    memory_enabled: bool = True
    consciousness_enabled: bool = False  # 日常模式才启用
    tools_enabled: bool = True
    auto_confirm: bool = False  # 是否自动确认工具调用
    session_id: str = "default"

    # 高级配置
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 60


@dataclass
class ChatResponse:
    """对话响应封装"""
    content: str
    session_id: str
    tool_calls: list[dict] = field(default_factory=list)
    memory_used: bool = False
    voice_response: str | None = None
    metadata: dict = field(default_factory=dict)


class SiliconBaseClient:
    """
    SiliconBase V5 统一客户端

    功能特性:
    - AI对话 (支持多Provider)
    - 工具调用 (68个内置工具)
    - 记忆系统 (5层记忆)
    - 语音交互 (可选)
    - 意识系统 (可选)
    - 流式响应
    """

    def __init__(self, config: ClientConfig | None = None):
        """
        初始化客户端

        Args:
            config: 客户端配置，None则使用默认配置
        """
        self.config = config or ClientConfig()
        self._initialized = False

        # 核心组件
        self._ai_client: AIClient | None = None
        self._memory: MemoryManager | None = None
        self._agent_loop: AgentLoop | None = None
        self._voice: Any | None = None
        self._consciousness: Any | None = None

        # 状态
        self._chat_history: list[dict] = []
        self._session_id = self.config.session_id
        self._callbacks: dict[str, list[Callable]] = {
            "on_tool_call": [],
            "on_response": [],
            "on_error": [],
        }

        # 初始化
        self._init_components()

    def _init_components(self):
        """初始化核心组件"""
        try:
            # 1. AI客户端
            self._ai_client = AIClient()
            logger.info(f"[Client] AI客户端初始化完成: {self.config.ai_provider}")

            # 2. 记忆系统
            if self.config.memory_enabled:
                self._memory = MemoryManager()
                logger.info("[Client] 记忆系统初始化完成")

            # 3. 工具管理器
            if self.config.tools_enabled:
                # 工具已在tool_manager单例中初始化
                logger.info(f"[Client] 工具管理器初始化完成，可用工具: {len(tool_manager.tools)}")

            # 4. Agent循环
            self._agent_loop = AgentLoop()
            logger.info("[Client] Agent循环初始化完成")

            # 5. 语音接口 (可选)
            if self.config.voice_enabled and VOICE_AVAILABLE:
                self._voice = VoiceInterface()
                logger.info("[Client] 语音接口初始化完成")

            # 6. 意识系统 (可选)
            if self.config.consciousness_enabled and CONSCIOUSNESS_AVAILABLE:
                self._consciousness = SiliconLifeConsciousness()
                logger.info("[Client] 意识系统初始化完成")

            self._initialized = True
            logger.info("[Client] ✅ 客户端初始化完成")

        except Exception as e:
            logger.error(f"[Client] 初始化失败: {e}", exc_info=True)
            raise RuntimeError(f"客户端初始化失败: {e}") from e

    # ==================== 核心对话API ====================

    def chat(self,
             message: str,
             context: list[dict] | None = None,
             use_tools: bool = True,
             stream: bool = False) -> ChatResponse:
        """
        同步对话

        Args:
            message: 用户消息
            context: 对话上下文（可选）
            use_tools: 是否启用工具调用
            stream: 是否流式返回

        Returns:
            ChatResponse: 对话响应

        Example:
            >>> client = SiliconBaseClient()
            >>> response = client.chat("帮我打开浏览器")
            >>> print(response.content)
        """
        if not self._initialized:
            raise RuntimeError("客户端未初始化")

        try:
            # 构建请求
            request = {
                "request_id": f"req_{threading.current_thread().ident}_{int(time.time())}",
                "content": message,
                "context": context or self._chat_history,
                "model_config": {
                    "model_name": self.config.ai_model,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                },
                "callback_info": {
                    "timeout": self.config.timeout,
                    "retry_times": 2,
                }
            }

            # 调用AI
            if stream:
                return self._chat_stream(request)
            else:
                return self._chat_sync(request)

        except Exception as e:
            logger.error(f"[Client] 对话失败: {e}")
            self._trigger_callback("on_error", e)
            raise

    def _chat_sync(self, request: dict) -> ChatResponse:
        """同步对话实现"""
        # 使用AI客户端发送请求
        response = self._ai_client.send_request(request)

        if not response.get("success"):
            error_msg = response.get("error", "未知错误")
            raise AIClientError(f"AI调用失败: {error_msg}")

        content = response.get("content", "")

        # 更新历史
        self._chat_history.append({"role": "user", "content": request["content"]})
        self._chat_history.append({"role": "assistant", "content": content})

        # 限制历史长度
        if len(self._chat_history) > 20:
            self._chat_history = self._chat_history[-20:]

        # 构建响应
        return ChatResponse(
            content=content,
            session_id=self._session_id,
            tool_calls=response.get("tool_calls", []),
            memory_used=self.config.memory_enabled,
            metadata={
                "model": self.config.ai_model,
                "provider": self.config.ai_provider,
            }
        )

    def _chat_stream(self, request: dict) -> Iterator[str]:
        """流式对话实现"""
        messages = request["context"].copy()
        messages.append({"role": "user", "content": request["content"]})

        yield from self._ai_client.chat_stream(
            messages,
            model=self.config.ai_model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens
        )

    async def chat_async(self,
                         message: str,
                         context: list[dict] | None = None) -> ChatResponse:
        """异步对话"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.chat, message, context)

    # ==================== 工具调用API ====================

    def execute_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """
        执行指定工具

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具执行结果

        Example:
            >>> result = client.execute_tool("launch_app", {"app_name": "chrome"})
        """
        try:
            self._trigger_callback("on_tool_call", {"tool": tool_name, "params": params})
            result = tool_manager.execute(tool_name, params)
            return result
        except Exception as e:
            logger.error(f"[Client] 工具执行失败 {tool_name}: {e}")
            raise

    def list_tools(self) -> list[dict]:
        """
        获取可用工具列表

        Returns:
            工具列表，包含名称、描述、参数等信息
        """
        tools = []
        for name, tool in tool_manager.tools.items():
            tools.append({
                "name": name,
                "description": getattr(tool, "description", "无描述"),
                "parameters": getattr(tool, "parameters", {}),
            })
        return tools

    # ==================== 语音API ====================

    def start_voice_chat(self,
                         wake_words: list[str] | None = None,
                         on_wake: Callable | None = None,
                         on_result: Callable | None = None):
        """
        启动语音对话模式

        Args:
            wake_words: 唤醒词列表（默认:["元旦","你好元旦"]）
            on_wake: 唤醒回调
            on_result: 语音识别结果回调
        """
        if not VOICE_AVAILABLE or self._voice is None:
            raise RuntimeError("语音功能不可用，请检查依赖安装")

        # 设置回调
        if on_result:
            self._voice.callback_on_result = lambda text: self._handle_voice_result(text, on_result)

        # 启动语音监听
        self._voice.start()
        logger.info(f"[Client] 语音对话已启动，唤醒词: {wake_words or ['元旦']}")

    def _handle_voice_result(self, text: str, callback: Callable):
        """处理语音结果"""
        try:
            # 调用对话
            response = self.chat(text)

            # 语音播报
            if self._voice:
                self._voice.speak(response.content)

            # 回调
            callback(text, response.content)

        except Exception as e:
            logger.error(f"[Client] 语音处理失败: {e}")

    def speak(self, text: str):
        """语音播报"""
        if self._voice:
            self._voice.speak(text)

    def stop_voice(self):
        """停止语音"""
        if self._voice:
            self._voice.stop()

    # ==================== 记忆API ====================

    def remember(self, content: str, level: str = "L2", metadata: dict | None = None):
        """
        添加记忆

        Args:
            content: 记忆内容
            level: 记忆层级 (L1/L2/L3/L4/L5)
            metadata: 元数据
        """
        if self._memory:
            self._memory.store(
                user_id=self._session_id,
                content=content,
                level=level,
                metadata=metadata or {}
            )

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """
        检索记忆

        Args:
            query: 查询内容
            limit: 返回数量

        Returns:
            相关记忆列表
        """
        if self._memory:
            return self._memory.retrieve(
                user_id=self._session_id,
                query=query,
                limit=limit
            )
        return []

    def clear_memory(self):
        """清空当前会话记忆"""
        self._chat_history = []
        logger.info("[Client] 对话历史已清空")

    # ==================== 会话管理 ====================

    def new_session(self, session_id: str | None = None) -> str:
        """
        创建新会话

        Args:
            session_id: 自定义会话ID，None则自动生成

        Returns:
            会话ID
        """
        self._session_id = session_id or f"session_{int(time.time())}"
        self._chat_history = []
        logger.info(f"[Client] 新会话创建: {self._session_id}")
        return self._session_id

    def get_session_info(self) -> dict:
        """获取当前会话信息"""
        return {
            "session_id": self._session_id,
            "history_count": len(self._chat_history),
            "ai_provider": self.config.ai_provider,
            "ai_model": self.config.ai_model,
            "voice_enabled": self._voice is not None,
            "memory_enabled": self._memory is not None,
        }

    # ==================== 回调系统 ====================

    def on(self, event: str, callback: Callable):
        """
        注册事件回调

        Args:
            event: 事件名 (on_tool_call/on_response/on_error)
            callback: 回调函数
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, data: Any):
        """触发回调"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.warning(f"[Client] 回调执行失败: {e}")

    # ==================== 生命周期 ====================

    def close(self):
        """关闭客户端，释放资源"""
        logger.info("[Client] 正在关闭客户端...")

        if self._voice:
            self._voice.close()

        if self._consciousness:
            # 停止意识系统
            pass

        self._initialized = False
        logger.info("[Client] ✅ 客户端已关闭")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


# ==================== 便捷函数 ====================

def create_client(**kwargs) -> SiliconBaseClient:
    """
    快速创建客户端

    Args:
        **kwargs: 配置参数

    Returns:
        SiliconBaseClient实例

    Example:
        >>> client = create_client(ai_provider="openai", voice_enabled=False)
    """
    config = ClientConfig(**kwargs)
    return SiliconBaseClient(config)


def quick_chat(message: str, **kwargs) -> str:
    """
    快速对话（无需手动管理客户端生命周期）

    Args:
        message: 用户消息
        **kwargs: 客户端配置

    Returns:
        AI响应内容

    Example:
        >>> response = quick_chat("你好")
        >>> print(response)
    """
    with create_client(**kwargs) as client:
        response = client.chat(message)
        return response.content


# ==================== CLI入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SiliconBase V5 客户端")
    parser.add_argument("--provider", default="ollama", help="AI Provider")
    parser.add_argument("--model", default="qwen3:8b", help="AI Model")
    parser.add_argument("--voice", action="store_true", help="启用语音")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    parser.add_argument("message", nargs="?", help="直接发送消息")

    args = parser.parse_args()

    # 创建客户端
    client = SiliconBaseClient(ClientConfig(
        ai_provider=args.provider,
        ai_model=args.model,
        voice_enabled=args.voice
    ))

    if args.message:
        # 直接对话
        response = client.chat(args.message)
        print(f"🤖 AI: {response.content}")

    elif args.interactive:
        # 交互模式
        print("=" * 50)
        print("🤖 SiliconBase V5 - 交互模式")
        print("输入 'quit' 或 'exit' 退出")
        print("=" * 50)

        while True:
            try:
                user_input = input("\n👤 你: ").strip()

                if user_input.lower() in ["quit", "exit", "q"]:
                    print("👋 再见！")
                    break

                if not user_input:
                    continue

                response = client.chat(user_input)
                print(f"🤖 AI: {response.content}")

            except KeyboardInterrupt:
                print("\n👋 再见！")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")

    else:
        parser.print_help()

    client.close()
