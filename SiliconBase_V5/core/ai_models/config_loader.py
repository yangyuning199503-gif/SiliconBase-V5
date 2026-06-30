"""
统一配置加载器
支持从旧配置迁移到新配置
"""
import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ModelBusConfigLoader:
    """ModelBus配置加载器"""

    def __init__(self, config_path: str = "config/models.yaml"):
        self.config_path = config_path
        self._config = None

    def load(self) -> dict[str, Any]:
        """加载配置"""
        # 1. 尝试加载新的统一配置
        if os.path.exists(self.config_path):
            logger.info(f"[ConfigLoader] 加载统一配置: {self.config_path}")
            with open(self.config_path, encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            return self._config

        # 2. 如果不存在，从旧配置迁移
        logger.info("[ConfigLoader] 统一配置不存在，从旧配置迁移")
        self._config = self._migrate_from_legacy()
        return self._config

    def _migrate_from_legacy(self) -> dict[str, Any]:
        """从旧配置迁移到新配置格式"""
        from core.config import config

        new_config = {
            "model_bus": {
                "version": "2.0",
                "global": {
                    "default_timeout": 120,
                    "max_retries": 2,
                    "fallback_enabled": True
                },
                "slots": {}
            }
        }

        slots = new_config["model_bus"]["slots"]

        # 迁移LLM配置 (ai.provider → chat.primary)
        ai_provider = config.get("ai.provider", "ollama")
        ai_model = config.get("ai.default_model", "qwen3:8b")
        ai_base_url = config.get(f"ai.{ai_provider}.base_url", "")

        slots["chat"] = {
            "primary": {
                "enabled": True,
                "type": "llm",
                "provider": ai_provider,
                "model": ai_model,
                "base_url": ai_base_url,
                "timeout": 120
            }
        }

        # 迁移视觉配置 (ai.vision.* → vision.main)
        vision_model = config.get("ai.vision.model") or config.get("ai.vision_model")
        if vision_model:
            slots["vision"] = {
                "main": {
                    "enabled": True,
                    "type": "vision",
                    "provider": "ollama",
                    "model": vision_model,
                    "capabilities": ["description", "qa", "ocr"]
                }
            }

        # 迁移语音配置 (voice.* → voice.*)
        voice_enabled = config.get("voice.enabled", False)
        if voice_enabled:
            slots["voice"] = {}

            # ASR
            vosk_model = config.get("voice.model_path", "assets/models/vosk-model-cn-0.22")
            slots["voice"]["recognition"] = {
                "enabled": True,
                "type": "audio_asr",
                "provider": "vosk",
                "model": vosk_model
            }

            # TTS
            tts_engine = config.get("voice.tts_engine", "piper")
            piper_model = config.get("voice.piper.model_path", "assets/models/piper/zh_CN-huayan-medium.onnx")
            slots["voice"]["synthesis"] = {
                "enabled": True,
                "type": "audio_tts",
                "provider": tts_engine,
                "model": piper_model
            }

        # 迁移向量配置 (local_models.embedding.* → memory.embedding)
        embedding_model = config.get("local_models.embedding.model_name", "all-MiniLM-L6-v2")
        embedding_device = config.get("local_models.embedding.device", "cpu")
        slots["memory"] = {
            "embedding": {
                "enabled": True,
                "type": "embedding",
                "provider": "sentence_transformers",
                "model": embedding_model,
                "device": embedding_device
            }
        }

        logger.info("[ConfigLoader] 配置迁移完成")
        return new_config

    def get_slot_config(self, slot_path: str) -> dict | None:
        """
        获取槽位配置

        Args:
            slot_path: 槽位路径，如 "chat.primary", "voice.synthesis"
        """
        if not self._config:
            self.load()

        parts = slot_path.split('.')
        current = self._config.get("model_bus", {}).get("slots", {})

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def save(self, config: dict[str, Any]):
        """保存配置到文件"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"[ConfigLoader] 配置已保存: {self.config_path}")
