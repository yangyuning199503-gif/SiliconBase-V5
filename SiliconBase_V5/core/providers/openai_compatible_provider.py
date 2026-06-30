#!/usr/bin/env python3
# 【Phase 4】chat_async 继承自 OpenAIProvider，自动支持异步调用
"""
OpenAI兼容Provider - 支持所有OpenAI API格式的服务商
包括：DeepSeek、Kimi、通义千问、智谱GLM、火山引擎豆包、LocalAI、LM Studio等
"""

from typing import Any

from .base import ProviderCapabilities
from .openai_provider import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    """
    OpenAI兼容Provider
    通过配置base_url支持任意OpenAI API格式的服务
    """

    # 服务商配置映射
    PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
        # ========== 云端商业API ==========
        "deepseek": {
            "name": "DeepSeek",
            "category": "cloud",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
            "description": "DeepSeek AI - 高性价比大模型",
            "vision": False,  # 不支持视觉
            "function_calling": True,
        },
        "kimi": {
            "name": "Kimi (Moonshot)",
            "category": "cloud",
            "base_url": "https://api.moonshot.cn/v1",
            "default_model": "moonshot-v1-8k",
            "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            "description": "Moonshot Kimi - 长文本专家",
            "vision": False,  # 暂时不支持视觉
            "function_calling": True,
        },
        "qwen": {
            "name": "通义千问",
            "category": "cloud",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "default_model": "qwen-turbo",
            "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-coder-plus", "qwen-vl-plus"],
            "description": "阿里云通义千问系列",
            "vision": True,  # 支持通义千问VL
            "function_calling": True,
        },
        "glm": {
            "name": "智谱GLM",
            "category": "cloud",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "default_model": "glm-4",
            "models": ["glm-4", "glm-4-plus", "glm-4-air", "glm-3-turbo", "glm-4v"],
            "description": "智谱AI GLM大模型",
            "vision": True,  # 支持GLM-4V
            "function_calling": True,
        },
        "doubao": {
            "name": "火山引擎（豆包）",
            "category": "cloud",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "default_model": "doubao-pro-32k",
            "models": ["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k", "doubao-vision"],
            "description": "字节跳动火山引擎豆包大模型",
            "vision": True,  # 支持豆包视觉版
            "function_calling": True,
        },

        # ========== 本地部署方案 ==========
        "localai": {
            "name": "LocalAI",
            "category": "local",
            "base_url": "http://localhost:8080/v1",
            "default_model": "gpt-3.5-turbo",
            "models": [],  # 动态获取
            "description": "LocalAI - 本地OpenAI兼容服务",
            "vision": False,  # 取决于部署的模型
            "function_calling": False,
        },
        "lmstudio": {
            "name": "LM Studio",
            "category": "local",
            "base_url": "http://localhost:1234/v1",
            "default_model": "local-model",
            "models": [],  # 动态获取
            "description": "LM Studio - 本地模型管理",
            "vision": False,  # 取决于加载的模型
            "function_calling": False,
        },
        "dify": {
            "name": "Dify",
            "category": "local",
            "base_url": "http://localhost/v1",
            "default_model": "dify",
            "models": [],
            "description": "Dify - LLM应用开发平台",
            "vision": False,
            "function_calling": False,
        },
        "langflow": {
            "name": "Langflow",
            "category": "local",
            "base_url": "http://localhost:7860/api/v1",
            "default_model": "langflow",
            "models": [],
            "description": "Langflow - 可视化LLM工作流",
            "vision": False,
            "function_calling": False,
        },
        "pinokio": {
            "name": "Pinokio",
            "category": "local",
            "base_url": "http://localhost:8600/v1",
            "default_model": "pinokio",
            "models": [],
            "description": "Pinokio - AI应用浏览器",
            "vision": False,
            "function_calling": False,
        },
    }

    def __init__(self, **kwargs):
        """
        初始化OpenAI兼容Provider

        Args:
            config: 配置字典，包含 provider_type, base_url, model, api_key, timeout 等
        """
        # 从kwargs中获取config字典
        config = kwargs.get("config", kwargs)

        # 获取服务商类型
        provider_type = config.get("provider_type", "custom")
        provider_defaults = self.PROVIDER_CONFIGS.get(provider_type, {})

        # 合并配置：用户配置 > 默认配置
        base_url = config.get("base_url", provider_defaults.get("base_url", ""))
        model = config.get("model", provider_defaults.get("default_model", "gpt-3.5-turbo"))
        api_key = config.get("api_key", "")
        timeout = config.get("timeout", 30)

        # 调用父类初始化
        super().__init__(
            config={
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "timeout": timeout
            }
        )

        self._provider_type = provider_type
        self._provider_info = provider_defaults

    def get_capabilities(self) -> ProviderCapabilities:
        """返回OpenAI兼容Provider的能力声明"""
        info = self._provider_info
        model_lower = self.model.lower()

        # 检查模型是否支持视觉
        vision_models = ["vl", "vision", "glm-4v"]
        has_vision = info.get("vision", False) or any(vm in model_lower for vm in vision_models)

        return ProviderCapabilities(
            streaming=True,
            vision=has_vision,
            function_calling=info.get("function_calling", False),
            max_context_length=32768 if "32k" in model_lower or "128k" in model_lower else 4096
        )

    def get_config(self) -> dict:
        """获取配置信息"""
        config = super().get_config()
        config.update({
            "provider_type": self._provider_type,
            "name": self._provider_info.get("name", "Custom"),
            "category": self._provider_info.get("category", "other"),
            "description": self._provider_info.get("description", ""),
        })
        return config

    def get_model_list(self) -> list[str]:
        """获取可用模型列表"""
        # 如果有预设模型列表，直接返回
        preset_models = self._provider_info.get("models", [])
        if preset_models:
            return preset_models

        # 否则尝试从API获取
        try:
            return super().get_model_list()
        except Exception:
            # 本地服务可能不支持模型列表API，返回默认模型
            return [self.model]

    @classmethod
    def get_provider_info(cls, provider_type: str) -> dict[str, Any]:
        """
        获取服务商信息（用于前端显示）

        Returns:
            {
                "name": 显示名称,
                "category": cloud/local,
                "default_model": 默认模型,
                "models": 预设模型列表,
                "description": 描述,
                "required_config": ["api_key", "base_url"],
                "optional_config": ["timeout", "retry_times"],
            }
        """
        config = cls.PROVIDER_CONFIGS.get(provider_type, {})

        # 确定必需和可选配置
        required = ["api_key"]
        optional = ["timeout", "retry_times", "temperature", "max_tokens"]

        # 本地服务通常不需要api_key
        if config.get("category") == "local":
            required = []
            optional = ["api_key", "base_url", "timeout"]

        return {
            "type": provider_type,
            "name": config.get("name", provider_type),
            "category": config.get("category", "other"),
            "default_model": config.get("default_model", ""),
            "models": config.get("models", []),
            "description": config.get("description", ""),
            "base_url": config.get("base_url", ""),
            "required_config": required,
            "optional_config": optional,
            "vision": config.get("vision", False),
            "function_calling": config.get("function_calling", False),
        }

    @classmethod
    def list_supported_providers(cls) -> list[str]:
        """列出所有支持的服务商类型"""
        return list(cls.PROVIDER_CONFIGS.keys())
