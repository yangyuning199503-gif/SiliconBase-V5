#!/usr/bin/env python3
"""
Common Utilities - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Task ID generation
- User ID retrieval
- Critical step detection for checkpointing
- Voice TTS global instance management
"""

import threading
import uuid
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# Voice TTS Global Instance Management
# =============================================================================

_voice_for_tts: Any | None = None
"""Global voice instance reference for TTS (thread-safe)"""

_voice_for_tts_lock = threading.Lock()
"""Lock protecting _voice_for_tts access"""


def set_voice_for_tts(voice: Any) -> None:
    """
    Set global voice instance for TTS (thread-safe)

    Args:
        voice: Voice instance to set
    """
    global _voice_for_tts
    with _voice_for_tts_lock:
        _voice_for_tts = voice


def get_voice_for_tts() -> Any | None:
    """
    Get global voice instance for TTS (thread-safe)

    Returns:
        Voice instance or None
    """
    with _voice_for_tts_lock:
        return _voice_for_tts


# =============================================================================
# Task & Session Utilities
# =============================================================================

def generate_task_id() -> str:
    """
    Generate a unique task ID

    Returns:
        str: Task ID in format "task_{uuid}"
    """
    return f"task_{uuid.uuid4().hex[:8]}"


def get_current_user_id() -> str:
    """
    Get current user ID from global context

    Returns:
        str: User ID, defaults to "default"
    """
    try:
        from core.global_state import get_current_user_id as get_user
        return get_user()
    except Exception as e:
        logger.error(f"[CommonUtils] Failed to get user ID: {e}", exc_info=True)
        return "default"


# Critical tools that should trigger checkpoint saving
CRITICAL_TOOLS = [
    "web_search",      # Web search - important information retrieval
    "screenshot",      # Screenshot - record interface state
    "file_manager",    # File manager - file operations
    "memory_search",   # Memory search - retrieve important info
    "memory_add",      # Memory add - record key information
    "window_ocr",      # OCR - get interface text
    "pixel_capture",   # Pixel capture - screenshot related
    "launch_app",      # Launch app - important operation
    "type_text",       # Type text - data entry
    "mouse_click",     # Mouse click - UI interaction
]


def is_critical_step(tool_name: str, critical_tools: list[str] = None) -> bool:
    """
    Check if a tool execution is a critical step (should save checkpoint)

    Critical steps are tool calls that significantly impact task progress.
    Saving checkpoints after these steps reduces duplicate work on recovery.

    Args:
        tool_name: Name of the tool
        critical_tools: Optional custom list of critical tool names

    Returns:
        bool: True if this is a critical step
    """
    tools = critical_tools or CRITICAL_TOOLS
    return tool_name in tools


__all__ = [
    'generate_task_id',
    'get_current_user_id',
    'is_critical_step',
    'CRITICAL_TOOLS',
    'set_voice_for_tts',
    'get_voice_for_tts',
]
