#!/usr/bin/env python3
"""
AI 客户端 - 通用AI服务客户端（AI插排架构）
支持多后端：Ollama/OpenAI/Anthropic/DeepSeek等

版本历史：
- 2026-02-15: 新增AI调用指数退避重试机制
- 2026-02-22: 重构，使用 ai_config 集中配置管理
- 2026-02-28: 修复，移除硬编码Ollama地址，支持配置热重载
- 2026-03-01: 重构，使用Provider Factory架构，支持多后端
"""
import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

# 智能路由相关导入
from typing import TYPE_CHECKING, Any

from core.logger import logger

# 导入Provider Factory
from core.providers.ai_provider_factory import AIProviderFactory
from core.providers.base import AIProvider, ProviderNotAvailableError

if TYPE_CHECKING:
    pass

# 并发统计（用于监控）
_concurrent_requests = 0
_concurrent_lock = threading.Lock()


@dataclass
class AIResponse:
    """AI响应封装"""
    content: str
    model: str | None = None
    provider: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None


class AIClientError(Exception):
    """AI客户端异常"""
    pass


class AIClient:
    """
    通用AI客户端 - AI插排架构核心组件

    特性：
    - 支持多后端（Ollama/OpenAI/Anthropic/DeepSeek等）
    - 配置热重载
    - 指数退避重试机制
    - 流式响应支持
    - 向后兼容原有API
    """

    def __init__(self):
        self._provider: AIProvider | None = None
        self._provider_lock = threading.Lock()
        self._fallback_provider: AIProvider | None = None
        from protocol import BaseProtocol
        self.protocol = BaseProtocol()

        # 事件监听（用于配置热重载）
        self._config_listeners: list[callable] = []

        # 配置版本号（用于缓存刷新检测）
        self._config_version: int = -1
        self._refresh_lock = threading.RLock()
        self._lock = threading.Lock()  # 【新增】实例锁用于版本检查

    @property
    def provider(self) -> AIProvider:
        """
        获取当前Provider实例（线程安全，支持懒加载）

        Returns:
            AIProvider: 当前配置的Provider实例

        Raises:
            AIClientError: 当没有配置可用的Provider时
        """
        if self._provider is None:
            with self._provider_lock:
                if self._provider is None:
                    self._provider = AIProviderFactory.get_current_provider()
                    if self._provider is None:
                        raise AIClientError("No AI provider configured")
        return self._provider

    @provider.setter
    def provider(self, provider: AIProvider):
        """手动设置Provider实例（用于测试或特殊场景）"""
        with self._provider_lock:
            self._provider = provider

    def refresh_provider(self) -> AIProvider:
        """
        刷新Provider缓存
        在AI配置更新后调用
        """
        try:
            with self._lock:
                old_provider = self._provider
                self._provider = None
                logger.info(f"[AIClient] Provider缓存已刷新，原Provider: {old_provider}")
        except Exception as e:
            logger.error(f"[AIClient] 刷新Provider缓存失败: {e}", exc_info=True)
            raise

    def add_config_listener(self, listener: callable):
        """
        添加配置变化监听器

        Args:
            listener: 回调函数，接收(old_provider, new_provider)参数
        """
        self._config_listeners.append(listener)

    def remove_config_listener(self, listener: callable):
        """移除配置变化监听器"""
        if listener in self._config_listeners:
            self._config_listeners.remove(listener)

    def _get_provider(self):
        """【修改】带版本号检查的 provider 获取"""
        try:
            from core.config import config
            current_version = config.get_version()
            if current_version != self._config_version:
                with self._lock:
                    if current_version != self._config_version:
                        logger.info("[AIClient] 配置已更新，刷新 provider")
                        with self._provider_lock:
                            self._provider = None
                        self._config_version = current_version

            if self._provider is None:
                with self._provider_lock:
                    if self._provider is None:
                        self._provider = AIProviderFactory.get_current_provider()
                        if self._provider is None:
                            raise AIClientError("No AI provider configured")

            return self._provider
        except Exception as e:
            logger.error(f"[AIClient] 获取 provider 失败: {e}", exc_info=True)
            raise

    def _check_refresh(self):
        """检查是否需要刷新provider（基于配置版本号）

        每次调用AI前检查配置版本号，如果配置已变更则刷新provider。
        使用双重检查锁定模式确保线程安全。
        """
        try:
            from core.config import config
            current_version = config.get_version()
            if current_version != self._config_version:
                with self._refresh_lock:
                    # 双重检查，避免多个线程同时刷新
                    if current_version != self._config_version:
                        logger.info(f"[AIClient] 配置已变更（版本 {self._config_version} -> {current_version}），刷新provider")
                        with self._provider_lock:
                            self._provider = None
                        self._config_version = current_version
        except Exception as e:
            # 禁止静默失败：记录ERROR日志但不中断流程
            logger.error(f"[AIClient] 检查配置刷新失败: {e}", exc_info=True)

    def health_check(self) -> tuple[bool, str]:
        """
        通用健康检查 - 检查当前Provider是否可用

        Returns:
            tuple[bool, str]: (是否可用, 状态信息)
        """
        try:
            provider = self.provider
            is_available = provider.is_available()

            if not is_available:
                return False, f"{provider.__class__.__name__} 服务不可用"

            # 获取可用模型列表
            models = provider.get_model_list()
            provider_name = getattr(provider, 'config', {}).get('provider', 'unknown')

            if models:
                return True, f"[{provider_name}] 可用模型: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}"
            return True, f"[{provider_name}] 服务可用"

        except AIClientError as e:
            return False, str(e)
        except Exception as e:
            return False, f"健康检查失败: {str(e)}"

    def get_ai_base_url(self) -> str:
        """
        获取当前AI服务的基础URL

        Returns:
            str: 服务基础URL
        """
        try:
            provider = self.provider
            config = provider.get_config()
            return config.get("base_url", "")
        except Exception as e:
            logger.warning(f"[AIClient] 获取AI基础URL失败: {e}")
            return ""

    def _get_model_name(self, model_config: dict = None) -> str:
        """
        获取模型名称，优先使用配置中的值

        Args:
            model_config: 模型配置字典

        Returns:
            str: 模型名称
        """
        model_config = model_config or {}

        # 1. 优先使用传入的model_config中的model_name
        model_name = model_config.get("model_name") or model_config.get("model")

        # 如果 model_name 是 "default" 或空值，需要从配置获取实际模型
        if model_name and str(model_name).lower() != "default":
            return model_name

        # 2. 从Provider配置获取
        try:
            provider_config = self.provider.get_config()
            provider_model = provider_config.get("model")
            if provider_model and str(provider_model).lower() != "default":
                return provider_model
        except Exception as e:
            logger.warning(f"[AIClient] 从Provider配置获取模型名称失败: {e}")

        # 3. 从全局配置获取
        try:
            from core.config import config
            default_model = config.get("ai.default_model")
            if default_model and str(default_model).lower() != "default":
                return default_model
        except Exception as e:
            logger.warning(f"[AIClient] 从全局配置获取模型名称失败: {e}")

        # 4. 默认回退
        return "qwen3:8b"

    def _extract_messages(self, standard_request: dict) -> list[dict[str, str]]:
        """
        从标准请求中提取消息列表（上下文 + 当前输入）

        Args:
            standard_request: 标准请求字典

        Returns:
            List[Dict[str, str]]: 消息列表
        """
        messages = standard_request.get("context", []).copy()
        messages.append({
            "role": "user",
            "content": standard_request["content"]
        })
        return messages

    def _extract_generation_params(self, model_config: dict, callback_info: dict) -> dict[str, Any]:
        """
        提取生成参数（通用参数，不依赖特定Provider）

        Args:
            model_config: 模型配置
            callback_info: 回调信息

        Returns:
            Dict[str, Any]: 通用生成参数
        """
        return {
            "temperature": model_config.get("temperature", 0.2),
            "max_tokens": model_config.get("max_tokens", 512),
            "top_p": model_config.get("top_p", 0.5),
            "top_k": model_config.get("top_k", 20),
            "repeat_penalty": model_config.get("repeat_penalty", 1.2),
            "presence_penalty": model_config.get("presence_penalty", 0.5),
            "frequency_penalty": model_config.get("frequency_penalty", 0.5),
            "stop": model_config.get("stop", ["\n\n", "```"]),
            "timeout": callback_info.get("timeout", 30),
        }

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """
        【修改】使用版本号检查的 chat 方法

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}, ...]
            **kwargs: 可选参数:
                - model: 模型名称
                - temperature: 温度参数 (0.0-1.0)
                - max_tokens: 最大生成token数
                - top_p: 核采样参数
                - top_k: 束搜索参数
                - stream: 是否流式输出 (bool)

        Returns:
            Optional[str]: AI响应内容，失败返回None

        Raises:
            AIClientError: Provider不可用时
            ProviderNotAvailableError: 服务调用失败时
        """
        # 【修改】使用带版本号检查的 _get_provider
        try:
            provider = self._get_provider()

            # 处理流式请求
            if kwargs.get("stream"):
                # 流式不支持直接返回字符串，需要调用chat_stream
                raise ValueError("流式请求请使用 chat_stream() 方法")

            return provider.chat(messages, **kwargs)

        except AIClientError:
            raise
        except ProviderNotAvailableError:
            raise
        except Exception as e:
            logger.error(f"[AIClient] chat调用失败: {e}", exc_info=True)
            raise AIClientError(f"AI调用失败: {str(e)}") from e

    def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> Iterator[str]:
        """
        流式调用AI服务

        Args:
            messages: 消息列表
            **kwargs: 可选参数（同chat方法）

        Yields:
            str: 响应文本片段

        Raises:
            AIClientError: Provider不可用时
        """
        try:
            provider = self.provider

            # 如果Provider支持流式接口
            if hasattr(provider, 'chat_stream'):
                yield from provider.chat_stream(messages, **kwargs)
            else:
                # 降级为非流式
                result = provider.chat(messages, **kwargs)
                if not result:
                    logger.error("[AIClient] chat_stream 降级调用返回空响应")
                    raise AIClientError("chat_stream 降级调用返回空响应")
                yield result

        except AIClientError:
            raise
        except Exception as e:
            logger.error(f"[AIClient] chat_stream调用失败: {e}")
            raise AIClientError(f"AI流式调用失败: {str(e)}") from e

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """异步聊天入口（Phase 4 原生异步改造）

        优先调用 provider.chat_async() 实现原生异步，彻底消除 run_in_executor 桥接。
        如果 provider 不支持 chat_async，才降级到线程池包装。

        Args:
            messages: 消息列表
            **kwargs: 同 chat() 方法

        Returns:
            Optional[str]: AI 响应内容

        Raises:
            AIClientError: Provider 不可用时
            ValueError: 流式请求请使用 chat_stream_async() 方法
        """
        if kwargs.get("stream"):
            raise ValueError("流式请求请使用 chat_stream_async() 方法")

        try:
            provider = self._get_provider()
            # 【Phase 4 关键改造】优先使用 provider 的原生 chat_async
            if hasattr(provider, 'chat_async') and callable(provider.chat_async):
                return await provider.chat_async(messages, **kwargs)

            # 降级：provider 未实现原生异步时，保留 run_in_executor 桥接
            logger.warning(f"[AIClient] Provider {type(provider).__name__} 未实现 chat_async，降级到 run_in_executor")
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: provider.chat(messages, **kwargs)
            )
        except AIClientError:
            raise
        except ProviderNotAvailableError:
            raise
        except Exception as e:
            logger.error(f"[AIClient] chat_async 调用失败: {e}", exc_info=True)
            raise AIClientError(f"AI 异步调用失败: {str(e)}") from e

    async def chat_stream_async(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """异步流式入口（Phase 7.0 基建）

        当前实现：同步生成器在线程中消费并通过 asyncio.Queue 传递。
        未来：provider 层提供 async 生成器后替换为原生实现。
        """
        try:
            provider = self.provider

            if hasattr(provider, 'chat_stream'):
                loop = asyncio.get_running_loop()
                queue = asyncio.Queue()

                def _consume():
                    try:
                        for chunk in provider.chat_stream(messages, **kwargs):
                            asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
                        asyncio.run_coroutine_threadsafe(queue.put(None), loop)
                    except Exception as e:
                        asyncio.run_coroutine_threadsafe(queue.put(e), loop)

                import threading
                threading.Thread(target=_consume, daemon=True).start()

                while True:
                    chunk = await queue.get()
                    if isinstance(chunk, Exception):
                        raise chunk
                    if chunk is None:
                        break
                    yield chunk
            else:
                result = await self.chat_async(messages, **kwargs)
                if not result:
                    logger.error("[AIClient] chat_stream_async 降级调用返回空响应")
                    raise AIClientError("chat_stream_async 降级调用返回空响应")
                yield result

        except AIClientError:
            raise
        except Exception as e:
            logger.error(f"[AIClient] chat_stream_async 调用失败: {e}")
            raise AIClientError(f"AI 异步流式调用失败: {str(e)}") from e

    def send_request(self, standard_request: dict) -> dict:
        """
        发送AI请求（向后兼容的公共API）

        特性：
        - 使用Provider Factory动态获取后端
        - 完整传递历史对话上下文
        - 指数退避重试机制
        - 硬超时保护

        Args:
            standard_request: 标准请求字典，包含：
                - request_id: 请求ID
                - content: 用户输入内容
                - context: 历史对话上下文
                - model_config: 模型配置参数
                - callback_info: 回调和超时配置

        Returns:
            Dict: 标准响应字典
        """
        # 检查是否需要刷新provider（配置变更时）
        self._check_refresh()

        request_id = standard_request.get("request_id", "unknown")
        logger.debug(f"[AIClient] send_request() 被调用，request_id={request_id}")

        model_config = standard_request.get("model_config", {})
        callback_info = standard_request.get("callback_info", {})

        # 重试配置
        max_retry = callback_info.get("retry_times", 2)
        timeout = callback_info.get("timeout", 60)

        # 获取模型名称
        model_name = self._get_model_name(model_config)

        # 健康检查
        available, msg = self.health_check()
        logger.info(f"[AIClient] 服务状态: {'可用' if available else '不可用'} - {msg}")
        if not available:
            return self.protocol.build_error_response(request_id, f"AI服务不可用: {msg}")

        # 提取消息和参数
        messages = self._extract_messages(standard_request)
        gen_params = self._extract_generation_params(model_config, callback_info)

        # 增加并发计数
        global _concurrent_requests
        with _concurrent_lock:
            _concurrent_requests += 1
            current_concurrent = _concurrent_requests

        logger.info(f"[AIClient] 并发数：{current_concurrent}，模型：{model_name}，temperature：{gen_params['temperature']}")

        # 启动心跳和超时机制
        heartbeat_stop = threading.Event()
        heartbeat_count = [0]
        request_done = threading.Event()
        hard_timeout_triggered = [False]

        def heartbeat():
            while not heartbeat_stop.wait(3):
                heartbeat_count[0] += 1
                if heartbeat_count[0] == 1:
                    logger.info(f"⏳ AI思考中...（已等待{heartbeat_count[0] * 3}秒）")
                elif heartbeat_count[0] % 2 == 0:
                    logger.info(f"⏳ AI仍在思考，请稍候...（已等待{heartbeat_count[0] * 3}秒）")

                # 硬超时检查
                elapsed = heartbeat_count[0] * 3
                if elapsed > timeout + 10 and not request_done.is_set():
                    logger.warning(f"⚠️ AI请求硬超时触发（已等待{elapsed}秒），强制终止")
                    hard_timeout_triggered[0] = True
                    heartbeat_stop.set()
                    break

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        last_error = ""

        try:
            for attempt in range(max_retry + 1):
                try:
                    logger.info(f"[AIClient] 第{attempt + 1}次尝试，模型：{model_name}，上下文轮次：{len(messages) - 1}")

                    # 使用Provider统一接口
                    raw_content = self.provider.chat(
                        messages=messages,
                        model=model_name,
                        **gen_params
                    )

                    # 标记请求完成
                    request_done.set()
                    heartbeat_stop.set()

                    # 处理空响应
                    if not raw_content:
                        logger.error(f"[AIClient] 第{attempt + 1}次返回空内容")
                        last_error = "AI返回空内容"
                        if attempt < max_retry:
                            time.sleep(1)
                        continue

                    raw_content = raw_content.strip()
                    logger.info(f"[AIClient] 提取内容长度: {len(raw_content)}")

                    # 【修复】只在非CHAT场景下强制要求JSON工具调用
                    scene = model_config.get("scene", "react")
                    is_chat_scene = (scene == "chat" or scene == "CHAT")

                    # JSON工具调用检查（只对REACT等任务场景）
                    if not is_chat_scene:
                        has_json_block = "```json" in raw_content or "```" in raw_content
                        has_tool_call = '{"tool":' in raw_content.replace(" ", "") or "{\"tool\":" in raw_content

                        if not (has_json_block or has_tool_call):
                            consecutive_no_json = getattr(self, '_consecutive_no_json', 0) + 1
                            self._consecutive_no_json = consecutive_no_json
                            if consecutive_no_json <= 3:
                                logger.warning(f"[AIClient] 响应中没有JSON工具调用，要求重新输出 (第{consecutive_no_json}次)")
                                logger.debug(f"[AIClient] 内容预览: {raw_content[:200]}")
                                # 修改消息列表，追加JSON要求
                                if messages:
                                    messages.append({
                                        "role": "system",
                                        "content": "⚠️ 注意：你的回复必须包含JSON格式的工具调用！请重新回复，必须包含 ```json 代码块。"
                                    })
                                    messages.append({
                                        "role": "user",
                                        "content": "请输出JSON格式的工具调用来完成任务。格式：{\"tool\": \"工具名\", \"params\": {}}"
                                    })
                                if attempt < max_retry:
                                    time.sleep(0.5)
                                continue
                            else:
                                logger.warning(f"[AIClient] 连续{consecutive_no_json}次无JSON，放弃重试，降级处理")
                                last_error = f"模型连续{consecutive_no_json}次未输出JSON格式"
                                break
                    else:
                        # CHAT场景或非JSON强制场景，重置计数器
                        self._consecutive_no_json = 0

                    # CHAT场景直接返回内容，不强制要求JSON格式
                    if is_chat_scene:
                        self._consecutive_no_json = 0
                        return {
                            "success": True,
                            "content": raw_content,
                            "request_id": request_id
                        }

                    self._consecutive_no_json = 0
                    return self.protocol.parse_response(raw_content, request_id)

                except Exception as e:
                    last_error = str(e)
                    request_done.set()
                    logger.error(f"[AIClient] 第{attempt + 1}/{max_retry + 1}次调用失败：{last_error}")
                    if attempt < max_retry:
                        sleep_time = min(2 ** attempt, 30)  # 指数退避
                        time.sleep(sleep_time)
                    continue

                # 检查硬超时
                if hard_timeout_triggered[0]:
                    last_error = "请求超时（硬超时保护触发）"
                    break

        finally:
            heartbeat_stop.set()
            with _concurrent_lock:
                _concurrent_requests -= 1

        # 处理硬超时
        if hard_timeout_triggered[0]:
            return self.protocol.build_error_response(
                request_id,
                "AI请求超时，请检查服务状态或稍后重试"
            )

        # 所有重试都失败
        return self.protocol.build_error_response(
            request_id,
            f"AI调用多次重试失败，最终错误：{last_error}"
        )

    def get_provider_info(self) -> dict[str, Any]:
        """
        获取当前Provider信息

        Returns:
            Dict[str, Any]: Provider信息
        """
        try:
            provider = self.provider
            config = provider.get_config()
            return {
                "provider_type": config.get("provider", "unknown"),
                "provider_class": provider.__class__.__name__,
                "model": config.get("model", "unknown"),
                "base_url": config.get("base_url", ""),
                "available": provider.is_available(),
            }
        except Exception as e:
            return {
                "provider_type": "unknown",
                "error": str(e),
                "available": False,
            }

    def set_fallback_provider(self, provider: AIProvider):
        """
        设置备用Provider

        Args:
            provider: 备用Provider实例
        """
        self._fallback_provider = provider

    def chat_with_fallback(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """
        带fallback的chat调用

        主Provider失败时自动切换到备用Provider

        Args:
            messages: 消息列表
            **kwargs: 其他参数

        Returns:
            Optional[str]: AI响应内容
        """
        try:
            return self.chat(messages, **kwargs)
        except (AIClientError, ProviderNotAvailableError) as e:
            if self._fallback_provider:
                logger.warning(f"[AIClient] 主Provider失败，切换到fallback: {e}")
                try:
                    return self._fallback_provider.chat(messages, **kwargs)
                except Exception as fallback_error:
                    logger.error(f"[AIClient] Fallback Provider也失败: {fallback_error}")
                    raise AIClientError(f"主Provider和Fallback均失败: {e}, {fallback_error}") from fallback_error
            raise

    # ==================== 智能路由支持 ====================

    def chat_with_smart_route(self,
                              message: str,
                              context: list[dict] | None = None,
                              deploy_mode: str = "hybrid",
                              **kwargs) -> str | None:
        """
        智能路由聊天 - 根据任务复杂度和网络状态自动选择模型

        特性：
        - 本地模型能力不足时自动切换到云端
        - 根据任务复杂度智能选择模型
        - 离线时自动降级到本地

        Args:
            message: 用户消息
            context: 对话上下文（可选）
            deploy_mode: 部署模式 (local/cloud/hybrid/auto)
            **kwargs: 其他参数（temperature, max_tokens等）

        Returns:
            Optional[str]: AI响应内容

        Example:
            >>> client = AIClient()
            >>> response = client.chat_with_smart_route(
            ...     "帮我分析这个代码",
            ...     deploy_mode="hybrid"
            ... )
        """
        try:
            # 延迟导入避免循环依赖
            from core.smart_ai_router import get_smart_router

            # 获取智能路由器
            router = get_smart_router(deploy_mode)

            # 构建消息列表
            messages = []
            if context:
                for msg in context:
                    messages.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")
                    })
            messages.append({"role": "user", "content": message})

            # 评估任务复杂度（用于日志）
            complexity = router.evaluate_complexity(message, context)
            logger.info(f"[AIClient] 智能路由 - 任务复杂度: {complexity.value}")

            # 执行智能路由调用
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果已经在事件循环中，使用run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(
                        router.chat_with_auto_route(message, context, **kwargs),
                        loop
                    )
                    return future.result(timeout=120)
                else:
                    return loop.run_until_complete(
                        router.chat_with_auto_route(message, context, **kwargs)
                    )
            except RuntimeError:
                # 没有事件循环，创建新的
                # 【规则7整改】使用new_event_loop替代asyncio.run，避免嵌套问题
                _new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_new_loop)
                try:
                    return _new_loop.run_until_complete(
                        router.chat_with_auto_route(message, context, **kwargs)
                    )
                finally:
                    _new_loop.close()

        except Exception as e:
            logger.error(f"[AIClient] 智能路由调用失败: {e}")
            # 降级到普通调用
            logger.info("[AIClient] 降级到普通调用")
            messages = [{"role": "user", "content": message}]
            return self.chat(messages, **kwargs)

    def evaluate_task_complexity(self, message: str,
                                  context: list[dict] | None = None) -> str:
        """
        评估任务复杂度

        Args:
            message: 用户消息
            context: 对话上下文（可选）

        Returns:
            str: 复杂度级别 (simple/medium/complex/vision)
        """
        try:
            from core.smart_ai_router import get_smart_router
            router = get_smart_router()
            complexity = router.evaluate_complexity(message, context)
            return complexity.value
        except Exception as e:
            logger.warning(f"[AIClient] 评估复杂度失败: {e}")
            # 简单启发式判断
            if len(message) < 100:
                return "simple"
            elif "分析" in message or "规划" in message or "推理" in message:
                return "complex"
            return "medium"

    def check_network_status(self) -> bool:
        """
        检查网络状态

        Returns:
            bool: 是否在线
        """
        try:
            from core.smart_ai_router import get_smart_router
            router = get_smart_router()
            return router._network_monitor.is_online()
        except Exception as e:
            logger.warning(f"[AIClient] 检查网络状态失败: {e}")
            # 尝试简单检测
            try:
                import socket
                socket.setdefaulttimeout(2)
                socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
                return True
            except (OSError, ImportError) as e:
                logger.error(f"[AIClient] 网络检测失败: {e}")
                raise

    def get_routing_recommendation(self, message: str) -> dict[str, Any]:
        """
        获取路由推荐信息

        Args:
            message: 用户消息

        Returns:
            Dict: 推荐信息，包含复杂度、推荐模型、预估成本等
        """
        try:
            from core.smart_ai_router import get_smart_router
            router = get_smart_router()

            complexity = router.evaluate_complexity(message)
            is_online = router._network_monitor.is_online()
            local_available = router.is_local_available()

            recommendation = {
                "task_complexity": complexity.value,
                "network_online": is_online,
                "local_available": local_available,
                "recommended_provider": None,
                "recommended_model": None,
                "estimated_cost": 0.0,
                "reason": ""
            }

            # 简单决策逻辑
            if not is_online:
                if local_available:
                    recommendation["recommended_provider"] = "ollama"
                    recommendation["recommended_model"] = router._get_best_local_model(complexity)
                    recommendation["reason"] = "离线模式，使用本地模型"
                else:
                    recommendation["reason"] = "离线且本地模型不可用"
            elif complexity.value == "simple" and local_available:
                recommendation["recommended_provider"] = "ollama"
                recommendation["recommended_model"] = router._get_best_local_model(complexity)
                recommendation["reason"] = "简单任务，优先使用本地模型节省成本"
            else:
                provider, model = router.select_best_cloud_provider(complexity)
                recommendation["recommended_provider"] = provider
                recommendation["recommended_model"] = model
                recommendation["estimated_cost"] = 0.01  # 粗略估计
                recommendation["reason"] = f"{complexity.value}任务，使用云端模型保证质量"

            return recommendation

        except Exception as e:
            logger.error(f"[AIClient] 获取路由推荐失败: {e}", exc_info=True)
            return {"error": str(e), "error_type": type(e).__name__}


# ==================== 向后兼容的API ====================

def get_ollama_base_url() -> str:
    """
    【已弃用】获取Ollama基础URL

    保留此函数以向后兼容，实际逻辑已移至Provider内部
    新代码应直接使用AIProviderFactory或AIClient获取配置

    Returns:
        Ollama服务基础URL（如果当前Provider是Ollama）

    Note:
        建议使用 AIClient().get_ai_base_url() 替代
    """
    try:
        client = AIClient()
        return client.get_ai_base_url()
    except Exception as e:
        logger.warning(f"[AIClient] 获取Ollama基础URL失败: {e}")
        return "http://localhost:11434"


def _check_ollama_service(base_url: str = "http://localhost:11434") -> bool:
    """
    【内部使用】检查Ollama服务健康状态

    仅用于向后兼容的内部检查

    Args:
        base_url: Ollama服务地址

    Returns:
        bool: 服务是否可用
    """
    try:
        import requests
        resp = requests.get(f"{base_url}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[AIClient] Ollama服务健康检查失败: {e}")
        return False


# 保持类名兼容性（某些地方可能直接导入OllamaClient）
OllamaClient = AIClient


# ==================== 便捷函数 ====================

def create_ai_client(provider_type: str = None, **config) -> AIClient:
    """
    创建指定类型的AI客户端

    Args:
        provider_type: Provider类型 (ollama/openai/anthropic等)
        **config: Provider配置

    Returns:
        AIClient: 配置好的AI客户端
    """
    client = AIClient()

    if provider_type:
        provider = AIProviderFactory.create_provider(provider_type, **config)
        client.provider = provider

    return client


def get_default_client() -> AIClient:
    """
    获取默认AI客户端实例（单例模式）

    Returns:
        AIClient: 默认客户端实例
    """
    if not hasattr(get_default_client, '_instance'):
        get_default_client._instance = AIClient()
    return get_default_client._instance
