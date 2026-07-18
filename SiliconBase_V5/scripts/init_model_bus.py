#!/usr/bin/env python3
"""
ModelBus初始化脚本
- 检查配置
- 注册所有Provider
- 初始化默认槽位
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.ai_models.base import ModelType
from core.ai_models.bus import ModelBus
from core.ai_models.config_loader import ModelBusConfigLoader
from core.ai_models.providers.audio.asr import VoskASRProvider, WhisperASRProvider
from core.ai_models.providers.audio.tts import EdgeTTSProvider, PiperTTSProvider
from core.ai_models.providers.embedding import SentenceTransformerProvider
from core.ai_models.providers.llm import OllamaLLMProvider, OpenAILLMProvider
from core.ai_models.providers.vision import OllamaVisionProvider


async def init_model_bus():
    """初始化ModelBus"""
    print("[Init] 初始化ModelBus...")

    bus = ModelBus()

    # 注册所有Provider
    print("[Init] 注册LLM Providers...")
    bus.register_provider("ollama", ModelType.LLM, OllamaLLMProvider)
    bus.register_provider("openai", ModelType.LLM, OpenAILLMProvider)

    print("[Init] 注册Vision Providers...")
    bus.register_provider("ollama", ModelType.VISION, OllamaVisionProvider)

    print("[Init] 注册ASR Providers...")
    bus.register_provider("vosk", ModelType.AUDIO_ASR, VoskASRProvider)
    bus.register_provider("whisper", ModelType.AUDIO_ASR, WhisperASRProvider)

    print("[Init] 注册TTS Providers...")
    bus.register_provider("piper", ModelType.AUDIO_TTS, PiperTTSProvider)
    bus.register_provider("edge_tts", ModelType.AUDIO_TTS, EdgeTTSProvider)

    print("[Init] 注册Embedding Providers...")
    bus.register_provider("sentence_transformers", ModelType.EMBEDDING, SentenceTransformerProvider)

    # 加载配置
    print("[Init] 加载配置...")
    loader = ModelBusConfigLoader()
    config = loader.load()

    # 初始化槽位
    print("[Init] 初始化槽位...")
    slots_config = config.get("model_bus", {}).get("slots", {})

    for slot_group, slots in slots_config.items():
        for slot_name, slot_config in slots.items():
            if not slot_config.get("enabled", False):
                continue

            slot_id = f"{slot_group}.{slot_name}"
            print(f"[Init] 创建槽位: {slot_id}")

            try:
                from core.ai_models.config import ModelConfig
                model_config = ModelConfig(
                    provider=slot_config["provider"],
                    model_name=slot_config["model"],
                    base_url=slot_config.get("base_url"),
                    api_key=slot_config.get("api_key"),
                    timeout=slot_config.get("timeout", 120),
                    extra_params={k: v for k, v in slot_config.items()
                                 if k not in ["provider", "model", "base_url", "api_key", "timeout", "enabled", "type"]}
                )

                model_type = ModelType[slot_config["type"].upper()]
                await bus.create_slot(slot_id, model_type, model_config)
                print(f"[Init] ✓ 槽位 {slot_id} 创建成功")

            except Exception as e:
                print(f"[Init] ✗ 槽位 {slot_id} 创建失败: {e}")

    print("[Init] ModelBus初始化完成")
    return bus


if __name__ == "__main__":
    asyncio.run(init_model_bus())
