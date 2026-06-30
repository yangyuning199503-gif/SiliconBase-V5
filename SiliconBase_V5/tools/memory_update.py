#!/usr/bin/env python3
"""
原子工具：更新记忆（AI 可以修改自己之前写的记忆）
"""
from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger
from core.permission_utils import check_memory_permission


class MemoryUpdate(BaseTool):
    tool_id = "memory_update"
    name = "更新记忆"
    description = "更新记忆库中已有的记录。当你发现之前的经验需要修正或补充时使用。"
    input_schema = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "要更新的记忆 ID，可通过 recall_memory 查询获得"
            },
            "content": {
                "type": "string",
                "description": "新的记忆内容"
            },
            "scene": {
                "type": "string",
                "description": "新的场景标签（可选，不填则保持原样）"
            },
            "rating": {
                "type": "integer",
                "minimum": -1,
                "maximum": 1,
                "description": "新的评分 -1=负面 0=中性 1=正面（可选）"
            },
            "value_assessment": {
                "type": "object",
                "description": "更新六维评分（可选）",
                "properties": {
                    "emotional_temperature": {"type": "integer", "minimum": 1, "maximum": 5},
                    "ethical_safety": {"type": "integer", "minimum": 1, "maximum": 5},
                    "self_growth": {"type": "integer", "minimum": 1, "maximum": 5},
                    "execution_effectiveness": {"type": "integer", "minimum": 1, "maximum": 5},
                    "sustainability": {"type": "integer", "minimum": 1, "maximum": 5},
                    "inspiration_innovation": {"type": "integer", "minimum": 1, "maximum": 5}
                }
            },
            "updater": {
                "type": "string",
                "enum": ["AI", "user", "system"],
                "description": "更新者身份，用于权限检查",
                "default": "AI"
            }
        },
        "required": ["memory_id", "content"]
    }

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        return "default_user"

    async def _execute_async(self, **kwargs):
        """Phase 8 TRUE_ASYNC: 直接调用 MemoryService，零线程池"""
        from core.memory.memory_service import get_memory_service

        self._get_current_user_id()
        ms = await get_memory_service()

        memory_id = kwargs.get("memory_id")
        content = kwargs.get("content")
        scene = kwargs.get("scene")
        rating = kwargs.get("rating")
        value_assessment = kwargs.get("value_assessment")
        updater = kwargs.get("updater", "AI")  # 默认为AI更新

        if not memory_id or not content:
            return format_error(INVALID_PARAMS, detail="memory_id 和 content 不能为空")

        try:
            # TRUE_ASYNC: 直接 await 查询原记忆
            old_mem = await ms.get_memory_by_id(memory_id)

            # 权限检查：AI只能修改自己创建的记忆
            if old_mem and updater == "AI":
                allowed, msg = check_memory_permission(old_mem, updater, "修改")
                if not allowed:
                    logger.warning(f"[MemoryUpdate] 权限拒绝：{msg}")
                    return format_error(TOOL_EXECUTION_ERROR, detail=msg)

            # 构建更新数据
            updates = {"content": content}
            if scene is not None:
                updates["scene"] = scene
            if rating is not None:
                updates["rating"] = rating
            if value_assessment is not None:
                # 验证六维评分格式，填充缺失维度
                required_dims = [
                    "emotional_temperature", "ethical_safety", "self_growth",
                    "execution_effectiveness", "sustainability", "inspiration_innovation"
                ]
                for dim in required_dims:
                    if dim not in value_assessment:
                        value_assessment[dim] = 3  # 默认值
                updates["value_assessment"] = value_assessment
                logger.debug(f"更新六维评分: {value_assessment}")

            # TRUE_ASYNC: 直接 await 更新
            success = await ms.update_memory(memory_id, updates)

            if success:
                logger.info(f"AI更新记忆成功，ID: {memory_id}")
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"记忆已更新: {content[:50]}...",
                    "data": {"memory_id": memory_id, "updated": True}
                }
            else:
                return format_error(TOOL_EXECUTION_ERROR, detail="记忆更新失败，可能ID不存在")

        except Exception as e:
            logger.error(f"更新记忆失败: {e}")
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
