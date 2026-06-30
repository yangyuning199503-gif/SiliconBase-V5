#!/usr/bin/env python3
"""
Text Parser Utilities - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Extract natural language from AI responses
- Extract thinking process from responses
- Extract tool calls from responses
- Check if action is required
"""

import json
import re
from typing import Any

from core.logger import logger


def extract_natural_language(response: str) -> str:
    """
    Extract natural language from response (aggressive cleanup)

    Args:
        response: AI response text

    Returns:
        Cleaned natural language text
    """
    if not response:
        return ""

    original = response  # noqa: F841  # Keep for debugging

    # Priority 1: Extract reply_to_user field
    try:
        json_match = re.search(r'\{[\s\S]*?"reply_to_user"\s*:\s*"([^"]+)"[\s\S]*?\}', response)
        if json_match:
            reply = json_match.group(1)
            if reply:
                return reply
    except Exception as e:
        logger.error(f"[TextParser] Failed to extract reply_to_user: {e}", exc_info=True)

    # Priority 2: Handle action: final_answer + content format
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, dict):
                if data.get('action') == 'final_answer' and 'content' in data:
                    content = data['content']
                    if content and isinstance(content, str):
                        return content
                if 'content' in data and data['content']:
                    content = data['content']
                    if isinstance(content, str):
                        return content
    except Exception as e:
        logger.debug(f"[TextParser] Failed to extract content: {e}")

    # Handle emoji format (thinking/plan/action)
    thinking_match = re.search(r'💭\s*思考[：:]\s*([^\n📝⚡]+)', response)
    if thinking_match:
        thinking = thinking_match.group(1).strip()
        if thinking and len(thinking) > 5:
            return thinking

    plan_match = re.search(r'📝\s*计划[：:]\s*([^\n⚡]+)', response)
    if plan_match:
        plan = plan_match.group(1).strip()
        if plan and len(plan) > 5:
            plan_lines = [line.strip() for line in plan.split('\n') if line.strip()]
            if plan_lines:
                return "计划" + "，".join(plan_lines[:3])

    # Aggressive cleanup
    cleaned = response
    cleaned = re.sub(r'```json\s*[\s\S]*?```', '', cleaned)
    cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
    cleaned = re.sub(r'\{[^{}]*"reply_to_user"[^{}]*\}', '', cleaned)

    for _ in range(5):
        new_cleaned = re.sub(r'\{[^{}]*\}', '', cleaned)
        if new_cleaned == cleaned:
            break
        cleaned = new_cleaned

    cleaned = re.sub(r'`[^`]+`', '', cleaned)
    cleaned = re.sub(r'!?\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    cleaned = re.sub(r'^\s*\d+\.\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'第[一二三四五六七八九十\d]+步[：:]?', '', cleaned)
    cleaned = re.sub(r'(调用|执行|使用)\s*\w+\s*(工具|函数|方法)', '正在操作', cleaned)
    cleaned = re.sub(r'\w+_\w+', '', cleaned)
    cleaned = re.sub(r'(status|success|error|code)\s*[=:]\s*\w+', '', cleaned, flags=re.IGNORECASE)

    cleaned = cleaned.strip()
    cleaned = ' '.join(cleaned.split())

    if len(cleaned) < 3:
        return "已完成"

    return cleaned


def extract_thinking_from_response(response: str) -> str | None:
    """
    Extract thinking process from AI response

    Args:
        response: AI response text

    Returns:
        Thinking content, or None if not found
    """
    if not response:
        return None

    thinking_patterns = [
        r'💭\s*思考[：:]\s*([^\n📝⚡]+)',
        r'【思考】\s*([^\n]+)',
        r'<thinking>(.+?)</thinking>',
        r'"thinking"\s*:\s*"([^"]+)"',
        # Claude / XML 格式变体
        r'<thinking>\s*([\s\S]+?)\s*</thinking>',
        r'```thinking\s*([\s\S]+?)```',
        r'\[思考\]\s*([\n\s\S]+?)(?=\n\[|\n📝|\n⚡|$)',
        r'Thinking:\s*([\n\s\S]+?)(?=\nAction:|\nObservation:|$)',
        r'<think>(.+?)</think>',
        r'"reasoning"\s*:\s*"([^"]+)"',
    ]

    for pattern in thinking_patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            thinking = match.group(1).strip()
            if thinking and len(thinking) > 5:
                return thinking

    return None


def extract_tool_calls_from_response(response: str) -> dict[str, Any] | None:
    """
    Extract tool_calls information from AI response

    Args:
        response: AI response text

    Returns:
        tool_calls dictionary, or None if not found
    """
    if not response:
        return None

    tool_calls = {"actions": []}

    # Match ```json ... ``` code block
    json_match = re.search(r'```json\s*([\s\S]*?)```', response)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict):
                if "action" in data:
                    tool_calls["actions"].append({
                        "action": data.get("action"),
                        "params": data.get("params", {}),
                        "tool": data.get("tool", data.get("action"))
                    })
                if "tool_calls" in data:
                    tool_calls["tool_calls"] = data["tool_calls"]
        except json.JSONDecodeError:
            pass

    # Match inline JSON
    inline_json_match = re.search(r'\{\s*"action"\s*:\s*"([^"]+)"', response)
    if inline_json_match and not tool_calls["actions"]:
        try:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1 and end > start:
                data = json.loads(response[start:end+1])
                if isinstance(data, dict) and "action" in data:
                    tool_calls["actions"].append({
                        "action": data.get("action"),
                        "params": data.get("params", {}),
                        "tool": data.get("tool", data.get("action"))
                    })
        except (json.JSONDecodeError, ValueError):
            pass

    return tool_calls if tool_calls["actions"] or "tool_calls" in tool_calls else None


def is_action_required(instruction: str) -> bool:
    """
    Check if user instruction requires specific action (not just conversation)

    Args:
        instruction: User instruction

    Returns:
        True = action required, False = pure conversation/query
    """
    if not instruction:
        return False

    instruction_lower = instruction.lower()

    # Action keywords
    action_keywords = [
        "打开", "关闭", "启动", "停止", "创建", "删除",
        "发送", "保存", "复制", "粘贴", "输入", "点击",
        "open", "close", "start", "stop", "create", "delete",
        "send", "save", "copy", "paste", "type", "click",
    ]

    # Conversation-only keywords
    conversation_keywords = [
        "你好", "谢谢", "再见", "请问", "告诉我", "什么是",
        "hello", "thanks", "bye", "what is", "how to", "explain",
    ]

    # Check if conversation-only
    for keyword in conversation_keywords:
        if keyword in instruction_lower:
            return False

    # Check if action required
    return any(keyword in instruction_lower for keyword in action_keywords)


__all__ = [
    'extract_natural_language',
    'extract_thinking_from_response',
    'extract_tool_calls_from_response',
    'is_action_required',
]
