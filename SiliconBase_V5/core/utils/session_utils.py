#!/usr/bin/env python3
"""
Session Utilities - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Validate UUID format
- Generate session title from user instruction
- Utility functions for session management
"""

import uuid


def is_valid_uuid(val: str) -> bool:
    """
    Check if string is valid UUID format

    Args:
        val: String to check

    Returns:
        True if valid UUID, False otherwise
    """
    if not val:
        return False
    try:
        uuid.UUID(val)
        return True
    except (ValueError, TypeError):
        return False


def generate_session_title(user_instruction: str, max_length: int = 30) -> str:
    """
    Generate session title from user instruction

    Args:
        user_instruction: User instruction
        max_length: Maximum length

    Returns:
        Generated title
    """
    if not user_instruction:
        return "新对话"

    # Clean instruction
    title = user_instruction.strip()

    # Truncate to max_length
    if len(title) > max_length:
        title = title[:max_length] + "..."

    return title if title else "新对话"


__all__ = [
    'is_valid_uuid',
    'generate_session_title',
]
