#!/usr/bin/env python3
"""
AI Model Bus 桥接模块

将 core.ai_models (新版 ModelBus) 接入主流程，复活所有新版 Provider。

设计原则：
1. 零侵入旧版工作流：旧版 core.providers 继续正常工作
2. 懒加载：模块导入时不执行任何异步操作
3. 单例托管：ModelBus 单例在此模块中统一管理
4. 兼容包装：提供同步包装函数供旧代码尝试使用新版

使用方法：
    from core.ai.ai_model_bridge import init_model_bus, get_model_bus
    bus = init_model_bus()          # 在主流程同步初始化阶段调用
    bus = get_model_bus()           # 获取已初始化的 ModelBus
"""

import asyncio
import logging
from typing import Any

# ============================================================================
# 导入新版 ModelBus 核心基础设施
# ============================================================================
from core.ai_models import (
    BaseModelProvider,
    ModelBus,
    ModelConfig,
    ModelRegistry,
    ModelType,
)

# Audio Providers
from core.ai_models.providers.audio.asr import (
    VoskASRProvider,
    WhisperASRProvider,
)
from core.ai_models.providers.audio.enhance import (
    MaskGCTEnhanceProvider,
)
from core.ai_models.providers.audio.tts import (
    EdgeTTSProvider,
    FishSpeechProvider,
    PiperTTSProvider,
)

# Embedding Providers
from core.ai_models.providers.embedding import (
    BaseEmbeddingProvider,
    OpenAIEmbeddingProvider,
    SentenceTransformerProvider,
)

# ============================================================================
# 导入新版 Provider（复活这些死文件）
# ============================================================================
# LLM Providers
from core.ai_models.providers.llm import (
    AnthropicLLMProvider,
    BaseLLMProvider,
    OllamaLLMProvider,
    OpenAICompatibleLLMProvider,
    OpenAILLMProvider,
)

# Multimodal Providers
from core.ai_models.providers.multimodal import (
    BaseMultimodalProvider,
    UITarsProvider,
)

# Vision Providers
from core.ai_models.providers.vision import (
    BaseVisionProvider,
    OllamaVisionProvider,
)
from core.exceptions import AIResponseError, ModelBusError

logger = logging.getLogger(__name__)

# ============================================================================
# 全局 ModelBus 实例引用
# ============================================================================
_model_bus: ModelBus | None = None


# ============================================================================
# Provider 注册表：定义所有要注册到 ModelBus 的 Provider
# ============================================================================
_PROVIDER_REGISTRY: list[dict[str, Any]] = [
    # LLM
    {"provider_type": "ollama", "model_type": ModelType.LLM, "provider_class": OllamaLLMProvider, "description": "Ollama本地LLM服务", "version": "1.0.0"},
    {"provider_type": "openai", "model_type": ModelType.LLM, "provider_class": OpenAILLMProvider, "description": "OpenAI官方API", "version": "1.0.0"},
    {"provider_type": "anthropic", "model_type": ModelType.LLM, "provider_class": AnthropicLLMProvider, "description": "Anthropic Claude API", "version": "1.0.0"},
    {"provider_type": "openai_compatible", "model_type": ModelType.LLM, "provider_class": OpenAICompatibleLLMProvider, "description": "OpenAI兼容API", "version": "1.0.0"},

    # Vision
    {"provider_type": "ollama_vision", "model_type": ModelType.VISION, "provider_class": OllamaVisionProvider, "description": "Ollama视觉模型", "version": "1.0.0"},

    # Audio - ASR
    {"provider_type": "vosk_asr", "model_type": ModelType.AUDIO_ASR, "provider_class": VoskASRProvider, "description": "Vosk语音识别", "version": "1.0.0"},
    {"provider_type": "whisper_asr", "model_type": ModelType.AUDIO_ASR, "provider_class": WhisperASRProvider, "description": "Whisper语音识别", "version": "1.0.0"},

    # Audio - TTS
    {"provider_type": "edge_tts", "model_type": ModelType.AUDIO_TTS, "provider_class": EdgeTTSProvider, "description": "Edge TTS语音合成", "version": "1.0.0"},
    {"provider_type": "fish_speech", "model_type": ModelType.AUDIO_TTS, "provider_class": FishSpeechProvider, "description": "Fish Speech语音合成", "version": "1.0.0"},
    {"provider_type": "piper_tts", "model_type": ModelType.AUDIO_TTS, "provider_class": PiperTTSProvider, "description": "Piper TTS语音合成", "version": "1.0.0"},

    # Audio - Enhance
    {"provider_type": "maskgct", "model_type": ModelType.AUDIO_ENHANCE, "provider_class": MaskGCTEnhanceProvider, "description": "MaskGCT语音增强", "version": "1.0.0"},

    # Embedding
    {"provider_type": "openai_embedding", "model_type": ModelType.EMBEDDING, "provider_class": OpenAIEmbeddingProvider, "description": "OpenAI Embedding", "version": "1.0.0"},
    {"provider_type": "sentence_transformer", "model_type": ModelType.EMBEDDING, "provider_class": SentenceTransformerProvider, "description": "Sentence Transformer Embedding", "version": "1.0.0"},

    # Multimodal
    {"provider_type": "ui_tars", "model_type": ModelType.MULTIMODAL, "provider_class": UITarsProvider, "description": "UI-TARS多模态模型", "version": "1.0.0"},
]


async def _init_model_bus_async() -> ModelBus:
    """
    异步初始化 ModelBus 并注册所有 Provider

    Returns:
        ModelBus: 初始化完成的 ModelBus 单例
    """
    global _model_bus

    if _model_bus is not None:
        logger.info("[AIModelBridge] ModelBus 已初始化，跳过重复初始化")
        return _model_bus

    bus = ModelBus()

    # 先触发内部初始化（_initialize 会在第一次 async 操作中自动调用，
    # 但显式调用可确保在注册前完成）
    # ModelBus.__new__ 已创建单例，但 _initialize 是 async 的，
    # 实际上 register_provider 内部会调用 _initialize，所以无需手动调用。

    registered_count = 0
    failed_providers = []

    for p in _PROVIDER_REGISTRY:
        try:
            await bus.register_provider(
                provider_type=p["provider_type"],
                model_type=p["model_type"],
                provider_class=p["provider_class"],
                description=p["description"],
                version=p["version"],
            )
            registered_count += 1
            logger.info(
                f"[AIModelBridge] Provider 注册成功: {p['provider_type']} / {p['model_type'].name}"
            )
        except Exception as e:
            # 单个 Provider 注册失败不应阻断整个初始化流程
            failed_providers.append((p["provider_type"], str(e)))
            logger.warning(
                f"[AIModelBridge] Provider 注册失败: {p['provider_type']} - {e}"
            )

    _model_bus = bus

    stats = bus.get_stats()
    logger.info(
        f"[AIModelBridge] ModelBus 初始化完成: "
        f"registered={registered_count}, failed={len(failed_providers)}, stats={stats}"
    )

    if failed_providers:
        logger.warning(f"[AIModelBridge] 以下 Provider 注册失败: {failed_providers}")

    return bus


async def init_model_bus() -> ModelBus:
    """
    异步入口：初始化新版 ModelBus

    在异步上下文中调用。直接使用 await 完成异步初始化。

    Returns:
        ModelBus: 初始化成功的 ModelBus 实例

    Raises:
        ModelBusError: 初始化失败时抛出，绝不静默返回 None
    """
    global _model_bus
    if _model_bus is not None:
        return _model_bus

    try:
        _model_bus = await _init_model_bus_async()
        return _model_bus
    except ModelBusError:
        raise
    except Exception as e:
        logger.error(f"[AIModelBridge] ModelBus 初始化失败: {e}", exc_info=True)
        raise ModelBusError(f"ModelBus 初始化失败: {e}") from e


async def init_model_bus_async() -> ModelBus:
    """
    异步入口：初始化新版 ModelBus

    在异步上下文中调用（如 FastAPI lifespan、async def 中）。

    Returns:
        ModelBus: 初始化成功的 ModelBus 实例

    Raises:
        ModelBusError: 初始化失败时抛出，绝不静默返回 None
    """
    try:
        return await _init_model_bus_async()
    except ModelBusError:
        raise
    except Exception as e:
        logger.error(f"[AIModelBridge] ModelBus 异步初始化失败: {e}", exc_info=True)
        raise ModelBusError(f"ModelBus 异步初始化失败: {e}") from e


def get_model_bus() -> ModelBus | None:
    """
    获取已初始化的 ModelBus 实例

    Returns:
        Optional[ModelBus]: ModelBus 实例，如果未初始化则返回 None
    """
    return _model_bus


def is_model_bus_ready() -> bool:
    """
    检查 ModelBus 是否已完成初始化

    Returns:
        bool: 是否就绪
    """
    bus = get_model_bus()
    if bus is None:
        return False
    return getattr(bus, '_initialized', False)


# ============================================================================
# 旧版兼容包装函数
# ============================================================================

def call_model_bus_sync(
    slot_id: str,
    input_data: Any,
    timeout: int | None = None,
    **kwargs
) -> str:
    """
    通过 ModelBus 调用模型的同步包装函数

    用于旧代码在同步上下文中尝试使用新版架构。

    Args:
        slot_id: 模型槽位ID
        input_data: 输入数据（字符串/字典/消息列表）
        timeout: 超时时间（秒）
        **kwargs: 额外参数

    Returns:
        str: 模型输出文本

    Raises:
        ModelBusError: ModelBus 未初始化或调用失败
        AIResponseError: 模型返回空或无效响应
    """
    bus = get_model_bus()
    if bus is None:
        msg = "[AIModelBridge] ModelBus 未初始化，无法调用"
        logger.error(msg)
        raise ModelBusError(msg)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            msg = (
                "[AIModelBridge] 事件循环运行中，无法同步调用 ModelBus。"
                "请使用异步接口 bus.invoke()"
            )
            logger.error(msg)
            raise ModelBusError(msg)

        response = loop.run_until_complete(
            bus.invoke(slot_id, input_data, timeout=timeout, **kwargs)
        )

        if response and response.is_success():
            content = response.content
            if isinstance(content, str):
                return content
            else:
                return str(content)

        msg = f"[AIModelBridge] ModelBus 调用未成功: {response}"
        logger.error(msg)
        raise AIResponseError(msg)

    except (ModelBusError, AIResponseError):
        raise
    except Exception as e:
        logger.error(f"[AIModelBridge] ModelBus 同步调用失败: {e}", exc_info=True)
        raise ModelBusError(f"ModelBus 同步调用失败: {e}") from e


def get_model_bus_stats() -> dict[str, Any]:
    """
    获取 ModelBus 统计信息（同步安全）

    Returns:
        Dict: 统计信息字典

    Raises:
        ModelBusError: ModelBus 未初始化或获取统计信息失败
    """
    bus = get_model_bus()
    if bus is None:
        msg = "[AIModelBridge] ModelBus 未初始化，无法获取统计信息"
        logger.error(msg)
        raise ModelBusError(msg)

    try:
        return bus.get_stats()
    except ModelBusError:
        raise
    except Exception as e:
        logger.error(f"[AIModelBridge] 获取统计信息失败: {e}")
        raise ModelBusError(f"获取统计信息失败: {e}") from e


def list_registered_providers() -> list[dict[str, Any]]:
    """
    列出所有已注册的 Provider 类型

    Returns:
        List[Dict]: Provider 信息列表

    Raises:
        ModelBusError: ModelBus 未初始化或列出失败
    """
    bus = get_model_bus()
    if bus is None:
        msg = "[AIModelBridge] ModelBus 未初始化，无法列出 Provider"
        logger.error(msg)
        raise ModelBusError(msg)

    try:
        registry = bus._registry
        result = []
        for model_type, providers in registry.get_all_providers().items():
            for provider_type in providers:
                info = registry.get_provider_info(provider_type, model_type)
                result.append({
                    "provider_type": provider_type,
                    "model_type": model_type.name,
                    "description": info.description,
                    "version": info.version,
                })
        return result
    except ModelBusError:
        raise
    except Exception as e:
        logger.error(f"[AIModelBridge] 列出 Provider 失败: {e}")
        raise ModelBusError(f"列出 Provider 失败: {e}") from e


# ============================================================================
# 导出列表
# ============================================================================
__all__ = [
    # 初始化函数
    "init_model_bus",
    "init_model_bus_async",
    "get_model_bus",
    "is_model_bus_ready",

    # 兼容调用函数
    "call_model_bus_sync",
    "get_model_bus_stats",
    "list_registered_providers",

    # 核心类（方便统一导入）
    "ModelBus",
    "ModelRegistry",
    "ModelType",
    "ModelConfig",
    "BaseModelProvider",

    # LLM Providers
    "BaseLLMProvider",
    "OllamaLLMProvider",
    "OpenAILLMProvider",
    "AnthropicLLMProvider",
    "OpenAICompatibleLLMProvider",

    # Vision Providers
    "BaseVisionProvider",
    "OllamaVisionProvider",

    # Audio Providers
    "VoskASRProvider",
    "WhisperASRProvider",
    "EdgeTTSProvider",
    "FishSpeechProvider",
    "PiperTTSProvider",
    "MaskGCTEnhanceProvider",

    # Embedding Providers
    "BaseEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "SentenceTransformerProvider",

    # Multimodal Providers
    "BaseMultimodalProvider",
    "UITarsProvider",
]
