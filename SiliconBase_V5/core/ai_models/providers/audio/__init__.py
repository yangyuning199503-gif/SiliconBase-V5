"""
音频Provider模块

提供音频相关的模型Provider实现，包括:
- ASR (自动语音识别): Vosk, Whisper等
- TTS (文本转语音): Piper, EdgeTTS, FishSpeech等
- Enhance (语音增强): MaskGCT等
"""

from core.ai_models.providers.audio.base_audio_provider import (
    BaseASRProvider,
    BaseAudioProvider,
    BaseEnhanceProvider,
    BaseTTSProvider,
)

__all__ = [
    'BaseAudioProvider',
    'BaseASRProvider',
    'BaseTTSProvider',
    'BaseEnhanceProvider',
]
