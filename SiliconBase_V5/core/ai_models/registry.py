"""
ModelBus注册中心模块

管理所有Provider的注册和发现
"""

import asyncio
import logging
import time
from typing import Any

from .base import BaseModelProvider, ModelType, ProviderInfo
from .exceptions import ProviderNotFoundException, RegistryException

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    ModelRegistry - Provider注册中心

    负责管理所有Provider类的注册和发现
    按ModelType分类存储，支持动态注册
    """

    def __init__(self):
        """初始化注册中心"""
        # 存储结构: {model_type: {provider_type: ProviderInfo}}
        self._registry: dict[ModelType, dict[str, ProviderInfo]] = {}
        self._lock = asyncio.Lock()
        self._initialized_at = time.time()

        logger.info("[ModelRegistry] 注册中心初始化完成")

    async def register(
        self,
        provider_type: str,
        model_type: ModelType,
        provider_class: type[BaseModelProvider],
        description: str = "",
        version: str = "1.0.0"
    ) -> None:
        """
        注册Provider类

        Args:
            provider_type: Provider类型标识（如 'openai', 'anthropic'）
            model_type: 模型类型
            provider_class: Provider类（必须是BaseModelProvider的子类）
            description: Provider描述
            version: Provider版本

        Raises:
            RegistryException: 注册失败时抛出
        """
        async with self._lock:
            # 验证provider_class
            if not issubclass(provider_class, BaseModelProvider):
                error_msg = f"Provider类必须是BaseModelProvider的子类: {provider_class.__name__}"
                logger.error(f"[ModelRegistry] 注册失败: {error_msg}")
                raise RegistryException(error_msg, provider_type)

            # 验证model_type
            if not isinstance(model_type, ModelType):
                error_msg = f"无效的ModelType: {model_type}"
                logger.error(f"[ModelRegistry] 注册失败: provider_type={provider_type}, error={error_msg}")
                raise RegistryException(error_msg, provider_type)

            # 初始化该ModelType的存储
            if model_type not in self._registry:
                self._registry[model_type] = {}
                logger.debug(f"[ModelRegistry] 创建ModelType存储: {model_type}")

            # 检查是否已存在
            if provider_type in self._registry[model_type]:
                existing = self._registry[model_type][provider_type]
                logger.warning(
                    f"[ModelRegistry] 覆盖已存在的Provider: "
                    f"provider_type={provider_type}, model_type={model_type}, "
                    f"old_class={existing.provider_class.__name__}, "
                    f"new_class={provider_class.__name__}"
                )

            # 创建ProviderInfo并注册
            provider_info = ProviderInfo(
                provider_type=provider_type,
                model_type=model_type,
                provider_class=provider_class,
                description=description,
                version=version
            )

            self._registry[model_type][provider_type] = provider_info

            logger.info(
                f"[ModelRegistry] Provider注册成功: "
                f"provider_type={provider_type}, model_type={model_type}, "
                f"class={provider_class.__name__}, version={version}"
            )

    async def unregister(self, provider_type: str, model_type: ModelType) -> bool:
        """
        注销Provider

        Args:
            provider_type: Provider类型
            model_type: 模型类型

        Returns:
            bool: 是否成功注销
        """
        async with self._lock:
            if model_type in self._registry and provider_type in self._registry[model_type]:
                del self._registry[model_type][provider_type]
                logger.info(
                    f"[ModelRegistry] Provider注销成功: "
                    f"provider_type={provider_type}, model_type={model_type}"
                )
                return True

            logger.warning(
                f"[ModelRegistry] 注销失败，Provider不存在: "
                f"provider_type={provider_type}, model_type={model_type}"
            )
            return False

    def get_provider_class(
        self,
        provider_type: str,
        model_type: ModelType
    ) -> type[BaseModelProvider]:
        """
        获取Provider类

        Args:
            provider_type: Provider类型
            model_type: 模型类型

        Returns:
            Type[BaseModelProvider]: Provider类

        Raises:
            ProviderNotFoundException: Provider不存在时抛出
        """
        if model_type not in self._registry:
            error_msg = f"ModelType '{model_type}' 下没有注册的Provider"
            logger.error(f"[ModelRegistry] {error_msg}")
            raise ProviderNotFoundException(provider_type, str(model_type), error_msg)

        if provider_type not in self._registry[model_type]:
            available = list(self._registry[model_type].keys())
            error_msg = f"Provider '{provider_type}' 未注册，可用Provider: {available}"
            logger.error(f"[ModelRegistry] {error_msg}")
            raise ProviderNotFoundException(
                provider_type,
                str(model_type),
                f"Provider '{provider_type}' 未注册，可用Provider: {available}"
            )

        return self._registry[model_type][provider_type].provider_class

    def get_provider_info(self, provider_type: str, model_type: ModelType) -> ProviderInfo:
        """
        获取Provider详细信息

        Args:
            provider_type: Provider类型
            model_type: 模型类型

        Returns:
            ProviderInfo: Provider信息

        Raises:
            ProviderNotFoundException: Provider不存在时抛出
        """
        if model_type not in self._registry:
            error_msg = f"ModelType '{model_type}' 下没有注册的Provider"
            logger.error(f"[ModelRegistry] {error_msg}")
            raise ProviderNotFoundException(provider_type, str(model_type), error_msg)

        if provider_type not in self._registry[model_type]:
            available = list(self._registry[model_type].keys())
            error_msg = f"Provider '{provider_type}' 未注册，可用Provider: {available}"
            logger.error(f"[ModelRegistry] {error_msg}")
            raise ProviderNotFoundException(
                provider_type,
                str(model_type),
                error_msg
            )

        return self._registry[model_type][provider_type]

    def list_providers(self, model_type: ModelType | None = None) -> list[str]:
        """
        列出所有已注册的Provider

        Args:
            model_type: 可选，如果指定则只返回该类型的Provider

        Returns:
            List[str]: Provider类型列表
        """
        providers = []

        if model_type is not None:
            if model_type in self._registry:
                providers = list(self._registry[model_type].keys())
        else:
            for mt in self._registry.values():
                providers.extend(mt.keys())

        return providers

    def list_by_model_type(self, model_type: ModelType) -> dict[str, ProviderInfo]:
        """
        获取指定ModelType下的所有Provider

        Args:
            model_type: 模型类型

        Returns:
            Dict[str, ProviderInfo]: Provider信息字典
        """
        return self._registry.get(model_type, {}).copy()

    def get_all_providers(self) -> dict[ModelType, list[str]]:
        """
        获取所有注册的Provider

        Returns:
            Dict[ModelType, List[str]]: 按ModelType分组的Provider列表
        """
        return {
            mt: list(providers.keys())
            for mt, providers in self._registry.items()
        }

    def is_registered(self, provider_type: str, model_type: ModelType) -> bool:
        """
        检查Provider是否已注册

        Args:
            provider_type: Provider类型
            model_type: 模型类型

        Returns:
            bool: 是否已注册
        """
        return (
            model_type in self._registry and
            provider_type in self._registry[model_type]
        )

    def clear(self) -> None:
        """清空所有注册"""
        self._registry.clear()
        logger.info("[ModelRegistry] 注册表已清空")

    def get_stats(self) -> dict[str, Any]:
        """
        获取注册统计信息

        Returns:
            Dict: 统计信息
        """
        total_providers = sum(len(p) for p in self._registry.values())

        return {
            "total_providers": total_providers,
            "model_types": {mt.name: len(p) for mt, p in self._registry.items()},
            "initialized_at": self._initialized_at,
            "uptime_seconds": time.time() - self._initialized_at
        }
