#!/usr/bin/env python3
"""
VoiceUtils - 语音播报辅助函数
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的 speak_ai_reply 实现。
"""


from core.agent.voice_strategy import VoiceAnnounceStrategy
from core.config import config
from core.utils.common import get_voice_for_tts, set_voice_for_tts
from core.utils.text_parser import extract_natural_language


def speak_ai_reply(text: str, voice_instance=None, max_length: int = 100) -> bool:
    """播报AI回复（清理并截断）

    Args:
        text: 要播报的文本
        voice_instance: 优先使用的 voice 实例
        max_length: 最大播报长度

    Returns:
        bool: 是否成功播报
    """
    voice = voice_instance

    if voice is None:
        voice = get_voice_for_tts()
        if voice is not None:
            print("[speak_ai_reply] [OK] 使用全局 _voice_for_tts")

    if voice is None:
        try:
            from core.dialog.dialogue_manager import dialogue_manager
            if dialogue_manager.voice is not None:
                voice = dialogue_manager.voice
                set_voice_for_tts(voice)
                print("[speak_ai_reply] [FIX] 从 dialogue_manager 恢复 voice")
        except Exception as e:
            print(f"[speak_ai_reply] [WARN] 无法从 dialogue_manager 恢复 voice: {e}")

    if voice is None:
        try:
            from core.global_state import get_voice_interface
            voice = get_voice_interface()
            if voice is not None:
                set_voice_for_tts(voice)
                print("[speak_ai_reply] [FIX] 从 global_state 恢复 voice")
        except Exception as e:
            print(f"[speak_ai_reply] [WARN] 无法从 global_state 恢复 voice: {e}")

    print(f"[speak_ai_reply] 被调用，text={text[:50] if text else 'None'}...")
    print(f"[speak_ai_reply] voice={'可用' if voice else '不可用'}")

    if voice and text:
        clean_text = extract_natural_language(text)
        print(f"[speak_ai_reply] 清理后文本: {clean_text}")
        if len(clean_text) > 100:
            clean_text = clean_text[:97] + "..."
        if len(clean_text) > 3:
            print(f"[speak_ai_reply] 调用语音播报: {clean_text}")
            try:
                if config.get("voice.announce.ai_output", True):
                    if VoiceAnnounceStrategy.should_announce_ai_output(clean_text):
                        voice.speak(clean_text, is_system=False, protected=False)
                        print(f"[speak_ai_reply] [AI输出播报] text={clean_text[:50]}...")
                    else:
                        print("[speak_ai_reply] [去重] 跳过重复AI输出播报")
                else:
                    voice.speak(clean_text, is_system=True)
                    print("[speak_ai_reply] [系统播报] AI输出播报已禁用")
            except Exception as e:
                print(f"[speak_ai_reply] [WARN] 配置检查失败，使用默认播报: {e}")
                voice.speak(clean_text, is_system=True)
        else:
            print("[speak_ai_reply] 文本太短，跳过播报")
    else:
        print(f"[speak_ai_reply] 跳过播报: voice={voice is not None}, text={'有' if text else '无'}")

    return bool(voice and text)
