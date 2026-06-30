"""utils module - SiliconBase V5

Contains utility modules for:
- text_parser: Text parsing utilities
- security: Security and sanitization
- session_utils: Session management utilities
- common: Common utilities (task IDs, user IDs, critical steps, voice TTS)
"""

# Re-export from submodules for convenience
__all__ = [
    "CRITICAL_TOOLS",
    "generate_task_id",
    "get_current_user_id",
    "get_voice_for_tts",
    "is_critical_step",
    "set_voice_for_tts",
    "escape_user_instruction",
    "sanitize_vision_description",
    "generate_session_title",
    "is_valid_uuid",
    "extract_natural_language",
    "extract_thinking_from_response",
    "extract_tool_calls_from_response",
]

from .common import (
    CRITICAL_TOOLS,
    generate_task_id,
    get_current_user_id,
    get_voice_for_tts,
    is_critical_step,
    set_voice_for_tts,
)
from .security import (
    escape_user_instruction,
    sanitize_vision_description,
)
from .session_utils import (
    generate_session_title,
    is_valid_uuid,
)
from .text_parser import (
    extract_natural_language,
    extract_thinking_from_response,
    extract_tool_calls_from_response,
)
