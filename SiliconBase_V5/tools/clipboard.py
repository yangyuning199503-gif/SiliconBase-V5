#!/usr/bin/env python3
"""
剪贴板工具模块
包含三个工具类：
- Clipboard: 统一接口，支持 get/set/clear 操作
- ClipboardGet: 单一职责，仅支持获取剪贴板
- ClipboardSet: 单一职责，仅支持设置剪贴板

设计说明：
- Clipboard 是统一接口范式，适合需要动态选择操作的场景
- ClipboardGet/ClipboardSet 是单一职责范式，适合明确操作类型的场景
- 三者并存，满足不同使用需求，不存在废弃关系
"""
from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, format_error
from tools.clipboard_core import clear_clipboard, get_clipboard, set_clipboard


class Clipboard(BaseTool):
    """
    剪贴板操作工具（统一接口版）
    支持: get获取文本, set设置文本, clear清空
    适用场景：操作类型需要动态决定的场景
    """
    tool_id = "clipboard"
    name = "剪贴板操作"
    description = "获取、设置或清空系统剪贴板文本内容"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "clear"],
                "description": "操作类型：get获取, set设置, clear清空"
            },
            "text": {
                "type": "string",
                "description": "要设置的文本（set操作时需要）"
            }
        },
        "required": ["action"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        action = kwargs.get("action", "get")

        if action == "get":
            return get_clipboard()
        elif action == "set":
            text = kwargs.get("text")
            if text is None:
                return format_error(INVALID_PARAMS, detail="set操作需要text参数")
            return set_clipboard(text)
        elif action == "clear":
            return clear_clipboard()
        else:
            return format_error(INVALID_PARAMS, detail=f"未知操作: {action}")


class ClipboardGet(BaseTool):
    """
    获取剪贴板工具（单一职责版）
    仅支持获取剪贴板文本内容
    适用场景：明确只需要获取剪贴板的场景
    """
    tool_id = "clipboard_get"
    name = "获取剪贴板"
    description = "获取系统剪贴板文本内容"
    input_schema = {
        "type": "object",
        "properties": {},
        "description": "无需输入参数"
    }

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        return get_clipboard()


class ClipboardSet(BaseTool):
    """
    设置剪贴板工具（单一职责版）
    仅支持设置剪贴板文本内容
    适用场景：明确只需要设置剪贴板的场景
    """
    tool_id = "clipboard_set"
    name = "设置剪贴板"
    description = "设置系统剪贴板文本内容"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要设置到剪贴板的文本内容"
            }
        },
        "required": ["text"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        text = kwargs.get("text")
        if text is None:
            return format_error(INVALID_PARAMS, detail="需要提供text参数")
        return set_clipboard(text)
