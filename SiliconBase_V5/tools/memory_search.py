#!/usr/bin/env python3
"""
记忆搜索工具 - 语义搜索记忆库，支持按维度加权排序
"""

from core.base_tool import BaseTool
from core.logger import logger
from core.memory.memory_service import get_memory_service


class MemorySearch(BaseTool):
    """
    语义搜索记忆库，返回相关记忆
    支持按维度加权排序

    【云端+本地双版本管控】
    - owner: system (系统内置工具)
    - 在云端模式下正常可用
    - 替代已废弃的 recall_memory 工具
    """
    tool_id = "memory_search"
    tool_owner = "system"  # 系统内置工具
    name = "搜索记忆"
    description = "语义搜索记忆库，支持按维度加权排序。当你需要查找特定主题的经验或知识时使用。"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题"
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "description": "返回结果数量"
            },
            "layer": {
                "type": "string",
                "enum": ["short", "medium", "evolve"],
                "description": "过滤特定层级（可选）"
            },
            "mem_type": {
                "type": "string",
                "description": "过滤特定类型（可选）"
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
            },
            "dimension_weights": {
                "type": "object",
                "description": "维度权重配置（可选），用于加权排序",
                "properties": {
                    "emotional_temperature": {"type": "number", "minimum": 0, "maximum": 1},
                    "ethical_safety": {"type": "number", "minimum": 0, "maximum": 1},
                    "self_growth": {"type": "number", "minimum": 0, "maximum": 1},
                    "execution_effectiveness": {"type": "number", "minimum": 0, "maximum": 1},
                    "sustainability": {"type": "number", "minimum": 0, "maximum": 1},
                    "inspiration_innovation": {"type": "number", "minimum": 0, "maximum": 1}
                }
            }
        },
        "required": ["query"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        query = kwargs.get("query")
        limit = kwargs.get("limit", 5)
        kwargs.get("layer")
        kwargs.get("mem_type")
        min_rating = kwargs.get("min_rating")
        min_overall_score = kwargs.get("min_overall_score")
        dimension_weights = kwargs.get("dimension_weights")

        if not query:
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "user_message": "搜索关键词不能为空",
                "data": None
            }

        try:
            # 获取当前用户ID
            user_id = self._get_current_user_id()

            # Phase 8: 使用 MemoryService 原生 async 接口
            ms = await get_memory_service()
            results = await ms.retrieve_memories(
                user_id=user_id,
                query=query,
                limit=limit * 3,
            )

            # 2. 筛选和格式化
            memories = []
            for mem in results:
                # 评分过滤
                rating = mem.get('rating', 0)
                if min_rating and rating < min_rating:
                    continue

                # 最低综合评分过滤
                if min_overall_score:
                    overall = mem.get('value_assessment', {}).get('overall', 0)
                    if overall < min_overall_score:
                        continue

                memories.append({
                    "id": mem.get('id', ''),
                    "content": str(mem.get('content', ''))[:200],
                    "layer": mem.get('layer', 'unknown'),
                    "mem_type": mem.get('mem_type', 'unknown'),
                    "rating": rating,
                    "value_assessment": mem.get('value_assessment', {}),
                    "similarity": mem.get('similarity', 0.0),
                    "created_at": mem.get('created_at', '')
                })

            # 3. 按维度权重排序（如果提供了权重）
            if dimension_weights:
                memories = self._sort_by_dimension_weights(memories, dimension_weights)
            else:
                # 按相似度和评分排序
                memories.sort(key=lambda x: (x['similarity'] * 0.7 + x['rating'] / 10 * 0.3), reverse=True)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"找到 {len(memories[:limit])} 条相关记忆",
                "data": {
                    "query": query,
                    "count": len(memories[:limit]),
                    "memories": memories[:limit]
                }
            }

        except Exception as e:
            logger.error(f"[MemorySearch] 搜索失败: {e}")
            return {
                "success": False,
                "error_code": "SEARCH_ERROR",
                "user_message": f"搜索失败: {str(e)}",
                "data": None
            }

    def _sort_by_dimension_weights(self, memories: list, weights: dict[str, float]) -> list:
        """按维度权重排序记忆"""
        def get_weighted_score(mem):
            va = mem.get('value_assessment', {})
            if not va:
                return 0

            score = 0
            total_weight = 0
            for dim, weight in weights.items():
                dim_score = va.get(dim, 3)
                score += dim_score * weight
                total_weight += weight

            if total_weight > 0:
                score = score / total_weight

            # 结合相似度和加权评分
            similarity = mem.get('similarity', 0)
            return similarity * 0.5 + (score / 5) * 0.5

        memories.sort(key=get_weighted_score, reverse=True)
        return memories

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        # 简化实现，实际应从上下文获取
        return "default_user"
