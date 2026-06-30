#!/usr/bin/env python3
"""
多模型路由系统 - Multi-Model Router System
支持GPT-4/Claude/DeepSeek/Ollama动态切换与智能降级

核心设计原则（异常处理铁律）：
1. ❌ 禁止模型调用失败时静默降级而不记录
2. ✅ 模型调用失败 = ERROR日志 + 尝试降级 + 降级失败抛错
3. ✅ 所有模型都失败 = ERROR日志 + 抛错
4. ✅ 用户必须知道当前使用的模型

部署日期: 2026-03-12
作者: Agent9
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.config import config
from core.logger import logger


# Provider导入 - 延迟加载避免循环依赖
def _get_provider_factory():
    """延迟导入Provider工厂"""
    from core.providers.ai_provider_factory import AIProviderFactory
    return AIProviderFactory


class TaskType(Enum):
    """任务类型枚举"""
    GENERAL = "general"           # 一般对话
    COMPLEX_REASONING = "complex_reasoning"  # 复杂推理
    CODE = "code"                 # 代码生成
    VISION = "vision"             # 视觉任务
    CREATIVE = "creative"         # 创意写作
    SUMMARIZE = "summarize"       # 摘要总结


class ModelRoutingError(Exception):
    """模型路由失败 - 所有模型都不可用"""
    pass


class ModelEmptyResponseError(Exception):
    """模型返回空响应"""
    pass


class ModelProviderNotAvailableError(Exception):
    """模型提供商不可用"""
    pass


class RoutingStrategy(Enum):
    """路由策略枚举"""
    BEST_QUALITY = "best_quality"    # 优先质量
    CHEAPEST = "cheapest"            # 优先成本
    BALANCED = "balanced"            # 平衡策略
    FASTEST = "fastest"              # 优先速度


@dataclass
class ModelResult:
    """模型调用结果"""
    content: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ProviderConfig:
    """提供商配置"""
    name: str
    enabled: bool = True
    priority: int = 100
    api_key_env: str = ""
    base_url: str = ""
    default_model: str = ""
    timeout: int = 60


class ModelRouter:
    """
    模型路由器 - 支持多模型动态切换与智能降级

    使用示例:
        router = ModelRouter()
        result = await router.chat(messages, task_type="code")
        print(f"使用模型: {result.provider}/{result.model}")
    """

    # 默认优先级配置（数值越小优先级越高）
    PROVIDER_PRIORITY = ["deepseek", "anthropic", "openai", "ollama"]

    # 任务类型到优先级的映射
    TASK_PRIORITY_MAP = {
        TaskType.COMPLEX_REASONING: ["openai", "anthropic", "deepseek", "ollama"],
        TaskType.CODE: ["anthropic", "openai", "deepseek", "ollama"],
        TaskType.VISION: ["openai", "anthropic", "ollama"],
        TaskType.CREATIVE: ["anthropic", "openai", "deepseek", "ollama"],
        TaskType.SUMMARIZE: ["deepseek", "openai", "anthropic", "ollama"],
        TaskType.GENERAL: ["deepseek", "anthropic", "openai", "ollama"],
    }

    # 提供商到默认模型的映射
    DEFAULT_MODELS = {
        "openai": "gpt-4",
        "anthropic": "claude-3-opus",
        "deepseek": "deepseek-chat",
        "ollama": "qwen3:8b",
    }

    def __init__(self):
        """初始化模型路由器"""
        self.providers: dict[str, Any] = {}
        self.provider_configs: dict[str, ProviderConfig] = {}
        self._current_provider: str | None = None
        self._fallback_count: dict[str, int] = {}  # 降级次数统计

        # 配置热加载支持 - 使用版本号机制避免全局刷新冲突
        self._config_version: int = -1  # 当前配置版本号
        self.task_priority: dict[str, list[str]] = {}  # 动态任务优先级配置

        self._init_providers()
        self._load_config()  # 加载路由配置

    def _init_providers(self):
        """初始化所有提供商"""
        factory = _get_provider_factory()

        # OpenAI配置
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                self.providers["openai"] = factory.create_provider(
                    "openai",
                    api_key=openai_key,
                    model=self.DEFAULT_MODELS["openai"],
                    timeout=60
                )
                self.provider_configs["openai"] = ProviderConfig(
                    name="openai",
                    enabled=True,
                    priority=2,
                    api_key_env="OPENAI_API_KEY",
                    default_model=self.DEFAULT_MODELS["openai"]
                )
                logger.info("[ModelRouter] OpenAI提供商已初始化")
            except Exception as e:
                logger.error(f"[ModelRouter] OpenAI初始化失败: {e}", exc_info=True)
        else:
            logger.info("[ModelRouter] OpenAI未配置(缺少OPENAI_API_KEY)")

        # Anthropic配置
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                self.providers["anthropic"] = factory.create_provider(
                    "anthropic",
                    api_key=anthropic_key,
                    model=self.DEFAULT_MODELS["anthropic"],
                    timeout=60
                )
                self.provider_configs["anthropic"] = ProviderConfig(
                    name="anthropic",
                    enabled=True,
                    priority=1,
                    api_key_env="ANTHROPIC_API_KEY",
                    default_model=self.DEFAULT_MODELS["anthropic"]
                )
                logger.info("[ModelRouter] Anthropic提供商已初始化")
            except Exception as e:
                logger.error(f"[ModelRouter] Anthropic初始化失败: {e}", exc_info=True)
        else:
            logger.info("[ModelRouter] Anthropic未配置(缺少ANTHROPIC_API_KEY)")

        # DeepSeek配置
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                self.providers["deepseek"] = factory.create_provider(
                    "deepseek",
                    api_key=deepseek_key,
                    model=self.DEFAULT_MODELS["deepseek"],
                    timeout=60
                )
                self.provider_configs["deepseek"] = ProviderConfig(
                    name="deepseek",
                    enabled=True,
                    priority=0,  # 默认最高优先级（便宜）
                    api_key_env="DEEPSEEK_API_KEY",
                    default_model=self.DEFAULT_MODELS["deepseek"]
                )
                logger.info("[ModelRouter] DeepSeek提供商已初始化")
            except Exception as e:
                logger.error(f"[ModelRouter] DeepSeek初始化失败: {e}", exc_info=True)
        else:
            logger.info("[ModelRouter] DeepSeek未配置(缺少DEEPSEEK_API_KEY)")

        # Ollama（本地模型）- 总是尝试初始化
        try:
            self.providers["ollama"] = factory.create_provider(
                "ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                model=self.DEFAULT_MODELS["ollama"],
                timeout=120
            )
            self.provider_configs["ollama"] = ProviderConfig(
                name="ollama",
                enabled=True,
                priority=10,  # 本地模型优先级最低（慢但免费）
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                default_model=self.DEFAULT_MODELS["ollama"]
            )
            logger.info("[ModelRouter] Ollama提供商已初始化")
        except Exception as e:
            logger.warning(f"[ModelRouter] Ollama初始化失败: {e}")

        # 初始化降级计数
        self._fallback_count = dict.fromkeys(self.providers.keys(), 0)

        # 记录可用提供商
        available = list(self.providers.keys())
        logger.info(f"[ModelRouter] 可用提供商: {available}")

    def _load_config(self):
        """
        从配置系统加载任务优先级配置

        读取 ai.routing.task_priority 配置，如果配置不存在或格式错误，
        则使用硬编码默认值。

        遵循修复铁律：
        1. 所有裸 Exception 必须打 ERROR 级别日志
        2. 禁止静默失败，配置错误时抛出明确异常并使用默认值
        3. 使用版本号机制避免全局刷新冲突
        """
        try:
            # 获取配置版本号（用于检测配置变更）
            current_version = config.get("_config_version", 0)
            if isinstance(current_version, int):
                self._config_version = current_version
            else:
                self._config_version = 0

            # 读取任务优先级配置
            task_priority = config.get("ai.routing.task_priority")

            if not task_priority:
                # 配置不存在，使用默认值
                logger.debug("[ModelRouter] ai.routing.task_priority 未配置，使用默认值")
                self.task_priority = self._get_default_priority()
                return

            # 验证配置格式
            if not isinstance(task_priority, dict):
                error_msg = f"[ModelRouter] ai.routing.task_priority 格式错误: 期望dict，实际{type(task_priority)}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # 验证必需键 - 配置格式错误时抛出明确异常
            required_keys = ['complex_reasoning', 'code', 'vision', 'general']
            missing = [k for k in required_keys if k not in task_priority]
            if missing:
                error_msg = f"[ModelRouter] ai.routing.task_priority 配置缺少必需键: {missing}"
                logger.error(error_msg)
                raise ValueError(f"ai.routing.task_priority 配置不完整: {missing}")

            # 验证每个任务类型的值是否为列表
            for task_type, providers in task_priority.items():
                if not isinstance(providers, list):
                    error_msg = f"[ModelRouter] ai.routing.task_priority.{task_type} 格式错误: 期望list，实际{type(providers)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)

            # 配置验证通过，使用配置值
            self.task_priority = task_priority
            logger.info(f"[ModelRouter] 已加载 ai.routing.task_priority: {list(task_priority.keys())}")

        except Exception as e:
            # 【修复铁律】所有裸 Exception 必须打 ERROR 级别日志
            logger.error(f"[ModelRouter] 加载 ai.routing.task_priority 配置失败: {e}", exc_info=True)
            # 使用默认值，不中断服务 - 不破坏原有流程
            self.task_priority = self._get_default_priority()

    def _get_default_priority(self) -> dict[str, list[str]]:
        """
        获取默认的任务优先级配置

        Returns:
            默认的任务类型到提供商列表的映射
        """
        return {
            'complex_reasoning': ['openai', 'anthropic', 'deepseek', 'ollama'],
            'code': ['anthropic', 'openai', 'deepseek', 'ollama'],
            'vision': ['openai', 'anthropic', 'ollama'],
            'general': ['deepseek', 'anthropic', 'openai', 'ollama'],
            'creative': ['anthropic', 'openai', 'deepseek', 'ollama'],
            'summarize': ['deepseek', 'openai', 'anthropic', 'ollama'],
        }

    def _check_config_update(self):
        """
        检查配置是否已更新，如有更新则重新加载

        使用版本号机制避免全局刷新冲突。
        """
        try:
            current_version = config.get("_config_version", 0)
            if current_version != self._config_version:
                logger.debug(f"[ModelRouter] 配置版本变更: {self._config_version} -> {current_version}，重新加载")
                self._load_config()
        except Exception as e:
            logger.error(f"[ModelRouter] 检查配置更新失败: {e}", exc_info=True)

    def _get_priority_by_task(self, task_type: str) -> list[str]:
        """
        根据任务类型确定模型优先级

        支持从配置系统动态加载 ai.routing.task_priority，
        并在配置变更时自动更新。

        Args:
            task_type: 任务类型字符串

        Returns:
            按优先级排序的提供商列表

        Raises:
            ValueError: 任务类型无效
        """
        # 检查配置是否已更新（版本号机制）
        self._check_config_update()

        # 转换为枚举
        try:
            task_enum = TaskType(task_type.lower())
        except ValueError as _exc:
            logger.error(f"[ModelRouter] 未知的任务类型: {task_type}")
            raise ValueError(f"不支持的任务类型: {task_type}") from _exc

        # 优先使用动态配置，如果没有则使用硬编码默认值
        task_type_key = task_enum.value
        if self.task_priority and task_type_key in self.task_priority:
            # 使用从配置系统加载的动态配置
            priority = self.task_priority[task_type_key]
            logger.debug(f"[ModelRouter] 使用动态配置优先级 for {task_type_key}: {priority}")
        else:
            # 使用硬编码默认值
            priority = self.TASK_PRIORITY_MAP.get(task_enum, self.TASK_PRIORITY_MAP[TaskType.GENERAL])
            logger.debug(f"[ModelRouter] 使用默认优先级 for {task_type_key}: {priority}")

        # 过滤掉未启用的提供商
        enabled_priority = [
            p for p in priority
            if p in self.providers and self.provider_configs.get(p, ProviderConfig(name=p)).enabled
        ]

        # 如果没有可用的提供商，尝试使用任何可用的提供商
        if not enabled_priority:
            enabled_priority = [
                p for p in self.PROVIDER_PRIORITY
                if p in self.providers
            ]
            logger.warning(f"[ModelRouter] 任务类型 {task_type} 的优先级提供商均不可用，使用默认优先级")

        if not enabled_priority:
            logger.error("[ModelRouter] 没有任何可用的AI提供商")
            raise RuntimeError("所有AI提供商均不可用")

        return enabled_priority

    def _validate_messages(self, messages: list) -> None:
        """
        验证消息格式

        Args:
            messages: 消息列表

        Raises:
            ValueError: 消息格式无效
        """
        if not messages:
            logger.error("[ModelRouter] messages为空")
            raise ValueError("messages不能为空")

        if not isinstance(messages, list):
            logger.error(f"[ModelRouter] messages类型错误: {type(messages)}")
            raise ValueError("messages必须是列表")

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                logger.error(f"[ModelRouter] 消息[{i}]类型错误: {type(msg)}")
                raise ValueError(f"消息[{i}]必须是字典")

            if "role" not in msg or "content" not in msg:
                logger.error(f"[ModelRouter] 消息[{i}]缺少必要字段")
                raise ValueError(f"消息[{i}]必须包含'role'和'content'字段")

    async def chat(
        self,
        messages: list,
        task_type: str = "general",
        preferred_provider: str | None = None,
        **kwargs
    ) -> ModelResult:
        """
        智能路由聊天请求

        失败时尝试降级，所有都失败则抛错。
        每次降级都会记录ERROR日志。

        Args:
            messages: 消息列表
            task_type: 任务类型 (general/complex_reasoning/code/vision/creative/summarize)
            preferred_provider: 首选提供商
            **kwargs: 额外参数传递给底层provider

        Returns:
            ModelResult: 包含内容、提供商、模型等信息的结果

        Raises:
            ModelRoutingError: 所有模型都失败
            ValueError: 消息格式无效
        """
        # 验证消息
        self._validate_messages(messages)

        # 确定优先级
        if preferred_provider and preferred_provider in self.providers:
            priority = [preferred_provider] + [
                p for p in self._get_priority_by_task(task_type)
                if p != preferred_provider
            ]
            logger.info(f"[ModelRouter] 使用首选提供商: {preferred_provider}")
        else:
            priority = self._get_priority_by_task(task_type)

        logger.info(f"[ModelRouter] 任务类型: {task_type}, 优先级顺序: {priority}")

        last_error = None
        attempted_providers = []

        for provider_name in priority:
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            attempted_providers.append(provider_name)

            try:
                logger.info(f"[ModelRouter] 尝试使用 {provider_name}...")

                # 检查提供商可用性
                if not provider.is_available():
                    error_msg = f"{provider_name} 服务不可用"
                    logger.error(f"[ModelRouter] {error_msg}")
                    last_error = ModelProviderNotAvailableError(error_msg)
                    continue

                # 获取模型名称
                model_name = self.provider_configs.get(
                    provider_name,
                    ProviderConfig(name=provider_name, default_model="unknown")
                ).default_model

                # 记录开始时间
                start_time = datetime.now()

                # 调用提供商（原生异步接口，彻底消除 run_in_executor）
                response = await provider.chat_async(messages, **kwargs)

                # 计算延迟
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # 验证结果
                if response is None:
                    logger.error(f"[ModelRouter] {provider_name} 返回None")
                    last_error = ModelEmptyResponseError(f"{provider_name} 返回None")
                    self._fallback_count[provider_name] += 1
                    continue

                content = str(response).strip()
                if not content:
                    logger.error(f"[ModelRouter] {provider_name} 返回空内容")
                    last_error = ModelEmptyResponseError(f"{provider_name} 返回空响应")
                    self._fallback_count[provider_name] += 1
                    continue

                # 成功！记录使用的模型
                self._current_provider = provider_name
                logger.info(f"[ModelRouter] ✅ 成功使用 {provider_name}/{model_name} (延迟: {latency_ms}ms)")

                # 重置降级计数
                self._fallback_count[provider_name] = 0

                return ModelResult(
                    content=content,
                    provider=provider_name,
                    model=model_name,
                    latency_ms=latency_ms
                )

            except Exception as e:
                # 【异常处理铁律】记录ERROR日志 + 尝试降级
                error_msg = f"[ModelRouter] {provider_name} 失败: {type(e).__name__}: {e}"
                logger.error(error_msg, exc_info=True)
                last_error = e
                self._fallback_count[provider_name] += 1
                continue  # 尝试下一个

        # 所有模型都失败
        error_detail = f"已尝试: {attempted_providers}, 最后错误: {last_error}"
        logger.error(f"[ModelRouter] 所有模型都失败！{error_detail}")
        raise ModelRoutingError(f"所有AI模型都不可用: {last_error}") from last_error

    def get_current_provider(self) -> str | None:
        """获取当前使用的提供商名称"""
        return self._current_provider

    def get_available_providers(self) -> list[str]:
        """获取所有可用的提供商列表"""
        available = []
        for name, provider in self.providers.items():
            try:
                if provider.is_available():
                    available.append(name)
            except Exception as e:
                logger.debug(f"[ModelRouter] 检查{name}可用性失败: {e}")
        return available

    def get_fallback_stats(self) -> dict[str, int]:
        """获取降级统计"""
        return self._fallback_count.copy()

    def get_provider_info(self) -> dict[str, dict]:
        """获取所有提供商信息"""
        info = {}
        for name, cfg in self.provider_configs.items():
            info[name] = {
                "name": cfg.name,
                "enabled": cfg.enabled,
                "priority": cfg.priority,
                "default_model": cfg.default_model,
                "available": name in self.providers,
                "fallback_count": self._fallback_count.get(name, 0),
            }
        return info

    def set_provider_priority(self, task_type: str, priority: list[str]):
        """
        设置任务类型的提供商优先级

        同时更新动态配置和硬编码默认值。

        Args:
            task_type: 任务类型
            priority: 按优先级排序的提供商列表
        """
        try:
            task_enum = TaskType(task_type.lower())
        except ValueError as _exc:
            logger.error(f"[ModelRouter] 未知任务类型: {task_type}")
            raise ValueError(f"不支持的任务类型: {task_type}") from _exc

        # 验证优先级列表
        if not isinstance(priority, list):
            logger.error(f"[ModelRouter] 优先级必须是列表，实际类型: {type(priority)}")
            raise ValueError("优先级必须是提供商名称列表")

        # 更新硬编码默认值（向后兼容）
        self.TASK_PRIORITY_MAP[task_enum] = priority

        # 更新动态配置
        task_type_key = task_enum.value
        self.task_priority[task_type_key] = priority

        logger.info(f"[ModelRouter] 已设置{task_type}的优先级: {priority}")

    def enable_provider(self, name: str):
        """启用提供商"""
        if name in self.provider_configs:
            self.provider_configs[name].enabled = True
            logger.info(f"[ModelRouter] 已启用 {name}")

    def disable_provider(self, name: str):
        """禁用提供商"""
        if name in self.provider_configs:
            self.provider_configs[name].enabled = False
            logger.info(f"[ModelRouter] 已禁用 {name}")


# 全局单例实例
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局模型路由器实例"""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router


def reset_model_router():
    """重置模型路由器（配置变更时调用）"""
    global _model_router
    _model_router = None
    logger.info("[ModelRouter] 已重置")


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件是SiliconBase V5的多模型路由系统核心模块，负责：
#   1. 管理多个AI提供商（OpenAI/Anthropic/DeepSeek/Ollama）
#   2. 根据任务类型智能选择最优模型
#   3. 实现失败降级机制，确保服务可用性
#   4. 严格遵守异常处理铁律：失败必记录、降级必通知、全失败必抛错
#
# 【核心类】
# 1. ModelRouter: 多模型路由器（核心类）
#    - chat(): 主调用方法，支持动态切换和降级
#    - 属性:
#      - providers: 提供商实例字典
#      - provider_configs: 提供商配置字典
#      - TASK_PRIORITY_MAP: 任务类型到优先级的映射
#
# 2. ModelResult: 模型调用结果数据类
#    - content: AI响应内容
#    - provider: 使用的提供商名称
#    - model: 使用的模型名称
#    - latency_ms: 响应延迟
#
# 3. 异常类:
#    - ModelRoutingError: 所有模型都失败
#    - ModelEmptyResponseError: 模型返回空响应
#    - ModelProviderNotAvailableError: 提供商不可用
#
# 【使用方式】
# 方式1: 直接使用
#   router = ModelRouter()
#   result = await router.chat(messages, task_type="code")
#   print(f"使用模型: {result.provider}/{result.model}")
#   print(f"AI回复: {result.content}")
#
# 方式2: 使用单例
#   router = get_model_router()
#   result = await router.chat(messages)
#
# 【异常处理铁律】
# 1. 每个provider失败都会记录ERROR日志
# 2. 降级时会记录INFO日志通知用户
# 3. 所有provider都失败时抛出ModelRoutingError
# 4. 返回结果包含provider和model信息，用户知道当前使用的模型
#
# 【配置要求】
# 环境变量:
#   - OPENAI_API_KEY: OpenAI API密钥
#   - ANTHROPIC_API_KEY: Anthropic API密钥
#   - DEEPSEEK_API_KEY: DeepSeek API密钥
#   - OLLAMA_BASE_URL: Ollama服务地址（默认: http://localhost:11434）
#
# 【关联文件】
#   - core/providers/ai_provider_factory.py: Provider工厂
#   - core/providers/base.py: Provider基类
#   - core/agent_loop.py: 使用ModelRouter进行AI调用
#   - core/exceptions.py: 异常定义
#
# =============================================================================
