#!/usr/bin/env python3
"""
记忆列表工具 - 列出记忆，支持过滤和分页
"""
from core.base_tool import BaseTool
from core.logger import logger


class MemoryList(BaseTool):
    """
    列出记忆，支持过滤和分页
    """
    tool_id = "memory_list"
    name = "列出记忆"
    description = "列出记忆库中的记录，支持按层级、类型、综合评分筛选和分页。"
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "enum": ["short", "medium", "evolve"],
                "description": "过滤特定层级（可选）"
            },
            "mem_type": {
                "type": "string",
                "description": "过滤特定类型（可选）"
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "返回数量"
            },
            "offset": {
                "type": "integer",
                "default": 0,
                "description": "偏移量（分页）"
            },
            "min_rating": {
                "type": "integer",
                "description": "最低评分过滤（可选）"
            },
            "min_overall_score": {
                "type": "number",
                "minimum": 1.0,
                "maximum": 5.0,
                "description": "最低综合评分过滤（1-5分，可选）"
            }
        }
    }

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        return "default_user"

    async def _execute_async(self, **kwargs) -> dict:
        """Phase 8 TRUE_ASYNC: 直接调用 MemoryService，零线程池"""
        from core.memory.memory_service import get_memory_service

        user_id = self._get_current_user_id()
        ms = await get_memory_service()

        layer = kwargs.get("layer")
        mem_type = kwargs.get("mem_type")
        limit = kwargs.get("limit", 20)
        offset = kwargs.get("offset", 0)
        min_rating = kwargs.get("min_rating")
        min_overall_score = kwargs.get("min_overall_score")

        try:
            # 构建过滤字典（与 AsyncMemory.get 语义对齐）
            filter_dict: dict = {}
            if min_overall_score:
                filter_dict["min_overall_score"] = min_overall_score

            # TRUE_ASYNC: 直接 await MemoryService.query_memories()
            # 多取 limit+offset 条用于前端分页过滤
            all_memories = await ms.query_memories(
                user_id=user_id,
                layer=layer,
                mem_type=mem_type,
                limit=limit + offset,
                min_rating=min_rating or -1,
                filter_dict=filter_dict or None,
            )

            # 手动分页（与同步版行为一致）
            memories = all_memories[offset:offset + limit]

            # 格式化结果
            formatted = []
            for mem in memories:
                va = mem.get('value_assessment', {})
                formatted.append({
                    "id": mem.get('id', 'unknown'),
                    "content": mem.get('content', '')[:100] + "..." if len(mem.get('content', '')) > 100 else mem.get('content', ''),
                    "layer": mem.get('layer', 'unknown'),
                    "mem_type": mem.get('mem_type', 'unknown'),
                    "rating": mem.get('rating', 0),
                    "overall_score": va.get('overall', 0),
                    "grade": va.get('grade', 'C'),
                    "created_at": mem.get('created_at', '')
                })

            return {
                "success": True,
                "error_code": None,
                "user_message": f"共 {len(formatted)} 条记忆（总计 {len(all_memories)} 条）",
                "data": {
                    "count": len(formatted),
                    "total": len(all_memories),
                    "offset": offset,
                    "limit": limit,
                    "memories": formatted
                }
            }

        except Exception as e:
            logger.error(f"[MemoryList] 列表获取失败: {e}")
            return {
                "success": False,
                "error_code": "LIST_ERROR",
                "user_message": f"获取列表失败: {str(e)}",
                "data": None
            }

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        return "default_user"
