#!/usr/bin/env python3
"""
记忆删除工具 - 删除指定的记忆
"""
from core.base_tool import BaseTool
from core.logger import logger
from core.permission_utils import check_memory_permission


class MemoryDelete(BaseTool):
    """
    删除指定的记忆
    """
    tool_id = "memory_delete"
    name = "删除记忆"
    description = "删除指定的记忆。当你确定某条记忆不再需要时使用。"
    input_schema = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "要删除的记忆ID"
            },
            "deleter": {
                "type": "string",
                "enum": ["AI", "user", "system"],
                "description": "删除者身份，用于权限检查",
                "default": "AI"
            }
        },
        "required": ["memory_id"]
    }

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        return "default_user"

    async def _execute_async(self, **kwargs) -> dict:
        """Phase 8 TRUE_ASYNC: 直接调用 MemoryService，零线程池"""
        from core.memory.memory_service import get_memory_service

        self._get_current_user_id()
        ms = await get_memory_service()

        memory_id = kwargs.get("memory_id")
        deleter = kwargs.get("deleter", "AI")  # 默认为AI删除

        if not memory_id:
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "user_message": "记忆ID不能为空",
                "data": None
            }

        try:
            # TRUE_ASYNC: 直接 await 查询记忆
            mem = await ms.get_memory_by_id(memory_id)
            if not mem:
                return {
                    "success": False,
                    "error_code": "MEMORY_NOT_FOUND",
                    "user_message": f"记忆 {memory_id} 不存在",
                    "data": None
                }

            # 权限检查：AI只能删除自己创建的记忆
            if deleter == "AI":
                allowed, msg = check_memory_permission(mem, deleter, "删除")
                if not allowed:
                    logger.warning(f"[MemoryDelete] 权限拒绝：{msg}")
                    return {
                        "success": False,
                        "error_code": "PERMISSION_DENIED",
                        "user_message": msg,
                        "data": None
                    }

            # TRUE_ASYNC: 直接 await 删除
            success = await ms.delete_memory(memory_id)

            if success:
                logger.info(f"[MemoryDelete] 删除记忆 {memory_id}")
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"记忆 {memory_id[:8]}... 已删除",
                    "data": {"deleted_id": memory_id}
                }
            else:
                return {
                    "success": False,
                    "error_code": "DELETE_FAILED",
                    "user_message": "删除失败，请稍后重试",
                    "data": None
                }

        except Exception as e:
            logger.error(f"[MemoryDelete] 删除失败: {e}")
            return {
                "success": False,
                "error_code": "DELETE_ERROR",
                "user_message": f"删除失败: {str(e)}",
                "data": None
            }

    def _get_current_user_id(self) -> str:
        """获取当前用户ID"""
        return "default_user"
