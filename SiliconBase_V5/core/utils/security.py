#!/usr/bin/env python3
"""
Security Utilities - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Escape user input to prevent injection attacks
- Sanitize vision descriptions
- Filter dangerous patterns
"""

import html
import re

from core.logger import logger


def escape_user_instruction(instruction: str, max_length: int = 500) -> str:
    """
    Escape user instruction to prevent injection into vision model

    Invalid return = explicit error + logging

    Args:
        instruction: User instruction string
        max_length: Maximum allowed length

    Returns:
        Escaped instruction string

    Raises:
        TypeError: If instruction is not a string
    """
    if not isinstance(instruction, str):
        error_msg = f"[SECURITY] User instruction type error: {type(instruction)}"
        logger.error(error_msg)
        raise TypeError(error_msg)

    # 1. Limit length
    if len(instruction) > max_length:
        logger.warning(f"[SECURITY] User instruction too long ({len(instruction)}), truncating to {max_length}")
        instruction = instruction[:max_length] + "...[截断]"

    # 2. Check dangerous character sequences
    DANGEROUS_SEQUENCES = [
        '"',
        "'",
        '\n',
        '\r',
        '\t',
        '/*',
        '*/',
        '<script',
        '</script>',
    ]

    for seq in DANGEROUS_SEQUENCES:
        if seq in instruction:
            logger.warning(f"[SECURITY] User instruction contains dangerous sequence '{seq}', removed")
            instruction = instruction.replace(seq, ' ')

    # 3. Simple escape (replace remaining quotes)
    instruction = instruction.replace('"', '\\"').replace("'", "\\'")

    return instruction


def sanitize_vision_description(desc: str, max_length: int = 2000) -> str:
    """
    Sanitize vision description to prevent prompt injection attacks

    Rules:
    1. Limit length to 2000 characters
    2. HTML escape special characters
    3. Filter dangerous keywords

    Args:
        desc: Vision description string
        max_length: Maximum allowed length

    Returns:
        Sanitized description string

    Raises:
        TypeError: If desc is not a string
    """
    if not isinstance(desc, str):
        error_msg = f"[SECURITY] Vision description type error: {type(desc)}, must be str"
        logger.error(error_msg)
        raise TypeError(error_msg)

    # 1. Limit length
    if len(desc) > max_length:
        logger.warning(f"[SECURITY] Vision description too long ({len(desc)}), truncating to {max_length}")
        desc = desc[:max_length] + "...[截断]"

    # 2. Filter dangerous keywords
    DANGEROUS_PATTERNS = [
        (r"忽略.*指令", "[FILTERED-忽略指令]"),
        (r"ignore.*previous", "[FILTERED]"),
        (r"system.*prompt", "[FILTERED-system]"),
        (r"你.*是.*现在", "[FILTERED-角色切换]"),
        (r"新.*角色", "[FILTERED-角色]"),
        (r" disregard ", "[FILTERED]"),
        (r" forget ", "[FILTERED]"),
    ]

    filtered_count = 0
    for pattern, replacement in DANGEROUS_PATTERNS:
        if re.search(pattern, desc, flags=re.IGNORECASE):
            desc = re.sub(pattern, replacement, desc, flags=re.IGNORECASE)
            filtered_count += 1
            logger.warning(f"[SECURITY] Filtered dangerous keyword: pattern={pattern}")

    # 3. HTML escape
    desc = html.escape(desc)

    if filtered_count > 0:
        logger.info(f"[SECURITY] Vision description sanitized, filtered {filtered_count} dangerous patterns")

    return desc


__all__ = [
    'escape_user_instruction',
    'sanitize_vision_description',
]
