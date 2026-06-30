#!/usr/bin/env python3
"""
Memory Formatter - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Format memories as subconscious stream (focus mode)
- Format memories as traditional list (daily mode)
- Support various memory types: experience, knowledge, chat, scene
"""

import json


def format_memories_as_subconscious(memories: list[dict], mode: str = "focus") -> str:
    """
    Format memories as subconscious/dream-like form

    Focus mode: Memories naturally emerge like dreams, non-list presentation
    Daily mode: Traditional list presentation

    Args:
        memories: List of memory dictionaries
        mode: Work mode (focus/daily)

    Returns:
        Formatted memory text
    """
    if not memories:
        return ""

    if mode == "daily":
        # Daily mode: traditional list
        return format_memories_as_list(memories)

    # Focus mode: subconscious/dream-like form
    subconscious_fragments = []

    for mem in memories:
        content = mem.get('content', '')
        scene = mem.get('scene', '')
        mem_type = mem.get('mem_type', 'general')

        # Ensure content is string type
        if not isinstance(content, str):
            try:
                # Try to convert to JSON string
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                # Fallback to str
                content = str(content)

        # Generate memory lines based on memory type
        if mem_type == 'experience':
            fragment = f"[经验] {content[:80]}..."
        elif mem_type == 'knowledge':
            fragment = f"[知识] {content[:80]}..."
        elif mem_type == 'chat':
            fragment = f"[对话] {content[:80]}..."
        elif scene:
            fragment = f"[{scene}] {content[:80]}..."
        else:
            fragment = f"[记忆] {content[:80]}..."

        subconscious_fragments.append(fragment)

    # Combine into memory stream
    if subconscious_fragments:
        return "【近期记忆】\n" + "\n".join(subconscious_fragments[:5])  # Max 5
    return ""


def format_memories_as_list(memories: list[dict]) -> str:
    """Traditional list-style memory formatting (daily mode)"""
    if not memories:
        return ""

    lines = ["【相关记忆】"]
    for i, mem in enumerate(memories[:5], 1):
        content = mem.get('content', '')
        mem_type = mem.get('mem_type', 'general')
        lines.append(f"{i}. [{mem_type}] {content[:80]}...")

    return "\n".join(lines)


__all__ = [
    'format_memories_as_subconscious',
    'format_memories_as_list',
]
