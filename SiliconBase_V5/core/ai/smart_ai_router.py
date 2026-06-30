#!/usr/bin/env python3
"""
智能AI路由客户端 - 云端 ↔ 本地 自动切换

功能特性：
- 根据任务复杂度智能选择模型（本地/云端）
- 本地模型能力不足时自动切换到云端
- 离线时自动降级到本地模型
- 本地模型失败检测（超时、OOM、错误率）
- 云端模型负载均衡
- 成本感知（优先便宜的模型）

版本历史：
- 2026-03-09: 初始实现
"""

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from core.ai.model_profile import MODEL_PROFILES, TaskType
from core.ai.model_router import ModelRouter, RoutingStrategy
from core.exceptions import AIResponseError, SiliconBaseException
from core.logger import logger
from core.providers.ai_provider_factory import AIProviderFactory
from core.providers.base import AIProvider


class TaskComplexity(Enum):
    """任务复杂度级别"""
    SIMPLE = "simple"       # 简单任务：短文本、问答
    MEDIUM = "medium"       # 中等任务：一般对话、摘要
    COMPLEX = "complex"     # 复杂任务：分析、规划、推理
    VISION = "vision"       # 视觉任务：图像理解


class DeployMode(Enum):
    """部署模式"""
    LOCAL = "local"         # 仅本地
    CLOUD = "cloud"         # 仅云端
    HYBRID = "hybrid"       # 混合模式（智能路由）
    AUTO = "auto"           # 自动模式（根据网络状态）


@dataclass
class RoutingDecision:
    """路由决策结果"""
    provider_type: str          # 选择的Provider类型
    model_name: str             # 选择的模型名称
    complexity: TaskComplexity  # 任务复杂度
    reason: str                 # 选择原因
    is_fallback: bool = False   # 是否为fallback
    estimated_cost: float = 0.0 # 预估成本
    estimated_latency: int = 0  # 预估延迟(ms)


@dataclass
class ModelHealth:
    """模型健康状态"""
    provider_type: str
    model_name: str
    is_available: bool
    last_check: datetime
    failure_count: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    oom_detected: bool = False  # 是否检测到OOM
    timeout_count: int = 0      # 超时次数


class NetworkMonitor:
    """网络状态监控器"""

    def __init__(self):
        self._is_online: bool = True
        self._last_check: datetime = datetime.now()
        self._check_interval: int = 30  # 30秒检查一次
        self._lock = threading.Lock()
        self._online_callbacks: list[callable] = []
        self._offline_callbacks: list[callable] = []

        # 启动后台监控线程
        self._stop_event = threading.Event()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self):
        """后台监控循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._stop_event.is_set():
                try:
                    is_online = loop.run_until_complete(self._check_network())
                    with self._lock:
                        old_status = self._is_online
                        self._is_online = is_online
                        self._last_check = datetime.now()

                        # 状态变化时触发回调
                        if old_status != is_online:
                            if is_online:
                                logger.info("[NetworkMonitor] 网络恢复在线")
                                for cb in self._online_callbacks:
                                    try:
                                        cb()
                                    except Exception as e:
                                        logger.warning(f"[NetworkMonitor] 在线回调出错: {e}")
                            else:
                                logger.warning("[NetworkMonitor] 网络离线")
                                for cb in self._offline_callbacks:
                                    try:
                                        cb()
                                    except Exception as e:
                                        logger.warning(f"[NetworkMonitor] 离线回调出错: {e}")

                    self._stop_event.wait(self._check_interval)
                except Exception as e:
                    logger.error(f"[NetworkMonitor] 监控出错: {e}")
                    self._stop_event.wait(5)
        finally:
            loop.close()

    async def _check_network_async(self) -> bool:
        """【Phase 7.4】异步检查网络状态（使用 asyncio.open_connection）"""
        try:
            import asyncio
            hosts = [
                ("8.8.8.8", 53),      # Google DNS
                ("223.5.5.5", 53),    # 阿里DNS
                ("1.1.1.1", 53),      # Cloudflare
            ]
            for host, port in hosts:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=2
                    )
                    writer.close()
                    await writer.wait_closed()
                    return True
                except (asyncio.TimeoutError, OSError) as e:
                    logger.error(f"[SmartAIRouter] 网络连接测试失败 ({host}:{port}): {e}", exc_info=True)
                    continue
            return False
        except OSError as e:
            logger.error(f"[SmartAIRouter] 网络检查失败: {e}", exc_info=True)
            return False

    async def _check_network(self) -> bool:
        """检查网络状态（异步版本）"""
        try:
            return await self._check_network_async()
        except Exception as e:
            logger.error(f"[SmartAIRouter] 网络检查失败: {e}", exc_info=True)
            return False

    def is_online(self) -> bool:
        """获取当前网络状态"""
        with self._lock:
            return self._is_online

    def add_online_callback(self, callback: callable):
        """添加网络恢复回调"""
        self._online_callbacks.append(callback)

    def add_offline_callback(self, callback: callable):
        """添加网络断开回调"""
        self._offline_callbacks.append(callback)

    def stop(self):
        """停止监控"""
        self._stop_event.set()


class SmartAIRouter:
    """
    智能AI路由器 - 实现云端 ↔ 本地 自动切换

    核心功能：
    1. 任务复杂度评估
    2. 网络状态检测
    3. 本地模型失败检测与自动切换
    4. 云端模型负载均衡
    5. 成本感知路由
    """

    def __init__(self, deploy_mode: str | DeployMode = DeployMode.HYBRID):
        """
        初始化智能路由器

        Args:
            deploy_mode: 部署模式 (local/cloud/hybrid/auto)
        """
        self.deploy_mode = DeployMode(deploy_mode) if isinstance(deploy_mode, str) else deploy_mode

        # 本地Provider（Ollama）
        self._local_provider: AIProvider | None = None
        self._local_models: list[str] = []

        # 云端Providers
        self._cloud_providers: dict[str, AIProvider] = {}
        self._cloud_models: dict[str, list[str]] = {}

        # 模型健康状态
        self._model_health: dict[str, ModelHealth] = {}
        self._health_lock = threading.Lock()

        # 网络监控
        self._network_monitor = NetworkMonitor()
        self._network_monitor.add_offline_callback(self._on_network_offline)
        self._network_monitor.add_online_callback(self._on_network_online)

        # 模型路由器
        self._model_router = ModelRouter()

        # 性能统计
        self._performance_stats: dict[str, list[dict]] = {}
        self._stats_lock = threading.Lock()

        # 配置参数
        self._config = {
            "local_timeout": 30,           # 本地模型超时时间
            "cloud_timeout": 60,           # 云端模型超时时间
            "max_local_failures": 3,       # 本地模型最大失败次数
            "local_failure_window": 300,   # 本地模型失败检查窗口(秒)
            "complexity_threshold_simple": 100,  # 简单任务消息长度阈值
            "complexity_threshold_complex": 500, # 复杂任务消息长度阈值
            "cost_priority": 0.3,          # 成本优先级权重
            "quality_priority": 0.4,       # 质量优先级权重
            "speed_priority": 0.3,         # 速度优先级权重
        }

        # 初始化Providers
        self._init_providers()

        logger.info(f"[SmartAIRouter] 初始化完成，部署模式: {self.deploy_mode.value}")

    def _init_providers(self):
        """初始化所有Providers"""
        # 初始化本地Provider
        try:
            self._local_provider = AIProviderFactory.create_provider(
                "ollama",
                config={"base_url": "http://localhost:11434", "timeout": 120}
            )
            self._local_models = self._local_provider.get_model_list()
            logger.info(f"[SmartAIRouter] 本地Ollama可用，模型: {self._local_models[:5]}...")
        except Exception as e:
            logger.warning(f"[SmartAIRouter] 本地Ollama初始化失败: {e}")
            self._local_provider = None

        # 初始化云端Providers
        cloud_provider_types = ["openai", "anthropic", "deepseek", "qwen", "kimi"]
        for provider_type in cloud_provider_types:
            try:
                provider = AIProviderFactory.create_provider(provider_type, config={})
                if provider.is_available():
                    self._cloud_providers[provider_type] = provider
                    self._cloud_models[provider_type] = provider.get_model_list()
                    logger.info(f"[SmartAIRouter] 云端Provider可用: {provider_type}")
            except Exception as e:
                logger.debug(f"[SmartAIRouter] 云端Provider {provider_type} 不可用: {e}")

    def _on_network_offline(self):
        """网络断开回调"""
        logger.warning("[SmartAIRouter] 网络已断开，切换到离线模式")
        if self.deploy_mode == DeployMode.CLOUD:
            logger.error("[SmartAIRouter] 警告：当前为云端模式，但网络已断开！")

    def _on_network_online(self):
        """网络恢复回调"""
        logger.info("[SmartAIRouter] 网络已恢复，可以访问云端模型")
        # 重置云端模型健康状态
        with self._health_lock:
            for health in self._model_health.values():
                if health.provider_type != "ollama":
                    health.failure_count = 0
                    health.is_available = True

    def evaluate_complexity(self, message: str, context: list[dict] | None = None) -> TaskComplexity:
        """
        评估任务复杂度

        评估维度：
        1. 消息长度
        2. 是否包含视觉相关关键词
        3. 是否包含复杂任务关键词（分析、规划、推理等）
        4. 上下文长度

        Args:
            message: 用户消息
            context: 对话上下文

        Returns:
            TaskComplexity: 任务复杂度级别
        """
        message_len = len(message)
        context_len = sum(len(m.get("content", "")) for m in (context or []))
        total_len = message_len + context_len

        # 检查视觉任务
        vision_keywords = ["图片", "图像", "看图", "照片", "vision", "image", "picture", "photo", "图"]
        if any(kw in message for kw in vision_keywords):
            return TaskComplexity.VISION

        # 检查复杂任务关键词
        complex_keywords = [
            "分析", "规划", "计划", "推理", "证明", "详细", "深入", "复杂",
            "analyze", "plan", "strategy", "reasoning", "proof", "detailed", "complex",
            "写代码", "编程", "程序", "code", "program", "script", "function",
            "总结长文", "长文档", "论文", "报告", "thesis", "report", "document"
        ]
        has_complex_keyword = any(kw in message for kw in complex_keywords)

        # 根据长度和关键词判断
        if total_len < self._config["complexity_threshold_simple"] and not has_complex_keyword:
            # 短消息 + 无复杂关键词 = 简单任务
            return TaskComplexity.SIMPLE
        elif has_complex_keyword or total_len > self._config["complexity_threshold_complex"]:
            # 有复杂关键词 或 长消息 = 复杂任务
            return TaskComplexity.COMPLEX
        else:
            return TaskComplexity.MEDIUM

    def _get_local_health(self) -> ModelHealth:
        """获取本地模型健康状态"""
        with self._health_lock:
            if "ollama/local" not in self._model_health:
                self._model_health["ollama/local"] = ModelHealth(
                    provider_type="ollama",
                    model_name="local",
                    is_available=self._local_provider is not None and self._local_provider.is_available(),
                    last_check=datetime.now()
                )
            return self._model_health["ollama/local"]

    def _update_model_health(self, provider_type: str, model_name: str,
                             success: bool, latency_ms: float, error: str | None = None):
        """更新模型健康状态"""
        key = f"{provider_type}/{model_name}"
        with self._health_lock:
            if key not in self._model_health:
                self._model_health[key] = ModelHealth(
                    provider_type=provider_type,
                    model_name=model_name,
                    is_available=True,
                    last_check=datetime.now()
                )

            health = self._model_health[key]
            health.last_check = datetime.now()

            if success:
                health.failure_count = 0
                health.timeout_count = 0
                health.is_available = True
                # 更新平均延迟
                if health.avg_latency_ms == 0:
                    health.avg_latency_ms = latency_ms
                else:
                    health.avg_latency_ms = health.avg_latency_ms * 0.7 + latency_ms * 0.3
            else:
                health.failure_count += 1
                if error and ("timeout" in error.lower() or "超时" in error):
                    health.timeout_count += 1
                if error and ("oom" in error.lower() or "out of memory" in error.lower() or "内存" in error):
                    health.oom_detected = True

                # 检查是否需要标记为不可用
                if health.failure_count >= self._config["max_local_failures"]:
                    health.is_available = False
                    logger.warning(f"[SmartAIRouter] 模型 {key} 被标记为不可用（连续失败{health.failure_count}次）")

    def is_local_available(self) -> bool:
        """检查本地模型是否可用"""
        health = self._get_local_health()
        return (self._local_provider is not None and
                health.is_available and
                not health.oom_detected)

    def select_best_cloud_provider(self, complexity: TaskComplexity,
                                   require_vision: bool = False) -> tuple[str, str]:
        """
        选择最佳云端Provider

        Args:
            complexity: 任务复杂度
            require_vision: 是否需要视觉支持

        Returns:
            (provider_type, model_name)

        Raises:
            AIClientError: 无可用云端模型时抛出，绝不返回 None
        """
        # 根据复杂度选择策略
        if complexity == TaskComplexity.SIMPLE:
            # 简单任务：优先便宜的模型
            strategy = RoutingStrategy.CHEAPEST
        elif complexity == TaskComplexity.COMPLEX:
            # 复杂任务：优先高质量
            strategy = RoutingStrategy.BEST_QUALITY
        else:
            # 默认：平衡策略
            strategy = RoutingStrategy.BALANCED

        # 任务类型映射
        task_type_map = {
            TaskComplexity.SIMPLE: TaskType.CHAT,
            TaskComplexity.MEDIUM: TaskType.CHAT,
            TaskComplexity.COMPLEX: TaskType.ANALYSIS,
            TaskComplexity.VISION: TaskType.VISION,
        }
        task_type = task_type_map.get(complexity, TaskType.CHAT)

        try:
            # 使用ModelRouter选择模型
            self._model_router.set_user_strategy("smart_router", strategy)
            model_name = self._model_router.select_model(
                user_id="smart_router",
                task_type=task_type,
                required_vision=require_vision
            )

            # 解析 provider/name
            if "/" in model_name:
                provider_type, name = model_name.split("/", 1)
                return provider_type, name

            msg = f"[SmartAIRouter] 选择云端模型返回无效格式: {model_name}"
            logger.error(msg)
            raise AIClientError(msg)

        except AIClientError:
            raise
        except Exception as e:
            msg = f"[SmartAIRouter] 选择云端模型失败: {e}"
            logger.error(msg)
            raise AIClientError(msg) from e

    async def chat_with_auto_route(self, message: str,
                                   context: list[dict] | None = None,
                                   stream: bool = False,
                                   **kwargs) -> str | AsyncIterator[str] | RoutingDecision:
        """
        智能路由聊天 - 根据任务复杂度和网络状态自动选择模型

        Args:
            message: 用户消息
            context: 对话上下文
            stream: 是否流式输出
            **kwargs: 额外参数

        Returns:
            AI响应内容 或 流式迭代器
        """
        # 1. 检测网络状态
        is_online = self._network_monitor.is_online()

        # 2. 评估任务复杂度
        complexity = self.evaluate_complexity(message, context)
        logger.info(f"[SmartAIRouter] 任务复杂度: {complexity.value}, 网络状态: {'在线' if is_online else '离线'}")

        # 3. 根据部署模式和网络状态决策
        decision = await self._make_routing_decision(complexity, is_online, message)
        logger.info(f"[SmartAIRouter] 路由决策: {decision.provider_type}/{decision.model_name}, 原因: {decision.reason}")

        # 4. 执行调用
        messages = self._build_messages(message, context)

        try:
            if decision.provider_type == "ollama":
                return await self._call_local_model(messages, decision, stream, **kwargs)
            else:
                return await self._call_cloud_model(messages, decision, stream, **kwargs)
        except Exception as e:
            logger.error(f"[SmartAIRouter] 主调用失败: {e}")

            # 尝试fallback
            if not decision.is_fallback:
                fallback_decision = await self._get_fallback_decision(complexity, is_online, str(e))
                if fallback_decision:
                    logger.info(f"[SmartAIRouter] 切换到fallback: {fallback_decision.provider_type}/{fallback_decision.model_name}")
                    if fallback_decision.provider_type == "ollama":
                        return await self._call_local_model(messages, fallback_decision, stream, **kwargs)
                    else:
                        return await self._call_cloud_model(messages, fallback_decision, stream, **kwargs)

            raise

    def _build_messages(self, message: str, context: list[dict] | None = None) -> list[dict[str, str]]:
        """构建消息列表"""
        messages = []
        if context:
            for msg in context:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        messages.append({"role": "user", "content": message})
        return messages

    async def _make_routing_decision(self, complexity: TaskComplexity,
                                     is_online: bool,
                                     message: str) -> RoutingDecision:
        """
        做出路由决策

        决策逻辑：
        1. 离线模式：强制使用本地
        2. 云端模式：强制使用云端
        3. 本地模式：优先本地，失败时fallback到云端
        4. 混合/自动模式：根据复杂度和网络状态智能选择
        """
        # 检查视觉任务
        require_vision = complexity == TaskComplexity.VISION

        # 离线模式
        if not is_online or self.deploy_mode == DeployMode.LOCAL:
            if self.is_local_available():
                return RoutingDecision(
                    provider_type="ollama",
                    model_name=self._get_best_local_model(complexity),
                    complexity=complexity,
                    reason="离线模式或强制本地模式",
                    estimated_cost=0.0,
                    estimated_latency=500
                )
            else:
                raise AIClientError("本地模型不可用且网络离线")

        # 云端模式
        if self.deploy_mode == DeployMode.CLOUD:
            provider, model = self.select_best_cloud_provider(complexity, require_vision)
            profile = MODEL_PROFILES.get(f"{provider}/{model}")
            return RoutingDecision(
                provider_type=provider,
                model_name=model,
                complexity=complexity,
                reason="强制云端模式",
                estimated_cost=profile.capabilities.estimate_cost(1000, 500) if profile else 0.001,
                estimated_latency=profile.capabilities.avg_latency_ms if profile else 1500
            )

        # 混合/自动模式 - 智能选择
        if complexity == TaskComplexity.SIMPLE and self.is_local_available():
            # 简单任务 + 本地可用 = 优先本地
            return RoutingDecision(
                provider_type="ollama",
                model_name=self._get_best_local_model(complexity),
                complexity=complexity,
                reason="简单任务，优先使用本地模型节省成本",
                estimated_cost=0.0,
                estimated_latency=300
            )

        # 复杂任务或视觉任务 = 使用云端
        try:
            provider, model = self.select_best_cloud_provider(complexity, require_vision)
            profile = MODEL_PROFILES.get(f"{provider}/{model}")
            return RoutingDecision(
                provider_type=provider,
                model_name=model,
                complexity=complexity,
                reason=f"{complexity.value}任务，使用云端模型保证质量",
                estimated_cost=profile.capabilities.estimate_cost(1000, 500) if profile else 0.01,
                estimated_latency=profile.capabilities.avg_latency_ms if profile else 2000
            )
        except AIClientError:
            # 云端不可用，fallback到本地
            if self.is_local_available():
                return RoutingDecision(
                    provider_type="ollama",
                    model_name=self._get_best_local_model(complexity),
                    complexity=complexity,
                    reason="云端模型不可用，fallback到本地",
                    is_fallback=True,
                    estimated_cost=0.0,
                    estimated_latency=800
                )
            raise

    def _get_best_local_model(self, complexity: TaskComplexity) -> str:
        """根据复杂度选择最佳本地模型"""
        if complexity == TaskComplexity.VISION:
            return "llama3.2-vision:11b" if "llama3.2-vision:11b" in self._local_models else "qwen3:8b"
        elif complexity == TaskComplexity.SIMPLE:
            return "llama3.2:3b" if "llama3.2:3b" in self._local_models else "qwen3:8b"
        else:
            # COMPLEX, MEDIUM 等复杂任务使用更强的模型
            return "qwen3:8b"  # 默认

    async def _get_fallback_decision(self, complexity: TaskComplexity,
                                     is_online: bool,
                                     error: str) -> RoutingDecision:
        """获取Fallback决策

        Raises:
            AIClientError: 本地和云端均不可用时抛出
        """
        # 如果本地失败，尝试云端
        if ("ollama" in error.lower() or "local" in error.lower()) and is_online:
            try:
                provider, model = self.select_best_cloud_provider(complexity)
                return RoutingDecision(
                    provider_type=provider,
                    model_name=model,
                    complexity=complexity,
                    reason="本地模型失败，fallback到云端",
                    is_fallback=True
                )
            except AIClientError:
                pass  # 云端也不可用，继续尝试本地

        # 如果云端失败，尝试本地
        if self.is_local_available():
            return RoutingDecision(
                provider_type="ollama",
                model_name=self._get_best_local_model(complexity),
                complexity=complexity,
                reason="云端模型失败，fallback到本地",
                is_fallback=True
            )

        msg = "[SmartAIRouter] 本地和云端模型均不可用，无法生成 fallback 决策"
        logger.error(msg)
        raise AIClientError(msg)

    async def _call_local_model(self, messages: list[dict[str, str]],
                                decision: RoutingDecision,
                                stream: bool = False,
                                **kwargs) -> str | AsyncIterator[str]:
        """调用本地模型"""
        if not self._local_provider:
            raise AIClientError("本地Provider未初始化")

        start_time = time.time()
        try:
            if stream:
                # 流式调用（优先使用原生异步流式接口）
                async def stream_generator():
                    try:
                        if hasattr(self._local_provider, 'chat_stream_async'):
                            async for chunk in self._local_provider.chat_stream_async(messages, **kwargs):
                                yield chunk
                        elif hasattr(self._local_provider, 'chat_stream'):
                            for chunk in self._local_provider.chat_stream(messages, **kwargs):
                                yield chunk
                        else:
                            result = self._local_provider.chat(messages, **kwargs)
                            if not result:
                                msg = "[SmartAIRouter] 本地模型流式调用返回空响应"
                                logger.error(msg)
                                raise AIResponseError(msg)
                            yield result
                    except (AIResponseError, AIClientError):
                        raise
                    except Exception as e:
                        logger.error(f"[SmartAIRouter] 本地模型流式调用失败: {e}")
                        raise

                return stream_generator()
            else:
                # 非流式调用（优先使用原生异步接口）
                if hasattr(self._local_provider, 'chat_async') and callable(self._local_provider.chat_async):
                    result = await self._local_provider.chat_async(
                        messages,
                        model=decision.model_name,
                        timeout=self._config["local_timeout"],
                        **kwargs
                    )
                else:
                    result = await asyncio.to_thread(
                        self._local_provider.chat,
                        messages,
                        model=decision.model_name,
                        timeout=self._config["local_timeout"],
                        **kwargs
                    )

                latency_ms = (time.time() - start_time) * 1000
                self._update_model_health("ollama", decision.model_name, True, latency_ms)

                return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._update_model_health("ollama", decision.model_name, False, latency_ms, str(e))
            logger.warning(f"[SmartAIRouter] 本地模型调用失败: {e}")
            raise AIClientError(f"本地模型调用失败: {e}") from e

    async def _call_cloud_model(self, messages: list[dict[str, str]],
                                decision: RoutingDecision,
                                stream: bool = False,
                                **kwargs) -> str | AsyncIterator[str]:
        """调用云端模型"""
        provider = self._cloud_providers.get(decision.provider_type)
        if not provider:
            raise AIClientError(f"云端Provider {decision.provider_type} 不可用")

        start_time = time.time()
        try:
            if stream:
                # 流式调用（优先使用原生异步流式接口）
                async def stream_generator():
                    try:
                        if hasattr(provider, 'chat_stream_async'):
                            async for chunk in provider.chat_stream_async(messages, **kwargs):
                                yield chunk
                        elif hasattr(provider, 'chat_stream'):
                            for chunk in provider.chat_stream(messages, **kwargs):
                                yield chunk
                        else:
                            result = provider.chat(messages, **kwargs)
                            if not result:
                                msg = "[SmartAIRouter] 云端模型流式调用返回空响应"
                                logger.error(msg)
                                raise AIResponseError(msg)
                            yield result
                    except (AIResponseError, AIClientError):
                        raise
                    except Exception as e:
                        logger.error(f"[SmartAIRouter] 云端模型流式调用失败: {e}")
                        raise

                return stream_generator()
            else:
                # 非流式调用（优先使用原生异步接口）
                if hasattr(provider, 'chat_async') and callable(provider.chat_async):
                    result = await provider.chat_async(
                        messages,
                        model=decision.model_name,
                        timeout=self._config["cloud_timeout"],
                        **kwargs
                    )
                else:
                    result = await asyncio.to_thread(
                        provider.chat,
                        messages,
                        model=decision.model_name,
                        timeout=self._config["cloud_timeout"],
                        **kwargs
                    )

                latency_ms = (time.time() - start_time) * 1000
                self._update_model_health(decision.provider_type, decision.model_name, True, latency_ms)

                return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._update_model_health(decision.provider_type, decision.model_name, False, latency_ms, str(e))
            logger.warning(f"[SmartAIRouter] 云端模型调用失败: {e}")
            raise AIClientError(f"云端模型调用失败: {e}") from e

    def get_health_status(self) -> dict[str, Any]:
        """获取健康状态报告"""
        with self._health_lock:
            return {
                "network_online": self._network_monitor.is_online(),
                "local_available": self.is_local_available(),
                "cloud_providers": list(self._cloud_providers.keys()),
                "model_health": {
                    key: {
                        "is_available": health.is_available,
                        "failure_count": health.failure_count,
                        "avg_latency_ms": round(health.avg_latency_ms, 2),
                        "oom_detected": health.oom_detected,
                        "timeout_count": health.timeout_count,
                    }
                    for key, health in self._model_health.items()
                }
            }

    def reset_model_health(self, provider_type: str | None = None):
        """重置模型健康状态"""
        with self._health_lock:
            if provider_type:
                for key in list(self._model_health.keys()):
                    if key.startswith(provider_type):
                        self._model_health[key].is_available = True
                        self._model_health[key].failure_count = 0
                        self._model_health[key].oom_detected = False
            else:
                for health in self._model_health.values():
                    health.is_available = True
                    health.failure_count = 0
                    health.oom_detected = False

    def update_config(self, **kwargs):
        """更新配置"""
        self._config.update(kwargs)
        logger.info(f"[SmartAIRouter] 配置已更新: {kwargs}")

    def close(self):
        """关闭路由器，释放资源"""
        self._network_monitor.stop()
        logger.info("[SmartAIRouter] 已关闭")


class AIClientError(SiliconBaseException):
    """AI客户端异常 - 智能路由失败时抛出

    禁止静默失败，任何路由决策失败必须抛出此异常。
    """
    pass


# ==================== 便捷函数 ====================

_default_router: SmartAIRouter | None = None
_router_lock = threading.Lock()


def get_smart_router(deploy_mode: str | DeployMode = DeployMode.HYBRID) -> SmartAIRouter:
    """
    获取智能路由器单例

    Args:
        deploy_mode: 部署模式

    Returns:
        SmartAIRouter: 智能路由器实例
    """
    global _default_router
    if _default_router is None:
        with _router_lock:
            if _default_router is None:
                _default_router = SmartAIRouter(deploy_mode)
    return _default_router


def create_smart_router(deploy_mode: str | DeployMode = DeployMode.HYBRID) -> SmartAIRouter:
    """
    创建新的智能路由器实例

    Args:
        deploy_mode: 部署模式

    Returns:
        SmartAIRouter: 新的智能路由器实例
    """
    return SmartAIRouter(deploy_mode)


# ==================== 测试代码 ====================

if __name__ == "__main__":
    async def test():
        router = create_smart_router(DeployMode.HYBRID)

        # 测试复杂度评估
        test_messages = [
            ("你好", TaskComplexity.SIMPLE),
            ("帮我分析这个数据", TaskComplexity.COMPLEX),
            ("看这张图片", TaskComplexity.VISION),
            ("总结一下", TaskComplexity.MEDIUM),
        ]

        for msg, expected in test_messages:
            complexity = router.evaluate_complexity(msg)
            print(f"消息: '{msg}' -> 复杂度: {complexity.value} (期望: {expected.value})")

        # 测试健康状态
        health = router.get_health_status()
        print(f"\n健康状态: {json.dumps(health, indent=2, ensure_ascii=False)}")

        router.close()

    # 【规则7整改】使用new_event_loop替代asyncio.run，避免嵌套问题
    _test_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_test_loop)
    try:
        _test_loop.run_until_complete(test())
    finally:
        _test_loop.close()
