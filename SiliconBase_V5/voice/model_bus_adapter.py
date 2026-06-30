"""
VoiceInterface与ModelBus的适配器

使现有代码可以逐步迁移到新的可插拔架构。
提供向后兼容性，同时支持新的ModelBus功能。

使用示例:
```python
from voice.model_bus_adapter import VoiceModelBusAdapter

adapter = VoiceModelBusAdapter()
await adapter.initialize({
    "asr": {"provider": "vosk", "model": "vosk-model-cn-0.22"},
    "tts": {"provider": "piper", "model": "zh_CN-huayan-medium.onnx"}
})

# ASR识别
text = await adapter.recognize(audio_data)

# TTS合成
audio = await adapter.synthesize("你好，世界")
```
"""

import contextlib
import logging
from typing import Any

from core.ai_models.bus import ModelBus
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ProviderNotFoundException, RecognitionException, SynthesisException
from core.ai_models.providers.audio.asr import VoskASRProvider, WhisperASRProvider
from core.ai_models.providers.audio.tts import EdgeTTSProvider, FishSpeechProvider, PiperTTSProvider
from core.ai_models.registry import ModelRegistry

logger = logging.getLogger(__name__)


class VoiceModelBusAdapter:
    """
    语音模型总线适配器

    提供统一的语音服务接口，支持:
    - ASR语音识别 (Vosk, Whisper)
    - TTS语音合成 (Piper, EdgeTTS, FishSpeech)
    - 语音增强 (预留接口)

    特点:
    - 向后兼容旧的VoiceInterface配置
    - 支持动态切换Provider
    - 统一的错误处理
    """

    # 默认槽位名称
    ASR_SLOT = "voice.asr"
    TTS_SLOT = "voice.tts"
    ENHANCE_SLOT = "voice.enhance"

    # Provider映射
    ASR_PROVIDERS = {
        "vosk": VoskASRProvider,
        "whisper": WhisperASRProvider,
    }

    TTS_PROVIDERS = {
        "piper": PiperTTSProvider,
        "edge": EdgeTTSProvider,
        "edgetts": EdgeTTSProvider,
        "fishspeech": FishSpeechProvider,
        "fish_speech": FishSpeechProvider,
    }

    def __init__(self):
        self.bus = ModelBus()
        self.registry = ModelRegistry()
        self._asr_slot = self.ASR_SLOT
        self._tts_slot = self.TTS_SLOT
        self._enhance_slot = self.ENHANCE_SLOT
        self._initialized = False

        # 注册Provider
        self._register_providers()

    def _register_providers(self):
        """注册所有音频Provider到注册表"""
        import asyncio

        from core.ai_models.base import ModelType

        # 注册ASR Provider
        for name, provider_class in self.ASR_PROVIDERS.items():
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.registry.register(
                provider_type=name,
                model_type=ModelType.AUDIO_ASR,
                provider_class=provider_class
            ))
            logger.debug(f"[VoiceAdapter] 注册ASR Provider: {name}")

        # 注册TTS Provider
        for name, provider_class in self.TTS_PROVIDERS.items():
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.registry.register(
                provider_type=name,
                model_type=ModelType.AUDIO_TTS,
                provider_class=provider_class
            ))
            logger.debug(f"[VoiceAdapter] 注册TTS Provider: {name}")

        logger.info(f"[VoiceAdapter] 已注册 {len(self.ASR_PROVIDERS)} 个ASR和 {len(self.TTS_PROVIDERS)} 个TTS Provider")

    async def initialize(self, config: dict[str, Any]) -> bool:
        """
        从配置初始化适配器

        支持旧配置格式:
        ```python
        config = {
            "voice.model_path": "assets/models/vosk-model-cn-0.22",
            "voice.piper.model_path": "assets/models/piper/zh_CN-huayan-medium.onnx",
            "voice.tts_engine": "piper"
        }
        ```

        也支持新配置格式:
        ```python
        config = {
            "asr": {
                "provider": "vosk",
                "model": "assets/models/vosk-model-cn-0.22"
            },
            "tts": {
                "provider": "piper",
                "model": "assets/models/piper/zh_CN-huayan-medium.onnx"
            }
        }
        ```

        Args:
            config: 配置字典

        Returns:
            bool: 初始化是否成功
        """
        try:
            logger.info("[VoiceAdapter] 初始化适配器...")

            # 解析ASR配置
            asr_config = self._parse_asr_config(config)
            if asr_config:
                await self._init_asr(asr_config)

            # 解析TTS配置
            tts_config = self._parse_tts_config(config)
            if tts_config:
                await self._init_tts(tts_config)

            self._initialized = True
            logger.info("[VoiceAdapter] 初始化完成")
            return True

        except Exception as e:
            logger.error(f"[VoiceAdapter] 初始化失败: {e}", exc_info=True)
            return False

    def _parse_asr_config(self, config: dict[str, Any]) -> dict | None:
        """解析ASR配置"""
        # 新格式
        if "asr" in config and isinstance(config["asr"], dict):
            return config["asr"]

        # 旧格式兼容
        asr_config = {}

        # 检测Provider类型
        if "voice.model_path" in config:
            asr_config["provider"] = "vosk"
            asr_config["model"] = config.get("voice.model_path")
        elif config.get("asr.provider"):
            asr_config["provider"] = config.get("asr.provider")
            asr_config["model"] = config.get("asr.model")

        return asr_config if asr_config.get("provider") else None

    def _parse_tts_config(self, config: dict[str, Any]) -> dict | None:
        """解析TTS配置"""
        # 新格式
        if "tts" in config and isinstance(config["tts"], dict):
            return config["tts"]

        # 旧格式兼容
        tts_config = {}

        # 检测TTS引擎类型
        tts_engine = config.get("voice.tts_engine", "piper")
        tts_config["provider"] = tts_engine

        if tts_engine == "piper":
            tts_config["model"] = config.get("voice.piper.model_path", "assets/models/piper/zh_CN-huayan-medium.onnx")
            tts_config["config_path"] = config.get("voice.piper.config_path")
        elif tts_engine in ("edge", "edgetts"):
            tts_config["voice"] = config.get("voice.edge.voice", "zh-CN-XiaoxiaoNeural")
        elif tts_engine in ("fishspeech", "fish_speech"):
            tts_config["model"] = config.get("voice.fishspeech.model")
            tts_config["base_url"] = config.get("voice.fishspeech.base_url")

        return tts_config if tts_config.get("provider") else None

    async def _init_asr(self, config: dict[str, Any]):
        """初始化ASR Provider"""
        provider_name = config.get("provider", "vosk")
        model_name = config.get("model", config.get("model_path"))

        logger.info(f"[VoiceAdapter] 初始化ASR: {provider_name}, 模型: {model_name}")

        # 创建配置
        model_config = ModelConfig(
            provider=provider_name,
            model_name=model_name,
            extra_params=config
        )

        # 创建Provider实例
        provider_class = self.ASR_PROVIDERS.get(provider_name)
        if not provider_class:
            raise ProviderNotFoundException(provider_name, "AUDIO_ASR")

        provider = provider_class(model_config)

        # 初始化Provider
        await provider.initialize()

        # 注册到ModelBus
        self.bus.register(self._asr_slot, provider)

        logger.info(f"[VoiceAdapter] ASR已初始化: {provider_name}")

    async def _init_tts(self, config: dict[str, Any]):
        """初始化TTS Provider"""
        provider_name = config.get("provider", "piper")
        model_name = config.get("model")

        logger.info(f"[VoiceAdapter] 初始化TTS: {provider_name}")

        # 创建配置
        extra_params = {k: v for k, v in config.items() if k not in ("provider", "model")}

        model_config = ModelConfig(
            provider=provider_name,
            model_name=model_name or f"{provider_name}-default",
            extra_params=extra_params
        )

        # 创建Provider实例
        provider_class = self.TTS_PROVIDERS.get(provider_name)
        if not provider_class:
            raise ProviderNotFoundException(provider_name, "AUDIO_TTS")

        provider = provider_class(model_config)

        # 初始化Provider
        await provider.initialize()

        # 注册到ModelBus
        self.bus.register(self._tts_slot, provider)

        logger.info(f"[VoiceAdapter] TTS已初始化: {provider_name}")

    async def recognize(self, audio_data: bytes, **kwargs) -> str:
        """
        ASR语音识别

        Args:
            audio_data: PCM音频数据 (16kHz, 16bit, mono)
            **kwargs: 额外参数
                - language: 语言代码
                - partial: 是否返回部分结果

        Returns:
            识别文本

        Raises:
            RecognitionException: 识别失败时抛出
        """
        if not self._initialized:
            raise RuntimeError("适配器未初始化")

        try:
            result = await self.bus.invoke(self._asr_slot, audio_data, **kwargs)
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            logger.error(f"[VoiceAdapter] ASR识别失败: {e}")
            raise RecognitionException(f"语音识别失败: {e}") from e

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        TTS语音合成

        Args:
            text: 要合成的文本
            **kwargs: 额外参数
                - speaker_id: 说话人ID
                - speed: 语速倍率
                - voice: 语音名称 (Edge TTS)

        Returns:
            WAV格式音频字节数据

        Raises:
            SynthesisException: 合成失败时抛出
        """
        if not self._initialized:
            raise RuntimeError("适配器未初始化")

        try:
            result = await self.bus.invoke(self._tts_slot, text, **kwargs)
            return result if isinstance(result, bytes) else b""
        except Exception as e:
            logger.error(f"[VoiceAdapter] TTS合成失败: {e}")
            raise SynthesisException(f"语音合成失败: {e}") from e

    async def switch_asr_provider(self, provider_name: str, config: dict[str, Any]) -> bool:
        """
        切换ASR Provider

        Args:
            provider_name: Provider名称 (vosk, whisper)
            config: Provider配置

        Returns:
            bool: 切换是否成功
        """
        try:
            # 注销旧Provider
            with contextlib.suppress(BaseException):
                self.bus.unregister(self._asr_slot)

            # 初始化新Provider
            config["provider"] = provider_name
            await self._init_asr(config)

            logger.info(f"[VoiceAdapter] ASR已切换到: {provider_name}")
            return True

        except Exception as e:
            logger.error(f"[VoiceAdapter] 切换ASR失败: {e}")
            return False

    async def switch_tts_provider(self, provider_name: str, config: dict[str, Any]) -> bool:
        """
        切换TTS Provider

        Args:
            provider_name: Provider名称 (piper, edge, fishspeech)
            config: Provider配置

        Returns:
            bool: 切换是否成功
        """
        try:
            # 注销旧Provider
            with contextlib.suppress(BaseException):
                self.bus.unregister(self._tts_slot)

            # 初始化新Provider
            config["provider"] = provider_name
            await self._init_tts(config)

            logger.info(f"[VoiceAdapter] TTS已切换到: {provider_name}")
            return True

        except Exception as e:
            logger.error(f"[VoiceAdapter] 切换TTS失败: {e}")
            return False

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        result = {
            "initialized": self._initialized,
            "asr": None,
            "tts": None
        }

        # 检查ASR
        try:
            asr_slot = self.bus.get_slot(self._asr_slot)
            if asr_slot and asr_slot.provider:
                result["asr"] = await asr_slot.provider.health_check()
        except Exception as e:
            result["asr"] = {"error": str(e)}

        # 检查TTS
        try:
            tts_slot = self.bus.get_slot(self._tts_slot)
            if tts_slot and tts_slot.provider:
                result["tts"] = await tts_slot.provider.health_check()
        except Exception as e:
            result["tts"] = {"error": str(e)}

        return result

    def get_available_providers(self) -> dict[str, list]:
        """
        获取可用的Provider列表

        Returns:
            包含ASR和TTS Provider名称的字典
        """
        return {
            "asr": list(self.ASR_PROVIDERS.keys()),
            "tts": list(self.TTS_PROVIDERS.keys())
        }

    async def cleanup(self):
        """清理资源"""
        logger.info("[VoiceAdapter] 清理资源...")
        await self.bus.clear()
        self._initialized = False

    async def reload_piper_model(self) -> bool:
        """
        重新加载Piper TTS模型（用于内存优化）

        Returns:
            bool: 是否成功
        """
        try:
            logger.info("[VoiceAdapter] 重新加载Piper TTS模型...")

            # 获取当前配置
            tts_slot = self.bus.get_slot(self._tts_slot)
            if not tts_slot or not tts_slot.provider:
                logger.warning("[VoiceAdapter] TTS Provider未初始化")
                return False

            # 切换Provider来重新加载
            current_provider = tts_slot.provider.config.provider if tts_slot.provider.config else "piper"

            # 重新初始化
            return await self.switch_tts_provider(current_provider, {})

        except Exception as e:
            logger.error(f"[VoiceAdapter] 重新加载Piper模型失败: {e}")
            return False

    def get_asr_provider(self) -> Any | None:
        """获取当前ASR Provider实例"""
        try:
            slot = self.bus.get_slot(self._asr_slot)
            return slot.provider if slot else None
        except Exception:
            return None

    def get_tts_provider(self) -> Any | None:
        """获取当前TTS Provider实例"""
        try:
            slot = self.bus.get_slot(self._tts_slot)
            return slot.provider if slot else None
        except Exception:
            return None


# 全局适配器实例
_voice_adapter: VoiceModelBusAdapter | None = None


def get_voice_adapter() -> VoiceModelBusAdapter:
    """
    获取全局Voice适配器实例（单例模式）

    Returns:
        VoiceModelBusAdapter实例
    """
    global _voice_adapter
    if _voice_adapter is None:
        _voice_adapter = VoiceModelBusAdapter()
    return _voice_adapter


async def init_voice_adapter(config: dict[str, Any]) -> bool:
    """
    初始化全局Voice适配器

    Args:
        config: 配置字典

    Returns:
        bool: 初始化是否成功
    """
    adapter = get_voice_adapter()
    return await adapter.initialize(config)
