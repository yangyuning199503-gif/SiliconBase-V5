#!/usr/bin/env python3
"""
原子工具：替换记忆（Hermes 风格策展接口）
删除旧记忆并添加新记忆，保持记忆总量可控。
"""
from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger


class MemoryReplace(BaseTool):
    tool_id = "memory_replace"
    name = "替换记忆"
    description = (
        "删除一条旧记忆并添加一条新记忆。"
        "当记忆空间接近上限时，用新经验替换过时的旧经验。"
        "先通过 memory_search 找到要替换的记忆ID，再调用此工具。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "要替换的旧记忆 ID，可通过 memory_search 查询获得"
            },
            "content": {
                "type": "string",
                "description": "新的记忆内容"
            },
            "layer": {
                "type": "string",
                "enum": ["short", "medium", "evolve"],
                "description": "新记忆的层级：short（短期）、medium（中期）、evolve（长期）"
            },
            "mem_type": {
                "type": "string",
                "description": "新记忆的类型，例如 'ai_note', 'user_preference', 'task_insight'"
            },
            "scene": {
                "type": "string",
                "description": "新记忆的场景标签"
            },
            "rating": {
                "type": "integer",
                "minimum": -1,
                "maximum": 1,
                "default": 0
            },
            "creator": {
                "type": "string",
                "enum": ["AI", "user", "system"],
                "default": "AI"
            }
        },
        "required": ["memory_id", "content"]
    }

    def _get_current_user_id(self) -> str:
        return "default_user"

    async def _execute_async(self, **kwargs) -> dict:
        from core.memory.memory_manager import MemoryManager

        user_id = self._get_current_user_id()
        memory_id = kwargs.get("memory_id")
        content = kwargs.get("content")

        if not memory_id or not content:
            return format_error(INVALID_PARAMS, detail="memory_id 和 content 不能为空")

        mm = MemoryManager()

        try:
            new_mem_id = await mm.replace_memory(
                user_id=user_id,
                old_mem_id=memory_id,
                new_content=content,
                layer=kwargs.get("layer", "short"),
                mem_type=kwargs.get("mem_type", "ai_note"),
                scene=kwargs.get("scene", ""),
                rating=kwargs.get("rating", 0),
                creator=kwargs.get("creator", "AI"),
            )
            return {
                "success": True,
                "message": f"记忆已替换: {memory_id} → {new_mem_id[:8]}...",
                "old_memory_id": memory_id,
                "new_memory_id": new_mem_id,
            }
        except ValueError as e:
            return {
                "success": False,
                "error_code": "MEMORY_REPLACE_FAILED",
                "user_message": str(e),
                "data": None
            }
        except Exception as e:
            logger.error(f"[MemoryReplace] 替换记忆失败: {e}", exc_info=True)
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
