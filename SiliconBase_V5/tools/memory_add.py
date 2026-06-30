#!/usr/bin/env python3
"""
原子工具：添加记忆（增强版，支持AI主动写入，含去重检查）
2026-03-11 修复：将run改为_execute，异常处理交由基类统一处理
"""
from core.base_tool import BaseTool
from core.logger import logger
from core.memory.vector_memory_compat import vector_memory


class MemoryAdd(BaseTool):
    tool_id = "memory_add"
    name = "添加记忆"
    description = "向记忆库添加一条记录。可用于保存重要信息、笔记、用户偏好、技巧等。如果内容重复，将返回已有记忆ID而不新增。"
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "enum": ["short", "medium", "evolve"],
                "description": "记忆层：short（短期）、medium（中期）、evolve（长期进化）"
            },
            "mem_type": {
                "type": "string",
                "description": "记忆类型，例如 'ai_note', 'user_preference', 'task_insight'"
            },
            "content": {"type": "string", "description": "记忆内容"},
            "scene": {"type": "string", "description": "场景标签，用于检索，如'打开应用'"},
            "rating": {"type": "integer", "minimum": -1, "maximum": 1, "default": 0},
            "expire_days": {"type": "integer", "minimum": 1, "description": "过期天数，默认永久"},
            "value_assessment": {
                "type": "object",
                "description": "六维评分（可选），用于评估记忆价值",
                "properties": {
                    "emotional_temperature": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "ethical_safety": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "self_growth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "execution_effectiveness": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "sustainability": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "inspiration_innovation": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3}
                }
            },
            "creator": {
                "type": "string",
                "enum": ["AI", "user", "system"],
                "description": "记忆创建者，AI添加的记忆标记为'AI'，用户添加的标记为'user'，系统添加的标记为'system'",
                "default": "AI"
            }
        },
        "required": ["layer", "mem_type", "content"]
    }

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)

    # ───────────────────────────────────────────────────────────────
    # Phase 4/5 衔接：原生 async 执行入口——【P1修复】使用新 MemoryManager
    # ───────────────────────────────────────────────────────────────
    async def _execute_async(self, **kwargs) -> dict:
        """异步添加记忆 - 使用 MemoryService，不再依赖旧模块"""
        import asyncio

        from core.memory.memory_service import get_memory_service

        # 获取参数（与同步版一致）
        layer = kwargs["layer"]
        mem_type = kwargs["mem_type"]
        content = kwargs["content"]
        scene = kwargs.get("scene", "")
        rating = kwargs.get("rating", 0)
        expire_days = kwargs.get("expire_days")
        value_assessment = kwargs.get("value_assessment")
        creator = kwargs.get("creator", "AI")

        ms = await get_memory_service()

        # 去重检查
        try:
            recent = await ms.query_memories(
                user_id="default",
                layer=layer,
                mem_type=mem_type,
                limit=100,
            )
            for mem in recent:
                if mem.get("content") == content:
                    logger.info(f"[MemoryAdd] 检测到重复记忆，返回已有ID: {mem['id']}")
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": "记忆内容已存在，未重复添加",
                        "data": {"memory_id": mem['id'], "duplicate": True}
                    }
        except Exception as e:
            logger.warning(f"[MemoryAdd] 去重检查失败，将继续添加: {e}")

        # 处理六维评分（纯逻辑，与同步版一致）
        if value_assessment:
            required_dims = [
                "emotional_temperature", "ethical_safety", "self_growth",
                "execution_effectiveness", "sustainability", "inspiration_innovation"
            ]
            for dim in required_dims:
                if dim not in value_assessment:
                    value_assessment[dim] = 3
            logger.debug(f"[MemoryAdd] 使用自定义六维评分: {value_assessment}")

        # 异步写入 PostgreSQL
        mem_id = await ms.add_memory(
            user_id="default",
            content={"text": content},
            memory_type=mem_type,
            layer=layer,
            scene=scene,
            rating=rating,
            expire_days=expire_days,
            value_assessment=value_assessment,
            creator=creator,
            source="ai",
        )

        # 向量同步（vector_memory 尚未 async 化，通过 run_in_executor 桥接）
        if mem_type in ["ai_note", "user_preference"]:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: vector_memory._chat_collection.add(
                        documents=[content],
                        metadatas=[{"mem_id": mem_id, "source": "ai_added"}],
                        ids=[mem_id]
                    )
                )
            except Exception as e:
                logger.warning(f"[MemoryAdd] 向量库同步失败: {e}")

        logger.info(f"[MemoryAdd] AI通过工具添加记忆，ID: {mem_id}")
        return {
            "success": True,
            "error_code": None,
            "user_message": f"记忆添加成功，ID: {mem_id}",
            "data": {"memory_id": mem_id}
        }
