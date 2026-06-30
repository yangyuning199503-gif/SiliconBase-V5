#!/usr/bin/env python3
"""
AI Provider工厂 - 管理多后端AI服务
"""

import threading
from typing import Any

from core.logger import logger
from core.providers.anthropic_provider import AnthropicProvider
from core.providers.base import AIProvider
from core.providers.custom_provider import CustomProvider
from core.providers.ollama_provider import OllamaProvider
from core.providers.openai_compatible_provider import OpenAICompatibleProvider
from core.providers.openai_provider import OpenAIProvider


class AIProviderFactory:
    """AI Provider工厂类 - 管理不同AI后端的实例创建"""

    _providers: dict[str, type[AIProvider]] = {
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "azure_openai": OpenAIProvider,
        "custom": CustomProvider,
        # OpenAI兼容服务商
        "deepseek": OpenAICompatibleProvider,
        "kimi": OpenAICompatibleProvider,
        "qwen": OpenAICompatibleProvider,
        "glm": OpenAICompatibleProvider,
        "doubao": OpenAICompatibleProvider,
        "localai": OpenAICompatibleProvider,
        "lmstudio": OpenAICompatibleProvider,
        "dify": OpenAICompatibleProvider,
        "langflow": OpenAICompatibleProvider,
        "pinokio": OpenAICompatibleProvider,
    }

    _current_provider: AIProvider | None = None
    _lock = threading.Lock()

    @classmethod
    def create_provider(cls, provider_type: str, **config) -> AIProvider:
        """
        创建指定类型的AI Provider实例

        Args:
            provider_type: Provider类型 (ollama/openai/anthropic/azure_openai/custom)
            **config: Provider配置参数

        Returns:
            AIProvider: 配置好的Provider实例

        Raises:
            ValueError: 不支持的Provider类型
        """
        provider_type = provider_type.lower()

        if provider_type not in cls._providers:
            raise ValueError(f"不支持的AI Provider类型: {provider_type}. "
                           f"支持的类型: {list(cls._providers.keys())}")

        provider_class = cls._providers[provider_type]

        # 处理特殊配置
        if provider_type == "azure_openai":
            config["is_azure"] = True

        # OpenAI兼容Provider需要传递provider_type
        if provider_class == OpenAICompatibleProvider:
            config["provider_type"] = provider_type

        # 统一使用 config 关键字参数
        return provider_class(config=config)

    @classmethod
    def get_current_provider(cls) -> AIProvider:
        """
        获取当前配置的AI Provider
        首次调用时会从配置文件创建

        Returns:
            AIProvider: 当前Provider实例，若未配置则返回默认OllamaProvider
        """
        if cls._current_provider is None:
            with cls._lock:
                if cls._current_provider is None:
                    try:
                        from core.config import config
                        # 优先从 ai.provider 读取，若未配置则从路由默认 provider 读取
                        provider_type = config.get("ai.provider") or config.get("ai.routing.default_provider")

                        if not provider_type:
                            # 未配置时返回默认Ollama，但记录警告
                            logger.warning("[AIProviderFactory] 未配置 ai.provider 或 ai.routing.default_provider，使用默认Ollama（可通过前端选择其他Provider）")
                            cls._current_provider = OllamaProvider(config={
                                "base_url": "http://localhost:11434",
                                "model": config.get("ai.default_model", "qwen3:8b"),
                                "timeout": 120,
                                "retry_times": 2
                            })
                            return cls._current_provider

                        # 优先从 ai.<provider_type> 读取配置（如 ai.ollama）
                        provider_config = config.get(f"ai.{provider_type}", {})

                        # 如果 provider_config 为空，尝试从 ai.config 读取（向后兼容）
                        if not provider_config:
                            provider_config = config.get("ai.config", {})

                        # 如果没有配置，使用合理的默认值
                        if not provider_config:
                            default_model = config.get("ai.default_model", "qwen3:8b")
                            provider_config = {
                                "base_url": "http://localhost:11434",
                                "model": default_model,
                                "timeout": 120,
                                "retry_times": 2
                            }

                        cls._current_provider = cls.create_provider(
                            provider_type, **provider_config
                        )
                    except Exception as e:
                        # 配置加载失败时降级到默认Ollama
                        logger.warning(f"[AIProviderFactory] 从配置加载AI Provider失败: {e}, 使用默认Ollama")
                        cls._current_provider = OllamaProvider(config={
                            "base_url": "http://localhost:11434",
                            "model": "qwen3:8b",
                            "timeout": 120,
                            "retry_times": 2
                        })

        return cls._current_provider

    @classmethod
    def refresh_provider(cls) -> AIProvider:
        """
        刷新当前Provider（配置热重载时使用）

        Returns:
            AIProvider: 新的Provider实例
        """
        with cls._lock:
            cls._current_provider = None
        return cls.get_current_provider()

    @classmethod
    def test_provider(cls, provider_type: str, config: dict = None, **kwargs) -> dict:
        """
        测试Provider配置是否有效（增强版，返回详细诊断信息）

        Args:
            provider_type: Provider类型
            config: Provider配置字典
            **kwargs: 额外配置（兼容旧接口）

        Returns:
            dict: 测试结果 {
                "success": bool,
                "message": str,
                "error": str|None,
                "available_models": List[str]  # 可用模型列表
            }
        """
        provider_config = config or kwargs

        try:
            provider = cls.create_provider(provider_type, **provider_config)

            # 获取Provider能力
            capabilities = provider.get_capabilities()

            # 基础连通性测试
            is_available = provider.is_available()
            if not is_available:
                return {
                    "success": False,
                    "message": (
                        f"无法连接到 {provider_type} 服务。\n"
                        f"可能原因：\n"
                        f"1. 服务未启动\n"
                        f"2. 配置的地址/端口不正确\n"
                        f"3. 网络连接问题"
                    ),
                    "error": "connection_failed",
                    "available_models": [],
                    "capabilities": {
                        "streaming": capabilities.streaming,
                        "vision": capabilities.vision,
                        "function_calling": capabilities.function_calling,
                        "max_context_length": capabilities.max_context_length,
                    }
                }

            # 获取可用模型列表
            available_models = provider.get_model_list()

            # 检查配置的模型是否存在
            configured_model = provider_config.get('model', '')
            if configured_model and available_models and configured_model not in available_models:
                model_list = ", ".join(available_models[:10])
                if len(available_models) > 10:
                    model_list += f" 等共 {len(available_models)} 个"

                # 根据Provider类型给出不同的模型安装提示
                provider_hints = {
                    "ollama": f"ollama pull {configured_model}",
                    "openai": "请在OpenAI官网查看可用模型",
                    "anthropic": "请在Anthropic官网查看可用模型",
                    "azure_openai": "请在Azure Portal中部署该模型",
                }

                # OpenAI兼容服务商的提示
                openai_compatible_hints = {
                    "deepseek": "请在DeepSeek平台查看可用模型",
                    "kimi": "请在Moonshot AI平台查看可用模型",
                    "qwen": "请在阿里云百炼平台查看可用模型",
                    "glm": "请在智谱AI开放平台查看可用模型",
                    "doubao": "请在火山引擎方舟平台查看可用模型",
                    "localai": "请在LocalAI服务端配置该模型",
                    "lmstudio": "请在LM Studio中加载该模型",
                }

                if provider_type in openai_compatible_hints:
                    install_hint = openai_compatible_hints[provider_type]
                else:
                    install_hint = provider_hints.get(provider_type, "请前往前端左侧工具栏 → AI模型选择进行配置")

                return {
                    "success": False,
                    "message": (
                        f"模型 '{configured_model}' 不存在。\n"
                        f"可用模型: {model_list}\n"
                        f"\n解决方法：\n"
                        f"1. {install_hint}\n"
                        f"2. 或选择其他可用模型\n"
                        f"3. 请前往前端左侧工具栏 → AI模型选择进行配置"
                    ),
                    "error": "model_not_found",
                    "available_models": available_models,
                    "capabilities": {
                        "streaming": capabilities.streaming,
                        "vision": capabilities.vision,
                        "function_calling": capabilities.function_calling,
                        "max_context_length": capabilities.max_context_length,
                    }
                }

            # 尝试实际调用
            try:
                test_result = provider.chat([
                    {"role": "user", "content": "Hi"}
                ], max_tokens=50, temperature=0.7)

                if test_result is not None and test_result.strip():
                    return {
                        "success": True,
                        "message": "连接成功！模型可正常使用。",
                        "error": None,
                        "available_models": available_models,
                        "response_preview": test_result[:100] if test_result else None,
                        "capabilities": {
                            "streaming": capabilities.streaming,
                            "vision": capabilities.vision,
                            "function_calling": capabilities.function_calling,
                            "max_context_length": capabilities.max_context_length,
                        }
                    }
                else:
                    # 连接成功但返回空，这可能是正常的（比如模型确实没有可回复的）
                    # 只要连接和模型检查通过，就认为配置有效
                    return {
                        "success": True,
                        "message": "连接成功！模型响应正常（返回内容为空，这是正常的）。",
                        "error": None,
                        "available_models": available_models,
                        "response_preview": "(模型返回空响应，但连接正常)",
                        "capabilities": {
                            "streaming": capabilities.streaming,
                            "vision": capabilities.vision,
                            "function_calling": capabilities.function_calling,
                            "max_context_length": capabilities.max_context_length,
                        }
                    }
            except Exception as call_error:
                error_msg = str(call_error)
                return {
                    "success": False,
                    "message": f"连接成功，但调用失败: {error_msg}",
                    "error": "call_failed",
                    "available_models": available_models,
                    "capabilities": {
                        "streaming": capabilities.streaming,
                        "vision": capabilities.vision,
                        "function_calling": capabilities.function_calling,
                        "max_context_length": capabilities.max_context_length,
                    }
                }

        except Exception as e:
            error_msg = str(e)
            return {
                "success": False,
                "message": f"测试失败: {error_msg}",
                "error": error_msg,
                "available_models": []
            }

    @classmethod
    def get_available_providers(cls) -> list:
        """获取可用的Provider类型列表（用于前端显示）"""
        return list(cls._providers.keys())

    @classmethod
    def get_provider_info(cls, provider_type: str) -> dict[str, Any]:
        """
        获取Provider详细信息（用于前端显示）

        Args:
            provider_type: Provider类型

        Returns:
            Provider信息字典
        """
        provider_type = provider_type.lower()

        # OpenAI兼容Provider的特殊处理
        if provider_type in OpenAICompatibleProvider.list_supported_providers():
            return OpenAICompatibleProvider.get_provider_info(provider_type)

        # 标准Provider的信息
        provider_info_map = {
            "ollama": {
                "name": "Ollama",
                "category": "local",
                "description": "本地Ollama服务",
                "required_config": [],
                "optional_config": ["base_url", "model", "timeout"],
                "default_model": "qwen3:8b",
            },
            "openai": {
                "name": "OpenAI",
                "category": "cloud",
                "description": "OpenAI官方API",
                "required_config": ["api_key"],
                "optional_config": ["base_url", "model", "timeout"],
                "default_model": "gpt-4",
            },
            "anthropic": {
                "name": "Anthropic Claude",
                "category": "cloud",
                "description": "Anthropic Claude系列",
                "required_config": ["api_key"],
                "optional_config": ["model", "timeout"],
                "default_model": "claude-3-opus",
            },
            "azure_openai": {
                "name": "Azure OpenAI",
                "category": "cloud",
                "description": "微软Azure OpenAI服务",
                "required_config": ["api_key", "base_url"],
                "optional_config": ["model", "timeout"],
                "default_model": "gpt-4",
            },
            "custom": {
                "name": "自定义",
                "category": "other",
                "description": "自定义OpenAI兼容服务",
                "required_config": ["base_url"],
                "optional_config": ["api_key", "model", "timeout"],
                "default_model": "",
            },
        }

        return provider_info_map.get(provider_type, {
            "name": provider_type,
            "category": "other",
            "description": "",
            "required_config": ["api_key"],
            "optional_config": ["base_url", "model", "timeout"],
            "default_model": "",
        })

    @classmethod
    def list_supported_providers(cls) -> list:
        """获取支持的Provider类型列表"""
        return list(cls._providers.keys())

    @classmethod
    def register_provider(cls, name: str, provider_class: type[AIProvider]):
        """
        注册自定义Provider

        Args:
            name: Provider名称
            provider_class: Provider类（必须继承AIProvider）
        """
        if not issubclass(provider_class, AIProvider):
            raise ValueError("Provider类必须继承AIProvider")
        cls._providers[name.lower()] = provider_class

    # ========== 视觉能力相关方法 ==========

    @classmethod
    def get_vision_providers(cls) -> list[str]:
        """
        获取所有支持视觉能力的Provider类型列表

        Returns:
            支持视觉的Provider类型列表
        """
        vision_providers = []

        for provider_type, provider_class in cls._providers.items():
            try:
                # 尝试创建临时实例来检查能力
                if provider_class == OpenAICompatibleProvider:
                    # OpenAI兼容Provider需要特殊配置
                    pass
                else:
                    # 标准Provider
                    pass

                # 使用类方法检查能力（避免创建实际实例）
                # 这里我们根据Provider类型静态判断
                vision_capable_providers = [
                    "ollama",       # 支持Qwen3-VL等
                    "openai",       # 支持GPT-4V
                    "azure_openai", # 支持GPT-4V
                    "anthropic",    # 支持Claude 3
                    "qwen",         # 通义千问VL
                    "glm",          # 智谱GLM-4V
                    "doubao",       # 豆包视觉版
                ]

                if provider_type in vision_capable_providers:
                    vision_providers.append(provider_type)

            except Exception as e:
                logger.warning(f"[AIProviderFactory] 检查Provider视觉能力失败: {e}")
                continue

        return vision_providers

    @classmethod
    def get_current_vision_provider(cls) -> AIProvider | None:
        """
        获取当前配置的Provider，如果它支持视觉能力

        Returns:
            当前Provider实例（如果支持视觉），否则返回None
        """
        try:
            current = cls.get_current_provider()
            if current and current.get_capabilities().vision:
                return current
        except Exception as e:
            logger.warning(f"[AIProviderFactory] 获取当前视觉Provider失败: {e}")
        return None

    @classmethod
    def get_first_available_vision_provider(cls, **kwargs) -> AIProvider | None:
        """
        获取第一个可用的支持视觉能力的Provider

        Args:
            **kwargs: 传递给Provider的配置参数

        Returns:
            第一个可用且支持视觉的Provider实例，如果没有则返回None
        """
        vision_providers = [
            "ollama",
            "openai",
            "anthropic",
            "azure_openai",
            "qwen",
            "glm",
            "doubao",
        ]

        for provider_type in vision_providers:
            try:
                provider = cls.create_provider(provider_type, **kwargs)
                if provider.is_available() and provider.get_capabilities().vision:
                    return provider
            except Exception as e:
                logger.warning(f"[AIProviderFactory] 创建视觉Provider失败: {e}")
                continue

        return None

    @classmethod
    def create_vision_provider(cls, provider_type: str, **config) -> AIProvider:
        """
        创建一个明确用于视觉任务的Provider

        Args:
            provider_type: Provider类型
            **config: Provider配置

        Returns:
            配置好的Provider实例

        Raises:
            ValueError: 如果Provider不支持视觉能力
        """
        provider = cls.create_provider(provider_type, **config)

        if not provider.get_capabilities().vision:
            raise ValueError(
                f"Provider '{provider_type}' 不支持视觉能力。"
                f"支持的视觉Provider: {cls.get_vision_providers()}"
            )

        return provider
