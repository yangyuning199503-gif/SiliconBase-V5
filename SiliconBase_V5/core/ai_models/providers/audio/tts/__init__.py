"""
TTS (文本转语音) Provider模块

支持的Provider:
- PiperTTSProvider: 本地轻量级TTS
- EdgeTTSProvider: 微软Edge在线TTS
- FishSpeechProvider: 高保真TTS，支持声音克隆
"""

from core.ai_models.providers.audio.tts.edge_tts_provider import EdgeTTSProvider
from core.ai_models.providers.audio.tts.fish_speech_provider import FishSpeechProvider
from core.ai_models.providers.audio.tts.piper_tts_provider import PiperTTSProvider

__all__ = [
    'PiperTTSProvider',
    'EdgeTTSProvider',
    'FishSpeechProvider',
]
