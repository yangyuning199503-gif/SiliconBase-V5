"""
ModelBus总线模块

提供统一的模型调用入口，支持多Provider热切换
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .base import BaseModelProvider, ModelConfig, ModelType
from .exceptions import (
    InvokeException,
    ProviderUnavailableException,
    SlotNotFoundException,
)
from .registry import ModelRegistry
from .types import HealthStatus, InvokeMetrics, ModelResponse, ResponseStatus
from .validator import ConfigValidator, InputValidator

logger = logging.getLogger(__name__)


@dataclass
class ModelSlot:
    """模型槽位"""
    slot_id: str
    model_type: ModelType
    provider: BaseModelProvider
    config: ModelConfig
    created_at: float = field(default_factory=time.time)
    last_used: float | None = None
    call_count: int = 0
    error_count: int = 0
    enabled: bool = True
    priority: int = 0
    fallback_slots: list[str] = field(default_factory=list)

    def record_call(self, success: bool = True):
        """记录调用"""
        self.last_used = time.time()
        self.call_count += 1
        if not success:
            self.error_count += 1

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "slot_id": self.slot_id,
            "model_type": self.model_type.name,
            "provider": self.config.provider,
            "model_name": self.config.model_name,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_rate": (
                (self.call_count - self.error_count) / self.call_count * 100
                if self.call_count > 0 else 100.0
            ),
            "enabled": self.enabled,
            "priority": self.priority
        }


class ModelBus:
    """
    ModelBus - 模型总线

    单例模式实现，提供统一的模型调用接口
    支持多Provider注册、槽位管理和热切换
    """

    _instance = None
    _lock = asyncio.Lock()
    _init_lock = asyncio.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    async def _initialize(self):
        """异步初始化"""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            self._slots: dict[str, ModelSlot] = {}
            self._registry = ModelRegistry()
            self._metrics: list[InvokeMetrics] = []
            self._max_metrics_size = 1000
            self._callbacks = {
                "pre_invoke": [],
                "post_invoke": [],
                "on_error": []
            }

            self._initialized = True
            self._initialized_at = time.time()

            logger.info("[ModelBus] 总线初始化完成")

    def _ensure_initialized(self):
        """确保已初始化"""
        if not self._initialized:
            error_msg = "ModelBus尚未初始化"
            logger.error(f"[ModelBus] {error_msg}")
            raise RuntimeError(error_msg)

    async def register_provider(
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
            provider_type: Provider类型标识
            model_type: 模型类型
            provider_class: Provider类
            description: Provider描述
            version: Provider版本
        """
        await self._initialize()
        await self._registry.register(
            provider_type=provider_type,
            model_type=model_type,
            provider_class=provider_class,
            description=description,
            version=version
        )

    async def create_slot(
        self,
        slot_id: str,
        model_type: ModelType,
        config: ModelConfig,
        enabled: bool = True,
        priority: int = 0,
        fallback_slots: list[str] | None = None
    ) -> ModelSlot:
        """
        创建模型槽位

        Args:
            slot_id: 槽位唯一标识
            model_type: 模型类型
            config: 模型配置
            enabled: 是否启用
            priority: 优先级
            fallback_slots: 回退槽位列表

        Returns:
            ModelSlot: 创建的槽位

        Raises:
            SlotNotFoundException: 槽位已存在时抛出
            ProviderNotFoundException: Provider未注册时抛出
            ProviderUnavailableException: Provider初始化失败时抛出
        """
        await self._initialize()

        # 验证槽位ID
        ConfigValidator.validate_slot_id(slot_id)

        # 检查槽位是否已存在
        if slot_id in self._slots:
            error_msg = f"槽位 '{slot_id}' 已存在"
            logger.error(f"[ModelBus] 创建槽位失败: {error_msg}")
            raise SlotNotFoundException(slot_id, error_msg)

        # 验证配置
        ConfigValidator.validate_model_config(config)

        # 获取Provider类
        provider_class = self._registry.get_provider_class(config.provider, model_type)

        # 实例化Provider
        try:
            provider = provider_class(config)
        except Exception as e:
            error_msg = f"Provider实例化失败: {type(e).__name__}: {e}"
            logger.error(f"[ModelBus] 创建槽位失败: slot_id={slot_id}, error={error_msg}")
            raise ProviderUnavailableException(
                config.provider,
                error_msg,
                slot_id
            ) from e

        # 初始化Provider
        try:
            initialized = await provider.initialize()
            if not initialized:
                error_msg = f"Provider初始化返回False: provider={config.provider}"
                logger.error(f"[ModelBus] 创建槽位失败: slot_id={slot_id}, error={error_msg}")
                raise ProviderUnavailableException(
                    config.provider,
                    "初始化失败",
                    slot_id
                )
        except Exception as e:
            error_msg = f"Provider初始化异常: {type(e).__name__}: {e}"
            logger.error(f"[ModelBus] 创建槽位失败: slot_id={slot_id}, error={error_msg}")
            raise ProviderUnavailableException(
                config.provider,
                error_msg,
                slot_id
            ) from e

        # 检查可用性
        try:
            available = await provider.is_available()
            if not available:
                error_msg = f"Provider不可用: provider={config.provider}"
                logger.warning(f"[ModelBus] 警告: slot_id={slot_id}, {error_msg}")
                # 不阻止创建，但记录警告
        except Exception as e:
            error_msg = f"Provider可用性检查异常: {type(e).__name__}: {e}"
            logger.warning(f"[ModelBus] 警告: slot_id={slot_id}, {error_msg}")

        # 创建槽位
        slot = ModelSlot(
            slot_id=slot_id,
            model_type=model_type,
            provider=provider,
            config=config,
            enabled=enabled,
            priority=priority,
            fallback_slots=fallback_slots or []
        )

        async with self._lock:
            self._slots[slot_id] = slot

        logger.info(
            f"[ModelBus] 槽位创建成功: "
            f"slot_id={slot_id}, model_type={model_type.name}, "
            f"provider={config.provider}, model={config.model_name}"
        )

        return slot

    async def invoke(
        self,
        slot_id: str,
        input_data: Any,
        timeout: int | None = None,
        **kwargs
    ) -> ModelResponse:
        """
        统一调用接口

        Args:
            slot_id: 槽位ID
            input_data: 输入数据
            timeout: 超时时间（秒）
            **kwargs: 额外参数

        Returns:
            ModelResponse: 模型响应

        Raises:
            SlotNotFoundException: 槽位不存在时抛出
            ProviderUnavailableException: Provider不可用时抛出
            InvokeException: 调用失败时抛出
        """
        await self._initialize()

        # 验证输入
        InputValidator.validate_invoke_input(input_data)

        # 获取槽位
        slot = self._slots.get(slot_id)
        if not slot:
            error_msg = f"槽位 '{slot_id}' 不存在"
            logger.error(f"[ModelBus] 调用失败: {error_msg}")
            raise SlotNotFoundException(slot_id, error_msg)

        if not slot.enabled:
            error_msg = f"槽位 '{slot_id}' 已禁用"
            logger.error(f"[ModelBus] 调用失败: {error_msg}")
            raise ProviderUnavailableException(
                slot.config.provider,
                error_msg,
                slot_id
            )

        # 执行调用
        start_time = time.time()
        metrics = InvokeMetrics(slot_id=slot_id, start_time=start_time)

        try:
            # 调用Provider
            result = await slot.provider.invoke(input_data, **kwargs)

            # 检查结果
            if result is None:
                error_msg = f"Provider返回None: provider={slot.config.provider}"
                logger.error(f"[ModelBus] 调用失败: slot_id={slot_id}, error={error_msg}")
                raise ProviderUnavailableException(
                    slot.config.provider,
                    "返回无效结果",
                    slot_id
                )

            # 构造响应
            latency_ms = (time.time() - start_time) * 1000

            response = ModelResponse(
                content=result,
                status=ResponseStatus.SUCCESS,
                model=slot.config.model_name,
                provider=slot.config.provider,
                latency_ms=latency_ms
            )

            # 更新统计
            slot.record_call(success=True)
            metrics.end_time = time.time()
            metrics.success = True

            logger.info(
                f"[ModelBus] 调用成功: "
                f"slot_id={slot_id}, provider={slot.config.provider}, "
                f"latency={latency_ms:.2f}ms"
            )

            return response

        except Exception as e:
            # 记录失败
            slot.record_call(success=False)
            metrics.end_time = time.time()
            metrics.success = False
            metrics.error_type = type(e).__name__

            # 如果是已知异常，直接抛出
            if isinstance(e, (SlotNotFoundException, ProviderUnavailableException)):
                raise

            # 包装为InvokeException
            error_msg = f"调用失败: {type(e).__name__}: {e}"
            logger.error(f"[ModelBus] 调用失败: slot_id={slot_id}, error={error_msg}")
            raise InvokeException(
                error_msg,
                slot_id=slot_id,
                provider=slot.config.provider,
                original_error=e
            ) from e
        finally:
            # 记录指标
            self._record_metrics(metrics)

    async def invoke_stream(
        self,
        slot_id: str,
        input_data: Any,
        timeout: int | None = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        流式调用接口

        Args:
            slot_id: 槽位ID
            input_data: 输入数据
            timeout: 超时时间
            **kwargs: 额外参数

        Yields:
            str: 流式输出片段
        """
        await self._initialize()

        # 验证输入
        InputValidator.validate_invoke_input(input_data)

        # 获取槽位
        slot = self._slots.get(slot_id)
        if not slot:
            error_msg = f"槽位 '{slot_id}' 不存在"
            logger.error(f"[ModelBus] 流式调用失败: {error_msg}")
            raise SlotNotFoundException(slot_id, error_msg)

        if not slot.enabled:
            error_msg = f"槽位 '{slot_id}' 已禁用"
            logger.error(f"[ModelBus] 流式调用失败: {error_msg}")
            raise ProviderUnavailableException(
                slot.config.provider,
                error_msg,
                slot_id
            )

        # 检查是否支持流式
        if not slot.provider.capabilities.streaming:
            error_msg = f"Provider不支持流式输出: provider={slot.config.provider}"
            logger.error(f"[ModelBus] 流式调用失败: slot_id={slot_id}, error={error_msg}")
            raise InvokeException(
                error_msg,
                slot_id=slot_id,
                provider=slot.config.provider
            )

        start_time = time.time()

        try:
            # 调用Provider
            result = await slot.provider.invoke(input_data, stream=True, **kwargs)

            if result is None:
                error_msg = "Provider返回None"
                logger.error(f"[ModelBus] 流式调用失败: slot_id={slot_id}, error={error_msg}")
                raise ProviderUnavailableException(
                    slot.config.provider,
                    "返回无效结果",
                    slot_id
                )

            # 返回异步迭代器
            if isinstance(result, AsyncIterator):
                slot.record_call(success=True)
                logger.info(f"[ModelBus] 流式调用开始: slot_id={slot_id}")
                async for chunk in result:
                    yield chunk

                latency_ms = (time.time() - start_time) * 1000
                logger.info(f"[ModelBus] 流式调用完成: slot_id={slot_id}, latency={latency_ms:.2f}ms")
            else:
                # 非流式结果，包装为单次yield
                slot.record_call(success=True)
                yield str(result)

        except Exception as e:
            slot.record_call(success=False)
            error_msg = f"流式调用失败: {type(e).__name__}: {e}"
            logger.error(f"[ModelBus] 流式调用失败: slot_id={slot_id}, error={error_msg}")
            raise InvokeException(
                error_msg,
                slot_id=slot_id,
                provider=slot.config.provider,
                original_error=e
            ) from e

    def get_slot(self, slot_id: str) -> ModelSlot | None:
        """
        获取槽位信息

        Args:
            slot_id: 槽位ID

        Returns:
            Optional[ModelSlot]: 槽位信息，不存在返回None
        """
        if not self._initialized:
            return None
        return self._slots.get(slot_id)

    def list_slots(
        self,
        model_type: ModelType | None = None,
        enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        """
        列出所有槽位

        Args:
            model_type: 可选，按模型类型过滤
            enabled_only: 只返回启用的槽位

        Returns:
            List[Dict[str, Any]]: 槽位信息列表
        """
        if not self._initialized:
            return []

        slots = []
        for slot in self._slots.values():
            if model_type and slot.model_type != model_type:
                continue
            if enabled_only and not slot.enabled:
                continue
            slots.append(slot.get_stats())

        # 按优先级排序
        slots.sort(key=lambda x: x.get("priority", 0), reverse=True)

        return slots

    async def switch_slot_provider(
        self,
        slot_id: str,
        new_config: ModelConfig,
        keep_fallback: bool = True
    ) -> ModelSlot:
        """
        热切换槽位的Provider

        Args:
            slot_id: 槽位ID
            new_config: 新配置
            keep_fallback: 是否保留回退设置

        Returns:
            ModelSlot: 更新后的槽位

        Raises:
            SlotNotFoundException: 槽位不存在时抛出
        """
        await self._initialize()

        # 获取旧槽位
        old_slot = self._slots.get(slot_id)
        if not old_slot:
            error_msg = f"槽位 '{slot_id}' 不存在，无法切换"
            logger.error(f"[ModelBus] 切换Provider失败: {error_msg}")
            raise SlotNotFoundException(slot_id, error_msg)

        # 清理旧Provider
        try:
            await old_slot.provider.cleanup()
            logger.info(f"[ModelBus] 旧Provider清理完成: slot_id={slot_id}")
        except Exception as e:
            logger.warning(
                f"[ModelBus] 旧Provider清理异常: "
                f"slot_id={slot_id}, error={type(e).__name__}: {e}"
            )

        # 获取fallback设置
        fallback_slots = old_slot.fallback_slots if keep_fallback else []
        priority = old_slot.priority
        enabled = old_slot.enabled

        # 删除旧槽位
        async with self._lock:
            del self._slots[slot_id]

        # 创建新槽位
        logger.info(
            f"[ModelBus] 开始切换Provider: "
            f"slot_id={slot_id}, old_provider={old_slot.config.provider}, "
            f"new_provider={new_config.provider}"
        )

        new_slot = await self.create_slot(
            slot_id=slot_id,
            model_type=old_slot.model_type,
            config=new_config,
            enabled=enabled,
            priority=priority,
            fallback_slots=fallback_slots
        )

        logger.info(
            f"[ModelBus] Provider切换成功: "
            f"slot_id={slot_id}, provider={new_config.provider}"
        )

        return new_slot

    async def remove_slot(self, slot_id: str, cleanup: bool = True) -> bool:
        """
        移除槽位

        Args:
            slot_id: 槽位ID
            cleanup: 是否清理Provider资源

        Returns:
            bool: 是否成功移除
        """
        await self._initialize()

        slot = self._slots.get(slot_id)
        if not slot:
            logger.warning(f"[ModelBus] 移除槽位失败: slot_id={slot_id} 不存在")
            return False

        if cleanup:
            try:
                await slot.provider.cleanup()
                logger.info(f"[ModelBus] Provider资源清理完成: slot_id={slot_id}")
            except Exception as e:
                logger.error(
                    f"[ModelBus] Provider资源清理异常: "
                    f"slot_id={slot_id}, error={type(e).__name__}: {e}"
                )

        async with self._lock:
            if slot_id in self._slots:
                del self._slots[slot_id]

        logger.info(f"[ModelBus] 槽位移除成功: slot_id={slot_id}")
        return True

    async def health_check(self, slot_id: str) -> HealthStatus:
        """
        槽位健康检查

        Args:
            slot_id: 槽位ID

        Returns:
            HealthStatus: 健康状态
        """
        await self._initialize()

        slot = self._slots.get(slot_id)
        if not slot:
            error_msg = f"槽位 '{slot_id}' 不存在"
            logger.error(f"[ModelBus] 健康检查失败: {error_msg}")
            raise SlotNotFoundException(slot_id, error_msg)

        start_time = time.time()

        try:
            result = await slot.provider.health_check()
            latency_ms = (time.time() - start_time) * 1000

            healthy = result.get("healthy", False)

            return HealthStatus(
                healthy=healthy,
                provider=slot.config.provider,
                model_type=slot.model_type.name,
                latency_ms=latency_ms,
                message=result.get("message", ""),
                details=result.get("details", {})
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            error_msg = f"健康检查异常: {type(e).__name__}: {e}"
            logger.error(f"[ModelBus] 健康检查失败: slot_id={slot_id}, error={error_msg}")

            return HealthStatus(
                healthy=False,
                provider=slot.config.provider,
                model_type=slot.model_type.name,
                latency_ms=latency_ms,
                message=error_msg
            )

    def _record_metrics(self, metrics: InvokeMetrics):
        """记录调用指标"""
        self._metrics.append(metrics)

        # 限制指标数量
        if len(self._metrics) > self._max_metrics_size:
            self._metrics = self._metrics[-self._max_metrics_size:]

    def get_metrics(self, slot_id: str | None = None) -> list[dict[str, Any]]:
        """
        获取调用指标

        Args:
            slot_id: 可选，按槽位过滤

        Returns:
            List[Dict]: 指标列表
        """
        if not self._initialized:
            return []

        metrics = self._metrics
        if slot_id:
            metrics = [m for m in metrics if m.slot_id == slot_id]

        return [
            {
                "slot_id": m.slot_id,
                "start_time": m.start_time,
                "end_time": m.end_time,
                "latency_ms": m.latency_ms,
                "success": m.success,
                "error_type": m.error_type
            }
            for m in metrics
        ]

    def get_stats(self) -> dict[str, Any]:
        """
        获取总线统计信息

        Returns:
            Dict: 统计信息
        """
        if not self._initialized:
            return {"status": "not_initialized"}

        return {
            "status": "initialized",
            "initialized_at": getattr(self, '_initialized_at', None),
            "slot_count": len(self._slots),
            "slots_by_type": self._count_slots_by_type(),
            "total_calls": sum(s.call_count for s in self._slots.values()),
            "total_errors": sum(s.error_count for s in self._slots.values()),
            "registry_stats": self._registry.get_stats()
        }

    def _count_slots_by_type(self) -> dict[str, int]:
        """按类型统计槽位数量"""
        counts = {}
        for slot in self._slots.values():
            type_name = slot.model_type.name
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts

    async def shutdown(self):
        """关闭总线，清理所有资源"""
        if not self._initialized:
            return

        logger.info("[ModelBus] 开始关闭总线...")

        # 清理所有槽位
        for slot_id in list(self._slots.keys()):
            try:
                await self.remove_slot(slot_id, cleanup=True)
            except Exception as e:
                logger.error(
                    f"[ModelBus] 清理槽位异常: "
                    f"slot_id={slot_id}, error={type(e).__name__}: {e}"
                )

        self._slots.clear()
        self._metrics.clear()

        logger.info("[ModelBus] 总线关闭完成")
